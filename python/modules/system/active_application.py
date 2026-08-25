"""Foreground application metadata without spawning a shell."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any


def read_active_application() -> dict[str, Any]:
    if sys.platform != "win32":
        raise RuntimeError("active application provider is unavailable on this platform")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        raise RuntimeError("foreground window is unavailable")
    length = user32.GetWindowTextLengthW(hwnd)
    title_buffer = ctypes.create_unicode_buffer(max(1, length + 1))
    user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    process = kernel32.OpenProcess(0x1000, False, process_id.value)
    executable = ""
    if process:
        try:
            size = wintypes.DWORD(32_768)
            path_buffer = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(process, 0, path_buffer, ctypes.byref(size)):
                executable = path_buffer.value
        finally:
            kernel32.CloseHandle(process)
    return {
        "name": Path(executable).name if executable else "unknown",
        "title": title_buffer.value,
        "process_id": int(process_id.value),
    }
