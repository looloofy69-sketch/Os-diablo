from datetime import UTC, datetime, timedelta

from sqlalchemy import text


def test_health_ready_and_headers(client):
    health = client.get("/health")
    assert health.status_code == 200 and health.json()["status"] == "ok"
    assert client.get("/ready").json()["database"] == "up"
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["x-request-id"]
    assert client.get("/", headers={}).headers["content-security-policy"].startswith("default-src 'self'")
    assert client.get("/api/me").headers["cache-control"] == "no-store"


def test_request_id_is_echoed_when_valid_and_replaced_when_not(client):
    assert client.get("/health", headers={"x-request-id": "abc-12345678"}).headers["x-request-id"] == "abc-12345678"
    assert client.get("/health", headers={"x-request-id": "bad id!"}).headers["x-request-id"] != "bad id!"


def test_goal_project_task_flow_with_updates_and_filters(client):
    goal = client.post("/api/goals", json={"title": "First ten customers"})
    assert goal.status_code == 201
    goal_id = goal.json()["id"]
    project = client.post("/api/projects", json={"name": "Outreach", "goal_id": goal_id}).json()
    task = client.post("/api/tasks", json={"title": "Call Alex", "project_id": project["id"], "priority": "high"}).json()
    assert task["status"] == "planned" and task["completed_at"] is None

    done = client.patch(f"/api/tasks/{task['id']}", json={"status": "done"}).json()
    assert done["completed_at"] is not None
    reopened = client.patch(f"/api/tasks/{task['id']}", json={"status": "active"}).json()
    assert reopened["completed_at"] is None

    assert [t["id"] for t in client.get("/api/tasks", params={"status": "active"}).json()] == [task["id"]]
    assert client.get("/api/tasks", params={"status": "done"}).json() == []
    assert client.get("/api/tasks", params={"project_id": project["id"]}).json()[0]["id"] == task["id"]
    assert client.post(f"/api/tasks/{task['id']}/complete").json()["status"] == "done"
    assert client.get(f"/api/projects/{project['id']}").json()["goal_id"] == goal_id


def test_validation_and_references(client):
    assert client.post("/api/tasks", json={"title": "x", "project_id": "nope"}).status_code == 422
    assert client.post("/api/tasks", json={"title": "x", "surprise": 1}).status_code == 422
    assert client.post("/api/tasks", json={"title": "   "}).status_code == 422
    assert client.post("/api/tasks", json={"title": "x", "priority": "someday"}).status_code == 422
    task = client.post("/api/tasks", json={"title": "valid"}).json()
    assert client.patch(f"/api/tasks/{task['id']}", json={"title": None}).status_code == 422
    assert client.patch("/api/tasks/missing", json={"title": "x"}).status_code == 404
    assert client.get("/api/goals/missing").json()["error"]["code"] == "not_found"


def test_naive_due_date_is_utc_and_overdue_filter(client):
    past = (datetime.now(UTC) - timedelta(days=2)).replace(tzinfo=None).isoformat()
    task = client.post("/api/tasks", json={"title": "late", "due_at": past}).json()
    assert task["due_at"].endswith("Z") or "+00:00" in task["due_at"]
    client.post("/api/tasks", json={"title": "future", "due_at": (datetime.now(UTC) + timedelta(days=5)).isoformat()})
    assert [t["title"] for t in client.get("/api/tasks", params={"overdue": True}).json()] == ["late"]


def test_contacts_unique_email_and_search(client):
    created = client.post("/api/contacts", json={"name": "Alex Morgan", "email": "Alex@Acme.io", "organisation": "Acme"})
    assert created.status_code == 201 and created.json()["email"] == "alex@acme.io"
    assert client.post("/api/contacts", json={"name": "Other", "email": "alex@acme.io"}).status_code == 409
    assert client.post("/api/contacts", json={"name": "No email", "email": ""}).json()["email"] is None
    assert client.post("/api/contacts", json={"name": "Bad", "email": "not-an-email"}).status_code == 422
    assert client.get("/api/contacts", params={"q": "acme"}).json()[0]["name"] == "Alex Morgan"
    found = client.get("/api/search", params={"q": "alex"}).json()
    assert found["contacts"][0]["title"] == "Alex Morgan"


def test_search_treats_wildcards_literally(client):
    client.post("/api/tasks", json={"title": "100% done"})
    client.post("/api/tasks", json={"title": "plain"})
    assert [t["title"] for t in client.get("/api/search", params={"q": "%"}).json()["tasks"]] == ["100% done"]


def test_pagination_header(client):
    for i in range(5):
        client.post("/api/tasks", json={"title": f"t{i}"})
    page = client.get("/api/tasks", params={"limit": 2, "offset": 1})
    assert len(page.json()) == 2 and page.headers["x-total-count"] == "5"
    assert client.get("/api/tasks", params={"limit": 1000}).status_code == 422


def test_briefing_surfaces_overdue_and_ranks_next_actions(client):
    past = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    client.post("/api/tasks", json={"title": "Send invoice reminder", "due_at": past})
    client.post("/api/tasks", json={"title": "Someday", "priority": "low"})
    goal = client.post("/api/goals", json={"title": "Launch"}).json()
    project = client.post("/api/projects", json={"name": "Site", "goal_id": goal["id"]}).json()
    done = client.post("/api/tasks", json={"title": "shipped", "project_id": project["id"]}).json()
    client.post(f"/api/tasks/{done['id']}/complete")
    b = client.get("/api/briefing").json()
    assert b["overdue_tasks"] == 1 and b["open_tasks"] == 2
    assert any(a["kind"] == "task.overdue" for a in b["attention"])
    assert b["next_actions"][0]["title"] == "Send invoice reminder"
    assert [g for g in b["goal_progress"] if g["id"] == goal["id"]][0]["progress"] == 1.0
    assert isinstance(b["integrations"], list) and b["integrations"]


def test_integrations_seeded_and_checked(client):
    names = {i["name"] for i in client.get("/api/integrations", params={"limit": 200}).json()}
    assert {"Creative Production", "Workflow Automation", "CRM"} <= names
    assert "NeuraSynth Studios" not in names and "Synapse" not in names
    item = client.get("/api/integrations", params={"category": "advertising"}).json()[0]
    assert client.post(f"/api/integrations/{item['id']}/check").json()["health"] == "sandbox_ready"


def test_ai_endpoints(client):
    plan = client.post("/api/ai/plan", json={"request": "audit organic search traffic", "capability": "seo"}).json()
    assert plan["capability"] == "seo" and "seo.audit" in plan["tools"] and "Search Console" in plan["required_integrations"]
    assert client.post("/api/ai/plan", json={"request": "x", "capability": "telepathy"}).status_code == 422
    names = {a["name"] for a in client.get("/api/ai/capabilities").json()["agents"]}
    assert {"Growth Manager", "Quality and Risk Manager"} <= names
    models = client.get("/api/local-models").json()["models"]
    assert {"qwen3-0.6b", "smollm2-1.7b-instruct"} <= {m["key"] for m in models}
    rec = client.get("/api/local-models/recommend", params={"task": "short extraction"}).json()
    assert any(m["key"] == "qwen3-0.6b" for m in rec["recommendations"])
    assert client.get("/api/local-models/unknown/status").status_code == 404


def test_audit_chain_verifies_and_detects_tampering(client):
    client.post("/api/goals", json={"title": "one"})
    client.post("/api/tasks", json={"title": "two"})
    verified = client.get("/api/audit/verify").json()
    assert verified["ok"] is True and verified["checked"] >= 2
    events = client.get("/api/audit", params={"event_type": "goal.created"}).json()
    assert events[0]["entry_hash"] and events[0]["prev_hash"]

    with client.app.state.engine.begin() as conn:
        conn.execute(text("UPDATE auditevent SET actor = 'mallory' WHERE id = 1"))
    broken = client.get("/api/audit/verify").json()
    assert broken["ok"] is False and broken["first_bad_id"] == 1


def test_mutation_and_audit_entry_share_a_transaction(client):
    task = client.post("/api/tasks", json={"title": "audited"}).json()
    client.patch(f"/api/tasks/{task['id']}", json={"priority": "urgent"})
    changes = client.get("/api/audit", params={"target": task["id"], "event_type": "task.updated"}).json()
    assert changes[0]["details"]["changes"]["priority"] == ["medium", "urgent"]
