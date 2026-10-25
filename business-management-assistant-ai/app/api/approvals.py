from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
from sqlmodel import col, select

from app.api.deps import AdminCtx, OperatorCtx, PageDep, SessionDep, ViewerCtx, paginate
from app.domain.models import ActionProposal, ApprovalAmend, ApprovalDecision, ApprovalRequest, ApprovalStatus
from app.errors import NotFound
from app.services import approvals

router = APIRouter(prefix="/api", tags=["approvals"])


@router.get("/policy/actions")
def policy_catalog(request: Request, _: ViewerCtx) -> list[dict[str, Any]]:
    """Every known action type with its risk tier; unknown types are treated as high-risk external."""
    return request.app.state.policy.catalog()


@router.post("/actions/propose", response_model=ApprovalRequest, status_code=201)
def propose_action(payload: ActionProposal, request: Request, response: Response, session: SessionDep, ctx: OperatorCtx) -> Any:
    state = request.app.state
    item, _, created = approvals.propose(session, payload, ctx, state.policy, state.settings, notifier=state.notifier)
    if not created:
        response.status_code = 200  # idempotent replay of an earlier proposal
    return item


@router.get("/approvals", response_model=list[ApprovalRequest])
def list_approvals(session: SessionDep, _: ViewerCtx, page: PageDep, response: Response, status: ApprovalStatus | None = None, risk: str | None = None) -> Any:
    approvals.housekeeping(session)
    statement = select(ApprovalRequest).order_by(col(ApprovalRequest.created_at).desc())
    if status:
        statement = statement.where(col(ApprovalRequest.status) == status.value)
    if risk:
        statement = statement.where(col(ApprovalRequest.risk) == risk)
    return paginate(session, statement, page, response)


@router.get("/approvals/{approval_id}", response_model=ApprovalRequest)
def get_approval(approval_id: str, session: SessionDep, _: ViewerCtx) -> Any:
    approvals.housekeeping(session)
    item = session.get(ApprovalRequest, approval_id)
    if item is None:
        raise NotFound("Approval request not found")
    return item


@router.post("/approvals/{approval_id}/decision", response_model=ApprovalRequest)
def decide_approval(approval_id: str, payload: ApprovalDecision, request: Request, session: SessionDep, ctx: AdminCtx) -> Any:
    state = request.app.state
    return approvals.decide(session, approval_id, payload, ctx, state.settings, state.connectors)


@router.post("/approvals/{approval_id}/execute", response_model=ApprovalRequest)
def execute_approval(approval_id: str, request: Request, session: SessionDep, ctx: AdminCtx) -> Any:
    return approvals.execute(session, approval_id, ctx, request.app.state.connectors)


@router.post("/approvals/{approval_id}/amend", response_model=ApprovalRequest)
def amend_approval(approval_id: str, payload: ApprovalAmend, request: Request, session: SessionDep, ctx: AdminCtx) -> Any:
    """Edit a pending request's target, payload or reason before deciding. Risk is re-evaluated and the change is audited."""
    return approvals.amend(session, approval_id, payload, ctx, request.app.state.policy)


@router.post("/approvals/{approval_id}/retry", response_model=ApprovalRequest)
def retry_approval(approval_id: str, request: Request, session: SessionDep, ctx: AdminCtx, execute: bool = False) -> Any:
    """Re-open a failed request that the connector reported as safe to retry (nothing was done)."""
    state = request.app.state
    item = approvals.retry(session, approval_id, ctx, state.settings)
    return approvals.execute(session, approval_id, ctx, state.connectors) if execute else item
