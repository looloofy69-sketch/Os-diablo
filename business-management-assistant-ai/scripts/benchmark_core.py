#!/usr/bin/env python3
"""Benchmark the optimized top-k task ranker against the previous full-sort method.

This synthetic CPU microbenchmark alternates measurement order, warms up both paths,
records raw samples, and validates result equivalence after every measured run. It is
not an end-to-end database/API benchmark.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

# Permit running the benchmark directly from a source checkout without editable install.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.priorities import TaskView, as_utc, rank_tasks, score_task  # noqa: E402


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def full_sort_reference(tasks: list[TaskView], moment: datetime, limit: int) -> list[tuple[TaskView, str]]:
    far = datetime.max.replace(tzinfo=timezone.utc)
    scored = []
    for task in tasks:
        result = score_task(task, moment)
        if result is not None:
            scored.append((result[0], task, result[1]))
    scored.sort(key=lambda row: (-row[0], as_utc(row[1].due_at) or far, row[1].title.lower()))
    return [(task, reason) for _, task, reason in scored[:limit]]


def _signature(rows: list[tuple[TaskView, str]]) -> list[tuple[str, str]]:
    return [(task.id, reason) for task, reason in rows]


def _timed(call: Callable[[], list[tuple[TaskView, str]]]) -> tuple[list[tuple[TaskView, str]], float]:
    started = time.perf_counter()
    result = call()
    return result, time.perf_counter() - started


def run(tasks_count: int, repeats: int, limit: int = 5, warmups: int = 2) -> dict[str, object]:
    if tasks_count < 1 or repeats < 1 or limit < 1 or warmups < 0:
        raise ValueError("tasks_count, repeats and limit must be positive; warmups cannot be negative")

    moment = datetime(2026, 10, 24, tzinfo=timezone.utc)
    tasks = []
    for index in range(tasks_count):
        due = moment - timedelta(hours=index % 900) if index % 7 == 0 else moment + timedelta(hours=index % 500) if index % 3 == 0 else None
        tasks.append(TaskView(
            id=str(index),
            title=f"Task {index:08d}",
            status="active" if index % 5 == 0 else "planned",
            priority=("urgent", "high", "medium", "low")[index % 4],
            due_at=due,
            project_id=str(index % 200),
        ))

    optimized_call = lambda: rank_tasks(tasks, moment, limit)
    reference_call = lambda: full_sort_reference(tasks, moment, limit)

    # Warm both implementations before measurements and fail immediately on semantic drift.
    for _ in range(warmups):
        optimized_warm = optimized_call()
        reference_warm = reference_call()
        if _signature(optimized_warm) != _signature(reference_warm):
            raise RuntimeError("optimized ranker produced different results from the reference sort")

    optimized_times: list[float] = []
    reference_times: list[float] = []
    optimized: list[tuple[TaskView, str]] = []
    reference: list[tuple[TaskView, str]] = []
    for repeat in range(repeats):
        # Alternate timing order to reduce a systematic first/second-call advantage.
        if repeat % 2 == 0:
            optimized, optimized_elapsed = _timed(optimized_call)
            reference, reference_elapsed = _timed(reference_call)
        else:
            reference, reference_elapsed = _timed(reference_call)
            optimized, optimized_elapsed = _timed(optimized_call)
        optimized_times.append(optimized_elapsed)
        reference_times.append(reference_elapsed)
        if _signature(optimized) != _signature(reference):
            raise RuntimeError(f"optimized ranker differed from reference on measured repeat {repeat + 1}")

    optimized_median = statistics.median(optimized_times)
    reference_median = statistics.median(reference_times)
    return {
        "task_count": tasks_count,
        "limit": limit,
        "warmups": warmups,
        "repeats": repeats,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "optimized_samples_seconds": [round(value, 6) for value in optimized_times],
        "full_sort_samples_seconds": [round(value, 6) for value in reference_times],
        "optimized_median_seconds": round(optimized_median, 6),
        "full_sort_median_seconds": round(reference_median, 6),
        "speedup": round(reference_median / optimized_median, 3) if optimized_median else None,
        "same_top_results": True,
        "top_task_ids": [task.id for task, _reason in optimized],
        "note": "Synthetic CPU microbenchmark only; alternating order and warmups reduce timing bias but do not replace database or end-to-end load tests.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=positive_int, default=50000)
    parser.add_argument("--repeats", type=positive_int, default=5)
    parser.add_argument("--limit", type=positive_int, default=5)
    parser.add_argument("--warmups", type=int, default=2)
    args = parser.parse_args()
    if args.warmups < 0:
        parser.error("--warmups must be zero or greater")
    print(json.dumps(run(args.tasks, args.repeats, args.limit, args.warmups), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
