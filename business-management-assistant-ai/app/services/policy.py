"""Action policy: classifies every action by risk and decides whether human approval is required."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Risk(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


_ORDER = (Risk.low, Risk.medium, Risk.high, Risk.critical)


def _rank(risk: Risk) -> int:
    return _ORDER.index(risk)


def _bump(risk: Risk) -> Risk:
    return _ORDER[min(_rank(risk) + 1, len(_ORDER) - 1)]


@dataclass(frozen=True)
class ActionSpec:
    action_type: str
    risk: Risk
    external: bool
    description: str


def _spec(action_type: str, risk: Risk, external: bool, description: str) -> tuple[str, ActionSpec]:
    return action_type, ActionSpec(action_type, risk, external, description)


CATALOG: dict[str, ActionSpec] = dict(
    [
        _spec("record.create", Risk.low, False, "Create an internal record"),
        _spec("record.update", Risk.low, False, "Update an internal record"),
        _spec("task.complete", Risk.low, False, "Mark an internal task done"),
        _spec("message.draft", Risk.low, False, "Prepare a message without sending it"),
        _spec("campaign.draft", Risk.low, False, "Prepare a campaign without launching it"),
        _spec("payment.prepare", Risk.medium, False, "Prepare a payment for review"),
        _spec("calendar.invite", Risk.medium, True, "Send a calendar invitation"),
        _spec("crm.update", Risk.medium, True, "Write to an external CRM"),
        _spec("message.send", Risk.high, True, "Send an email, chat or text message"),
        _spec("content.publish", Risk.high, True, "Publish content publicly"),
        _spec("campaign.launch", Risk.high, True, "Launch an advertising campaign"),
        _spec("invoice.send", Risk.high, True, "Send an invoice to a customer"),
        _spec("contract.send", Risk.high, True, "Send a contract for review"),
        _spec("data.export", Risk.high, True, "Export or share business data"),
        _spec("payment.execute", Risk.critical, True, "Move money"),
        _spec("campaign.budget_change", Risk.critical, True, "Change advertising spend"),
        _spec("contract.sign", Risk.critical, True, "Sign or accept a contract"),
        _spec("integration.enable", Risk.critical, True, "Enable a connector"),
        _spec("permission.change", Risk.critical, True, "Change account permissions"),
        _spec("data.delete", Risk.critical, True, "Delete data"),
    ]
)

ALIASES = {
    "send_external_message": "message.send",
    "send_email": "message.send",
    "send_message": "message.send",
    "publish": "content.publish",
    "publish_content": "content.publish",
    "make_payment": "payment.execute",
    "pay": "payment.execute",
    "delete": "data.delete",
}

_MONEY_KEYS = ("amount", "budget", "value", "total", "price")
_RECIPIENT_KEYS = ("recipients", "to", "emails")


@dataclass(frozen=True)
class PolicyDecision:
    action_type: str
    risk: Risk
    external: bool
    known: bool
    requires_approval: bool
    reasons: tuple[str, ...]


def _money_values(payload: Mapping[str, Any], depth: int = 2) -> Iterator[Any]:
    for key, value in payload.items():
        if str(key).lower() in _MONEY_KEYS:
            yield value
        elif isinstance(value, Mapping) and depth > 0:
            yield from _money_values(value, depth - 1)


def _as_amount(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").strip().lstrip("$€£"))
        except ValueError:
            return None
    return None


class PolicyEngine:
    def __init__(self, high_value_threshold: float = 1000.0, approval_floor: Risk = Risk.medium, bulk_recipients: int = 25) -> None:
        self.high_value_threshold = high_value_threshold
        self.approval_floor = approval_floor
        self.bulk_recipients = bulk_recipients

    @staticmethod
    def canonical(action_type: str) -> str:
        key = action_type.strip().lower()
        return ALIASES.get(key, key)

    def evaluate(self, action_type: str, payload: Mapping[str, Any] | None = None) -> PolicyDecision:
        payload = payload or {}
        canonical = self.canonical(action_type)
        reasons: list[str] = []
        spec = CATALOG.get(canonical)
        if spec is None:
            risk, external, known = Risk.high, True, False
            reasons.append("unknown action type: treated as high-risk external (fail closed)")
        else:
            risk, external, known = spec.risk, spec.external, True
            reasons.append(f"{canonical} is {risk.value} risk" + (" and external" if external else " and internal"))

        for value in _money_values(payload):
            amount = _as_amount(value)
            if amount is None:
                risk = _bump(risk)
                reasons.append("monetary field is not numeric: escalated")
            elif amount >= self.high_value_threshold:
                risk = _bump(risk)
                reasons.append(f"amount {amount:g} is at or above {self.high_value_threshold:g}: escalated")
                break

        for key in _RECIPIENT_KEYS:
            recipients = payload.get(key)
            if isinstance(recipients, (list, tuple)) and len(recipients) > self.bulk_recipients:
                risk = _bump(risk)
                reasons.append(f"{len(recipients)} recipients exceeds bulk limit {self.bulk_recipients}: escalated")
                break

        if payload.get("public") is True or str(payload.get("visibility", "")).lower() == "public":
            if _rank(risk) < _rank(Risk.high):
                risk = Risk.high
                reasons.append("public visibility: raised to high")

        requires = external or _rank(risk) >= _rank(self.approval_floor)
        return PolicyDecision(canonical, risk, external, known, requires, tuple(reasons))

    @staticmethod
    def catalog() -> list[dict[str, Any]]:
        return [
            {"action_type": s.action_type, "risk": s.risk.value, "external": s.external, "description": s.description}
            for s in CATALOG.values()
        ]


def external_action_types() -> list[str]:
    """Action types a model may propose: external, or at least medium risk."""
    return [name for name, spec in CATALOG.items() if spec.external or _rank(spec.risk) >= _rank(Risk.medium)]
