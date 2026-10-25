import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.api.conftest import ADMIN, ADMIN2, OPERATOR, VIEWER, as_, make_settings


def test_requests_without_valid_key_are_rejected(secured):
    for headers in ({}, as_("wrong"), {"authorization": "Bearer nope"}):
        r = secured.get("/api/briefing", headers=headers)
        assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    assert secured.get("/api/briefing", headers={"authorization": f"Bearer {VIEWER}"}).status_code == 200
    assert secured.get("/health").status_code == 200


def test_role_matrix(secured):
    assert secured.get("/api/tasks", headers=as_(VIEWER)).status_code == 200
    assert secured.post("/api/tasks", json={"title": "x"}, headers=as_(VIEWER)).status_code == 403
    assert secured.post("/api/tasks", json={"title": "x"}, headers=as_(OPERATOR)).status_code == 201
    assert secured.get("/api/audit", headers=as_(OPERATOR)).status_code == 403
    assert secured.get("/api/audit", headers=as_(ADMIN)).status_code == 200
    assert secured.post("/api/chat", json={"message": "brief me"}, headers=as_(VIEWER)).status_code == 403


def test_operator_cannot_review_and_requester_cannot_self_approve(secured):
    body = {"action_type": "message.send", "target": "a@b.io", "reason": "r"}
    item = secured.post("/api/actions/propose", json=body, headers=as_(ADMIN)).json()
    assert item["requested_by"] == "root"
    assert secured.post(f"/api/approvals/{item['id']}/decision", json={"decision": "approved"}, headers=as_(OPERATOR)).status_code == 403
    own = secured.post(f"/api/approvals/{item['id']}/decision", json={"decision": "approved"}, headers=as_(ADMIN))
    assert own.status_code == 403 and "own request" in own.json()["error"]["message"]
    ok = secured.post(f"/api/approvals/{item['id']}/decision", json={"decision": "approved"}, headers=as_(ADMIN2))
    assert ok.status_code == 200 and ok.json()["reviewed_by"] == "second"


def test_assistant_requests_can_be_approved_by_the_requesting_admin(secured):
    r = secured.post("/api/chat", json={"message": "publish the launch post"}, headers=as_(ADMIN)).json()
    ok = secured.post(f"/api/approvals/{r['approval_id']}/decision", json={"decision": "approved"}, headers=as_(ADMIN))
    assert ok.status_code == 200


def test_audit_records_authenticated_actor(secured):
    secured.post("/api/goals", json={"title": "g"}, headers=as_(OPERATOR))
    assert secured.get("/api/audit", params={"event_type": "goal.created"}, headers=as_(ADMIN)).json()[0]["actor"] == "ops"


def test_non_sandbox_requires_keys_and_strong_secrets():
    with pytest.raises(RuntimeError):
        create_app(make_settings(environment="production", api_keys=""))
    with pytest.raises(ValueError):
        create_app(make_settings(environment="production", api_keys="root:admin:short"))
    with pytest.raises(RuntimeError):
        create_app(make_settings(llm_base_url="http://127.0.0.1:8001"))


def test_docs_hidden_outside_sandbox(secured):
    assert secured.get("/docs").status_code == 404
    assert secured.get("/openapi.json").status_code == 404


def test_live_mode_fails_closed_without_connector():
    with TestClient(create_app(make_settings(environment="staging", api_keys=f"root:admin:{ADMIN},second:admin:{ADMIN2}"))) as c:
        item = c.post("/api/actions/propose", json={"action_type": "message.send", "target": "a@b.io", "reason": "r"}, headers=as_(ADMIN)).json()
        c.post(f"/api/approvals/{item['id']}/decision", json={"decision": "approved"}, headers=as_(ADMIN2))
        out = c.post(f"/api/approvals/{item['id']}/execute", headers=as_(ADMIN2)).json()
        assert out["status"] == "failed" and "no connector" in out["result"]["detail"]


def test_rate_limit_returns_429_with_retry_after():
    with TestClient(create_app(make_settings(rate_limit_per_minute=3))) as c:
        codes = [c.get("/api/me").status_code for _ in range(5)]
        assert codes[:3] == [200, 200, 200] and codes[-1] == 429
        limited = c.get("/api/me")
        assert limited.headers["retry-after"] and limited.json()["error"]["code"] == "rate_limited"
        assert c.get("/health").status_code == 200  # probes are never limited


def test_schema_guard_refuses_legacy_database(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    sqlite3.connect(path).executescript("CREATE TABLE goal (id TEXT PRIMARY KEY, title TEXT);")
    with pytest.raises(RuntimeError, match="0.1 schema"):
        with TestClient(create_app(make_settings(database_url=f"sqlite:///{path}"))):
            pass


def test_llm_configuration_is_validated():
    from tests.api.conftest import KEYS

    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        create_app(make_settings(llm_provider="anthropic", llm_model="claude-x"))
    with pytest.raises(RuntimeError, match="ASSISTANT_MODE"):
        create_app(make_settings(assistant_mode="llm"))  # auto-discovery is off in the test settings and nothing else is configured
    with pytest.raises(RuntimeError, match="https"):
        create_app(make_settings(environment="staging", api_keys=KEYS, llm_model="m", llm_base_url="http://api.example.com:8000"))
    with pytest.raises(RuntimeError, match="LLM_BASE_URL"):
        create_app(make_settings(llm_model="m"))
    with pytest.raises(RuntimeError, match="LLM_ENDPOINTS"):
        create_app(make_settings(llm_endpoints="[not json"))
    app = create_app(make_settings(llm_model="m", llm_base_url="http://127.0.0.1:9"))
    assert app.state.pool is not None and app.state.settings.effective_assistant_mode == "hybrid"
    assert create_app(make_settings()).state.pool is None


def test_empty_environment_variables_count_as_unset(monkeypatch):
    for name in ("ASSISTANT_MODE", "LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY", "API_KEYS"):
        monkeypatch.setenv(name, "")
    from app.core import Settings

    settings = Settings(_env_file=None, database_url="sqlite://", llm_auto_discover=False)
    settings.validate_runtime()
    assert settings.effective_assistant_mode == "rules" and not settings.llm_enabled
