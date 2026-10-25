#!/bin/sh
# Outside sandbox the schema comes from migrations; run them before serving unless RUN_MIGRATIONS=0.
set -e
if [ "${ENVIRONMENT:-sandbox}" != "sandbox" ] && [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  alembic upgrade head
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 ${UVICORN_ARGS:-}
