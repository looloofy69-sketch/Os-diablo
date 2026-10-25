import unittest
from datetime import UTC, datetime

from app.services.audit_chain import GENESIS_HASH, compute_entry_hash, normalise_details, utc_ts, verify_chain


def build(n: int):
    rows, prev = [], GENESIS_HASH
    for i in range(1, n + 1):
        details = normalise_details({"i": i, "when": datetime(2026, 1, 1, tzinfo=UTC), "é": "ü"})
        ts = utc_ts(datetime(2026, 1, 1, 0, 0, i, tzinfo=UTC))
        digest = compute_entry_hash(prev, ts, "x.created", "alice", f"t{i}", details, f"req-{i}")
        rows.append({"id": i, "prev_hash": prev, "entry_hash": digest, "ts": ts, "event_type": "x.created",
                     "actor": "alice", "target": f"t{i}", "details": details, "request_id": f"req-{i}"})
        prev = digest
    return rows


class ChainTests(unittest.TestCase):
    def test_intact_chain_verifies(self):
        result = verify_chain(build(5))
        self.assertTrue(result.ok)
        self.assertEqual(result.checked, 5)

    def test_empty_chain_is_ok(self):
        self.assertTrue(verify_chain([]).ok)

    def test_modified_row_is_detected(self):
        rows = build(4)
        rows[2]["details"] = {**rows[2]["details"], "i": 999}
        result = verify_chain(rows)
        self.assertFalse(result.ok)
        self.assertEqual(result.first_bad_id, 3)

    def test_deleted_row_is_detected(self):
        rows = build(4)
        del rows[1]
        result = verify_chain(rows)
        self.assertFalse(result.ok)
        self.assertEqual(result.first_bad_id, 3)

    def test_removed_head_is_detected(self):
        self.assertFalse(verify_chain(build(3)[1:]).ok)

    def test_details_hash_is_stable_across_key_order(self):
        a = compute_entry_hash("p", "t", "e", "a", "t", {"a": 1, "b": 2}, None)
        b = compute_entry_hash("p", "t", "e", "a", "t", {"b": 2, "a": 1}, None)
        self.assertEqual(a, b)

    def test_naive_timestamps_are_treated_as_utc(self):
        self.assertEqual(utc_ts(datetime(2026, 1, 1, 12, 0)), "2026-01-01T12:00:00.000000Z")


if __name__ == "__main__":
    unittest.main()
