"""Chat orchestration: parse intent, apply policy, call the same services the HTTP API uses."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError
from sqlmodel import Session, col, select

from app.core import Settings
from app.domain.chat_models import ChatMessage, ChatRequest, ChatResponse, Conversation
from app.domain.models import (
    ActionProposal,
    ContactCreate,
    GoalCreate,
    Integration,
    ProjectCreate,
    TaskCreate,
    now,
)
from app.errors import DomainError, NotFound
from app.services import approvals, records, tools
from app.services import intents as I
from app.services import planner as P
from app.services.ai import ModelRouter
from app.services.audit import VIA, record_event
from app.services.briefing import build_briefing, render_briefing_text
from app.services.context import Ctx
from app.services.llm import LLMError
from app.services.model_pool import ModelPool, NoModelAvailable
from app.services.policy import PolicyEngine, external_action_types

log = logging.getLogger("bma.chat")
HISTORY_TURNS = 8
SNAPSHOT_CHARS = 1200
FALLBACK_NOTE = "\n(The assistant model was unavailable, so this was handled with built-in commands.)"

HELP_TEXT = (
    "Commands I understand:\n"
    "- brief me\n"
    "- create goal|project|task|contact: ... (tasks accept 'by 2026-11-01', 'due tomorrow', 'high priority', 'in project X')\n"
    "- complete task: ...\n"
    "- list goals|tasks|projects|contacts|approvals (optionally open, overdue, pending)\n"
    "- find ...\n"
    "- anything that sends, publishes, pays, signs, deletes or launches becomes an approval request."
)
DEFAULT_SUGGESTIONS = ["brief me", "create task: ", "list tasks"]


class Reply:
    def __init__(self, text: str, intent: str, *, actions: list[dict[str, Any]] | None = None, approval_id: str | None = None,
                 approval_required: bool = False, suggestions: list[str] | None = None, via: str = "rules") -> None:
        self.text = text
        self.intent = intent
        self.actions = actions or []
        self.approval_id = approval_id
        self.approval_required = approval_required
        self.suggestions = suggestions if suggestions is not None else DEFAULT_SUGGESTIONS
        self.via = via


_fmt_due = tools._fmt_due


class BusinessChat:
    def __init__(self, router: ModelRouter, policy: PolicyEngine, settings: Settings, connectors: Any, pool: ModelPool | None = None, notifier: Any = None) -> None:
        self.router = router
        self.policy = policy
        self.settings = settings
        self.connectors = connectors
        self.pool = pool
        self.notifier = notifier

    # ------------------------------------------------------------ entry point

    def respond(self, session: Session, request: ChatRequest, ctx: Ctx) -> ChatResponse:
        conversation = self._conversation(session, request.conversation_id, request.message, ctx)
        self._save(session, conversation.id, "user", request.message)
        session.commit()

        intent = I.parse(request.message)
        reply: Reply | None = None
        attempted_llm = False
        if self._use_planner(intent):
            reply, attempted_llm = self._plan_and_run(session, request.message, conversation, intent, ctx)
        if reply is None:
            try:
                reply = self._dispatch(session, intent, request.message, conversation, ctx)
            except (DomainError, ValidationError) as exc:
                session.rollback()
                message = exc.message if isinstance(exc, DomainError) else "; ".join(e["msg"] for e in exc.errors())
                reply = Reply(f"I could not do that: {message}", "error")
            if attempted_llm:
                reply.text += FALLBACK_NOTE

        agent = self.router.agent_for_intent(intent.name) if reply.via == "rules" else None
        self._save(session, conversation.id, "assistant", reply.text, {"intent": reply.intent, "actions": reply.actions})
        conversation.updated_at = now()
        session.add(conversation)
        session.commit()
        return ChatResponse(
            conversation_id=conversation.id,
            message=reply.text,
            intent=reply.intent,
            handled_by=agent.name if agent else None,
            actions=reply.actions,
            approval_required=reply.approval_required,
            approval_id=reply.approval_id,
            suggestions=reply.suggestions,
            via=reply.via,
        )

    # ------------------------------------------------------------ helpers

    def _use_planner(self, intent: I.Intent) -> bool:
        mode = self.settings.effective_assistant_mode
        if self.pool is None or mode == "rules" or intent.name == I.HELP:
            return False
        if mode == "llm":
            return True
        # hybrid: deterministic commands stay deterministic; open-ended, growth and external requests go to the model
        return intent.name in {I.PROTECTED, I.SEO, I.ADVERTISING, I.OTHER}

    def _snapshot(self, session: Session) -> str:
        return render_briefing_text(build_briefing(session, self.settings.environment))[:SNAPSHOT_CHARS]

    def _history(self, session: Session, conversation_id: str, current: str) -> list[tuple[str, str]]:
        rows = session.exec(select(ChatMessage).where(col(ChatMessage.conversation_id) == conversation_id).order_by(col(ChatMessage.id).desc()).limit(HISTORY_TURNS + 1)).all()
        turns = [(m.role, m.content) for m in reversed(rows)]
        if turns and turns[-1] == ("user", current):
            turns.pop()  # the message being planned is passed separately
        return turns

    def _plan_and_run(self, session: Session, text: str, conversation: Conversation, intent: I.Intent, ctx: Ctx) -> tuple[Reply | None, bool]:
        """Models plan, validated tools execute. Returns ``(reply, attempted)``; reply None means the rules should answer."""
        assert self.pool is not None
        system = P.build_system_prompt(now(), self._snapshot(session), external_action_types())
        messages = P.build_messages(self._history(session, conversation.id, text), text)

        def check(raw: str) -> tuple[bool, P.PlanParse, str | None]:
            parsed = P.parse_plan(raw)
            return parsed.ok, parsed, parsed.error

        try:
            result = self.pool.complete_checked("plan", system, messages, check, P.repair_messages)
        except NoModelAvailable:
            return None, False  # nothing reachable: rules answer without a warning
        except LLMError as exc:
            log.warning("planner unavailable: %s", exc)
            return None, True
        parsed: P.PlanParse = result.parsed
        usage = dict(result.usage)

        rule_action = None
        if intent.name == I.PROTECTED and intent.action_type:
            rule_action = {"action_type": intent.action_type, **{k: v for k, v in intent.entities.items() if k in {"target", "summary", "amount"}}}
        steps, injected = P.ensure_proposal(parsed.steps, rule_action)
        if not steps:
            if not parsed.reply:
                return None, True
            self._audit_plan(session, conversation, ctx, result, steps, [], injected, usage)
            return Reply(parsed.reply, "llm_reply", via="llm"), True

        env = tools.ToolEnv(self.policy, self.settings, conversation.id, self.notifier)
        token = VIA.set(f"llm:{result.model}")
        try:
            results = [tools.run_step(session, step, ctx, env) for step in steps]
        finally:
            VIA.reset(token)
        try:
            composed = self.pool.complete("compose", P.COMPOSE_SYSTEM, P.build_compose_messages(text, results), prefer_key=result.key)
            message = composed.text
            for name, value in composed.usage.items():
                usage[name] = usage.get(name, 0) + value
        except LLMError:
            message = P.render_results_fallback(results)
        if injected:
            message += "\nA protected action was detected in your request, so it was queued for approval."
        self._audit_plan(session, conversation, ctx, result, steps, results, injected, usage)
        approval = next((r for r in results if r.get("ok") and r.get("approval_id")), None)
        return (
            Reply(
                message,
                "llm_plan",
                actions=[r["action"] for r in results if r.get("ok") and "action" in r],
                approval_id=approval["approval_id"] if approval else None,
                approval_required=approval is not None,
                suggestions=["brief me", "list approvals", "list tasks"],
                via="llm",
            ),
            True,
        )

    def _audit_plan(self, session: Session, conversation: Conversation, ctx: Ctx, result: Any, steps: Any, results: list[dict[str, Any]], injected: bool, usage: dict[str, int]) -> None:
        record_event(
            session,
            "assistant.planned",
            ctx.actor,
            conversation.id,
            {
                "model": result.model, "endpoint": result.endpoint, "mode": self.settings.effective_assistant_mode,
                "attempts": [{"model": a.model, "ok": a.ok, "reason": a.reason} for a in result.attempts],
                "tools": [s.tool for s in steps], "failed": [r["tool"] for r in results if not r.get("ok")],
                "safety_net_injected": injected, "usage": usage,
            },
            ctx.request_id,
        )
        session.commit()

    @staticmethod
    def _conversation(session: Session, conversation_id: str | None, first_message: str, ctx: Ctx) -> Conversation:
        if conversation_id:
            found = session.get(Conversation, conversation_id)
            if found is None:
                raise NotFound("Conversation not found")
            return found
        conversation = Conversation(title=first_message[:80], created_by=ctx.actor)
        session.add(conversation)
        session.commit()
        session.refresh(conversation)
        return conversation

    @staticmethod
    def _save(session: Session, conversation_id: str, role: str, content: str, extra: dict[str, Any] | None = None) -> ChatMessage:
        message = ChatMessage(conversation_id=conversation_id, role=role, content=content, extra_data=extra or {})
        session.add(message)
        session.flush()
        return message

    def _dispatch(self, session: Session, intent: I.Intent, text: str, conversation: Conversation, ctx: Ctx) -> Reply:
        handlers = {
            I.BRIEFING: lambda: self._briefing(session),
            I.HELP: lambda: Reply(HELP_TEXT, "help"),
            I.CLARIFY: lambda: Reply(f"What should the {intent.entities['for']} {intent.entities['missing']} be?", "clarify", suggestions=[f"create {intent.entities['for']}: "]),
            I.CREATE_GOAL: lambda: self._create_goal(session, intent, ctx),
            I.CREATE_PROJECT: lambda: self._create_project(session, intent, ctx),
            I.CREATE_TASK: lambda: self._create_task(session, intent, ctx),
            I.CREATE_CONTACT: lambda: self._create_contact(session, intent, ctx),
            I.COMPLETE_TASK: lambda: self._complete_task(session, intent, ctx),
            I.LIST: lambda: self._list(session, intent),
            I.SEARCH: lambda: self._search(session, intent),
            I.PROTECTED: lambda: self._protected(session, intent, text, conversation, ctx),
            I.SEO: lambda: self._growth(session, I.SEO, text),
            I.ADVERTISING: lambda: self._growth(session, I.ADVERTISING, text),
        }
        handler = handlers.get(intent.name)
        if handler is not None:
            return handler()
        plan = self.router.plan(text)
        return Reply(
            "I could not map that to a command. Say 'help' to see what I can do, or phrase it as "
            f"'create task: ...'. Routing note: {plan['rationale']}.",
            "general_business_request",
        )

    # ------------------------------------------------------------ handlers

    def _briefing(self, session: Session) -> Reply:
        briefing = build_briefing(session, self.settings.environment)
        return Reply(render_briefing_text(briefing), "business_briefing", suggestions=["list tasks", "list approvals", "create task: "])

    def _create_goal(self, session: Session, intent: I.Intent, ctx: Ctx) -> Reply:
        goal = records.create_goal(session, GoalCreate(title=intent.entities["title"], target_date=intent.entities.get("target_date")), ctx)
        when = f" (target {goal.target_date.date().isoformat()})" if goal.target_date else ""
        return Reply(f"Created goal: {goal.title}{when}", "create_goal", actions=[{"type": "goal.created", "id": goal.id, "title": goal.title}],
                     suggestions=[f"create project: {goal.title[:40]}", "list goals"])

    def _create_project(self, session: Session, intent: I.Intent, ctx: Ctx) -> Reply:
        project = records.create_project(session, ProjectCreate(name=intent.entities["name"]), ctx)
        return Reply(f"Created project: {project.name}", "create_project", actions=[{"type": "project.created", "id": project.id, "name": project.name}],
                     suggestions=[f"create task: first step in project {project.name}", "list projects"])

    def _create_task(self, session: Session, intent: I.Intent, ctx: Ctx) -> Reply:
        e = intent.entities
        project = records.find_project_by_name(session, e["project_name"]) if e.get("project_name") else None
        task = records.create_task(
            session,
            TaskCreate(title=e["title"], priority=e["priority"], due_at=e.get("due_at"), project_id=project.id if project else None),
            ctx,
        )
        note = ""
        if e.get("project_name"):
            note = f" in project {project.name}" if project else f" (no project named '{e['project_name']}', so it is unassigned)"
        return Reply(f"Created task: {task.title} [{task.priority}{_fmt_due(task.due_at)}]{note}", "create_task",
                     actions=[{"type": "task.created", "id": task.id, "title": task.title}], suggestions=["list tasks", f"complete task: {task.title[:40]}"])

    def _create_contact(self, session: Session, intent: I.Intent, ctx: Ctx) -> Reply:
        e = intent.entities
        contact = records.create_contact(session, ContactCreate(name=e["name"], email=e.get("email"), organisation=e.get("organisation", "")), ctx)
        return Reply(f"Created contact: {contact.name}", "create_contact", actions=[{"type": "contact.created", "id": contact.id, "name": contact.name}])

    def _complete_task(self, session: Session, intent: I.Intent, ctx: Ctx) -> Reply:
        query = intent.entities["query"]
        matches = records.find_open_tasks(session, query)
        if not matches:
            return Reply(f"No open task matches '{query}'.", "complete_task", suggestions=["list tasks", f"create task: {query}"])
        if len(matches) > 1:
            names = "\n".join(f"- {t.title}" for t in matches[:5])
            return Reply(f"More than one open task matches '{query}'. Be more specific:\n{names}", "complete_task", suggestions=[f"complete task: {t.title}" for t in matches[:3]])
        task = records.complete_task(session, matches[0].id, ctx)
        return Reply(f"Marked done: {task.title}", "complete_task", actions=[{"type": "task.completed", "id": task.id, "title": task.title}], suggestions=["brief me", "list tasks"])

    def _list(self, session: Session, intent: I.Intent) -> Reply:
        entity, scope = intent.entities["entity"], intent.entities.get("scope")
        rows = tools.list_rows(session, entity, scope)
        if entity == "integrations":
            rows = [f"{i.name} [{i.health}]" for i in session.exec(select(Integration).order_by(col(Integration.name)).limit(20)).all()]
        if not rows:
            return Reply(f"No {entity} to show. You can create one here.", f"list_{entity}")
        return Reply(f"{entity.capitalize()}:\n" + "\n".join(f"- {row}" for row in rows), f"list_{entity}")

    def _search(self, session: Session, intent: I.Intent) -> Reply:
        found = records.search(session, intent.entities["query"], limit=5)
        lines = [f"- {kind[:-1]}: {item['title']} [{item['status']}]" for kind, items in found.items() for item in items]
        if not lines:
            return Reply(f"Nothing matches '{intent.entities['query']}'.", "search")
        return Reply("Matches:\n" + "\n".join(lines), "search")

    def _protected(self, session: Session, intent: I.Intent, text: str, conversation: Conversation, ctx: Ctx) -> Reply:
        e = intent.entities
        payload = {"request": e.get("summary", text[:300]), "on_behalf_of": ctx.actor}
        if "amount" in e:
            payload["amount"] = e["amount"]
        proposal = ActionProposal(action_type=intent.action_type or "unclassified.external", target=e.get("target", "unspecified"), payload=payload,
                                  reason=f"Requested in chat: {text[:200]}")
        item, decision, _ = approvals.propose(session, proposal, ctx, self.policy, self.settings, origin="assistant", conversation_id=conversation.id, requested_by="assistant", notifier=self.notifier)
        why = decision.reasons[-1] if decision.reasons else ""
        return Reply(
            f"Nothing was sent or changed. I queued {item.action_type} ({item.risk} risk) for approval: {why}.\nReview the exact payload in the approval queue (request {item.id[:8]}).",
            "protected_action",
            actions=[{"type": "approval.requested", "id": item.id, "action_type": item.action_type, "risk": item.risk}],
            approval_id=item.id,
            approval_required=decision.requires_approval,
            suggestions=["list approvals", "brief me"],
        )

    def _growth(self, session: Session, capability: str, text: str) -> Reply:
        plan = self.router.plan(text, capability)
        wanted = plan["required_integrations"]
        health = {i.name: i.health for i in session.exec(select(Integration).where(col(Integration.name).in_(wanted))).all()}
        lines = "\n".join(f"- {name}: {health.get(name, 'unknown')}" for name in wanted)
        return Reply(
            f"{'SEO' if capability == I.SEO else 'Advertising'} plan (sandbox, route {plan['route']}; tools {', '.join(plan['tools'])}).\n"
            f"Connectors needed:\n{lines}\nNothing is published or spent without approval.",
            f"{capability}_request",
            actions=[{"type": "manager.plan", "capability": capability, "tools": plan["tools"]}],
            suggestions=[f"create project: {capability} plan", "list approvals"],
        )
