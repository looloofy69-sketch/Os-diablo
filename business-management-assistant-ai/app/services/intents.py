"""Deterministic intent parsing. Rules decide; models may only help with unmatched text (see llm.py)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

BRIEFING = "briefing"
HELP = "help"
CREATE_GOAL = "create_goal"
CREATE_TASK = "create_task"
CREATE_PROJECT = "create_project"
CREATE_CONTACT = "create_contact"
COMPLETE_TASK = "complete_task"
LIST = "list"
SEARCH = "search"
PROTECTED = "protected_action"
SEO = "seo"
ADVERTISING = "advertising"
CLARIFY = "clarify"
OTHER = "other"

PRIORITIES = ("urgent", "high", "medium", "low")


@dataclass(frozen=True)
class Intent:
    name: str
    confidence: float
    entities: dict[str, Any] = field(default_factory=dict)
    action_type: str | None = None


_PREFIX = re.compile(
    r"^(?:please|pls|hey|hi|ok|okay|so|could you|can you|would you|will you|i want to|i would like to|i'd like to|i need to|let's|lets|go ahead and)\b[\s,]*",
    re.I,
)
_BRIEFING = re.compile(
    r"^(?:brief me|(?:business |daily |morning )?briefing|status(?: update)?|how(?:'s| is) the business(?: going)?|"
    r"what(?:'s| is) going on|what should i (?:do|work on) (?:next|today)|what(?:'s| is) next|what now)\W*$",
    re.I,
)
_HELP = re.compile(r"^(?:help|what can you do|commands)\W*$", re.I)
_CREATE = re.compile(r"^(?:create|add|new)\s+(?:an?\s+|new\s+)?(goal|task|project|contact|todo)\b(?:\s*[:\-]\s*|\s+)?(.*)$", re.I | re.S)
_COMPLETE = re.compile(
    r"^(?:complete|finish|close|check off|mark)\s+(?:the\s+)?(?:task\s*[:\-]?\s*)?(.+?)(?:\s+(?:as\s+)?(?:done|complete|completed|finished))?\W*$",
    re.I | re.S,
)
_LIST = re.compile(
    r"^(?:list|show|display|what are|what's|whats)(?:\s+me)?(?:\s+all)?(?:\s+(?:my|the|our))?"
    r"(?:\s+(open|overdue|pending|blocked|active|done))?\s+(goals|tasks|projects|contacts|approvals|integrations)\W*$",
    re.I,
)
_LIST_SHORT = re.compile(r"^(overdue|open|pending|blocked)\s+(tasks|approvals)\W*$", re.I)
_SEARCH = re.compile(r"^(?:search|find|look\s*up)\s+(?:for\s+)?(.+?)\W*$", re.I | re.S)
_QUESTION = re.compile(r"^(?:what|how|why|when|who|where|which|should|does|do|is|are|can i|could i)\b", re.I)
_SEO = re.compile(r"\bseo\b|search (?:rankings?|visibility|traffic|engine)|google rankings?|organic (?:search|traffic)|\bkeywords?\b", re.I)
_ADS = re.compile(r"\badvertis\w*|\bads?\b|\bcampaigns?\b|\bppc\b|\bad spend\b", re.I)

# Leading verbs (imperative requests) -> action type.
LEADING_VERBS = {
    "send": "message.send", "email": "message.send", "message": "message.send", "reply": "message.send", "forward": "message.send",
    "publish": "content.publish", "post": "content.publish", "tweet": "content.publish",
    "pay": "payment.execute", "wire": "payment.execute", "transfer": "payment.execute", "refund": "payment.execute",
    "buy": "payment.execute", "purchase": "payment.execute", "order": "payment.execute",
    "invoice": "invoice.send", "sign": "contract.sign",
    "delete": "data.delete", "remove": "data.delete", "erase": "data.delete",
    "launch": "campaign.launch", "schedule": "calendar.invite", "book": "calendar.invite",
    "share": "data.export", "export": "data.export",
}
# Verbs that are unambiguous even in the middle of a sentence (nouns like "post" or "order" are excluded).
INLINE_VERBS = {
    "send": "message.send", "publish": "content.publish", "pay": "payment.execute", "wire": "payment.execute",
    "refund": "payment.execute", "purchase": "payment.execute", "sign": "contract.sign", "delete": "data.delete",
    "launch": "campaign.launch", "tweet": "content.publish",
}
_INLINE = re.compile(r"\b(" + "|".join(INLINE_VERBS) + r")\b", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_ISO_DATE = re.compile(r"\b(?:by|due|on|before)\s+(\d{4}-\d{2}-\d{2})\b", re.I)
_REL_DATE = re.compile(r"\b(?:by|due|on|before)\s+(today|tomorrow)\b", re.I)
_IN_DATE = re.compile(r"\b(?:by|due|in)\s+(\d{1,3})\s+(day|days|week|weeks)\b", re.I)
_PRIORITY = re.compile(r"(?:^|\s)(?:!(urgent|high|medium|low)\b|(urgent|high|medium|low)[ -]priority\b|priority[: ]+(urgent|high|medium|low)\b)", re.I)
_PROJECT = re.compile(r"\b(?:in|for|under)\s+project\s+[\"']?(.+?)[\"']?(?=\s+(?:by|due|!)|\s+(?:urgent|high|medium|low)[ -]priority|$)", re.I)
_AMOUNT = re.compile(
    r"(?:[$€£]\s?(\d[\d,]*(?:\.\d+)?)\s?(k|m)?)|(?:\b(\d[\d,]*(?:\.\d+)?)\s?(k|m)?\s?(?:usd|eur|gbp|dzd|dollars|euros)\b)", re.I
)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("’", "'")).strip()


def _strip_prefix(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = _PREFIX.sub("", text, count=1)
    return text


def _tidy(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip(" ,;.:-")


def _end_of_day(day: datetime) -> datetime:
    return day.replace(hour=23, minute=59, second=0, microsecond=0, tzinfo=UTC)


def _extract_due(text: str, now: datetime) -> tuple[str, datetime | None]:
    if match := _ISO_DATE.search(text):
        try:
            y, m, d = (int(part) for part in match.group(1).split("-"))
            due = _end_of_day(datetime(y, m, d))
        except ValueError:
            return text, None
        return text[: match.start()] + text[match.end():], due
    if match := _REL_DATE.search(text):
        base = now.astimezone(UTC)
        offset = 1 if match.group(1).lower() == "tomorrow" else 0
        return text[: match.start()] + text[match.end():], _end_of_day(base + timedelta(days=offset))
    if match := _IN_DATE.search(text):
        count = int(match.group(1)) * (7 if match.group(2).lower().startswith("week") else 1)
        return text[: match.start()] + text[match.end():], _end_of_day(now.astimezone(UTC) + timedelta(days=count))
    return text, None


def _extract_priority(text: str) -> tuple[str, str | None]:
    if match := _PRIORITY.search(text):
        level = next(g for g in match.groups() if g).lower()
        return text[: match.start()] + text[match.end():], level
    return text, None


def _extract_amount(text: str) -> float | None:
    match = _AMOUNT.search(text)
    if not match:
        return None
    number, suffix = (match.group(1), match.group(2)) if match.group(1) else (match.group(3), match.group(4))
    value = float(number.replace(",", ""))
    return value * {"k": 1_000, "m": 1_000_000}.get((suffix or "").lower(), 1)


def parse_create(kind: str, rest: str, now: datetime) -> Intent:
    rest = _clean(rest)
    kind = "task" if kind == "todo" else kind
    name = {"goal": CREATE_GOAL, "task": CREATE_TASK, "project": CREATE_PROJECT, "contact": CREATE_CONTACT}[kind]
    if not rest:
        return Intent(CLARIFY, 1.0, {"missing": "title", "for": kind})
    entities: dict[str, Any] = {}
    if kind == "contact":
        email = _EMAIL.search(rest)
        if email:
            entities["email"] = email.group(0).lower()
            rest = rest[: email.start()] + rest[email.end():]
        org = re.search(r"\s+(?:at|from|of)\s+(.+)$", rest, re.I)
        if org:
            entities["organisation"] = _tidy(org.group(1))
            rest = rest[: org.start()]
        entities["name"] = _tidy(rest)
        if not entities["name"]:
            return Intent(CLARIFY, 1.0, {"missing": "name", "for": kind})
        return Intent(name, 0.95, entities)

    rest, priority = _extract_priority(rest)
    rest, due = _extract_due(rest, now)
    if kind == "task":
        if match := _PROJECT.search(rest):
            entities["project_name"] = _tidy(match.group(1))
            rest = rest[: match.start()] + rest[match.end():]
        entities["priority"] = priority or "medium"
        entities["due_at"] = due
    elif kind == "goal":
        entities["target_date"] = due
    title = _tidy(rest)
    if not title:
        return Intent(CLARIFY, 1.0, {"missing": "title", "for": kind})
    entities["title" if kind != "project" else "name"] = title
    return Intent(name, 0.95, entities)


def parse(text: str, now: datetime | None = None) -> Intent:
    now = now or datetime.now(UTC)
    cleaned = _strip_prefix(_clean(text))
    if not cleaned:
        return Intent(OTHER, 0.0)

    if _BRIEFING.match(cleaned):
        return Intent(BRIEFING, 0.95)
    if _HELP.match(cleaned):
        return Intent(HELP, 0.95)
    if match := _CREATE.match(cleaned):
        return parse_create(match.group(1).lower(), match.group(2), now)
    if match := _LIST.match(cleaned) or _LIST_SHORT.match(cleaned):
        groups = match.groups()
        scope, entity = (groups[0], groups[1]) if len(groups) == 2 else (None, groups[0])
        return Intent(LIST, 0.95, {"entity": entity.lower(), "scope": (scope or "").lower() or None})
    if match := _COMPLETE.match(cleaned):
        return Intent(COMPLETE_TASK, 0.8, {"query": _tidy(match.group(1))})

    lowered = cleaned.lower()
    first = lowered.split(" ", 1)[0].strip(".,:;!?")
    if first in LEADING_VERBS:
        return Intent(PROTECTED, 0.9, _protected_entities(cleaned), LEADING_VERBS[first])
    if not _QUESTION.match(cleaned) and (inline := _INLINE.search(cleaned)):
        return Intent(PROTECTED, 0.75, _protected_entities(cleaned), INLINE_VERBS[inline.group(1).lower()])

    if _SEO.search(cleaned):
        return Intent(SEO, 0.7)
    if _ADS.search(cleaned):
        return Intent(ADVERTISING, 0.7)
    if match := _SEARCH.match(cleaned):
        return Intent(SEARCH, 0.85, {"query": _tidy(match.group(1))})
    return Intent(OTHER, 0.0)


def _protected_entities(text: str) -> dict[str, Any]:
    entities: dict[str, Any] = {"summary": text[:300]}
    emails = _EMAIL.findall(text)
    if emails:
        entities["target"] = emails[0].lower()
    elif match := re.search(r"\bto\s+(.+?)(?:\s+(?:about|regarding|re|saying|that|with|for)\b|[.,;]|$)", text, re.I):
        entities["target"] = _tidy(match.group(1))[:200]
    amount = _extract_amount(text)
    if amount is not None:
        entities["amount"] = amount
    return entities
