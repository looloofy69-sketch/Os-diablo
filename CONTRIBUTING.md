# Contributing

OS Diablo contains both the Business Management Assistant AI application source and its cross-cutting architecture, security, delivery and governance records. Keep source changes, evidence and claims consistent.

## Application changes

The Python project lives under `business-management-assistant-ai/`.

```bash
cd business-management-assistant-ai
python -m pip install -e ".[dev]"
ruff check .
pytest -q
```

For PostgreSQL validation install `.[dev,postgres]`, set `TEST_DATABASE_URL`, run the tests, and exercise Alembic migrations against an empty database and a supported prior schema. The GitHub Actions workflow is `.github/workflows/application-ci.yml`; it is at repository root because GitHub does not execute nested `.github/workflows` directories.

## Documentation and governance rules

1. Label material statements as implemented, partially implemented, planned, unverified or deferred.
2. Record evidence and review dates; distinguish code inspection from connected-CI and live-service results.
3. Do not mark a task complete based only on a design or local unit-test pass.
4. Include acceptance criteria, failure behavior, security impact, migration requirements and operational implications with new capabilities.
5. Use stable task IDs from the implementation backlog and synchronize the issue map with GitHub Issues.
6. Never commit credentials, customer data, production logs, private endpoints or secrets. `.env.example` is acceptable; real environment files and private keys are not.
7. Prefer small, reviewable pull requests and preserve unrelated source and governance work.

## Backlog synchronization

Run this repository's dependency-free consistency check before changing backlog/issue-map relationships:

```bash
python3 scripts/check_backlog_sync.py
```

GitHub Actions runs this check for relevant pushes and pull requests and on a daily schedule.

## Definition of done

- Acceptance criteria are met with appropriate test or verification evidence.
- Security, privacy, failure, migration and operational impacts are documented.
- README, changelog, architecture, backlog, issue map, findings and runbooks are updated where relevant.
- Claims about release readiness reflect the actual checks completed; do not describe blocked checks as passes.
