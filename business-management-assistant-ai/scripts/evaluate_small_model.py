#!/usr/bin/env python3
"""Score ONE model against the seed dataset (routing labels, JSON extraction, risk labels, planner tool selection).

Works with any OpenAI-compatible endpoint or the Anthropic API. Exits non-zero below --min-accuracy so it can gate a
model or prompt change in CI. To score everything the running assistant can reach, use scripts/evaluate_models.py.

  python scripts/evaluate_small_model.py Qwen/Qwen3-8B --base-url http://127.0.0.1:8001
  ANTHROPIC_API_KEY=... python scripts/evaluate_small_model.py <model> --provider anthropic
"""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from pathlib import Path

from app.services.evaluation import run_dataset, summarise, validate_dataset
from app.services.llm import ChatClient


def _accuracy(value: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number from 0 to 1") from exc
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise argparse.ArgumentTypeError("must be a finite number from 0 to 1")
    return result


def _timeout(value: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive number up to 300 seconds") from exc
    if not math.isfinite(result) or not 0 < result <= 300:
        raise argparse.ArgumentTypeError("must be a finite number in (0, 300]")
    return result


def _write_jsonl_atomic(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temp_name = handle.name
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("model")
    parser.add_argument("--provider", choices=["openai_compatible", "anthropic"], default="openai_compatible")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--api-key-env", default=None, help="Variable holding the API key (default ANTHROPIC_API_KEY or LLM_API_KEY)")
    parser.add_argument("--dataset", default="data/evaluation/small_model_seed.jsonl")
    parser.add_argument("--output", default="data/evaluation/results.jsonl")
    parser.add_argument("--timeout", type=_timeout, default=120.0)
    parser.add_argument("--min-accuracy", type=_accuracy, default=0.9)
    parser.add_argument("--min-graded", type=int, default=10, help="Minimum graded rows required to pass the evaluation gate")
    args = parser.parse_args()
    if args.min_graded < 1:
        parser.error("--min-graded must be at least 1")

    dataset_path, output_path = Path(args.dataset), Path(args.output)
    if dataset_path.resolve() == output_path.resolve():
        parser.error("--output must not overwrite the evaluation dataset")
    try:
        rows = [json.loads(line) for line in dataset_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        rows = validate_dataset(rows)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        parser.error(f"invalid evaluation dataset: {exc}")

    key_var = args.api_key_env or ("ANTHROPIC_API_KEY" if args.provider == "anthropic" else "LLM_API_KEY")
    client = ChatClient(args.provider, args.model, None if args.provider == "anthropic" else args.base_url, os.environ.get(key_var), args.timeout, max_tokens=800)
    scores, results, latencies = run_dataset(lambda system, messages: client.complete(system, messages).text, rows)

    summary = summarise(scores, args.min_accuracy, args.min_graded)
    summary["median_latency_s"] = round(sorted(latencies)[len(latencies) // 2], 3) if latencies else None
    _write_jsonl_atomic(output_path, results)
    print(json.dumps(summary, indent=2))
    return 0 if summary["meets_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
