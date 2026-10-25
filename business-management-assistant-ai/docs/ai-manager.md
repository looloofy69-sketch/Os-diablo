# Enhanced AI manager

## Operating model

The manager is an orchestrator over specialist agents rather than a single unbounded chatbot. It retrieves approved context, classifies intent, chooses a capability route, plans tool calls, validates the result, and records the outcome. The current implementation is intentionally provider-neutral and sandbox-safe.

## Specialist agents

The first registry includes a Chief of Staff, Planner, Operations Manager, Growth Manager, Commercial Manager, Finance Operations Manager, Contracts Manager, Knowledge Manager, Integration Manager, and Quality and Risk Manager.

Each agent has a mission, capabilities, default model route, and an approval-sensitive flag. The runtime catalog is available at `GET /api/ai/capabilities`.

## Conversational management

`POST /api/chat` accepts a conversation ID, user message, and actor. The assistant currently supports direct commands for:

- Business briefings
- Creating goals, projects, tasks, and contacts
- Listing goals, projects, and tasks
- Advertising and SEO planning requests
- External actions such as sending, publishing, paying, or buying, which are converted into approval-required proposals

Conversation and message history are stored through `GET /api/conversations` and `GET /api/conversations/{id}/messages`.

## Integration policy

The registry includes broad connector families for communications, productivity, documents, project management, CRM, support, finance, contracts, HR, commerce, advertising, SEO, analytics, content, social publishing, automation, engineering, and creative production. This is a capability inventory, not a silent connection mechanism. Credentials, scopes, provider-specific APIs, and external writes must be configured and approved separately.

The two previously named integrations were removed from both the registry and the product tests.

## Next production upgrades

1. Add authenticated users and tenant isolation.
2. Replace local heuristic intent routing with runtime model-provider adapters.
3. Add tool contracts for each connector family.
4. Add policy-as-code and per-tool budgets.
5. Add background jobs for long-running research, reporting, and synchronisation.
6. Add evaluation datasets for intent, action safety, and factual grounding.


## LLM planner (0.3)

The specialist agents above are routing labels. Execution is a single planner loop in `services/chat.py`:
rules classify the message, `services/planner.py` defines the tool contract and validates model output,
`services/tools.py` runs each validated step through `services/records.py` and `services/approvals.py`.
Adding a capability means adding a `ToolSpec` and a handler; an import-time assertion keeps the two in sync.
External effects are never tools of their own: they are `propose_action` requests that a person approves.
