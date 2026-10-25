import os

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel

from app.core import Settings
from app.core import build_engine
from app.main import create_app

ADMIN = "a" * 32
ADMIN2 = "b" * 32
OPERATOR = "c" * 32
VIEWER = "d" * 32
KEYS = f"root:admin:{ADMIN},second:admin:{ADMIN2},ops:operator:{OPERATOR},eyes:viewer:{VIEWER}"


@pytest.fixture(autouse=True)
def _clean_external_database():
    """With TEST_DATABASE_URL set (PostgreSQL), start every test from an empty schema."""
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        engine = build_engine(url)
        SQLModel.metadata.drop_all(engine)
        engine.dispose()
    yield


def make_settings(**overrides) -> Settings:
    base = {
        "_env_file": None,
        "database_url": os.environ.get("TEST_DATABASE_URL", "sqlite://"),  # CI also runs the suite against PostgreSQL
        "rate_limit_per_minute": 0,
        "llm_auto_discover": False,  # tests must never probe the network
    }
    base.update(overrides)
    return Settings(**base)


@pytest.fixture()
def client():
    """Sandbox, open mode, in-memory database."""
    with TestClient(create_app(make_settings())) as c:
        yield c


@pytest.fixture()
def secured():
    """Staging with API keys: authentication, roles and distinct reviewers are enforced."""
    with TestClient(create_app(make_settings(environment="staging", api_keys=KEYS))) as c:
        yield c


def as_(key: str) -> dict:
    return {"x-api-key": key}


# ---------------------------------------------------------------- scripted model for LLM-path tests
import json as _json  # noqa: E402
from contextlib import contextmanager  # noqa: E402

from app.services.llm import CallBudget, ChatClient, LLMError  # noqa: E402
from app.services.model_pool import EndpointConfig, ModelPool  # noqa: E402


class Script:
    """Stands in for the model provider. Each call consumes the next scripted reply (text or an exception)."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append(payload)
        if not self.replies:
            raise LLMError("script exhausted")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return {"choices": [{"message": {"content": reply}}], "usage": {"prompt_tokens": 100, "completion_tokens": 20}}


def plan(reply="", *steps):
    return _json.dumps({"reply": reply, "steps": [{"tool": t, "args": a} for t, a in steps]})


@contextmanager
def llm_app(script, mode="hybrid", budget=None, **settings):
    """``script`` is one Script (a single model named test-model) or {model_name: Script} for cascade tests."""
    scripts = script if isinstance(script, dict) else {"test-model": script}
    endpoint = EndpointConfig("test", "openai_compatible", "http://127.0.0.1:9", models=tuple(scripts), hosted=False)
    pool = ModelPool(
        [endpoint],
        client_factory=lambda ep, model: ChatClient("openai_compatible", model, ep.base_url, transport=scripts[model]),
        budget=budget,
        scores={f"test/{name}": 1.0 - 0.1 * i for i, name in enumerate(scripts)},  # measured scores fix the cascade order
    )
    cfg = make_settings(llm_model="test-model", llm_base_url="http://127.0.0.1:9", assistant_mode=mode, **settings)
    with TestClient(create_app(cfg, model_pool=pool)) as c:
        yield c


__all__ = ["ADMIN", "ADMIN2", "KEYS", "OPERATOR", "VIEWER", "CallBudget", "LLMError", "Script", "as_", "llm_app", "make_settings", "plan"]
