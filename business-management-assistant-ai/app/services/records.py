"""Business record operations shared by the HTTP API and the chat interface."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, col, select

from app.domain.models import (
    Contact,
    ContactCreate,
    ContactUpdate,
    Goal,
    GoalCreate,
    GoalUpdate,
    Project,
    ProjectCreate,
    ProjectUpdate,
    Status,
    Task,
    TaskCreate,
    TaskUpdate,
    now,
)
from app.errors import Conflict, Invalid, NotFound
from app.services.audit import record_event
from app.services.context import Ctx
from app.services.priorities import as_utc


def _plain(values: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for key, value in values.items():
        if isinstance(value, Enum):
            value = value.value
        elif isinstance(value, datetime):
            value = as_utc(value)
        out[key] = value
    return out


def _jsonable(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _require(session: Session, model: type[SQLModel], entity_id: str | None, label: str) -> None:
    if entity_id is not None and session.get(model, entity_id) is None:
        raise Invalid(f"{label} {entity_id!r} does not exist")


def _commit(session: Session, conflict_message: str | None = None) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise Conflict(conflict_message or "The change conflicts with existing data") from exc


def _create(session: Session, ctx: Ctx, item: Any, event_type: str, details: dict[str, Any], conflict: str | None = None) -> Any:
    session.add(item)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise Conflict(conflict or "The record conflicts with existing data") from exc
    record_event(session, event_type, ctx.actor, item.id, details, ctx.request_id)
    _commit(session, conflict)
    session.refresh(item)
    return item


def create_goal(session: Session, data: GoalCreate, ctx: Ctx) -> Goal:
    goal = Goal(**_plain(data.model_dump()))
    return _create(session, ctx, goal, "goal.created", {"title": goal.title})


def create_project(session: Session, data: ProjectCreate, ctx: Ctx) -> Project:
    _require(session, Goal, data.goal_id, "goal_id")
    project = Project(**_plain(data.model_dump()))
    return _create(session, ctx, project, "project.created", {"name": project.name, "goal_id": project.goal_id})


def create_task(session: Session, data: TaskCreate, ctx: Ctx) -> Task:
    _require(session, Project, data.project_id, "project_id")
    task = Task(**_plain(data.model_dump()))
    return _create(session, ctx, task, "task.created", {"title": task.title, "priority": task.priority, "project_id": task.project_id})


def create_contact(session: Session, data: ContactCreate, ctx: Ctx) -> Contact:
    if data.email and session.exec(select(Contact).where(Contact.email == data.email)).first():
        raise Conflict("A contact with this email already exists")
    contact = Contact(**_plain(data.model_dump()))
    return _create(session, ctx, contact, "contact.created", {"name": contact.name}, "A contact with this email already exists")


def _update(
    session: Session,
    ctx: Ctx,
    model: type[SQLModel],
    entity_id: str,
    data: BaseModel,
    event_type: str,
    nullable: set[str],
    conflict: str | None = None,
) -> Any:
    item = session.get(model, entity_id)
    if item is None:
        raise NotFound(f"{model.__name__} {entity_id!r} not found")
    changes = _plain(data.model_dump(exclude_unset=True))
    diff: dict[str, list[Any]] = {}
    for field, value in changes.items():
        if value is None and field not in nullable:
            raise Invalid(f"{field} cannot be null")
        old = getattr(item, field)
        if old != value:
            diff[field] = [_jsonable(old), _jsonable(value)]
            setattr(item, field, value)
    if not diff:
        return item
    if isinstance(item, Task) and "status" in diff:
        item.completed_at = now() if item.status == Status.done.value else None
    item.updated_at = now()
    session.add(item)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise Conflict(conflict or "The change conflicts with existing data") from exc
    record_event(session, event_type, ctx.actor, item.id, {"changes": diff}, ctx.request_id)
    _commit(session, conflict)
    session.refresh(item)
    return item


def update_goal(session: Session, goal_id: str, data: GoalUpdate, ctx: Ctx) -> Goal:
    return _update(session, ctx, Goal, goal_id, data, "goal.updated", {"target_date"})


def update_project(session: Session, project_id: str, data: ProjectUpdate, ctx: Ctx) -> Project:
    if "goal_id" in data.model_fields_set:
        _require(session, Goal, data.goal_id, "goal_id")
    return _update(session, ctx, Project, project_id, data, "project.updated", {"goal_id"})


def update_task(session: Session, task_id: str, data: TaskUpdate, ctx: Ctx) -> Task:
    if "project_id" in data.model_fields_set:
        _require(session, Project, data.project_id, "project_id")
    return _update(session, ctx, Task, task_id, data, "task.updated", {"project_id", "due_at"})


def update_contact(session: Session, contact_id: str, data: ContactUpdate, ctx: Ctx) -> Contact:
    return _update(session, ctx, Contact, contact_id, data, "contact.updated", {"email"}, "A contact with this email already exists")


def complete_task(session: Session, task_id: str, ctx: Ctx) -> Task:
    return update_task(session, task_id, TaskUpdate(status=Status.done), ctx)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def contains(column: Any, text: str) -> Any:
    return col(column).ilike(f"%{_escape(text)}%", escape="\\")


def equals(column: Any, text: str) -> Any:
    return col(column).ilike(_escape(text), escape="\\")


def find_open_tasks(session: Session, query: str, limit: int = 6) -> list[Task]:
    """Exact (case-insensitive) title match wins; otherwise substring matches."""
    open_tasks = select(Task).where(col(Task.status) != Status.done.value)
    exact = session.exec(open_tasks.where(equals(Task.title, query))).all()
    if exact:
        return list(exact)
    return list(session.exec(open_tasks.where(contains(Task.title, query)).limit(limit)).all())


def find_project_by_name(session: Session, name: str) -> Project | None:
    return session.exec(select(Project).where(equals(Project.name, name))).first()


def search(session: Session, query: str, limit: int = 10) -> dict[str, list[dict[str, Any]]]:
    goals = select(Goal).where(contains(Goal.title, query) | contains(Goal.description, query)).limit(limit)
    projects = select(Project).where(contains(Project.name, query) | contains(Project.objective, query)).limit(limit)
    tasks = select(Task).where(contains(Task.title, query) | contains(Task.description, query)).limit(limit)
    contacts = select(Contact).where(contains(Contact.name, query) | contains(Contact.organisation, query) | contains(Contact.email, query)).limit(limit)
    return {
        "goals": [{"id": g.id, "title": g.title, "status": g.status} for g in session.exec(goals)],
        "projects": [{"id": p.id, "title": p.name, "status": p.status} for p in session.exec(projects)],
        "tasks": [{"id": t.id, "title": t.title, "status": t.status} for t in session.exec(tasks)],
        "contacts": [{"id": c.id, "title": c.name, "status": c.relationship} for c in session.exec(contacts)],
    }
