from sqlalchemy import text


def propose(client, **overrides):
    body = {"action_type": "message.send", "target": "prospect@example.com", "payload": {"subject": "Draft"}, "reason": "Sales follow-up"}
    body.update(overrides)
    return client.post("/api/actions/propose", json=body)


def test_protected_action_lifecycle(client):
    created = propose(client)
    assert created.status_code == 201
    item = created.json()
    assert item["status"] == "pending" and item["risk"] == "high" and item["policy_reasons"]

    decided = client.post(f"/api/approvals/{item['id']}/decision", json={"decision": "approved", "note": "ok"})
    assert decided.status_code == 200 and decided.json()["status"] == "approved"
    assert decided.json()["reviewed_by"] == "founder"

    executed = client.post(f"/api/approvals/{item['id']}/execute").json()
    assert executed["status"] == "executed" and executed["result"]["dry_run"] is True
    again = client.post(f"/api/approvals/{item['id']}/execute")
    assert again.status_code == 200 and again.json()["executed_at"] == executed["executed_at"]
    assert client.post(f"/api/approvals/{item['id']}/decision", json={"decision": "rejected"}).status_code == 409

    types = [e["event_type"] for e in client.get("/api/audit", params={"target": item["id"]}).json()]
    assert {"action.proposed", "action.approved", "action.executing", "action.executed"} <= set(types)


def test_status_cannot_be_forced_through_decision(client):
    item = propose(client).json()
    for forbidden in ("executed", "pending", "expired"):
        assert client.post(f"/api/approvals/{item['id']}/decision", json={"decision": forbidden}).status_code == 422
    assert client.get(f"/api/approvals/{item['id']}").json()["status"] == "pending"


def test_unapproved_or_rejected_cannot_execute(client):
    item = propose(client).json()
    assert client.post(f"/api/approvals/{item['id']}/execute").status_code == 409
    client.post(f"/api/approvals/{item['id']}/decision", json={"decision": "rejected"})
    assert client.post(f"/api/approvals/{item['id']}/execute").status_code == 409


def test_approve_and_execute_in_one_call(client):
    item = propose(client).json()
    result = client.post(f"/api/approvals/{item['id']}/decision", json={"decision": "approved", "execute": True}).json()
    assert result["status"] == "executed"


def test_idempotency_key_replays_original(client):
    first = propose(client, idempotency_key="send-2026-10-follow-up")
    second = propose(client, idempotency_key="send-2026-10-follow-up")
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len(client.get("/api/approvals").json()) == 1


def test_policy_tiers_and_escalation(client):
    internal = propose(client, action_type="record.create", target="task").json()
    assert internal["status"] == "approved" and internal["reviewed_by"] == "policy"
    unknown = propose(client, action_type="teleport.cargo").json()
    assert unknown["status"] == "pending" and unknown["risk"] == "high"
    big = propose(client, action_type="invoice.send", payload={"amount": 25000}).json()
    assert big["risk"] == "critical"
    alias = propose(client, action_type="send_external_message").json()
    assert alias["action_type"] == "message.send"
    assert any(a["action_type"] == "payment.execute" for a in client.get("/api/policy/actions").json())


def test_payload_size_limit(client):
    assert propose(client, payload={"blob": "x" * 20000}).status_code == 422


def test_pending_requests_expire(client):
    item = propose(client).json()
    with client.app.state.engine.begin() as conn:
        conn.execute(text("UPDATE approvalrequest SET expires_at = '2000-01-01 00:00:00.000000' WHERE id = :i"), {"i": item["id"]})
    assert client.post(f"/api/approvals/{item['id']}/decision", json={"decision": "approved"}).status_code == 409
    assert client.get(f"/api/approvals/{item['id']}").json()["status"] == "expired"
    assert client.get("/api/briefing").json()["pending_approvals"] == 0


def test_approved_request_expires_before_execution(client):
    item = propose(client).json()
    client.post(f"/api/approvals/{item['id']}/decision", json={"decision": "approved"})
    with client.app.state.engine.begin() as conn:
        conn.execute(text("UPDATE approvalrequest SET expires_at = '2000-01-01 00:00:00.000000' WHERE id = :i"), {"i": item["id"]})
    assert client.post(f"/api/approvals/{item['id']}/execute").status_code == 409
    assert client.get(f"/api/approvals/{item['id']}").json()["status"] == "expired"


def test_legacy_reviewer_field_is_ignored(client):
    item = propose(client).json()
    out = client.post(f"/api/approvals/{item['id']}/decision", json={"reviewer": "someone-else", "decision": "approved"}).json()
    assert out["reviewed_by"] == "founder"
