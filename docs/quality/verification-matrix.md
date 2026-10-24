# Verification Matrix

Use this matrix to decide what evidence is adequate. A document saying a test should exist is not evidence that it passed.

| Claim | Minimum evidence | Current baseline |
| --- | --- | --- |
| Unit logic is correct | Relevant unit tests and test output for exact SHA | Supplied report says 137 standard-library tests passed |
| API routes and permissions work | Dependency-backed API tests, positive and negative role cases | Not fully verified in the release sandbox |
| PostgreSQL compatibility | PostgreSQL CI/test run and migration logs | CI job is configured; completed green run for candidate must be recorded |
| Migrations are safe | Blank install plus prior-version upgrade test and backup/rollback plan | Baseline exists; follow-on policy and upgrade path need work |
| Docker deployment works | Compose config, image build, startup, health/readiness smoke tests | Compose YAML fixed in candidate packaging; Docker build was unavailable in the earlier sandbox |
| Hosted model works | Live provider test using approved non-sensitive fixtures, captured latency/cost/errors | Not verified against a live model |
| Model rankings are reliable | Versioned held-out evaluation, graded coverage, regression thresholds | 25-row seed; insufficient for production autonomy |
| SMTP is safe | Mailpit delivery/rejection/timeout tests and recipient-domain block | Not verified with a live SMTP catcher |
| Slack is delivered | Test workspace delivery evidence; failure/unknown outcome handling | Connector exists; health method reports configured, not probed |
| Webhook receiver is safe | Signature validation, status/timeout/idempotency contract tests | Live receiver behavior not verified |
| Approval policy is safe | API tests for identity, separation of duties, expiry, mutation/re-evaluation and concurrency | Some unit/API coverage exists; complete results are a release gate |
| Unknown outcomes are safe | Failure-injection test proves no blind retry and operator reconciliation | Targeted coverage must be evidenced for each action type |
| Audit history is trustworthy | Chain verification plus external anchor and restore test | In-database chain verification exists; external anchor not identified |
| Data can be recovered | Restore drill with record counts/integrity and elapsed time | Not established |
| Production is secure | Deployment threat review, access tests, security scan and negative config tests | Not established by unit tests alone |
| Multi-tenancy is safe | Tenant-isolation tests across APIs, jobs, caches, logs and exports | Not implemented in baseline scope |

## Evidence fields

Every verification record should include:
- Exact repository and commit SHA.
- Tool/runtime/dependency versions.
- Command or procedure.
- Pass/fail/blocked result and actual output.
- Environment (local, CI, staging) and sanitized configuration context.
- Date, responsible operator, and linked artifact or workflow run.
- Known exclusions and residual risk.

## Result vocabulary

- **Pass** — test actually ran and met criteria.
- **Fail** — test ran and did not meet criteria.
- **Blocked** — unable to run due to missing dependency/access/service.
- **Not run** — intentionally not executed.
- **Not applicable** — reason documented.

Never relabel Blocked or Not run as Pass.
