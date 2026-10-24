# Findings Register

**Baseline date:** 2026-10-24  
**Subject:** business-management-assistant-ai v0.4.0 release candidate  
**Status note:** This is an engineering review register, not a penetration-test report. Revalidate findings as implementation changes.

Severity definitions: **P0** release/security gate; **P1** required for dependable pilot operations; **P2** substantial capability or maintainability improvement; **P3** later enhancement or intentionally deferred scope.

**Tracking:** All 22 findings map to one or more of the 20 backlog tasks. See the [backlog-to-issue synchronization map](../roadmap/issue-map.md) for task IDs and live GitHub Issues.

| ID | Severity | Finding | Evidence/status | Required follow-up |
| --- | --- | --- | --- | --- |
| F-01 | P0 | Sandbox open mode is hazardous if exposed | Confirmed by security code: no keys means admin open mode in sandbox; Compose defaults to sandbox | Add deployment guardrails and negative tests; reject unsafe public/non-loopback deployment combinations where detectable |
| F-02 | P0 | Hosted model data egress is enabled by default | Confirmed setting: hosted models allowed by default | Make provider allowlist and data classification explicit; document prompt/data egress; test private-only mode |
| F-03 | P0 | Release verification is incomplete | Release evidence says dependency-backed API tests, Ruff, PostgreSQL migration, Docker build and live services were not all verified | Run release gates on the exact commit and preserve CI artifacts |
| F-04 | P1 | Static API keys lack a full identity lifecycle | API key and role primitives exist; no built-in user/key rotation/revocation workflow or SSO/MFA was identified in reviewed scope | Add key inventory, rotation/revocation procedure, stronger authentication integration where required |
| F-05 | P1 | Authorization is coarse-grained | Roles are viewer/operator/admin; fine-grained record/resource scope and tenant boundary are absent | Define authorization matrix, ownership rules and negative access tests |
| F-06 | P1 | Multi-step workflow recovery is incomplete | Review concern; exact failure modes require targeted tests | Persist workflow/step state and prove partial failures, cancellation, idempotency and compensation behavior |
| F-07 | P1 | Integration catalogue overstates operational breadth if interpreted as implemented | Registry seeds many provider families; live connector factory currently builds email, Slack webhook and generic signed webhook | Add explicit capability state per integration: catalog-only, configured, connected, contract-tested, production-supported |
| F-08 | P1 | External integration behavior is not uniformly live-probed | Slack health explicitly reports configured/not probed; webhook outcomes can be uncertain | Model connection/credential/configuration/delivery health separately; add receiver contract tests and operator-visible delivery state |
| F-09 | P1 | No tested disaster-recovery evidence | Backup/restore procedure and recovery objectives were not established in reviewed materials | Define RPO/RTO; automate backup; restore into isolated environment and record evidence |
| F-10 | P1 | Audit chain lacks an independent trust anchor | In-database chain verification exists; an actor with database write access may recompute it | Periodically anchor chain head outside the application database; define immutable export and retention |
| F-11 | P1 | Model evaluation is too small to justify close ranking decisions | Seed evaluation file contains 25 rows; evaluation grading and live runs are limited | Expand representative cases, split holdout data, add safety/prompt-injection/tool-use rubrics and regression thresholds |
| F-12 | P1 | Operational observability is incomplete | Health/readiness endpoints exist; readiness only tests database access | Add model/connector/workflow metrics, trace IDs, structured error classification, alerts and incident runbooks |
| F-13 | P1 | Data deletion, archival and retention lifecycle are incomplete | No complete delete/archive/retention workflow was identified | Define soft-delete versus hard-delete, legal holds, export, retention, audit handling and tests |
| F-14 | P1 | Migration evolution is under-specified | Baseline exists; future schema changes need explicit migration scripts; existing database stamping needs a controlled procedure | Set migration policy, upgrade-from-previous-version tests, compatibility and rollback/restore guidance |
| F-15 | P2 | Domain model is not a full business operations schema | Core entities are goals, projects, tasks, contacts, approvals, integrations, audit, conversations | Derive required entities from prioritized workflows; add only justified domains with ownership, invariants and lifecycle tests |
| F-16 | P2 | Full operator UX is incomplete | Useful briefing/task/approval/audit/model UI exists, but complex admin and business lifecycles lack complete screens | Map operator journeys and cover every supported lifecycle with UI and API tests |
| F-17 | P2 | No durable scheduler is included | Explicitly out of current scope | Add scheduler only after workflow persistence, retries, leases, observability and idempotency are established |
| F-18 | P2 | OAuth/provider integrations are absent | Explicitly out of current scope | Add one provider at a time, beginning with the business workflow that has measurable need; implement token lifecycle and scopes |
| F-19 | P2 | Documents and knowledge layer is absent | Explicitly out of current scope | Define ingestion, access filtering, provenance, freshness, deletion propagation and retrieval evaluation before adding RAG |
| F-20 | P2 | Tenant isolation is absent | Explicitly out of current scope | Do not offer shared multi-customer hosting until tenant-scoped persistence, keys, audit, quotas, and negative tests exist |
| F-21 | P2 | CI security and dependency supply-chain checks need strengthening | CI includes test, lint and migrations; broader vulnerability and dependency policy was not evidenced | Add dependency audit, secret scanning, pinned actions/dependencies policy, SBOM and release artifact verification |
| F-22 | P3 | Irreversible financial/contract actions remain intentionally excluded | Explicitly deferred safety boundary | Keep money movement and contract signing behind a separately authorized, idempotent and audited service; do not bypass the boundary in the planner |

## Interpretation rules

- **Confirmed** means visible in reviewed code/configuration or documented release evidence.
- **Review concern** means plausible architectural risk requiring a targeted test to establish exact behavior.
- **Not identified** means not found in the reviewed scope; it is not proof that no external process exists.
- Severity is a prioritization, not a formal risk score. Reassess likelihood and impact in the deployment's actual threat model.

## Update protocol

When a finding is closed, add the implementing commit or PR, test/evidence link, environment, and verification date. Do not delete historical findings; mark them resolved with evidence.
