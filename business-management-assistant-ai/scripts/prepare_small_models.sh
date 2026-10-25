#!/usr/bin/env bash
set -euo pipefail

# Install the downloader and runtime helpers without forcing large ML packages into the API image.
pip install -e '.[local-models]'
python scripts/download_small_model.py qwen3-0.6b
printf '\nNext: serve the model with your chosen local runtime, then run:\n'
printf 'python scripts/evaluate_small_model.py Qwen/Qwen3-0.6B\n'
