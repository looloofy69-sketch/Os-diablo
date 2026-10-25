from __future__ import annotations

import random
import time
from contextvars import ContextVar
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.domain.models import AuditEvent
from app.services.audit_chain import (
    GENESIS_HASH,
    VerifyResult,
    compute_entry_hash,
    normalise_details,
    utc_ts,
    verify_chain,
)

MAX_ATTEMPTS = 25
# Set while model-planned steps run, so every audit entry they cause says so.
VIA: ContextVar[str | None] = ContextVar("audit_via", default=None)


def record_event(
    session: Session,
    event_type: str,
    actor: str,
    target: str,
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> AuditEvent:
    """Append to the chain inside the caller's transaction. The caller commits, so a mutation and its audit entry land together."""
    merged = dict(details or {})
    if (via := VIA.get()) is not None:
        merged.setdefault("via", via)
    safe_details = normalise_details(merged)
    session.flush()  # surface the caller's own integrity errors before the retry loop below
    for attempt in range(MAX_ATTEMPTS):
        try:
            with session.begin_nested():
                previous = session.exec(select(AuditEvent.entry_hash).order_by(col(AuditEvent.id).desc()).limit(1)).first()
                prev_hash = previous or GENESIS_HASH
                stamp = utc_ts()
                event = AuditEvent(
                    ts=stamp,
                    event_type=event_type,
                    actor=actor,
                    target=target,
                    details=safe_details,
                    request_id=request_id,
                    prev_hash=prev_hash,
                    entry_hash=compute_entry_hash(prev_hash, stamp, event_type, actor, target, safe_details, request_id),
                )
                session.add(event)
            return event
        except IntegrityError:  # another writer extended the chain first: back off briefly, re-read the head, retry
            time.sleep(random.random() * 0.005 * (attempt + 1))
            continue
    raise RuntimeError("audit chain contention: could not append after several attempts")


def verify_database_chain(session: Session) -> VerifyResult:
    rows = session.exec(select(AuditEvent).order_by(col(AuditEvent.id)))
    return verify_chain(
        {
            "id": r.id,
            "prev_hash": r.prev_hash,
            "entry_hash": r.entry_hash,
            "ts": r.ts,
            "event_type": r.event_type,
            "actor": r.actor,
            "target": r.target,
            "details": r.details,
            "request_id": r.request_id,
        }
        for r in rows
    )
