# Documentation Index

This repository is the documentation, architecture, planning, and governance layer for OS Diablo. It is not the application source repository and a documentation merge does not deploy or change the application.

## Start here

- [v0.4.0 release-candidate review](assessments/2026-10-24-v0.4.0-review.md) — scope, verified observations, limits, and conclusions.
- [Findings register](assessments/findings-register.md) — prioritized technical and operational risks.
- [Current-state architecture](architecture/current-state.md) — what exists versus what is planned.
- [Threat model](security/threat-model.md) — trust boundaries, threats, and required controls.
- [Implementation backlog](roadmap/implementation-backlog.md) — stable task IDs and acceptance criteria.
- [Backlog-to-issue map](roadmap/issue-map.md) — GitHub issue links and finding-to-task traceability for all 20 tasks.
- [Milestones](roadmap/milestones.md) — proposed delivery sequence and exit gates.
- [Release verification runbook](operations/release-verification.md) — repeatable checks for the candidate.
- [Production-readiness checklist](operations/production-readiness-checklist.md) — minimum controls before a real deployment.
- [Verification matrix](quality/verification-matrix.md) — how each claim should be evidenced.
- [ADR-0001: execution safety](decisions/ADR-0001-execution-safety.md) — governing decision for external actions.

## Status vocabulary

- **Implemented** — present in the reviewed source; this does not automatically imply production validation.
- **Partially implemented** — a working foundation exists but a stated capability is incomplete.
- **Planned** — backlog item, not an existing feature.
- **Unverified** — source/configuration may exist, but the relevant test or environment check has not passed.
- **Deferred** — intentionally excluded until its prerequisites or authorization model are ready.
- **Evidence required** — no completion claim is accepted until a test result, CI link, configuration proof, or operator record is attached.

## Review discipline

The baseline assessment is dated 2026-10-24 and concerns the supplied business-management-assistant-ai v0.4.0 archive. Reassess findings after substantive code changes. Keep facts, interpretation, risk, and proposed work separate.
