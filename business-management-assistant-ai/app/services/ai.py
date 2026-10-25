from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.services import intents as I
from app.services.local_models import catalog as local_model_catalog
from app.services.local_models import task_recommendations


@dataclass(frozen=True)
class ModelRoute:
    capability: str
    model: str
    rationale: str
    tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentDefinition:
    key: str
    name: str
    mission: str
    capabilities: tuple[str, ...]
    default_route: str
    approval_sensitive: bool = False


CAPABILITY_INTEGRATIONS: dict[str, tuple[str, ...]] = {
    "seo": ("Search Console", "Web Analytics", "SEO Research", "Content Management System"),
    "advertising": ("Google Ads", "Meta Ads", "LinkedIn Ads", "TikTok Ads", "Web Analytics"),
    "finance": ("Accounting", "Invoicing", "Banking and Payments"),
    "contracts": ("Contracts and E-Signature", "Cloud Documents"),
    "customer_success": ("CRM", "Customer Support", "Email"),
}

# Which specialist owns an intent; used to attribute chat replies and plans.
INTENT_AGENT = {
    I.BRIEFING: "chief_of_staff",
    I.CREATE_GOAL: "planner",
    I.CREATE_PROJECT: "planner",
    I.CREATE_TASK: "planner",
    I.COMPLETE_TASK: "operations",
    I.LIST: "operations",
    I.CREATE_CONTACT: "commercial",
    I.SEARCH: "knowledge",
    I.SEO: "growth",
    I.ADVERTISING: "growth",
    I.PROTECTED: "quality",
}


class ModelRouter:
    """Provider-neutral routing policy; production loads the live catalog at runtime."""

    routes = {
        "classification": ModelRoute("classification", "fast-workhorse", "high-volume, low-latency work", ("extract", "classify")),
        "planning": ModelRoute("planning", "balanced-reasoner", "structured decomposition and tool use", ("plan", "delegate")),
        "strategy": ModelRoute("strategy", "high-capability-reasoner", "difficult multi-step decisions", ("research", "evaluate")),
        "multimodal": ModelRoute("multimodal", "long-context-multimodal", "documents, images, audio, and video", ("vision", "transcribe")),
        "advertising": ModelRoute("advertising", "balanced-reasoner", "campaign planning and performance analysis", ("ads.read", "ads.draft")),
        "seo": ModelRoute("seo", "balanced-reasoner", "search visibility analysis and content planning", ("seo.audit", "seo.draft")),
        "finance": ModelRoute("finance", "high-capability-reasoner", "financial operations with evidence and review", ("finance.read", "finance.prepare")),
        "contracts": ModelRoute("contracts", "high-capability-reasoner", "obligation extraction and risk review", ("contracts.extract", "contracts.compare")),
        "customer_success": ModelRoute("customer_success", "balanced-reasoner", "support triage and relationship continuity", ("crm.read", "support.draft")),
    }

    agents = (
        AgentDefinition("chief_of_staff", "Chief of Staff", "Turn business intent into priorities, decisions, and coordinated execution.", ("briefing", "prioritisation", "decisions"), "strategy"),
        AgentDefinition("planner", "Planner", "Decompose goals into milestones, tasks, owners, and dependencies.", ("planning", "scheduling", "dependencies"), "planning"),
        AgentDefinition("operations", "Operations Manager", "Run recurring workflows, monitor exceptions, and escalate blockers.", ("workflow", "monitoring", "escalation"), "planning"),
        AgentDefinition("growth", "Growth Manager", "Coordinate advertising, SEO, content, analytics, and experiments.", ("advertising", "seo", "analytics", "experiments"), "advertising"),
        AgentDefinition("commercial", "Commercial Manager", "Manage leads, customer relationships, proposals, and renewals.", ("crm", "pipeline", "customer_success"), "customer_success"),
        AgentDefinition("finance", "Finance Operations Manager", "Organise cash visibility, budgets, invoices, and financial controls.", ("finance", "forecasting", "reconciliation"), "finance", True),
        AgentDefinition("contracts", "Contracts Manager", "Track agreements, obligations, renewals, and review risks.", ("contracts", "compliance", "obligations"), "contracts", True),
        AgentDefinition("knowledge", "Knowledge Manager", "Maintain evidence-linked business memory and searchable context.", ("retrieval", "indexing", "source_tracking"), "multimodal"),
        AgentDefinition("integrations", "Integration Manager", "Select safe connectors, check health, and enforce least privilege.", ("connectors", "scopes", "health"), "planning", True),
        AgentDefinition("quality", "Quality and Risk Manager", "Verify outputs, enforce policy, and identify uncertainty before action.", ("evaluation", "policy", "audit"), "strategy", True),
    )

    def __init__(self, mode: str = "sandbox", models_dir: str = "models", llm_configured: bool = False, assistant_mode: str = "rules") -> None:
        self.mode = mode
        self.models_dir = models_dir
        self.llm_configured = llm_configured
        self.assistant_mode = assistant_mode
        self._agents = {agent.key: agent for agent in self.agents}

    def select(self, capability: str) -> ModelRoute:
        return self.routes.get(capability, self.routes["planning"])

    def agent_for_intent(self, intent: str) -> AgentDefinition | None:
        key = INTENT_AGENT.get(intent)
        return self._agents.get(key) if key else None

    def plan(self, request: str, capability: str = "planning") -> dict[str, Any]:
        route = self.select(capability)
        return {
            "request": request,
            "route": route.model,
            "capability": route.capability,
            "rationale": route.rationale,
            "tools": list(route.tools),
            "required_integrations": list(CAPABILITY_INTEGRATIONS.get(capability, ())),
            "mode": self.mode,
            "next": "connect a provider adapter and execute only approved tools",
        }

    def capability_catalog(self) -> dict[str, Any]:
        return {
            "agents": [asdict(agent) for agent in self.agents],
            "routes": [asdict(route) for route in self.routes.values()],
            "local_models": local_model_catalog(),
            "policies": {
                "sandbox_default": self.mode == "sandbox",
                "protected_actions_require_approval": True,
                "external_credentials_in_source": False,
                "model_catalog_loaded_at_runtime": True,
                "llm_planner_configured": self.llm_configured,
                "assistant_mode": self.assistant_mode,
                "external_actions_only_via_approval": True,
            },
        }

    def local_fallback(self, task: str) -> dict[str, Any]:
        """Recommend the smallest prepared model for a task; large models remain the evaluator."""
        return {
            "task": task,
            "recommendations": task_recommendations(task),
            "policy": "Use a local model for bounded, low-risk work; escalate uncertain or high-impact results to the larger evaluator.",
        }
