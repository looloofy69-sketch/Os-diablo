from __future__ import annotations

import argparse
import unittest

from scripts.benchmark_core import positive_int, run


class BenchmarkCoreTests(unittest.TestCase):
    def test_positive_int_accepts_positive_integer(self):
        self.assertEqual(positive_int("12"), 12)

    def test_positive_int_rejects_invalid_values(self):
        for value in ("0", "-1", "1.2", "abc"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                positive_int(value)

    def test_benchmark_alternates_and_preserves_top_results(self):
        result = run(tasks_count=300, repeats=3, limit=5, warmups=1)
        self.assertTrue(result["same_top_results"])
        self.assertEqual(len(result["optimized_samples_seconds"]), 3)
        self.assertEqual(len(result["full_sort_samples_seconds"]), 3)
        self.assertEqual(result["task_count"], 300)

    def test_benchmark_rejects_nonpositive_dimensions(self):
        with self.assertRaises(ValueError):
            run(tasks_count=0, repeats=1)
        with self.assertRaises(ValueError):
            run(tasks_count=10, repeats=1, warmups=-1)


if __name__ == "__main__":
    unittest.main()
