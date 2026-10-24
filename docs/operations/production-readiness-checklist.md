# Production Readiness Checklist

This checklist is a gate, not an aspirational feature list. Mark an item complete only when evidence is linked.

## Deployment and access
- [ ] Production environment selected explicitly; sandbox is not exposed.
- [ ] Strong API secrets generated, stored externally, inventoried and rotatable.
- [ ] Public ingress is TLS-protected and access controls are verified at the actual network boundary.
- [ ] Rate limits, request size/timeouts and abuse controls are configured.
- [ ] Admin, operator and viewer permissions are tested, including denied requests.
- [ ] Database, API and model-provider credentials follow least privilege.

## Data and model governance
- [ ] Data classes and allowed destinations are documented.
- [ ] Hosted model use is explicitly allowed or disabled by policy; provider allowlist is documented.
- [ ] Prompt/context minimization and secret/PII redaction are tested where required.
- [ ] Logs do not include secrets or unnecessary customer content.
- [ ] Evaluation data is authorized, versioned, representative and separated into development/holdout sets.
- [ ] Model/provider changes pass regression tests before being used for external actions.

## Execution and connectors
- [ ] Every external action has explicit authorization and approval requirements.
- [ ] Idempotency and retry behavior are documented for each connector/action.
- [ ] Unknown outcomes are surfaced and reconciled, not blindly retried.
- [ ] Connector credentials, scopes, health, quotas and failure alerts are tested.
- [ ] Staging uses recipient/endpoint allowlists and cannot reach real customers accidentally.
- [ ] Irreversible financial and contract actions remain outside the planner unless separately approved and audited.

## Data durability and audit
- [ ] Backup schedule and retention are defined.
- [ ] A restore has been completed successfully in an isolated environment.
- [ ] Recovery point objective (RPO) and recovery time objective (RTO) are agreed.
- [ ] Schema upgrade path from the last supported version is tested.
- [ ] Deletion, archival, legal hold and backup retention behavior are documented.
- [ ] Audit chain is verified, and independent anchoring/retention is implemented or formally risk-accepted.

## Operations
- [ ] Logs, metrics, traces, dashboards and alerts are tested.
- [ ] On-call owner and incident escalation path are defined.
- [ ] Runbooks cover model outage, connector outage, stuck execution, unknown outcome, migration failure and data restore.
- [ ] Health checks distinguish process health, database readiness and critical dependency capability.
- [ ] CI is green for the exact candidate commit; dependency and secret scanning are in scope.
- [ ] Rollback/recovery plan is tested, not just written.

## Release decision
- [ ] P0 findings closed.
- [ ] All mandatory verification steps completed or formally blocked with a documented exception.
- [ ] Residual risks accepted by an accountable owner.
- [ ] Candidate version and checksums recorded.
- [ ] Go/no-go decision and evidence links archived.
