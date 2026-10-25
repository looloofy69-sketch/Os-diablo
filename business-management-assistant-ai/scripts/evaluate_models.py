#!/usr/bin/env python3
"""Evaluate reachable models with explicit call-cost controls and trusted score promotion.

`--limit` limits the number of models; `--max-examples` limits examples per model.
A sample with fewer than ten graded examples can be used as a smoke test, but is
not persisted as ranking evidence. The default full run costs approximately
number_of_models * dataset_rows model calls, less provider failures.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from app.core import Settings
from app.services.evaluation import run_dataset, summarise, validate_dataset
from app.services.model_pool import MIN_GRADED_SCORE_ROWS
from app.services.model_setup import build_pool


def nonnegative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero (unlimited) or a positive integer")
    return parsed


def read_dataset(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read dataset {path}: {exc}") from exc
    rows = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in {path}:{line_number}: {exc.msg}") from exc
    return validate_dataset(rows)


def read_existing_scores(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"existing scores file is invalid ({path}): {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"existing scores file must contain a JSON object: {path}")
    return value


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temp_name = handle.name
            json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default="data/evaluation/small_model_seed.jsonl")
    parser.add_argument("--limit", type=nonnegative_int, default=0, help="Evaluate at most this many models (best-ranked first); 0 means all")
    parser.add_argument("--max-examples", type=nonnegative_int, default=0, help="Evaluate at most this many dataset rows per model; 0 means all")
    parser.add_argument("--only", default="", help="Substring filter on endpoint/model")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    try:
        rows = read_dataset(dataset_path)
    except ValueError as exc:
        parser.error(str(exc))
    if args.max_examples:
        rows = rows[:args.max_examples]
    if not rows:
        parser.error("no evaluation rows selected")

    settings = Settings()
    scores_path = Path(settings.llm_scores_path)
    if scores_path.resolve() == dataset_path.resolve():
        parser.error("scores output path must not overwrite the evaluation dataset")
    try:
        existing = read_existing_scores(scores_path)
    except ValueError as exc:
        parser.error(str(exc))

    pool = build_pool(settings, with_scores=False)
    if pool is None:
        print("No LLM endpoints are configured or discoverable.")
        return 2
    pool.refresh(force=True)
    candidates = [candidate for candidate in pool.candidates("compose") if args.only in candidate.key]
    if args.limit:
        candidates = candidates[:args.limit]
    if not candidates:
        print("No reachable models.")
        return 2

    estimated_calls = len(candidates) * len(rows)
    print(f"Evaluation plan: {len(candidates)} model(s) x {len(rows)} example(s) = up to {estimated_calls} provider calls.")
    now = datetime.now(UTC).isoformat()
    changed = False
    for candidate in candidates:
        client = pool.client_for(candidate)
        row_scores, _, latencies = run_dataset(lambda system, messages: client.complete(system, messages).text, rows)
        summary = summarise(row_scores, min_graded=MIN_GRADED_SCORE_ROWS)
        latency = round(median(latencies), 3) if latencies else None
        print(
            f"{candidate.key:50s} accuracy {summary['accuracy']:.2f} "
            f"({summary['graded']}/{len(rows)} graded) median {latency}s"
        )
        if summary["graded"] < MIN_GRADED_SCORE_ROWS:
            print(f"  ranking score not updated: need at least {MIN_GRADED_SCORE_ROWS} graded examples")
            continue
        existing[candidate.key] = {
            "accuracy": summary["accuracy"],
            "graded": summary["graded"],
            "examples": len(rows),
            "median_latency_s": latency,
            "evaluated_at": now,
            "dataset": str(dataset_path),
        }
        changed = True

    if changed:
        atomic_write_json(scores_path, existing)
        print(f"Updated ranking scores atomically: {scores_path}")
    else:
        print("No ranking scores were changed; collected samples were below the evidence threshold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
