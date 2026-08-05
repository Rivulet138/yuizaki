#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(dirname "$0")"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
CONTROL_SERVER_PORT="${CONTROL_SERVER_PORT:-38949}"
BACKEND_PORT="${SERVER_PORT:-0}"
TOKEN="${YUIZAKI_CONTROL_TOKEN:-linux-smoke-token}"
LOG_FILE="${YUIZAKI_ELECTRON_SMOKE_LOG:-/tmp/yuizaki-electron-smoke.log}"
BACKEND_LOG="${YUIZAKI_BACKEND_SMOKE_LOG:-/tmp/yuizaki-electron-smoke-backend.log}"
BACKEND_PORT_FILE="$(mktemp "${TMPDIR:-/tmp}/yuizaki-backend-port.XXXXXX")"

[[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]] || {
	echo "[ERROR] Linux Electron smoke test requires a graphical session." >&2
	exit 1
}

PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/check_linux_environment.sh" --check

export CONTROL_SERVER_PORT
export YUIZAKI_CONTROL_TOKEN="$TOKEN"
export YUIZAKI_BACKEND_API_TOKEN="$TOKEN"
export DESKTOP_PET_SKIP_INTERNAL_PYTHON=1
export YUIZAKI_PROJECT_ROOT="$ROOT"
export YUIZAKI_ELECTRON_ROOT="$ROOT/electron"

electron_pid=""
backend_pid=""
cleanup() {
	trap - EXIT INT TERM
	if [[ -n "$electron_pid" ]]; then
		kill -TERM "$electron_pid" 2>/dev/null || true
		wait "$electron_pid" 2>/dev/null || true
	fi
	if [[ -n "$backend_pid" ]]; then
		kill -TERM "$backend_pid" 2>/dev/null || true
		wait "$backend_pid" 2>/dev/null || true
	fi
	rm -f "$BACKEND_PORT_FILE"
}
trap cleanup EXIT INT TERM

"$PYTHON_BIN" - "$BACKEND_PORT" "$BACKEND_PORT_FILE" <<'PY' >"$BACKEND_LOG" 2>&1 &
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

port = int(sys.argv[1])
port_file = sys.argv[2]

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/ping":
            payload = {"ok": True}
        elif self.path == "/health":
            payload = {"status": "degraded", "healthy": False}
        else:
            self.send_error(404)
            return
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return

server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
with open(port_file, "w", encoding="utf-8") as handle:
    handle.write(str(server.server_port))
server.serve_forever()
PY
backend_pid="$!"

for ((attempt = 0; attempt < 50; attempt++)); do
	if ! kill -0 "$backend_pid" 2>/dev/null; then
		cat "$BACKEND_LOG" >&2 || true
		echo "[ERROR] Backend smoke fixture exited before becoming ready." >&2
		exit 1
	fi
	[[ -s "$BACKEND_PORT_FILE" ]] && break
	sleep 0.1
done

if [[ ! -s "$BACKEND_PORT_FILE" ]]; then
	cat "$BACKEND_LOG" >&2 || true
	echo "[ERROR] Backend smoke fixture did not publish its port." >&2
	exit 1
fi

BACKEND_PORT="$(<"$BACKEND_PORT_FILE")"
export SERVER_HOST=127.0.0.1
export SERVER_PORT="$BACKEND_PORT"
export DESKTOP_PET_BACKEND_URL="http://127.0.0.1:$BACKEND_PORT"

if ! "$PYTHON_BIN" - "$BACKEND_PORT" <<'PY'; then
import json
import sys
import urllib.request

with urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/api/ping", timeout=3) as response:
    payload = json.load(response)
raise SystemExit(0 if payload.get("ok") is True else 1)
PY
	cat "$BACKEND_LOG" >&2 || true
	echo "[ERROR] Backend smoke fixture failed its liveness check." >&2
	exit 1
fi

(cd "$ROOT/electron" && exec node scripts/run-electron.mjs) >"$LOG_FILE" 2>&1 &
electron_pid="$!"

if ! "$PYTHON_BIN" - "$CONTROL_SERVER_PORT" "$TOKEN" <<'PY'; then
import json
import sys
import time
import urllib.error
import urllib.request

port, token = sys.argv[1:]
url = f"http://127.0.0.1:{port}/api/system/diagnostics"
deadline = time.monotonic() + 45
last_error = "control server unavailable"
while time.monotonic() < deadline:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.load(response)
        if (
            payload.get("status") == "ok"
            and payload.get("petOverlayVisible") is True
            and payload.get("petOverlayHasVisiblePixels") is True
        ):
            print(json.dumps({
                "status": payload["status"],
                "petOverlayVisible": payload["petOverlayVisible"],
                "petOverlayHasVisiblePixels": payload["petOverlayHasVisiblePixels"],
            }, separators=(",", ":")))
            raise SystemExit(0)
        last_error = f"desktop pet not visibly rendered: {payload}"
    except (OSError, urllib.error.URLError, ValueError) as error:
        last_error = str(error)
    time.sleep(1)
raise SystemExit(last_error)
PY
	cat "$LOG_FILE" >&2 || true
	cat "$BACKEND_LOG" >&2 || true
	exit 1
fi

echo "[OK] Linux Electron GUI smoke test passed."
