"""Builds connectors and the notifier from settings. Credentials come only from configuration."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from app.core import Settings
from app.services.connector_email import EMAIL_RE, EmailConnector, SmtpConfig, default_smtp_factory
from app.services.connector_http import (
    HttpPost,
    SignedWebhookConnector,
    SlackConnector,
    parse_webhook_routes,
    urllib_post,
)
from app.services.connectors import Connector, ConnectorRegistry
from app.services.netutil import is_private_host
from app.services.notifier import Notifier

log = logging.getLogger("bma.notify")


def build_connectors(settings: Settings, *, smtp_factory: Callable[[SmtpConfig], Any] | None = None, post: HttpPost | None = None) -> list[Connector]:
    """Validates configuration (raises ValueError) and returns live connectors in resolution order: email, Slack, webhooks."""
    connectors: list[Connector] = []
    insecure_ok = settings.is_sandbox
    if settings.smtp_host:
        if not settings.smtp_sender or not EMAIL_RE.match(settings.smtp_sender):
            raise ValueError("SMTP_HOST requires SMTP_SENDER to be a valid email address")
        if settings.smtp_username and not settings.smtp_password:
            raise ValueError("SMTP_USERNAME requires SMTP_PASSWORD")
        if settings.smtp_security == "none" and not settings.is_sandbox and not is_private_host(f"http://{settings.smtp_host}"):
            raise ValueError("Outside sandbox, SMTP_SECURITY=none is only allowed for private hosts")
        domains = tuple(d.strip().lower().lstrip("@") for d in re.split(r"[,\s]+", settings.smtp_allowed_domains) if d.strip())
        config = SmtpConfig(
            host=settings.smtp_host, port=settings.smtp_port, sender=settings.smtp_sender, username=settings.smtp_username,
            password=settings.smtp_password.get_secret_value() if settings.smtp_password else None, security=settings.smtp_security, allowed_domains=domains,
        )
        connectors.append(EmailConnector(config, smtp_factory or default_smtp_factory))
    if settings.slack_webhook_url:
        connectors.append(SlackConnector(settings.slack_webhook_url.get_secret_value(), post or urllib_post, allow_insecure_remote=insecure_ok))
    routes = parse_webhook_routes(settings.webhook_routes, allow_insecure_remote=insecure_ok)
    if routes:
        connectors.append(SignedWebhookConnector(routes, post or urllib_post))
    return connectors


def build_registry(settings: Settings, connectors: list[Connector] | None = None, **kwargs: Any) -> ConnectorRegistry:
    registry = ConnectorRegistry(sandbox=settings.is_sandbox)
    for connector in connectors if connectors is not None else build_connectors(settings, **kwargs):
        registry.register(connector)
    return registry


def build_notifier(settings: Settings, registry: ConnectorRegistry, *, post: HttpPost | None = None, background: bool = True) -> Notifier:
    """Notices go only to operator-owned destinations (NOTIFY_EMAIL, NOTIFY_WEBHOOK_URL). Sandbox logs instead of sending."""
    sinks: list[Callable[[str, str, str], None]] = []

    def logged(result: Any) -> None:
        if not result.ok:
            log.warning("notification not delivered: %s", result.detail)

    email = next((c for c in registry.connectors if isinstance(c, EmailConnector)), None)
    if settings.notify_email and email is not None:
        recipient = settings.notify_email
        sinks.append(lambda key, title, body: logged(email.execute(action_type="message.send", target=recipient, payload={"subject": title, "body": body}, idempotency_key=key)))
    if settings.notify_webhook_url:
        hook = SlackConnector(settings.notify_webhook_url.get_secret_value(), post or urllib_post, allow_insecure_remote=settings.is_sandbox)
        sinks.append(lambda key, title, body: logged(hook.execute(action_type="message.send", target="slack", payload={"text": f"{title}\n{body}"}, idempotency_key=key)))
    return Notifier(sinks, live=not settings.is_sandbox, background=background)
