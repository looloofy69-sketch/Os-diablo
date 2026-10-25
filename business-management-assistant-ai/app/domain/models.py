import json
from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator
from pydantic import Field as PydField
from sqlalchemy import JSON, Column, DateTime, String
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field, SQLModel


def now() -> datetime:
    return datetime.now(timezone.utc)


def uid() -> str:
    return str(uuid4())


class UTCDateTime(TypeDecorator):
    """Always returns timezone-aware UTC; naive input is interpreted as UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def ts(nullable: bool = False, index: bool = False) -> Column:
    return Column(UTCDateTime(timezone=True), nullable=nullable, index=index)


class Status(StrEnum):
    planned = "planned"
    active = "active"
    blocked = "blocked"
    done = "done"


class Priority(StrEnum):
    urgent = "urgent"
    high = "high"
    medium = "medium"
    low = "low"


class ApprovalStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"
    executing = "executing"
    executed = "executed"
    failed = "failed"


# ---------------------------------------------------------------- tables


class SchemaMeta(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str


class Goal(SQLModel, table=True):
    id: str = Field(default_factory=uid, primary_key=True)
    title: str
    description: str = ""
    status: str = Field(default=Status.planned.value, index=True)
    owner: str = "founder"
    target_date: datetime | None = Field(default=None, sa_column=ts(nullable=True))
    created_at: datetime = Field(default_factory=now, sa_column=ts())
    updated_at: datetime = Field(default_factory=now, sa_column=ts())


class Project(SQLModel, table=True):
    id: str = Field(default_factory=uid, primary_key=True)
    name: str
    objective: str = ""
    status: str = Field(default=Status.planned.value, index=True)
    owner: str = "founder"
    goal_id: str | None = Field(default=None, foreign_key="goal.id", index=True)
    created_at: datetime = Field(default_factory=now, sa_column=ts())
    updated_at: datetime = Field(default_factory=now, sa_column=ts())


class Task(SQLModel, table=True):
    id: str = Field(default_factory=uid, primary_key=True)
    title: str
    description: str = ""
    project_id: str | None = Field(default=None, foreign_key="project.id", index=True)
    owner: str = "founder"
    status: str = Field(default=Status.planned.value, index=True)
    priority: str = Field(default=Priority.medium.value, index=True)
    due_at: datetime | None = Field(default=None, sa_column=ts(nullable=True, index=True))
    completed_at: datetime | None = Field(default=None, sa_column=ts(nullable=True))
    created_at: datetime = Field(default_factory=now, sa_column=ts())
    updated_at: datetime = Field(default_factory=now, sa_column=ts())


class Contact(SQLModel, table=True):
    id: str = Field(default_factory=uid, primary_key=True)
    name: str
    organisation: str = ""
    email: str | None = Field(default=None, sa_column=Column(String(254), unique=True, index=True, nullable=True))
    relationship: str = "prospect"
    notes: str = ""
    created_at: datetime = Field(default_factory=now, sa_column=ts())
    updated_at: datetime = Field(default_factory=now, sa_column=ts())


class ApprovalRequest(SQLModel, table=True):
    id: str = Field(default_factory=uid, primary_key=True)
    action_type: str = Field(index=True)
    target: str
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    reason: str
    risk: str = "high"
    policy_reasons: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    status: str = Field(default=ApprovalStatus.pending.value, index=True)
    origin: str = "human"  # human | assistant
    requested_by: str = "assistant"
    reviewed_by: str | None = None
    review_note: str = ""
    idempotency_key: str | None = Field(default=None, sa_column=Column(String(128), unique=True, nullable=True))
    conversation_id: str | None = None
    result: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    expires_at: datetime | None = Field(default=None, sa_column=ts(nullable=True))
    reviewed_at: datetime | None = Field(default=None, sa_column=ts(nullable=True))
    executed_at: datetime | None = Field(default=None, sa_column=ts(nullable=True))
    created_at: datetime = Field(default_factory=now, sa_column=ts(index=True))


class Integration(SQLModel, table=True):
    id: str = Field(default_factory=uid, primary_key=True)
    name: str = Field(index=True, unique=True)
    category: str = Field(index=True)
    scopes: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    enabled: bool = False
    health: str = "not_configured"
    last_checked_at: datetime | None = Field(default=None, sa_column=ts(nullable=True))
    created_at: datetime = Field(default_factory=now, sa_column=ts())


class AuditEvent(SQLModel, table=True):
    """Append-only, hash-chained. ``prev_hash`` is unique so the database itself enforces a single linear chain."""

    id: int | None = Field(default=None, primary_key=True)
    ts: str
    event_type: str = Field(index=True)
    actor: str = Field(index=True)
    target: str = Field(index=True)
    details: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    request_id: str | None = None
    prev_hash: str = Field(sa_column=Column(String(64), unique=True, nullable=False))
    entry_hash: str = Field(sa_column=Column(String(64), nullable=False))
    created_at: datetime = Field(default_factory=now, sa_column=ts())


# ---------------------------------------------------------------- request schemas

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Name100 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Body = Annotated[str, StringConstraints(max_length=4000)]
Email = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _blank_to_none(value: Any) -> Any:
    return None if isinstance(value, str) and not value.strip() else value


class GoalCreate(_Strict):
    title: Title
    description: Body = ""
    owner: Name100 = "founder"
    target_date: datetime | None = None


class GoalUpdate(_Strict):
    title: Title | None = None
    description: Body | None = None
    owner: Name100 | None = None
    status: Status | None = None
    target_date: datetime | None = None


class ProjectCreate(_Strict):
    name: Title
    objective: Body = ""
    owner: Name100 = "founder"
    goal_id: str | None = None


class ProjectUpdate(_Strict):
    name: Title | None = None
    objective: Body | None = None
    owner: Name100 | None = None
    status: Status | None = None
    goal_id: str | None = None


class TaskCreate(_Strict):
    title: Title
    description: Body = ""
    project_id: str | None = None
    owner: Name100 = "founder"
    priority: Priority = Priority.medium
    due_at: datetime | None = None


class TaskUpdate(_Strict):
    title: Title | None = None
    description: Body | None = None
    project_id: str | None = None
    owner: Name100 | None = None
    status: Status | None = None
    priority: Priority | None = None
    due_at: datetime | None = None


class ContactCreate(_Strict):
    name: Title
    organisation: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""
    email: Email | None = None
    relationship: Name100 = "prospect"
    notes: Body = ""

    _blank_email = field_validator("email", mode="before")(_blank_to_none)


class ContactUpdate(_Strict):
    name: Title | None = None
    organisation: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    email: Email | None = None
    relationship: Name100 | None = None
    notes: Body | None = None

    _blank_email = field_validator("email", mode="before")(_blank_to_none)


class ActionProposal(_Strict):
    action_type: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    target: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    payload: dict[str, Any] = PydField(default_factory=dict)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    idempotency_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)] | None = None

    @field_validator("payload")
    @classmethod
    def _payload_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, default=str)) > 16_384:
            raise ValueError("payload must be 16 KB or smaller")
        return value


class ApprovalDecision(BaseModel):
    """Reviewer identity comes from authentication; a legacy ``reviewer`` field is ignored."""

    model_config = ConfigDict(extra="ignore")
    decision: Literal["approved", "rejected"]
    note: Annotated[str, StringConstraints(max_length=1000)] = ""
    execute: bool = False


class ApprovalAmend(_Strict):
    target: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)] | None = None
    payload: dict[str, Any] | None = None
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)] | None = None

    @field_validator("payload")
    @classmethod
    def _payload_size(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None and len(json.dumps(value, default=str)) > 16_384:
            raise ValueError("payload must be 16 KB or smaller")
        return value


Capability = Literal["classification", "planning", "strategy", "multimodal", "advertising", "seo", "finance", "contracts", "customer_success"]


class PlanRequest(_Strict):
    request: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    capability: Capability = "planning"
