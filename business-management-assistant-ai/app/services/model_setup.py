"""Builds the model pool from settings: explicit endpoints, a pinned model, and runtime auto-discovery."""

from __future__ import annotations

import os
from collections.abc import Mapping

from app.core import Settings
from app.services.llm import ANTHROPIC_DEFAULT_URL, CallBudget
from app.services.model_pool import (
    ClientFactory,
    EndpointConfig,
    Lister,
    ModelPool,
    auto_endpoints,
    load_scores,
    merge_endpoints,
    parse_endpoints,
)
from app.services.netutil import is_private_host


def explicit_endpoints(settings: Settings, env: Mapping[str, str] | None = None) -> list[EndpointConfig]:
    env = env if env is not None else os.environ
    endpoints = parse_endpoints(settings.llm_endpoints, env, allow_insecure_remote=settings.is_sandbox)
    if settings.llm_pinned:
        base = (settings.llm_base_url or ANTHROPIC_DEFAULT_URL).rstrip("/")
        if not settings.is_sandbox and base.startswith("http://") and not is_private_host(base):
            raise ValueError("Outside sandbox, a remote LLM endpoint must use https")
        endpoints.append(
            EndpointConfig(
                name="pinned", provider=settings.llm_provider, base_url=base, api_key=settings.llm_api_key.get_secret_value() if settings.llm_api_key else None,
                models=(settings.llm_model or "",), timeout=settings.llm_timeout_seconds, max_tokens=settings.llm_max_tokens, hosted=not is_private_host(base), priority=50,
            )
        )
    return endpoints


def build_pool(
    settings: Settings,
    env: Mapping[str, str] | None = None,
    *,
    with_scores: bool = True,
    client_factory: ClientFactory | None = None,
    lister: Lister | None = None,
) -> ModelPool | None:
    """None when the assistant is configured for rules only or there is nothing to try. No network calls happen here."""
    env = env if env is not None else os.environ
    if settings.effective_assistant_mode == "rules":
        return None
    endpoints = explicit_endpoints(settings, env)
    if settings.llm_auto_discover:
        endpoints = merge_endpoints(endpoints, auto_endpoints(env, probe_local=True))
    if not endpoints:
        return None
    return ModelPool(
        endpoints,
        scores=load_scores(settings.llm_scores_path) if with_scores else {},
        prefer=settings.llm_prefer,
        allow_hosted=settings.llm_allow_hosted,
        max_cascade=settings.llm_max_cascade,
        refresh_seconds=settings.llm_refresh_seconds,
        min_plan_score=settings.llm_min_plan_score,
        budget=CallBudget(settings.llm_daily_call_limit),
        client_factory=client_factory,
        lister=lister,
    )
