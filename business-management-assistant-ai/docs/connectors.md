# Connectors

A connector performs an approved action. Nothing reaches one without a person's approval, and sandbox mode never reaches any of them: every approved action is a dry run.

| Connector | Actions | Target | Configure |
|---|---|---|---|
| SMTP email | `message.send`, `invoice.send`, `contract.send`, `calendar.invite` | email address(es) | `SMTP_*` |
| Slack webhook | `message.send`, `content.publish` | `slack` or `slack:#channel` (the webhook decides the channel) | `SLACK_WEBHOOK_URL` |
| Signed webhook | any action matching a configured prefix | free text | `WEBHOOK_ROUTES` |

Resolution order for `message.send`: email address, then `slack...`, then a webhook route. No match: the action fails (`no connector is configured`); it never silently succeeds.

Not included on purpose: moving money (`payment.execute`) and signing (`contract.sign`). Route them to your own service with a webhook route if you accept that responsibility.

## Email
Payload: `subject` and `body` (required), `cc` (optional). Calendar invites: `title`, `start`, `end` (ISO 8601), optional `location`, `description`, `body`; an ICS part is attached. At most 25 recipients; header injection is rejected; `SMTP_ALLOWED_DOMAINS` restricts every recipient including cc and is **required in staging**. The Message-ID is derived from the approval id, so the mail log shows which approval sent it. Attachments are not supported.

A request raised by chat without subject and body fails with an instruction to amend it. Edit the payload in the approval card (or `POST /api/approvals/{id}/amend`), then approve.

## Signed webhooks
`WEBHOOK_ROUTES='[{"name":"crm","prefix":"crm","url":"https://hooks.example.com/crm","secret":"16+ characters"}]'`. The longest matching prefix wins (`campaign.launch` beats `campaign`). Each call is a JSON POST:

```
POST <url>
Idempotency-Key: <approval id>
X-BMA-Timestamp: <unix seconds>
X-BMA-Signature: sha256=<hex hmac of "<timestamp>.<raw body>" with your secret>
{"id": "<approval id>", "action_type": "crm.update", "target": "deal-7", "payload": {...}}
```
Receiver checklist: recompute the HMAC over the raw body, compare in constant time, reject timestamps older than a few minutes, de-duplicate on `Idempotency-Key`. A 2xx response is success (an `id` in the JSON body is stored as the external id); 429/503 mean "not processed, safe to retry"; other 4xx are rejections; other 5xx and timeouts are outcome-unknown.

## Retry rules
Each failure carries `retryable`. It is true only when the provider provably did nothing (connection refused, DNS failure, SMTP 4xx, HTTP 429/503). Then an admin may press Retry (`POST /api/approvals/{id}/retry`). Everything else (timeouts mid-send, dropped connections, 5xx, a process that died while executing) is recorded as outcome-unknown and is never retried automatically: check the destination, then propose the action again. Executions that report nothing for 10 minutes are failed this way.

## Health and notices
`POST /api/integrations/{id}/check` asks the connector (an SMTP NOOP; webhooks report "configured, not probed"). Nothing is sent. `NOTIFY_EMAIL` and `NOTIFY_WEBHOOK_URL` get a short notice (action, risk, target, request id, never the content) when an approval is waiting; sandbox only logs.

## Writing another connector
Implement `Connector` (`supports`, `execute`, `health`, `integrations`) in `services/connectors.py`, return `retryable=True` only when nothing happened, take secrets from settings, validate every outbound URL with `check_outbound_url`, and add it in `connector_setup.build_connectors`. Test it with fakes the way `tests/unit/test_connectors.py` does.
