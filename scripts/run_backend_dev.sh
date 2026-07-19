#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(dirname "$0")"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="${PYTHON_BIN:-$ROOT/python/.venv/bin/python}"

[[ -x "$PYTHON" ]] || {
	echo "[ERROR] Python venv is missing: $PYTHON" >&2
	exit 1
}

export APP_ENV="${APP_ENV:-development}"
export ENV="${ENV:-development}"
export NODE_ENV="${NODE_ENV:-development}"
export SERVER_HOST="${SERVER_HOST:-127.0.0.1}"
export SERVER_BIND_HOST="${SERVER_BIND_HOST:-127.0.0.1}"
export SERVER_PORT="${SERVER_PORT:-8001}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"
export PYTHONUNBUFFERED=1
export PYTHONIOENCODING=utf-8
export SCHEMA_MIGRATION_MODE="${SCHEMA_MIGRATION_MODE:-bootstrap}"

if [[ -z "${YUIZAKI_BACKEND_API_TOKEN:-}" ]]; then
	export YUIZAKI_BACKEND_API_TOKEN="$($PYTHON -c 'import secrets; print(secrets.token_urlsafe(32))')"
fi

cd "$ROOT/python"
"$PYTHON" migration_bootstrap.py
exec "$PYTHON" -m uvicorn app:app \
	--host "$SERVER_BIND_HOST" \
	--port "$SERVER_PORT" \
	--env-file .env \
	--log-level "$(printf '%s' "$LOG_LEVEL" | tr '[:upper:]' '[:lower:]')"
