#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(dirname "$0")"
ROOT="$(cd "$SCRIPT_DIR" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

for command in node npm "$PYTHON_BIN"; do
	command -v "$command" >/dev/null 2>&1 || {
		echo "[ERROR] Command not found: $command" >&2
		exit 1
	}
done

node -e "const [major, minor] = process.versions.node.split('.').map(Number); if (major < 22 || (major === 22 && minor < 13)) { console.error('[ERROR] Node.js 22.13+ is required. Current: ' + process.versions.node); process.exit(1) }"

echo "[1/3] Installing Electron dependencies..."
(cd "$ROOT/electron" && npm ci)

echo "[2/3] Installing node-mcp dependencies..."
(cd "$ROOT/node-mcp" && npm ci)

echo "[3/3] Creating Python venv and installing runtime dependencies..."
if [[ ! -x "$ROOT/python/.venv/bin/python" ]]; then
	"$PYTHON_BIN" -m venv "$ROOT/python/.venv"
fi
PYTHON="$ROOT/python/.venv/bin/python"
"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install -r "$ROOT/python/requirements.txt"

if [[ ! -f "$ROOT/python/.env" ]]; then
	cp "$ROOT/python/.env.example" "$ROOT/python/.env"
	echo "[INFO] Created python/.env from .env.example"
fi

echo "[OK] Full setup finished."
echo "[NEXT] Edit python/.env and set the required model credentials."
