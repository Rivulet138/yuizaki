#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(dirname "$0")"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
CONTROL_SERVER_PORT="${CONTROL_SERVER_PORT:-38949}"
TOKEN="${YUIZAKI_CONTROL_TOKEN:-linux-smoke-token}"
LOG_FILE="${YUIZAKI_ELECTRON_SMOKE_LOG:-/tmp/yuizaki-electron-smoke.log}"

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
cleanup() {
	trap - EXIT INT TERM
	if [[ -n "$electron_pid" ]]; then
		kill -TERM "$electron_pid" 2>/dev/null || true
		wait "$electron_pid" 2>/dev/null || true
	fi
}
trap cleanup EXIT INT TERM

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
	exit 1
fi

echo "[OK] Linux Electron GUI smoke test passed."
