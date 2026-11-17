#!/bin/sh
# Старт контейнера app: миграции → (опционально) seed → процесс из CMD.
# PostgreSQL к этому моменту готов: compose ждёт его healthcheck (depends_on: service_healthy).
set -eu

echo "[entrypoint] alembic upgrade head"
alembic upgrade head

if [ "${SEED_ON_START:-0}" = "1" ]; then
    echo "[entrypoint] SEED_ON_START=1: python -m app.maintenance.seed"
    python -m app.maintenance.seed
fi

exec "$@"
