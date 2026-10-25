# Changelog

## 0.4.1

- Hardened model ranking evidence: scores without an explicit graded-example count of at least ten are ignored, including legacy scalar scores and accuracy-only entries.
- Hardened webhook configuration: reject malformed/empty ports, query strings, fragments, invalid timeouts, non-string route fields, and duplicate normalized route prefixes.
- Connector results now carry `outcome_unknown` as an explicit boolean. Approval execution no longer infers outcome certainty from error-detail text; ambiguous HTTP/SMTP outcomes are typed and persisted.
- Hardened release packaging to exclude credential directories and common key/certificate/state files regardless of filename case; added regression coverage.

Correctness, latency and release-validation hardening. This version is packaged as a candidate and remains subject to the full dependency-backed and live-service release gate.

- Model discovery: concurrent first requests now coalesce behind one refresh instead of racing against an empty model list; provider discovery results are type-checked and deduplicated.
- Endpoint configuration: validate URL structure, credentials-in-URL, mutually exclusive key sources, model/role types, finite timeouts, token limits, daily limits and boolean flags before network calls.
- Model ranking evidence: only finite accuracy values in [0, 1] are loaded; evaluated scores require at least ten graded examples so tiny smoke tests cannot silently distort model ranking.
- Connector safety: ambiguous webhook HTTP responses (including 429/5xx) are outcome-unknown and are not marked automatically retryable. Only explicit network failures known to occur before delivery remain retryable.
- Evaluation logic: validate JSONL dataset structure before provider calls, preserve duplicate tool-call counts during planner scoring, add per-example evaluation controls, estimate provider calls, and write score files atomically.
- Performance: top-k task ranking uses a bounded heap rather than sorting and retaining every scored item, reducing selection complexity from O(n log n) to O(n log k) for the usual five results.
- Release verification: remove duplicate unit-test execution; add compile checks; use an actual temporary SQLite database path; require Docker by default or explicitly label a run partial when Docker is skipped.
- Packaging: add a clean, deterministic source-packaging script and exclude test caches, virtual environments, local databases, secrets, model weights and generated evaluation outputs.

## 0.4.0

Every available model, real connectors, operational hardening.

- Models: no chosen model. A pool discovers what is reachable (provider keys in the environment, local Ollama / LM Studio / llama.cpp, explicit `LLM_ENDPOINTS`), ranks by measured scores or a name heuristic, cascades on failure or invalid output, opens per-model circuit breakers, and re-discovers every few minutes. `LLM_ALLOW_HOSTED=false` keeps data on private endpoints. `scripts/evaluate_models.py` measures every reachable model and feeds the ranking. `GET /api/ai/models`.
- Connectors: SMTP email (message, invoice and contract send, calendar invites with ICS), Slack incoming webhook and signed generic webhooks (n8n, Zapier, Make, your own service). Routed by action and target; sandbox always dry-runs; live mode with no connector fails closed. Per-connector health feeds the Integrations registry.
- Safety: connector results say whether a retry is safe (`retryable` only when nothing was done); unknown outcomes are never retried; executions stuck for 10 minutes are failed as outcome-unknown; admins can amend a pending request (risk is re-evaluated) and retry safe failures; operators are notified of waiting approvals without message content.
- Staging guard: SMTP in staging requires `SMTP_ALLOWED_DOMAINS`.
- Operations: Alembic baseline and Docker entrypoint migrations; `AUTO_CREATE_SCHEMA` only in sandbox; SQLite writers serialise with `BEGIN IMMEDIATE`; audit append retries with back-off; CI runs the suite on SQLite and PostgreSQL; real concurrency tests for approval decisions, execution claims and the audit chain.
- Breaking: `LLM_BASE_URL`/`LLM_MODEL` now pin one model instead of being the only way to enable the planner; `ChatClient`-based `create_app(llm_client=)` is replaced by `create_app(model_pool=, connectors=, notifier=)`; `ConnectorRegistry.register()` takes a connector object, `resolve()` takes `(action_type, target)`. Auto-discovery is on by default: set `LLM_AUTO_DISCOVER=false` to disable.

## 0.3.0

LLM-driven assistant.

- Planner: model returns validated JSON tool calls; results are executed through the shared services; the reply is composed from real results.
- Providers: OpenAI-compatible servers (local or hosted) and the Anthropic Messages API, selected by `LLM_PROVIDER`.
- Modes: `ASSISTANT_MODE=rules|hybrid|llm`; default `hybrid` once a model is configured.
- Safety: external effects only through `propose_action` (always pending for model-originated requests); rule-based safety net injects a missing proposal; step, call and daily-budget caps; automatic fallback to rules.
- Audit: `via` attribution on model-planned mutations; `assistant.planned` events with tools, failures and token usage.
- Evaluation: planner tool-selection rows in the seed dataset; the script now supports both providers and gates on accuracy.
- Config: `env_ignore_empty` so empty variables (docker compose) count as unset; non-loopback LLM endpoints must use https outside sandbox.
- UI: shows the assistant mode and marks model-planned replies.

Upgrade from 0.2: no schema change. `LLM_BASE_URL` + `LLM_MODEL` now enable the planner (previously the label-only classifier, which is removed).

## 0.2.0

Safety and correctness rebuild: authenticated roles, central policy engine, atomic approval lifecycle, hash-chained audit, PATCH/filters/pagination, UTC datetimes, rewritten UI. See README "What changed in 0.2" for breaking changes.

## 0.1.0

Initial foundation.
