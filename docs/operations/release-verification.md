# Release Verification Runbook

## Purpose

Run the complete verification gate for a specific application commit and deployment configuration. Record the commit SHA, Python version, OS/container runtime, dependency lock state, command outputs, and any skipped checks.

## 1. Clean environment

Use a connected development or CI environment with supported Python and package-index access. Start from a clean checkout of the application repository, not from a previously modified working tree.

    python -m venv .venv
    . .venv/bin/activate
    python -m pip install --upgrade pip
    pip install -e '.[dev,postgres]'

On Windows, activate the virtual environment using its Windows activation script.

## 2. Static and automated tests

    ruff check .
    python -m compileall -q app scripts tests
    pytest -q

Record test counts, skipped tests, warnings and the exact commit. Do not describe a partial suite as the full suite.

## 3. PostgreSQL migrations

Start an isolated PostgreSQL instance and set TEST_DATABASE_URL / DATABASE_URL to a throwaway database. Never run destructive setup statements against a real database.

    DATABASE_URL="$TEST_DATABASE_URL" alembic upgrade head
    DATABASE_URL="$TEST_DATABASE_URL" alembic current

Also verify an upgrade from the last supported schema, foreign-key/integrity behavior, transaction/concurrency cases, and application startup against that migrated database. The empty-database CI migration check does not replace an upgrade-from-previous-version test.

Existing sandbox databases may require a controlled Alembic stamp procedure as described by the application release notes. Back up first, inspect actual schema/version, and never stamp a database merely to silence a migration error.

## 4. Docker

    docker compose config
    docker build -t os-diablo-app-candidate .

If using Compose, use a dedicated test environment file, an explicit non-sandbox environment, a strong test API key, isolated database storage, and no real recipients. Verify startup, migration logs, health and readiness endpoints, and shutdown behavior. Do not publish the app with sandbox defaults.

## 5. Model evaluation

Run the application-provided evaluator only against models and endpoints explicitly approved for the test data. Evaluation can make provider calls and incur cost.

    python scripts/evaluate_models.py --limit 1

Record the model/provider identifier, evaluation dataset revision, number of graded examples, accuracy, latency, cost if available, and failures. A score from the 25-row seed dataset is only a provisional signal, not an approval for unsupervised business actions. Do not use real customer data in an evaluation dataset without authorization and minimization.

## 6. Connector tests

- **SMTP:** use a local catcher such as Mailpit. Restrict allowed recipient domains; verify accepted, rejected, timeout and connection-failure outcomes. Confirm that no test mail can reach real users.
- **Slack:** use a dedicated test workspace/webhook and send a test message only after explicit authorization. Record delivered/rejected/unknown outcomes.
- **Generic webhook:** use a disposable receiver that verifies signatures, rejects bad signatures, records idempotency keys, simulates timeouts and returns controlled status codes.
- **Sandbox:** confirm that actions are dry runs and no real external side effect occurs.

Never test against production customer systems with synthetic or potentially destructive actions unless a reviewed test plan and authorization exist.

## 7. Browser and workflow tests

Exercise:
- Authentication and role-based access, including negative cases.
- Approval creation, modification, distinct-reviewer requirements and expiry.
- Safe retry versus unknown outcomes.
- Concurrent claims/approval decisions and audit-chain verification.
- Partial failure in a multi-step plan, process restart and recovery.
- Operator visibility for failed or stuck executions.

## 8. Evidence record

For each candidate, preserve:

- Application commit SHA and package checksum.
- Dependency and runtime versions.
- CI job URLs and all failed/skipped checks.
- Migration target and database engine/version.
- Model/evaluation dataset revision and cost/latency summary.
- Connector environment and test outcome without exposing secret values.
- Known limitations and owner-approved residual risks.

## Release gate

A release is not production-ready until all required tests pass, residual P0 findings are closed, operational recovery is demonstrated, and the owner records an explicit go/no-go decision. If a check cannot run, report it as blocked/unverified, not passed.
