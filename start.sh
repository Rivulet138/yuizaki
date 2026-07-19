#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(dirname "$0")"
ROOT="$(cd "$SCRIPT_DIR" && pwd)"
PYTHON="${PYTHON_BIN:-$ROOT/python/.venv/bin/python}"
WITH_MCP=0
DEV_RENDERER=0
CHECK_ONLY=0
SMOKE=0

for argument in "$@"; do
	case "$argument" in
	--with-mcp) WITH_MCP=1 ;;
	--no-mcp) WITH_MCP=0 ;;
	--dev-renderer) DEV_RENDERER=1 ;;
	--no-dev-renderer) DEV_RENDERER=0 ;;
	--check | --verify) CHECK_ONLY=1 ;;
	--smoke) SMOKE=1 ;;
	--no-qdrant | --no-open | --no-show-pet) ;;
	--help | -h)
		echo "Usage: ./start.sh [--check] [--with-mcp] [--dev-renderer] [--smoke]"
		exit 0
		;;
	*)
		echo "[ERROR] Unknown argument: $argument" >&2
		exit 2
		;;
	esac
done

require_file() { [[ -e "$1" ]] || {
	echo "[ERROR] Missing: $1" >&2
	exit 1
}; }
preflight_mode="--launch"
if ((CHECK_ONLY)); then preflight_mode="--check"; fi
PYTHON_BIN="$PYTHON" bash "$ROOT/scripts/check_linux_environment.sh" "$preflight_mode"
require_file "$PYTHON"
require_file "$ROOT/python/app.py"
require_file "$ROOT/electron/package.json"
require_file "$ROOT/electron/node_modules/electron/cli.js"
if ((WITH_MCP)); then require_file "$ROOT/node-mcp/node_modules"; fi

if ((CHECK_ONLY)); then
	"$PYTHON" -c 'import fastapi, socketio, sqlalchemy, uvicorn'
	(cd "$ROOT/electron" && npm run type-check)
	echo "[OK] Linux startup preflight passed."
	exit 0
fi

select_port() {
	"$PYTHON" - "$@" <<'PY'
import socket, sys
for raw in sys.argv[1:]:
    port = int(raw)
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', port))
        except OSError:
            continue
    print(port)
    raise SystemExit(0)
raise SystemExit(1)
PY
}

wait_url() {
	"$PYTHON" - "$1" "${2:-120}" <<'PY'
import sys, time, urllib.request
url, timeout = sys.argv[1], float(sys.argv[2])
deadline = time.monotonic() + timeout
while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            if 200 <= response.status < 500:
                raise SystemExit(0)
    except Exception:
        time.sleep(0.5)
raise SystemExit(f'timed out waiting for {url}')
PY
}

SERVER_PORT="${SERVER_PORT:-$(select_port 8001 8011 8012 8013 8014 8015)}"
CONTROL_SERVER_PORT="${CONTROL_SERVER_PORT:-$(select_port 38945 38946 38947 38948 38949)}"
RENDERER_PORT="${RENDERER_PORT:-$(select_port 5173 5174 5175 5176 5177)}"
MCP_PORT="${MCP_PORT:-$(select_port 7777 7778 7779)}"
TOKEN="${YUIZAKI_BACKEND_API_TOKEN:-$($PYTHON -c 'import secrets; print(secrets.token_urlsafe(32))')}"

export SERVER_HOST=127.0.0.1 SERVER_BIND_HOST=127.0.0.1 SERVER_PORT
export CONTROL_SERVER_PORT RENDERER_PORT MCP_PORT
export VITE_DEV_SERVER_PORT="$RENDERER_PORT"
export YUIZAKI_BACKEND_API_TOKEN="$TOKEN" YUIZAKI_CONTROL_TOKEN="$TOKEN"
export DESKTOP_PET_SKIP_INTERNAL_PYTHON=1
export BACKEND_URL="http://127.0.0.1:$SERVER_PORT"
export DESKTOP_PET_BACKEND_URL="$BACKEND_URL"
export VITE_YUIZAKI_API_ORIGIN="$BACKEND_URL"
export VITE_YUIZAKI_CONTROL_ORIGIN="http://127.0.0.1:$CONTROL_SERVER_PORT"
export YUIZAKI_PROJECT_ROOT="$ROOT"
export YUIZAKI_ELECTRON_ROOT="$ROOT/electron"
export YUIZAKI_ALLOWED_ORIGINS="http://127.0.0.1:$CONTROL_SERVER_PORT,http://localhost:$CONTROL_SERVER_PORT,http://127.0.0.1:$RENDERER_PORT,http://localhost:$RENDERER_PORT"

pids=()
cleanup() {
	trap - EXIT INT TERM
	for ((index = ${#pids[@]} - 1; index >= 0; index--)); do
		kill -TERM "${pids[index]}" 2>/dev/null || true
	done
	wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if ((DEV_RENDERER)); then
	(cd "$ROOT/electron" && npm run build:electron)
else
	(cd "$ROOT/electron" && npm run build)
fi

(cd "$ROOT/python" && exec "$ROOT/scripts/run_backend_dev.sh") &
pids+=("$!")
wait_url "$BACKEND_URL/api/ping" 120

if ((WITH_MCP)); then
	(cd "$ROOT/node-mcp" && exec node server.mjs) &
	pids+=("$!")
	wait_url "http://127.0.0.1:$MCP_PORT/health" 120
fi

if ((DEV_RENDERER)); then
	export VITE_DEV_SERVER_URL="http://localhost:$RENDERER_PORT"
	(cd "$ROOT/electron" && exec node node_modules/vite/bin/vite.js --host 127.0.0.1 --port "$RENDERER_PORT") &
	pids+=("$!")
	wait_url "$VITE_DEV_SERVER_URL" 120
else
	unset VITE_DEV_SERVER_URL || true
fi

(cd "$ROOT/electron" && exec node scripts/run-electron.mjs) &
electron_pid="$!"
pids+=("$electron_pid")
wait_url "http://127.0.0.1:$CONTROL_SERVER_PORT/api/health" 240

if ((SMOKE)); then
	wait_url "http://127.0.0.1:$CONTROL_SERVER_PORT/api/ping" 30
	echo "[OK] Linux smoke endpoints are responding."
fi

echo "[OK] Yuizaki is running on Linux. Press Ctrl+C to stop."
wait "$electron_pid"
