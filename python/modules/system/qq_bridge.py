"""Managed QQ bridge so a personal account can be connected from inside Yuizaki.

The connector layer already speaks OneBot 11 to a *local bridge process*; this
module owns that process: verified download, generated configuration, console
launch, health polling, and logout. Users no longer install and wire a bridge by
hand.

Verified upstream behaviour (Lagrange.OneBot, win-x64 self-contained):
- the executable crashes with ``IOException: invalid handle`` when stdout is a
  pipe, so it must be spawned with its own console (Windows ``CREATE_NEW_CONSOLE``);
  the ASCII QR code is drawn in that console window;
- first run writes ``appsettings.json`` next to the executable;
- ``QrCode.ConsoleCompatibilityMode`` renders a plain-text QR;
- ``Message.IgnoreSelf`` drops the account's own messages at the bridge.

Nothing here grants trust: the bridge is a third-party personal-account client.
It is downloaded at runtime (never redistributed by this project), the user must
accept the account-risk notice explicitly, and the archive hash is pinned in
``resources.lock.json``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

BRIDGE_RESOURCE_ID = "qq_bridge"
BRIDGE_VERSION = "nightly-2026-10-22"
BRIDGE_EXE = "Lagrange.OneBot.exe"
CONFIG_NAME = "appsettings.json"
SERVER_PORT_DEFAULT = 8001
PENDING = "awaiting_scan"

try:  # optional: enables inline QR and readable login failures
    from winpty import PtyProcess as _PtyProcess  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - absence is the common case
    _PtyProcess = None
CONNECTED = "connected"
_STATE_ORDER = ("not_installed", "installed", "starting", PENDING, CONNECTED, "failed", "stopped")
# Loopback probes must not inherit HTTP_PROXY/ALL_PROXY: a proxy in the
# environment would otherwise make the local bridge look offline.
_LOOPBACK_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class QqBridgeError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class BridgeConfig:
    """Everything the bridge needs, derived from the lock file and our own ports."""

    root: Path
    exe: Path
    config_path: Path
    token: str
    api_port: int
    backend_port: int
    sign_server_url: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def bridge_url(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"

    def payload(self) -> dict[str, Any]:
        return {
            "$schema": "https://raw.githubusercontent.com/LagrangeDev/Lagrange.Core/master/Lagrange.OneBot/Resources/appsettings_schema.json",
            "Logging": {
                "LogLevel": {
                    "Default": "Information",
                    "Microsoft": "Warning",
                    "Microsoft.Hosting.Lifetime": "Information",
                }
            },
            "SignServerUrl": self.sign_server_url,
            "SignProxyUrl": "",
            "MusicSignServerUrl": "",
            "Account": {
                "Uin": 0,
                "Protocol": "Linux",
                "AutoReconnect": True,
                "GetOptimumServer": True,
            },
            # The bridge drops the account's own messages, so our self_id filter is
            # a second line of defence rather than the only one.
            "Message": {"IgnoreSelf": True, "StringPost": False},
            # Plain-text QR renders in the console window we allocate.
            "QrCode": {"ConsoleCompatibilityMode": True},
            "Implementations": [
                {
                    "Type": "HttpPost",
                    "Host": "127.0.0.1",
                    "Port": self.backend_port,
                    "Suffix": "/api/system/connectors/qq/webhook",
                    "HeartBeatInterval": 5000,
                    "AccessToken": self.token,
                },
                {
                    "Type": "Http",
                    "Host": "127.0.0.1",
                    "Port": self.api_port,
                    "AccessToken": self.token,
                },
            ],
        }


class QqBridgeSupervisor:
    """Install, start, supervise, and stop the bundled personal-account bridge."""

    def __init__(
        self,
        *,
        data_dir: Path,
        resource: Mapping[str, Any],
        env: Mapping[str, str] | None = None,
        spawn: Callable[..., Any] | None = None,
        clock: Callable[[], float] = time.time,
        popen: Callable[..., Any] | None = None,
        health_probe: Callable[[], Any] | None = None,
        pty_factory: Callable[..., Any] | None = None,
        capture: bool = True,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._resource = dict(resource)
        self._env = dict(os.environ if env is None else env)
        self._spawn = spawn or subprocess.Popen
        self._clock = clock
        self._popen = popen
        self._health_probe = health_probe
        self._pty_factory = pty_factory
        self._capture_enabled = capture
        self._pty: Any | None = None
        self._pty_buffer = ""
        self._qr_text: str | None = None
        self._login_failure: str | None = None
        self._sign_server_url = str(self._env.get("YUIZAKI_QQ_SIGN_SERVER_URL", "") or "").strip()
        self._process: Any | None = None
        self._state = "not_installed"
        self._last_error: str | None = None
        self._started_at: float | None = None
        self._config: BridgeConfig | None = None
        self._state_path = self._data_dir / "qq_bridge_state.json"
        self._load_state()

    # ---------------------------------------------------------------- paths
    @property
    def version(self) -> str:
        return str(self._resource.get("version") or BRIDGE_VERSION)

    @property
    def root(self) -> Path:
        return self._data_dir / "qq-bridge" / self.version

    @property
    def exe_path(self) -> Path:
        return self.root / BRIDGE_EXE

    @property
    def state_file(self) -> Path:
        return self.root / CONFIG_NAME

    def _backend_port(self) -> int:
        raw = self._env.get("SERVER_PORT", "") or str(SERVER_PORT_DEFAULT)
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return SERVER_PORT_DEFAULT

    # ---------------------------------------------------------------- state
    def _load_state(self) -> None:
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(data, dict):
            token = str(data.get("token") or "")
            api_port = data.get("api_port")
            if token and isinstance(api_port, int):
                self._config = BridgeConfig(
                    root=self.root,
                    exe=self.exe_path,
                    config_path=self.state_file,
                    token=token,
                    api_port=api_port,
                    backend_port=self._backend_port(),
                    sign_server_url=str(data.get("sign_server_url") or ""),
                )
                self._sign_server_url = self._config.sign_server_url
            self._last_error = data.get("last_error") or None

    def _save_state(self) -> None:
        if self._config is None:
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.version,
            "token": self._config.token,
            "api_port": self._config.api_port,
            "backend_port": self._config.backend_port,
            "sign_server_url": self._config.sign_server_url,
            "last_error": self._last_error,
            "updated_at": self._clock(),
        }
        temporary = self._state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self._state_path)

    @property
    def installed(self) -> bool:
        return self.exe_path.is_file()

    def status(self) -> dict[str, Any]:
        running = self._process_alive()
        state = self._state
        account: dict[str, Any] = {}
        if not self.installed:
            state = "not_installed"
        elif running:
            info = self._login_info()
            if info is not None:
                state = CONNECTED
                account = {
                    "accountId": str(info.get("user_id") or "") or None,
                    "accountName": str(info.get("nickname") or "") or None,
                }
            else:
                # A captured login failure is more useful than an endless
                # "waiting for scan" spinner.
                failure = self._detect_failure()
                state = "failed" if failure else PENDING
        elif state in {CONNECTED, PENDING, "starting"}:
            state = "stopped"
        return {
            "id": "qq",
            "installed": self.installed,
            "state": state,
            "version": self.version,
            "running": running,
            "pid": getattr(self._process, "pid", None) if running else None,
            "apiPort": self._config.api_port if self._config else None,
            "bridgeUrl": self._config.bridge_url if self._config else "",
            "tokenConfigured": bool(self._config and self._config.token),
            "startedAt": self._started_at,
            "lastError": self._last_error,
            "installDir": str(self.root) if self.installed else "",
            "accountId": account.get("accountId"),
            "accountName": account.get("accountName"),
            "qrText": None if state == CONNECTED else self._qr_text,
            "signServerUrl": self._sign_server_url,
            "signServerConfigured": bool(self._sign_server_url),
            "captureMode": "pty" if self._pty is not None else "console",
            "loginHint": (
                "桥进程已在独立窗口启动：请用手机 QQ 扫描该窗口中的二维码。"
                if state == PENDING
                else ("桥已连接，扫码完成。" if state == CONNECTED else "")
            ),
        }

    # -------------------------------------------------------------- install
    @property
    def current_token(self) -> str:
        """Token the generated bridge config uses; empty before the first start."""
        return self._config.token if self._config is not None else ""

    def install(self, *, accept_risk: bool) -> dict[str, Any]:
        if not accept_risk:
            raise QqBridgeError(
                "qq_bridge_risk_not_accepted",
                "个人账号桥存在封号风险，必须显式确认后才能安装",
                status_code=422,
            )
        if self.installed:
            return self.status()
        sources = self._resource.get("sources") or []
        if not sources:
            raise QqBridgeError("qq_bridge_no_source", "资源锁未配置桥下载源", status_code=503)
        source = sources[0]
        url = str(source.get("url") or "")
        expected = str(source.get("sha256") or "").lower()
        if not url or not expected:
            raise QqBridgeError("qq_bridge_no_source", "资源锁缺少 url 或 sha256", status_code=503)

        archive = self.root.parent / f"{self.version}.zip"
        self.root.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._download(url, archive)
            actual = _sha256(archive)
            if actual != expected:
                archive.unlink(missing_ok=True)
                raise QqBridgeError(
                    "qq_bridge_hash_mismatch",
                    "下载产物校验失败，已丢弃",
                    status_code=502,
                )
            self._extract(archive)
        except QqBridgeError:
            raise
        except (OSError, urllib.error.URLError, zipfile.BadZipFile) as exc:
            self._last_error = str(exc)
            self._save_state()
            raise QqBridgeError("qq_bridge_install_failed", f"桥安装失败：{exc}", status_code=502) from exc
        finally:
            archive.unlink(missing_ok=True)

        if not self.installed:
            raise QqBridgeError("qq_bridge_install_incomplete", "压缩包中没有桥可执行文件", status_code=502)
        self._state = "installed"
        self._last_error = None
        self._save_state()
        return self.status()

    def _download(self, url: str, target: Path) -> None:
        temporary = target.with_suffix(".part")
        with urllib.request.urlopen(url, timeout=300) as response, temporary.open("wb") as handle:  # noqa: S310 - pinned https source
            shutil.copyfileobj(response, handle)
        temporary.replace(target)

    def _extract(self, archive: Path) -> None:
        staging = self.root.parent / f".staging-{self.version}"
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            members = [name for name in bundle.namelist() if name.lower().endswith(f"/{BRIDGE_EXE.lower()}")]
            if not members:
                raise zipfile.BadZipFile("bridge executable missing from archive")
            with bundle.open(members[0]) as source, (staging / BRIDGE_EXE).open("wb") as target:
                shutil.copyfileobj(source, target)
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)
        staging.replace(self.root)

    # ---------------------------------------------------------------- start
    def ensure_config(self, *, token: str | None = None, api_port: int | None = None) -> BridgeConfig:
        config = self._config or BridgeConfig(
            root=self.root,
            exe=self.exe_path,
            config_path=self.state_file,
            token=token or self._env.get("YUIZAKI_QQ_BRIDGE_TOKEN", "") or _random_token(),
            api_port=api_port or _free_port(),
            backend_port=self._backend_port(),
        )
        config.root = self.root
        config.exe = self.exe_path
        config.config_path = self.state_file
        config.backend_port = self._backend_port()
        if token:
            config.token = token
        if api_port:
            config.api_port = api_port
        self._config = config
        return config

    def start(self) -> dict[str, Any]:
        if not self.installed:
            raise QqBridgeError("qq_bridge_not_installed", "尚未安装桥，请先安装", status_code=409)
        if self._process_alive():
            return self.status()
        config = self.ensure_config()
        self.root.mkdir(parents=True, exist_ok=True)
        config.config_path.write_text(
            json.dumps(config.payload(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        creationflags = 0x00000010 if sys.platform == "win32" else 0  # CREATE_NEW_CONSOLE
        command = [str(config.exe)]
        config.sign_server_url = self._sign_server_url
        captured = self._start_capture(command, str(self.root))
        try:
            if not captured:
                # No pseudo console available: the bridge still needs a console,
                # so the QR is shown in its own window.
                self._process = self._spawn(command, cwd=str(self.root), creationflags=creationflags)
        except OSError as exc:
            self._state = "failed"
            self._last_error = str(exc)
            self._save_state()
            raise QqBridgeError("qq_bridge_spawn_failed", f"桥启动失败：{exc}", status_code=502) from exc
        self._state = "starting"
        self._started_at = self._clock()
        self._last_error = None
        self._save_state()
        return self.status()

    def stop(self) -> dict[str, Any]:
        self._stop_capture()
        if self._process_alive():
            try:
                self._process.terminate()
                self._process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired, AttributeError):
                try:
                    self._process.kill()
                except (OSError, AttributeError):
                    pass
        self._process = None
        self._state = "stopped"
        self._save_state()
        return self.status()

    def logout(self) -> dict[str, Any]:
        self.stop()
        for path in (self.state_file, self._state_path):
            path.unlink(missing_ok=True)
        session_dir = self.root / "data"
        if session_dir.is_dir():
            shutil.rmtree(session_dir, ignore_errors=True)
        self._config = None
        self._state = "installed"
        return self.status()

    # --------------------------------------------------------------- health
    # --------------------------------------------------------------- capture
    def _capture_supported(self) -> bool:
        if not self._capture_enabled:
            return False
        return self._pty_factory is not None or _PtyProcess is not None

    def _reader_factory(self):
        return self._pty_factory or _PtyProcess

    def _append_output(self, chunk: str) -> None:
        if not chunk:
            return
        self._pty_buffer = (self._pty_buffer + chunk)[-20000:]
        qr = extract_qr_block(self._pty_buffer)
        if qr:
            self._qr_text = qr
        failure = detect_login_failure(self._pty_buffer)
        if failure:
            self._login_failure = failure
            self._last_error = failure

    def _detect_failure(self) -> str | None:
        if self._login_failure:
            # start() clears the error field after spawning; keep the captured
            # failure visible instead of losing it to that reset.
            self._last_error = self._login_failure
            return self._login_failure
        failure = detect_login_failure(self._pty_buffer)
        if failure:
            self._login_failure = failure
            self._last_error = failure
        return failure

    def _start_capture(self, command: list[str], cwd: str) -> bool:
        """Run the bridge inside a pseudo console so its QR and errors are readable.

        Returns False when no capture backend is available; the caller then falls
        back to an ordinary console window.
        """
        if not self._capture_supported():
            return False
        factory = self._reader_factory()
        if factory is None:
            return False
        try:
            pty = factory.spawn(command[0], cwd=cwd)
        except Exception as exc:  # pragma: no cover - depends on the backend
            self._last_error = f"qq_bridge_capture_unavailable: {exc}"
            return False
        self._pty = pty
        self._pty_buffer = ""
        self._qr_text = None
        self._login_failure = None

        def pump() -> None:
            while True:
                try:
                    chunk = pty.read(4096)
                except Exception:
                    break
                if not chunk:
                    # Empty means "nothing yet" for a live pty and EOF for a dead
                    # one; never spin on it.
                    if not _pty_is_alive(pty):
                        break
                    time.sleep(0.1)
                    continue
                if isinstance(chunk, bytes):
                    chunk = chunk.decode("utf-8", "replace")
                self._append_output(str(chunk))

        thread = threading.Thread(target=pump, name="qq-bridge-capture", daemon=True)
        thread.start()
        self._pty_thread = thread
        return True

    def _stop_capture(self) -> None:
        pty, self._pty = self._pty, None
        if pty is not None:
            try:
                pty.terminate(force=True)
            except Exception:
                pass

    def set_sign_server(self, url: str) -> dict[str, Any]:
        """Configure the sign server this protocol version requires."""
        cleaned = str(url or "").strip()
        if cleaned and not re.match(r"^https?://", cleaned):
            raise QqBridgeError("qq_bridge_invalid_sign_server", "签名服务地址必须以 http(s):// 开头", status_code=422)
        self._sign_server_url = cleaned
        config = self.ensure_config() if self.installed else self._config
        if config is not None:
            config.sign_server_url = cleaned
            self._save_state()
        return self.status()

    def _process_alive(self) -> bool:
        if self._pty is not None:
            try:
                return bool(self._pty.isalive())
            except Exception:
                return False
        if self._process is None:
            return False
        poll = getattr(self._process, "poll", None)
        if poll is None:
            return True
        return poll() is None

    def _login_info(self) -> dict[str, Any] | None:
        """Return the logged-in account, or ``None`` while the API is not ready.

        ``get_login_info`` only answers after a successful login, so it doubles as
        the readiness probe and as the source of the account identity shown in the
        UI.
        """
        if self._health_probe is not None:
            probed = self._health_probe()
            if isinstance(probed, dict):
                return probed
            return {} if probed else None
        if self._config is None:
            return None
        url = f"{self._config.bridge_url}/get_login_info"
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {self._config.token}"},
        )
        try:
            # Never route a loopback probe through an environment proxy.
            with _LOOPBACK_OPENER.open(request, timeout=2) as response:  # noqa: S310 - loopback only
                payload = json.loads(response.read().decode("utf-8", "replace") or "{}")
        except (urllib.error.URLError, OSError, ValueError):
            return None
        if str(payload.get("status")) != "ok" and payload.get("retcode") != 0:
            return None
        data = payload.get("data")
        return dict(data) if isinstance(data, dict) else {}

    def _api_healthy(self) -> bool:
        return self._login_info() is not None


_ANSI = re.compile(r"\[[0-9;?]*[a-zA-Z]")
_BLOCK_CHARS = "█▀▄▌▐░▒▓"


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def extract_qr_block(text: str, *, max_lines: int = 80) -> str | None:
    """Return the QR rendering from captured console output, if present.

    Lagrange draws the code with block characters; with
    ``ConsoleCompatibilityMode`` it uses dense ASCII instead. The block is the
    longest run of consecutive dense lines.
    """
    clean = strip_ansi(text)
    lines = clean.splitlines()[-max_lines:]
    best: list[str] = []
    current: list[str] = []
    for line in lines:
        dense = sum(1 for char in line if char in _BLOCK_CHARS or char in "#@")
        wide = len(line.strip()) >= 8
        if wide and dense >= 2:
            current.append(line.rstrip())
        else:
            if len(current) > len(best):
                best = current
            current = []
    if len(current) > len(best):
        best = current
    if len(best) < 6:
        return None
    return chr(10).join(best)


def detect_login_failure(text: str) -> str | None:
    """Map known bridge login failures to stable codes."""
    clean = strip_ansi(text)
    if "Signer server returned" in clean or "signer server" in clean.lower():
        return "qq_bridge_signer_unavailable"
    if "All login failed" in clean:
        return "qq_bridge_login_failed"
    if "Address already in use" in clean:
        return "qq_bridge_port_in_use"
    return None


def _pty_is_alive(pty: Any) -> bool:
    try:
        return bool(pty.isalive())
    except Exception:
        return False


def _random_token() -> str:
    import secrets

    return secrets.token_urlsafe(24)


def load_bridge_resource(lock_path: Path) -> dict[str, Any]:
    """Return the ``qq_bridge`` resource entry, or an empty mapping."""
    try:
        payload = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    resources = payload.get("resources") if isinstance(payload, dict) else None
    if not isinstance(resources, dict):
        return {}
    entry = resources.get(BRIDGE_RESOURCE_ID)
    return dict(entry) if isinstance(entry, dict) else {}
