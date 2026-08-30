"""Capabilities shared by the browser renderer and the Electron shell.

The backend can describe protocol availability, but it must not imply that a
browser has desktop privileges. Keeping this contract server-side lets the
renderer present the same honest boundary in both deployment modes.
"""

from __future__ import annotations

from typing import Any

from .platform_capabilities import build_platform_capability_snapshot

SCHEMA_VERSION = "yuizaki.ui-capabilities.v1"


def build_ui_capabilities() -> dict[str, Any]:
    platform_snapshot = build_platform_capability_snapshot()
    browser_row = next(
        (
            row
            for row in platform_snapshot.get("platforms", [])
            if isinstance(row, dict) and row.get("id") == "browser-pwa"
        ),
        {},
    )
    browser_capabilities = browser_row.get("capabilities", {}) if isinstance(browser_row, dict) else {}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "protocol": {
            "http": True,
            "socketIo": True,
            "openapi": "/docs",
        },
        "clients": {
            "browser": {
                "mode": "browser",
                "coreRoutes": ["chat", "memory", "settings"],
                "hostCapabilities": {
                    "windowControls": False,
                    "desktopActions": False,
                    "screenCapture": False,
                    "localFilePicker": False,
                },
                "limitations": ["transparent_pet", "native_desktop_actions", "electron_process_controls"],
            },
            "electron": {
                "mode": "electron",
                "coreRoutes": ["chat", "memory", "settings"],
                "hostCapabilities": {
                    "windowControls": True,
                    "desktopActions": True,
                    "screenCapture": True,
                    "localFilePicker": True,
                },
                "limitations": [],
            },
        },
        "browserPlatform": browser_capabilities,
    }


__all__ = ["SCHEMA_VERSION", "build_ui_capabilities"]
