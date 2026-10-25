# Business Management Assistant AI

Control plane for an AI-assisted business: goals, projects, tasks, contacts, approvals, integrations, an LLM-planned chat assistant, and a tamper-evident audit trail. Starts in sandbox mode; nothing leaves the process without an approved, audited action.

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload
```

UI at http://127.0.0.1:8000, API reference at `/docs` (sandbox only).

Sandbox with no `API_KEYS` runs in open mode as the local `founder` admin. Any other `ENVIRONMENT` refuses to start without keys:

```bash
export ENVIRONMENT=staging
export API_KEYS="root:admin:$(python -c 'import secrets;print(secrets.token_urlsafe(32))'),ops:operator:<secret>,eyes:viewer:<secret>"
```

Send the key as `X-API-Key` or `Authorization: Bearer`. Roles: `viewer` reads, `operator` writes records and chats, `admin` reviews approvals and reads the audit log.

```bash
curl -X POST localhost:8000/api/chat -H 'content-type: application/json' \
  -d '{"message":"create task: call Alex by 2026-11-01 high priority"}'
curl -X POST localhost:8000/api/chat -H 'content-type: application/json' \
  -d '{"message":"send the proposal to alex@acme.io"}'      # -> approval request, nothing sent
curl localhost:8000/api/approvals?status=pending
```

Tests: `pytest` (API tests need the dev extras) or, for the dependency-free decision logic, `python -m unittest discover -s tests/unit -t .`.

## LLM-driven assistant, with whatever models are available

Release-candidate version: 0.4.1. No model has to be chosen. The assistant discovers and uses every reachable model: provider keys in the environment (Anthropic, OpenAI, OpenRouter, Groq, Together, Mistral), local servers (Ollama, LM Studio, llama.cpp), and anything in `LLM_ENDPOINTS`. It ranks them (measured scores when you have run `scripts/evaluate_models.py`, a name heuristic until then), falls through to the next model on errors or invalid output, and drops to the built-in rules if nothing works. `GET /api/ai/models` shows what it sees. Details: [`docs/models.md`](docs/models.md).

```bash
export ANTHROPIC_API_KEY=...        # optional: any of the supported provider keys
ollama serve &                      # optional: any local OpenAI-compatible server
uvicorn app.main:app                # discovers both
LLM_ALLOW_HOSTED=false uvicorn ...  # keep business data on private endpoints
```

| `ASSISTANT_MODE` | Behaviour |
|---|---|
| `rules` | No model calls. |
| `hybrid` (default when any model is reachable) | Structured commands (`create task: ...`, `list tasks`, `brief me`) stay deterministic and free. Open-ended, growth and external-action requests go to the models. |
| `llm` | The models plan everything except `help`. |

How a request flows: a model returns JSON steps from a fixed tool list (`get_briefing`, `list_items`, `search`, `create_goal|project|task|contact`, `update_task`, `complete_task`, `propose_action`). Each step is validated, executed through the same services as the HTTP API, and the results are handed back to a model to write the reply, so the reply describes what happened rather than what was predicted. Records are referenced by title, never by model-supplied ids.

What a model cannot do, whatever it outputs:

- Send, publish, pay, sign, delete or launch. The only route is `propose_action`, which creates a **pending** approval for a person. Assistant-originated requests are never auto-approved and internal record types are rejected there.
- Skip the gate: if the rules detect an external verb the plan did not propose, the proposal is added.
- Act outside the caller's role or approve its own requests.
- Run unbounded: at most 5 steps, a bounded cascade, per-process and per-endpoint daily call caps.

Mutations made by model-planned steps carry `"via": "llm:<model>"` in the audit trail; every planned message writes an `assistant.planned` event (model, failed attempts, tools, token usage; prompts are not stored). With a hosted provider reachable, message text, recent turns and a short business snapshot may be sent to it.

## Connectors

Approved actions run through connectors: **SMTP email** (including calendar invites), **Slack webhook**, and **signed webhooks** to your own automation. Sandbox always dry-runs; outside sandbox an action with no connector fails closed. Failures say whether a retry is safe; unknown outcomes are never retried. See [`docs/connectors.md`](docs/connectors.md).

```bash
export ENVIRONMENT=staging API_KEYS=... SMTP_HOST=localhost SMTP_PORT=1025 SMTP_SECURITY=none \
       SMTP_SENDER=assistant@corp.test SMTP_ALLOWED_DOMAINS=corp.test   # e.g. against Mailpit
```

## What changed in 0.2

| Area | Before | Now |
|---|---|---|
| Approvals | Any `decision` value accepted, including `executed`; approving did nothing; chat claimed to queue actions it never stored | `approved`/`rejected` only; compare-and-set transitions; explicit execute step through a connector; expiry; idempotency keys; chat creates real requests |
| Policy | `startswith("send ")` check in chat | Central engine: risk tiers per action type, unknown types fail closed, amount/bulk/public escalation |
| Identity | Free-text `actor` and `reviewer` fields | API-key auth, roles, actor taken from the credential, distinct-reviewer rule outside sandbox |
| Audit | Separate commit after the mutation; no integrity | Same transaction as the mutation; hash-chained; `GET /api/audit/verify` |
| Records | Create-only; tasks could never be completed | PATCH, complete, filters, pagination with `X-Total-Count`, FK checks, unique contact email |
| Time | Naive/aware mix, `updated_at` never advanced | Always timezone-aware UTC |
| Chat | Substring matching (`ads` matched `heads`), no entities | Word-boundary rules, priority/due/project extraction, task completion, unknown conversation is a 404 |
| Local model | Catalogued only | Optional label-only intent assist; rules and policy keep authority; scored evaluation gate |
| Briefing | Counts | Overdue, blocked, at-risk goals, stale approvals, ranked next actions, goal progress |
| Ops | Import-time DB side effects, root container, shared test DB | App factory, lifespan, request IDs, security headers, rate limit, `/ready`, non-root image, isolated in-memory tests |

### Breaking changes

- Create endpoints return `201`.
- `POST /api/ai/plan` takes a JSON body (`request`, `capability`); capability is validated.
- `reviewer` (decision) and `actor` (chat) are ignored; identity comes from the key.
- Chat with an unknown `conversation_id` returns 404 instead of silently starting a new one.
- Errors from application code use `{"error": {"code", "message", "details", "request_id"}}`.
- The database schema changed. A 0.1 SQLite file is refused at startup with an explanation; start from a new file.
- `psycopg` moved to the `postgres` extra (`pip install '.[postgres]'`).

## Approval lifecycle

```
pending -> approved -> executing -> executed
   |          |             \-> failed
   |          \-> expired (not run before expires_at)
   \-> rejected | expired
```

Low-risk internal action types are auto-approved by policy (`reviewed_by: policy`). Everything external, unknown, or escalated waits for an admin. In sandbox every connector is a dry run; in other environments an action type with no registered connector ends as `failed`, never silently succeeds.

## Configuration

See `config/.env.example`. Notable settings: `APPROVAL_TTL_HOURS`, `HIGH_VALUE_THRESHOLD`, `RATE_LIMIT_PER_MINUTE` (per client IP; behind a proxy run uvicorn with `--proxy-headers --forwarded-allow-ips`), and `LLM_ALLOW_HOSTED` to control whether hosted models may receive business context. Set both `LLM_BASE_URL` and `LLM_MODEL` only when you want to pin a single OpenAI-compatible endpoint; otherwise the model pool discovers available endpoints by default.

## Docker

```bash
cp config/.env.example .env   # set POSTGRES_PASSWORD, and API_KEYS for non-sandbox; the image runs `alembic upgrade head` outside sandbox
docker compose --env-file .env up --build
```

The API binds to `127.0.0.1` only.

## Known limits

- Model and connector behavior still requires controlled live verification against an approved model, SMTP catcher such as Mailpit, and test webhook receiver. Run `python scripts/evaluate_models.py --limit 1 --max-examples 10` for a bounded smoke run; fewer than ten graded rows do not update ranking scores. The candidate has not been declared production-ready.
- Auto-discovery probes four loopback ports and uses any provider key present in the environment; disable with `LLM_AUTO_DISCOVER=false`.
- Connectors for OAuth-based systems (Google, accounting, CRM) and payments are not included.
- No documents/knowledge layer, no delete/archive flow, no scheduler.

- Single tenant; no per-user data scoping.
- Migrations: Alembic baseline only; write and review every later revision explicitly. Existing sandbox databases: `alembic stamp head`.
- Audit verification reads the whole chain; add checkpoints before it grows large.
- Idempotency keys are global, not per requester.
- Live connectors are not included; the registry and contract are.
- Each planned step commits on its own; a plan that fails midway leaves earlier steps applied (all are audited).
- No streaming responses; no per-user model budgets; model health and call budgets are per process.
- Rate limiter state is per process.
- SQLite serialises writers (`BEGIN IMMEDIATE`); use PostgreSQL for more than one active user.

More: [`docs/models.md`](docs/models.md), [`docs/connectors.md`](docs/connectors.md), [`docs/architecture-decisions.md`](docs/architecture-decisions.md), [`docs/local-models.md`](docs/local-models.md), [`docs/foundation.md`](docs/foundation.md).

## License

Private project. All rights reserved until a license is selected.
