"""Evidence-backed platform capability matrix for the local status page.

This module only reports capabilities that can be inferred from the current
host/runtime.  It does not initialize a renderer, open a device, or claim a
third-party integration is supported merely because a UI entry exists.
"""

from __future__ import annotations

import os
import platform
import stat
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _status(value: str, detail: str, evidence: str) -> dict[str, str]:
    return {"status": value, "detail": detail, "evidence": evidence}


def _wayland_socket_present(display: str | None) -> bool:
    """Check only for the local compositor socket; never open or probe it."""

    if not display:
        return False
    socket_path = display
    if not os.path.isabs(socket_path):
        runtime_dir = os.getenv("XDG_RUNTIME_DIR")
        if not runtime_dir:
            return False
        socket_path = os.path.join(runtime_dir, socket_path)
    try:
        return stat.S_ISSOCK(os.stat(socket_path).st_mode)
    except OSError:
        return False


def build_platform_capability_snapshot() -> dict[str, Any]:
    """Return a stable matrix for the current host without side effects."""

    system = platform.system().lower()
    is_windows = system == "windows"
    is_linux = system == "linux"
    is_macos = system == "darwin"
    has_display = bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))
    display_server = "wayland" if os.getenv("WAYLAND_DISPLAY") else "x11" if os.getenv("DISPLAY") else "unknown"
    wayland_socket_present = _wayland_socket_present(os.getenv("WAYLAND_DISPLAY"))

    if is_windows:
        desktop_status = _status(
            "experimental",
            "检测到 Windows 主机；Electron 桌面运行和安装资格尚未由本快照验证",
            "host_probe",
        )
        native_action = _status(
            "experimental",
            "user32 桌面动作适配器实现存在；动作、权限和桌面会话尚未资格验证",
            "implementation_contract",
        )
    elif is_linux:
        desktop_status = _status(
            "experimental" if has_display else "needs_config",
            "检测到 Linux 图形会话；Electron 桌面运行和发行资格尚未验证"
            if has_display
            else "未检测到 DISPLAY/WAYLAND_DISPLAY",
            "display_environment",
        )
        native_action = _status(
            "experimental" if display_server in {"wayland", "x11"} else "needs_config",
            (
                "检测到 Wayland compositor socket，但原生桌面动作仍需 compositor 验证"
                if wayland_socket_present
                else "未检测到 Wayland compositor socket，原生桌面动作仍需验证"
            )
            if display_server == "wayland"
            else "检测到 X11 会话；桌面动作适配器实现存在但尚未执行资格验证"
            if display_server == "x11"
            else "需要图形会话",
            "display_environment",
        )
    elif is_macos:
        desktop_status = _status("experimental", "Electron 桌面壳可运行，原生桌面动作尚未完成验收", "declared_contract")
        native_action = _status("planned", "macOS 原生动作适配器尚未验收", "roadmap")
    else:
        desktop_status = _status("experimental", f"未识别的宿主系统：{system or 'unknown'}", "runtime_probe")
        native_action = _status("planned", "未识别宿主系统的原生动作适配器尚未验收", "roadmap")

    platforms = [
        {
            "id": "windows",
            "name": "Windows",
            "host": is_windows,
            "capabilities": {
                "desktop": desktop_status if is_windows else _status("experimental", "Windows 发行目标已声明，仍需在 Windows 主机验收", "release_contract"),
                "live2d_vrm": _status("available", "Electron 渲染器支持 Live2D/VRM 资源", "runtime_contract"),
                "text_voice": _status("needs_config", "文字链路实现存在；ASR/LLM/TTS Provider 和音频设备尚未资格验证", "provider_device_qualification"),
                "native_actions": native_action if is_windows else _status("experimental", "Windows user32 适配器实现存在，仍需宿主动作和权限验收", "implementation_contract"),
            },
        },
        {
            "id": "linux",
            "name": "Linux",
            "host": is_linux,
            "capabilities": {
                "desktop": desktop_status if is_linux else _status("experimental", "Linux 发行目标已声明，仍需在 Linux 图形会话验收", "release_contract"),
                "live2d_vrm": _status("available", "Electron 渲染器支持 Live2D/VRM 资源", "runtime_contract"),
                "text_voice": _status("needs_config", "文字链路实现存在；ASR/LLM/TTS Provider 和音频设备尚未资格验证", "provider_device_qualification"),
                "native_actions": native_action if is_linux else _status("experimental", "X11/Wayland 适配路径存在，仍需宿主 compositor 和权限验收", "implementation_contract"),
            },
        },
        {
            "id": "macos",
            "name": "macOS",
            "host": is_macos,
            "capabilities": {
                "desktop": desktop_status if is_macos else _status("planned", "尚未作为当前发行平台验收", "roadmap"),
                "live2d_vrm": _status("experimental", "渲染器理论可复用，尚无本地发行验收", "declared_contract"),
                "text_voice": _status("experimental", "后端协议可复用，设备与打包尚无验收", "declared_contract"),
                "native_actions": native_action if is_macos else _status("planned", "macOS 原生动作适配器尚未验收", "roadmap"),
            },
        },
        {
            "id": "browser-pwa",
            "name": "浏览器 / PWA",
            "host": False,
            "capabilities": {
                "desktop": _status("planned", "仅规划文字、记忆和配置工作区，不等价于透明桌宠", "roadmap"),
                "live2d_vrm": _status("planned", "浏览器渲染差异尚未完成验收", "roadmap"),
                "text_voice": _status("experimental", "可复用 HTTP/Socket.IO 协议，浏览器设备权限需单独验证", "declared_contract"),
                "native_actions": _status("unsupported", "浏览器不提供本地 user32/X11 桌面动作", "platform_boundary"),
            },
        },
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": _now(),
        "host": {
            "system": system or "unknown",
            "release": platform.release(),
            "displayServer": display_server,
            "wayland": {
                "displayConfigured": bool(os.getenv("WAYLAND_DISPLAY")),
                "socketPresent": wayland_socket_present,
                "probe": "detected" if wayland_socket_present else "not_detected",
            },
        },
        "platforms": platforms,
        "statusLegend": ["available", "needs_config", "experimental", "planned", "unsupported"],
    }


__all__ = ["SCHEMA_VERSION", "build_platform_capability_snapshot"]
