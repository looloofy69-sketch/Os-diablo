# Local small-model subsystem

The business manager can use compact local models for bounded, repetitive, privacy-sensitive, or high-volume tasks. The larger AI manager remains the evaluator, policy gate, and fallback for uncertain or high-impact work.

## Recommended seed models

| Model | Best use | License / access | Official link |
|---|---|---|---|
| Qwen3 0.6B | Routing, classification, short extraction, lightweight local chat | Apache-2.0 | [Qwen/Qwen3-0.6B](https://huggingface.co/Qwen/Qwen3-0.6B) |
| SmolLM2 1.7B Instruct | Summaries, rewriting, function-call drafts, local chat | Apache-2.0 | [HuggingFaceTB/SmolLM2-1.7B-Instruct](https://huggingface.co/HuggingFaceTB/SmolLM2-1.7B-Instruct) |
| Gemma 3 1B IT | Compact chat, summarisation, image-text assistance | Gemma Terms of Use; gated access may require accepting terms | [google/gemma-3-1b-it](https://huggingface.co/google/gemma-3-1b-it) |
| Qwen3 Embedding 0.6B | Semantic search and business-memory indexing | Check official model card | [Qwen/Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) |
| Qwen3 ASR 0.6B | Local meeting transcription and voice notes | Check official model card | [Qwen/Qwen3-ASR-0.6B](https://huggingface.co/Qwen/Qwen3-ASR-0.6B) |

The links above are official Hugging Face model cards. Check each model card and licence before commercial deployment. The registry intentionally does not silently download weights.

## Download

From the repository root:

```bash
pip install -e '.[local-models]'
python scripts/download_small_model.py qwen3-0.6b
```

Or prepare the default seed setup:

```bash
bash scripts/prepare_small_models.sh
```

The downloader accepts only catalogued keys and places weights under `models/<key>`. It does not accept arbitrary repository IDs. Use a Hugging Face token through the normal Hugging Face CLI/environment when a gated model requires authentication; never commit tokens.

Available keys:

```text
qwen3-0.6b
smollm2-1.7b-instruct
gemma3-1b-it
qwen3-embedding-0.6b
qwen3-asr-0.6b
```

## API discovery

- `GET /api/local-models` — catalog plus local readiness status
- `GET /api/local-models/recommend?task=routing` — task-specific recommendations
- `GET /api/local-models/{model_key}/status` — one model's readiness
- `GET /api/ai/capabilities` — full specialist-agent, route, policy, and local-model catalog

## Runtime pattern

1. The manager classifies a request and identifies whether it is bounded and low risk.
2. A local model handles routing, extraction, summarisation, embeddings, or transcription where appropriate.
3. Outputs are schema-checked and logged.
4. The larger evaluator reviews samples, failures, uncertainty, and policy-sensitive outputs.
5. Finance, contracts, public publishing, account changes, and external communications remain approval-gated.

## Evaluation and seed learning

The seed dataset is `data/evaluation/small_model_seed.jsonl`. Start a local OpenAI-compatible model server, then run:

```bash
python scripts/evaluate_small_model.py Qwen/Qwen3-0.6B
```

Label and JSON rows carry an `expected` value and are scored automatically; the script prints accuracy, failures, rows needing review and median latency, and exits non-zero below `--min-accuracy` (default 0.9). To let the API use a served model for intent assist, set `LLM_BASE_URL` and `LLM_MODEL`: the model may return only `briefing`, `seo`, `advertising`, `protected_action` or `other`, and only for text the rules did not match.

Results are written to `data/evaluation/results.jsonl`. Promotion should require larger-model evaluation, schema validity, task accuracy, refusal/safety checks, latency, cost, and regression comparison against the previous model. The small model may learn from approved, redacted business examples, but raw personal, legal, financial, or secret data must not be copied into training data without a documented data policy.
