# Threat Model

## Scope

Initial threat model for the v0.4.0 release candidate. It is a working engineering document and must be reviewed against each deployment and data class. It is not a compliance certification or penetration test.

## Assets to protect

- Business records, customer and employee data, conversations, uploaded or retrieved documents if added later.
- Model prompts, outputs, tool arguments and provider credentials.
- API keys, SMTP credentials, Slack webhook URLs and generic webhook signing secrets.
- Approval decisions, workflow states, external system identifiers and execution outcomes.
- Audit records and their integrity evidence.
- Model usage budgets and service availability.

## Trust boundaries

1. Internet/client -> reverse proxy/API.
2. API -> model providers, including local endpoints and optional hosted providers.
3. Planner -> policy engine -> approval queue.
4. Execution service -> SMTP, Slack and generic webhook receivers.
5. Application -> database and migration process.
6. Application logs/audit store -> operators and backup/archive storage.
7. Future tenant boundary -> all records, provider credentials, model context and audit queries.

## Threat scenarios and controls

| Threat | Existing foundation | Required additional control |
| --- | --- | --- |
| Publicly exposed sandbox without credentials | Sandbox mode is intentionally open and Compose defaults to sandbox | Fail-closed production startup, deployment guardrails, reverse-proxy/network checks, explicit deployment checklist and negative tests |
| Sensitive context sent to hosted model | Hosted models can be disabled with configuration | Default-deny or explicit allowlist policy, data classification, redaction/minimization, provider-specific terms and audit evidence |
| Unauthorized external action | Roles, approval requests and policy checks exist | Fine-grained authorization, separation of duties, replay resistance, expiry checks and tests for every action type |
| Prompt injection or malicious retrieved content | Planner/policy boundary exists | Treat model output and external content as untrusted; validate tool schemas, limit capabilities, test injection cases and prohibit policy override by model content |
| Duplicate action after timeout | Connector outcomes distinguish some retry-safe from unknown results | Durable idempotency ledger, external idempotency key support where available, reconciliation UI and no retry on ambiguous outcome |
| Database or administrator rewrites audit history | Hash-chain verification detects many accidental or ordinary edits | External immutable anchor, independent retention, restricted DB roles and periodic verification |
| Credential disclosure | Secrets are represented as secret settings and hidden from some representations | External secret manager, log redaction, rotation/revocation runbook, key inventory and secret scanning |
| Resource exhaustion/cost abuse | Per-process/per-endpoint call limits and request rate limit exist | Shared quotas, concurrency ceilings, provider spend/latency monitoring, alerting and per-tenant budgets if multi-tenancy is added |
| Cross-tenant data leak | No tenant isolation in baseline scope | No shared tenancy until tenant ID is part of every record/query/cache/audit path and negative isolation tests pass |
| Data retained after requested deletion | Complete delete/archive lifecycle is missing | Retention matrix, deletion propagation, backup-retention rules, legal hold policy and evidence of completed deletion |

## Required invariants

- A model cannot authorize itself or bypass the policy engine.
- No external side effect occurs before required approval is valid.
- A caller can access only records and actions permitted by its identity and scope.
- Unknown execution outcomes are visibly unknown and never silently reported as success or safe-to-retry.
- Hosted data egress must comply with an explicit deployment policy.
- Secrets and sensitive prompt content do not appear in normal logs or public issues.
- Audit verification failure is an incident, not a warning to ignore.
- Tenant isolation must be proven before supporting multiple customer organizations in one shared data store.

## Before production

Complete P0 backlog items, run abuse and failure-injection tests, document data flows/providers, agree the deployment-specific threat model, and record residual-risk acceptance by the responsible owner.
