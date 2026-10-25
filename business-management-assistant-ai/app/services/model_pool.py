"""Use every model that is reachable: discovery, ranking, health-aware failover. Stdlib only.

Nothing here assumes a chosen model. Endpoints (local servers, hosted APIs) are probed at runtime, their models
are ranked by measured evaluation scores when available and by a name-based heuristic otherwise, and a request
cascades through the best healthy candidates until one produces a valid result.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.services.llm import (\n    ANTHROPIC_DEFAULT_URL,\n    PROVIDERS,\n    BudgetExceeded,\n    CallBudget,\n    ChatClient,\n    LLMError,\n    LLMReply,\n    list_models,\n)
from app.services.netutil import is_private_host

ROLES = frozenset({"plan", "compose"})
NON_CHAT = re.compile(r"embed|rerank|whisper|tts|moderation|dall-?e|imagen|gpt-image|\basr\b|transcribe|speech|guard", re.I)
LOCAL_PROBES = (("ollama", "http://127.0.0.1:11434"), ("lmstudio", "http://127.0.0.1:1234"), ("llamacpp", "http://127.0.0.1:8080"), ("local-8001", "http://127.0.0.1:8001"))
HOSTED_ENV = (
    ("anthropic", "ANTHROPIC_API_KEY", "anthropic", ANTHROPIC_DEFAULT_URL),
    ("openai", "OPENAI_API_KEY", "openai_compatible", "https://api.openai.com/v1"),
    ("openrouter", "OPENROUTER_API_KEY", "openai_compatible", "https://openrouter.ai/api/v1"),
    ("groq", "GROQ_API_KEY", "openai_compatible", "https://api.groq.com/openai/v1"),
    ("together", "TOGETHER_API_KEY", "openai_compatible", "https://api.together.xyz/v1"),
    ("mistral", "MISTRAL_API_KEY", "openai_compatible", "https://api.mistral.ai/v1"),
)
BREAKER_THRESHOLD = 3


@dataclass(frozen=True)
class EndpointConfig:
    name: str
    provider: str
    base_url: str
    api_key: str | None = None
    models: tuple[str, ...] = ()  # empty: discover at runtime
    roles: frozenset[str] = ROLES
    priority: int = 100  # lower is tried first, ahead of quality
    timeout: float = 30.0
    max_tokens: int = 800
    daily_limit: int = 0
    hosted: bool = True

    def __repr__(self) -> str:  # never print credentials
        return f"EndpointConfig(name={self.name!r}, provider={self.provider!r}, base_url={self.base_url!r}, models={self.models!r})"


def parse_endpoints(raw: str, env: Mapping[str, str] | None = None, *, allow_insecure_remote: bool = True) -> list[EndpointConfig]:
    """Parse and validate the ``LLM_ENDPOINTS`` JSON array.

    Secrets should normally be referenced through ``api_key_env``. Numeric values,
    booleans, model names, roles and URL structure are validated before any network
    call can be made.
    """
    env = env if env is not None else os.environ
    if not isinstance(raw, str):
        raise ValueError("LLM_ENDPOINTS must be a JSON string")
    if not raw.strip():
        return []
    try:
        items = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("LLM_ENDPOINTS must be valid JSON") from exc
    if not isinstance(items, list):
        raise ValueError("LLM_ENDPOINTS must be a JSON array")

    allowed = {"name", "provider", "base_url", "api_key", "api_key_env", "model", "models", "roles", "priority", "timeout", "max_tokens", "daily_limit", "hosted"}
    endpoints: list[EndpointConfig] = []
    for index, item in enumerate(items, start=1):
        prefix = f"LLM_ENDPOINTS[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{prefix} must be an object")
        unknown = set(item) - allowed
        if unknown:
            raise ValueError(f"{prefix}: unknown keys {sorted(unknown)}")

        name_value = item.get("name", f"endpoint-{index}")
        if not isinstance(name_value, str) or not name_value.strip() or len(name_value.strip()) > 100:
            raise ValueError(f"{prefix}: name must be a non-empty string of at most 100 characters")
        name = name_value.strip()

        provider = item.get("provider", "openai_compatible")
        if not isinstance(provider, str) or provider not in PROVIDERS:
            raise ValueError(f"{prefix}: provider must be one of {', '.join(PROVIDERS)}")

        base_value = item.get("base_url") or (ANTHROPIC_DEFAULT_URL if provider == "anthropic" else "")
        if not isinstance(base_value, str):
            raise ValueError(f"{prefix}: base_url must be a string URL")
        base = base_value.strip().rstrip("/")
        parsed = urlparse(base)
        try:
            _ = parsed.port  # force validation of malformed ports
        except ValueError as exc:
            raise ValueError(f"{prefix}: base_url has an invalid port") from exc
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError(f"{prefix}: base_url must be an http(s) URL without embedded credentials")
        if any(character.isspace() or ord(character) < 33 for character in parsed.netloc):
            raise ValueError(f"{prefix}: base_url host must not contain whitespace or control characters")
        if parsed.query or parsed.fragment:
            raise ValueError(f"{prefix}: base_url must not contain a query or fragment")
        if not allow_insecure_remote and parsed.scheme == "http" and not is_private_host(base):
            raise ValueError(f"{prefix}: remote endpoints must use https outside sandbox")

        api_key_value = item.get("api_key")
        api_key_env = item.get("api_key_env")
        if api_key_value is not None and (not isinstance(api_key_value, str) or not api_key_value.strip()):
            raise ValueError(f"{prefix}: api_key must be a non-empty string when supplied")
        if api_key_env is not None:
            if not isinstance(api_key_env, str) or not api_key_env.strip():
                raise ValueError(f"{prefix}: api_key_env must be a non-empty environment-variable name")
            if api_key_value is not None:
                raise ValueError(f"{prefix}: use api_key or api_key_env, not both")
        key = (api_key_value.strip() if isinstance(api_key_value, str) else None) or (env.get(api_key_env.strip()) if api_key_env else None)
        if key is not None and (not isinstance(key, str) or not key.strip()):
            raise ValueError(f"{prefix}: resolved API key must be a non-empty string")
        if api_key_env and not key:
            raise ValueError(f"{prefix}: environment variable {api_key_env} is not set")
        if provider == "anthropic" and not key:
            raise ValueError(f"{prefix}: the anthropic provider needs api_key or api_key_env")

        model_value, models_value = item.get("model"), item.get("models")
        if model_value is not None and models_value is not None:
            raise ValueError(f"{prefix}: specify model or models, not both")
        if model_value is not None and (not isinstance(model_value, str) or not model_value.strip()):
            raise ValueError(f"{prefix}: model must be a non-empty string")
        if models_value is None:
            models = (model_value.strip(),) if isinstance(model_value, str) else ()
        else:
            if not isinstance(models_value, list) or any(not isinstance(m, str) or not m.strip() for m in models_value):
                raise ValueError(f"{prefix}: models must be a list of non-empty strings")
            models = tuple(m.strip() for m in models_value)
            if len(set(models)) != len(models):
                raise ValueError(f"{prefix}: models must not contain duplicates")

        roles_value = item.get("roles", sorted(ROLES))
        if not isinstance(roles_value, list) or any(not isinstance(role, str) for role in roles_value):
            raise ValueError(f"{prefix}: roles must be a list containing plan and/or compose")
        roles = frozenset(role.strip() for role in roles_value)
        if not roles or not roles <= ROLES:
            raise ValueError(f"{prefix}: roles must be a non-empty subset of {sorted(ROLES)}")

        priority = item.get("priority", 100)
        timeout = item.get("timeout", 30.0)
        max_tokens = item.get("max_tokens", 800)
        daily_limit = item.get("daily_limit", 0)
        hosted = item.get("hosted", not is_private_host(base))
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise ValueError(f"{prefix}: priority must be an integer")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 300:
            raise ValueError(f"{prefix}: timeout must be a finite number in (0, 300]")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 32000:
            raise ValueError(f"{prefix}: max_tokens must be an integer from 1 to 32000")
        if isinstance(daily_limit, bool) or not isinstance(daily_limit, int) or daily_limit < 0:
            raise ValueError(f"{prefix}: daily_limit must be a non-negative integer")
        if not isinstance(hosted, bool):
            raise ValueError(f"{prefix}: hosted must be a JSON boolean")

        endpoints.append(EndpointConfig(
            name=name, provider=provider, base_url=base, api_key=key, models=models,
            roles=roles, priority=priority, timeout=float(timeout), max_tokens=max_tokens,
            daily_limit=daily_limit, hosted=hosted,
        ))

    names = [endpoint.name for endpoint in endpoints]
    if len(names) != len(set(names)):
        raise ValueError("LLM_ENDPOINTS names must be unique")
    return endpoints


def auto_endpoints(env: Mapping[str, str], probe_local: bool = True) -> list[EndpointConfig]:
    """Endpoints implied by the environment: provider API keys and well-known local server ports. Keys go only to their own hosts."""
    found = [
        EndpointConfig(name=name, provider=provider, base_url=base, api_key=env[var], hosted=True)
        for name, var, provider, base in HOSTED_ENV
        if env.get(var)
    ]
    if probe_local:
        found += [EndpointConfig(name=name, provider="openai_compatible", base_url=url, hosted=False, timeout=60.0) for name, url in LOCAL_PROBES]
    return found


def merge_endpoints(explicit: list[EndpointConfig], auto: list[EndpointConfig]) -> list[EndpointConfig]:
    used_urls = {e.base_url.rstrip("/") for e in explicit}
    used_names = {e.name for e in explicit}
    extra = [e for e in auto if e.base_url.rstrip("/") not in used_urls and e.name not in used_names]
    return [*explicit, *extra]


MIN_GRADED_SCORE_ROWS = 10


def load_scores(path: str | Path) -> dict[str, float]:
    """Load trustworthy accuracy values in [0, 1]. Small samples are not ranking evidence."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    scores: dict[str, float] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not key.strip() or not isinstance(value, dict):
            continue
        # Scores influence model selection, so a bare legacy float or an accuracy
        # without a graded-sample count is not sufficient ranking evidence.
        graded = value.get("graded")
        number = value.get("accuracy")
        if isinstance(graded, bool) or not isinstance(graded, int) or graded < MIN_GRADED_SCORE_ROWS:
            continue
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            continue
        score = float(number)
        if math.isfinite(score) and 0.0 <= score <= 1.0:
            scores[key] = score
    return scores


def quality_hint(model: str) -> float:
    """Rough 0-100 capability guess from the model name. Measured scores always override it."""
    name = model.lower()
    score = 50.0
    if match := re.search(r"(\d+(?:\.\d+)?)\s*b(?![a-z])", name):
        score = min(90.0, 20.0 + 12.0 * math.log2(float(match.group(1)) + 1))
    for pattern, value in ((r"opus|mythos|fable", 95), (r"sonnet", 85), (r"gpt-5|\bo3\b|\bo4\b", 90), (r"gpt-4", 80), (r"haiku", 60)):
        if re.search(pattern, name):
            score = float(value)
            break
    if re.search(r"mini|nano|flash|small|lite|tiny|instant", name):
        score -= 15
    return max(0.0, min(100.0, score))


@dataclass(frozen=True)
class Candidate:
    endpoint: EndpointConfig
    model: str

    @property
    def key(self) -> str:
        return f"{self.endpoint.name}/{self.model}"


@dataclass
class _State:
    consecutive_failures: int = 0
    down_until: float = 0.0
    ewma_latency: float | None = None
    ok: int = 0
    failed: int = 0
    quality_failures: int = 0
    last_error: str | None = None


@dataclass(frozen=True)
class Attempt:
    model: str
    ok: bool
    reason: str | None = None


@dataclass(frozen=True)
class PoolResult:
    text: str
    key: str
    model: str
    endpoint: str
    usage: dict[str, int]
    attempts: tuple[Attempt, ...]
    parsed: Any = None


class NoModelAvailable(LLMError):
    """Nothing is reachable right now (no endpoint answered discovery, or all are cooling down)."""


class PoolExhausted(LLMError):
    def __init__(self, attempts: list[Attempt]) -> None:
        super().__init__("no model produced a valid result: " + "; ".join(f"{a.model}: {a.reason}" for a in attempts if not a.ok)[:300])
        self.attempts = tuple(attempts)


ClientFactory = Callable[[EndpointConfig, str], Any]
Lister = Callable[[EndpointConfig], list[str]]
Check = Callable[[str], tuple[bool, Any, str | None]]
Repair = Callable[[list[dict[str, str]], str, str], list[dict[str, str]]]


def _default_client(endpoint: EndpointConfig, model: str) -> ChatClient:
    return ChatClient(endpoint.provider, model, endpoint.base_url, endpoint.api_key, endpoint.timeout, endpoint.max_tokens)


def _default_lister(endpoint: EndpointConfig) -> list[str]:
    return list_models(endpoint.provider, endpoint.base_url, endpoint.api_key, timeout=3.0)


class ModelPool:
    def __init__(
        self,
        endpoints: list[EndpointConfig],
        *,
        scores: dict[str, float] | None = None,
        prefer: str = "quality",
        allow_hosted: bool = True,
        max_cascade: int = 3,
        refresh_seconds: float = 300.0,
        per_endpoint_cap: int = 4,
        min_plan_score: float = 0.5,
        clock: Callable[[], float] = time.monotonic,
        client_factory: ClientFactory | None = None,
        lister: Lister | None = None,
        budget: CallBudget | None = None,
    ) -> None:
        if prefer not in {"quality", "local", "hosted"}:
            raise ValueError("prefer must be one of: quality, local, hosted")
        if isinstance(max_cascade, bool) or not isinstance(max_cascade, int) or max_cascade < 1:
            raise ValueError("max_cascade must be a positive integer")
        if isinstance(per_endpoint_cap, bool) or not isinstance(per_endpoint_cap, int) or per_endpoint_cap < 1:
            raise ValueError("per_endpoint_cap must be a positive integer")
        if isinstance(refresh_seconds, bool) or not isinstance(refresh_seconds, (int, float)) or not math.isfinite(refresh_seconds) or refresh_seconds <= 0:
            raise ValueError("refresh_seconds must be a finite positive number")
        if isinstance(min_plan_score, bool) or not isinstance(min_plan_score, (int, float)) or not math.isfinite(min_plan_score) or not 0 <= min_plan_score <= 1:
            raise ValueError("min_plan_score must be between 0 and 1")
        endpoint_names = [endpoint.name for endpoint in endpoints]
        if any(not isinstance(name, str) or not name.strip() for name in endpoint_names):
            raise ValueError("endpoint names must be non-empty strings")
        if len(endpoint_names) != len(set(endpoint_names)):
            raise ValueError("endpoint names must be unique")
        for endpoint in endpoints:
            if endpoint.provider not in PROVIDERS:
                raise ValueError(f"unsupported provider for endpoint {endpoint.name!r}")
            if not endpoint.roles or not endpoint.roles <= ROLES:
                raise ValueError(f"endpoint {endpoint.name!r} has invalid roles")
            if isinstance(endpoint.priority, bool) or not isinstance(endpoint.priority, int):
                raise ValueError(f"endpoint {endpoint.name!r} priority must be an integer")
            if isinstance(endpoint.timeout, bool) or not isinstance(endpoint.timeout, (int, float)) or not math.isfinite(endpoint.timeout) or not 0 < endpoint.timeout <= 300:
                raise ValueError(f"endpoint {endpoint.name!r} timeout must be in (0, 300]")
            if isinstance(endpoint.max_tokens, bool) or not isinstance(endpoint.max_tokens, int) or not 1 <= endpoint.max_tokens <= 32000:
                raise ValueError(f"endpoint {endpoint.name!r} max_tokens must be 1..32000")
            if isinstance(endpoint.daily_limit, bool) or not isinstance(endpoint.daily_limit, int) or endpoint.daily_limit < 0:
                raise ValueError(f"endpoint {endpoint.name!r} daily_limit must be non-negative")
        self.endpoints = endpoints
        self.scores: dict[str, float] = {}
        for key, value in (scores or {}).items():
            if isinstance(key, str) and key.strip() and not isinstance(value, bool) and isinstance(value, (int, float)):
                score = float(value)
                if math.isfinite(score) and 0 <= score <= 1:
                    self.scores[key] = score
        self.prefer, self.allow_hosted, self.max_cascade = prefer, allow_hosted, max_cascade
        self.refresh_seconds, self.per_endpoint_cap, self.min_plan_score = float(refresh_seconds), per_endpoint_cap, float(min_plan_score)
        self._clock = clock
        self._client_factory = client_factory or _default_client
        self._lister = lister or _default_lister
        self.budget = budget
        self._endpoint_budgets = {e.name: CallBudget(e.daily_limit) for e in endpoints if e.daily_limit > 0}
        self._discovered: dict[str, list[str]] = {}
        self._discovery_error: dict[str, str] = {}
        self._last_refresh: float | None = None
        self._state: dict[str, _State] = {}
        self._clients: dict[str, Any] = {}
        self._lock = threading.RLock()
        self._refresh_condition = threading.Condition(self._lock)
        self._refreshing = False

    # -------------------------------------------------------------- discovery
    def refresh(self, force: bool = False) -> None:
        """Refresh model discovery once per interval and coalesce concurrent first requests.

        Callers arriving while discovery is in progress wait for that refresh instead
        of observing an empty, half-initialized pool. Endpoint probes run concurrently;
        one failed probe preserves the last-known model list for that endpoint.
        """
        with self._refresh_condition:
            while self._refreshing:
                self._refresh_condition.wait()
                # The in-flight refresh satisfied this caller, including force callers.
                return
            now = self._clock()
            if not force and self._last_refresh is not None and now - self._last_refresh < self.refresh_seconds:
                return
            targets = [e for e in self.endpoints if not e.models]
            if not targets:
                self._last_refresh = now
                return
            self._refreshing = True

        def probe(endpoint: EndpointConfig) -> tuple[str, list[str] | None, str | None]:
            try:
                models = self._lister(endpoint)
                if not isinstance(models, list) or any(not isinstance(model, str) for model in models):
                    return endpoint.name, None, "invalid model-list response"
                return endpoint.name, models, None
            except Exception as exc:  # provider adapters may raise transport or parsing errors
                return endpoint.name, None, f"{type(exc).__name__}: {exc}"[:200]

        try:
            with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
                results = list(pool.map(probe, targets))
            with self._refresh_condition:
                for name, models, error in results:
                    if models is not None:
                        # Deduplicate while preserving provider order before ranking.
                        self._discovered[name] = list(dict.fromkeys(m.strip() for m in models if m.strip()))
                        self._discovery_error.pop(name, None)
                    else:
                        self._discovery_error[name] = error or "unreachable"
                self._last_refresh = self._clock()
        finally:
            with self._refresh_condition:
                self._refreshing = False
                self._refresh_condition.notify_all()

    # -------------------------------------------------------------- ranking
    def _models_of(self, endpoint: EndpointConfig) -> list[str]:
        if endpoint.models:
            return [model for model in endpoint.models if not NON_CHAT.search(model)]
        models = [m for m in self._discovered.get(endpoint.name, []) if not NON_CHAT.search(m)]
        models.sort(key=lambda m: -quality_hint(m))
        return models[: self.per_endpoint_cap]

    def _quality(self, candidate: Candidate) -> float:
        measured = self.scores.get(candidate.key, self.scores.get(candidate.model))
        state = self._state.get(candidate.key)
        penalty = 12.0 * min(state.quality_failures, 4) if state else 0.0
        return (measured * 100.0 if measured is not None else quality_hint(candidate.model)) - penalty

    def _endpoint_exhausted(self, name: str) -> bool:
        budget = self._endpoint_budgets.get(name)
        return budget is not None and budget.exhausted()

    def _is_down(self, key: str) -> bool:
        state = self._state.get(key)
        return bool(state and state.down_until > self._clock())

    def candidates(self, role: str, prefer_key: str | None = None) -> list[Candidate]:
        self.refresh()
        with self._lock:
            pool = [Candidate(e, m) for e in self.endpoints if role in e.roles and (self.allow_hosted or not e.hosted) for m in self._models_of(e)]
            pool = [c for c in pool if not self._is_down(c.key) and not self._endpoint_exhausted(c.endpoint.name)]
            if role == "plan":
                pool = [c for c in pool if self.scores.get(c.key, self.scores.get(c.model, 1.0)) >= self.min_plan_score]
            tier = {"local": lambda c: int(c.endpoint.hosted), "hosted": lambda c: int(not c.endpoint.hosted)}.get(self.prefer, lambda c: 0)
            pool.sort(key=lambda c: (tier(c), c.endpoint.priority, -self._quality(c), c.key))
            if prefer_key:
                pool.sort(key=lambda c: c.key != prefer_key)  # stable: preferred first, order otherwise kept
            return pool

    def available(self) -> bool:
        return bool(self.candidates("plan"))

    # -------------------------------------------------------------- calls
    def _client(self, candidate: Candidate) -> Any:
        with self._lock:
            if candidate.key not in self._clients:
                self._clients[candidate.key] = self._client_factory(candidate.endpoint, candidate.model)
            return self._clients[candidate.key]

    def _call(self, candidate: Candidate, system: str, messages: list[dict[str, str]]) -> LLMReply:
        if self.budget is not None and not self.budget.try_acquire():
            raise BudgetExceeded("daily model call limit reached")
        endpoint_budget = self._endpoint_budgets.get(candidate.endpoint.name)
        if endpoint_budget is not None and not endpoint_budget.try_acquire():
            raise LLMError(f"daily call limit reached for {candidate.endpoint.name}")  # skip this endpoint, keep cascading
        started = self._clock()
        try:
            reply = self._client(candidate).complete(system, messages)
        except BudgetExceeded:
            raise
        except LLMError as exc:
            self._record_failure(candidate.key, str(exc))
            raise
        self._record_success(candidate.key, self._clock() - started)
        return reply

    def _record_success(self, key: str, latency: float) -> None:
        with self._lock:
            state = self._state.setdefault(key, _State())
            state.consecutive_failures, state.down_until, state.ok = 0, 0.0, state.ok + 1
            state.ewma_latency = latency if state.ewma_latency is None else 0.7 * state.ewma_latency + 0.3 * latency

    def _record_failure(self, key: str, reason: str) -> None:
        with self._lock:
            state = self._state.setdefault(key, _State())
            state.consecutive_failures += 1
            state.failed += 1
            state.last_error = reason[:200]
            if state.consecutive_failures >= BREAKER_THRESHOLD:
                state.down_until = self._clock() + min(60.0 * 2 ** (state.consecutive_failures - BREAKER_THRESHOLD), 600.0)

    def _record_quality(self, key: str, good: bool) -> None:
        with self._lock:
            state = self._state.setdefault(key, _State())
            state.quality_failures = 0 if good else state.quality_failures + 1

    @staticmethod
    def _sum(total: dict[str, int], more: dict[str, int]) -> None:
        for name, value in more.items():
            total[name] = total.get(name, 0) + value

    def complete(self, role: str, system: str, messages: list[dict[str, str]], *, prefer_key: str | None = None) -> PoolResult:
        candidates = self.candidates(role, prefer_key)
        if not candidates:
            raise NoModelAvailable("no model is currently reachable")
        attempts: list[Attempt] = []
        for candidate in candidates[: self.max_cascade]:
            try:
                reply = self._call(candidate, system, messages)
            except BudgetExceeded:
                raise
            except LLMError as exc:
                attempts.append(Attempt(candidate.key, False, str(exc)))
                continue
            attempts.append(Attempt(candidate.key, True))
            return PoolResult(reply.text, candidate.key, candidate.model, candidate.endpoint.name, dict(reply.usage), tuple(attempts))
        raise PoolExhausted(attempts)

    def complete_checked(self, role: str, system: str, messages: list[dict[str, str]], check: Check, repair: Repair | None = None) -> PoolResult:
        """Cascade until ``check`` accepts an output. Each candidate gets one repair attempt before the next is tried."""
        candidates = self.candidates(role)
        if not candidates:
            raise NoModelAvailable("no model is currently reachable")
        attempts: list[Attempt] = []
        usage: dict[str, int] = {}
        for candidate in candidates[: self.max_cascade]:
            current = messages
            for round_number in (1, 2):
                try:
                    reply = self._call(candidate, system, current)
                except BudgetExceeded:
                    raise
                except LLMError as exc:
                    attempts.append(Attempt(candidate.key, False, str(exc)))
                    break
                self._sum(usage, reply.usage)
                ok, parsed, error = check(reply.text)
                if ok:
                    self._record_quality(candidate.key, True)
                    attempts.append(Attempt(candidate.key, True))
                    return PoolResult(reply.text, candidate.key, candidate.model, candidate.endpoint.name, usage, tuple(attempts), parsed)
                attempts.append(Attempt(candidate.key, False, f"invalid output: {error}"))
                if round_number == 1 and repair is not None:
                    current = repair(messages, reply.text, error or "invalid")
                    continue
                self._record_quality(candidate.key, False)
                break
        raise PoolExhausted(attempts)

    # -------------------------------------------------------------- introspection
    def client_for(self, candidate: Candidate) -> Any:
        return self._client(candidate)

    def status(self) -> list[dict[str, Any]]:
        self.refresh()
        rows: list[dict[str, Any]] = []
        with self._lock:
            for endpoint in self.endpoints:
                models = self._models_of(endpoint)
                if not models:
                    rows.append({"endpoint": endpoint.name, "model": None, "hosted": endpoint.hosted, "available": False, "detail": self._discovery_error.get(endpoint.name, "no models")})
                for model in models:
                    candidate = Candidate(endpoint, model)
                    state = self._state.get(candidate.key, _State())
                    rows.append({
                        "endpoint": endpoint.name, "model": model, "hosted": endpoint.hosted, "roles": sorted(endpoint.roles),
                        "available": not self._is_down(candidate.key), "quality": round(self._quality(candidate), 1),
                        "measured": candidate.key in self.scores or model in self.scores,
                        "latency_s": None if state.ewma_latency is None else round(state.ewma_latency, 3),
                        "ok": state.ok, "failed": state.failed, "last_error": state.last_error,
                    })
        return rows
