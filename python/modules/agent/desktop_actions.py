"""Fail-closed, host-scoped native window actions.

Native window identifiers never cross the adapter/controller boundary.  The
model receives short-lived random leases, and every live action re-discovers
and fingerprints its target immediately before the platform call.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import hashlib
import hmac
import json
import os
import queue
import secrets
import sys
import threading
import time
import weakref
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, Protocol

from .permission_receipt import PermissionReceipt, redact_permission_parameters
from .tool_registry import ToolDefinition, ToolRegistry, _verify_execution_permit
from .tool_result import ToolResultEnvelope

MAX_WINDOWS = 100
MAX_LABEL_LENGTH = 160
MAX_LEASE_TTL_SECONDS = 15.0
DEFAULT_HOST_LEASE_TTL_SECONDS = 5.0
MAX_HOST_LEASE_TTL_SECONDS = 30.0
DEFAULT_APP_GRANT_TTL_SECONDS = 30.0
MAX_APP_GRANT_TTL_SECONDS = 300.0
DEFAULT_ACTION_TIMEOUT_SECONDS = 1.0
MAX_ACTIVE_LEASES = 512
MAX_ACTIVE_APP_GRANTS = 512
MAX_USED_PERMITS = 2048
DESKTOP_ACTION_SCHEMA_VERSION = "yuizaki.desktop-action.v2"


class DesktopActionError(RuntimeError):
    """A deterministic native desktop rejection."""

    def __init__(self, code: str, message: str, *, category: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.category = category


def _opaque(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise DesktopActionError("DA_INVALID_SCOPE", f"{field_name} must be an opaque string")
    clean = value.strip()
    if not clean or len(clean) > 256 or any(ord(char) < 32 for char in clean):
        raise DesktopActionError("DA_INVALID_SCOPE", f"{field_name} is invalid")
    return clean


def _bounded_label(value: object) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split())
    return text[:MAX_LABEL_LENGTH]


@dataclass(frozen=True)
class DesktopActionScope:
    workspace_id: str
    session_id: str
    turn_id: str
    request_id: str
    generation_id: str
    interruption_epoch: int

    def to_dict(self) -> dict[str, str | int]:
        return {
            "workspace_id": self.workspace_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "request_id": self.request_id,
            "generation_id": self.generation_id,
            "interruption_epoch": self.interruption_epoch,
        }


_SCOPE_FIELDS = (
    "workspace_id", "session_id", "turn_id", "request_id",
    "generation_id",
)


def _validated_scope(scope: DesktopActionScope) -> DesktopActionScope:
    values = scope.to_dict()
    epoch = values.get("interruption_epoch")
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
        raise DesktopActionError("DA_INVALID_SCOPE", "interruption_epoch must be non-negative")
    return DesktopActionScope(
        **{field_name: _opaque(values.get(field_name), field_name) for field_name in _SCOPE_FIELDS},
        interruption_epoch=epoch,
    )


@dataclass(frozen=True)
class NativeWindowTarget:
    """Adapter-only target. ``native_id`` must never be serialized."""

    native_id: int
    title: str
    app_label: str
    fingerprint: str
    visible: bool = True
    app_fingerprint: str = ""
    window_fingerprint: str = ""


@dataclass(frozen=True)
class WindowDescriptor:
    """Compatibility-safe public descriptor with only a random lease."""

    window_id: str
    title: str
    process_id: int | None = None
    visible: bool = True
    app_label: str = ""

    def to_dict(self) -> dict[str, Any]:
        # process_id is deliberately omitted even when a legacy caller supplied it.
        return {
            "target_lease": self.window_id,
            "title": _bounded_label(self.title),
            "app_label": _bounded_label(self.app_label),
            "visible": bool(self.visible),
        }


@dataclass(frozen=True)
class NativeDesktopResult:
    category: Literal["completed", "requested"]
    evidence: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DesktopActionStopFence:
    issued_stop_epoch: int
    issued_feature_revision: int
    issued_revocation_generation: int
    _state_provider: Callable[[], tuple[int, int, int, bool, bool]]
    _authorization_provider: Callable[[], bool] | None = None

    @property
    def stopped(self) -> bool:
        stop_epoch, feature_revision, revocation_generation, enabled, emergency_stopped = self._state_provider()
        return (
            not enabled
            or emergency_stopped
            or stop_epoch != self.issued_stop_epoch
            or feature_revision != self.issued_feature_revision
            or revocation_generation != self.issued_revocation_generation
            or (
                self._authorization_provider is not None
                and not self._authorization_provider()
            )
        )

    def raise_if_stopped(self) -> None:
        if self.stopped:
            _stop, _revision, _revocation, enabled, emergency_stopped = self._state_provider()
            code = "DA_EMERGENCY_STOPPED" if emergency_stopped or not enabled else "DA_ACTION_REVOKED"
            raise DesktopActionError(code, "desktop action was fenced")


class DesktopActionAdapter(Protocol):
    def discover(self, *, limit: int = MAX_WINDOWS) -> list[NativeWindowTarget]: ...

    def focus(self, target: NativeWindowTarget, fence: DesktopActionStopFence) -> NativeDesktopResult: ...

    def request_close(self, target: NativeWindowTarget, fence: DesktopActionStopFence) -> NativeDesktopResult: ...


def _fingerprint(*parts: object) -> str:
    material = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(material.encode("utf-8", errors="replace")).hexdigest()


class WindowsDesktopActionAdapter:
    """Bounded user32 window discovery, focus, and graceful WM_CLOSE."""

    WM_CLOSE = 0x0010
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    def __init__(self, *, close_observation_seconds: float = 0.25) -> None:
        if os.name != "nt":
            raise DesktopActionError("DA_PLATFORM_UNAVAILABLE", "Windows user32 is unavailable")
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        hwnd = ctypes.c_void_p
        self._user32.IsWindow.argtypes = [hwnd]
        self._user32.IsWindow.restype = ctypes.c_int
        self._user32.IsWindowVisible.argtypes = [hwnd]
        self._user32.IsWindowVisible.restype = ctypes.c_int
        self._user32.GetWindowTextLengthW.argtypes = [hwnd]
        self._user32.GetWindowTextLengthW.restype = ctypes.c_int
        self._user32.GetWindowTextW.argtypes = [hwnd, ctypes.c_wchar_p, ctypes.c_int]
        self._user32.GetWindowTextW.restype = ctypes.c_int
        self._user32.GetClassNameW.argtypes = [hwnd, ctypes.c_wchar_p, ctypes.c_int]
        self._user32.GetClassNameW.restype = ctypes.c_int
        self._user32.GetWindowThreadProcessId.argtypes = [hwnd, ctypes.POINTER(ctypes.c_ulong)]
        self._user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
        self._user32.SetForegroundWindow.argtypes = [hwnd]
        self._user32.SetForegroundWindow.restype = ctypes.c_int
        self._user32.GetForegroundWindow.argtypes = []
        self._user32.GetForegroundWindow.restype = hwnd
        self._user32.PostMessageW.argtypes = [hwnd, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        self._user32.PostMessageW.restype = ctypes.c_int
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        self._kernel32.OpenProcess.restype = ctypes.c_void_p
        self._kernel32.QueryFullProcessImageNameW.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong),
        ]
        self._kernel32.QueryFullProcessImageNameW.restype = ctypes.c_int
        self._kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        self._kernel32.CloseHandle.restype = ctypes.c_int
        self._close_observation_seconds = max(0.0, min(float(close_observation_seconds), 1.0))

    def _process_image_identity(self, process_id: int, app_label: str, hwnd: int) -> str:
        process = self._kernel32.OpenProcess(self.PROCESS_QUERY_LIMITED_INFORMATION, 0, process_id)
        if process:
            try:
                size = ctypes.c_ulong(32768)
                buffer = ctypes.create_unicode_buffer(size.value)
                if self._kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                    return _fingerprint("win32-image", buffer.value.casefold())
            finally:
                self._kernel32.CloseHandle(process)
        # Process IDs are reusable and may be unavailable. A denied query must
        # narrow authorization to one window instead of grouping unknown apps.
        return _fingerprint("win32-window-process", hwnd, process_id, app_label)

    def _target(self, hwnd: int) -> NativeWindowTarget | None:
        if not self._user32.IsWindow(hwnd) or not self._user32.IsWindowVisible(hwnd):
            return None
        length = min(max(int(self._user32.GetWindowTextLengthW(hwnd)), 0), 4096)
        if length <= 0:
            return None
        title_buffer = ctypes.create_unicode_buffer(length + 1)
        self._user32.GetWindowTextW(hwnd, title_buffer, length + 1)
        title = _bounded_label(title_buffer.value)
        if not title:
            return None
        class_buffer = ctypes.create_unicode_buffer(257)
        self._user32.GetClassNameW(hwnd, class_buffer, 256)
        app_label = _bounded_label(class_buffer.value) or "Windows application"
        process_id = ctypes.c_ulong(0)
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        return NativeWindowTarget(
            native_id=int(hwnd),
            title=title,
            app_label=app_label,
            fingerprint=_fingerprint("win32", int(hwnd), int(process_id.value), app_label, title),
            app_fingerprint=self._process_image_identity(int(process_id.value), app_label, int(hwnd)),
            window_fingerprint=_fingerprint("win32-window", int(hwnd), int(process_id.value)),
        )

    def discover(self, *, limit: int = MAX_WINDOWS) -> list[NativeWindowTarget]:
        bounded_limit = max(1, min(int(limit), MAX_WINDOWS))
        result: list[NativeWindowTarget] = []
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        @callback_type
        def callback(hwnd: int, _lparam: int) -> bool:
            target = self._target(int(hwnd))
            if target is not None:
                result.append(target)
            return len(result) < bounded_limit

        # EnumWindows returns zero when our callback intentionally stops early.
        self._user32.EnumWindows(callback, 0)
        return result[:bounded_limit]

    def _revalidate(self, target: NativeWindowTarget) -> NativeWindowTarget:
        current = self._target(target.native_id)
        if current is None:
            raise DesktopActionError("DA_TARGET_GONE", "target window no longer exists")
        if not secrets.compare_digest(current.fingerprint, target.fingerprint):
            raise DesktopActionError("DA_TARGET_RECYCLED", "target window identity changed")
        return current

    def focus(self, target: NativeWindowTarget, fence: DesktopActionStopFence) -> NativeDesktopResult:
        current = self._revalidate(target)
        fence.raise_if_stopped()
        if not self._user32.SetForegroundWindow(current.native_id):
            raise DesktopActionError("DA_FOCUS_REJECTED", "Windows rejected foreground focus")
        fence.raise_if_stopped()
        if int(self._user32.GetForegroundWindow()) != current.native_id:
            raise DesktopActionError("DA_POSTCONDITION_FAILED", "foreground focus was not established")
        return NativeDesktopResult("completed", {"foreground_verified": "true"})

    def request_close(self, target: NativeWindowTarget, fence: DesktopActionStopFence) -> NativeDesktopResult:
        current = self._revalidate(target)
        fence.raise_if_stopped()
        if not self._user32.PostMessageW(current.native_id, self.WM_CLOSE, 0, 0):
            raise DesktopActionError("DA_CLOSE_REJECTED", "Windows rejected WM_CLOSE")
        deadline = time.monotonic() + self._close_observation_seconds
        while time.monotonic() < deadline and self._user32.IsWindow(current.native_id):
            fence.raise_if_stopped()
            time.sleep(0.01)
        fence.raise_if_stopped()
        state = "closed" if not self._user32.IsWindow(current.native_id) else "still_open"
        return NativeDesktopResult("requested", {"message": "WM_CLOSE", "observed_state": state})


class _XWindowAttributes(ctypes.Structure):
    _fields_: ClassVar[list[tuple[str, Any]]] = [  # pyright: ignore[reportIncompatibleVariableOverride]
        ("x", ctypes.c_int), ("y", ctypes.c_int), ("width", ctypes.c_int),
        ("height", ctypes.c_int), ("border_width", ctypes.c_int),
        ("depth", ctypes.c_int), ("visual", ctypes.c_void_p),
        ("root", ctypes.c_ulong), ("class_", ctypes.c_int),
        ("bit_gravity", ctypes.c_int), ("win_gravity", ctypes.c_int),
        ("backing_store", ctypes.c_int), ("backing_planes", ctypes.c_ulong),
        ("backing_pixel", ctypes.c_ulong), ("save_under", ctypes.c_int),
        ("colormap", ctypes.c_ulong), ("map_installed", ctypes.c_int),
        ("map_state", ctypes.c_int), ("all_event_masks", ctypes.c_long),
        ("your_event_mask", ctypes.c_long), ("do_not_propagate_mask", ctypes.c_long),
        ("override_redirect", ctypes.c_int), ("screen", ctypes.c_void_p),
    ]


class _XClientMessageData(ctypes.Union):
    _fields_: ClassVar[list[tuple[str, Any]]] = [  # pyright: ignore[reportIncompatibleVariableOverride]
        ("b", ctypes.c_char * 20), ("s", ctypes.c_short * 10), ("l", ctypes.c_long * 5),
    ]


class _XClientMessageEvent(ctypes.Structure):
    _fields_: ClassVar[list[tuple[str, Any]]] = [  # pyright: ignore[reportIncompatibleVariableOverride]
        ("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p), ("window", ctypes.c_ulong),
        ("message_type", ctypes.c_ulong), ("format", ctypes.c_int),
        ("data", _XClientMessageData),
    ]


class _XEvent(ctypes.Union):
    _fields_: ClassVar[list[tuple[str, Any]]] = [  # pyright: ignore[reportIncompatibleVariableOverride]
        ("type", ctypes.c_int), ("xclient", _XClientMessageEvent), ("pad", ctypes.c_long * 24),
    ]


class _XClassHint(ctypes.Structure):
    _fields_: ClassVar[list[tuple[str, Any]]] = [  # pyright: ignore[reportIncompatibleVariableOverride]
        ("res_name", ctypes.c_void_p),
        ("res_class", ctypes.c_void_p),
    ]


class X11DesktopActionAdapter:
    """ctypes-only X11 implementation; pure Wayland is explicitly rejected."""

    IS_VIEWABLE = 2
    REVERT_TO_PARENT = 2
    CURRENT_TIME = 0
    CLIENT_MESSAGE = 33

    def __init__(self, *, close_observation_seconds: float = 0.25) -> None:
        session_type = os.environ.get("XDG_SESSION_TYPE", "").strip().lower()
        if session_type == "wayland":
            raise DesktopActionError("DA_WAYLAND_UNSUPPORTED", "pure Wayland window control is unsupported")
        if session_type != "x11" or not os.environ.get("DISPLAY"):
            raise DesktopActionError("DA_X11_UNAVAILABLE", "an explicit X11 session and DISPLAY are required")
        library = ctypes.util.find_library("X11")
        if not library:
            raise DesktopActionError("DA_X11_UNAVAILABLE", "libX11 was not found")
        self._x11 = ctypes.CDLL(library)
        display_pointer = ctypes.c_void_p
        window = ctypes.c_ulong
        atom = ctypes.c_ulong
        self._x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self._x11.XOpenDisplay.restype = ctypes.c_void_p
        self._display = self._x11.XOpenDisplay(None)
        if not self._display:
            raise DesktopActionError("DA_X11_UNAVAILABLE", "XOpenDisplay failed")
        self._x11.XDefaultRootWindow.argtypes = [display_pointer]
        self._x11.XDefaultRootWindow.restype = ctypes.c_ulong
        self._root = int(self._x11.XDefaultRootWindow(self._display))
        self._x11.XFetchName.argtypes = [display_pointer, window, ctypes.POINTER(ctypes.c_char_p)]
        self._x11.XFetchName.restype = ctypes.c_int
        self._x11.XGetClassHint.argtypes = [display_pointer, window, ctypes.POINTER(_XClassHint)]
        self._x11.XGetClassHint.restype = ctypes.c_int
        self._x11.XFree.argtypes = [ctypes.c_void_p]
        self._x11.XFree.restype = ctypes.c_int
        self._x11.XGetWindowAttributes.argtypes = [display_pointer, window, ctypes.POINTER(_XWindowAttributes)]
        self._x11.XGetWindowAttributes.restype = ctypes.c_int
        self._x11.XQueryTree.argtypes = [
            display_pointer, window, ctypes.POINTER(window), ctypes.POINTER(window),
            ctypes.POINTER(ctypes.POINTER(window)), ctypes.POINTER(ctypes.c_uint),
        ]
        self._x11.XQueryTree.restype = ctypes.c_int
        self._x11.XSetInputFocus.argtypes = [display_pointer, window, ctypes.c_int, ctypes.c_ulong]
        self._x11.XSetInputFocus.restype = ctypes.c_int
        self._x11.XGetInputFocus.argtypes = [display_pointer, ctypes.POINTER(window), ctypes.POINTER(ctypes.c_int)]
        self._x11.XGetInputFocus.restype = ctypes.c_int
        self._x11.XInternAtom.argtypes = [display_pointer, ctypes.c_char_p, ctypes.c_int]
        self._x11.XInternAtom.restype = atom
        self._x11.XSendEvent.argtypes = [display_pointer, window, ctypes.c_int, ctypes.c_long, ctypes.POINTER(_XEvent)]
        self._x11.XSendEvent.restype = ctypes.c_int
        self._x11.XFlush.argtypes = [display_pointer]
        self._x11.XFlush.restype = ctypes.c_int
        self._close_observation_seconds = max(0.0, min(float(close_observation_seconds), 1.0))
        self._lock = threading.Lock()

    def _title(self, window: int) -> str:
        name = ctypes.c_char_p()
        if not self._x11.XFetchName(self._display, ctypes.c_ulong(window), ctypes.byref(name)) or not name.value:
            return ""
        try:
            return _bounded_label(name.value.decode("utf-8", errors="replace"))
        finally:
            self._x11.XFree(name)

    def _target(self, window: int) -> NativeWindowTarget | None:
        attributes = _XWindowAttributes()
        if not self._x11.XGetWindowAttributes(self._display, ctypes.c_ulong(window), ctypes.byref(attributes)):
            return None
        if attributes.map_state != self.IS_VIEWABLE or attributes.override_redirect:
            return None
        title = self._title(window)
        if not title:
            return None
        class_hint = _XClassHint()
        app_label = "X11 application"
        app_identity = _fingerprint("x11-window", window)
        if self._x11.XGetClassHint(self._display, ctypes.c_ulong(window), ctypes.byref(class_hint)):
            try:
                name_bytes = ctypes.cast(class_hint.res_name, ctypes.c_char_p).value if class_hint.res_name else None
                class_bytes = ctypes.cast(class_hint.res_class, ctypes.c_char_p).value if class_hint.res_class else None
                name = name_bytes.decode("utf-8", errors="replace") if name_bytes else ""
                class_name = class_bytes.decode("utf-8", errors="replace") if class_bytes else ""
                if class_name or name:
                    app_label = _bounded_label(class_name or name)
                    app_identity = _fingerprint("x11-wm-class", class_name.casefold(), name.casefold())
            finally:
                if class_hint.res_name:
                    self._x11.XFree(class_hint.res_name)
                if class_hint.res_class:
                    self._x11.XFree(class_hint.res_class)
        return NativeWindowTarget(
            native_id=window,
            title=title,
            app_label=app_label,
            fingerprint=_fingerprint("x11", window, title, attributes.width, attributes.height),
            app_fingerprint=app_identity,
            window_fingerprint=_fingerprint("x11-window", window),
        )

    def discover(self, *, limit: int = MAX_WINDOWS) -> list[NativeWindowTarget]:
        bounded_limit = max(1, min(int(limit), MAX_WINDOWS))
        root_return = ctypes.c_ulong()
        parent_return = ctypes.c_ulong()
        children = ctypes.POINTER(ctypes.c_ulong)()
        count = ctypes.c_uint()
        with self._lock:
            if not self._x11.XQueryTree(
                self._display, ctypes.c_ulong(self._root), ctypes.byref(root_return),
                ctypes.byref(parent_return), ctypes.byref(children), ctypes.byref(count),
            ):
                raise DesktopActionError("DA_DISCOVERY_FAILED", "XQueryTree failed")
            try:
                targets: list[NativeWindowTarget] = []
                for index in range(min(int(count.value), MAX_WINDOWS * 4)):
                    target = self._target(int(children[index]))
                    if target is not None:
                        targets.append(target)
                    if len(targets) >= bounded_limit:
                        break
                return targets
            finally:
                if children:
                    self._x11.XFree(children)

    def _revalidate(self, target: NativeWindowTarget) -> NativeWindowTarget:
        current = self._target(target.native_id)
        if current is None:
            raise DesktopActionError("DA_TARGET_GONE", "target window no longer exists")
        if not secrets.compare_digest(current.fingerprint, target.fingerprint):
            raise DesktopActionError("DA_TARGET_RECYCLED", "target window identity changed")
        return current

    def focus(self, target: NativeWindowTarget, fence: DesktopActionStopFence) -> NativeDesktopResult:
        with self._lock:
            current = self._revalidate(target)
            fence.raise_if_stopped()
            self._x11.XSetInputFocus(
                self._display, ctypes.c_ulong(current.native_id), self.REVERT_TO_PARENT, self.CURRENT_TIME,
            )
            self._x11.XFlush(self._display)
            focused = ctypes.c_ulong()
            revert = ctypes.c_int()
            self._x11.XGetInputFocus(self._display, ctypes.byref(focused), ctypes.byref(revert))
            fence.raise_if_stopped()
            if int(focused.value) != current.native_id:
                raise DesktopActionError("DA_POSTCONDITION_FAILED", "X11 input focus was not established")
            return NativeDesktopResult("completed", {"input_focus_verified": "true"})

    def request_close(self, target: NativeWindowTarget, fence: DesktopActionStopFence) -> NativeDesktopResult:
        with self._lock:
            current = self._revalidate(target)
            wm_protocols = int(self._x11.XInternAtom(self._display, b"WM_PROTOCOLS", 0))
            wm_delete = int(self._x11.XInternAtom(self._display, b"WM_DELETE_WINDOW", 0))
            if not wm_protocols or not wm_delete:
                raise DesktopActionError("DA_CLOSE_UNSUPPORTED", "WM_DELETE_WINDOW is unavailable")
            event = _XEvent()
            event.xclient.type = self.CLIENT_MESSAGE
            event.xclient.display = self._display
            event.xclient.window = current.native_id
            event.xclient.message_type = wm_protocols
            event.xclient.format = 32
            event.xclient.data.l[0] = wm_delete
            event.xclient.data.l[1] = self.CURRENT_TIME
            fence.raise_if_stopped()
            if not self._x11.XSendEvent(self._display, ctypes.c_ulong(current.native_id), 0, 0, ctypes.byref(event)):
                raise DesktopActionError("DA_CLOSE_REJECTED", "X11 rejected WM_DELETE_WINDOW")
            self._x11.XFlush(self._display)
        deadline = time.monotonic() + self._close_observation_seconds
        state = "still_open"
        while time.monotonic() < deadline:
            fence.raise_if_stopped()
            with self._lock:
                if self._target(current.native_id) is None:
                    state = "closed"
                    break
            time.sleep(0.01)
        return NativeDesktopResult("requested", {"message": "WM_DELETE_WINDOW", "observed_state": state})


def create_system_desktop_adapter() -> DesktopActionAdapter:
    if os.name == "nt":
        return WindowsDesktopActionAdapter()
    if sys.platform.startswith("linux"):
        return X11DesktopActionAdapter()
    raise DesktopActionError("DA_PLATFORM_UNSUPPORTED", "native desktop actions are unsupported on this platform")


class SystemDesktopActionAdapter:
    """Lazy platform adapter preserving fail-closed construction on any host."""

    def __init__(self) -> None:
        self._resolved: DesktopActionAdapter | None = None

    def _adapter(self) -> DesktopActionAdapter:
        if self._resolved is None:
            self._resolved = create_system_desktop_adapter()
        return self._resolved

    def discover(self, *, limit: int = MAX_WINDOWS) -> list[NativeWindowTarget]:
        return self._adapter().discover(limit=limit)

    def focus(self, target: NativeWindowTarget, fence: DesktopActionStopFence) -> NativeDesktopResult:
        return self._adapter().focus(target, fence)

    def request_close(self, target: NativeWindowTarget, fence: DesktopActionStopFence) -> NativeDesktopResult:
        return self._adapter().request_close(target, fence)

    # Legacy methods cannot safely accept raw identifiers anymore.
    def list_windows(self, *, include_hidden: bool = False) -> list[WindowDescriptor]:
        del include_hidden
        raise DesktopActionError("DA_HOST_BINDING_REQUIRED", "window discovery requires a scoped controller")

    def focus_window(self, window_id: str) -> str:
        del window_id
        raise DesktopActionError("DA_HOST_BINDING_REQUIRED", "raw window actions are disabled")

    def close_window(self, window_id: str) -> str:
        del window_id
        raise DesktopActionError("DA_HOST_BINDING_REQUIRED", "raw window actions are disabled")


@dataclass
class _TargetLease:
    target: NativeWindowTarget
    scope: DesktopActionScope
    expires_at: float
    feature_revision: int
    stop_epoch: int
    revocation_generation: int
    app_scope_id: str
    window_scope_id: str
    app_grant_id: str
    app_grant_revision: int
    allowed_actions: frozenset[str]
    revoked: bool = False


@dataclass
class _AppGrant:
    grant_id: str
    app_scope_id: str
    allowed_actions: frozenset[str]
    expires_at: float
    feature_revision: int
    revision: int
    revoked: bool = False


@dataclass
class _HostDiscovery:
    revision: int
    expires_at: float
    app_scope_ids: frozenset[str]


class DesktopActionController:
    """Opaque lease authority and immediate revision/stop fencing."""

    def __init__(
        self,
        *,
        adapter: DesktopActionAdapter | None = None,
        clock: Callable[[], float] = time.monotonic,
        action_timeout_seconds: float = DEFAULT_ACTION_TIMEOUT_SECONDS,
        enabled: bool = False,
        identity_secret: bytes | None = None,
    ) -> None:
        self.adapter = adapter or SystemDesktopActionAdapter()
        self._clock = clock
        self._action_timeout_seconds = max(0.05, min(float(action_timeout_seconds), 5.0))
        self._enabled = bool(enabled)
        self._emergency_stopped = False
        self._feature_revision = 1
        self._stop_epoch = 0
        self._revocation_generation = 0
        self._lease_epoch = 1
        self._lease_deadline = (
            self._clock() + DEFAULT_HOST_LEASE_TTL_SECONDS if enabled else 0.0
        )
        self._identity_secret = identity_secret or secrets.token_bytes(32)
        if len(self._identity_secret) < 32:
            raise ValueError("desktop identity secret must contain at least 32 bytes")
        self._discovery_revision = 0
        self._grant_revision = 0
        self._host_discovery: _HostDiscovery | None = None
        self._app_grants: dict[str, _AppGrant] = {}
        self._leases: dict[str, _TargetLease] = {}
        self._bindings: dict[int, tuple[weakref.ReferenceType[Any], DesktopActionScope]] = {}
        self._used_permits: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.RLock()
        self._driver_lock = threading.Lock()

    def status(self) -> dict[str, Any]:
        platform = "windows" if os.name == "nt" else ("linux" if sys.platform.startswith("linux") else "unsupported")
        reason: str | None = None
        available = False
        if os.name == "nt":
            available = True
        elif sys.platform.startswith("linux"):
            session_type = os.environ.get("XDG_SESSION_TYPE", "").strip().lower()
            if session_type == "wayland":
                reason = "DA_WAYLAND_UNSUPPORTED"
            elif (
                session_type != "x11"
                or not os.environ.get("DISPLAY")
                or not ctypes.util.find_library("X11")
            ):
                reason = "DA_X11_UNAVAILABLE"
            else:
                available = True
        else:
            reason = "DA_PLATFORM_UNSUPPORTED"
        with self._lock:
            self._expire_host_lease_locked()
            expires_in_ms = max(0, int((self._lease_deadline - self._clock()) * 1000)) if self._enabled else 0
            return {
                "enabled": self._enabled,
                "emergency_stopped": self._emergency_stopped,
                "available": available,
                "window_actions_available": available,
                "native_input_available": False,
                "feature_revision": self._feature_revision,
                "stop_epoch": self._stop_epoch,
                "lease_epoch": self._lease_epoch,
                "lease_expires_in_ms": expires_in_ms,
                "lease_deadline_monotonic_ms": int(self._lease_deadline * 1000) if self._enabled else 0,
                "schema_version": DESKTOP_ACTION_SCHEMA_VERSION,
                "platform": platform,
                "reason": reason,
            }

    @staticmethod
    def _host_ttl(ttl_seconds: object) -> float:
        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, (int, float))
            or not 0 < float(ttl_seconds) <= MAX_HOST_LEASE_TTL_SECONDS
        ):
            raise DesktopActionError("DA_INVALID_HOST_LEASE_TTL", "host lease TTL is invalid")
        return float(ttl_seconds)

    def _expire_host_lease_locked(self) -> None:
        if self._enabled and self._clock() >= self._lease_deadline:
            self._enabled = False
            self._stop_epoch += 1
            self._feature_revision += 1
            self._revocation_generation += 1
            self._lease_epoch += 1
            self._revoke_all_locked()

    def _start_host_lease_locked(self, ttl_seconds: object) -> None:
        ttl = self._host_ttl(ttl_seconds)
        self._lease_epoch += 1
        self._lease_deadline = self._clock() + ttl

    def set_enabled(
        self,
        enabled: bool,
        *,
        lease_ttl_seconds: float = DEFAULT_HOST_LEASE_TTL_SECONDS,
    ) -> dict[str, Any]:
        if not isinstance(enabled, bool):
            raise DesktopActionError("DA_INVALID_FEATURE_STATE", "enabled must be boolean")
        with self._lock:
            self._expire_host_lease_locked()
            if enabled and self._emergency_stopped:
                raise DesktopActionError("DA_REARM_REQUIRED", "emergency stop must be explicitly rearmed")
            self._enabled = enabled
            self._feature_revision += 1
            self._stop_epoch += 1
            self._revocation_generation += 1
            self._revoke_all_locked()
            if enabled:
                self._start_host_lease_locked(lease_ttl_seconds)
            else:
                self._lease_deadline = 0.0
            return self.status()

    def rearm(self, *, lease_ttl_seconds: float = DEFAULT_HOST_LEASE_TTL_SECONDS) -> dict[str, Any]:
        with self._lock:
            self._enabled = True
            self._emergency_stopped = False
            self._feature_revision += 1
            self._stop_epoch += 1
            self._revocation_generation += 1
            self._revoke_all_locked()
            self._start_host_lease_locked(lease_ttl_seconds)
            return self.status()

    def heartbeat(self, *, lease_epoch: int, lease_ttl_seconds: float = DEFAULT_HOST_LEASE_TTL_SECONDS) -> dict[str, Any]:
        if isinstance(lease_epoch, bool) or not isinstance(lease_epoch, int) or lease_epoch < 1:
            raise DesktopActionError("DA_INVALID_LEASE_EPOCH", "host lease epoch is invalid")
        ttl = self._host_ttl(lease_ttl_seconds)
        with self._lock:
            self._expire_host_lease_locked()
            if not self._enabled or self._emergency_stopped:
                raise DesktopActionError("DA_HOST_LEASE_EXPIRED", "desktop host lease is not active")
            if lease_epoch != self._lease_epoch:
                raise DesktopActionError("DA_HOST_LEASE_EPOCH_MISMATCH", "desktop host lease epoch changed")
            self._lease_deadline = self._clock() + ttl
            return self.status()

    def emergency_stop(self) -> dict[str, Any]:
        with self._lock:
            self._enabled = False
            self._emergency_stopped = True
            self._stop_epoch += 1
            self._feature_revision += 1
            self._revocation_generation += 1
            self._revoke_all_locked()
            self._lease_epoch += 1
            self._lease_deadline = 0.0
            return self.status()

    def _revoke_all_locked(self) -> None:
        for lease in self._leases.values():
            lease.revoked = True
        self._bindings.clear()
        for grant in self._app_grants.values():
            grant.revoked = True
        self._host_discovery = None

    def revoke_all(self) -> int:
        with self._lock:
            self._feature_revision += 1
            self._revocation_generation += 1
            count = sum(not lease.revoked for lease in self._leases.values())
            self._revoke_all_locked()
            return count

    def revoke_target(self, target_lease: str) -> bool:
        with self._lock:
            lease = self._leases.get(_opaque(target_lease, "target_lease"))
            if lease is None:
                return False
            self._revocation_generation += 1
            lease.revoked = True
            return True

    def revoke_session(self, session_id: str) -> int:
        count = self._revoke_matching(lambda lease: lease.scope.session_id == session_id)
        with self._lock:
            self._bindings = {
                key: binding for key, binding in self._bindings.items()
                if binding[1].session_id != session_id
            }
        return count

    def revoke_scope(self, scope: DesktopActionScope) -> int:
        validated = _validated_scope(scope)
        count = self._revoke_matching(lambda lease: lease.scope == validated)
        with self._lock:
            self._bindings = {
                key: binding for key, binding in self._bindings.items()
                if binding[1] != validated
            }
        return count

    def _revoke_matching(self, predicate: Callable[[_TargetLease], bool]) -> int:
        with self._lock:
            count = 0
            matched = False
            for lease in self._leases.values():
                if predicate(lease):
                    matched = True
                    if not lease.revoked:
                        lease.revoked = True
                        count += 1
            if matched:
                self._revocation_generation += 1
            return count

    def bind_context(self, ctx: Any, *, trusted_scope: DesktopActionScope) -> None:
        scope = _validated_scope(trusted_scope)
        context_id = id(ctx)

        def remove(reference: weakref.ReferenceType[Any]) -> None:
            with self._lock:
                existing = self._bindings.get(context_id)
                if existing is not None and existing[0] is reference:
                    self._bindings.pop(context_id, None)

        try:
            reference = weakref.ref(ctx, remove)
        except TypeError as exc:
            raise DesktopActionError("DA_INVALID_CONTEXT", "context must support weak references") from exc
        with self._lock:
            self._expire_host_lease_locked()
            if not self._enabled:
                self._bindings.pop(context_id, None)
                return
            self._bindings[context_id] = (reference, scope)

    def _scope_for_context(self, ctx: Any) -> DesktopActionScope:
        with self._lock:
            self._expire_host_lease_locked()
            binding = self._bindings.get(id(ctx))
            if binding is None or binding[0]() is not ctx:
                raise DesktopActionError("DA_HOST_BINDING_REQUIRED", "trusted desktop context is unavailable")
            if not self._enabled:
                raise DesktopActionError("DA_FEATURE_DISABLED", "native desktop actions are disabled")
            if self._emergency_stopped:
                raise DesktopActionError("DA_REARM_REQUIRED", "desktop actions require explicit rearm")
            return binding[1]

    def _state(self) -> tuple[int, int, int, bool, bool]:
        with self._lock:
            self._expire_host_lease_locked()
            return (
                self._stop_epoch,
                self._feature_revision,
                self._revocation_generation,
                self._enabled,
                self._emergency_stopped,
            )

    def _app_scope_id(self, target: NativeWindowTarget) -> str:
        identity = target.app_fingerprint or target.app_label
        digest = hmac.new(self._identity_secret, f"app\x1f{identity}".encode(), hashlib.sha256).hexdigest()
        return f"das_app_{digest[:40]}"

    def _window_scope_id(self, target: NativeWindowTarget) -> str:
        identity = target.window_fingerprint or target.fingerprint
        digest = hmac.new(self._identity_secret, f"window\x1f{identity}".encode(), hashlib.sha256).hexdigest()
        return f"das_window_{digest[:40]}"

    def _configure_identity_secret_locked(self, identity_secret: str | None) -> None:
        if identity_secret is None:
            return
        material = identity_secret.encode("utf-8")
        if not material:
            raise DesktopActionError("DA_HOST_UNAUTHORIZED", "desktop host identity secret is unavailable")
        derived = hashlib.sha256(b"yuizaki.desktop.identity\x00" + material).digest()
        if secrets.compare_digest(derived, self._identity_secret):
            return
        self._identity_secret = derived
        self._feature_revision += 1
        self._revocation_generation += 1
        self._revoke_all_locked()
        self._host_discovery = None

    def host_discover(
        self,
        *,
        ttl_seconds: float = MAX_LEASE_TTL_SECONDS,
        identity_secret: str | None = None,
    ) -> dict[str, Any]:
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)) or not 0 < ttl_seconds <= MAX_LEASE_TTL_SECONDS:
            raise DesktopActionError("DA_INVALID_TTL", "host discovery TTL is invalid")
        with self._lock:
            self._expire_host_lease_locked()
            if not self._enabled:
                raise DesktopActionError("DA_HOST_LEASE_EXPIRED", "desktop host lease is not active")
            self._configure_identity_secret_locked(identity_secret)
        fence = self._new_fence()
        discovered = self._run_driver(lambda: self.adapter.discover(limit=MAX_WINDOWS), fence=fence, effect_possible=False)
        if not isinstance(discovered, list) or any(not isinstance(item, NativeWindowTarget) for item in discovered):
            raise DesktopActionError("DA_ADAPTER_RESULT_INVALID", "adapter discovery returned an invalid result")
        apps: dict[str, dict[str, Any]] = {}
        for target in discovered[:MAX_WINDOWS]:
            app_id = self._app_scope_id(target)
            app = apps.setdefault(app_id, {
                "app_id": app_id,
                "app_label": _bounded_label(target.app_label),
                "windows": [],
            })
            app["windows"].append({
                "window_id": self._window_scope_id(target),
                "title": _bounded_label(target.title),
                "visible": bool(target.visible),
            })
        with self._lock:
            fence.raise_if_stopped()
            self._discovery_revision += 1
            revision = self._discovery_revision
            self._host_discovery = _HostDiscovery(
                revision=revision,
                expires_at=self._clock() + float(ttl_seconds),
                app_scope_ids=frozenset(apps),
            )
        return {"code": "DA_HOST_DISCOVERY", "discovery_revision": revision, "apps": list(apps.values())}

    def grant_app(
        self,
        *,
        app_id: object,
        discovery_revision: object,
        allowed_actions: object,
        ttl_seconds: float = DEFAULT_APP_GRANT_TTL_SECONDS,
    ) -> dict[str, Any]:
        selected_app = _opaque(app_id, "app_id")
        if isinstance(discovery_revision, bool) or not isinstance(discovery_revision, int):
            raise DesktopActionError("DA_DISCOVERY_REVISION_INVALID", "discovery revision is invalid")
        if not isinstance(allowed_actions, list) or not allowed_actions:
            raise DesktopActionError("DA_APP_ACTIONS_INVALID", "allowed actions are required")
        actions = frozenset(allowed_actions)
        if actions - {"focus", "request_close"} or any(not isinstance(item, str) for item in allowed_actions):
            raise DesktopActionError("DA_APP_ACTIONS_INVALID", "allowed actions are invalid")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)) or not 0 < ttl_seconds <= MAX_APP_GRANT_TTL_SECONDS:
            raise DesktopActionError("DA_INVALID_TTL", "app grant TTL is invalid")
        with self._lock:
            self._expire_host_lease_locked()
            self._prune_app_grants_locked()
            discovery = self._host_discovery
            if (
                discovery is None
                or discovery.revision != discovery_revision
                or self._clock() >= discovery.expires_at
            ):
                raise DesktopActionError("DA_DISCOVERY_STALE", "host discovery is stale")
            if selected_app not in discovery.app_scope_ids:
                raise DesktopActionError("DA_APP_SCOPE_MISMATCH", "application was not in host discovery")
            for existing in self._app_grants.values():
                existing.revoked = True
            for lease in self._leases.values():
                lease.revoked = True
            self._prune_app_grants_locked()
            if len(self._app_grants) >= MAX_ACTIVE_APP_GRANTS:
                raise DesktopActionError("DA_APP_GRANT_CAPACITY", "application grant capacity is exhausted")
            self._grant_revision += 1
            grant_id = f"dag_{secrets.token_urlsafe(24)}"
            grant = _AppGrant(
                grant_id=grant_id,
                app_scope_id=selected_app,
                allowed_actions=actions,
                expires_at=self._clock() + float(ttl_seconds),
                feature_revision=self._feature_revision,
                revision=self._grant_revision,
            )
            self._app_grants[grant_id] = grant
            return {
                "code": "DA_APP_GRANTED",
                "grant_id": grant_id,
                "app_id": selected_app,
                "allowed_actions": sorted(actions),
                "grant_revision": grant.revision,
                "expires_in_ms": max(0, int((grant.expires_at - self._clock()) * 1000)),
            }

    def _prune_app_grants_locked(self) -> None:
        now = self._clock()
        stale = [
            grant_id
            for grant_id, grant in self._app_grants.items()
            if (
                grant.revoked
                or now >= grant.expires_at
                or grant.feature_revision != self._feature_revision
            )
        ]
        for grant_id in stale:
            self._app_grants.pop(grant_id, None)

    def _active_grants_locked(self) -> dict[str, _AppGrant]:
        self._expire_host_lease_locked()
        self._prune_app_grants_locked()
        now = self._clock()
        return {
            grant.app_scope_id: grant
            for grant in self._app_grants.values()
            if not grant.revoked and now < grant.expires_at and grant.feature_revision == self._feature_revision
        }

    def _new_fence(self) -> DesktopActionStopFence:
        with self._lock:
            return DesktopActionStopFence(
                issued_stop_epoch=self._stop_epoch,
                issued_feature_revision=self._feature_revision,
                issued_revocation_generation=self._revocation_generation,
                _state_provider=self._state,
            )

    def _grant_is_active_for_lease(self, lease: _TargetLease, action: str) -> bool:
        with self._lock:
            self._expire_host_lease_locked()
            grant = self._app_grants.get(lease.app_grant_id)
            return bool(
                self._enabled
                and not self._emergency_stopped
                and grant is not None
                and not grant.revoked
                and self._clock() < grant.expires_at
                and grant.feature_revision == self._feature_revision
                and grant.revision == lease.app_grant_revision
                and grant.app_scope_id == lease.app_scope_id
                and action in grant.allowed_actions
            )

    @staticmethod
    def _normalize_adapter_error(value: object) -> DesktopActionError:
        if isinstance(value, DesktopActionError):
            return DesktopActionError(
                value.code,
                "native desktop operation was rejected",
                category=value.category or "adapter_rejection",
            )
        return DesktopActionError(
            "DA_ADAPTER_FAILURE",
            "native desktop adapter failed",
            category="adapter_error",
        )

    def _latch_outcome_unknown(self) -> None:
        with self._lock:
            self._enabled = False
            self._emergency_stopped = True
            self._stop_epoch += 1
            self._feature_revision += 1
            self._revocation_generation += 1
            self._revoke_all_locked()

    def _run_driver(
        self,
        callback: Callable[[], object],
        *,
        fence: DesktopActionStopFence,
        effect_possible: bool,
    ) -> object:
        """Run one complete driver transaction on the serialized host lane."""
        results: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

        def run() -> None:
            try:
                with self._driver_lock:
                    fence.raise_if_stopped()
                    value = callback()
                    fence.raise_if_stopped()
                results.put((True, value), block=False)
            except Exception as exc:  # noqa: BLE001 - adapter boundary normalizes all failures
                try:
                    results.put((False, exc), block=False)
                except queue.Full:
                    pass

        thread = threading.Thread(target=run, name="desktop-native-driver", daemon=True)
        thread.start()
        deadline = time.monotonic() + self._action_timeout_seconds
        while thread.is_alive():
            fence.raise_if_stopped()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if effect_possible:
                    self._latch_outcome_unknown()
                    raise DesktopActionError(
                        "DA_OUTCOME_UNKNOWN",
                        "desktop action timed out after a possible native effect",
                    )
                raise DesktopActionError("DA_ACTION_TIMEOUT", "desktop discovery timed out")
            thread.join(min(0.02, remaining))
        fence.raise_if_stopped()
        try:
            succeeded, value = results.get_nowait()
        except queue.Empty as exc:
            raise DesktopActionError("DA_ADAPTER_FAILURE", "native driver returned no result") from exc
        if not succeeded:
            raise self._normalize_adapter_error(value)
        return value

    def _prune_leases_locked(self) -> None:
        now = self._clock()
        stale = [
            lease_id for lease_id, lease in self._leases.items()
            if lease.revoked or now >= lease.expires_at
        ]
        for lease_id in stale:
            self._leases.pop(lease_id, None)
        while len(self._leases) >= MAX_ACTIVE_LEASES:
            self._leases.pop(next(iter(self._leases)))

    def list_targets(self, ctx: Any, *, ttl_seconds: float = MAX_LEASE_TTL_SECONDS) -> dict[str, Any]:
        scope = self._scope_for_context(ctx)
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)) or not 0 < ttl_seconds <= MAX_LEASE_TTL_SECONDS:
            raise DesktopActionError("DA_INVALID_TTL", "target TTL must be greater than zero and at most 15 seconds")
        fence = self._new_fence()
        discovered = self._run_driver(
            lambda: self.adapter.discover(limit=MAX_WINDOWS),
            fence=fence,
            effect_possible=False,
        )
        if not isinstance(discovered, list):
            raise DesktopActionError("DA_ADAPTER_RESULT_INVALID", "adapter discovery returned an invalid result")
        targets = discovered[:min(MAX_WINDOWS, MAX_ACTIVE_LEASES)]
        if len(targets) > MAX_WINDOWS or any(not isinstance(target, NativeWindowTarget) for target in targets):
            raise DesktopActionError("DA_ADAPTER_RESULT_INVALID", "adapter discovery exceeded its contract")
        windows: list[dict[str, Any]] = []
        with self._lock:
            if scope != self._scope_for_context(ctx):
                raise DesktopActionError("DA_SCOPE_MISMATCH", "desktop context changed during discovery")
            fence.raise_if_stopped()
            grants = self._active_grants_locked()
            if not grants:
                raise DesktopActionError("DA_APP_GRANT_REQUIRED", "a fresh host application grant is required")
            self._prune_leases_locked()
            for target in targets:
                app_scope_id = self._app_scope_id(target)
                grant = grants.get(app_scope_id)
                if grant is None:
                    continue
                while len(self._leases) >= MAX_ACTIVE_LEASES:
                    self._leases.pop(next(iter(self._leases)))
                lease_id = f"da_{secrets.token_urlsafe(24)}"
                window_scope_id = self._window_scope_id(target)
                self._leases[lease_id] = _TargetLease(
                    target=target,
                    scope=scope,
                    expires_at=self._clock() + float(ttl_seconds),
                    feature_revision=self._feature_revision,
                    stop_epoch=self._stop_epoch,
                    revocation_generation=self._revocation_generation,
                    app_scope_id=app_scope_id,
                    window_scope_id=window_scope_id,
                    app_grant_id=grant.grant_id,
                    app_grant_revision=grant.revision,
                    allowed_actions=grant.allowed_actions,
                )
                windows.append({
                    "target_lease": lease_id,
                    "title": _bounded_label(target.title),
                    "app_label": _bounded_label(target.app_label),
                    "visible": bool(target.visible),
                    "expires_in_ms": int(float(ttl_seconds) * 1000),
                })
        return {"code": "DA_TARGETS_ISSUED", "windows": windows, "count": len(windows)}

    def _lease_for(self, ctx: Any, target_lease: object) -> tuple[str, _TargetLease]:
        lease_id = _opaque(target_lease, "target_lease")
        scope = self._scope_for_context(ctx)
        with self._lock:
            lease = self._leases.get(lease_id)
            if lease is None:
                raise DesktopActionError("DA_TARGET_UNKNOWN", "target lease is unknown")
            if lease.revoked:
                raise DesktopActionError("DA_TARGET_REVOKED", "target lease was revoked")
            if self._clock() >= lease.expires_at:
                lease.revoked = True
                raise DesktopActionError("DA_TARGET_EXPIRED", "target lease expired")
            if lease.scope != scope:
                raise DesktopActionError("DA_SCOPE_MISMATCH", "target lease belongs to another request scope")
            if lease.feature_revision != self._feature_revision:
                raise DesktopActionError("DA_REVISION_MISMATCH", "feature revision changed")
            if lease.stop_epoch != self._stop_epoch:
                raise DesktopActionError("DA_EMERGENCY_STOPPED", "stop epoch changed")
            if lease.revocation_generation != self._revocation_generation:
                raise DesktopActionError("DA_ACTION_REVOKED", "target authorization generation changed")
            grant = self._app_grants.get(lease.app_grant_id)
            if (
                grant is None
                or grant.revoked
                or self._clock() >= grant.expires_at
                or grant.feature_revision != self._feature_revision
                or grant.revision != lease.app_grant_revision
                or grant.app_scope_id != lease.app_scope_id
            ):
                lease.revoked = True
                raise DesktopActionError("DA_APP_GRANT_EXPIRED", "application grant is no longer valid")
            return lease_id, lease

    def _confirmation_summary(self, lease: _TargetLease, action: str) -> dict[str, str]:
        return {
            "action": action,
            "application": _bounded_label(lease.target.app_label) or "Application",
            "window_title": _bounded_label(lease.target.title) or "Untitled window",
        }

    def _digest(self, lease_id: str, lease: _TargetLease, action: str) -> str:
        material = json.dumps({
            "lease": lease_id,
            "fingerprint": lease.target.fingerprint,
            "scope": lease.scope.to_dict(),
            "action": action,
            "app_scope_id": lease.app_scope_id,
            "window_scope_id": lease.window_scope_id,
            "confirmation_summary": self._confirmation_summary(lease, action),
            "feature_revision": lease.feature_revision,
            "stop_epoch": lease.stop_epoch,
            "revocation_generation": lease.revocation_generation,
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def preview(self, ctx: Any, *, target_lease: object, action: object) -> dict[str, Any]:
        if not isinstance(action, str) or action not in {"focus", "request_close"}:
            raise DesktopActionError("DA_INVALID_ACTION", "action must be focus or request_close")
        lease_id, lease = self._lease_for(ctx, target_lease)
        if action not in lease.allowed_actions:
            raise DesktopActionError("DA_APP_ACTION_DENIED", "application grant does not allow this action")
        confirmation_summary = self._confirmation_summary(lease, action)
        return {
            "code": "DA_PREVIEW",
            "action": action,
            "target_lease": lease_id,
            "preview_digest": self._digest(lease_id, lease, action),
            "confirmation_summary": confirmation_summary,
            "evidence": {
                "title": _bounded_label(lease.target.title),
                "app_label": _bounded_label(lease.target.app_label),
                "feature_revision": lease.feature_revision,
                "stop_epoch": lease.stop_epoch,
                "expires_in_ms": max(0, int((lease.expires_at - self._clock()) * 1000)),
            },
        }

    def _permit_claims(self, ctx: Any, action: str, target_lease: object) -> str:
        try:
            lease_id, lease = self._lease_for(ctx, target_lease)
            return self._digest(lease_id, lease, action)
        except DesktopActionError as exc:
            # ToolExecutor claim construction must remain total.  The context
            # handler repeats authoritative validation and returns the typed
            # rejection instead of allowing a pre-handler exception to escape.
            material = json.dumps(
                {"rejected": exc.code, "context_id": id(ctx), "action": action},
                sort_keys=True,
                separators=(",", ":"),
            )
            return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def perform(
        self,
        ctx: Any,
        *,
        tool_name: str,
        target_lease: object,
        action: Literal["focus", "request_close"],
        preview_digest: object,
        confirmation_summary: object,
        permission_receipt: PermissionReceipt | None,
        tool_args: dict[str, Any],
        execution_permit: object,
    ) -> dict[str, Any]:
        lease_id, lease = self._lease_for(ctx, target_lease)
        if action not in lease.allowed_actions:
            raise DesktopActionError("DA_APP_ACTION_DENIED", "application grant does not allow this action")
        expected_digest = self._digest(lease_id, lease, action)
        if not isinstance(preview_digest, str) or not secrets.compare_digest(preview_digest, expected_digest):
            raise DesktopActionError("DA_PREVIEW_MISMATCH", "preview digest does not match the live target")
        expected_summary = self._confirmation_summary(lease, action)
        if confirmation_summary != expected_summary:
            raise DesktopActionError("DA_CONFIRMATION_MISMATCH", "confirmation summary does not match the target")
        permit_nonce = _verify_execution_permit(
            execution_permit,
            tool_name=tool_name,
            parameters=tool_args,
            ctx=ctx,
            receipt=permission_receipt,
            claims=expected_digest,
        )
        if permit_nonce is None:
            raise DesktopActionError("DA_PERMISSION_REQUIRED", "a verified execution permit is required")
        if (
            permission_receipt is None
            or permission_receipt.decision != "allowed"
            or permission_receipt.reason_code != "user_allowed"
            or permission_receipt.decided_at is None
            or permission_receipt.capability_id != tool_name
        ):
            raise DesktopActionError("DA_PERMISSION_REQUIRED", "a fresh matching user permission is required")
        with self._lock:
            if permit_nonce in self._used_permits:
                raise DesktopActionError("DA_PERMISSION_REPLAY", "execution permit was already consumed")
            self._used_permits[permit_nonce] = None
            while len(self._used_permits) > MAX_USED_PERMITS:
                self._used_permits.popitem(last=False)
            # One live action consumes the lease before crossing the native boundary.
            lease.revoked = True
            fence = DesktopActionStopFence(
                issued_stop_epoch=self._stop_epoch,
                issued_feature_revision=self._feature_revision,
                issued_revocation_generation=self._revocation_generation,
                _state_provider=self._state,
                _authorization_provider=lambda: self._grant_is_active_for_lease(lease, action),
            )

        def transaction() -> tuple[NativeWindowTarget, NativeDesktopResult]:
            # Discovery, target revalidation, effect and the adapter's bounded
            # postcondition check are one serialized native transaction.
            current = next(
                (item for item in self.adapter.discover(limit=MAX_WINDOWS) if item.native_id == lease.target.native_id),
                None,
            )
            if current is None:
                raise DesktopActionError("DA_TARGET_GONE", "target window no longer exists")
            if not secrets.compare_digest(current.fingerprint, lease.target.fingerprint):
                raise DesktopActionError("DA_TARGET_RECYCLED", "target window identity changed")
            current_app_scope_id = self._app_scope_id(current)
            if not secrets.compare_digest(current_app_scope_id, lease.app_scope_id):
                raise DesktopActionError("DA_APP_SCOPE_MISMATCH", "target application identity changed")
            current_window_scope_id = self._window_scope_id(current)
            if not secrets.compare_digest(current_window_scope_id, lease.window_scope_id):
                raise DesktopActionError("DA_WINDOW_SCOPE_MISMATCH", "target window scope changed")
            with self._lock:
                self._expire_host_lease_locked()
                if not self._enabled:
                    raise DesktopActionError("DA_HOST_LEASE_EXPIRED", "desktop host lease is not active")
                if self._emergency_stopped:
                    raise DesktopActionError("DA_REARM_REQUIRED", "desktop actions require explicit rearm")
                grant = self._app_grants.get(lease.app_grant_id)
                if (
                    grant is None
                    or grant.revoked
                    or self._clock() >= grant.expires_at
                    or grant.feature_revision != self._feature_revision
                    or grant.revision != lease.app_grant_revision
                    or grant.app_scope_id != lease.app_scope_id
                ):
                    raise DesktopActionError("DA_APP_GRANT_EXPIRED", "application grant is no longer valid")
                if action not in grant.allowed_actions:
                    raise DesktopActionError("DA_APP_ACTION_DENIED", "application grant does not allow this action")
                if current_app_scope_id != lease.app_scope_id:
                    raise DesktopActionError("DA_APP_SCOPE_MISMATCH", "target application identity changed")
                if current_window_scope_id != lease.window_scope_id:
                    raise DesktopActionError("DA_WINDOW_SCOPE_MISMATCH", "target window scope changed")
                fence.raise_if_stopped()
            result = (
                self.adapter.focus(current, fence)
                if action == "focus"
                else self.adapter.request_close(current, fence)
            )
            return current, result

        transaction_result = self._run_driver(transaction, fence=fence, effect_possible=True)
        if (
            not isinstance(transaction_result, tuple)
            or len(transaction_result) != 2
            or not isinstance(transaction_result[0], NativeWindowTarget)
            or not isinstance(transaction_result[1], NativeDesktopResult)
        ):
            raise DesktopActionError("DA_ADAPTER_RESULT_INVALID", "adapter returned an invalid result")
        current, result = transaction_result
        if len(result.evidence) > 8 or any(
            not isinstance(key, str) or not isinstance(item, str)
            or len(key) > 64 or len(item) > 256
            for key, item in result.evidence.items()
        ):
            raise DesktopActionError("DA_ADAPTER_RESULT_INVALID", "adapter evidence exceeded bounds")
        fence.raise_if_stopped()
        before = {"title": _bounded_label(current.title), "app_label": _bounded_label(current.app_label)}
        safe_adapter_evidence, _redacted_paths = redact_permission_parameters(dict(result.evidence))
        return {
            "code": "DA_FOCUSED" if action == "focus" else "DA_CLOSE_REQUESTED",
            "action": action,
            "target_lease": lease_id,
            "evidence": {
                "before": before,
                "completion": result.category,
                "adapter": safe_adapter_evidence,
                "feature_revision": fence.issued_feature_revision,
                "stop_epoch": fence.issued_stop_epoch,
            },
        }


def _result(tool_name: str, callback: Callable[[], dict[str, Any]]) -> ToolResultEnvelope:
    try:
        value = callback()
        return ToolResultEnvelope(
            success=True,
            content=json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            source="builtin",
            tool_name=tool_name,
            data=value,
        )
    except DesktopActionError as exc:
        data: dict[str, Any] = {"code": exc.code}
        if exc.category:
            data["failure_category"] = exc.category
        return ToolResultEnvelope(
            success=False, content="", source="builtin", tool_name=tool_name,
            data=data, error=f"{exc.code}: {exc}",
            outcome="unknown_effect" if exc.code == "DA_OUTCOME_UNKNOWN" else "known_failure",
            retryable=False if exc.code == "DA_OUTCOME_UNKNOWN" else None,
        )


def _closed_handler(tool_name: str) -> ToolResultEnvelope:
    return _result(tool_name, lambda: (_ for _ in ()).throw(
        DesktopActionError("DA_HOST_BINDING_REQUIRED", "direct desktop handlers are disabled")
    ))


def _target_schema(*, with_preview: bool = False) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "target_lease": {"type": "string", "minLength": 16, "maxLength": 128},
    }
    required = ["target_lease"]
    if with_preview:
        properties["preview_digest"] = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
        properties["confirmation_summary"] = {
            "type": "object",
            "properties": {
                "action": {"enum": ["focus", "request_close"]},
                "application": {"type": "string", "minLength": 1, "maxLength": MAX_LABEL_LENGTH},
                "window_title": {"type": "string", "minLength": 1, "maxLength": MAX_LABEL_LENGTH},
            },
            "required": ["action", "application", "window_title"],
            "additionalProperties": False,
        }
        required.append("preview_digest")
        required.append("confirmation_summary")
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def register_desktop_action_tools(
    registry: ToolRegistry,
    *,
    adapter: DesktopActionAdapter | None = None,
    controller: DesktopActionController | None = None,
) -> DesktopActionAdapter:
    """Register scoped desktop tools; return the adapter for legacy runtime callers."""
    resolved = controller or DesktopActionController(adapter=adapter)

    registry.register(ToolDefinition(
        name="desktop.list_windows",
        description="List visible desktop windows as short-lived opaque target leases.",
        source="builtin",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        handler=lambda _args: _closed_handler("desktop.list_windows"),
        context_handler=lambda _args, ctx, _receipt, _permit: _result(
            "desktop.list_windows", lambda: resolved.list_targets(ctx)
        ),
        risk_level="safe",
        tags=["desktop", "window", "discovery", "lease"],
        scopes=["desktop:read"],
    ))
    registry.register(ToolDefinition(
        name="desktop.preview_action",
        description="Create a pure digest-bound preview for focus or graceful close.",
        source="builtin",
        parameters={
            "type": "object",
            "properties": {
                "target_lease": {"type": "string", "minLength": 16, "maxLength": 128},
                "action": {"enum": ["focus", "request_close"]},
            },
            "required": ["target_lease", "action"],
            "additionalProperties": False,
        },
        handler=lambda _args: _closed_handler("desktop.preview_action"),
        context_handler=lambda args, ctx, _receipt, _permit: _result(
            "desktop.preview_action",
            lambda: resolved.preview(ctx, target_lease=args.get("target_lease"), action=args.get("action")),
        ),
        risk_level="safe",
        tags=["desktop", "window", "preview", "dry-run"],
        scopes=["desktop:preview"],
    ))

    def register_live(tool_name: str, action: Literal["focus", "request_close"], *, close: bool) -> None:
        registry.register(ToolDefinition(
            name=tool_name,
            description=(
                "Request a graceful application close for one previewed target lease."
                if close else "Focus one previewed target lease after explicit application permission."
            ),
            source="builtin",
            parameters=_target_schema(with_preview=True),
            handler=lambda _args: _closed_handler(tool_name),
            context_handler=lambda args, ctx, receipt, permit: _result(
                tool_name,
                lambda: resolved.perform(
                    ctx,
                    tool_name=tool_name,
                    target_lease=args.get("target_lease"),
                    action=action,
                    preview_digest=args.get("preview_digest"),
                    confirmation_summary=args.get("confirmation_summary"),
                    permission_receipt=receipt,
                    tool_args=args,
                    execution_permit=permit,
                ),
            ),
            execution_permit_claims=lambda args, ctx: resolved._permit_claims(
                ctx, action, args.get("target_lease")
            ),
            require_confirm=True,
            risk_level="high" if close else "low",
            tags=["desktop", "window", "side-effect", "close" if close else "focus"],
            scopes=["desktop:close" if close else "desktop:focus"],
            allow_remembered_decision=False,
        ))

    register_live("desktop.focus_window", "focus", close=False)
    register_live("desktop.request_close", "request_close", close=True)
    # Compatibility alias retains the exact same lease/preview/permit contract.
    register_live("desktop.close_window", "request_close", close=True)
    return resolved.adapter
