from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StringConstraints
from pydantic import Field as PydField
from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.domain.models import now, ts, uid


class Conversation(SQLModel, table=True):
    id: str = Field(default_factory=uid, primary_key=True)
    title: str = "New business conversation"
    channel: str = "web"
    created_by: str = "founder"
    created_at: datetime = Field(default_factory=now, sa_column=ts())
    updated_at: datetime = Field(default_factory=now, sa_column=ts(index=True))


class ChatMessage(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    conversation_id: str = Field(foreign_key="conversation.id", index=True)
    role: str
    content: str
    extra_data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=now, sa_column=ts())


class ChatRequest(BaseModel):
    """Identity comes from authentication; a legacy ``actor`` field is ignored."""

    model_config = ConfigDict(extra="ignore")
    conversation_id: str | None = None
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class ChatResponse(BaseModel):
    conversation_id: str
    message: str
    intent: str
    handled_by: str | None = None
    actions: list[dict[str, Any]] = PydField(default_factory=list)
    approval_required: bool = False
    approval_id: str | None = None
    suggestions: list[str] = PydField(default_factory=list)
    via: str = "rules"  # rules | llm
