# Architecture decisions

## Shape
Modular monolith. One deployable, one database, services behind plain functions. Splitting earlier would add network failure modes without a scaling need.

```
api/      routers, auth dependencies, pagination
services/ records, approvals, chat, briefing, audit, integrations   (database)
          policy, intents, priorities, audit_chain, llm, connectors (pure, stdlib only)
domain/   tables and request schemas
```

Pure modules import nothing third-party, so the decisions that matter (what needs approval, what an utterance means, whether the audit chain is intact) are unit-tested without a web stack.

## Decisions

**D1. One policy engine, not per-feature checks.** Chat, API and future agents all call `PolicyEngine.evaluate`. Unknown action types are treated as high-risk external. Escalation by amount, recipient count and public visibility is data-driven.

**D2. The model proposes, code disposes.** The LLM emits steps from a closed tool list; arguments are validated against typed specs; records are resolved by name server-side; external effects exist only as `propose_action`, which always yields a pending approval for model-originated requests and rejects internal record types. Deterministic rules keep a veto: an external verb the plan did not propose gets a proposal injected. Hybrid mode keeps structured commands off the model entirely (cost, latency, determinism).

**D3. Compare-and-set transitions.** Each approval transition is `UPDATE ... WHERE status = :expected`. Two reviewers or a retried request cannot both win. The `executing` claim is committed before any side effect.

**D4. Audit in the caller's transaction, hash-chained.** `prev_hash` is unique, so concurrent writers collide in the database rather than forking the chain; the loser retries inside a SAVEPOINT. Verification is a pure function over rows. Detects edits, deletions and reordering. It does not stop a database owner who recomputes the whole chain: anchor the head hash externally if that threat matters.

**D5. Statuses stored as strings.** Native enum types need `ALTER TYPE` migrations on PostgreSQL every time a state is added. Validation happens at the API boundary with enums.

**D6. UTC datetimes by type.** `UTCDateTime` makes every loaded value aware; naive inputs are interpreted as UTC. Removes a class of comparison bugs between SQLite and PostgreSQL.

**D7. Fail closed on configuration.** Non-sandbox without keys, weak secrets, or half-configured LLM settings stop startup. Live mode without a connector marks the action `failed`.

**D8. Separation of duties is conditional.** A human cannot approve the request they raised (default on outside sandbox). Assistant-originated requests can be approved by the human who asked, which is the point of human-in-the-loop for a small team.

**D9. Compose from results, not predictions.** A second model call writes the reply from executed results; if it fails, a deterministic renderer reports them. The first-pass reply is used only when no tools ran.

**D10. Degrade, don't fail.** Provider errors, budget exhaustion and unrepairable output fall back to the rules, with a visible note. The model is an enhancement to availability-critical paths, never a dependency.

**D11. No chosen model.** Models are a pool, not a setting. Ranking is measured where possible and heuristic otherwise; failures fall through; the rules are always the floor. The cost is one more moving part (discovery, breakers) and unpredictable provider mix, mitigated by `LLM_ALLOW_HOSTED`, budgets and per-message audit of which model acted.

**D12. Retry only what provably did not happen.** Connectors classify failures; duplicates of money, mail or customer-visible actions are worse than a manual re-propose. Unknown outcomes are surfaced, never guessed.

**D13. Notices are not actions.** Operator notifications go only to operator-owned destinations and carry no content, so they sit outside the approval gate.

## Rejected for now
- Background workers for expiry: lazy expiry on read is sufficient until scheduled jobs exist.
- Optimistic concurrency versions on records: last write wins is acceptable single-tenant; audit diffs show what changed.
- Redis rate limiting: needed only with more than one process.

## Failure modes covered by tests
Double approval, execute before approval, execute after expiry, retried execute, duplicate idempotency key, forced status via decision, wildcard characters in search, naive vs aware datetimes, tampered or deleted audit rows, missing/insufficient credentials, self-approval, rate limit, legacy database file, connector missing in live mode.

## Next, in order
0. Run the evaluation script against the target model and tune the prompt; add transactional multi-step plans if partial application proves a problem.
1. Run the PostgreSQL job and the evaluation against real models; tune the prompt from measured failures.
2. Provider connectors that need OAuth (Google Workspace, accounting, CRM) behind the same contract.
3. Knowledge layer: documents, retrieval, evidence-linked answers.
4. Archive/delete flow (always a `data.delete` approval), audit head anchoring, per-requester idempotency, multi-tenancy.
