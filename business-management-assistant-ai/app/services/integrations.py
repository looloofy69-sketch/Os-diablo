from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.domain.models import Integration, now
from app.services.audit import record_event
from app.services.connectors import ConnectorRegistry
from app.services.context import SYSTEM, Ctx

# Registry only: credentials and live permissions are never embedded in source code.
# Each entry represents a connector family that can later be replaced by a provider adapter.
DEFAULT_INTEGRATIONS = [
    ("Email", "communications", ["read", "draft"]),
    ("Calendar", "productivity", ["read", "draft_events"]),
    ("Video Meetings", "communications", ["read", "draft_meetings"]),
    ("Team Chat", "communications", ["read", "draft_messages"]),
    ("Cloud Documents", "knowledge", ["read", "index"]),
    ("Project Management", "operations", ["read", "draft_tasks"]),
    ("CRM", "commercial", ["read", "draft_updates"]),
    ("Customer Support", "customer_success", ["read", "draft_replies"]),
    ("Accounting", "finance", ["read", "prepare_exports"]),
    ("Banking and Payments", "finance", ["read", "prepare_transactions"]),
    ("Invoicing", "finance", ["read", "draft_invoices"]),
    ("Contracts and E-Signature", "legal_operations", ["read", "extract_obligations"]),
    ("Human Resources", "people", ["read", "draft_workflows"]),
    ("E-Commerce", "commerce", ["read", "draft_catalog_updates"]),
    ("Subscriptions", "commerce", ["read", "draft_changes"]),
    ("Google Ads", "advertising", ["read", "draft_campaigns", "draft_reports"]),
    ("Meta Ads", "advertising", ["read", "draft_campaigns", "draft_reports"]),
    ("LinkedIn Ads", "advertising", ["read", "draft_campaigns", "draft_reports"]),
    ("TikTok Ads", "advertising", ["read", "draft_campaigns", "draft_reports"]),
    ("Search Console", "seo", ["read", "indexing_insights"]),
    ("Web Analytics", "analytics", ["read", "report"]),
    ("SEO Research", "seo", ["read", "draft_audits"]),
    ("Content Management System", "content", ["read", "draft_content"]),
    ("Social Publishing", "marketing", ["read", "draft_posts"]),
    ("Email Marketing", "marketing", ["read", "draft_campaigns"]),
    ("Affiliate and Referral", "marketing", ["read", "draft_reports"]),
    ("Webhooks", "automation", ["receive", "draft_events"]),
    ("Workflow Automation", "automation", ["read", "draft_workflows"]),
    ("Data Warehouse", "analytics", ["read", "query"]),
    ("Customer Data Platform", "analytics", ["read", "segment"]),
    ("Developer Repository", "engineering", ["read", "draft_issues"]),
    ("Deployment and Monitoring", "engineering", ["read", "draft_incidents"]),
    ("Creative Production", "creative_production", ["read", "draft_jobs"]),
]


def seed_integrations(session: Session) -> None:
    """Idempotent and safe under concurrent startup: the unique name constraint arbitrates."""
    existing = {item.name for item in session.exec(select(Integration)).all()}
    for name, category, scopes in DEFAULT_INTEGRATIONS:
        if name in existing:
            continue
        try:
            with session.begin_nested():
                session.add(Integration(name=name, category=category, scopes=scopes))
        except IntegrityError:
            continue
    session.commit()


def _connector_for(registry: ConnectorRegistry, integration_name: str):
    return next((c for c in registry.connectors if integration_name in c.integrations), None)


def check_integration(session: Session, integration: Integration, ctx: Ctx, registry: ConnectorRegistry) -> Integration:
    """Sandbox reports registry readiness only. Live mode asks the connector (e.g. an SMTP NOOP); nothing is ever sent."""
    integration.last_checked_at = now()
    detail = ""
    if registry.sandbox:
        integration.health = "sandbox_ready"
    else:
        connector = _connector_for(registry, integration.name)
        if connector is None:
            integration.health, integration.enabled = "not_configured", False
        else:
            result = connector.health()
            integration.health, integration.enabled, detail = ("connected" if result.ok else "unhealthy"), True, result.detail
    session.add(integration)
    record_event(session, "integration.health_checked", ctx.actor, integration.id, {"health": integration.health, "detail": detail}, ctx.request_id)
    session.commit()
    session.refresh(integration)
    return integration


def sync_connector_integrations(session: Session, registry: ConnectorRegistry) -> int:
    """Mark integrations backed by a configured connector as enabled and check them. Safe to call on every start."""
    touched = 0
    for connector in registry.connectors:
        for name in connector.integrations:
            row = session.exec(select(Integration).where(Integration.name == name)).first()
            if row is not None:
                check_integration(session, row, SYSTEM, registry)
                row.enabled = True
                session.add(row)
                touched += 1
    session.commit()
    return touched
