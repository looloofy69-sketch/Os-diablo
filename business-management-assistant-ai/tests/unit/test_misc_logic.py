import json
import unittest
from datetime import UTC, datetime, timedelta

from app.services.evaluation import parse_json_object, score_row, summarise, validate_dataset
from app.services.llm import normalise_label
from app.services.priorities import TaskView, goal_at_risk, goal_progress, rank_tasks, score_task

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def task(id, priority="medium", due=None, status="planned"):
    return TaskView(id=id, title=id, status=status, priority=priority, due_at=due)


class RankingTests(unittest.TestCase):
    def test_overdue_beats_higher_priority_without_due_date(self):
        ranked = rank_tasks([task("urgent-no-date", "urgent"), task("late", "medium", NOW - timedelta(days=3))], NOW)
        self.assertEqual(ranked[0][0].id, "late")
        self.assertIn("overdue by 3d", ranked[0][1])

    def test_done_and_blocked_are_excluded(self):
        ranked = rank_tasks([task("a", status="done"), task("b", status="blocked"), task("c")], NOW)
        self.assertEqual([t.id for t, _ in ranked], ["c"])

    def test_naive_datetimes_are_treated_as_utc(self):
        ranked = rank_tasks([task("a", due=datetime(2026, 10, 7, 12, 0))], NOW)
        self.assertIn("overdue", ranked[0][1])

    def test_ties_are_deterministic_and_limit_applies(self):
        ranked = rank_tasks([task("b"), task("a"), task("c")], NOW, limit=2)
        self.assertEqual([t.id for t, _ in ranked], ["a", "b"])

    def test_top_k_ranking_preserves_order_and_handles_nonpositive_limit(self):
        tasks = [task(f"task-{i:04d}", priority=("urgent" if i % 9 == 0 else "medium")) for i in range(2000)]
        got = rank_tasks(tasks, NOW, limit=5)
        scored = []
        for item in tasks:
            result = score_task(item, NOW)
            if result is not None:
                scored.append((result[0], item, result[1]))
        far = datetime.max.replace(tzinfo=UTC)
        scored.sort(key=lambda row: (-row[0], row[1].due_at or far, row[1].title.lower()))
        expected_ids = [item.id for _, item, _ in scored[:5]]
        self.assertEqual([item.id for item, _ in got], expected_ids)
        self.assertEqual(rank_tasks(tasks, NOW, limit=0), [])
        self.assertEqual(rank_tasks(tasks, NOW, limit=-1), [])

    def test_goal_progress_and_risk(self):
        self.assertIsNone(goal_progress(0, 0))
        self.assertEqual(goal_progress(1, 4), 0.25)
        soon = NOW + timedelta(days=5)
        self.assertTrue(goal_at_risk(soon, 0.2, "active", NOW))
        self.assertFalse(goal_at_risk(soon, 0.8, "active", NOW))
        self.assertFalse(goal_at_risk(NOW + timedelta(days=90), 0.0, "active", NOW))
        self.assertTrue(goal_at_risk(NOW - timedelta(days=1), 0.9, "active", NOW))
        self.assertFalse(goal_at_risk(NOW - timedelta(days=1), 1.0, "done", NOW))


class EvaluationTests(unittest.TestCase):
    def test_label_and_json_scoring(self):
        self.assertTrue(score_row({"id": "1", "task": "routing", "kind": "label", "expected": "seo"}, "<think>x</think>SEO").passed)
        self.assertFalse(score_row({"id": "2", "task": "routing", "kind": "label", "expected": "seo"}, "other").passed)
        row = {"id": "3", "task": "short_extraction", "kind": "json", "expected": {"company": "Acme Labs"}}
        self.assertTrue(score_row(row, 'Here: {"company": "Acme Labs", "renewal_date": "2027-03-31"}').passed)
        self.assertFalse(score_row(row, "no json here").passed)
        self.assertFalse(score_row(row, json.dumps({"company": "Other"})).passed)
        self.assertIsNone(score_row({"id": "4", "task": "summarization"}, "text").passed)

    def test_planner_evaluation_counts_duplicate_tool_calls(self):
        row = {"id": "plan-count", "task": "unique action", "kind": "plan", "expected": ["propose_action"]}
        raw = json.dumps({"reply": "", "steps": [
            {"tool": "propose_action", "args": {"action_type": "message.send", "target": "a", "reason": "r"}},
            {"tool": "propose_action", "args": {"action_type": "message.send", "target": "a", "reason": "r"}},
        ]})
        result = score_row(row, raw)
        self.assertFalse(result.passed)
        self.assertIn("'propose_action', 'propose_action'", result.detail)

    def test_summary_gate_requires_minimum_graded_evidence(self):
        one = [score_row({"id": "x", "task": "routing", "kind": "label", "expected": "a"}, "a")]
        self.assertFalse(summarise(one)["meets_gate"])
        self.assertTrue(summarise(one, min_graded=1)["meets_gate"])
        with self.assertRaises(ValueError):
            summarise(one, min_accuracy=1.5)
        with self.assertRaises(ValueError):
            summarise(one, min_graded=0)

    def test_evaluation_dataset_validation_rejects_duplicates_and_wrong_types(self):
        valid = {"id": "a", "task": "routing", "prompt": "route this", "kind": "label", "expected": "briefing"}
        self.assertEqual(validate_dataset([valid]), [valid])
        with self.assertRaises(ValueError):
            validate_dataset([valid, valid])
        with self.assertRaises(ValueError):
            validate_dataset([{**valid, "expected": []}])
        with self.assertRaises(ValueError):
            validate_dataset([{**valid, "kind": "unknown"}])
        with self.assertRaises(ValueError):
            validate_dataset([])

    def test_summary_gate(self):
        scores = [score_row({"id": str(i), "task": "t", "kind": "label", "expected": "a"}, "a" if i < 9 else "b") for i in range(10)]
        scores.append(score_row({"id": "free", "task": "summarization"}, "x"))
        summary = summarise(scores, min_accuracy=0.9)
        self.assertEqual((summary["graded"], summary["passed"]), (10, 9))
        self.assertTrue(summary["meets_gate"])
        self.assertEqual(summary["needs_review"], ["free"])
        self.assertFalse(summarise(scores, min_accuracy=0.95)["meets_gate"])
        self.assertFalse(summarise([])["meets_gate"])

    def test_parse_json_object_rejects_non_objects(self):
        self.assertIsNone(parse_json_object("[1,2]"))
        self.assertIsNone(parse_json_object("{broken"))


if __name__ == "__main__":
    unittest.main()


class DatasetTests(unittest.TestCase):
    def test_seed_dataset_is_well_formed(self):
        import pathlib

        rows = [json.loads(line) for line in pathlib.Path("data/evaluation/small_model_seed.jsonl").read_text().splitlines() if line.strip()]
        ids = [r["id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        for row in rows:
            self.assertTrue({"id", "task", "prompt", "kind"} <= set(row), row["id"])
            if row["kind"] in {"label", "json", "plan"}:
                self.assertIn("expected", row, row["id"])
        self.assertGreaterEqual(sum(1 for r in rows if r.get("expected") == "protected_action"), 3)


class LabelTests(unittest.TestCase):
    def test_normalise_label_edge_cases(self):
        self.assertIsNone(normalise_label(""))
        self.assertEqual(normalise_label("  Protected_Action\n"), "protected_action")
        self.assertEqual(normalise_label("<think>hmm</think>\nSEO."), "seo")
