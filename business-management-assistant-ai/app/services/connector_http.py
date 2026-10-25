"""Slack incoming-webhook and signed generic webhook connectors. Stdlib only."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.services.connectors import ConnectorResult, HealthResult
from app.services.netutil import check_outbound_url

MIN_SECRET_LENGTH = 16


class HttpNetworkError(Exception):
    def __init__(self, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


HttpPost = Callable[[str, dict[str, str], bytes, float], tuple[int, str]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Action payloads and signature headers must not be forwarded to redirect targets."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirect)


def urllib_post(url: str, headers: dict[str, str], body: bytes, timeout: float) -> tuple[int, str]:
    """Return ``(status, text)`` for any HTTP response. Raise HttpNetworkError when no response arrived."""
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with _NO_REDIRECT_OPENER.open(request, timeout=timeout) as response:  # noqa: S310 - URL validated at configuration time
            return response.status, response.read(4000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read(2000).decode("utf-8", "replace")
        finally:
            exc.close()
    except urllib.error.URLError as exc:
        reached_nothing = isinstance(exc.reason, (ConnectionRefusedError, socket.gaierror))
        raise HttpNetworkError(f"request failed ({type(exc.reason).__name__})", retryable=reached_nothing) from exc
    except (TimeoutError, OSError) as exc:
        raise HttpNetworkError(f"request failed ({type(exc).__name__}); outcome unknown", retryable=False) from exc


def interpret(status: int, text: str) -> ConnectorResult:
    """Classify an HTTP response conservatively for external-side-effect safety.

    A 2xx response confirms success. Clear request/auth/validation rejections are
    treated as non-retryable failures. Rate-limit, conflict, timeout and server
    responses are not proof that a side effect did not happen, so they are marked
    outcome-unknown and must not be retried automatically.
    """
    if 200 <= status < 300:
        external_id = None
        try:
            payload = json.loads(text) if text.strip().startswith("{") else None
            value = payload.get("id") if isinstance(payload, dict) else None
            external_id = str(value) if value is not None else None
        except (ValueError, AttributeError):
            pass
        return ConnectorResult(ok=True, dry_run=False, detail=f"delivered (HTTP {status})", external_id=external_id)

    # A generic receiver's non-2xx response does not prove that it performed no
    # side effect before returning the status. Do not infer certainty from status
    # classes or human-readable response text.
    if 100 <= status <= 599:
        return ConnectorResult(
            ok=False,
            dry_run=False,
            detail=f"receiver returned HTTP {status}; outcome unknown; verify the destination before retrying",
            outcome_unknown=True,
        )
    return ConnectorResult(
        ok=False,
        dry_run=False,
        detail=f"invalid HTTP status {status}; outcome unknown; verify the destination before retrying",
        outcome_unknown=True,
    )


def _network_failure(exc: HttpNetworkError) -> ConnectorResult:
    return ConnectorResult(
        ok=False,
        dry_run=False,
        detail=str(exc),
        retryable=exc.retryable,
        outcome_unknown=not exc.retryable,
    )


class SlackConnector:
    name = "slack-webhook"
    integrations = ("Team Chat",)
    action_types = ("message.send", "content.publish")

    def __init__(self, webhook_url: str, post: HttpPost = urllib_post, timeout: float = 10.0, allow_insecure_remote: bool = False) -> None:
        self._url = check_outbound_url(webhook_url, allow_insecure_remote)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 300:
            raise ValueError("Slack webhook timeout must be a finite number in (0, 300]")
        self._post, self._timeout = post, float(timeout)

    def __repr__(self) -> str:
        return "SlackConnector(url=<hidden>)"

    def supports(self, action_type: str, target: str) -> bool:
        return action_type in self.action_types and target.strip().lower().startswith("slack")

    def execute(self, *, action_type: str, target: str, payload: dict[str, Any], idempotency_key: str) -> ConnectorResult:
        text = str(payload.get("text") or payload.get("body") or payload.get("subject") or "").strip()
        if not text:
            return ConnectorResult(False, False, "slack messages need 'text' (or 'body') in the payload; amend the request before approving")
        try:
            status, reply = self._post(self._url, {"content-type": "application/json"}, json.dumps({"text": text[:3000]}).encode(), self._timeout)
        except HttpNetworkError as exc:
            return _network_failure(exc)
        return interpret(status, reply)

    def health(self) -> HealthResult:
        return HealthResult(True, "webhook configured (not probed: Slack has no safe test call)")


@dataclass(frozen=True)
class WebhookRoute:
    name: str
    prefix: str  # action type or family, e.g. "crm" or "campaign.launch"
    url: str
    secret: str

    def __repr__(self) -> str:
        return f"WebhookRoute(name={self.name!r}, prefix={self.prefix!r})"

    def matches(self, action_type: str) -> bool:
        return action_type == self.prefix or action_type.startswith(self.prefix + ".")


def parse_webhook_routes(raw: str, allow_insecure_remote: bool = False) -> list[WebhookRoute]:
    if not raw.strip():
        return []
    try:
        items = json.loads(raw)
    except ValueError as exc:
        raise ValueError("WEBHOOK_ROUTES must be valid JSON") from exc
    if not isinstance(items, list):
        raise ValueError("WEBHOOK_ROUTES must be a JSON array")
    routes = []
    seen_prefixes: set[str] = set()
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict) or not {"prefix", "url", "secret"} <= set(item) or set(item) - {"name", "prefix", "url", "secret"}:
            raise ValueError(f"WEBHOOK_ROUTES[{index}] needs exactly prefix, url, secret (and optional name)")
        prefix_value, url_value, secret_value = item["prefix"], item["url"], item["secret"]
        name_value = item.get("name", f"route-{index}")
        if not isinstance(prefix_value, str) or not prefix_value.strip() or not re.fullmatch(r"[A-Za-z0-9_.-]+", prefix_value.strip()):
            raise ValueError(f"WEBHOOK_ROUTES[{index}]: prefix must be a non-empty action-family string")
        prefix = prefix_value.strip().lower()
        if prefix in seen_prefixes:
            raise ValueError(f"WEBHOOK_ROUTES[{index}]: duplicate prefix {prefix!r}")
        seen_prefixes.add(prefix)
        if not isinstance(url_value, str):
            raise ValueError(f"WEBHOOK_ROUTES[{index}]: url must be a string")
        if not isinstance(secret_value, str) or secret_value != secret_value.strip() or len(secret_value) < MIN_SECRET_LENGTH:
            raise ValueError(f"WEBHOOK_ROUTES[{index}]: secret must be a string of at least {MIN_SECRET_LENGTH} characters without surrounding whitespace")
        if not isinstance(name_value, str) or not name_value.strip() or len(name_value.strip()) > 100:
            raise ValueError(f"WEBHOOK_ROUTES[{index}]: name must be a non-empty string of at most 100 characters")
        try:
            url = check_outbound_url(url_value, allow_insecure_remote)
        except ValueError as exc:
            raise ValueError(f"WEBHOOK_ROUTES[{index}]: {exc}") from exc
        routes.append(WebhookRoute(name_value.strip(), prefix, url, secret_value))
    return routes


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


class SignedWebhookConnector:
    """POSTs approved actions as signed JSON to your own automation (n8n, Zapier, Make, a service). Receivers verify
    ``X-BMA-Signature`` = sha256 HMAC of ``"<X-BMA-Timestamp>.<raw body>"`` and de-duplicate on ``Idempotency-Key``."""

    name = "signed-webhook"
    integrations = ("Webhooks", "Workflow Automation")

    def __init__(self, routes: list[WebhookRoute], post: HttpPost = urllib_post, timeout: float = 15.0, clock: Callable[[], float] = time.time) -> None:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 300:
            raise ValueError("Signed webhook timeout must be a finite number in (0, 300]")
        self.routes, self._post, self._timeout, self._clock = routes, post, float(timeout), clock

    def _route(self, action_type: str) -> WebhookRoute | None:
        matches = [r for r in self.routes if r.matches(action_type)]
        return max(matches, key=lambda r: len(r.prefix), default=None)

    def supports(self, action_type: str, target: str) -> bool:
        return self._route(action_type) is not None

    def execute(self, *, action_type: str, target: str, payload: dict[str, Any], idempotency_key: str) -> ConnectorResult:
        route = self._route(action_type)
        if route is None:
            return ConnectorResult(False, False, f"no webhook route for {action_type}")
        body = json.dumps({"id": idempotency_key, "action_type": action_type, "target": target, "payload": payload}, sort_keys=True, separators=(",", ":")).encode()
        stamp = str(int(self._clock()))
        headers = {
            "content-type": "application/json", "idempotency-key": idempotency_key, "x-bma-timestamp": stamp,
            "x-bma-signature": sign(route.secret, stamp, body), "user-agent": "business-assistant/0.4.1",
        }
        try:
            status, reply = self._post(route.url, headers, body, self._timeout)
        except HttpNetworkError as exc:
            return _network_failure(exc)
        return interpret(status, reply)

    def health(self) -> HealthResult:
        return HealthResult(bool(self.routes), f"{len(self.routes)} route(s) configured (not probed)")
