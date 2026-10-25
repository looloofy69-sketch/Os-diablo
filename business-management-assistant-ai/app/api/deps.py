from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Header, Query, Request, Response
from sqlmodel import Session, func, select

from app.errors import Forbidden, Unauthorized
from app.security import Principal, Role, extract_secret
from app.services.context import Ctx


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine, expire_on_commit=False) as session:
        yield session


def current_principal(
    request: Request,
    x_api_key: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    principal = request.app.state.auth.authenticate(extract_secret(x_api_key, authorization))
    if principal is None:
        raise Unauthorized("Missing or invalid API key. Send it as X-API-Key or Authorization: Bearer.")
    request.state.principal = principal.name
    return principal


def ctx_for(minimum: Role) -> Callable[..., Ctx]:
    def dependency(request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> Ctx:
        if not principal.allows(minimum):
            raise Forbidden(f"This action requires the {minimum.value} role; you have {principal.role.value}")
        return Ctx(principal, getattr(request.state, "request_id", None))

    return dependency


SessionDep = Annotated[Session, Depends(get_session)]
ViewerCtx = Annotated[Ctx, Depends(ctx_for(Role.viewer))]
OperatorCtx = Annotated[Ctx, Depends(ctx_for(Role.operator))]
AdminCtx = Annotated[Ctx, Depends(ctx_for(Role.admin))]


@dataclass(frozen=True)
class PageParams:
    limit: int
    offset: int


def page_params(limit: Annotated[int, Query(ge=1, le=200)] = 50, offset: Annotated[int, Query(ge=0)] = 0) -> PageParams:
    return PageParams(limit, offset)


PageDep = Annotated[PageParams, Depends(page_params)]


def paginate(session: Session, statement: Any, page: PageParams, response: Response) -> list[Any]:
    """Apply limit/offset and expose the unpaginated count as ``X-Total-Count``."""
    total = session.exec(select(func.count()).select_from(statement.order_by(None).subquery())).one()
    response.headers["X-Total-Count"] = str(total)
    return list(session.exec(statement.limit(page.limit).offset(page.offset)).all())
