from __future__ import annotations

import logging
import math
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from app.api import routers
from app.core import Settings, build_engine, init_db
from app.errors import DomainError
from app.security import AuthRegistry, RateLimiter, parse_api_keys
from app.services.ai import ModelRouter
from app.services.chat import BusinessChat
from app.services.connector_setup import build_notifier, build_registry
from app.services.connectors import ConnectorRegistry
from app.services.integrations import seed_integrations, sync_connector_integrations
from app.services.model_pool import ModelPool
from app.services.model_setup import build_pool
from app.services.notifier import Notifier
from app.services.policy import PolicyEngine

access_log = logging.getLogger("bma.access")
error_log = logging.getLogger("bma.error")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_UI_CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"


def _find_static(settings: Settings) -> Path | None:
    candidates = [Path(settings.static_dir)] if settings.static_dir else []
    candidates += [Path(__file__).resolve().parent.parent / "static", Path.cwd() / "static"]
    return next((path for path in candidates if (path / "index.html").is_file()), None)


def _error_body(code: str, message: str, request_id: str | None, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}, "request_id": request_id}}


def create_app(
    settings: Settings | None = None,
    model_pool: ModelPool | None = None,
    connectors: ConnectorRegistry | None = None,
    notifier: Notifier | None = None,
) -> FastAPI:
    settings = settings or Settings()
    settings.validate_runtime()

    engine = build_engine(settings.database_url)
    policy = PolicyEngine(high_value_threshold=settings.high_value_threshold)
    pool = model_pool if model_pool is not None else build_pool(settings)
    router = ModelRouter(
        mode=settings.environment, models_dir=settings.models_dir, llm_configured=pool is not None, assistant_mode=settings.effective_assistant_mode if pool is not None else "rules"
    )
    registry = connectors if connectors is not None else build_registry(settings)
    notices = notifier if notifier is not None else build_notifier(settings, registry)
    limiter = RateLimiter(settings.rate_limit_per_minute)
    static_dir = _find_static(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        init_db(engine, create=settings.schema_auto_create)
        with Session(engine) as session:
            seed_integrations(session)
            try:
                sync_connector_integrations(session, registry)
            except Exception:  # noqa: BLE001 - a dead SMTP server must not stop the app from starting
                error_log.exception("connector health check failed at startup")
        yield
        engine.dispose()

    docs = settings.is_sandbox or settings.enable_docs
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="Safe business operating system control plane",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.policy = policy
    app.state.router = router
    app.state.pool = pool
    app.state.connectors = registry
    app.state.notifier = notices
    app.state.auth = AuthRegistry(parse_api_keys(settings.api_keys))
    app.state.chat = BusinessChat(router, policy, settings, registry, pool, notices)

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(status_code=exc.status_code, content=_error_body(exc.code, exc.message, request_id, exc.details))

    @app.middleware("http")
    async def request_context(request: Request, call_next: Any) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _REQUEST_ID.fullmatch(incoming) else uuid4().hex
        request.state.request_id = request_id
        path = request.url.path
        started = time.perf_counter()

        response: Response
        allowed, retry_after = (True, 0.0)
        if path.startswith("/api/"):
            allowed, retry_after = limiter.check(request.client.host if request.client else "unknown")
        if not allowed:
            response = JSONResponse(
                status_code=429,
                content=_error_body("rate_limited", "Too many requests", request_id),
                headers={"Retry-After": str(math.ceil(retry_after))},
            )
        else:
            try:
                response = await call_next(request)
            except Exception:
                error_log.exception("unhandled error request_id=%s path=%s", request_id, path)
                response = JSONResponse(status_code=500, content=_error_body("internal_error", "Unexpected server error", request_id))

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        if path == "/" or path.startswith("/static/"):
            response.headers["Content-Security-Policy"] = _UI_CSP
        elapsed_ms = (time.perf_counter() - started) * 1000
        access_log.info(
            "request_id=%s principal=%s %s %s -> %s %.1fms",
            request_id, getattr(request.state, "principal", "-"), request.method, path, response.status_code, elapsed_ms,
        )
        return response

    for api_router in routers:
        app.include_router(api_router)

    if static_dir is not None:
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

        @app.get("/", include_in_schema=False)
        def home() -> FileResponse:
            return FileResponse(static_dir / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
