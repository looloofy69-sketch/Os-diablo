# ADR-0001: External Action Execution Safety

- **Status:** Accepted as a governing design requirement
- **Date:** 2026-10-24
- **Scope:** Planning and implementation guidance for OS Diablo and the reviewed application

## Context

The system can generate plans and invoke external connectors. Provider requests can time out after reaching the receiver, multi-step plans can partially complete, and audit records cannot reverse a side effect. A retry that is safe for one connector/action may duplicate an action in another.

## Decision

External actions must use a durable execution record and an explicit outcome state. At minimum:

- proposed;
- awaiting approval;
- approved;
- executing;
- succeeded;
- failed with confirmed no side effect;
- outcome unknown / reconciliation required;
- cancelled before side effect;
- compensated, where a valid compensation action exists.

Every execution and step must have a stable identifier, idempotency key, actor, approval reference, policy decision, timestamps, connector/action type, external identifier when available, and sanitized result classification.

Only failures that prove the provider did not process the request may be automatically retried. Unknown outcomes require reconciliation or an explicit operator decision. Compensation is a new action with its own authorization and audit record; it is not equivalent to rolling back a database transaction.

## Consequences

**Benefits:** safer retries, clear partial completion, operator recovery, traceability and more reliable incident diagnosis.

**Costs:** additional persistence, state transitions, migrations, concurrency controls, UI work and connector-specific semantics.

**Non-goals:** guaranteeing true atomic transactions across unrelated external systems; fully automating irreversible financial or legal actions; treating a hash-chain as proof against a database administrator.

## Acceptance requirements

WF-01 and WF-02 in the implementation backlog operationalize this decision. Implementation is not considered complete until restart, concurrency, duplicate-request, timeout and partial-failure tests pass.
