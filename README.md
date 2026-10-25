# OS Diablo — Business Management Assistant AI

OS Diablo is the single repository for the Business Management Assistant AI application, its release artifacts and verification evidence, and the architecture/security/governance controls around it.

## Application source

The v0.4.1 review candidate is maintained as ordinary source files under [`business-management-assistant-ai/`](business-management-assistant-ai/). Start with its [application README](business-management-assistant-ai/README.md), [release notes](business-management-assistant-ai/docs/releases/v0.4.1-release-notes.md), [validation report](business-management-assistant-ai/docs/releases/v0.4.1-performance-validation.md), and [artifact checksums](business-management-assistant-ai/docs/releases/v0.4.1-artifact-checksums.md).

The current integration is being reviewed on branch `integrate/v0.4.1-app-source`. It is not considered merged, tagged, deployed, or production-ready until CI and the remaining release gates pass. The original source ZIP SHA-256 is recorded in the release evidence; it is not a Git tree hash.

## Governance and engineering records

- [Documentation index](docs/README.md)
- [Current-state architecture](docs/architecture/current-state.md)
- [v0.4.0 assessment](docs/assessments/2026-10-24-v0.4.0-review.md)
- [v0.4.1 performance review](docs/assessments/2026-10-24-v0.4.1-performance-review.md)
- [v0.4.1 repository integration record](docs/assessments/2026-10-25-v0.4.1-integration.md)
- [Findings register](docs/assessments/findings-register.md)
- [Implementation backlog](docs/roadmap/implementation-backlog.md)
- [Issue map](docs/roadmap/issue-map.md)
- [Release verification runbook](docs/operations/release-verification.md)
- [Threat model](docs/security/threat-model.md)

## Local development

```bash
cd business-management-assistant-ai
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
pytest -q
```

For PostgreSQL tests, install `.[dev,postgres]` and set `TEST_DATABASE_URL`. Docker/Compose commands and runtime configuration are documented in the application README.

## Status and limits

The source tree and a root-level application CI workflow are being integrated; this is not proof of a successful GitHub CI run or a live deployment. Current local evidence includes 158 unit tests and 52 subtests passing. The full API suite, Ruff, PostgreSQL migration tests, Docker build/start, provider and connector delivery tests, browser E2E and realistic load remain gates to verify in connected CI or suitable test environments.
