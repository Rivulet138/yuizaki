from __future__ import annotations

from modules.system.ui_capabilities import SCHEMA_VERSION, build_ui_capabilities


def test_ui_capabilities_exposes_browser_safe_contract() -> None:
    payload = build_ui_capabilities()

    assert payload["schemaVersion"] == SCHEMA_VERSION
    assert payload["protocol"] == {
        "http": True,
        "socketIo": True,
        "openapi": "/docs",
    }
    browser = payload["clients"]["browser"]
    assert browser["mode"] == "browser"
    assert browser["hostCapabilities"] == {
        "windowControls": False,
        "desktopActions": False,
        "screenCapture": False,
        "localFilePicker": False,
    }
    assert "native_desktop_actions" in browser["limitations"]


def test_ui_capabilities_reuses_browser_platform_evidence() -> None:
    payload = build_ui_capabilities()
    browser_platform = payload["browserPlatform"]

    assert browser_platform["native_actions"]["status"] == "unsupported"
    assert browser_platform["native_actions"]["evidence"] == "platform_boundary"
