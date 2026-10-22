from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

import pytest

import modules.system.qq_bridge as qq_bridge
from modules.system.message_connectors import MessageConnectorRegistry
from modules.system.qq_bridge import (
    BRIDGE_EXE,
    QqBridgeError,
    QqBridgeSupervisor,
    load_bridge_resource,
)

RESOURCE = {
    "label": "test bridge",
    "version": "test-1",
    "sources": [{"url": "https://example.invalid/bridge.zip", "sha256": "0" * 64}],
}


class FakeProcess:
    def __init__(self) -> None:
        self.pid = 4242
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None) -> int:
        return self.returncode or 0


def _build_zip(path: Path, *, include_exe: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as bundle:
        if include_exe:
            bundle.writestr(f"publish/{BRIDGE_EXE}", b"MZ fake executable")


def _supervisor(tmp_path: Path, *, spawn=None, env=None, health=None) -> QqBridgeSupervisor:
    return QqBridgeSupervisor(
        data_dir=tmp_path,
        resource=RESOURCE,
        env=env or {"SERVER_PORT": "8001"},
        spawn=spawn or (lambda *a, **k: FakeProcess()),
        # Tests never touch a real port or a real pseudo console; the capture
        # cases inject a fake pty explicitly.
        health_probe=health or (lambda: False),
        capture=False,
    )


def _install_without_network(supervisor: QqBridgeSupervisor, tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "bridge.zip"
    _build_zip(archive)
    monkeypatch.setattr(qq_bridge, "_sha256", lambda path: "0" * 64, raising=False)

    def fake_download(url: str, target: Path) -> None:
        target.write_bytes(archive.read_bytes())

    monkeypatch.setattr(supervisor, "_download", fake_download)
    supervisor.install(accept_risk=True)


def test_install_requires_explicit_risk_acceptance(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path)
    with pytest.raises(QqBridgeError) as excinfo:
        supervisor.install(accept_risk=False)
    assert excinfo.value.code == "qq_bridge_risk_not_accepted"
    assert excinfo.value.status_code == 422
    assert supervisor.status()["state"] == "not_installed"


def test_install_verifies_hash_and_rejects_mismatch(tmp_path: Path, monkeypatch) -> None:
    supervisor = _supervisor(tmp_path)

    def fake_download(url: str, target: Path) -> None:
        target.write_bytes(b"not the pinned archive")

    monkeypatch.setattr(supervisor, "_download", fake_download)
    with pytest.raises(QqBridgeError) as excinfo:
        supervisor.install(accept_risk=True)
    assert excinfo.value.code == "qq_bridge_hash_mismatch"
    assert not supervisor.installed
    # The rejected archive must not be left behind.
    assert not list((tmp_path / "qq-bridge").glob("*.zip"))


def test_install_extracts_only_the_executable(tmp_path: Path, monkeypatch) -> None:
    supervisor = _supervisor(tmp_path)
    _install_without_network(supervisor, tmp_path, monkeypatch)
    assert supervisor.installed
    files = sorted(p.name for p in supervisor.root.iterdir())
    assert files == [BRIDGE_EXE], "only the executable may be unpacked"
    assert supervisor.status()["state"] == "installed"


def test_install_reports_incomplete_archive(tmp_path: Path, monkeypatch) -> None:
    supervisor = _supervisor(tmp_path)
    archive = tmp_path / "empty.zip"
    _build_zip(archive, include_exe=False)
    monkeypatch.setattr(qq_bridge, "_sha256", lambda path: "0" * 64, raising=False)

    def fake_download(url: str, target: Path) -> None:
        target.write_bytes(archive.read_bytes())

    monkeypatch.setattr(supervisor, "_download", fake_download)
    with pytest.raises(QqBridgeError):
        supervisor.install(accept_risk=True)


def test_start_writes_onebot_config_with_both_implementations(tmp_path: Path, monkeypatch) -> None:
    supervisor = _supervisor(tmp_path)
    _install_without_network(supervisor, tmp_path, monkeypatch)

    status = supervisor.start()
    # The process is up, but the OneBot API only answers after login.
    assert status["state"] == "awaiting_scan"
    assert status["running"] is True

    config = json.loads((supervisor.root / "appsettings.json").read_text(encoding="utf-8"))
    assert config["Account"]["Uin"] == 0, "zero means QR-code login"
    assert config["Message"]["IgnoreSelf"] is True
    assert config["QrCode"]["ConsoleCompatibilityMode"] is True

    implementations = {item["Type"]: item for item in config["Implementations"]}
    assert set(implementations) == {"HttpPost", "Http"}
    assert implementations["HttpPost"]["Port"] == 8001
    assert implementations["HttpPost"]["Suffix"] == "/api/system/connectors/qq/webhook"
    assert implementations["Http"]["Port"] == status["apiPort"]
    token = implementations["Http"]["AccessToken"]
    assert token and token == implementations["HttpPost"]["AccessToken"]
    assert status["bridgeUrl"] == f"http://127.0.0.1:{status['apiPort']}"
    assert supervisor.current_token == token


def test_start_is_idempotent_and_stop_clears_process(tmp_path: Path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def spawn(argv, **kwargs):
        calls.append(list(argv))
        return FakeProcess()

    supervisor = _supervisor(tmp_path, spawn=spawn)
    _install_without_network(supervisor, tmp_path, monkeypatch)
    supervisor.start()
    second = supervisor.start()
    assert second["running"] is True
    assert len(calls) == 1, "a running bridge must not be spawned twice"

    stopped = supervisor.stop()
    assert stopped["running"] is False
    assert stopped["state"] == "stopped"


def test_start_without_install_is_rejected(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path)
    with pytest.raises(QqBridgeError) as excinfo:
        supervisor.start()
    assert excinfo.value.code == "qq_bridge_not_installed"


def test_token_survives_restart_through_state_file(tmp_path: Path, monkeypatch) -> None:
    supervisor = _supervisor(tmp_path)
    _install_without_network(supervisor, tmp_path, monkeypatch)
    first = supervisor.start()
    token = supervisor.current_token

    reopened = _supervisor(tmp_path)
    assert reopened.current_token == token, "the bridge token must be readable after a restart"
    assert reopened.ensure_config().api_port == first["apiPort"]
    assert reopened.status()["tokenConfigured"] is True


def test_logout_removes_config_and_session_state(tmp_path: Path, monkeypatch) -> None:
    supervisor = _supervisor(tmp_path)
    _install_without_network(supervisor, tmp_path, monkeypatch)
    supervisor.start()
    session_dir = supervisor.root / "data"
    session_dir.mkdir()
    (session_dir / "keystore.json").write_text("{}", encoding="utf-8")

    supervisor.logout()
    assert not (supervisor.root / "appsettings.json").exists()
    assert not session_dir.exists()
    assert supervisor.current_token == ""
    assert supervisor.installed, "logging out must not delete the binary"


def test_status_reports_not_installed_without_binary(tmp_path: Path) -> None:
    status = _supervisor(tmp_path).status()
    assert status["state"] == "not_installed"
    assert status["installed"] is False
    assert status["bridgeUrl"] == ""


def test_status_reports_connected_when_onebot_api_answers(tmp_path: Path, monkeypatch) -> None:
    supervisor = _supervisor(tmp_path, health=lambda: True)
    _install_without_network(supervisor, tmp_path, monkeypatch)
    status = supervisor.start()
    assert status["state"] == "connected"
    assert "扫码完成" in status["loginHint"]


def test_status_exposes_the_logged_in_account(tmp_path: Path, monkeypatch) -> None:
    """After the scan the card should show who signed in, not just "connected"."""
    supervisor = _supervisor(
        tmp_path,
        health=lambda: {"user_id": 10086, "nickname": "小号"},
    )
    _install_without_network(supervisor, tmp_path, monkeypatch)
    status = supervisor.start()
    assert status["state"] == "connected"
    assert status["accountId"] == "10086"
    assert status["accountName"] == "小号"


def test_status_has_no_account_before_login(tmp_path: Path, monkeypatch) -> None:
    supervisor = _supervisor(tmp_path, health=lambda: False)
    _install_without_network(supervisor, tmp_path, monkeypatch)
    status = supervisor.start()
    assert status["state"] == "awaiting_scan"
    assert status["accountId"] is None
    assert status["accountName"] is None


def test_status_returns_to_stopped_when_process_exits(tmp_path: Path, monkeypatch) -> None:
    process = FakeProcess()
    supervisor = _supervisor(tmp_path, spawn=lambda *a, **k: process)
    _install_without_network(supervisor, tmp_path, monkeypatch)
    supervisor.start()
    assert supervisor.status()["running"] is True
    process.returncode = 1  # crashed
    status = supervisor.status()
    assert status["running"] is False
    assert status["state"] == "stopped"


class FakePty:
    """Stand-in for winpty.PtyProcess that replays canned console output."""

    def __init__(self, chunks: list[str]) -> None:
        self._chunks = list(chunks)
        self.terminated = False

    def read(self, _size: int) -> str:
        return self._chunks.pop(0) if self._chunks else ""

    def isalive(self) -> bool:
        return not self.terminated

    def terminate(self, force: bool = False) -> None:
        self.terminated = True


class FakePtyFactory:
    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks
        self.spawned: list[tuple[str, str]] = []

    def spawn(self, command: str, cwd: str = ".") -> FakePty:
        self.spawned.append((command, cwd))
        return FakePty(self._chunks)


def _capturing_supervisor(tmp_path: Path, chunks: list[str]) -> tuple[QqBridgeSupervisor, FakePtyFactory]:
    factory = FakePtyFactory(chunks)
    supervisor = QqBridgeSupervisor(
        data_dir=tmp_path,
        resource=RESOURCE,
        env={"SERVER_PORT": "8001"},
        spawn=lambda *a, **k: FakeProcess(),
        health_probe=lambda: False,
        pty_factory=factory,
    )
    return supervisor, factory


def test_pty_capture_exposes_the_qr_and_switches_mode(tmp_path: Path, monkeypatch) -> None:
    rows = chr(10).join(["██  ████ ██"] * 12)
    supervisor, factory = _capturing_supervisor(tmp_path, [f"info: waiting" + chr(10) + rows + chr(10)])
    _install_without_network(supervisor, tmp_path, monkeypatch)

    status = supervisor.start()
    time.sleep(0.2)  # let the reader thread drain the fake stream
    status = supervisor.status()

    assert factory.spawned, "the bridge must run inside the pseudo console"
    assert status["captureMode"] == "pty"
    assert status["qrText"] and "██" in status["qrText"]
    assert status["state"] == "awaiting_scan"


def test_captured_signer_failure_becomes_a_failed_state(tmp_path: Path, monkeypatch) -> None:
    supervisor, _ = _capturing_supervisor(
        tmp_path,
        ["info: connecting" + chr(10), "System.Exception: Signer server returned a NotFound" + chr(10)],
    )
    _install_without_network(supervisor, tmp_path, monkeypatch)
    supervisor.start()
    time.sleep(0.2)

    status = supervisor.status()
    assert status["state"] == "failed"
    assert status["lastError"] == "qq_bridge_signer_unavailable"


def test_sign_server_is_generated_into_the_config_and_persisted(tmp_path: Path, monkeypatch) -> None:
    supervisor = _supervisor(tmp_path)
    _install_without_network(supervisor, tmp_path, monkeypatch)
    supervisor.set_sign_server("https://sign.example.org/api/sign")
    status = supervisor.start()

    config = json.loads((supervisor.root / "appsettings.json").read_text(encoding="utf-8"))
    assert config["SignServerUrl"] == "https://sign.example.org/api/sign"
    assert status["signServerConfigured"] is True

    reopened = _supervisor(tmp_path)
    assert reopened.status()["signServerUrl"] == "https://sign.example.org/api/sign"


def test_sign_server_rejects_a_bare_host(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path)
    with pytest.raises(QqBridgeError) as excinfo:
        supervisor.set_sign_server("sign.example.org")
    assert excinfo.value.code == "qq_bridge_invalid_sign_server"


def test_stop_terminates_the_captured_process(tmp_path: Path, monkeypatch) -> None:
    supervisor, factory = _capturing_supervisor(tmp_path, ["info: idle" + chr(10)])
    _install_without_network(supervisor, tmp_path, monkeypatch)
    supervisor.start()
    supervisor.stop()
    assert supervisor.status()["running"] is False
    assert supervisor.status()["captureMode"] == "console"


def test_load_bridge_resource_reads_lock(tmp_path: Path) -> None:
    lock = tmp_path / "resources.lock.json"
    lock.write_text(json.dumps({"resources": {"qq_bridge": {"version": "x"}}}), encoding="utf-8")
    assert load_bridge_resource(lock) == {"version": "x"}
    assert load_bridge_resource(tmp_path / "missing.json") == {}


def test_webhook_accepts_onebot_access_token_query(tmp_path: Path) -> None:
    """OneBot 11 bridges often pass the token as a query parameter."""
    registry = MessageConnectorRegistry(state_path=tmp_path / "connectors.json")
    registry.update_config("qq", {
        "accountMode": "personal_bridge",
        "bridgeUrl": "http://127.0.0.1:5701",
        "bridgeProtocol": "onebot11",
        "bridgeToken": "s3cret-token",
        "enabled": True,
    })
    assert registry.verify_request("qq", {}, b"", {"access_token": "s3cret-token"}) is True
    assert registry.verify_request("qq", {}, b"", {"access_token": "wrong"}) is False
    assert registry.verify_request("qq", {}, b"", {}) is False
    assert registry.verify_request("qq", {"Authorization": "Bearer s3cret-token"}, b"", {}) is True
