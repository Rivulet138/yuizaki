from __future__ import annotations

import json
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
from modules.system.platform_capabilities import build_platform_capability_snapshot

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "platform_capability_matrix.json"


@pytest.mark.parametrize(
    "case",
    json.loads(FIXTURE_PATH.read_text(encoding="utf-8")),
    ids=lambda case: f"{case['system']}-{case['environment'].get('DISPLAY') or case['environment'].get('WAYLAND_DISPLAY') or 'headless'}",
)
def test_platform_matrix_fixture_preserves_claim_boundary(monkeypatch, case: dict[str, object]) -> None:
    monkeypatch.setattr("platform.system", lambda: case["system"])
    environment = case["environment"]
    assert isinstance(environment, dict)
    for key in ("DISPLAY", "WAYLAND_DISPLAY"):
        value = environment.get(key)
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, str(value))

    snapshot = build_platform_capability_snapshot()
    host = str(case["host"])
    platform_row = next(item for item in snapshot["platforms"] if item["id"] == host)
    expected = case["expected"]
    assert isinstance(expected, dict)
    assert platform_row["host"] is True
    assert platform_row["capabilities"]["desktop"]["status"] == expected["desktop"]
    assert platform_row["capabilities"]["desktop"]["evidence"] == expected["desktop_evidence"]
    assert platform_row["capabilities"]["native_actions"]["status"] == expected["native_actions"]
    assert platform_row["capabilities"]["native_actions"]["evidence"] == expected["native_evidence"]
    assert platform_row["capabilities"]["text_voice"]["status"] == expected["text_voice"]
    assert platform_row["capabilities"]["text_voice"]["evidence"] == expected["text_voice_evidence"]


def test_platform_matrix_is_versioned_and_has_explicit_status_boundary() -> None:
    snapshot = build_platform_capability_snapshot()

    assert snapshot["schemaVersion"] == 1
    assert {item["id"] for item in snapshot["platforms"]} == {
        "windows",
        "linux",
        "macos",
        "browser-pwa",
    }
    assert set(snapshot["statusLegend"]) == {
        "available",
        "needs_config",
        "experimental",
        "planned",
        "unsupported",
    }
    browser = next(item for item in snapshot["platforms"] if item["id"] == "browser-pwa")
    assert browser["capabilities"]["native_actions"]["status"] == "unsupported"
    assert browser["capabilities"]["native_actions"]["evidence"] == "platform_boundary"


def test_linux_display_probe_does_not_claim_native_actions_without_display(monkeypatch) -> None:
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    snapshot = build_platform_capability_snapshot()
    linux = next(item for item in snapshot["platforms"] if item["id"] == "linux")
    assert linux["host"] is True
    assert linux["capabilities"]["desktop"]["status"] == "needs_config"
    assert linux["capabilities"]["native_actions"]["status"] == "needs_config"


def test_wayland_probe_reports_socket_evidence_without_upgrading_native_actions(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))

    snapshot = build_platform_capability_snapshot()
    linux = next(item for item in snapshot["platforms"] if item["id"] == "linux")
    assert linux["capabilities"]["native_actions"]["status"] == "experimental"
    assert snapshot["host"]["wayland"] == {
        "displayConfigured": True,
        "socketPresent": False,
        "probe": "not_detected",
    }

    socket_path = tmp_path / "wayland-0"
    socket_path.touch()
    snapshot = build_platform_capability_snapshot()
    assert snapshot["host"]["wayland"]["socketPresent"] is False


def test_wayland_probe_detects_unix_socket(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(
        "modules.system.platform_capabilities.os.stat",
        lambda _path: SimpleNamespace(st_mode=stat.S_IFSOCK),
    )
    snapshot = build_platform_capability_snapshot()
    assert snapshot["host"]["wayland"]["socketPresent"] is True
    linux = next(item for item in snapshot["platforms"] if item["id"] == "linux")
    assert "检测到 Wayland compositor socket" in linux["capabilities"]["native_actions"]["detail"]


def test_windows_runtime_contract_is_not_used_for_other_hosts(monkeypatch) -> None:
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    snapshot = build_platform_capability_snapshot()
    windows = next(item for item in snapshot["platforms"] if item["id"] == "windows")
    assert windows["host"] is False
    assert windows["capabilities"]["native_actions"]["status"] == "experimental"
    assert windows["capabilities"]["native_actions"]["evidence"] == "implementation_contract"


def test_implementation_presence_never_claims_host_qualification(monkeypatch) -> None:
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    snapshot = build_platform_capability_snapshot()
    for platform_id in ("windows", "linux"):
        platform_row = next(item for item in snapshot["platforms"] if item["id"] == platform_id)
        for capability in ("desktop", "native_actions", "text_voice"):
            assert platform_row["capabilities"][capability]["status"] != "available"

    windows = next(item for item in snapshot["platforms"] if item["id"] == "windows")
    assert windows["capabilities"]["desktop"]["evidence"] == "host_probe"
    assert windows["capabilities"]["native_actions"]["evidence"] == "implementation_contract"
    assert windows["capabilities"]["text_voice"]["evidence"] == "provider_device_qualification"
