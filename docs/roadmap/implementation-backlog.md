# Implementation Backlog

This is the canonical prioritized task list for the reviewed v0.4.0 baseline. IDs should remain stable across documentation, issues, PRs and release notes. Tasks are proposed; none is complete just because it is documented here.

**Issue tracking:** The 20 backlog tasks are mapped to live GitHub Issues in the [backlog-to-issue synchronization map](issue-map.md), including traceability to the findings register.

## P0 — release and security gates

### SEC-01 — Prevent unsafe sandbox exposure

**GitHub issue:** [SEC-01](https://github.com/looloofy69-sketch/Os-diablo/issues/2)
**Outcome:** Sandbox open mode is only available for intentional local development and cannot be mistaken for a protected deployment.  
**Acceptance criteria:**
- Startup validates production/staging settings and rejects missing/weak secrets.
- Documentation and Compose examples default to a safe local-only posture and clearly label sandbox open mode.
- Add negative tests for empty keys, wrong environment, weak secrets, and exposed deployment configuration.
- Deployment checklist covers reverse proxy, host binding, TLS and access controls.

### SEC-02 — Make model data egress an explicit policy

**GitHub issue:** [SEC-02](https://github.com/looloofy69-sketch/Os-diablo/issues/3)
**Outcome:** Hosted-model use is governed by a deliberate deployment setting and permitted-provider list.  
**Acceptance criteria:**
- Document which request/context fields may leave the network for each provider.
- Add an enforceable provider allowlist and explicit default behavior for new deployments.
- Test private-only mode and rejection of unapproved hosted providers.
- Record provider/model and an appropriate non-sensitive decision trail without logging raw prompts by default.

### REL-01 — Complete the dependency-backed release suite

**GitHub issue:** [REL-01](https://github.com/looloofy69-sketch/Os-diablo/issues/4)
**Outcome:** Release evidence is complete for the candidate SHA.  
**Acceptance criteria:**
- Ruff, full pytest suite, PostgreSQL tests, Alembic upgrade, Docker build/start and smoke checks run in CI or a documented equivalent.
- Any failure is fixed or explicitly documented as a release blocker.
- CI artifact records test results and candidate commit SHA.

### REL-02 — Add release security and supply-chain checks

**GitHub issue:** [REL-02](https://github.com/looloofy69-sketch/Os-diablo/issues/5)
**Outcome:** Dependencies and artifacts have a repeatable security review.  
**Acceptance criteria:**
- Dependency vulnerability scan and secret scanning run in CI.
- Release artifact checksum and dependency inventory/SBOM are generated where tooling supports it.
- Action versions and dependency update policy are documented.

## P1 — safe operational execution

### WF-01 — Durable workflow execution state

**GitHub issue:** [WF-01](https://github.com/looloofy69-sketch/Os-diablo/issues/6)
**Outcome:** Multi-step plans have persisted state, step history and an explicit final/partial/unknown outcome.  
**Acceptance criteria:**
- Workflow and step state survive process restart.
- Each transition records actor, timestamp, attempt, idempotency key and result classification.
- Failure injection proves recovery after every step boundary.
- Partial completion is visible to an operator; successful earlier steps are not silently represented as rolled back.

### WF-02 — Idempotency, retry, cancellation and compensation

**GitHub issue:** [WF-02](https://github.com/looloofy69-sketch/Os-diablo/issues/7)
**Outcome:** Retries are safe and reversible actions can be compensated deliberately.  
**Acceptance criteria:**
- Each action documents its idempotency guarantees and provider limitations.
- Unknown outcomes are never automatically retried without reconciliation.
- Safe retry and compensation paths have concurrency tests.
- Cancellation semantics state which actions have already taken effect.

### OPS-01 — Backup, restore and disaster recovery

**GitHub issue:** [OPS-01](https://github.com/looloofy69-sketch/Os-diablo/issues/8)
**Outcome:** The system can be restored within agreed recovery objectives.  
**Acceptance criteria:**
- Define RPO/RTO and database/file/secret dependencies.
- Automate encrypted backup and retention.
- Restore into an isolated environment and verify data, migrations and audit integrity.
- Document incident steps and record a restore drill.

### OBS-01 — Operational observability and alerts

**GitHub issue:** [OBS-01](https://github.com/looloofy69-sketch/Os-diablo/issues/9)
**Outcome:** Operators can see degraded model, connector and workflow behavior before users report it.  
**Acceptance criteria:**
- Structured logs correlate request, workflow, step and external action IDs.
- Metrics cover error rate, latency, queue/lease age, unknown outcomes, provider cost/usage and connector failures.
- Alerts and runbooks are tested; logs redact secrets and unnecessary personal data.
- Readiness states clearly identify what was checked.

### AUD-01 — Independently anchor audit evidence

**GitHub issue:** [AUD-01](https://github.com/looloofy69-sketch/Os-diablo/issues/10)
**Outcome:** Audit integrity is not dependent solely on the mutable application database.  
**Acceptance criteria:**
- Export or anchor audit-chain heads to a separately permissioned store on a schedule.
- Verification detects missing, reordered, changed and stale/unanchored segments.
- Define retention, access, restore and incident procedures.
- Tests prove anchor failure is visible and does not silently claim integrity.

### AI-01 — Expand model evaluation and set regression gates

**GitHub issue:** [AI-01](https://github.com/looloofy69-sketch/Os-diablo/issues/11)
**Outcome:** Model ranking and task eligibility are supported by representative evidence.  
**Acceptance criteria:**
- Expand the 25-row seed with versioned representative cases and a held-out set.
- Include tool arguments, malformed output, ambiguity, prompt injection, privacy, refusal and failure-recovery cases.
- Report graded coverage, accuracy, latency and cost where available.
- Establish minimum confidence/score and regression thresholds; low evidence means manual approval or rules path.

### PERF-01 — Integrate and verify the v0.4.1 performance/logic-validation candidate

**GitHub issue:** [PERF-01](https://github.com/looloofy69-sketch/Os-diablo/issues/22)

**Outcome:** The candidate's ranking and validation changes are integrated into the canonical application source repository and verified on a specific commit.

**Acceptance criteria:**
- Identify the canonical application source repository and record its source/base commit.
- Compare the candidate ZIP with that source and review a small, explainable diff rather than blindly replacing files.
- Retain regression coverage for top-k equivalence, endpoint/model-pool validation, evaluation sample gates, duplicate-tool scoring, redirects, ambiguous connector outcomes, and package exclusions.
- Run the dependency-backed API suite, Ruff, PostgreSQL migration/upgrade tests, and Docker build/start in connected CI.
- Run controlled model evaluation, SMTP-catcher tests, and signed-webhook tests; record the models/services actually exercised.
- Preserve benchmark methodology and the synthetic-only qualification; add database/API load measurements before making end-to-end performance claims.
- Update application source version, changelog, release package, and checksums only after the accepted changes are in the application repository.
- Do not tag or deploy as production-ready while mandatory checks remain blocked or unrun.

**Current limitation:** the v0.4.1 source ZIP has been prepared and locally tested, but it has not been integrated into an identified application-source repository or deployed.

### INT-01 — Define connector capability and delivery lifecycle

**GitHub issue:** [INT-01](https://github.com/looloofy69-sketch/Os-diablo/issues/12)
**Outcome:** Catalogue entries are visibly different from implemented, configured, verified and healthy integrations.  
**Acceptance criteria:**
- Every integration has capability state, supported actions, auth method, health method and limitations.
- Distinguish configuration health from delivery success.
- Add contract tests for SMTP, Slack and generic webhooks using isolated test services.
- Capture external IDs, safe retryability and unknown outcome in the operator interface.

### DB-01 — Establish migration and data lifecycle policy

**GitHub issue:** [DB-01](https://github.com/looloofy69-sketch/Os-diablo/issues/13)
**Outcome:** Schema and data changes are repeatable and recoverable.  
**Acceptance criteria:**
- Every schema change uses an explicit Alembic revision.
- CI tests blank install and upgrade from the prior supported version.
- Document safe procedure for existing sandbox databases and the use of stamp versus upgrade.
- Define deletion, archive, retention and backup interactions.

## P2 — product capability and scale

### AUTH-01 — Add identity and key lifecycle management

**GitHub issue:** [AUTH-01](https://github.com/looloofy69-sketch/Os-diablo/issues/14)
**Outcome:** Keys and roles can be managed and revoked without manual configuration archaeology.  
**Acceptance criteria:** Key inventory, rotation/revocation, audit trail, least-privilege scopes, and documented SSO/MFA path where required.

### DOMAIN-01 — Define the first supported business workflow and domain model

**GitHub issue:** [DOMAIN-01](https://github.com/looloofy69-sketch/Os-diablo/issues/15)
**Outcome:** The next business entity work is driven by a real workflow, not a list of integrations.  
**Acceptance criteria:** Pick one target workflow, define entities and lifecycle states, ownership, invariants, API shape, migrations, permission matrix and end-to-end acceptance tests.

### UI-01 — Complete operator workflows

**GitHub issue:** [UI-01](https://github.com/looloofy69-sketch/Os-diablo/issues/16)
**Outcome:** Operators can inspect and manage all supported lifecycles without undocumented API calls.  
**Acceptance criteria:** Journey map and screens for approvals, execution state, contacts/projects/goals as needed, integrations, model diagnostics, access and recovery; accessible forms and browser automation.

### SCHED-01 — Add a durable scheduler

**GitHub issue:** [SCHED-01](https://github.com/looloofy69-sketch/Os-diablo/issues/17)
**Dependency:** WF-01, WF-02 and OBS-01.  
**Outcome:** Scheduled and recurring runs survive restarts and daylight/time changes.  
**Acceptance criteria:** Persistent schedules, leases, misfire policy, cancellation, timezone semantics, concurrency limits, idempotency and audit evidence.

### KNOW-01 — Add documents and retrieval only with governance

**GitHub issue:** [KNOW-01](https://github.com/looloofy69-sketch/Os-diablo/issues/18)
**Outcome:** Document context can be indexed and retrieved without bypassing access controls.  
**Acceptance criteria:** Source provenance, access-filtered retrieval, freshness, deletion propagation, tenant boundaries, prompt-injection handling and retrieval evaluation.

### INT-02 — Add OAuth-backed provider adapters

**GitHub issue:** [INT-02](https://github.com/looloofy69-sketch/Os-diablo/issues/19)
**Outcome:** One validated provider is integrated end-to-end at a time.  
**Acceptance criteria:** Authorization scopes, secure token storage/refresh/revocation, webhook verification, rate limits, external ID mapping, sync cursor/reconciliation, contract tests and operator status.

### TEN-01 — Multi-tenancy (deferred)

**GitHub issue:** [TEN-01](https://github.com/looloofy69-sketch/Os-diablo/issues/20)
**Dependency:** AUTH-01, DB-01, AUD-01 and a complete data-flow inventory.  
**Outcome:** Multiple organizations can share infrastructure without cross-tenant access.  
**Acceptance criteria:** Tenant scope applied to all records, caches, prompts, credentials, queues, audit queries, exports and background jobs; isolation tests and tenant lifecycle procedures.

## P3 — deliberately constrained or later work

### SAFE-01 — External irreversible action gateway

**GitHub issue:** [SAFE-01](https://github.com/looloofy69-sketch/Os-diablo/issues/21)
**Outcome:** Money movement and contract signing stay outside general autonomous execution until a dedicated gateway exists.  
**Acceptance criteria:** Separate authorization, exact payload confirmation, step-up authentication, limits, idempotency, reconciliation, independent audit and explicit human confirmation. This is not a prerequisite to ship the current constrained feature set.

## Backlog governance

A task may move to Done only after its acceptance criteria are met and evidence is linked. Reprioritize using impact, likelihood, dependency order and operational risk. Do not claim the backlog is exhaustive; update it when code review, test evidence or a real workflow reveals new requirements.
