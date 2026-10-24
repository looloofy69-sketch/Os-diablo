# OS Diablo

OS Diablo is the documentation, architecture, delivery-planning, and governance home for the AI-enabled business operations system. This repository starts as a documentation-first control plane; it does not claim to contain or deploy the application implementation.

## Initial scope

- Record the v0.4.0 release-candidate assessment of `business-management-assistant-ai`.
- Track confirmed observations, risks, unverified assumptions, and missing capabilities.
- Maintain a prioritized implementation backlog with acceptance criteria.
- Define architecture boundaries, security expectations, operational runbooks, and release gates.

## Status

The initial documentation baseline is merged into `main`; outstanding application work remains tracked as GitHub Issues and is not complete merely because it is documented. The initial assessment is based on the supplied v0.4.0 archive and static code review dated 2026-10-24. It is not evidence that live model providers, SMTP, Slack, webhooks, PostgreSQL migrations, or Docker have been validated end-to-end.

## Start here

- [Documentation index](docs/README.md)
- [Assessment and findings](docs/assessments/2026-10-24-v0.4.0-review.md)
- [v0.4.1 performance review](docs/assessments/2026-10-24-v0.4.1-performance-review.md)
- [Findings register](docs/assessments/findings-register.md)
- [Prioritized implementation backlog](docs/roadmap/implementation-backlog.md)
- [GitHub issue map](docs/roadmap/issue-map.md) — 21 tracked tasks
- [GitHub issue map](docs/roadmap/issue-map.md)
- [Release verification runbook](docs/operations/release-verification.md)
- [Threat model](docs/security/threat-model.md)

## Working principles

1. Separate implemented, partially implemented, planned, and unverified capabilities.
2. Prefer fail-closed security defaults outside a local sandbox.
3. Never treat a unit-test pass as proof of live integration or production readiness.
4. Every backlog item should have an owner, dependencies, acceptance criteria, and evidence of completion before it is marked done.
5. Keep application code and this governance repository's documents clearly distinguished.

## Repository status

See [CHANGELOG.md](CHANGELOG.md) for documentation changes. No deployment, repository release, or application behavior is implied by a documentation commit.
