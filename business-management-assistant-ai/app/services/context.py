from __future__ import annotations

from dataclasses import dataclass

from app.security import Principal, Role


@dataclass(frozen=True)
class Ctx:
    """Who is acting and under which request; threaded through every service call and audit entry."""

    principal: Principal
    request_id: str | None = None

    @property
    def actor(self) -> str:
        return self.principal.name


SYSTEM = Ctx(Principal(name="system", role=Role.admin))
