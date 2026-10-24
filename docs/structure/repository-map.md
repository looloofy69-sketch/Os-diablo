# Repository Structure and Ownership

## Top-level map

    README.md
    CHANGELOG.md
    CONTRIBUTING.md
    SECURITY.md
    .github/
      ISSUE_TEMPLATE/
      pull_request_template.md
    docs/
      README.md
      assessments/
      architecture/
      decisions/
      operations/
      quality/
      roadmap/
      security/
      structure/

## Directory responsibilities

- **assessments/** — dated reviews of a specific artifact/commit, methods, evidence, limits and disposition.
- **architecture/** — current implementation boundary and target design direction.
- **decisions/** — durable architecture decisions with context, tradeoffs and acceptance consequences.
- **operations/** — repeatable commands, deployment gates, recovery and incident procedures.
- **quality/** — test/evidence matrix, quality thresholds and verification records.
- **roadmap/** — stable task IDs, dependencies, milestones and acceptance criteria.
- **security/** — threat model, trust boundaries, policies and residual risks.
- **structure/** — repository conventions and document ownership.

## Source-of-truth boundaries

- Application code and runtime configuration live in the application repository.
- This repository owns cross-cutting assessments, architecture direction, work planning and governance evidence.
- Live CI output and release artifacts remain in their respective systems; link them rather than copying stale results into prose.
- Do not add secrets, real customer data, raw private logs, or large generated model artifacts here.
- Avoid copying the application code into this repository unless a future architecture decision explicitly changes this boundary.

## Document update routing

- New code review finding -> findings register plus assessment update.
- New work -> implementation backlog, optionally linked GitHub issue.
- Changed technical direction -> ADR.
- Changed test/release process -> verification matrix and runbook.
- New runtime behavior -> architecture baseline and relevant operator documentation.
