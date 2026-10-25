"""Connector contract and registry. Sandbox mode can only ever resolve the dry-run connector."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ConnectorNotConfigured(Exception):
    pass


@dataclass(frozen=True)
class ConnectorResult:
    ok: bool
    dry_run: bool
    detail: str
    external_id: str | None = None
    retryable: bool = False  # True only when the provider provably did not act, so a retry cannot duplicate the effect
    outcome_unknown: bool = False  # True when an external side effect may have happened but cannot be confirmed


@dataclass(frozen=True)
class HealthResult:
    ok: bool
    detail: str


class Connector(Protocol):
    name: str
    integrations: tuple[str, ...]  # Integration registry entries this connector backs

    def supports(self, action_type: str, target: str) -> bool: ...

    def execute(self, *, action_type: str, target: str, payload: dict[str, Any], idempotency_key: str) -> ConnectorResult: ...

    def health(self) -> HealthResult: ...


class SandboxConnector:
    name = "sandbox"
    integrations: tuple[str, ...] = ()

    def supports(self, action_type: str, target: str) -> bool:
        return True

    def execute(self, *, action_type: str, target: str, payload: dict[str, Any], idempotency_key: str) -> ConnectorResult:
        return ConnectorResult(ok=True, dry_run=True, detail=f"Dry run: {action_type} -> {target} (nothing left the sandbox)")

    def health(self) -> HealthResult:
        return HealthResult(True, "sandbox dry run")


class ConnectorRegistry:
    def __init__(self, sandbox: bool) -> None:
        self.sandbox = sandbox
        self._connectors: list[Connector] = []

    def register(self, connector: Connector) -> None:
        self._connectors.append(connector)

    @property
    def connectors(self) -> tuple[Connector, ...]:
        return tuple(self._connectors)

    def resolve(self, action_type: str, target: str) -> Connector:
        """First registered connector that supports the action and target. Sandbox always gets the dry run."""
        if self.sandbox:
            return SandboxConnector()
        for connector in self._connectors:
            if connector.supports(action_type, target):
                return connector
        raise ConnectorNotConfigured(f"no connector is configured for {action_type} to {target!r}")
