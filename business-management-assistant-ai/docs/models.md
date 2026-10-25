# Models

The assistant is not tied to a model. At runtime it uses whatever is reachable.

## Where models come from
1. **Environment**: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `GROQ_API_KEY`, `TOGETHER_API_KEY`, `MISTRAL_API_KEY`. A key is only ever sent to its own provider's host.
2. **Local servers**, probed on loopback: Ollama (11434), LM Studio (1234), llama.cpp (8080), anything on 8001.
3. **`LLM_ENDPOINTS`**: a JSON array for everything else (vLLM on another machine, a gateway, per-endpoint limits).
4. **`LLM_MODEL` + `LLM_BASE_URL`**: pins one model; it is simply one more endpoint, tried first.

Each endpoint's model list is read from `/v1/models` and refreshed every `LLM_REFRESH_SECONDS` (default 300) during normal traffic, so a server started or stopped while the app runs is picked up. A failed refresh keeps the last known list. `POST /api/ai/models/refresh` (admin) forces it. Embedding, speech, image and guard models are never used for chat.

## How a model is chosen for a request
Candidates are ordered by: explicit endpoint `priority` (lower first), then quality, then name. Tier preference (`LLM_PREFER=local|hosted`) goes in front of both.

- **Quality** is the measured accuracy from `data/evaluation/scores.json` when present, otherwise a name-based guess (parameter count, `opus`/`sonnet`/`haiku`, `gpt-5`, `mini`...). The guess is only a starting point. Measured scores must be finite and in [0, 1], and an evaluation record needs at least ten graded rows to influence ranking.
- Models measured below `LLM_MIN_PLAN_SCORE` are not used for planning (they can still write replies).
- A model that returns invalid plans is demoted a step each time and restored after one good plan.

For a planning request the pool tries the best candidate (one repair attempt on invalid output), then the next, up to `LLM_MAX_CASCADE`. The reply is composed by the same model that produced the plan when it is still healthy. Errors, timeouts and quality failures all fall through to the next model; after three consecutive infrastructure failures a model is skipped for a minute, doubling up to ten.

Nothing reachable: the rules answer, silently. Reachable but all failing: the rules answer and say so.

## Limits and data
- `LLM_DAILY_CALL_LIMIT` (per process) and `daily_limit` per endpoint stop spending; hitting one never marks a model unhealthy.
- With any hosted provider reachable, message text, recent turns and a short business snapshot may be sent to it. `LLM_ALLOW_HOSTED=false` removes hosted endpoints from consideration entirely.
- Prompts and replies are not stored; the audit trail records which model served each planned message, the attempts that failed, and token usage.

## Measuring
```bash
python scripts/evaluate_models.py                         # all models x all dataset rows
python scripts/evaluate_models.py --limit 3               # at most three models, all rows each
python scripts/evaluate_models.py --limit 1 --max-examples 10  # cap cost for one-model smoke test
python scripts/evaluate_small_model.py <model> --base-url http://...   # one model, exits 1 below 90%
```
Re-run after adding models or changing prompts. The seed dataset is small (25 rows); extend it with your own requests before trusting small differences.


### Evaluation cost and score promotion

`--limit` limits the **number of models**, not the number of provider calls. `--max-examples` limits dataset rows per model. The command prints an estimate before making model calls. Partial runs with fewer than 10 graded rows are useful smoke tests but do not overwrite ranking scores. The evaluation file is validated before provider requests, and the score JSON is updated atomically only after the run finishes. Avoid real business/customer prompts in evaluation data unless authorized.
