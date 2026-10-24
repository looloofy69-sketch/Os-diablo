# Proposed Delivery Milestones

The sequence below is a dependency-aware proposal, not a commitment to dates. Task IDs link to live issues through the [backlog-to-issue map](issue-map.md).

## M0 — Verify the actual baseline
**Exit gate:** Exact source SHA known; tests and migration/Docker checks recorded; open P0 findings visible; release disposition documented.

Includes REL-01, investigation of SEC-01/SEC-02 behavior, and a runbook-tested local SMTP/model evaluation setup.

## M1 — Safe deployment boundary
**Exit gate:** Production/staging cannot start with unsafe authentication; model egress is controlled and tested; secrets and network exposure checklist is complete.

Includes SEC-01, SEC-02, REL-02.

## M2 — Recoverable actions
**Exit gate:** Process restart, timeout, duplicate request, partial failure and unknown outcomes are covered by automated tests; operator can reconcile state.

Includes WF-01 and WF-02.

## M3 — Operable service
**Exit gate:** Backup restore drill passes; monitoring and alerts are exercised; audit anchor verification and incident runbooks are available.

Includes OPS-01, OBS-01 and AUD-01.

## M4 — Evidence-based model and connector quality
**Exit gate:** Evaluations are versioned, representative and regression-gated; connector health distinguishes configured from verified; test services exercise delivery outcomes.

Includes AI-01 and INT-01.

## M5 — First complete business workflow
**Exit gate:** One prioritized business workflow is implemented end-to-end with domain invariants, permissions, UI/API coverage, migration path, audit evidence, and operator runbook.

Includes DOMAIN-01 and relevant parts of UI-01. Choose the domain only after validating the intended business use case.

## M6 — Controlled expansion
OAuth providers, document retrieval, scheduling, and tenancy are sequenced independently after their dependencies. Do not make multi-tenancy or broad autonomy a prerequisite for a useful single-organization deployment.
