# Performance and Logic-Validation Notes — v0.4.1 Candidate

## Scope and evidence boundary

This document records source changes in the v0.4.1 candidate package. The benchmark is a synthetic CPU microbenchmark; it does not prove database throughput or live-model latency. The dependency-backed API suite, PostgreSQL tests, Ruff, Docker build, and live providers still need to run in a connected release environment.

## Performance changes

### Top-k task ranking

`app/services/priorities.py` previously scored every eligible task into a list and fully sorted it, even though the briefing only needs five next actions. It now uses `heapq.nsmallest` with the same scoring and ordering keys. Selection work changes from O(n log n) sorting to O(n log k), with O(k) top-result storage, where `k` is the small result limit.

Run a reproducible synthetic comparison:

    python scripts/benchmark_core.py --tasks 50000 --repeats 5

The script compares optimized output against a reference implementation of the former full-sort behavior and aborts if task IDs or reasons differ. The latest five-run sample on Python 3.13.5 with 50,000 synthetic tasks measured a 0.037587-second optimized median versus 0.093045 seconds for full sort (2.475x in that run). Raw optimized samples were 0.037042, 0.037587, 0.036930, 0.038961, and 0.037896 seconds; full-sort samples were 0.153207, 0.086952, 0.093045, 0.156822, and 0.087318 seconds. Timing varies between runs. This is a synthetic CPU microbenchmark, not a general performance guarantee or an end-to-end application benchmark.

### Narrower briefing reads

The briefing query now selects only the six task fields needed for counts, overdue/blocked attention, and ranking rather than materializing full ORM Task entities. The task count still needs to be traversed to produce exact ranking and overdue summaries; this is a memory/row-shape optimization, not a claim that query cost is constant with table size.

### Model discovery

Concurrent requests during the first discovery now wait on one in-flight refresh rather than racing after the cache timestamp was set but before model lists were available. Probes remain concurrent (bounded to eight endpoints), while successful results are deduplicated and failed refreshes preserve the prior list.

### Evaluation-cost controls

`evaluate_models.py --limit N` limits models, not calls. `--max-examples N` limits the rows run per model, and the CLI prints the upper-bound call estimate before provider requests. Score files are replaced atomically only after completed evaluations. Runs with fewer than ten graded examples do not update ranking scores.

## Logic-validation changes

- Endpoint JSON now validates base URL structure, embedded credentials, query/fragment components, model/role types, numeric finiteness/ranges, daily limits, and boolean flags before discovery or model calls.
- Direct model-pool construction also validates cascade, refresh, ranking threshold and candidate-cap settings.
- Measured scores are accepted only when finite and in [0, 1] and accompanied by an explicit integer graded-example count of at least ten. Legacy scalar scores and accuracy-only records without a graded count are ignored; rerun evaluation before relying on measured ranking evidence.
- Webhook URL validation rejects whitespace/control characters, embedded credentials, malformed/empty/out-of-range ports, query strings and fragments. Route entries require correctly typed name/prefix/URL/secret fields and duplicate normalized prefixes are rejected.
- Direct Slack and signed-webhook connector construction rejects non-finite, boolean, non-positive or excessive timeouts.
- Planner evaluation preserves duplicate tool calls rather than converting them to a set; unexpected duplicate proposal/write tools no longer receive an easy false pass.
- Evaluation JSONL is schema-checked for unique IDs, supported kinds, required values and prompt length before provider costs are incurred.
- A short one-example smoke test cannot satisfy the evaluation promotion gate by accuracy alone; the minimum graded sample count is explicit.
- Connector results carry an explicit `outcome_unknown` boolean independent of `retryable`. The approval layer persists that typed field and never infers outcome certainty by searching error text. This prevents timeouts or transport failures with different wording from being misclassified.
- All non-2xx HTTP responses are outcome-unknown for generic webhook actions because a receiver response cannot prove the side effect did not happen; these are not automatically retryable. DNS/refused connection failures known to occur before delivery can be retryable; ambiguous transport failures are explicitly unknown. SMTP send-stage disconnects/timeouts are marked outcome-unknown.
- Model API and action POST clients no longer automatically follow HTTP redirects, which could forward credentials, signed payloads or business prompts to an unvalidated location.
- Bare ISO dates now resolve to the true end of the UTC day (23:59:59.999999), matching the date parser's documented intent.

## Release gate behavior

`scripts/verify_release.sh` performs one full pytest run (unit tests are included), Ruff, Python compilation, Alembic upgrade/current against a real temporary SQLite database, Compose config validation and Docker build. Docker is required by default. `--skip-docker` is an explicit partial run and prints that production tagging is not justified by that run.

`scripts/package_release.py` creates a deterministic source ZIP and checks that `pyproject.toml`, runtime settings, and changelog version headings agree. It excludes local `.env` files, databases, caches, virtual environments, model weights, generated evaluation scores/results, common key/certificate files, Terraform state, and credential/private-key directories (case-insensitively).

## Local verification run during this packaging pass

- Standard-library unit suite after typed outcome propagation: **158 tests passed**; `pytest tests/unit` reports **158 passed, 52 subtests passed**.
- Added an API regression test proving approval persistence trusts the explicit `outcome_unknown` field rather than parsing error text. That API test and the complete API suite remain blocked in this sandbox during collection because `sqlmodel` is unavailable.
- Python compilation and shell syntax checks: passed. Regression tests cover model payloads and common secret/key/certificate files being excluded from release ZIPs while the `models/.gitkeep` placeholder is retained.
- `docker-compose.yml` and CI YAML parse: passed with PyYAML available.
- Runtime tests confirm HTTP redirects are not followed for webhook action POSTs or model API calls, and HTTP-error response streams are closed after classification.
- Full `pytest -q` is blocked during API test collection by `ModuleNotFoundError: No module named 'sqlmodel'`. Ruff and Docker are not installed; package-index DNS resolution prevented installing dependencies. PostgreSQL migration checks, Docker build and live-provider/connector tests therefore remain unverified.
