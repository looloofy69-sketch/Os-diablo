# Current-State Architecture

## Purpose and boundary

This document describes the reviewed business-management-assistant-ai v0.4.0 candidate. OS Diablo is the governance and planning repository; it currently contains this documentation rather than a duplicate application implementation.

## Logical components

1. **API and operator UI** — FastAPI endpoints plus a static browser UI for briefing, chat, tasks, approvals, audit review, integrations and model status.
2. **Domain persistence** — SQLModel/SQLAlchemy entities for goals, projects, tasks, contacts, approvals, integration registry, audit events, conversations and messages.
3. **Planner and policy layer** — interprets requests, chooses tools, evaluates policy, and turns externally consequential work into approval requests.
4. **Model pool** — discovers configured and local endpoints, tracks health/failures, optionally reads evaluation scores and cascades across candidate models.
5. **Connector layer** — sandbox dry-run connector plus live SMTP email, Slack incoming webhook and signed generic HTTP webhook implementations.
6. **Audit and notification services** — audit events/hash-chain verification and approval-waiting notifications.
7. **Persistence and migration** — SQLite-oriented development defaults, PostgreSQL support, Alembic baseline and Docker entrypoint migration flow.

## Existing control flow (conceptual)

User request -> authentication/role gate -> planner and policy evaluation -> safe internal operation OR approval request -> authorized execution -> connector result -> audit event and operator visibility.

For external actions, the system must distinguish:
- known rejection before delivery;
- confirmed delivery;
- retryable failure where the provider did nothing;
- unknown outcome where the request may have reached the external system.

Unknown outcomes must not be blindly retried.

## Configuration and trust boundaries

- Local sandbox intentionally supports dry-run actions and open authentication when no API keys are configured.
- Non-sandbox environments require API keys at startup.
- Hosted model use is enabled by default in the reviewed settings; deployments must explicitly decide whether business context may leave the network.
- Connector URLs and credentials form an outbound trust boundary. URL validation, secret management, recipient allowlists and provider permissions must be maintained and tested.
- The integration registry includes aspirational/catalogued families. A registry row is not evidence of a live provider adapter.

## Current limitations

The application is not yet a multi-tenant platform, general workflow engine, document/knowledge platform, full ERP/CRM/finance system, or durable scheduler. OAuth-based provider integrations are not part of the live connector set reviewed here. Do not infer that an integration is functional solely because its name appears in the registry.

## Target-state boundaries

Keep the following concerns separate even if implemented in one deployment initially:

- **Identity and policy:** user identity, roles/scopes, approval policy, data-egress policy.
- **Planning and evaluation:** task planning, model selection, evaluation and regression gates.
- **Execution control plane:** durable workflows, leases, idempotency, cancellation, reconciliation and compensation.
- **Domain services:** explicit business entities and their lifecycle invariants.
- **Adapters:** provider-specific auth, requests, rate limits, external IDs, callbacks and health.
- **Evidence and operations:** audit anchoring, logs, traces, metrics, backup/restore and incident procedures.

This separation is a design direction, not a claim of current implementation.
