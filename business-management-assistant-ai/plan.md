> Status note (0.3): this file records the original 0.1 direction. Current decisions live in `docs/architecture-decisions.md`.

# Implementation plan

## Objective

Deliver a private, runnable foundation for a new-business AI operating system. The first version provides a safe internal control plane for business records, workflow proposals, approvals, audit events, and integration metadata.

## Architecture

- `app/domain`: persistence models and domain enums.
- `app/services`: policy, audit, AI routing, and integration services.
- `app/api`: HTTP routes and request/response schemas.
- `static`: intentionally small executive control-room UI.
- `tests`: API and service-level tests.
- `docs`: product foundation and operating policies.
- `config`: non-secret example configuration.

The service uses FastAPI and SQLModel. SQLite is the default local database; the `DATABASE_URL` setting supports PostgreSQL-compatible deployments. The AI layer is provider-neutral and exposes a model-routing contract without embedding provider secrets. Connector adapters are registered with scopes and health metadata before any live capability is enabled.

## Design direction

**Design movement:** quiet enterprise control room: editorial typography, high signal density, and deliberate status colour.

**Core principles:** calm over flashy; evidence before action; visible system state; progressive disclosure.

**Colour philosophy:** warm off-white surfaces reduce fatigue, graphite text creates authority, and a single electric-cyan accent marks live system intelligence without making risk states ambiguous. Amber and red are reserved for pending approvals and blocked actions.

**Layout paradigm:** a left operational rail with a wide briefing canvas and stacked decision queues, rather than a generic centred dashboard grid.

**Signature elements:** a live-system pulse line, evidence/source chips, and approval cards that show exact proposed payloads.

**Interaction philosophy:** every action is reversible where possible; risky actions reveal their payload and pause for approval; empty states explain the next best action.

**Typography:** Inter for interface text, IBM Plex Mono for identifiers, timestamps, and audit values.

**Brand essence:** an AI chief-of-staff layer for founders and operating teams that turns intent into controlled execution. Personality: composed, rigorous, anticipatory.

## Safety and scope

Local sandbox mode never sends external messages, pays, publishes, deletes, or changes permissions. Protected actions are represented as approval requests. A production deployment must add authentication, encrypted secrets, background workers, rate limits, policy-as-code, provider adapters, and observability.
