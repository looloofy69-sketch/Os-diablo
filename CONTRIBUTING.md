# Contributing

## Purpose

OS Diablo coordinates architecture, findings, priorities, verification evidence, and operational guidance for the AI-enabled business operations system. Keep this repository clearly distinguished from repositories that contain executable application code.

## Documentation rules

1. Label the status of each material statement: implemented, partially implemented, planned, unverified, or deferred.
2. Record the evidence and review date for findings. Separate direct source observations from assumptions and live-environment results.
3. Do not mark a task done based only on a written design. Link a commit, test result, CI run, or operator evidence.
4. Any new capability should include acceptance criteria, failure behavior, security impact, data migration needs, and operational implications.
5. Use stable task IDs from the implementation backlog, for example SEC-01 or REL-02, and keep references synchronized when task IDs change.
6. Do not commit credentials, customer data, production logs, private endpoints, or secrets.
7. Prefer small, reviewable pull requests. Avoid unrelated formatting or wide structural changes in a documentation update.

## Task lifecycle

Proposed -> Ready -> In progress -> In review -> Verified -> Done.

A task is Ready only when its scope, dependencies, owner or responsible role, and acceptance criteria are explicit. Verified requires evidence appropriate to the task. A documentation-only change must not be described as an implementation change.

## Backlog synchronization check

Run the local consistency check before submitting changes to the backlog, findings register, issue map, or related workflow:

    python3 scripts/check_backlog_sync.py

When `GITHUB_TOKEN` is set, the script additionally verifies that each mapped Issue exists, its title contains the task ID, its body links to the canonical backlog, and its live state matches the issue-map status. GitHub Actions runs this check on relevant pushes and pull requests and once per day.

## Definition of done

- Requirements and acceptance criteria are satisfied.
- Tests or verification steps are recorded.
- Security, privacy, failure and migration impacts are documented.
- Operator-facing changes include relevant runbooks.
- README, backlog, issue map, findings register and changelog references are updated where needed.
