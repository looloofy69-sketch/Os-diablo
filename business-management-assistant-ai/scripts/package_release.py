#!/usr/bin/env python3
"""Create a clean deterministic source ZIP for release review.

The script excludes runtime secrets, databases, environments, caches, model weights,
pytest artefacts, and generated evaluation outputs. It never publishes or tags a release.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import stat
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache",
    ".mypy_cache", ".tox", "dist", "build", "node_modules", "release_artifacts",
    ".aws", ".ssh", ".terraform", "credentials", "private_keys", "secrets",
}
EXCLUDED_FILES = {
    ".env", "results.jsonl", "scores.json", ".DS_Store", "secrets.json",
    "secrets.yaml", "secrets.yml", "credentials.json", "id_rsa", "id_ed25519",
    "id_ecdsa", "known_hosts", "authorized_keys",
}
EXCLUDED_SUFFIXES = {
    ".pyc", ".pyo", ".db", ".sqlite", ".sqlite3", ".log", ".pem", ".key",
    ".p12", ".pfx", ".crt", ".cer", ".jks", ".tfstate",
}
ROOT_PREFIX = "business-management-assistant-ai"


def included(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if any(part.lower() in EXCLUDED_DIRS for part in rel.parts):
        return False
    lower_name = path.name.lower()
    if lower_name in EXCLUDED_FILES or path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    if lower_name.startswith(".env") and lower_name != ".env.example":
        return False
    if rel.parts[0].lower() == "models" and lower_name != ".gitkeep":
        return False
    if path.as_posix().endswith("data/evaluation/results.jsonl") or path.as_posix().endswith("data/evaluation/scores.json"):
        return False
    if any(secret in path.parts for secret in (".aws", ".ssh", "secrets")):
        return False
    return path.is_file()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        version = tomllib.load(handle)["project"]["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"Expected a stable semantic version in pyproject.toml, got {version!r}")
    core = (ROOT / "app" / "core.py").read_text(encoding="utf-8")
    if f'version: str = "{version}"' not in core:
        raise ValueError("pyproject.toml and app/core.py version values disagree")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if not re.search(rf"^## {re.escape(version)}$", changelog, re.M):
        raise ValueError("CHANGELOG.md has no section for the project version")
    return version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    version = project_version()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"{ROOT_PREFIX}-v{version}.zip"
    sources = sorted(path for path in ROOT.rglob("*") if included(path))
    if not sources:
        raise SystemExit("No source files found to package")

    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, strict_timestamps=True) as bundle:
        for path in sources:
            relative = path.relative_to(ROOT).as_posix()
            arcname = f"{ROOT_PREFIX}/{relative}"
            info = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | (0o755 if path.stat().st_mode & 0o111 else 0o644)) << 16
            bundle.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)

    print(f"Packaged {len(sources)} files: {archive}")
    print(f"SHA-256: {sha256(archive)}")
    print("Excluded caches, virtual environments, local databases, .env files, model weights and generated evaluation outputs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
