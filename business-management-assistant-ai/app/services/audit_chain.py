"""Hash-chained audit entries: pure functions, no database access."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

GENESIS_HASH = "0" * 64


def utc_ts(moment: datetime | None = None) -> str:
    moment = moment or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def normalise_details(details: Mapping[str, Any] | None) -> dict[str, Any]:
    """Round-trip through JSON so the stored value hashes identically after a database read."""
    return json.loads(canonical_json(dict(details or {})))


def compute_entry_hash(
    prev_hash: str,
    ts: str,
    event_type: str,
    actor: str,
    target: str,
    details: Mapping[str, Any] | None,
    request_id: str | None,
) -> str:
    material = json.dumps([prev_hash, ts, event_type, actor, target, canonical_json(details or {}), request_id or ""])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    checked: int
    first_bad_id: int | None = None
    reason: str | None = None


def verify_chain(rows: Iterable[Mapping[str, Any]]) -> VerifyResult:
    """Walk rows in ascending id order and report the first inconsistency."""
    expected_prev = GENESIS_HASH
    checked = 0
    for row in rows:
        if row["prev_hash"] != expected_prev:
            return VerifyResult(False, checked, row["id"], "chain broken: an earlier entry was removed or reordered")
        recomputed = compute_entry_hash(
            row["prev_hash"], row["ts"], row["event_type"], row["actor"], row["target"], row["details"], row.get("request_id")
        )
        if recomputed != row["entry_hash"]:
            return VerifyResult(False, checked, row["id"], "entry content does not match its hash")
        expected_prev = row["entry_hash"]
        checked += 1
    return VerifyResult(True, checked)
