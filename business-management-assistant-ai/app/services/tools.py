"""Executes validated planner steps through the same services as the HTTP API.

Tools resolve records by name (never by model-supplied ids), return structured results, and turn
domain errors into result objects so one failed step cannot abort the others.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlmodel import Session, col, select

from app.core import Settings
from app.domain.models import (
    ActionProposal,
    ApprovalRequest,
    ApprovalStatus,
    Contact,
    ContactCreate,
    Goal,
    GoalCreate,
    Project,
    ProjectCreate,
    Status,
    Task,
    TaskCreate,
    TaskUpdate,
    now,
)
from app.errors import DomainError, Invalid
from app.services import approvals, records
from app.services.briefing import build_briefing, render_briefing_text
from app.services.context import Ctx
from app.services.planner import PROPOSE, SPEC_BY_NAME, Step
from app.services.policy import PolicyEngine, external_action_types


@dataclass(frozen=True)
class ToolEnv:
    policy: PolicyEngine
    settings: Settings
    conversation_id: str | None = None
    notifier: Any = None


def _fmt_due(moment: Any) -> str:
    return f", due {moment.date().isoformat()}" if moment else ""


def list_rows(session: Session, entity: str, scope: str | None = None, limit: int = 20) -> list[str]:
    if entity == "tasks":
        query = select(Task).order_by(col(Task.created_at).desc())
        if scope == "open":
            query = query.where(col(Task.status) != Status.done.value)
        elif scope == "overdue":
            query = query.where(col(Task.status) != Status.done.value, col(Task.due_at) < now())
        elif scope in {"blocked", "active", "done"}:
            query = query.where(col(Task.status) == scope)
        return [f"{t.title} [{t.status}, {t.priority}{_fmt_due(t.due_at)}]" for t in session.exec(query.limit(limit)).all()]
    if entity == "goals":
        return [f"{g.title} [{g.status}]" for g in session.exec(select(Goal).order_by(col(Goal.created_at).desc()).limit(limit)).all()]
    if entity == "projects":
        return [f"{p.name} [{p.status}]" for p in session.exec(select(Project).order_by(col(Project.created_at).desc()).limit(limit)).all()]
    if entity == "contacts":
        return [f"{c.name}{' <' + c.email + '>' if c.email else ''}" for c in session.exec(select(Contact).order_by(col(Contact.created_at).desc()).limit(limit)).all()]
    if entity == "approvals":
        status = ApprovalStatus.pending.value if scope in {None, "pending"} else scope
        query = select(ApprovalRequest).where(col(ApprovalRequest.status) == status).order_by(col(ApprovalRequest.created_at).desc()).limit(limit)
        return [f"{a.action_type} to {a.target} [{a.risk}, {a.status}]" for a in session.exec(query).all()]
    return []


def _one_open_task(session: Session, query: str) -> Task:
    matches = records.find_open_tasks(session, query)
    if not matches:
        raise Invalid(f"no open task matches {query!r}")
    if len(matches) > 1:
        raise Invalid(f"{len(matches)} open tasks match {query!r}: " + "; ".join(t.title for t in matches[:5]))
    return matches[0]


def _project_id(session: Session, name: str | None) -> str | None:
    if not name:
        return None
    project = records.find_project_by_name(session, name)
    if project is None:
        raise Invalid(f"no project titled {name!r}; create it first")
    return project.id


# ---------------------------------------------------------------- handlers: (session, ctx, args, env) -> result dict


def _get_briefing(session: Session, ctx: Ctx, args: dict, env: ToolEnv) -> dict[str, Any]:
    b = build_briefing(session, env.settings.environment)
    return {"summary": render_briefing_text(b), "data": {k: b[k] for k in ("open_tasks", "overdue_tasks", "blocked_tasks", "pending_approvals")}}


def _list_items(session: Session, ctx: Ctx, args: dict, env: ToolEnv) -> dict[str, Any]:
    rows = list_rows(session, args["entity"], args.get("scope"))
    return {"summary": f"{len(rows)} {args['entity']}", "data": rows}


def _search(session: Session, ctx: Ctx, args: dict, env: ToolEnv) -> dict[str, Any]:
    found = records.search(session, args["query"], limit=5)
    return {"summary": f"{sum(len(v) for v in found.values())} matches", "data": found}


def _create_goal(session: Session, ctx: Ctx, args: dict, env: ToolEnv) -> dict[str, Any]:
    goal = records.create_goal(session, GoalCreate(**args), ctx)
    return {"summary": f"created goal {goal.title!r}", "action": {"type": "goal.created", "id": goal.id, "title": goal.title}}


def _create_project(session: Session, ctx: Ctx, args: dict, env: ToolEnv) -> dict[str, Any]:
    fields = dict(args)
    goal_title = fields.pop("goal_title", None)
    goal_id = None
    if goal_title:
        goal = session.exec(select(Goal).where(records.equals(Goal.title, goal_title))).first()
        if goal is None:
            raise Invalid(f"no goal titled {goal_title!r}; create it first")
        goal_id = goal.id
    project = records.create_project(session, ProjectCreate(**fields, goal_id=goal_id), ctx)
    return {"summary": f"created project {project.name!r}", "action": {"type": "project.created", "id": project.id, "name": project.name}}


def _create_task(session: Session, ctx: Ctx, args: dict, env: ToolEnv) -> dict[str, Any]:
    fields = dict(args)
    project_id = _project_id(session, fields.pop("project_name", None))
    task = records.create_task(session, TaskCreate(**fields, project_id=project_id), ctx)
    return {"summary": f"created task {task.title!r} [{task.priority}{_fmt_due(task.due_at)}]", "action": {"type": "task.created", "id": task.id, "title": task.title}}


def _create_contact(session: Session, ctx: Ctx, args: dict, env: ToolEnv) -> dict[str, Any]:
    contact = records.create_contact(session, ContactCreate(**args), ctx)
    return {"summary": f"created contact {contact.name!r}", "action": {"type": "contact.created", "id": contact.id, "name": contact.name}}


def _update_task(session: Session, ctx: Ctx, args: dict, env: ToolEnv) -> dict[str, Any]:
    fields = dict(args)
    task = _one_open_task(session, fields.pop("task_query"))
    if not fields:
        raise Invalid("nothing to change: give status, priority, due_at or title")
    updated = records.update_task(session, task.id, TaskUpdate(**fields), ctx)
    return {"summary": f"updated task {updated.title!r}", "action": {"type": "task.updated", "id": updated.id, "title": updated.title}}


def _complete_task(session: Session, ctx: Ctx, args: dict, env: ToolEnv) -> dict[str, Any]:
    task = records.complete_task(session, _one_open_task(session, args["task_query"]).id, ctx)
    return {"summary": f"completed task {task.title!r}", "action": {"type": "task.completed", "id": task.id, "title": task.title}}


def _propose_action(session: Session, ctx: Ctx, args: dict, env: ToolEnv) -> dict[str, Any]:
    canonical = env.policy.canonical(args["action_type"])
    if canonical not in external_action_types():
        raise Invalid(f"{args['action_type']!r} is not an external action type; use the create_* tools for records. Valid types: {', '.join(external_action_types())}")
    payload = {**args.get("payload", {}), "on_behalf_of": ctx.actor}
    proposal = ActionProposal(action_type=canonical, target=args["target"], payload=payload, reason=args["reason"])
    item, decision, _ = approvals.propose(
        session, proposal, ctx, env.policy, env.settings, origin="assistant", conversation_id=env.conversation_id, requested_by="assistant", notifier=env.notifier
    )
    return {
        "summary": f"approval requested for {item.action_type} to {item.target} ({item.risk} risk); nothing was sent",
        "approval_id": item.id,
        "approval_required": True,
        "action": {"type": "approval.requested", "id": item.id, "action_type": item.action_type, "risk": item.risk},
    }


HANDLERS: dict[str, Callable[[Session, Ctx, dict, ToolEnv], dict[str, Any]]] = {
    "get_briefing": _get_briefing,
    "list_items": _list_items,
    "search": _search,
    "create_goal": _create_goal,
    "create_project": _create_project,
    "create_task": _create_task,
    "create_contact": _create_contact,
    "update_task": _update_task,
    "complete_task": _complete_task,
    PROPOSE: _propose_action,
}
assert set(HANDLERS) == set(SPEC_BY_NAME), "every planner tool needs a handler and vice versa"


def run_step(session: Session, step: Step, ctx: Ctx, env: ToolEnv) -> dict[str, Any]:
    try:
        return {"tool": step.tool, "ok": True, **HANDLERS[step.tool](session, ctx, step.args, env)}
    except DomainError as exc:
        session.rollback()
        return {"tool": step.tool, "ok": False, "error": exc.message}
    except ValidationError as exc:
        session.rollback()
        return {"tool": step.tool, "ok": False, "error": "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())}
