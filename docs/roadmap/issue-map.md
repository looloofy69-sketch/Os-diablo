# Backlog-to-Issue Synchronization Map

This file is the synchronization index between the canonical Markdown backlog, findings register, and GitHub Issues. The Markdown backlog owns task scope and acceptance criteria; GitHub Issues own discussion, assignment, implementation tracking, and evidence. Keep both synchronized.

## Backlog task index

| ID | Priority | Task | GitHub issue | Status |
| --- | --- | --- | --- | --- |
| SEC-01 | P0 | Prevent unsafe sandbox exposure | [#2](https://github.com/looloofy69-sketch/Os-diablo/issues/2) | Open |
| SEC-02 | P0 | Make model data egress an explicit policy | [#3](https://github.com/looloofy69-sketch/Os-diablo/issues/3) | Open |
| REL-01 | P0 | Complete dependency-backed release verification | [#4](https://github.com/looloofy69-sketch/Os-diablo/issues/4) | Open |
| REL-02 | P0 | Add dependency and secret-scan release controls | [#5](https://github.com/looloofy69-sketch/Os-diablo/issues/5) | Open |
| WF-01 | P1 | Durable workflow execution state | [#6](https://github.com/looloofy69-sketch/Os-diablo/issues/6) | Open |
| WF-02 | P1 | Idempotency, retry, cancellation and compensation | [#7](https://github.com/looloofy69-sketch/Os-diablo/issues/7) | Open |
| OPS-01 | P1 | Backup, restore and disaster recovery | [#8](https://github.com/looloofy69-sketch/Os-diablo/issues/8) | Open |
| OBS-01 | P1 | Operational observability and alerts | [#9](https://github.com/looloofy69-sketch/Os-diablo/issues/9) | Open |
| AUD-01 | P1 | Independently anchor audit-chain evidence | [#10](https://github.com/looloofy69-sketch/Os-diablo/issues/10) | Open |
| AI-01 | P1 | Expand model evaluation and regression gates | [#11](https://github.com/looloofy69-sketch/Os-diablo/issues/11) | Open |
| PERF-01 | P1 | Integrate and verify v0.4.1 performance/logic-validation candidate | [#22](https://github.com/looloofy69-sketch/Os-diablo/issues/22) | Open / source-repo integration and release gates pending |
| INT-01 | P1 | Connector capability and delivery lifecycle | [#12](https://github.com/looloofy69-sketch/Os-diablo/issues/12) | Open |
| DB-01 | P1 | Migration and data lifecycle policy | [#13](https://github.com/looloofy69-sketch/Os-diablo/issues/13) | Open |
| AUTH-01 | P2 | Identity and API-key lifecycle management | [#14](https://github.com/looloofy69-sketch/Os-diablo/issues/14) | Open |
| DOMAIN-01 | P2 | First complete business workflow | [#15](https://github.com/looloofy69-sketch/Os-diablo/issues/15) | Open |
| UI-01 | P2 | Operator workflows and recovery screens | [#16](https://github.com/looloofy69-sketch/Os-diablo/issues/16) | Open |
| SCHED-01 | P2 | Durable scheduler, after prerequisites | [#17](https://github.com/looloofy69-sketch/Os-diablo/issues/17) | Open / blocked by prerequisites |
| KNOW-01 | P2 | Governed documents and knowledge layer | [#18](https://github.com/looloofy69-sketch/Os-diablo/issues/18) | Open / dependency-gated |
| INT-02 | P2 | OAuth-backed provider adapters | [#19](https://github.com/looloofy69-sketch/Os-diablo/issues/19) | Open / provider selection required |
| TEN-01 | P2 | Prove tenant isolation before shared hosting | [#20](https://github.com/looloofy69-sketch/Os-diablo/issues/20) | Open / explicitly deferred |
| SAFE-01 | P3 | Separate gateway for irreversible financial/legal actions | [#21](https://github.com/looloofy69-sketch/Os-diablo/issues/21) | Open / explicitly deferred |

**Coverage:** 21 backlog tasks have corresponding GitHub Issues. Issue #1 is the merged documentation PR; task issues are #2–#22.

## Finding-to-task traceability

| Finding | Primary task(s) |
| --- | --- |
| F-01 — unsafe sandbox exposure | SEC-01 |
| F-02 — hosted-model data egress | SEC-02 |
| F-03 — incomplete release verification | REL-01, PERF-01 |
| F-04 — key lifecycle | AUTH-01 |
| F-05 — coarse-grained authorization | AUTH-01 |
| F-06 — multi-step recovery | WF-01, WF-02 |
| F-07 — integration catalog vs implementation | INT-01 |
| F-08 — unverified integration health/delivery | INT-01 |
| F-09 — disaster recovery | OPS-01 |
| F-10 — independent audit trust anchor | AUD-01 |
| F-11 — small model evaluation set | AI-01, PERF-01 |
| F-12 — observability and alerting | OBS-01 |
| F-13 — deletion/archive/retention lifecycle | DB-01 |
| F-14 — migration evolution | DB-01 |
| F-15 — incomplete business-domain model | DOMAIN-01 |
| F-16 — incomplete operator UX | UI-01 |
| F-17 — durable scheduler | SCHED-01 |
| F-18 — OAuth/provider integrations | INT-02 |
| F-19 — documents/knowledge layer | KNOW-01 |
| F-20 — tenant isolation | TEN-01 |
| F-21 — dependency/supply-chain controls | REL-02 |
| F-22 — irreversible financial/legal actions | SAFE-01 |

## Sync rules

1. New backlog task: assign a stable ID, add acceptance criteria, create a GitHub Issue, then update this map.
2. Changed task scope or priority: update both the backlog and the Issue; preserve the link to the task ID.
3. Closed Issue: do not automatically consider the task done. Require acceptance criteria and verification evidence in the Issue or linked PR.
4. New finding: add it to the findings register and map it to an existing task or create a new task/Issue.
5. Issue state in this document is a snapshot; use the live issue URL for current state. Refresh status as part of planning/release reviews.
