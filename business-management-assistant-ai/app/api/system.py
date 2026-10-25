from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlmodel import Session, col, select

from app.api.deps import AdminCtx, OperatorCtx, PageDep, SessionDep, ViewerCtx, paginate
from app.domain.chat_models import ChatMessage, ChatRequest, ChatResponse, Conversation
from app.domain.models import AuditEvent, Integration, PlanRequest
from app.errors import NotFound
from app.services import approvals
from app.services.audit import verify_database_chain
from app.services.briefing import build_briefing
from app.services.integrations import check_integration
from app.services.local_models import catalog, get_model, local_status, task_recommendations

router = APIRouter()


@router.get("/health", tags=["system"])
def health(request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    return {"status": "ok", "environment": settings.environment, "version": settings.version}


@router.get("/ready", tags=["system"])
def ready(request: Request) -> Any:
    try:
        with Session(request.app.state.engine) as session:
            session.connection().execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable", "database": "down"})
    return {"status": "ready", "database": "up"}


@router.get("/api/me", tags=["system"])
def me(request: Request, ctx: ViewerCtx) -> dict[str, Any]:
    settings = request.app.state.settings
    return {
        "name": ctx.actor,
        "role": ctx.principal.role.value,
        "open_mode": ctx.principal.open_mode,
        "assistant_mode": settings.effective_assistant_mode if request.app.state.pool is not None else "rules",
        "sandbox": settings.is_sandbox,
    }


@router.get("/api/briefing", tags=["briefing"])
def briefing(request: Request, session: SessionDep, _: ViewerCtx) -> dict[str, Any]:
    approvals.housekeeping(session)
    return build_briefing(session, request.app.state.settings.environment)


# ---- chat
@router.post("/api/chat", response_model=ChatResponse, tags=["chat"])
def chat_with_business(payload: ChatRequest, request: Request, session: SessionDep, ctx: OperatorCtx) -> Any:
    """Chat with the assistant: safe commands run directly, external actions become approval requests."""
    return request.app.state.chat.respond(session, payload, ctx)


@router.get("/api/conversations", response_model=list[Conversation], tags=["chat"])
def list_conversations(session: SessionDep, _: ViewerCtx, page: PageDep, response: Response) -> Any:
    return paginate(session, select(Conversation).order_by(col(Conversation.updated_at).desc()), page, response)


@router.get("/api/conversations/{conversation_id}/messages", response_model=list[ChatMessage], tags=["chat"])
def conversation_messages(conversation_id: str, session: SessionDep, _: ViewerCtx, page: PageDep, response: Response) -> Any:
    if session.get(Conversation, conversation_id) is None:
        raise NotFound("Conversation not found")
    statement = select(ChatMessage).where(col(ChatMessage.conversation_id) == conversation_id).order_by(col(ChatMessage.id))
    return paginate(session, statement, page, response)


# ---- integrations
@router.get("/api/integrations", response_model=list[Integration], tags=["integrations"])
def list_integrations(session: SessionDep, _: ViewerCtx, page: PageDep, response: Response, category: str | None = None) -> Any:
    statement = select(Integration).order_by(col(Integration.name))
    if category:
        statement = statement.where(col(Integration.category) == category)
    return paginate(session, statement, page, response)


@router.post("/api/integrations/{integration_id}/check", response_model=Integration, tags=["integrations"])
def integration_check(integration_id: str, request: Request, session: SessionDep, ctx: AdminCtx) -> Any:
    item = session.get(Integration, integration_id)
    if item is None:
        raise NotFound("Integration not found")
    return check_integration(session, item, ctx, request.app.state.connectors)


@router.get("/api/connectors", tags=["integrations"])
def list_connectors(request: Request, _: ViewerCtx) -> dict[str, Any]:
    registry = request.app.state.connectors
    return {
        "live": not registry.sandbox,
        "connectors": [{"name": c.name, "integrations": list(c.integrations)} for c in registry.connectors],
        "note": "Sandbox: configured connectors are not used; every approved action is a dry run." if registry.sandbox else "Approved actions run through these connectors.",
    }


# ---- AI manager and local models
@router.post("/api/ai/plan", tags=["ai"])
def ai_plan(payload: PlanRequest, request: Request, _: OperatorCtx) -> dict[str, Any]:
    return request.app.state.router.plan(payload.request, payload.capability)


@router.get("/api/ai/models", tags=["ai"])
def ai_models(request: Request, _: ViewerCtx) -> dict[str, Any]:
    """Every model currently discovered or configured, with health, measured score and latency. May probe endpoints on first call."""
    pool = request.app.state.pool
    return {"enabled": pool is not None, "models": pool.status() if pool else []}


@router.post("/api/ai/models/refresh", tags=["ai"])
def ai_models_refresh(request: Request, _: AdminCtx) -> dict[str, Any]:
    pool = request.app.state.pool
    if pool is None:
        return {"enabled": False, "models": []}
    pool.refresh(force=True)
    return {"enabled": True, "models": pool.status()}


@router.get("/api/ai/capabilities", tags=["ai"])
def ai_capabilities(request: Request, _: ViewerCtx) -> dict[str, Any]:
    return request.app.state.router.capability_catalog()


@router.get("/api/local-models", tags=["local-models"])
def local_models(request: Request, _: ViewerCtx) -> dict[str, Any]:
    root = request.app.state.settings.models_dir
    return {"models": [{**item, "status": local_status(get_model(item["key"]), root)} for item in catalog()]}


@router.get("/api/local-models/recommend", tags=["local-models"])
def recommend_local_models(task: Annotated[str, Query(min_length=1, max_length=60)], _: ViewerCtx) -> dict[str, Any]:
    return {"task": task, "recommendations": task_recommendations(task)}


@router.get("/api/local-models/{model_key}/status", tags=["local-models"])
def local_model_status(model_key: str, request: Request, _: ViewerCtx) -> dict[str, Any]:
    try:
        model = get_model(model_key)
    except KeyError as exc:
        raise NotFound("Local model not found") from exc
    return local_status(model, request.app.state.settings.models_dir)


# ---- audit
@router.get("/api/audit", response_model=list[AuditEvent], tags=["audit"])
def audit(
    session: SessionDep,
    _: AdminCtx,
    page: PageDep,
    response: Response,
    actor: str | None = None,
    event_type: str | None = None,
    target: str | None = None,
) -> Any:
    statement = select(AuditEvent).order_by(col(AuditEvent.id).desc())
    if actor:
        statement = statement.where(col(AuditEvent.actor) == actor)
    if event_type:
        statement = statement.where(col(AuditEvent.event_type) == event_type)
    if target:
        statement = statement.where(col(AuditEvent.target) == target)
    return paginate(session, statement, page, response)


@router.get("/api/audit/verify", tags=["audit"])
def audit_verify(session: SessionDep, _: AdminCtx) -> dict[str, Any]:
    """Recompute the hash chain. Any edited, removed or reordered entry is reported by id."""
    result = verify_database_chain(session)
    return {"ok": result.ok, "checked": result.checked, "first_bad_id": result.first_bad_id, "reason": result.reason}
