import smtplib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import create_app
from app.services.connector_setup import build_registry
from app.services.connectors import ConnectorRegistry, ConnectorResult, HealthResult
from app.services.notifier import Notifier
from tests.api.conftest import ADMIN, ADMIN2, KEYS, OPERATOR, as_, make_settings


class FakeSMTP:
    def __init__(self):
        self.sent, self.fail_connect, self.send_error = [], None, None

    def factory(self, _config):
        if self.fail_connect:
            raise self.fail_connect
        return self

    def send_message(self, msg, to_addrs=None):
        if self.send_error:
            raise self.send_error
        self.sent.append((msg, to_addrs))

    def noop(self):
        return 250, b"ok"

    def quit(self):
        pass


SMTP = {"smtp_host": "smtp.test", "smtp_sender": "bot@corp.test", "smtp_allowed_domains": "corp.test"}


class TypedOutcomeConnector:
    name = "typed-outcome-test"
    integrations = ()

    def __init__(self, detail, outcome_unknown):
        self.detail = detail
        self.outcome_unknown = outcome_unknown

    def supports(self, action_type, target):
        return action_type == "message.send"

    def execute(self, *, action_type, target, payload, idempotency_key):
        return ConnectorResult(
            ok=False, dry_run=False, detail=self.detail,
            retryable=False, outcome_unknown=self.outcome_unknown,
        )

    def health(self):
        return HealthResult(True, "test connector")


def live_app(fake, notifier=None, **overrides):
    settings = make_settings(environment="staging", api_keys=KEYS, **{**SMTP, **overrides})
    registry = build_registry(settings, smtp_factory=fake.factory)
    return TestClient(create_app(settings, connectors=registry, notifier=notifier))


def propose(c, key=OPERATOR, **overrides):
    body = {"action_type": "message.send", "target": "alex@corp.test", "reason": "Pilot follow-up", "payload": {"subject": "Pilot", "body": "Hi Alex"}}
    body.update(overrides)
    r = c.post("/api/actions/propose", json=body, headers=as_(key))
    assert r.status_code == 201, r.text
    return r.json()


def approve(c, item, key=ADMIN, **extra):
    return c.post(f"/api/approvals/{item['id']}/decision", json={"decision": "approved", **extra}, headers=as_(key))


def test_approved_email_is_really_sent_through_the_connector():
    fake = FakeSMTP()
    with live_app(fake) as c:
        item = propose(c)
        done = approve(c, item, execute=True).json()
        assert done["status"] == "executed" and done["result"]["dry_run"] is False
        message, recipients = fake.sent[0]
        assert (message["Subject"], recipients) == ("Pilot", ["alex@corp.test"])
        assert message["Message-ID"] == f"<{item['id']}@corp.test>"
        assert [e["event_type"] for e in c.get("/api/audit", params={"target": item["id"], "event_type": "action.executed"}, headers=as_(ADMIN)).json()]


def test_sandbox_never_sends_even_with_smtp_configured():
    fake = FakeSMTP()
    settings = make_settings(**SMTP)
    with TestClient(create_app(settings, connectors=build_registry(settings, smtp_factory=fake.factory))) as c:
        item = c.post("/api/actions/propose", json={"action_type": "message.send", "target": "alex@corp.test", "reason": "r", "payload": {"subject": "s", "body": "b"}}).json()
        done = c.post(f"/api/approvals/{item['id']}/decision", json={"decision": "approved", "execute": True}).json()
        assert done["result"]["dry_run"] is True and fake.sent == []
        listing = c.get("/api/connectors").json()
        assert listing["live"] is False and listing["connectors"][0]["name"] == "smtp-email"
        email = [i for i in c.get("/api/integrations", params={"limit": 200}).json() if i["name"] == "Email"][0]
        assert email["enabled"] is True and email["health"] == "sandbox_ready"


def test_recipients_outside_allowed_domains_fail_without_retry():
    fake = FakeSMTP()
    with live_app(fake) as c:
        item = propose(c, target="someone@real-customer.com")
        done = approve(c, item, execute=True).json()
        assert done["status"] == "failed" and "allowed domains" in done["result"]["detail"] and fake.sent == []
        assert c.post(f"/api/approvals/{item['id']}/retry", headers=as_(ADMIN)).status_code == 409


def test_failed_before_contact_can_be_retried_once_the_server_is_back():
    fake = FakeSMTP()
    fake.fail_connect = ConnectionRefusedError()
    with live_app(fake) as c:
        item = propose(c)
        failed = approve(c, item, execute=True).json()
        assert failed["status"] == "failed" and failed["result"]["retryable"] is True
        fake.fail_connect = None
        retried = c.post(f"/api/approvals/{item['id']}/retry", params={"execute": True}, headers=as_(ADMIN2)).json()
        assert retried["status"] == "executed" and len(fake.sent) == 1
        types = [e["event_type"] for e in c.get("/api/audit", params={"target": item["id"]}, headers=as_(ADMIN)).json()]
        assert "action.retry_authorized" in types


def test_unknown_outcome_is_never_retried():
    fake = FakeSMTP()
    fake.send_error = smtplib.SMTPServerDisconnected("dropped")
    with live_app(fake) as c:
        item = propose(c)
        failed = approve(c, item, execute=True).json()
        assert failed["result"]["retryable"] is False and failed["result"]["outcome_unknown"] is True
        assert c.post(f"/api/approvals/{item['id']}/retry", headers=as_(ADMIN)).status_code == 409


def test_approval_persists_typed_outcome_without_parsing_error_text():
    settings = make_settings(environment="staging", api_keys=KEYS, **SMTP)
    for detail, unknown in (("connection interrupted", True), ("outcome unknown", False)):
        registry = ConnectorRegistry(sandbox=False)
        registry.register(TypedOutcomeConnector(detail, unknown))
        with TestClient(create_app(settings, connectors=registry)) as c:
            item = propose(c)
            failed = approve(c, item, execute=True).json()
            assert failed["status"] == "failed"
            assert failed["result"]["detail"] == detail
            assert failed["result"]["outcome_unknown"] is unknown
            assert failed["result"]["retryable"] is False


def test_reviewer_can_amend_a_request_that_lacks_content_before_approving():
    fake = FakeSMTP()
    with live_app(fake) as c:
        chat = c.post("/api/chat", json={"message": "send the deck to alex@corp.test"}, headers=as_(ADMIN)).json()
        item = c.get(f"/api/approvals/{chat['approval_id']}", headers=as_(ADMIN)).json()
        assert "subject" not in item["payload"]
        failed_probe = c.post(f"/api/approvals/{item['id']}/amend", json={}, headers=as_(ADMIN))
        assert failed_probe.status_code == 422  # nothing to change
        amended = c.post(f"/api/approvals/{item['id']}/amend", json={"payload": {"subject": "The deck", "body": "Attached soon."}}, headers=as_(ADMIN)).json()
        assert amended["payload"]["subject"] == "The deck" and amended["status"] == "pending"
        done = approve(c, item, execute=True).json()
        assert done["status"] == "executed" and fake.sent[0][0]["Subject"] == "The deck"
        change = c.get("/api/audit", params={"event_type": "action.amended"}, headers=as_(ADMIN)).json()[0]["details"]["changes"]
        assert "payload" in change
        assert c.post(f"/api/approvals/{item['id']}/amend", json={"reason": "x"}, headers=as_(ADMIN)).status_code == 409  # no longer pending
        assert c.post(f"/api/approvals/{item['id']}/amend", json={"reason": "x"}, headers=as_(OPERATOR)).status_code == 403


def test_amend_reevaluates_risk():
    with live_app(FakeSMTP()) as c:
        item = propose(c, action_type="invoice.send", payload={"subject": "Invoice", "body": "Due", "amount": 10})
        assert item["risk"] == "high"
        bigger = c.post(f"/api/approvals/{item['id']}/amend", json={"payload": {"subject": "Invoice", "body": "Due", "amount": 50000}}, headers=as_(ADMIN)).json()
        assert bigger["risk"] == "critical"


def test_integration_health_uses_the_connector_in_live_mode():
    fake = FakeSMTP()
    with live_app(fake) as c:
        email = [i for i in c.get("/api/integrations", params={"limit": 200}, headers=as_(ADMIN)).json() if i["name"] == "Email"][0]
        assert email["enabled"] is True and email["health"] == "connected"
        fake.fail_connect = ConnectionRefusedError()
        assert c.post(f"/api/integrations/{email['id']}/check", headers=as_(ADMIN)).json()["health"] == "unhealthy"
        crm = [i for i in c.get("/api/integrations", params={"limit": 200}, headers=as_(ADMIN)).json() if i["name"] == "CRM"][0]
        assert c.post(f"/api/integrations/{crm['id']}/check", headers=as_(ADMIN)).json()["health"] == "not_configured"


def test_stuck_executions_are_failed_as_unknown_and_flagged():
    with live_app(FakeSMTP()) as c:
        item = propose(c)
        approve(c, item)
        with c.app.state.engine.begin() as conn:
            conn.execute(text("UPDATE approvalrequest SET status = 'executing', executed_at = '2000-01-01 00:00:00.000000' WHERE id = :i"), {"i": item["id"]})
        row = c.get(f"/api/approvals/{item['id']}", headers=as_(ADMIN)).json()
        assert row["status"] == "failed" and row["result"]["outcome_unknown"] is True and row["result"]["retryable"] is False
        assert c.post(f"/api/approvals/{item['id']}/retry", headers=as_(ADMIN)).status_code == 409
        assert c.get("/api/audit", params={"event_type": "action.recovered"}, headers=as_(ADMIN)).json()


def test_operator_is_notified_when_a_request_needs_review():
    sent = []
    notifier = Notifier([lambda key, title, body: sent.append((key, title, body))], live=True, background=False)
    with live_app(FakeSMTP(), notifier=notifier) as c:
        item = propose(c)
        assert len(sent) == 1 and "message.send" in sent[0][1] and item["id"][:8] in sent[0][2]
        assert "Hi Alex" not in sent[0][2]  # notices never carry the content
        propose(c, action_type="record.create", target="x")  # policy-internal and human-originated: auto-approved, no notice
        assert len(sent) == 1


def test_a_failing_notifier_never_blocks_the_request():
    def boom(*_):
        raise RuntimeError("channel down")

    with live_app(FakeSMTP(), notifier=Notifier([boom], live=True, background=False)) as c:
        assert c.post("/api/actions/propose", json={"action_type": "message.send", "target": "a@corp.test", "reason": "r"}, headers=as_(OPERATOR)).status_code == 201


def test_staging_smtp_requires_an_allowlist_and_secure_transport():
    base = {"environment": "staging", "api_keys": KEYS, "smtp_host": "smtp.test", "smtp_sender": "bot@corp.test"}
    with pytest.raises(RuntimeError, match="SMTP_ALLOWED_DOMAINS"):
        create_app(make_settings(**base))
    with pytest.raises(RuntimeError, match="SMTP_SECURITY"):
        create_app(make_settings(**base, smtp_allowed_domains="corp.test", smtp_security="none"))
    with pytest.raises(RuntimeError, match="SMTP_SENDER"):
        create_app(make_settings(environment="staging", api_keys=KEYS, smtp_host="smtp.test", smtp_allowed_domains="corp.test"))
    with pytest.raises(RuntimeError, match="WEBHOOK_ROUTES"):
        create_app(make_settings(webhook_routes="[{]"))


def test_webhook_connector_routes_crm_updates_with_a_verifiable_signature():
    import hashlib
    import hmac
    import json

    from app.services.connector_setup import build_connectors

    posted = []

    def post(url, headers, body, timeout):
        posted.append((url, headers, body))
        return 200, '{"id": "evt-1"}'

    routes = json.dumps([{"prefix": "crm", "url": "https://hooks.example.com/crm", "secret": "k" * 20}])
    settings = make_settings(environment="staging", api_keys=KEYS, webhook_routes=routes)
    registry = build_registry(settings, build_connectors(settings, post=post))
    with TestClient(create_app(settings, connectors=registry)) as c:
        item = propose(c, action_type="crm.update", target="deal-7", payload={"stage": "won"})
        done = approve(c, item, execute=True).json()
        assert done["status"] == "executed" and done["result"]["external_id"] == "evt-1"
        url, headers, body = posted[0]
        expected = "sha256=" + hmac.new(b"k" * 20, headers["x-bma-timestamp"].encode() + b"." + body, hashlib.sha256).hexdigest()
        assert url == "https://hooks.example.com/crm" and headers["x-bma-signature"] == expected
