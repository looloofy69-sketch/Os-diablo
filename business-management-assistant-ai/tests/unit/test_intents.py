import unittest
from datetime import UTC, datetime

from app.services import intents as I

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)


def p(text):
    return I.parse(text, NOW)


class RoutingTests(unittest.TestCase):
    def test_briefing_phrases(self):
        for text in ("brief me", "Status", "how is the business?", "what's going on", "what should I do next", "Please brief me"):
            self.assertEqual(p(text).name, I.BRIEFING, text)

    def test_create_variants(self):
        self.assertEqual(p("create goal: Reach the first ten customers").entities["title"], "Reach the first ten customers")
        self.assertEqual(p("add a task call Alex").name, I.CREATE_TASK)
        self.assertEqual(p("New project - Website launch").entities["name"], "Website launch")
        self.assertEqual(p("can you create a todo: renew domain").name, I.CREATE_TASK)

    def test_create_without_title_asks_for_it(self):
        intent = p("create task")
        self.assertEqual(intent.name, I.CLARIFY)
        self.assertEqual(intent.entities["for"], "task")

    def test_list_variants(self):
        self.assertEqual(p("list tasks").entities, {"entity": "tasks", "scope": None})
        self.assertEqual(p("show my overdue tasks").entities["scope"], "overdue")
        self.assertEqual(p("what are my goals").entities["entity"], "goals")
        self.assertEqual(p("pending approvals").entities, {"entity": "approvals", "scope": "pending"})

    def test_complete_task(self):
        self.assertEqual(p("mark call Alex as done").entities["query"], "call Alex")
        self.assertEqual(p("complete task: renew domain").entities["query"], "renew domain")

    def test_search(self):
        self.assertEqual(p("find pricing page").entities["query"], "pricing page")

    def test_empty_and_unknown(self):
        self.assertEqual(p("   ").name, I.OTHER)
        self.assertEqual(p("the weather is nice").name, I.OTHER)


class TaskEntityTests(unittest.TestCase):
    def test_priority_due_and_project_are_extracted_and_removed_from_title(self):
        intent = p("create task: call Alex by 2026-11-01 high priority in project Website launch")
        e = intent.entities
        self.assertEqual(e["title"], "call Alex")
        self.assertEqual(e["priority"], "high")
        self.assertEqual(e["project_name"], "Website launch")
        self.assertEqual(e["due_at"], datetime(2026, 11, 1, 23, 59, tzinfo=UTC))

    def test_relative_dates(self):
        self.assertEqual(p("add task: ship invoice due tomorrow").entities["due_at"].day, 9)
        self.assertEqual(p("add task: follow up in 2 weeks").entities["due_at"].day, 22)
        self.assertEqual(p("add task: report by today !urgent").entities["priority"], "urgent")

    def test_invalid_iso_date_is_kept_in_title(self):
        intent = p("create task: file by 2026-02-31")
        self.assertIsNone(intent.entities["due_at"])
        self.assertIn("2026-02-31", intent.entities["title"])

    def test_default_priority_is_medium(self):
        self.assertEqual(p("create task: write docs").entities["priority"], "medium")

    def test_goal_target_date(self):
        self.assertEqual(p("create goal: 10 customers by 2027-01-31").entities["target_date"].year, 2027)

    def test_contact_parsing(self):
        e = p("create contact: Alex Morgan alex@acme.io at Acme Labs").entities
        self.assertEqual((e["name"], e["email"], e["organisation"]), ("Alex Morgan", "alex@acme.io", "Acme Labs"))


class ProtectedActionTests(unittest.TestCase):
    def test_leading_verbs_are_protected(self):
        cases = {
            "send an email to a prospect": "message.send",
            "please publish the launch post": "content.publish",
            "wire $5,000 to the vendor": "payment.execute",
            "delete all contacts": "data.delete",
            "sign the NDA": "contract.sign",
            "launch the spring campaign": "campaign.launch",
        }
        for text, action in cases.items():
            intent = p(text)
            self.assertEqual((intent.name, intent.action_type), (I.PROTECTED, action), text)

    def test_polite_and_inline_phrasing_cannot_bypass_the_gate(self):
        for text in ("could you send the proposal to bob@acme.io", "I think we should publish the report today", "go ahead and pay the invoice"):
            self.assertEqual(p(text).name, I.PROTECTED, text)

    def test_questions_about_actions_are_not_actions(self):
        self.assertNotEqual(p("how do I send an invoice?").name, I.PROTECTED)
        self.assertNotEqual(p("what does it take to launch a campaign").name, I.PROTECTED)

    def test_structured_commands_win_over_inline_verbs(self):
        self.assertEqual(p("create task: send invoice to Alex").name, I.CREATE_TASK)

    def test_entities_include_target_and_amount(self):
        e = p("pay $2.5k to Acme Supplies for hosting").entities
        self.assertEqual(e["amount"], 2500.0)
        self.assertEqual(e["target"], "Acme Supplies")
        self.assertEqual(p("email alex@acme.io the deck").entities["target"], "alex@acme.io")


class GrowthTests(unittest.TestCase):
    def test_word_boundaries(self):
        self.assertEqual(p("audit SEO").name, I.SEO)
        self.assertEqual(p("plan an advertising campaign").name, I.ADVERTISING)
        self.assertNotEqual(p("the heads of the team are downloading leads").name, I.ADVERTISING)

    def test_search_ranking_is_seo_not_a_search_query(self):
        self.assertEqual(p("search ranking audit").name, I.SEO)


if __name__ == "__main__":
    unittest.main()
