#!/usr/bin/env bash
# Release gate. Needs: pip install -e '.[dev,postgres]'
set -euo pipefail

skip_docker=false
while (($#)); do
  case "$1" in
    --skip-docker) skip_docker=true ;;
    -h|--help)
      echo "Usage: scripts/verify_release.sh [--skip-docker]"
      echo "By default Docker is required; --skip-docker explicitly makes this a partial verification run."
      exit 0
      ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

python -m compileall -q app scripts tests
ruff check .
pytest -q

# Use a private temporary directory rather than mktemp -u (which races by not creating a file).
tmpdir="$(mktemp -d)"
created_env_file=false
cleanup() {
  rm -rf "$tmpdir"
  if [[ "$created_env_file" == true ]]; then rm -f .env; fi
}
trap cleanup EXIT
DATABASE_URL="sqlite:///$tmpdir/release.db" alembic upgrade head
DATABASE_URL="sqlite:///$tmpdir/release.db" alembic current

docker_built=false
if command -v docker >/dev/null 2>&1; then
  # Compose's env_file path is part of the configuration; create an empty temporary file only if absent.
  if [[ ! -f .env ]]; then : > .env; created_env_file=true; fi
  POSTGRES_PASSWORD="release-check-only-not-a-secret" docker compose config --quiet
  docker build --pull -t business-assistant:verify .
  docker_built=true
elif [[ "$skip_docker" != true ]]; then
  echo "ERROR: Docker is not installed. Install Docker or explicitly use --skip-docker for a partial local check." >&2
  exit 2
fi

if [[ "$docker_built" == true ]]; then
  echo "PASS: automated release checks completed, including Docker configuration/build."
  echo "Before tagging, run controlled model evaluation and SMTP/webhook integration tests as documented."
else
  echo "PARTIAL VERIFICATION ONLY: Python tests, Ruff and SQLite migration checks completed; Docker checks were explicitly skipped."
  echo "Do not tag or mark this candidate production-ready from that partial run."
fi
