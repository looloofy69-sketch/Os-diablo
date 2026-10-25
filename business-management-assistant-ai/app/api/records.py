from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response
from sqlmodel import col, select

from app.api.deps import OperatorCtx, PageDep, SessionDep, ViewerCtx, paginate
from app.domain.models import (
    Contact,
    ContactCreate,
    ContactUpdate,
    Goal,
    GoalCreate,
    GoalUpdate,
    Priority,
    Project,
    ProjectCreate,
    ProjectUpdate,
    Status,
    Task,
    TaskCreate,
    TaskUpdate,
    now,
)
from app.errors import NotFound
from app.services import records

router = APIRouter(prefix="/api", tags=["records"])


def _one(session: SessionDep, model: Any, entity_id: str) -> Any:
    item = session.get(model, entity_id)
    if item is None:
        raise NotFound(f"{model.__name__} {entity_id!r} not found")
    return item


# ---- goals
@router.post("/goals", response_model=Goal, status_code=201)
def create_goal(payload: GoalCreate, session: SessionDep, ctx: OperatorCtx) -> Any:
    return records.create_goal(session, payload, ctx)


@router.get("/goals", response_model=list[Goal])
def list_goals(session: SessionDep, _: ViewerCtx, page: PageDep, response: Response, status: Status | None = None) -> Any:
    statement = select(Goal).order_by(col(Goal.created_at).desc())
    if status:
        statement = statement.where(col(Goal.status) == status.value)
    return paginate(session, statement, page, response)


@router.get("/goals/{goal_id}", response_model=Goal)
def get_goal(goal_id: str, session: SessionDep, _: ViewerCtx) -> Any:
    return _one(session, Goal, goal_id)


@router.patch("/goals/{goal_id}", response_model=Goal)
def update_goal(goal_id: str, payload: GoalUpdate, session: SessionDep, ctx: OperatorCtx) -> Any:
    return records.update_goal(session, goal_id, payload, ctx)


# ---- projects
@router.post("/projects", response_model=Project, status_code=201)
def create_project(payload: ProjectCreate, session: SessionDep, ctx: OperatorCtx) -> Any:
    return records.create_project(session, payload, ctx)


@router.get("/projects", response_model=list[Project])
def list_projects(session: SessionDep, _: ViewerCtx, page: PageDep, response: Response, status: Status | None = None, goal_id: str | None = None) -> Any:
    statement = select(Project).order_by(col(Project.created_at).desc())
    if status:
        statement = statement.where(col(Project.status) == status.value)
    if goal_id:
        statement = statement.where(col(Project.goal_id) == goal_id)
    return paginate(session, statement, page, response)


@router.get("/projects/{project_id}", response_model=Project)
def get_project(project_id: str, session: SessionDep, _: ViewerCtx) -> Any:
    return _one(session, Project, project_id)


@router.patch("/projects/{project_id}", response_model=Project)
def update_project(project_id: str, payload: ProjectUpdate, session: SessionDep, ctx: OperatorCtx) -> Any:
    return records.update_project(session, project_id, payload, ctx)


# ---- tasks
@router.post("/tasks", response_model=Task, status_code=201)
def create_task(payload: TaskCreate, session: SessionDep, ctx: OperatorCtx) -> Any:
    return records.create_task(session, payload, ctx)


@router.get("/tasks", response_model=list[Task])
def list_tasks(
    session: SessionDep,
    _: ViewerCtx,
    page: PageDep,
    response: Response,
    status: Status | None = None,
    priority: Priority | None = None,
    project_id: str | None = None,
    owner: str | None = None,
    overdue: Annotated[bool, Query(description="Only open tasks past their due date")] = False,
    due_before: datetime | None = None,
) -> Any:
    statement = select(Task).order_by(col(Task.created_at).desc())
    if status:
        statement = statement.where(col(Task.status) == status.value)
    if priority:
        statement = statement.where(col(Task.priority) == priority.value)
    if project_id:
        statement = statement.where(col(Task.project_id) == project_id)
    if owner:
        statement = statement.where(col(Task.owner) == owner)
    if overdue:
        statement = statement.where(col(Task.status) != Status.done.value, col(Task.due_at) < now())
    if due_before:
        statement = statement.where(col(Task.due_at) < due_before)
    return paginate(session, statement, page, response)


@router.get("/tasks/{task_id}", response_model=Task)
def get_task(task_id: str, session: SessionDep, _: ViewerCtx) -> Any:
    return _one(session, Task, task_id)


@router.patch("/tasks/{task_id}", response_model=Task)
def update_task(task_id: str, payload: TaskUpdate, session: SessionDep, ctx: OperatorCtx) -> Any:
    return records.update_task(session, task_id, payload, ctx)


@router.post("/tasks/{task_id}/complete", response_model=Task)
def complete_task(task_id: str, session: SessionDep, ctx: OperatorCtx) -> Any:
    return records.complete_task(session, task_id, ctx)


# ---- contacts
@router.post("/contacts", response_model=Contact, status_code=201)
def create_contact(payload: ContactCreate, session: SessionDep, ctx: OperatorCtx) -> Any:
    return records.create_contact(session, payload, ctx)


@router.get("/contacts", response_model=list[Contact])
def list_contacts(session: SessionDep, _: ViewerCtx, page: PageDep, response: Response, q: str | None = None, relationship: str | None = None) -> Any:
    statement = select(Contact).order_by(col(Contact.created_at).desc())
    if q:
        statement = statement.where(records.contains(Contact.name, q) | records.contains(Contact.organisation, q) | records.contains(Contact.email, q))
    if relationship:
        statement = statement.where(col(Contact.relationship) == relationship)
    return paginate(session, statement, page, response)


@router.get("/contacts/{contact_id}", response_model=Contact)
def get_contact(contact_id: str, session: SessionDep, _: ViewerCtx) -> Any:
    return _one(session, Contact, contact_id)


@router.patch("/contacts/{contact_id}", response_model=Contact)
def update_contact(contact_id: str, payload: ContactUpdate, session: SessionDep, ctx: OperatorCtx) -> Any:
    return records.update_contact(session, contact_id, payload, ctx)


# ---- search
@router.get("/search")
def search(session: SessionDep, _: ViewerCtx, q: Annotated[str, Query(min_length=1, max_length=200)], limit: Annotated[int, Query(ge=1, le=50)] = 10) -> dict[str, list[dict[str, Any]]]:
    return records.search(session, q, limit)
