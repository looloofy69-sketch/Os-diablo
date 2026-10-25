from fastapi.testclient import TestClient

from app.main import create_app
from app.services.llm import ChatClient, LLMError
from app.services.model_setup import build_pool
from tests.api.conftest import ADMIN, KEYS, OPERATOR, VIEWER, Script, as_, make_settings, plan


def pool_for(settings, env, listing, scripts=None):
    """Discovery with fake network: ``listing`` maps endpoint name -> model ids (or an exception)."""
    scripts = scripts or {}

    def lister(endpoint):
        value = listing.get(endpoint.name, LLMError("connection refused"))
        if isinstance(value, Exception):
            raise value
        return value

    return build_pool(settings, env, with_scores=False, lister=lister,
                      client_factory=lambda ep, model: ChatClient(ep.provider, model, ep.base_url, ep.api_key or "k", transport=scripts.get(f"{ep.name}/{model}", Script())))


def test_everything_reachable_is_discovered_and_everything_else_is_reported_down():
    settings = make_settings(llm_auto_discover=True, environment="staging", api_keys=KEYS)
    env = {"ANTHROPIC_API_KEY": "sk-ant-test"}
    pool = pool_for(settings, env, {"ollama": ["qwen3:8b", "nomic-embed-text"], "anthropic": ["claude-opus-5-5", "claude-haiku-5-5"]})
    with TestClient(create_app(settings, model_pool=pool)) as c:
        rows = c.get("/api/ai/models", headers=as_(VIEWER)).json()["models"]
        available = {(r["endpoint"], r["model"]) for r in rows if r["model"] and r["available"]}
        assert ("ollama", "qwen3:8b") in available and ("anthropic", "claude-opus-5-5") in available
        assert all(r["model"] != "nomic-embed-text" for r in rows)
        down = {r["endpoint"]: r["detail"] for r in rows if r["model"] is None}
        assert {"lmstudio", "llamacpp", "local-8001"} <= set(down)
        assert c.post("/api/ai/models/refresh", headers=as_(OPERATOR)).status_code == 403
        assert c.post("/api/ai/models/refresh", headers=as_(ADMIN)).json()["enabled"] is True


def test_models_appearing_later_are_picked_up_on_refresh():
    settings = make_settings(llm_auto_discover=True)
    listing = {}
    pool = pool_for(settings, {}, listing)
    with TestClient(create_app(settings, model_pool=pool)) as c:
        assert [r for r in c.get("/api/ai/models").json()["models"] if r["model"]] == []
        listing["ollama"] = ["llama3.1:8b"]
        rows = c.post("/api/ai/models/refresh").json()["models"]
        assert [r["model"] for r in rows if r["model"]] == ["llama3.1:8b"]


def test_with_nothing_reachable_the_rules_answer_silently():
    settings = make_settings(llm_auto_discover=True)
    with TestClient(create_app(settings, model_pool=pool_for(settings, {}, {}))) as c:
        reply = c.post("/api/chat", json={"message": "Thinking about pricing"}).json()
        assert reply["via"] == "rules" and "built-in commands" not in reply["message"]


def test_discovered_models_actually_serve_requests_and_hosted_can_be_forbidden():
    settings = make_settings(llm_auto_discover=True)
    env = {"OPENAI_API_KEY": "sk-test"}
    local = Script(plan("Tell me more."))
    hosted = Script(plan("From the hosted model."))
    scripts = {"ollama/qwen3:8b": local, "openai/gpt-5": hosted}
    pool = pool_for(settings, env, {"ollama": ["qwen3:8b"], "openai": ["gpt-5"]}, scripts)
    with TestClient(create_app(settings, model_pool=pool)) as c:
        assert c.post("/api/chat", json={"message": "Thinking about pricing"}).json()["message"] == "From the hosted model."
    private = make_settings(llm_auto_discover=True, llm_allow_hosted=False)
    scripts = {"ollama/qwen3:8b": Script(plan("Local only.")), "openai/gpt-5": Script(plan("must not be used"))}
    pool = pool_for(private, env, {"ollama": ["qwen3:8b"], "openai": ["gpt-5"]}, scripts)
    with TestClient(create_app(private, model_pool=pool)) as c:
        assert c.post("/api/chat", json={"message": "Thinking about pricing"}).json()["message"] == "Local only."
        assert scripts["openai/gpt-5"].calls == []


def test_models_endpoint_when_the_assistant_is_rules_only():
    with TestClient(create_app(make_settings())) as c:
        assert c.get("/api/ai/models").json() == {"enabled": False, "models": []}
        assert c.get("/api/me").json()["assistant_mode"] == "rules"
