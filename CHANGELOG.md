# Changelog

This changelog records OS Diablo repository and application-source integration changes. The application retains its own version history in `business-management-assistant-ai/CHANGELOG.md`.

## Unreleased

- Integrated the `business-management-assistant-ai` v0.4.1 candidate source under `business-management-assistant-ai/` from the verified 97-entry source archive, without replacing the existing governance docs.
- Added root-level `application-ci.yml` so GitHub Actions runs application checks from the nested project directory; the app's original workflow definition is retained with the application source for package fidelity.
- Added release notes, artifact checksum references, raw benchmark data, and performance-validation evidence under the application documentation.
- Added a dated repository-integration record and updated the root README, architecture boundary, repository map, contributing guidance and issue map.
- Preserved the review disposition: the local unit suite passed (158 tests, 52 subtests), while dependency-backed API tests, Ruff, PostgreSQL migration/upgrade validation, Docker, live connectors/providers, browser E2E and realistic load remain unverified.
- Recorded the original source ZIP SHA-256 `8ccf53b1b44f793eeca833c935985c9444c54ae8313fc5af000188a04b29ab18` and release bundle SHA-256 `3dbb83ae10b82f80ba9bfa0ea694f7b2f0aefa0579f2a466906626f9f1584327`. These identify delivered archives, not the resulting Git tree.
- Kept PERF-01 (Issue #22) open until the source integration is merged and mandatory release gates have evidence.
- Established the initial documentation/governance baseline, v0.4.0 assessment, findings register, implementation backlog, architecture, threat model, runbooks, quality matrix and ADR-0001.
