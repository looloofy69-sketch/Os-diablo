"""Provider-neutral chat client (OpenAI-compatible servers and the Anthropic Messages API). Stdlib only."""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlparse

PROVIDERS = ("openai_compatible", "anthropic")
ANTHROPIC_DEFAULT_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)

Transport = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]
GetTransport = Callable[[str, dict[str, str], float], dict[str, Any]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Do not forward API credentials or prompts to an unvalidated redirect target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirect)


class LLMError(Exception):
    """Any provider, transport, budget or response-shape failure. Messages never contain credentials."""


class BudgetExceeded(LLMError):
    """A call cap was reached. Not the provider's fault, so it must not trip health breakers."""


@dataclass(frozen=True)
class LLMReply:
    text: str
    usage: dict[str, int] = field(default_factory=dict)


def strip_reasoning(text: str) -> str:
    return _THINK.sub("", text or "").strip()


def normalise_label(output: str) -> str | None:
    cleaned = strip_reasoning(output).lower()
    match = re.match(r"[a-z_]+", cleaned)
    return match.group(0) if match else None


def is_loopback(url: str) -> bool:
    return (urlparse(url).hostname or "") in LOOPBACK_HOSTS


def _urllib_transport(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with _NO_REDIRECT_OPENER.open(request, timeout=timeout) as response:  # noqa: S310 - scheme validated in ChatClient
            return json.load(response)
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        raise LLMError(f"provider returned HTTP {code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise LLMError(f"provider unreachable: {type(exc).__name__}") from exc


def _urllib_get(url: str, headers: dict[str, str], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with _NO_REDIRECT_OPENER.open(request, timeout=timeout) as response:  # noqa: S310 - scheme validated by callers
            return json.load(response)
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        raise LLMError(f"provider returned HTTP {code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise LLMError(f"provider unreachable: {type(exc).__name__}") from exc


def list_models(
    provider: str, base_url: str | None, api_key: str | None = None, timeout: float = 3.0, transport: GetTransport | None = None
) -> list[str]:
    """Model ids a provider currently serves (OpenAI-compatible ``/v1/models`` or Anthropic ``/v1/models``)."""
    base = (base_url or (ANTHROPIC_DEFAULT_URL if provider == "anthropic" else "")).rstrip("/")
    if not base or urlparse(base).scheme not in {"http", "https"}:
        raise LLMError("invalid base URL")
    if provider == "anthropic":
        url = f"{base}/v1/models?limit=100"
        headers = {"x-api-key": api_key or "", "anthropic-version": ANTHROPIC_VERSION}
    else:
        url = f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"
        headers = {"authorization": f"Bearer {api_key}"} if api_key else {}
    body = (transport or _urllib_get)(url, headers, timeout)
    try:
        return [str(item["id"]) for item in body["data"] if item.get("id")]
    except (KeyError, TypeError, AttributeError) as exc:
        raise LLMError("unexpected model list shape") from exc


class CallBudget:
    """Daily cap on model calls (UTC day, per process). ``limit == 0`` disables the cap."""

    def __init__(self, limit: int, today: Callable[[], date] = lambda: datetime.now(UTC).date()) -> None:
        self.limit = limit
        self._today = today
        self._day = today()
        self._used = 0
        self._lock = threading.Lock()

    def try_acquire(self) -> bool:
        if self.limit <= 0:
            return True
        with self._lock:
            current = self._today()
            if current != self._day:
                self._day, self._used = current, 0
            if self._used >= self.limit:
                return False
            self._used += 1
            return True

    @property
    def used(self) -> int:
        return self._used

    def exhausted(self) -> bool:
        if self.limit <= 0:
            return False
        with self._lock:
            if self._today() != self._day:
                return False
            return self._used >= self.limit


class ChatClient:
    def __init__(
        self,
        provider: str,
        model: str,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
        max_tokens: int = 800,
        transport: Transport | None = None,
        budget: CallBudget | None = None,
    ) -> None:
        if provider not in PROVIDERS:
            raise ValueError(f"unknown LLM provider {provider!r}; use one of {', '.join(PROVIDERS)}")
        base = (base_url or (ANTHROPIC_DEFAULT_URL if provider == "anthropic" else "")).rstrip("/")
        if not base:
            raise ValueError("LLM base URL is required for openai_compatible providers")
        if urlparse(base).scheme not in {"http", "https"}:
            raise ValueError("LLM base URL must use http or https")
        if provider == "anthropic" and not api_key:
            raise ValueError("the anthropic provider requires an API key")
        self.provider, self.model, self.timeout, self.max_tokens = provider, model, timeout, max_tokens
        self._api_key = api_key
        self._transport = transport or _urllib_transport
        self.budget = budget
        if provider == "anthropic":
            self.url = f"{base}/v1/messages"
        else:
            self.url = f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"

    def complete(self, system: str, messages: list[dict[str, str]]) -> LLMReply:
        if self.budget is not None and not self.budget.try_acquire():
            raise BudgetExceeded("daily model call limit reached")
        headers = {"content-type": "application/json"}
        if self.provider == "anthropic":
            headers.update({"x-api-key": self._api_key or "", "anthropic-version": ANTHROPIC_VERSION})
            payload: dict[str, Any] = {"model": self.model, "max_tokens": self.max_tokens, "system": system, "messages": messages}
        else:
            if self._api_key:
                headers["authorization"] = f"Bearer {self._api_key}"
            payload = {
                "model": self.model,
                "messages": [{"role": "system", "content": system}, *messages],
                "temperature": 0,
                "max_tokens": self.max_tokens,
            }
        body = self._transport(self.url, headers, payload, self.timeout)
        try:
            if self.provider == "anthropic":
                text = "".join(block.get("text", "") for block in body["content"] if block.get("type") == "text")
                usage = {"input_tokens": int(body.get("usage", {}).get("input_tokens", 0)), "output_tokens": int(body.get("usage", {}).get("output_tokens", 0))}
            else:
                text = body["choices"][0]["message"]["content"] or ""
                raw = body.get("usage", {})
                usage = {"input_tokens": int(raw.get("prompt_tokens", 0)), "output_tokens": int(raw.get("completion_tokens", 0))}
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
            raise LLMError("unexpected provider response shape") from exc
        text = strip_reasoning(text)
        if not text:
            raise LLMError("empty model response")
        return LLMReply(text=text, usage=usage)
