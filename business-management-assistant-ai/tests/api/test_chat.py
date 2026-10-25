def say(client, message, conversation_id=None):
    return client.post("/api/chat", json={"message": message, "conversation_id": conversation_id})


def test_chat_creates_records_and_briefs(client):
    created = say(client, "create goal: Reach first ten customers").json()
    assert created["intent"] == "create_goal" and "Reach first ten customers" in created["message"]
    assert created["handled_by"] == "Planner" and created["conversation_id"]
    brief = say(client, "brief me", created["conversation_id"]).json()
    assert brief["intent"] == "business_briefing" and "1 goals" in brief["message"]
    assert len(client.get(f"/api/conversations/{created['conversation_id']}/messages").json()) == 4


def test_chat_task_entities_and_project_link(client):
    say(client, "create project: Website launch")
    r = say(client, "create task: ship pricing page by 2026-11-01 urgent priority in project Website launch").json()
    assert "Website launch" in r["message"]
    task = client.get("/api/tasks").json()[0]
    assert task["title"] == "ship pricing page" and task["priority"] == "urgent" and task["due_at"].startswith("2026-11-01")
    assert task["project_id"]


def test_chat_complete_task_and_ambiguity(client):
    say(client, "create task: renew domain")
    say(client, "create task: renew insurance")
    ambiguous = say(client, "complete task: renew").json()
    assert "More than one" in ambiguous["message"]
    done = say(client, "mark renew domain as done").json()
    assert done["intent"] == "complete_task" and "Marked done" in done["message"]
    assert [t["status"] for t in client.get("/api/tasks", params={"status": "done"}).json()] == ["done"]
    assert "No open task" in say(client, "complete task: nothing like this").json()["message"]


def test_chat_lists_and_clarifies(client):
    assert "No tasks" in say(client, "list tasks").json()["message"]
    say(client, "create task: one")
    assert "one" in say(client, "show my open tasks").json()["message"]
    clarify = say(client, "create task").json()
    assert clarify["intent"] == "clarify"


def test_chat_external_actions_create_real_approvals(client):
    r = say(client, "please wire $5,000 to Acme Supplies").json()
    assert r["intent"] == "protected_action" and r["approval_required"] is True and r["approval_id"]
    approval = client.get(f"/api/approvals/{r['approval_id']}").json()
    assert approval["status"] == "pending" and approval["origin"] == "assistant"
    assert approval["action_type"] == "payment.execute" and approval["risk"] == "critical"
    assert approval["payload"]["amount"] == 5000
    assert "Nothing was sent" in r["message"]


def test_chat_cannot_approve_or_execute(client):
    r = say(client, "send an email to bob@acme.io").json()
    reply = say(client, f"approve {r['approval_id']}").json()
    assert reply["approval_id"] is None
    assert client.get(f"/api/approvals/{r['approval_id']}").json()["status"] == "pending"


def test_chat_word_boundaries_and_questions(client):
    assert say(client, "the heads of the team are downloading leads").json()["intent"] == "general_business_request"
    assert say(client, "how do I send an invoice?").json()["intent"] != "protected_action"
    assert say(client, "audit SEO").json()["intent"] == "seo_request"
    assert "Search Console" in say(client, "audit SEO").json()["message"]


def test_chat_unknown_conversation_and_legacy_actor(client):
    assert say(client, "brief me", "does-not-exist").status_code == 404
    r = client.post("/api/chat", json={"message": "create goal: x", "actor": "mallory"})
    assert r.status_code == 200
    events = client.get("/api/audit", params={"event_type": "goal.created"}).json()
    assert events[0]["actor"] == "founder"


def test_chat_duplicate_contact_is_reported_not_raised(client):
    say(client, "create contact: Alex Morgan alex@acme.io")
    again = say(client, "create contact: Alex Two alex@acme.io").json()
    assert again["intent"] == "error" and "already exists" in again["message"]


def test_chat_input_limits(client):
    assert say(client, "x" * 5000).status_code == 422
    assert client.post("/api/chat", json={"message": "   "}).status_code == 422
