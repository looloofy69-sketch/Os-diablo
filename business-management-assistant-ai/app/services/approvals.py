"""Approval lifecycle: pending -> approved|rejected|expired; approved -> executing -> executed|failed.

Every transition is a conditional UPDATE (compare-and-set on status), so concurrent reviewers or retries
can never double-approve or double-execute.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import timedelta
from typing import Any

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.core import Settings
from app.domain.models import ActionProposal, ApprovalAmend, ApprovalDecision, ApprovalRequest, ApprovalStatus, now
from app.errors import Conflict, Forbidden, Invalid, NotFound
from app.services.audit import normalise_details, record_event
from app.services.connectors import ConnectorNotConfigured, ConnectorRegistry
from app.services.context import SYSTEM, Ctx
from app.services.policy import PolicyDecision, PolicyEngine

log = logging.getLogger("bma.approvals")
S = ApprovalStatus
STUCK_AFTER_MINUTES = 10


def _transition(session: Session, approval_id: str, expected: S, **values: object) -> bool:
    result = session.exec(
        update(ApprovalRequest).where(col(ApprovalRequest.id) == approval_id, col(ApprovalRequest.status) == expected.value).values(**values)
    )
    return result.rowcount == 1


def _get(session: Session, approval_id: str) -> ApprovalRequest:
    item = session.get(ApprovalRequest, approval_id)
    if item is None:
        raise NotFound("Approval request not found")
    return item


def expire_stale(session: Session) -> int:
    """Lazily expire pending requests past their deadline; no background worker required."""
    stamp = now()
    due = session.exec(select(ApprovalRequest).where(col(ApprovalRequest.status) == S.pending.value, col(ApprovalRequest.expires_at) < stamp)).all()
    expired = 0
    for item in due:
        if _transition(session, item.id, S.pending, status=S.expired.value):
            record_event(session, "action.expired", SYSTEM.actor, item.id, {"action_type": item.action_type})
            expired += 1
    if expired:
        session.commit()
    return expired


def recover_stuck(session: Session) -> int:
    """An execution that never reported back may or may not have acted. Fail it as outcome-unknown and never auto-retry."""
    cutoff = now() - timedelta(minutes=STUCK_AFTER_MINUTES)
    stuck = session.exec(select(ApprovalRequest).where(col(ApprovalRequest.status) == S.executing.value, col(ApprovalRequest.executed_at) < cutoff)).all()
    recovered = 0
    for item in stuck:
        result = {"ok": False, "dry_run": False, "retryable": False, "outcome_unknown": True,
                  "detail": "Execution did not report back (process stopped?). Check the destination system before proposing the action again."}
        if _transition(session, item.id, S.executing, status=S.failed.value, result=result):
            record_event(session, "action.recovered", SYSTEM.actor, item.id, {"action_type": item.action_type, "outcome": "unknown"})
            recovered += 1
    if recovered:
        session.commit()
    return recovered


def housekeeping(session: Session) -> None:
    expire_stale(session)
    recover_stuck(session)


def propose(
    session: Session,
    data: ActionProposal,
    ctx: Ctx,
    policy: PolicyEngine,
    settings: Settings,
    *,
    origin: str = "human",
    conversation_id: str | None = None,
    requested_by: str | None = None,
    notifier: Any = None,
) -> tuple[ApprovalRequest, PolicyDecision, bool]:
    """Returns ``(request, policy decision, created)``. A repeated idempotency key returns the original request."""
    if data.idempotency_key:
        existing = session.exec(select(ApprovalRequest).where(ApprovalRequest.idempotency_key == data.idempotency_key)).first()
        if existing:
            return existing, policy.evaluate(existing.action_type, existing.payload), False

    decision = policy.evaluate(data.action_type, data.payload)
    stamp = now()
    item = ApprovalRequest(
        action_type=decision.action_type,
        target=data.target,
        payload=data.payload,
        reason=data.reason,
        risk=decision.risk.value,
        policy_reasons=list(decision.reasons),
        origin=origin,
        requested_by=requested_by or ctx.actor,
        conversation_id=conversation_id,
        idempotency_key=data.idempotency_key,
        expires_at=stamp + timedelta(hours=settings.approval_ttl_hours),
    )
    auto_approve = not decision.requires_approval and origin != "assistant"  # model-originated requests always wait for a person
    if auto_approve:
        item.status, item.reviewed_by, item.reviewed_at = S.approved.value, "policy", stamp
    session.add(item)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = session.exec(select(ApprovalRequest).where(ApprovalRequest.idempotency_key == data.idempotency_key)).first() if data.idempotency_key else None
        if existing:
            return existing, decision, False
        raise
    detail = {"action_type": item.action_type, "target": item.target, "risk": item.risk, "origin": origin}
    record_event(session, "action.proposed", ctx.actor, item.id, detail, ctx.request_id)
    if auto_approve:
        record_event(session, "action.auto_approved", "policy", item.id, {"reasons": list(decision.reasons)}, ctx.request_id)
    session.commit()
    session.refresh(item)
    if notifier is not None and item.status == S.pending.value:
        try:
            notifier.approval_pending(item)
        except Exception:  # noqa: BLE001 - notices are best effort
            log.exception("notifier failed for approval %s", item.id)
    return item, decision, True


def decide(session: Session, approval_id: str, data: ApprovalDecision, ctx: Ctx, settings: Settings, connectors: ConnectorRegistry) -> ApprovalRequest:
    housekeeping(session)
    item = _get(session, approval_id)
    if item.status != S.pending.value:
        raise Conflict(f"Approval request is {item.status}, not pending")
    if item.origin == "human" and item.requested_by == ctx.actor and settings.distinct_reviewer_required:
        raise Forbidden("The requester cannot review their own request")
    new_status = S.approved if data.decision == "approved" else S.rejected
    if not _transition(session, approval_id, S.pending, status=new_status.value, reviewed_by=ctx.actor, reviewed_at=now(), review_note=data.note):
        session.rollback()
        raise Conflict("Approval request was decided by someone else")
    record_event(session, f"action.{new_status.value}", ctx.actor, approval_id, {"target": item.target, "note": data.note}, ctx.request_id)
    session.commit()
    session.refresh(item)
    if new_status is S.approved and data.execute:
        return execute(session, approval_id, ctx, connectors)
    return item


def execute(session: Session, approval_id: str, ctx: Ctx, connectors: ConnectorRegistry) -> ApprovalRequest:
    item = _get(session, approval_id)
    if item.status == S.executed.value:
        return item  # a retried call after success is harmless
    if item.status != S.approved.value:
        raise Conflict(f"Only approved requests can be executed; this one is {item.status}")
    if item.expires_at is not None and item.expires_at < now():
        if _transition(session, approval_id, S.approved, status=S.expired.value):
            record_event(session, "action.expired", SYSTEM.actor, approval_id, {"stage": "before_execution"}, ctx.request_id)
            session.commit()
        raise Conflict("Approval expired before execution; propose the action again")
    if not _transition(session, approval_id, S.approved, status=S.executing.value):
        session.rollback()
        raise Conflict("Another request is already executing this action")
    record_event(session, "action.executing", ctx.actor, approval_id, {"action_type": item.action_type}, ctx.request_id)
    _transition(session, approval_id, S.executing, executed_at=now())  # start time, used to detect a stuck execution
    session.commit()  # claim is durable before any side effect

    try:
        outcome = connectors.resolve(item.action_type, item.target).execute(
            action_type=item.action_type, target=item.target, payload=item.payload, idempotency_key=approval_id
        )
        # Retry safety and outcome certainty are explicit connector contract fields;
        # never infer side-effect state from user-facing error text.
        final, result = (S.executed if outcome.ok else S.failed), asdict(outcome)
    except ConnectorNotConfigured as exc:
        final, result = S.failed, {"ok": False, "dry_run": False, "retryable": False, "outcome_unknown": False, "detail": str(exc)}
    except Exception as exc:  # connector bugs must not leave the request stuck in "executing"
        log.exception("connector failed for approval %s", approval_id)
        final, result = S.failed, {"ok": False, "dry_run": False, "retryable": False, "outcome_unknown": True, "detail": f"{type(exc).__name__}: connector error"}

    if not _transition(session, approval_id, S.executing, status=final.value, result=result, executed_at=now()):
        log.error("approval %s left 'executing' while the connector ran (recovered as stuck?); result not stored", approval_id)
    record_event(session, f"action.{final.value}", ctx.actor, approval_id, {"dry_run": result.get("dry_run"), "detail": result.get("detail")}, ctx.request_id)
    session.commit()
    session.refresh(item)
    return item


def retry(session: Session, approval_id: str, ctx: Ctx, settings: Settings) -> ApprovalRequest:
    """Re-open a failed request, only when the connector reported that nothing was done. The human approval carries over."""
    item = _get(session, approval_id)
    if item.status != S.failed.value:
        raise Conflict(f"Only failed requests can be retried; this one is {item.status}")
    if not item.result.get("retryable"):
        raise Conflict("This failure is not marked safe to retry (the outcome may be unknown). Verify at the destination, then propose the action again.")
    deadline = now() + timedelta(hours=settings.approval_ttl_hours)
    if not _transition(session, approval_id, S.failed, status=S.approved.value, expires_at=deadline):
        session.rollback()
        raise Conflict("Request changed while retrying")
    record_event(session, "action.retry_authorized", ctx.actor, approval_id, {"previous": item.result.get("detail")}, ctx.request_id)
    session.commit()
    session.refresh(item)
    return item


def amend(session: Session, approval_id: str, data: ApprovalAmend, ctx: Ctx, policy: PolicyEngine) -> ApprovalRequest:
    """Reviewer edits a pending request (typically to add the subject and body a rule-originated request lacks). Risk is re-evaluated."""
    housekeeping(session)
    item = _get(session, approval_id)
    if item.status != S.pending.value:
        raise Conflict(f"Only pending requests can be amended; this one is {item.status}")
    changes: dict[str, Any] = {}
    if data.target is not None and data.target != item.target:
        changes["target"] = [item.target, data.target]
    if data.payload is not None and data.payload != item.payload:
        changes["payload"] = [normalise_details({"p": item.payload})["p"], data.payload]
    if data.reason is not None and data.reason != item.reason:
        changes["reason"] = [item.reason, data.reason]
    if not changes:
        raise Invalid("Nothing to change")
    decision = policy.evaluate(item.action_type, data.payload if data.payload is not None else item.payload)
    values: dict[str, Any] = {"risk": decision.risk.value, "policy_reasons": list(decision.reasons)}
    values.update({k: v[1] for k, v in changes.items()})
    if not _transition(session, approval_id, S.pending, **values):
        session.rollback()
        raise Conflict("Request was decided while you were editing it")
    record_event(session, "action.amended", ctx.actor, approval_id, {"changes": changes, "risk": decision.risk.value}, ctx.request_id)
    session.commit()
    session.refresh(item)
    return item
