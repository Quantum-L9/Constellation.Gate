#!/usr/bin/env sh
set -eu

export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-9000}"
export APP_MODULE="${APP_MODULE:-constellation_gate.api.main:app}"

python scripts/predeploy_check.py
exec uvicorn "${APP_MODULE}" --host "${HOST}" --port "${PORT}"
