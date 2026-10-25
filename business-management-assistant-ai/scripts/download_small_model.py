#!/usr/bin/env python3
"""Download one catalogued model from Hugging Face into models/<key>.

Install the optional downloader first: pip install -e '.[local-models]'.
The script never downloads arbitrary repository IDs; it only accepts catalog keys.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from app.services.local_models import get_model


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_key", help="Catalog key, for example qwen3-0.6b")
    parser.add_argument("--root", default="models", help="Destination root")
    parser.add_argument("--revision", default=None, help="Optional pinned Hugging Face revision")
    args = parser.parse_args()
    try:
        model = get_model(args.model_key)
    except KeyError:
        raise SystemExit(f"Unknown model key {args.model_key!r}. Run: python -c \"from app.services.local_models import catalog; print([m['key'] for m in catalog()])\"") from None

    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise SystemExit("Install local-model dependencies with: pip install -e '.[local-models]'") from exc

    destination = Path(args.root) / model.key
    destination.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=model.repo_id, local_dir=str(destination), revision=args.revision)
    manifest = {"key": model.key, "repo_id": model.repo_id, "revision": args.revision or "default-branch", "downloaded_at": datetime.now(UTC).isoformat()}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if not args.revision:
        print("Warning: no --revision given; pin one so evaluation results stay reproducible.")
    print(f"Downloaded {model.display_name} to {destination}")
    print(f"Official model card: {model.official_url}")


if __name__ == "__main__":
    main()
