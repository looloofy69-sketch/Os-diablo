"""Authentication, authorisation and rate limiting primitives (stdlib only)."""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    viewer = "viewer"
    operator = "operator"
    admin = "admin"


_RANK = {Role.viewer: 0, Role.operator: 1, Role.admin: 2}


@dataclass(frozen=True)
class Principal:
    name: str
    role: Role
    open_mode: bool = False

    def allows(self, minimum: Role) -> bool:
        return _RANK[self.role] >= _RANK[minimum]


@dataclass(frozen=True)
class ApiKey:
    name: str
    role: Role
    digest: bytes


def _digest(secret: str) -> bytes:
    return hashlib.sha256(secret.encode("utf-8")).digest()


def parse_api_keys(raw: str, min_secret_length: int = 0) -> list[ApiKey]:
    """Parse ``name:role:secret`` entries separated by commas. Secrets may contain ``:``."""
    keys: list[ApiKey] = []
    seen: set[str] = set()
    for entry in (part.strip() for part in raw.split(",")):
        if not entry:
            continue
        parts = entry.split(":", 2)
        if len(parts) != 3:
            raise ValueError("API key entries must look like name:role:secret")
        name, role_text, secret = (part.strip() for part in parts)
        if not name or not secret:
            raise ValueError("API key entries need a non-empty name and secret")
        try:
            role = Role(role_text)
        except ValueError as exc:
            raise ValueError(f"unknown role {role_text!r} for key {name!r}; use viewer, operator or admin") from exc
        if name in seen:
            raise ValueError(f"duplicate API key name {name!r}")
        if len(secret) < min_secret_length:
            raise ValueError(f"secret for key {name!r} must be at least {min_secret_length} characters")
        seen.add(name)
        keys.append(ApiKey(name=name, role=role, digest=_digest(secret)))
    return keys


def extract_secret(x_api_key: str | None, authorization: str | None) -> str | None:
    if x_api_key:
        return x_api_key.strip() or None
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
    return None


class AuthRegistry:
    """Constant-time key lookup. With no keys configured the registry is in open (sandbox) mode."""

    def __init__(self, keys: list[ApiKey]) -> None:
        self._keys = tuple(keys)

    @property
    def open_mode(self) -> bool:
        return not self._keys

    def authenticate(self, secret: str | None) -> Principal | None:
        if self.open_mode:
            return Principal(name="founder", role=Role.admin, open_mode=True)
        if not secret:
            return None
        candidate = _digest(secret)
        matched: ApiKey | None = None
        for key in self._keys:  # no early exit: timing does not reveal which key matched
            if hmac.compare_digest(candidate, key.digest):
                matched = key
        return Principal(name=matched.name, role=matched.role) if matched else None


class RateLimiter:
    """Token bucket per key. ``per_minute == 0`` disables limiting."""

    def __init__(
        self,
        per_minute: int,
        burst: int | None = None,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 10_000,
    ) -> None:
        self.rate = per_minute / 60.0
        self.capacity = float(burst if burst is not None else max(per_minute, 1))
        self.enabled = per_minute > 0
        self._clock = clock
        self._max_keys = max_keys
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, float]:
        """Return ``(allowed, retry_after_seconds)``."""
        if not self.enabled:
            return True, 0.0
        now = self._clock()
        with self._lock:
            tokens, last = self._buckets.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens >= 1.0:
                self._buckets[key] = (tokens - 1.0, now)
                self._prune(now)
                return True, 0.0
            self._buckets[key] = (tokens, now)
            return False, (1.0 - tokens) / self.rate

    def _prune(self, now: float) -> None:
        if len(self._buckets) <= self._max_keys:
            return
        refill = self.capacity / self.rate if self.rate else 0.0
        self._buckets = {k: v for k, v in self._buckets.items() if now - v[1] < refill}
        if len(self._buckets) > self._max_keys:
            oldest = sorted(self._buckets.items(), key=lambda item: item[1][1])
            for key, _ in oldest[: len(oldest) // 2]:
                del self._buckets[key]
