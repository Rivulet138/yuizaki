#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(dirname "$0")"
ROOT="$(cd "$SCRIPT_DIR" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/check_linux_environment.sh" --install

echo "[1/3] Installing Electron dependencies..."
(cd "$ROOT/electron" && npm ci && npm run install:runtime)

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
