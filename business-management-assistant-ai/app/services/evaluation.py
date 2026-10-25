"""Scoring for small-model evaluation runs (pure). Promotion gate lives in scripts/evaluate_small_model.py."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.services.llm import LLMError, normalise_label
from app.services.planner import build_messages, build_system_prompt, parse_plan
from app.services.policy import external_action_types

SUPPORTED_KINDS = frozenset({"label", "json", "plan", "free"})


def validate_dataset(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate evaluation fixtures before any metered provider calls are made."""
    if not isinstance(rows, list) or not rows:
        raise ValueError("evaluation dataset must be a non-empty JSONL list")
    seen: set[str] = set()
    checked: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"dataset row {index} must be a JSON object")
        for field in ("id", "task", "prompt", "kind"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f"dataset row {index}: {field} must be a non-empty string")
        row_id = row["id"].strip()
        if row_id in seen:
            raise ValueError(f"dataset row {index}: duplicate id {row_id!r}")
        seen.add(row_id)
        kind = row["kind"]
        if kind not in SUPPORTED_KINDS:
            raise ValueError(f"dataset row {index}: unsupported kind {kind!r}")
        if len(row["prompt"]) > 12000:
            raise ValueError(f"dataset row {index}: prompt exceeds 12000 characters")
        if kind != "free" and "expected" not in row:
            raise ValueError(f"dataset row {index}: {kind} rows require expected")
        expected = row.get("expected")
        if kind == "label" and (not isinstance(expected, str) or not expected.strip()):
            raise ValueError(f"dataset row {index}: label expected must be a non-empty string")
        if kind == "json" and not isinstance(expected, dict):
            raise ValueError(f"dataset row {index}: json expected must be an object")
        if kind == "plan" and (not isinstance(expected, list) or any(not isinstance(tool, str) or not tool for tool in expected)):
            raise ValueError(f"dataset row {index}: plan expected must be a list of tool names")
        checked.append(row)
    return checked

_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


@dataclass(frozen=True)
class RowScore:
    id: str
    task: str
    kind: str
    passed: bool | None  # None: needs human or larger-model review
    detail: str = ""


def parse_json_object(output: str) -> dict[str, Any] | None:
    match = _JSON_BLOCK.search(re.sub(r"<think>.*?</think>", "", output or "", flags=re.S | re.I))
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def score_row(row: dict[str, Any], output: str) -> RowScore:
    kind = row.get("kind", "free")
    expected = row.get("expected")
    base = {"id": row["id"], "task": row["task"], "kind": kind}
    if kind == "label":
        got = normalise_label(output)
        return RowScore(**base, passed=got == expected, detail=f"expected {expected!r}, got {got!r}")
    if kind == "json":
        parsed = parse_json_object(output)
        if parsed is None:
            return RowScore(**base, passed=False, detail="output is not a JSON object")
        wrong = {k: parsed.get(k) for k, v in (expected or {}).items() if parsed.get(k) != v}
        return RowScore(**base, passed=not wrong, detail="" if not wrong else f"mismatched fields: {wrong}")
    if kind == "plan":
        plan = parse_plan(output)
        if not plan.ok:
            return RowScore(**base, passed=False, detail=f"invalid plan: {plan.error}")
        # Preserve multiplicity: repeated write/proposal tools are not equivalent to
        # one expected call and must not pass by set-deduplication.
        got = sorted(step.tool for step in plan.steps)
        want = sorted(expected or [])
        return RowScore(**base, passed=got == want, detail=f"expected tools {want}, got {got}")
    return RowScore(**base, passed=None, detail="free-form: route to larger evaluator")


def summarise(scores: list[RowScore], min_accuracy: float = 0.9, min_graded: int = 10) -> dict[str, Any]:
    """Summarize quality and require both accuracy and minimum sample coverage."""
    if isinstance(min_accuracy, bool) or not isinstance(min_accuracy, (int, float)) or not 0 <= min_accuracy <= 1:
        raise ValueError("min_accuracy must be between 0 and 1")
    if isinstance(min_graded, bool) or not isinstance(min_graded, int) or min_graded < 1:
        raise ValueError("min_graded must be a positive integer")
    graded = [s for s in scores if s.passed is not None]
    passed = sum(1 for s in graded if s.passed)
    accuracy = passed / len(graded) if graded else 0.0
    enough_evidence = len(graded) >= min_graded
    return {
        "graded": len(graded),
        "required_graded": min_graded,
        "passed": passed,
        "accuracy": round(accuracy, 4),
        "needs_review": [s.id for s in scores if s.passed is None],
        "failures": [{"id": s.id, "detail": s.detail} for s in graded if not s.passed],
        "meets_gate": enough_evidence and accuracy >= min_accuracy,
    }


PLAN_SYSTEM = build_system_prompt(datetime(2026, 10, 10, 9, 0, tzinfo=UTC), "No records yet.", external_action_types())


def run_dataset(complete: Callable[[str, list[dict[str, str]]], str], rows: list[dict[str, Any]]) -> tuple[list[RowScore], list[dict[str, Any]], list[float]]:
    """Run every validated row through ``complete(system, messages) -> text``."""
    rows = validate_dataset(rows)
    scores: list[RowScore] = []
    results: list[dict[str, Any]] = []
    latencies: list[float] = []
    for row in rows:
        system, messages = "Follow the instruction exactly.", [{"role": "user", "content": row["prompt"]}]
        if row["kind"] == "plan":
            system, messages = PLAN_SYSTEM, build_messages([], row["prompt"])
        started = time.perf_counter()
        error = ""
        try:
            output = complete(system, messages)
        except LLMError as exc:
            output, error = "", str(exc)
        latency = time.perf_counter() - started
        latencies.append(latency)
        score = score_row(row, output)
        scores.append(score)
        results.append({**row, "output": output, "passed": score.passed, "detail": error or score.detail, "latency_s": round(latency, 3)})
    return scores, results, latencies
