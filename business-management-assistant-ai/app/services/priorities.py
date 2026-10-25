"""Task ranking and goal-health heuristics (pure)."""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from datetime import UTC, datetime

PRIORITY_WEIGHT = {"urgent": 40, "high": 30, "medium": 15, "low": 5}
EXCLUDED = {"done", "blocked"}


@dataclass(frozen=True)
class TaskView:
    id: str
    title: str
    status: str
    priority: str
    due_at: datetime | None = None
    project_id: str | None = None


def as_utc(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def score_task(task: TaskView, now: datetime) -> tuple[float, str] | None:
    """Return ``(score, reason)`` or None when the task should not be suggested."""
    if task.status in EXCLUDED:
        return None
    score = float(PRIORITY_WEIGHT.get(task.priority, 15))
    reasons = [f"{task.priority} priority"]
    due = as_utc(task.due_at)
    if due is not None:
        hours = (due - now).total_seconds() / 3600
        if hours < 0:
            days = int(-hours // 24)
            score += 25 + min(days, 14) * 3
            reasons.insert(0, f"overdue by {days}d" if days else "overdue today")
        elif hours <= 48:
            score += 20
            reasons.insert(0, "due within 48h")
        elif hours <= 24 * 7:
            score += 8
            reasons.insert(0, "due this week")
    if task.status == "active":
        score += 5
    return score, ", ".join(reasons)


def rank_tasks(tasks: list[TaskView], now: datetime, limit: int = 5) -> list[tuple[TaskView, str]]:
    """Return the top tasks without sorting/materializing the full scored list.

    The ranking key is unchanged. ``heapq.nsmallest`` reduces the selection cost from
    O(n log n) to O(n log k), where k is the requested result count (usually five).
    """
    if limit <= 0:
        return []
    far = datetime.max.replace(tzinfo=UTC)

    def scored_rows():
        for task in tasks:
            result = score_task(task, now)
            if result is not None:
                yield result[0], task, result[1]

    best = heapq.nsmallest(
        limit,
        scored_rows(),
        key=lambda row: (-row[0], as_utc(row[1].due_at) or far, row[1].title.lower()),
    )
    return [(task, reason) for _, task, reason in best]



def goal_progress(done: int, total: int) -> float | None:
    return None if total == 0 else done / total


def goal_at_risk(target_date: datetime | None, progress: float | None, status: str, now: datetime, window_days: int = 14) -> bool:
    target = as_utc(target_date)
    if status == "done" or target is None:
        return False
    if target < now:
        return progress is None or progress < 1.0
    return (target - now).days <= window_days and (progress or 0.0) < 0.5
