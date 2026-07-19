#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(dirname "$0")"
ROOT="$(cd "$SCRIPT_DIR" && pwd)"
SERVICE_DIR="$ROOT/services/soulx-svc"
PYTHON="${PYTHON_BIN:-$ROOT/python/.venv/bin/python}"
REFERENCE="${1:-}"

[[ -f "$SERVICE_DIR/docker-compose.yml" ]] || {
	echo "[ERROR] SoulX compose file is missing." >&2
	exit 1
}
[[ -x "$PYTHON" ]] || {
	echo "[ERROR] Python venv is missing: $PYTHON" >&2
	exit 1
}
command -v docker >/dev/null 2>&1 || {
	echo "[ERROR] Docker is not installed." >&2
	exit 1
}
docker info >/dev/null 2>&1 || {
	echo "[ERROR] Docker daemon is not running." >&2
	exit 1
}
docker compose version >/dev/null 2>&1 || {
	echo "[ERROR] Docker Compose v2 is required." >&2
	exit 1
}

if [[ "$REFERENCE" == "--check" ]]; then
	echo "[OK] Docker, Compose, Python venv, and SoulX service files are available."
	exit 0
fi

if [[ -n "$REFERENCE" ]]; then
	[[ -f "$REFERENCE" ]] || {
		echo "[ERROR] Reference audio not found: $REFERENCE" >&2
		exit 1
	}
	extension="${REFERENCE##*.}"
	extension="${extension,,}"
	case "$extension" in wav | mp3 | flac | m4a) ;; *)
		echo "[ERROR] Reference audio must be wav, mp3, flac, or m4a." >&2
		exit 1
		;;
	esac
	mkdir -p "$SERVICE_DIR/references"
	cp -- "$REFERENCE" "$SERVICE_DIR/references/0.$extension"
fi

if ! find "$SERVICE_DIR/references" -maxdepth 2 -type f \( -name '0.wav' -o -name '0.mp3' -o -name '0.flac' -o -name '0.m4a' -o -name 'prompt.wav' -o -name 'reference.wav' \) -print -quit | grep -q .; then
	echo "[ERROR] SoulX requires reference audio. Pass a file path as the first argument." >&2
	exit 1
fi

if [[ ! -f "$SERVICE_DIR/models/SoulX-Singer/model-svc.pt" && ! -f "$SERVICE_DIR/models/SoulX-Singer/model.pt" ]] || [[ ! -d "$SERVICE_DIR/models/SoulX-Singer-Preprocess" ]]; then
	"$PYTHON" -m pip install 'huggingface_hub>=0.23'
	"$PYTHON" "$SERVICE_DIR/download_models.py"
fi

exec docker compose -f "$SERVICE_DIR/docker-compose.yml" up --build
