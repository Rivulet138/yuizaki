#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(dirname "$0")"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MODE="${1:---check}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

fail() {
	echo "[ERROR] $1" >&2
	exit 1
}

warn() {
	echo "[WARN] $1" >&2
}

case "$MODE" in
--install | --check | --launch) ;;
*) fail "Unknown Linux environment check mode: $MODE" ;;
esac

[[ "$(uname -s)" == "Linux" ]] || fail "Linux runtime required."

for command in node npm "$PYTHON_BIN"; do
	command -v "$command" >/dev/null 2>&1 || fail "Command not found: $command"
done

node -e "const [major, minor] = process.versions.node.split('.').map(Number); if (major < 22 || (major === 22 && minor < 13)) process.exit(1)" ||
	fail "Node.js 22.13+ is required. Current: $(node -p 'process.versions.node')"
"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' ||
	fail "Python 3.12+ is required. Current: $("$PYTHON_BIN" --version 2>&1)"

case "$(uname -m)" in
x86_64 | amd64) hook_arch="x64" ;;
aarch64 | arm64) hook_arch="arm64" ;;
loongarch64) hook_arch="loong64" ;;
*)
	hook_arch=""
	warn "This architecture has not completed the release test matrix: $(uname -m)"
	;;
esac

if [[ "$MODE" != "--install" ]]; then
	ELECTRON_BIN="$ROOT/electron/node_modules/electron/dist/electron"
	[[ -x "$ELECTRON_BIN" ]] || fail "Electron runtime missing. Run ./install_core.sh or ./install_full.sh."
	CHROME_SANDBOX="$ROOT/electron/node_modules/electron/dist/chrome-sandbox"
	user_namespace_enabled=0
	if command -v unshare >/dev/null 2>&1; then
		if unshare --user --map-root-user true >/dev/null 2>&1; then
			user_namespace_enabled=1
		fi
	elif [[ "$(cat /proc/sys/kernel/unprivileged_userns_clone 2>/dev/null || echo 0)" == "1" ]]; then
		user_namespace_enabled=1
		warn "The current user's namespace access could not be exercised because unshare is unavailable."
	fi
	if [[ "$user_namespace_enabled" != "1" ]]; then
		[[ -f "$CHROME_SANDBOX" ]] || fail "Electron sandbox helper is missing. Reinstall the Electron runtime."
		sandbox_owner="$(stat -c '%u' "$CHROME_SANDBOX" 2>/dev/null || echo -1)"
		sandbox_mode="$(stat -c '%a' "$CHROME_SANDBOX" 2>/dev/null || echo 0)"
		[[ "$sandbox_owner" == "0" && "$sandbox_mode" == "4755" ]] ||
			fail "Linux user namespaces are disabled and chrome-sandbox is not owned by root with mode 4755."
	fi

	if command -v ldd >/dev/null 2>&1; then
		missing_libraries="$(ldd "$ELECTRON_BIN" 2>/dev/null | awk '/not found/ { print $1 }')"
		[[ -z "$missing_libraries" ]] || fail "Electron shared libraries missing: $(echo "$missing_libraries" | tr '\n' ' ')"
	fi

	if [[ -n "$hook_arch" ]]; then
		HOOK_BIN="$ROOT/electron/node_modules/uiohook-napi/prebuilds/linux-$hook_arch/uiohook-napi.node"
		[[ -f "$HOOK_BIN" ]] || fail "Global input runtime is unavailable for linux-$hook_arch."
		if command -v ldd >/dev/null 2>&1; then
			missing_hook_libraries="$(ldd "$HOOK_BIN" 2>/dev/null | awk '/not found/ { print $1 }')"
			[[ -z "$missing_hook_libraries" ]] || fail "Global input shared libraries missing: $(echo "$missing_hook_libraries" | tr '\n' ' ')"
		fi
	fi
fi

if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
	if [[ "$MODE" == "--launch" ]]; then
		fail "No graphical session detected. Set DISPLAY or WAYLAND_DISPLAY."
	fi
	warn "No graphical session detected; GUI launch was not tested."
elif ! (
	cd "$ROOT/electron"
	node -e "require('uiohook-napi')"
) >/dev/null 2>&1; then
	fail "Global input runtime failed to initialize in the current graphical session."
fi

if [[ -n "${WAYLAND_DISPLAY:-}" ]]; then
	[[ -n "${XDG_RUNTIME_DIR:-}" ]] || warn "XDG_RUNTIME_DIR is unset; PipeWire portal capture may be unavailable."
	command -v systemctl >/dev/null 2>&1 &&
		systemctl --user is-active --quiet pipewire 2>/dev/null ||
		warn "PipeWire user service is not active or could not be inspected."
fi

echo "[OK] Linux environment check passed ($MODE)."
