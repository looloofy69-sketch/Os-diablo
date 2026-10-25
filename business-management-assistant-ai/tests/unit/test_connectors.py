import hashlib
import hmac
import json
import smtplib
import threading
import unittest
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

from app.services.connector_email import EmailConnector, SmtpConfig, build_ics, parse_recipients
from app.services.connector_http import (
    HttpNetworkError,
    SignedWebhookConnector,
    SlackConnector,
    WebhookRoute,
    parse_webhook_routes,
    sign,
    urllib_post,
)
from app.services.connectors import ConnectorNotConfigured, ConnectorRegistry, SandboxConnector
from app.services.netutil import check_outbound_url, is_private_host


class FakeSMTP:
    def __init__(self, send_error=None, noop=(250, b"ok")):
        self.send_error, self.noop_result, self.sent, self.quit_called = send_error, noop, [], False

    def send_message(self, msg, to_addrs=None):
        if self.send_error:
            raise self.send_error
        self.sent.append((msg, to_addrs))

    def noop(self):
        if isinstance(self.noop_result, Exception):
            raise self.noop_result
        return self.noop_result

    def quit(self):
        self.quit_called = True


def email(fake=None, connect_error=None, **config):
    cfg = SmtpConfig(host="smtp.test", port=587, sender="bot@corp.test", **config)
    smtp = fake or FakeSMTP()

    def factory(_):
        if connect_error:
            raise connect_error
        return smtp

    return EmailConnector(cfg, factory), smtp


def send(connector, **kw):
    args = dict(action_type="message.send", target="alex@acme.io", payload={"subject": "Hello", "body": "Hi Alex"}, idempotency_key="abc-123")
    args.update(kw)
    return connector.execute(**args)


class EmailTests(unittest.TestCase):
    def test_sends_with_deterministic_message_id_and_closes_the_session(self):
        connector, smtp = email()
        result = send(connector)
        self.assertTrue(result.ok and not result.dry_run)
        message, recipients = smtp.sent[0]
        self.assertEqual((message["Subject"], message["To"], recipients), ("Hello", "alex@acme.io", ["alex@acme.io"]))
        self.assertEqual((message["Message-ID"], result.external_id), ("<abc-123@corp.test>", "<abc-123@corp.test>"))
        self.assertIn("Hi Alex", message.get_content())
        self.assertTrue(smtp.quit_called)

    def test_supports_only_email_targets_and_known_actions(self):
        connector, _ = email()
        self.assertTrue(connector.supports("message.send", "a@b.io, c@d.io"))
        self.assertTrue(connector.supports("calendar.invite", "a@b.io"))
        self.assertFalse(connector.supports("message.send", "slack:#general"))
        self.assertFalse(connector.supports("payment.execute", "a@b.io"))
        self.assertFalse(connector.supports("message.send", ""))
        self.assertFalse(connector.supports("message.send", "not an email"))

    def test_cc_dedupe_and_recipient_limits(self):
        connector, smtp = email(max_recipients=3)
        self.assertTrue(send(connector, target="a@x.io", payload={"subject": "s", "body": "b", "cc": ["A@x.io", "b@x.io"]}).ok)
        self.assertEqual(smtp.sent[0][1], ["a@x.io", "b@x.io"])
        many = ",".join(f"u{i}@x.io" for i in range(4))
        self.assertIn("exceeds", send(connector, target=many).detail)
        self.assertIn("invalid recipient", send(connector, payload={"subject": "s", "body": "b", "cc": "bad"}).detail)

    def test_allowed_domains_block_everyone_else_including_cc(self):
        connector, smtp = email(allowed_domains=("corp.test",))
        self.assertIn("outside the allowed domains", send(connector, target="alex@acme.io").detail)
        self.assertIn("outside", send(connector, target="a@corp.test", payload={"subject": "s", "body": "b", "cc": "x@evil.io"}).detail)
        self.assertEqual(smtp.sent, [])
        self.assertTrue(send(connector, target="a@corp.test").ok)

    def test_content_is_required_and_headers_cannot_be_injected(self):
        connector, smtp = email()
        self.assertIn("subject", send(connector, payload={"body": "b"}).detail)
        self.assertIn("amend", send(connector, payload={"subject": "s"}).detail)
        injected = send(connector, payload={"subject": "Hi\r\nBcc: victim@x.io", "body": "b"})
        self.assertFalse(injected.ok)
        self.assertEqual(smtp.sent, [])

    def test_failure_classification_drives_retry_safety(self):
        cases = [
            ("connect refused", dict(connect_error=ConnectionRefusedError()), True),
            ("dns", dict(connect_error=OSError("name resolution")), True),
            ("auth", dict(connect_error=smtplib.SMTPAuthenticationError(535, b"bad")), False),
            ("temporary reject", dict(fake=FakeSMTP(smtplib.SMTPDataError(451, b"try later"))), True),
            ("permanent reject", dict(fake=FakeSMTP(smtplib.SMTPDataError(550, b"no"))), False),
            ("all refused", dict(fake=FakeSMTP(smtplib.SMTPRecipientsRefused({"a@b.io": (550, b"x")}))), False),
            ("dropped mid-send", dict(fake=FakeSMTP(smtplib.SMTPServerDisconnected("gone"))), False),
            ("timeout mid-send", dict(fake=FakeSMTP(TimeoutError())), False),
        ]
        for name, kwargs, retryable in cases:
            connector, _ = email(**kwargs)
            result = send(connector)
            self.assertFalse(result.ok, name)
            self.assertEqual(result.retryable, retryable, name)
            self.assertEqual(result.outcome_unknown, name in {"dropped mid-send", "timeout mid-send"}, name)
        unknown, _ = email(fake=FakeSMTP(TimeoutError()))
        self.assertIn("outcome unknown", send(unknown).detail)

    def test_calendar_invite_builds_an_ics_alternative(self):
        connector, smtp = email()
        result = send(connector, action_type="calendar.invite", payload={"title": "Pilot kickoff", "start": "2026-11-02T09:00:00Z", "end": "2026-11-02T09:30:00Z", "location": "Room 1, HQ"})
        self.assertTrue(result.ok)
        message = smtp.sent[0][0]
        calendar = [p for p in message.walk() if p.get_content_type() == "text/calendar"][0]
        body = calendar.get_content()
        self.assertIn("DTSTART:20261102T090000Z", body)
        self.assertIn("SUMMARY:Pilot kickoff", body)
        self.assertIn("LOCATION:Room 1\\, HQ", body)
        self.assertIn("ATTENDEE;RSVP=TRUE:mailto:alex@acme.io", body)
        self.assertEqual(calendar.get_param("method"), "REQUEST")

    def test_calendar_invite_validation(self):
        connector, _ = email()
        base = {"title": "x", "start": "2026-11-02T09:00:00Z", "end": "2026-11-02T09:30:00Z"}
        for payload in ({**base, "end": "2026-11-02T08:00:00Z"}, {**base, "start": "soon"}, {"title": "x"}, {**base, "title": ""}):
            self.assertFalse(send(connector, action_type="calendar.invite", payload=payload).ok, payload)

    def test_ics_escaping_and_folding(self):
        text = build_ics("u1", "A;B,C\nD", datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC), "o@x.io", ["a@x.io"], description="x" * 200,
                         stamp=datetime(2026, 1, 1, tzinfo=UTC))
        self.assertIn("SUMMARY:A\\;B\\,C\\nD", text)
        self.assertTrue(all(len(line) <= 75 for line in text.split("\r\n")))
        self.assertTrue(text.endswith("END:VCALENDAR\r\n"))

    def test_health(self):
        self.assertTrue(email()[0].health().ok)
        self.assertFalse(email(fake=FakeSMTP(noop=(421, b"x")))[0].health().ok)
        self.assertFalse(email(fake=FakeSMTP(noop=smtplib.SMTPServerDisconnected()))[0].health().ok)
        self.assertIn("authentication", email(connect_error=smtplib.SMTPAuthenticationError(535, b"x"))[0].health().detail)

    def test_config_repr_hides_password(self):
        self.assertNotIn("s3cret", repr(SmtpConfig("h", 25, "a@b.io", "u", "s3cret")))

    def test_parse_recipients(self):
        self.assertEqual(parse_recipients("A@x.io; b@x.io  A@X.io", ["c@x.io", None], 5), ["a@x.io", "b@x.io", "c@x.io", "5"])


class Poster:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, body))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class SlackTests(unittest.TestCase):
    def make(self, *responses):
        poster = Poster(*responses)
        return SlackConnector("https://hooks.slack.com/services/T/B/X", poster), poster

    def test_routing_and_delivery(self):
        slack, poster = self.make((200, "ok"))
        self.assertTrue(slack.supports("message.send", "slack:#general"))
        self.assertFalse(slack.supports("message.send", "alex@acme.io"))
        self.assertFalse(slack.supports("payment.execute", "slack:#x"))
        result = slack.execute(action_type="message.send", target="slack:#general", payload={"body": "Launch is live"}, idempotency_key="k")
        self.assertTrue(result.ok)
        self.assertEqual(json.loads(poster.calls[0][2]), {"text": "Launch is live"})

    def test_requires_text_and_hides_url(self):
        slack, poster = self.make()
        self.assertFalse(slack.execute(action_type="message.send", target="slack", payload={}, idempotency_key="k").ok)
        self.assertEqual(poster.calls, [])
        self.assertNotIn("hooks.slack.com", repr(slack))

    def test_status_handling_never_retries_ambiguous_http_responses(self):
        for response, ok, retryable in [((404, "no_service"), False, False), ((429, ""), False, False), ((500, ""), False, False), (HttpNetworkError("refused", True), False, True), (HttpNetworkError("timeout", False), False, False)]:
            slack, _ = self.make(response)
            result = slack.execute(action_type="message.send", target="slack", payload={"text": "x"}, idempotency_key="k")
            self.assertEqual((result.ok, result.retryable), (ok, retryable), response)
            expected_unknown = isinstance(response, tuple) or (isinstance(response, HttpNetworkError) and not response.retryable)
            self.assertEqual(result.outcome_unknown, expected_unknown, response)
            if isinstance(response, tuple) and response[0] in {404, 429, 500}:
                self.assertIn("outcome unknown", result.detail)

    def test_http_post_does_not_forward_signed_payload_to_redirect_target(self):
        hits = {"redirect": 0, "target": 0}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API
                if self.path == "/redirect":
                    hits["redirect"] += 1
                    self.send_response(307)
                    self.send_header("Location", "/target")
                    self.end_headers()
                    self.wfile.write(b"redirect")
                else:
                    hits["target"] += 1
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"accepted")

            def log_message(self, *_args):
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, body = urllib_post(
                f"http://127.0.0.1:{server.server_port}/redirect",
                {"x-bma-signature": "test-signature"}, b"sensitive payload", 2.0,
            )
            self.assertEqual(status, 307)
            self.assertEqual(body, "redirect")
            self.assertEqual(hits, {"redirect": 1, "target": 0})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_rejects_insecure_remote_urls(self):
        with self.assertRaises(ValueError):
            SlackConnector("http://hooks.example.com/x")
        SlackConnector("http://127.0.0.1:9/x")

    def test_rejects_invalid_timeouts_and_ambiguous_url_components(self):
        for timeout in (0, -1, float("nan"), float("inf"), True):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                SlackConnector("https://hooks.slack.com/services/T/B/X", timeout=timeout)
        for url in (
            "https://hooks.example.com/x?token=secret",
            "https://hooks.example.com/x#fragment",
            "https://hooks.example.com:99999/x",
            "https://hooks.example.com:0/x",
            "https://hooks.example.com:/x",
            "https://hooks.example.com/x?",
            "https://hooks.example.com/x#",
            "https://hooks.example.com/with space",
            " https://hooks.example.com/x",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                SlackConnector(url)


class WebhookTests(unittest.TestCase):
    routes = [WebhookRoute("crm", "crm", "https://n8n.example/hook/crm", "s" * 20), WebhookRoute("launch", "campaign.launch", "https://n8n.example/hook/launch", "t" * 20),
              WebhookRoute("campaigns", "campaign", "https://n8n.example/hook/campaigns", "u" * 20)]

    def make(self, *responses):
        poster = Poster(*responses)
        return SignedWebhookConnector(self.routes, poster, clock=lambda: 1_700_000_000), poster

    def test_longest_prefix_wins_and_unrouted_actions_are_unsupported(self):
        hook, _ = self.make()
        self.assertTrue(hook.supports("crm.update", "x") and hook.supports("crm", "x"))
        self.assertFalse(hook.supports("crmx.update", "x") or hook.supports("payment.execute", "x"))
        self.assertEqual(hook._route("campaign.launch").name, "launch")
        self.assertEqual(hook._route("campaign.budget_change").name, "campaigns")

    def test_signature_is_verifiable_by_the_receiver(self):
        hook, poster = self.make((200, '{"id": "evt_1"}'))
        result = hook.execute(action_type="crm.update", target="deal-7", payload={"stage": "won"}, idempotency_key="idem-1")
        self.assertTrue(result.ok)
        self.assertEqual(result.external_id, "evt_1")
        url, headers, body = poster.calls[0]
        self.assertEqual(url, "https://n8n.example/hook/crm")
        expected = "sha256=" + hmac.new(b"s" * 20, b"1700000000." + body, hashlib.sha256).hexdigest()
        self.assertEqual(headers["x-bma-signature"], expected)
        self.assertEqual((headers["idempotency-key"], headers["x-bma-timestamp"]), ("idem-1", "1700000000"))
        self.assertEqual(json.loads(body), {"action_type": "crm.update", "id": "idem-1", "payload": {"stage": "won"}, "target": "deal-7"})
        self.assertNotEqual(sign("a" * 20, "1", b"x"), sign("b" * 20, "1", b"x"))
        self.assertNotEqual(sign("a" * 20, "1", b"x"), sign("a" * 20, "2", b"x"))

    def test_outcomes(self):
        for response, ok, retryable in [((503, ""), False, False), ((400, "bad"), False, False), ((502, ""), False, False), (HttpNetworkError("x", True), False, True)]:
            hook, _ = self.make(response)
            result = hook.execute(action_type="crm.update", target="t", payload={}, idempotency_key="k")
            self.assertEqual((result.ok, result.retryable), (ok, retryable), response)
            expected_unknown = isinstance(response, tuple) or (isinstance(response, HttpNetworkError) and not response.retryable)
            self.assertEqual(result.outcome_unknown, expected_unknown, response)
            if isinstance(response, tuple) and response[0] in {503, 502, 400}:
                self.assertIn("outcome unknown", result.detail)

    def test_parse_routes(self):
        raw = json.dumps([{"prefix": "CRM", "url": "https://x.example/h", "secret": "z" * 16, "name": "crm"}])
        self.assertEqual(parse_webhook_routes(raw)[0].prefix, "crm")
        self.assertEqual(parse_webhook_routes(" "), [])
        for bad in ("{", "{}", "[1]", json.dumps([{"prefix": "a", "url": "https://x.example", "secret": "short"}]),
                    json.dumps([{"prefix": "a", "url": "http://remote.example", "secret": "z" * 16}]), json.dumps([{"prefix": "a", "url": "https://x.example", "secret": "z" * 16, "extra": 1}]),
                    json.dumps([{"prefix": "a", "url": "https://user:pw@x.example", "secret": "z" * 16}])):
            with self.assertRaises(ValueError, msg=bad):
                parse_webhook_routes(bad)
        self.assertEqual(len(parse_webhook_routes(json.dumps([{"prefix": "a", "url": "http://127.0.0.1:5678/h", "secret": "z" * 16}]))), 1)

    def test_route_parser_rejects_wrong_types_duplicate_prefixes_and_unsafe_urls(self):
        bad = [
            [{"prefix": 123, "url": "https://x.example/h", "secret": "z" * 16}],
            [{"prefix": "a", "url": 123, "secret": "z" * 16}],
            [{"prefix": "a", "url": "https://x.example/h", "secret": 1234567890123456}],
            [{"prefix": "a", "url": "https://x.example/h?token=x", "secret": "z" * 16}],
            [{"prefix": "a", "url": "https://x.example:99999/h", "secret": "z" * 16}],
            [
                {"prefix": "CRM", "url": "https://x.example/one", "secret": "z" * 16},
                {"prefix": "crm", "url": "https://x.example/two", "secret": "y" * 16},
            ],
        ]
        for value in bad:
            raw = json.dumps(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_webhook_routes(raw)

    def test_signed_webhook_rejects_invalid_timeout(self):
        for timeout in (0, -1, float("nan"), float("inf"), True):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                SignedWebhookConnector(self.routes, timeout=timeout)

    def test_route_repr_hides_secret(self):
        self.assertNotIn("s" * 20, repr(self.routes[0]))


class RegistryAndNetTests(unittest.TestCase):
    def test_sandbox_never_resolves_a_live_connector(self):
        registry = ConnectorRegistry(sandbox=True)
        registry.register(email()[0])
        self.assertIsInstance(registry.resolve("message.send", "a@b.io"), SandboxConnector)

    def test_live_resolution_order_and_fail_closed(self):
        registry = ConnectorRegistry(sandbox=False)
        with self.assertRaises(ConnectorNotConfigured):
            registry.resolve("message.send", "a@b.io")
        mail, _ = email()
        slack = SlackConnector("https://hooks.slack.com/x")
        hook = SignedWebhookConnector([WebhookRoute("m", "message", "https://x.example/h", "z" * 16)])
        for connector in (mail, slack, hook):
            registry.register(connector)
        self.assertIs(registry.resolve("message.send", "a@b.io"), mail)
        self.assertIs(registry.resolve("message.send", "slack:#ops"), slack)
        self.assertIs(registry.resolve("message.send", "sms:+213555"), hook)
        with self.assertRaises(ConnectorNotConfigured):
            registry.resolve("payment.execute", "vendor")

    def test_outbound_url_policy(self):
        self.assertTrue(is_private_host("http://10.1.2.3/x") and is_private_host("http://localhost:1") and not is_private_host("http://example.com"))
        for bad in ("ftp://x", "http://example.com", "https://u:p@example.com", "https://"):
            with self.assertRaises(ValueError, msg=bad):
                check_outbound_url(bad)
        self.assertEqual(check_outbound_url("http://example.com", allow_insecure_remote=True), "http://example.com")


if __name__ == "__main__":
    unittest.main()
