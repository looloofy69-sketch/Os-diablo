# Contributing

- Domain and policy logic stays free of external calls; integrations live behind `Connector` adapters.
- Every externally meaningful mutation goes through a service function that writes its audit entry **in the same transaction** (`record_event` flushes, the caller commits).
- New action types are added to `services/policy.py` with a risk tier and a test. Unknown types fail closed.
- Approval status changes use the compare-and-set helper in `services/approvals.py`; never assign `status` directly.
- Connectors report `retryable=True` only when the provider provably did nothing, take secrets from settings, and validate outbound URLs with `check_outbound_url`.
- Schema changes need an explicit Alembic revision; never edit a released one.
- Pure modules (`policy`, `intents`, `priorities`, `audit_chain`, `llm`, `model_pool`, `connectors`, `connector_email`, `connector_http`, `planner`, `evaluation`, `security`, `netutil`) must not import FastAPI, SQLModel or pydantic.

Before opening a change: `ruff check .` and `pytest`. Never commit credentials, production data, or provider tokens.
