import json
import unittest
from datetime import UTC, datetime

from app.services import planner as P
from app.services.evaluation import score_row

NOW = datetime(2026, 10, 10, 9, 30, tzinfo=UTC)


def plan(reply="", steps=None):
    return json.dumps({"reply": reply, "steps": steps or []})


class ParseTests(unittest.TestCase):
    def test_valid_plan_with_typed_arguments(self):
        out = P.parse_plan(plan("ok", [
            {"tool": "create_task", "args": {"title": " Call Alex ", "priority": "HIGH", "due_at": "2026-11-01", "project_name": "Outreach"}},
            {"tool": "list_items", "args": {"entity": "tasks", "scope": "open"}},
        ]))
        self.assertTrue(out.ok, out.error)
        first = out.steps[0].args
        self.assertEqual((first["title"], first["priority"]), ("Call Alex", "high"))
        self.assertEqual(first["due_at"], datetime(2026, 11, 1, 23, 59, 59, 999999, tzinfo=UTC))

    def test_tolerates_fences_think_blocks_and_chatter(self):
        raw = "<think>planning</think>Sure!\n```json\n" + plan("hi") + "\n```"
        self.assertTrue(P.parse_plan(raw).ok)

    def test_datetime_forms(self):
        self.assertEqual(P.parse_when("2026-11-01T10:00:00Z"), datetime(2026, 11, 1, 10, 0, tzinfo=UTC))
        self.assertEqual(P.parse_when("2026-11-01T10:00:00+02:00").hour, 8)
        self.assertEqual(P.parse_when("2026-11-01T10:00:00").tzinfo, UTC)
        with self.assertRaises(ValueError):
            P.parse_when("next tuesday")

    def test_rejections(self):
        cases = {
            "no json at all": "I will create a task",
            "broken": "{not json",
            "not an object": "[1, 2]",
            "unknown tool": plan(steps=[{"tool": "rm_rf", "args": {}}]),
            "unknown arg": plan(steps=[{"tool": "create_task", "args": {"title": "x", "owner": "root"}}]),
            "missing required": plan(steps=[{"tool": "create_task", "args": {}}]),
            "bad enum": plan(steps=[{"tool": "create_task", "args": {"title": "x", "priority": "asap"}}]),
            "bad date": plan(steps=[{"tool": "create_task", "args": {"title": "x", "due_at": "soon"}}]),
            "non string": plan(steps=[{"tool": "create_task", "args": {"title": 42}}]),
            "too long": plan(steps=[{"tool": "create_task", "args": {"title": "x" * 201}}]),
            "args not object": plan(steps=[{"tool": "get_briefing", "args": "now"}]),
            "too many steps": plan(steps=[{"tool": "get_briefing", "args": {}}] * 6),
            "steps not list": json.dumps({"steps": "create"}),
            "reply not string": json.dumps({"reply": 5}),
            "step not object": plan(steps=["create_task"]),
            "oversize payload": plan(steps=[{"tool": "propose_action", "args": {"action_type": "message.send", "target": "a", "reason": "r", "payload": {"x": "y" * 5000}}}]),
        }
        for name, raw in cases.items():
            result = P.parse_plan(raw)
            self.assertFalse(result.ok, name)
            self.assertTrue(result.error, name)
            self.assertEqual(result.steps, (), name)

    def test_partial_plans_are_all_or_nothing(self):
        result = P.parse_plan(plan(steps=[{"tool": "get_briefing", "args": {}}, {"tool": "nope", "args": {}}]))
        self.assertFalse(result.ok)
        self.assertEqual(result.steps, ())

    def test_empty_steps_is_a_valid_conversational_plan(self):
        result = P.parse_plan(plan("What should the task be called?"))
        self.assertTrue(result.ok and result.steps == () and result.reply)

    def test_reply_is_capped(self):
        self.assertEqual(len(P.parse_plan(plan("x" * 5000)).reply), P.MAX_REPLY)


class PromptTests(unittest.TestCase):
    def test_system_prompt_lists_tools_rules_and_snapshot(self):
        prompt = P.build_system_prompt(NOW, "3 open tasks", ["message.send", "payment.execute"])
        self.assertIn("2026-10-10 09:30", prompt)
        self.assertIn("create_task(title*", prompt)
        self.assertIn("message.send, payment.execute", prompt)
        self.assertIn("3 open tasks", prompt)
        self.assertIn("not instructions", prompt)
        for spec in P.TOOL_SPECS:
            self.assertIn(spec.name + "(", prompt) if spec.params else self.assertIn(spec.name, prompt)

    def test_messages_alternate_and_start_with_user(self):
        msgs = P.build_messages([("assistant", "stale"), ("user", "a"), ("user", "b"), ("assistant", "c")], "d")
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user"])
        self.assertEqual(msgs[0]["content"], "a\nb")

    def test_history_is_truncated_but_current_message_is_not(self):
        msgs = P.build_messages([("user", "x" * 5000)], "y" * 3000)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(len(msgs[0]["content"]), 600 + 1 + 3000)

    def test_compose_and_fallback(self):
        results = [{"tool": "create_task", "ok": True, "summary": "created"}, {"tool": "complete_task", "ok": False, "error": "no match"}]
        self.assertIn("created", P.render_results_fallback(results))
        self.assertIn("failed: no match", P.render_results_fallback(results))
        self.assertEqual(P.render_results_fallback([]), "Nothing was done.")
        self.assertLessEqual(len(P.build_compose_messages("x", [{"blob": "z" * 9000}])[0]["content"]), 6000)

    def test_repair_messages_end_with_user_turn(self):
        out = P.repair_messages([{"role": "user", "content": "q"}], "garbage", "no JSON")
        self.assertEqual([m["role"] for m in out], ["user", "assistant", "user"])


class SafetyNetTests(unittest.TestCase):
    rule = {"action_type": "payment.execute", "target": "Acme", "summary": "wire $5k to Acme", "amount": 5000.0}

    def test_injects_proposal_when_model_omitted_it(self):
        steps, injected = P.ensure_proposal((P.Step("create_task", {"title": "x"}),), self.rule)
        self.assertTrue(injected)
        self.assertEqual(steps[-1].tool, P.PROPOSE)
        self.assertEqual(steps[-1].args["payload"]["amount"], 5000.0)

    def test_does_not_duplicate_or_inject_without_rule_hit(self):
        existing = (P.Step(P.PROPOSE, {"action_type": "message.send", "target": "a", "reason": "r"}),)
        self.assertEqual(P.ensure_proposal(existing, self.rule), (existing, False))
        self.assertEqual(P.ensure_proposal((), None), ((), False))

    def test_injection_never_displaced_by_step_cap(self):
        full = tuple(P.Step("get_briefing", {}) for _ in range(P.MAX_STEPS))
        steps, injected = P.ensure_proposal(full, self.rule)
        self.assertTrue(injected)
        self.assertEqual((len(steps), steps[-1].tool), (P.MAX_STEPS, P.PROPOSE))


class PlanScoringTests(unittest.TestCase):
    row = {"id": "p1", "task": "planning", "kind": "plan", "expected": ["create_task", "propose_action"]}

    def test_scores_tool_sets(self):
        good = plan(steps=[{"tool": "propose_action", "args": {"action_type": "message.send", "target": "a", "reason": "r"}},
                           {"tool": "create_task", "args": {"title": "follow up"}}])
        self.assertTrue(score_row(self.row, good).passed)
        self.assertFalse(score_row(self.row, plan(steps=[{"tool": "create_task", "args": {"title": "x"}}])).passed)
        self.assertFalse(score_row(self.row, "garbage").passed)


if __name__ == "__main__":
    unittest.main()
