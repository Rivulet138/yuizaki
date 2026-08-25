from __future__ import annotations

import asyncio
import inspect
import threading
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.agent.computer_use import ComputerUseController
from modules.agent.context import AgentPipelineResult, AgentRequestContext
from modules.agent.desktop_actions import (
    MAX_ACTIVE_APP_GRANTS,
    MAX_ACTIVE_LEASES,
    MAX_USED_PERMITS,
    DesktopActionController,
    DesktopActionError,
    DesktopActionScope,
    DesktopActionStopFence,
    NativeDesktopResult,
    NativeWindowTarget,
    WindowsDesktopActionAdapter,
    X11DesktopActionAdapter,
    register_desktop_action_tools,
)
from modules.agent.host_control import create_desktop_action_host_router
from modules.agent.permission_receipt import build_permission_receipt
from modules.agent.policy_engine import PolicyEngine
from modules.agent.runtime import create_agent_runtime
from modules.agent.tool_executor import ToolExecutor
from modules.agent.tool_registry import ToolRegistry
from modules.agent.turn_service import SemanticTurnRequest, TurnPorts, TurnService
from modules.system.backend_api_auth import verify_host_desktop_action_authorization

RAW_NATIVE_FIELDS = {
    "hwnd",
    "xid",
    "pid",
    "process_id",
    "process_path",
    "executable_path",
    "window_id",
}


def _desktop_tools():
    registry = ToolRegistry()
    register_desktop_action_tools(registry)
    return [
        tool
        for name in (
            "desktop.list_windows",
            "desktop.preview_action",
            "desktop.focus_window",
            "desktop.request_close",
            "desktop.close_window",
        )
        if (tool := registry.get(name)) is not None
    ]


def test_model_schemas_never_expose_native_window_or_process_identifiers() -> None:
    tools = _desktop_tools()

    assert tools
    for tool in tools:
        properties = set(tool.parameters.get("properties", {}))
        assert properties.isdisjoint(RAW_NATIVE_FIELDS), tool.name


def test_desktop_action_module_has_no_shell_process_or_force_kill_path() -> None:
    from modules.agent import desktop_actions

    source = inspect.getsource(desktop_actions).lower()

    for forbidden in (
        "import subprocess",
        "from subprocess",
        "os.system(",
        "shell=true",
        "taskkill",
        "terminateprocess",
        "sigkill",
        "wm_kill",
    ):
        assert forbidden not in source


def test_mouse_and_keyboard_injection_remain_unavailable_by_default() -> None:
    controller = ComputerUseController()

    assert controller.adapter is None


class FakeNativeAdapter:
    def __init__(self) -> None:
        self.target = NativeWindowTarget(
            native_id=0x1234,
            title="Editor",
            app_label="Code",
            fingerprint="fingerprint-v1",
        )
        self.effects: list[str] = []

    def discover(self, *, limit: int = 100) -> list[NativeWindowTarget]:
        del limit
        return [self.target]

    def focus(self, target: NativeWindowTarget, fence: DesktopActionStopFence) -> NativeDesktopResult:
        fence.raise_if_stopped()
        self.effects.append(f"focus:{target.native_id}")
        return NativeDesktopResult("completed", {"foreground_verified": "true"})

    def request_close(self, target: NativeWindowTarget, fence: DesktopActionStopFence) -> NativeDesktopResult:
        fence.raise_if_stopped()
        self.effects.append(f"close:{target.native_id}")
        return NativeDesktopResult("requested", {"observed_state": "still_open"})


def scope() -> DesktopActionScope:
    return DesktopActionScope(
        workspace_id="ws-1",
        session_id="session-1",
        turn_id="turn-1",
        request_id="request-1",
        generation_id="generation-1",
        interruption_epoch=4,
    )


def context(
    controller: DesktopActionController,
    selected: DesktopActionScope | None = None,
    *,
    authorize: bool = True,
) -> AgentRequestContext:
    current = selected or scope()
    ctx = AgentRequestContext(
        sid="socket-1",
        session_id=current.session_id,
        messages=[],
        workspace_id=current.workspace_id,
        request_id=current.request_id,
        permission_scope="socket:test",
        turn_id=current.turn_id,
        generation_id=current.generation_id,
        interruption_epoch=current.interruption_epoch,
        extra={},
    )
    controller.bind_context(ctx, trusted_scope=current)
    if authorize:
        discovery = controller.host_discover()
        for app in discovery["apps"]:
            controller.grant_app(
                app_id=app["app_id"],
                discovery_revision=discovery["discovery_revision"],
                allowed_actions=["focus", "request_close"],
            )
    return ctx


def lease_and_preview(
    controller: DesktopActionController,
    ctx: AgentRequestContext,
    *,
    action: str = "focus",
    ttl_seconds: float = 15.0,
) -> tuple[str, dict]:
    target_lease = controller.list_targets(ctx, ttl_seconds=ttl_seconds)["windows"][0]["target_lease"]
    return target_lease, controller.preview(ctx, target_lease=target_lease, action=action)


def registered_tools(controller: DesktopActionController) -> ToolRegistry:
    registry = ToolRegistry()
    register_desktop_action_tools(registry, controller=controller)
    return registry


def live_args(target_lease: str, preview: dict) -> dict:
    return {
        "target_lease": target_lease,
        "preview_digest": preview["preview_digest"],
        "confirmation_summary": preview["confirmation_summary"],
    }


@pytest.mark.parametrize(
    "field,spoofed",
    [
        ("workspace_id", "ws-2"),
        ("session_id", "session-2"),
        ("turn_id", "turn-2"),
        ("request_id", "request-2"),
        ("generation_id", "generation-2"),
        ("interruption_epoch", 5),
    ],
)
def test_target_lease_rejects_cross_field_scope_replay(field: str, spoofed: object) -> None:
    controller = DesktopActionController(adapter=FakeNativeAdapter(), enabled=True)
    original = context(controller)
    target_lease, _ = lease_and_preview(controller, original)
    replay = context(controller, replace(scope(), **{field: spoofed}), authorize=False)

    with pytest.raises(DesktopActionError) as rejected:
        controller.preview(replay, target_lease=target_lease, action="focus")

    assert rejected.value.code == "DA_SCOPE_MISMATCH"


def test_serialized_discovery_and_preview_hide_native_ids_fingerprints_pids_and_paths() -> None:
    adapter = FakeNativeAdapter()
    adapter.target = replace(adapter.target, fingerprint=r"C:\private\app.exe|pid=4242|xid=0x1234")
    controller = DesktopActionController(adapter=adapter, enabled=True)
    ctx = context(controller)
    issued = controller.list_targets(ctx)
    preview = controller.preview(ctx, target_lease=issued["windows"][0]["target_lease"], action="focus")
    serialized = repr({"issued": issued, "preview": preview}).lower()

    for private_value in ("0x1234", "4242", "private\\app.exe", "fingerprint"):
        assert private_value not in serialized


def test_recycled_native_target_is_rejected_before_adapter_effect(tmp_path) -> None:
    adapter = FakeNativeAdapter()
    controller = DesktopActionController(adapter=adapter, enabled=True)
    ctx = context(controller)
    target_lease, preview = lease_and_preview(controller, ctx)
    adapter.target = replace(adapter.target, fingerprint="fingerprint-recycled")
    registry = registered_tools(controller)
    executor = ToolExecutor(registry, PolicyEngine(store_file=tmp_path / "permissions.json"))

    async def allow(**payload) -> None:
        executor.policy_engine.resolve_pending(payload["request_id"], True)

    result = asyncio.run(executor.execute(
        "desktop.focus_window",
        live_args(target_lease, preview),
        permission_request_cb=allow,
        ctx=ctx,
    ))

    assert not result.success and result.data["code"] == "DA_TARGET_RECYCLED"
    assert adapter.effects == []


@pytest.mark.parametrize(
    ("replacement", "expected_code"),
    [
        ({"app_fingerprint": "app-v2"}, "DA_APP_SCOPE_MISMATCH"),
        ({"window_fingerprint": "window-v2"}, "DA_WINDOW_SCOPE_MISMATCH"),
    ],
)
def test_native_effect_revalidates_current_app_and_window_scope(
    tmp_path, replacement: dict[str, str], expected_code: str,
) -> None:
    adapter = FakeNativeAdapter()
    adapter.target = replace(
        adapter.target,
        app_fingerprint="app-v1",
        window_fingerprint="window-v1",
    )
    controller = DesktopActionController(adapter=adapter, enabled=True)
    ctx = context(controller)
    target_lease, preview = lease_and_preview(controller, ctx)
    adapter.target = replace(adapter.target, **replacement)
    executor = ToolExecutor(
        registered_tools(controller),
        PolicyEngine(store_file=tmp_path / "permissions.json"),
    )

    async def allow(**payload) -> None:
        executor.policy_engine.resolve_pending(payload["request_id"], True)

    result = asyncio.run(executor.execute(
        "desktop.focus_window",
        live_args(target_lease, preview),
        permission_request_cb=allow,
        ctx=ctx,
    ))

    assert not result.success and result.data["code"] == expected_code
    assert adapter.effects == []


def test_new_app_grant_fences_inflight_old_app_and_becomes_only_active_app(tmp_path) -> None:
    entered = threading.Event()
    release = threading.Event()

    class MultiAppBlockingAdapter(FakeNativeAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.target = replace(self.target, app_fingerprint="app-a", window_fingerprint="window-a")
            self.other = NativeWindowTarget(
                0x5678,
                "Other",
                "Other App",
                "fingerprint-other",
                app_fingerprint="app-b",
                window_fingerprint="window-b",
            )

        def discover(self, *, limit: int = 100) -> list[NativeWindowTarget]:
            del limit
            return [self.target, self.other]

        def focus(self, target: NativeWindowTarget, fence: DesktopActionStopFence) -> NativeDesktopResult:
            entered.set()
            assert release.wait(timeout=2)
            fence.raise_if_stopped()
            self.effects.append(f"focus:{target.native_id}")
            return NativeDesktopResult("completed")

    adapter = MultiAppBlockingAdapter()
    controller = DesktopActionController(adapter=adapter, enabled=True)
    ctx = context(controller, authorize=False)
    discovery = controller.host_discover()
    apps = {app["app_label"]: app for app in discovery["apps"]}
    controller.grant_app(
        app_id=apps["Code"]["app_id"],
        discovery_revision=discovery["discovery_revision"],
        allowed_actions=["focus"],
    )
    issued = controller.list_targets(ctx)
    assert [window["title"] for window in issued["windows"]] == ["Editor"]
    target_lease = issued["windows"][0]["target_lease"]
    preview = controller.preview(ctx, target_lease=target_lease, action="focus")
    policy = PolicyEngine(store_file=tmp_path / "permissions.json")

    async def scenario():
        async def allow(**payload) -> None:
            policy.resolve_pending(payload["request_id"], True)

        pending = asyncio.create_task(ToolExecutor(registered_tools(controller), policy).execute(
            "desktop.focus_window",
            live_args(target_lease, preview),
            permission_request_cb=allow,
            ctx=ctx,
        ))
        assert await asyncio.to_thread(entered.wait, 1)
        controller.grant_app(
            app_id=apps["Other App"]["app_id"],
            discovery_revision=discovery["discovery_revision"],
            allowed_actions=["focus"],
        )
        release.set()
        return await pending

    result = asyncio.run(scenario())

    assert not result.success and result.data["code"] == "DA_ACTION_REVOKED"
    assert adapter.effects == []
    with pytest.raises(DesktopActionError) as old_preview:
        controller.preview(ctx, target_lease=target_lease, action="focus")
    assert old_preview.value.code == "DA_TARGET_REVOKED"
    active = controller.list_targets(ctx)
    assert [window["title"] for window in active["windows"]] == ["Other"]
    new_preview = controller.preview(
        ctx,
        target_lease=active["windows"][0]["target_lease"],
        action="focus",
    )
    assert new_preview["code"] == "DA_PREVIEW"


def test_grant_expiry_inside_adapter_is_fenced_before_native_effect(tmp_path) -> None:
    now = [0.0]

    class ExpiringAdapter(FakeNativeAdapter):
        def focus(self, target: NativeWindowTarget, fence: DesktopActionStopFence) -> NativeDesktopResult:
            del target
            now[0] = 2.0
            fence.raise_if_stopped()
            self.effects.append("effect-after-expiry")
            return NativeDesktopResult("completed")

    adapter = ExpiringAdapter()
    controller = DesktopActionController(adapter=adapter, enabled=True, clock=lambda: now[0])
    ctx = context(controller, authorize=False)
    discovery = controller.host_discover()
    controller.grant_app(
        app_id=discovery["apps"][0]["app_id"],
        discovery_revision=discovery["discovery_revision"],
        allowed_actions=["focus"],
        ttl_seconds=1,
    )
    target_lease, preview = lease_and_preview(controller, ctx)
    policy = PolicyEngine(store_file=tmp_path / "permissions.json")

    async def allow(**payload) -> None:
        policy.resolve_pending(payload["request_id"], True)

    result = asyncio.run(ToolExecutor(registered_tools(controller), policy).execute(
        "desktop.focus_window",
        live_args(target_lease, preview),
        permission_request_cb=allow,
        ctx=ctx,
    ))

    assert not result.success and result.data["code"] == "DA_ACTION_REVOKED"
    assert adapter.effects == []


def test_preview_digest_cannot_be_replayed_for_a_different_action() -> None:
    controller = DesktopActionController(adapter=FakeNativeAdapter(), enabled=True)
    ctx = context(controller)
    target_lease, preview = lease_and_preview(controller, ctx, action="request_close")

    with pytest.raises(DesktopActionError) as rejected:
        controller.perform(
            ctx,
            tool_name="desktop.focus_window",
            target_lease=target_lease,
            action="focus",
            preview_digest=preview["preview_digest"],
            confirmation_summary=preview["confirmation_summary"],
            permission_receipt=None,
            tool_args=live_args(target_lease, preview),
            execution_permit=None,
        )

    assert rejected.value.code == "DA_PREVIEW_MISMATCH"


def test_expired_target_lease_is_rejected() -> None:
    now = [10.0]
    controller = DesktopActionController(adapter=FakeNativeAdapter(), enabled=True, clock=lambda: now[0])
    ctx = context(controller)
    target_lease, _ = lease_and_preview(controller, ctx, ttl_seconds=1.0)
    now[0] = 11.0

    with pytest.raises(DesktopActionError) as rejected:
        controller.preview(ctx, target_lease=target_lease, action="focus")

    assert rejected.value.code == "DA_TARGET_EXPIRED"


@pytest.mark.parametrize("fence", ["target", "revision", "stop"])
def test_revoke_revision_and_stop_each_invalidate_existing_target_lease(fence: str) -> None:
    controller = DesktopActionController(adapter=FakeNativeAdapter(), enabled=True)
    ctx = context(controller)
    target_lease, _ = lease_and_preview(controller, ctx)
    if fence == "target":
        controller.revoke_target(target_lease)
    elif fence == "revision":
        controller.rearm()
    else:
        controller.emergency_stop()
    if fence != "stop":
        controller.bind_context(ctx, trusted_scope=scope())

    with pytest.raises(DesktopActionError) as rejected:
        controller.preview(ctx, target_lease=target_lease, action="focus")

    assert rejected.value.code == ("DA_HOST_BINDING_REQUIRED" if fence == "stop" else "DA_TARGET_REVOKED")


def test_direct_handler_and_forged_receipt_cannot_reach_native_adapter() -> None:
    adapter = FakeNativeAdapter()
    controller = DesktopActionController(adapter=adapter, enabled=True)
    ctx = context(controller)
    target_lease, preview = lease_and_preview(controller, ctx)
    tool = registered_tools(controller).get("desktop.focus_window")
    assert tool is not None and tool.context_handler is not None
    args = live_args(target_lease, preview)
    receipt = build_permission_receipt(
        agent_request_id="request-1",
        decision="allowed",
        reason_code="user_allowed",
        retryable=True,
        permission_scope="socket:test",
        capability_id=tool.name,
        capability_type="tool",
        capability_kind="builtin-tool",
        risk_level=tool.risk_level,
        parameters=args,
        decided_at=datetime.now(UTC).isoformat(),
    )

    direct = tool.handler(args)
    forged = tool.context_handler(args, ctx, receipt, object())

    assert direct.data["code"] == "DA_HOST_BINDING_REQUIRED"
    assert forged.data["code"] == "DA_PERMISSION_REQUIRED"
    assert adapter.effects == []


def test_remembered_allow_cannot_bypass_fresh_confirmation(tmp_path) -> None:
    adapter = FakeNativeAdapter()
    controller = DesktopActionController(adapter=adapter, enabled=True)
    ctx = context(controller)
    target_lease, preview = lease_and_preview(controller, ctx)
    registry = registered_tools(controller)
    policy = PolicyEngine(store_file=tmp_path / "permissions.json")
    policy._remembered["desktop.focus_window::socket:test"] = True

    result = asyncio.run(ToolExecutor(registry, policy).execute(
        "desktop.focus_window",
        live_args(target_lease, preview),
        ctx=ctx,
    ))

    assert not result.success
    assert result.error and "requires user confirmation" in result.error
    assert adapter.effects == []


def test_execution_permit_replay_never_reaches_adapter_twice(tmp_path) -> None:
    adapter = FakeNativeAdapter()
    controller = DesktopActionController(adapter=adapter, enabled=True)
    ctx = context(controller)
    target_lease, preview = lease_and_preview(controller, ctx)
    registry = registered_tools(controller)
    tool = registry.get("desktop.focus_window")
    assert tool is not None and tool.context_handler is not None
    args = live_args(target_lease, preview)
    original = tool.context_handler
    captured: list[object] = []

    def capture(tool_args, bound_ctx, receipt, execution_permit):
        captured.append(execution_permit)
        return original(tool_args, bound_ctx, receipt, execution_permit)

    tool.context_handler = capture
    policy = PolicyEngine(store_file=tmp_path / "permissions.json")

    async def execute_once():
        async def allow(**payload) -> None:
            policy.resolve_pending(payload["request_id"], True)

        return await ToolExecutor(registry, policy).execute(
            tool.name, args, permission_request_cb=allow, ctx=ctx,
        )

    first = asyncio.run(execute_once())
    tool.context_handler = original
    replay = original(args, ctx, first.permission_receipt, captured[0])

    assert first.success
    assert not replay.success
    assert len(adapter.effects) == 1


def test_emergency_stop_fences_blocking_adapter_late_completion(tmp_path) -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingAdapter(FakeNativeAdapter):
        def focus(self, target: NativeWindowTarget, fence: DesktopActionStopFence) -> NativeDesktopResult:
            del target
            entered.set()
            assert release.wait(timeout=2)
            fence.raise_if_stopped()
            self.effects.append("late-focus")
            return NativeDesktopResult("completed")

    adapter = BlockingAdapter()
    controller = DesktopActionController(adapter=adapter, enabled=True)
    ctx = context(controller)
    target_lease, preview = lease_and_preview(controller, ctx)
    registry = registered_tools(controller)
    policy = PolicyEngine(store_file=tmp_path / "permissions.json")

    async def scenario():
        async def allow(**payload) -> None:
            policy.resolve_pending(payload["request_id"], True)

        pending = asyncio.create_task(ToolExecutor(registry, policy).execute(
            "desktop.focus_window",
            live_args(target_lease, preview),
            permission_request_cb=allow,
            ctx=ctx,
        ))
        assert await asyncio.to_thread(entered.wait, 1)
        controller.emergency_stop()
        release.set()
        return await pending

    result = asyncio.run(scenario())

    assert not result.success and result.data["code"] == "DA_EMERGENCY_STOPPED"
    assert adapter.effects == []


class _WindowsPostconditionProbe(WindowsDesktopActionAdapter):
    def __init__(self, user32) -> None:
        self._user32 = user32
        self._close_observation_seconds = 0.0

    def _revalidate(self, target: NativeWindowTarget) -> NativeWindowTarget:
        return target


class _X11PostconditionProbe(X11DesktopActionAdapter):
    def __init__(self, x11, target: NativeWindowTarget, *, close_observation_seconds: float = 0.0) -> None:
        self._x11 = x11
        self._display = 1
        self._target_value: NativeWindowTarget | None = target
        self._close_observation_seconds = close_observation_seconds
        self._lock = threading.Lock()

    def discover(self, *, limit: int = 100) -> list[NativeWindowTarget]:
        del limit
        return [self._target_value] if self._target_value is not None else []

    def _target(self, window: int) -> NativeWindowTarget | None:
        if self._target_value is not None and self._target_value.native_id == window:
            return self._target_value
        return None

    def _revalidate(self, target: NativeWindowTarget) -> NativeWindowTarget:
        return target


@pytest.mark.parametrize("process_id", [0, 4242])
def test_windows_failed_process_identity_query_isolated_per_window(process_id: int) -> None:
    class FailedKernel32:
        @staticmethod
        def OpenProcess(_access, _inherit, _process_id):
            return 0

    adapter = WindowsDesktopActionAdapter.__new__(WindowsDesktopActionAdapter)
    adapter._kernel32 = FailedKernel32()

    first = adapter._process_image_identity(process_id, "Chrome_WidgetWin_1", 0x1001)
    second = adapter._process_image_identity(process_id, "Chrome_WidgetWin_1", 0x1002)

    assert first != second


def test_windows_process_image_identity_still_groups_windows_from_same_image() -> None:
    class ImageKernel32:
        @staticmethod
        def OpenProcess(_access, _inherit, _process_id):
            return 1

        @staticmethod
        def QueryFullProcessImageNameW(_process, _flags, buffer, _size):
            buffer.value = r"C:\Program Files\App\app.exe"
            return 1

        @staticmethod
        def CloseHandle(_process):
            return 1

    adapter = WindowsDesktopActionAdapter.__new__(WindowsDesktopActionAdapter)
    adapter._kernel32 = ImageKernel32()

    first = adapter._process_image_identity(100, "SharedClass", 0x1001)
    second = adapter._process_image_identity(200, "SharedClass", 0x1002)

    assert first == second


def test_windows_focus_requires_verified_foreground_postcondition() -> None:
    class User32:
        SetForegroundWindow = staticmethod(lambda _native_id: 1)
        GetForegroundWindow = staticmethod(lambda: 999)

    adapter = _WindowsPostconditionProbe(User32())
    target = FakeNativeAdapter().target
    fence = DesktopActionStopFence(0, 1, 0, lambda: (0, 1, 0, True, False))

    with pytest.raises(DesktopActionError) as rejected:
        adapter.focus(target, fence)

    assert rejected.value.code == "DA_POSTCONDITION_FAILED"


def test_windows_close_uses_graceful_wm_close_and_reports_observed_state() -> None:
    posted: list[tuple[int, int]] = []

    class User32:
        IsWindow = staticmethod(lambda _native_id: 1)
        PostMessageW = staticmethod(lambda native_id, message, _wparam, _lparam: posted.append((native_id, message)) or 1)

    adapter = _WindowsPostconditionProbe(User32())
    target = FakeNativeAdapter().target
    fence = DesktopActionStopFence(0, 1, 0, lambda: (0, 1, 0, True, False))

    result = adapter.request_close(target, fence)

    assert posted == [(target.native_id, WindowsDesktopActionAdapter.WM_CLOSE)]
    assert result.evidence == {"message": "WM_CLOSE", "observed_state": "still_open"}


def test_x11_focus_requires_verified_input_focus_postcondition() -> None:
    class X11:
        XSetInputFocus = staticmethod(lambda _display, _native_id, _revert, _time: 1)
        XFlush = staticmethod(lambda _display: 1)

        @staticmethod
        def XGetInputFocus(_display, focused, _revert) -> int:
            focused._obj.value = 999
            return 1

    target = FakeNativeAdapter().target
    adapter = _X11PostconditionProbe(X11(), target)
    fence = DesktopActionStopFence(0, 1, 0, lambda: (0, 1, 0, True, False))

    with pytest.raises(DesktopActionError) as rejected:
        adapter.focus(target, fence)

    assert rejected.value.code == "DA_POSTCONDITION_FAILED"


@pytest.mark.parametrize("target_after_send,expected_state", [(True, "still_open"), (False, "closed")])
def test_x11_close_reports_observed_window_state(target_after_send: bool, expected_state: str) -> None:
    sent: list[int] = []

    class X11:
        XInternAtom = staticmethod(lambda _display, name, _only_if_exists: 1 if name == b"WM_PROTOCOLS" else 2)
        XFlush = staticmethod(lambda _display: 1)

        @staticmethod
        def XSendEvent(_display, native_id, _propagate, _event_mask, _event) -> int:
            sent.append(int(native_id.value))
            return 1

    target = FakeNativeAdapter().target
    adapter = _X11PostconditionProbe(X11(), target, close_observation_seconds=0.02)
    if not target_after_send:
        original_flush = adapter._x11.XFlush

        def close_after_flush(display) -> int:
            adapter._target_value = None
            return original_flush(display)

        adapter._x11.XFlush = close_after_flush
    fence = DesktopActionStopFence(0, 1, 0, lambda: (0, 1, 0, True, False))

    result = adapter.request_close(target, fence)

    assert sent == [target.native_id]
    assert result.evidence == {"message": "WM_DELETE_WINDOW", "observed_state": expected_state}


def test_x11_focus_timeout_after_native_effect_is_unknown_and_not_retryable(tmp_path) -> None:
    entered_postcondition = threading.Event()
    release = threading.Event()
    effects: list[int] = []

    class X11:
        XFlush = staticmethod(lambda _display: 1)

        @staticmethod
        def XSetInputFocus(_display, native_id, _revert, _time) -> int:
            effects.append(int(native_id.value))
            return 1

        @staticmethod
        def XGetInputFocus(_display, focused, _revert) -> int:
            entered_postcondition.set()
            assert release.wait(timeout=2)
            focused._obj.value = effects[-1]
            return 1

    target = FakeNativeAdapter().target
    adapter = _X11PostconditionProbe(X11(), target)
    controller = DesktopActionController(adapter=adapter, enabled=True, action_timeout_seconds=0.05)
    ctx = context(controller)
    target_lease, preview = lease_and_preview(controller, ctx)
    policy = PolicyEngine(store_file=tmp_path / "permissions.json")

    async def execute():
        async def allow(**payload) -> None:
            policy.resolve_pending(payload["request_id"], True)

        return await ToolExecutor(registered_tools(controller), policy).execute(
            "desktop.focus_window", live_args(target_lease, preview), permission_request_cb=allow, ctx=ctx,
        )

    try:
        result = asyncio.run(execute())
        assert entered_postcondition.is_set()
    finally:
        release.set()

    assert effects == [target.native_id]
    assert not result.success and result.data["code"] == "DA_OUTCOME_UNKNOWN"
    assert result.outcome == "unknown_effect"
    assert result.retryable is False


@pytest.mark.parametrize(
    "session_type,display,library,expected_code",
    [
        ("wayland", ":0", "libX11.so", "DA_WAYLAND_UNSUPPORTED"),
        ("x11", "", "libX11.so", "DA_X11_UNAVAILABLE"),
        ("x11", ":0", None, "DA_X11_UNAVAILABLE"),
    ],
)
def test_linux_wayland_missing_display_and_missing_x11_library_fail_closed(
    monkeypatch,
    session_type: str,
    display: str,
    library: str | None,
    expected_code: str,
) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", session_type)
    if display:
        monkeypatch.setenv("DISPLAY", display)
    else:
        monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr("modules.agent.desktop_actions.ctypes.util.find_library", lambda _name: library)

    with pytest.raises(DesktopActionError) as rejected:
        X11DesktopActionAdapter()

    assert rejected.value.code == expected_code


def test_each_target_gets_private_app_and_window_scope_ids_that_never_serialize() -> None:
    adapter = FakeNativeAdapter()
    second = replace(adapter.target, native_id=0x5678, title="Terminal", fingerprint="fp-2")
    adapter.discover = lambda *, limit=100: [adapter.target, second]  # type: ignore[method-assign]
    controller = DesktopActionController(adapter=adapter, enabled=True)
    issued = controller.list_targets(context(controller))
    leases = controller._leases
    private_pairs = {
        (lease.app_scope_id, lease.window_scope_id)
        for lease in leases.values()
    }

    assert len(private_pairs) == 2
    assert all(app.startswith("das_app_") and window.startswith("das_window_") for app, window in private_pairs)
    serialized = repr(issued)
    assert "das_app_" not in serialized and "das_window_" not in serialized


def test_controller_stop_latch_rejects_enable_until_rearm_and_never_enables_native_input() -> None:
    controller = DesktopActionController(adapter=FakeNativeAdapter(), enabled=True)
    stopped = controller.emergency_stop()

    with pytest.raises(DesktopActionError) as rejected:
        controller.set_enabled(True)

    assert rejected.value.code == "DA_REARM_REQUIRED"
    assert stopped["enabled"] is False and stopped["emergency_stopped"] is True
    assert stopped["native_input_available"] is False
    assert controller.rearm()["emergency_stopped"] is False


def test_general_backend_token_is_rejected_and_distinct_private_host_token_is_accepted() -> None:
    assert verify_host_desktop_action_authorization(
        "Bearer backend-general", "desktop-private", "backend-general",
    ) == (False, "Invalid desktop action host token")
    assert verify_host_desktop_action_authorization(
        "Bearer desktop-private", "desktop-private", "backend-general",
    ) == (True, "")
    assert verify_host_desktop_action_authorization(
        "Bearer same-token", "same-token", "same-token",
    ) == (False, "Desktop action host token must be distinct")


def test_discovery_timeout_is_bounded_and_does_not_latch_possible_effect() -> None:
    release = threading.Event()

    class BlockingDiscovery(FakeNativeAdapter):
        def discover(self, *, limit: int = 100) -> list[NativeWindowTarget]:
            del limit
            assert release.wait(timeout=2)
            return [self.target]

    controller = DesktopActionController(
        adapter=BlockingDiscovery(), enabled=True, action_timeout_seconds=0.05,
    )
    ctx = context(controller, authorize=False)
    started = __import__("time").monotonic()
    try:
        with pytest.raises(DesktopActionError) as rejected:
            controller.list_targets(ctx)
    finally:
        release.set()

    assert rejected.value.code == "DA_ACTION_TIMEOUT"
    assert __import__("time").monotonic() - started < 0.5
    assert controller.status()["enabled"] is True
    assert controller.status()["emergency_stopped"] is False


def test_confirmation_summary_tamper_is_rejected_before_native_effect(tmp_path) -> None:
    adapter = FakeNativeAdapter()
    controller = DesktopActionController(adapter=adapter, enabled=True)
    ctx = context(controller)
    target_lease, preview = lease_and_preview(controller, ctx)
    args = live_args(target_lease, preview)
    args["confirmation_summary"] = {
        **args["confirmation_summary"],
        "window_title": "Attacker substituted window",
    }
    policy = PolicyEngine(store_file=tmp_path / "permissions.json")

    async def allow(**payload) -> None:
        assert payload["args"]["confirmation_summary"]["window_title"] == "Attacker substituted window"
        policy.resolve_pending(payload["request_id"], True)

    result = asyncio.run(ToolExecutor(registered_tools(controller), policy).execute(
        "desktop.focus_window", args, permission_request_cb=allow, ctx=ctx,
    ))

    assert not result.success and result.data["code"] == "DA_CONFIRMATION_MISMATCH"
    assert adapter.effects == []


def test_revoke_fences_inflight_action_without_late_success(tmp_path) -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingEffect(FakeNativeAdapter):
        def focus(self, target: NativeWindowTarget, fence: DesktopActionStopFence) -> NativeDesktopResult:
            del target
            entered.set()
            assert release.wait(timeout=2)
            fence.raise_if_stopped()
            self.effects.append("late-success")
            return NativeDesktopResult("completed")

    adapter = BlockingEffect()
    controller = DesktopActionController(adapter=adapter, enabled=True, action_timeout_seconds=1.0)
    ctx = context(controller)
    target_lease, preview = lease_and_preview(controller, ctx)
    policy = PolicyEngine(store_file=tmp_path / "permissions.json")

    async def scenario():
        async def allow(**payload) -> None:
            policy.resolve_pending(payload["request_id"], True)

        pending = asyncio.create_task(ToolExecutor(registered_tools(controller), policy).execute(
            "desktop.focus_window", live_args(target_lease, preview), permission_request_cb=allow, ctx=ctx,
        ))
        assert await asyncio.to_thread(entered.wait, 1)
        controller.revoke_all()
        release.set()
        return await pending

    result = asyncio.run(scenario())

    assert not result.success and result.data["code"] == "DA_ACTION_REVOKED"
    assert adapter.effects == []


def test_effect_timeout_latches_outcome_unknown_and_never_reports_late_success(tmp_path) -> None:
    entered = threading.Event()
    release = threading.Event()

    class UncooperativeEffect(FakeNativeAdapter):
        def focus(self, target: NativeWindowTarget, fence: DesktopActionStopFence) -> NativeDesktopResult:
            del target, fence
            entered.set()
            assert release.wait(timeout=2)
            self.effects.append("native-returned-late")
            return NativeDesktopResult("completed")

    adapter = UncooperativeEffect()
    controller = DesktopActionController(adapter=adapter, enabled=True, action_timeout_seconds=0.05)
    ctx = context(controller)
    target_lease, preview = lease_and_preview(controller, ctx)
    policy = PolicyEngine(store_file=tmp_path / "permissions.json")

    async def execute():
        async def allow(**payload) -> None:
            policy.resolve_pending(payload["request_id"], True)

        return await ToolExecutor(registered_tools(controller), policy).execute(
            "desktop.focus_window", live_args(target_lease, preview), permission_request_cb=allow, ctx=ctx,
        )

    result = asyncio.run(execute())
    assert entered.is_set()
    release.set()
    threading.Event().wait(0.05)

    assert not result.success and result.data["code"] == "DA_OUTCOME_UNKNOWN"
    assert controller.status()["enabled"] is False
    assert controller.status()["emergency_stopped"] is True
    assert result.content == ""


def test_production_turn_service_binder_supports_discovery_preview_and_live_permit(tmp_path) -> None:
    adapter = FakeNativeAdapter()
    policy = PolicyEngine(store_file=tmp_path / "permissions.json")
    runtime = create_agent_runtime(
        schedule_context_factory=lambda _item: None,
        policy_engine=policy,
        desktop_adapter=adapter,
    )
    controller = runtime.desktop_action_controller
    assert controller is not None and runtime.turn_service is not None
    controller.rearm()
    discovery = controller.host_discover()
    controller.grant_app(
        app_id=discovery["apps"][0]["app_id"],
        discovery_revision=discovery["discovery_revision"],
        allowed_actions=["focus", "request_close"],
    )
    observed_confirmation: list[dict] = []

    async def run(bound_ctx: AgentRequestContext) -> AgentPipelineResult:
        listed = await runtime.tool_executor.execute("desktop.list_windows", {}, ctx=bound_ctx)
        assert listed.success
        target_lease = listed.data["windows"][0]["target_lease"]
        preview = await runtime.tool_executor.execute(
            "desktop.preview_action", {"target_lease": target_lease, "action": "focus"}, ctx=bound_ctx,
        )
        assert preview.success
        args = live_args(target_lease, preview.data)

        async def allow(**payload) -> None:
            observed_confirmation.append(payload["args"]["confirmation_summary"])
            policy.resolve_pending(payload["request_id"], True)

        live = await runtime.tool_executor.execute(
            "desktop.focus_window", args, permission_request_cb=allow, ctx=bound_ctx,
        )
        assert live.success and live.data["code"] == "DA_FOCUSED"
        return AgentPipelineResult(reply="desktop chain complete")

    binder = runtime.turn_service.ports.bind_context
    assert binder is not None
    service = TurnService(TurnPorts(run=run, bind_context=binder))
    commit = asyncio.run(service.execute("socket", SemanticTurnRequest(
        session_id="session-prod",
        workspace_id="workspace-prod",
        request_id="request-prod",
        turn_id="turn-prod",
        generation_id="generation-prod",
        interruption_epoch=8,
        messages=[{"role": "user", "content": "focus the editor"}],
    )))

    assert commit.result.reply == "desktop chain complete"
    assert commit.context.turn_id == "turn-prod"
    assert commit.context.generation_id == "generation-prod"
    assert commit.context.interruption_epoch == 8
    assert observed_confirmation == [{"action": "focus", "application": "Code", "window_title": "Editor"}]
    assert adapter.effects == ["focus:4660"]


def test_adapter_exception_is_normalized_without_leaking_secret_details() -> None:
    secret = "password=correct-horse-battery-staple C:\\private\\token.txt"

    class LeakingAdapter(FakeNativeAdapter):
        def discover(self, *, limit: int = 100) -> list[NativeWindowTarget]:
            del limit
            raise RuntimeError(secret)

    controller = DesktopActionController(adapter=LeakingAdapter(), enabled=True)
    ctx = context(controller, authorize=False)

    with pytest.raises(DesktopActionError) as rejected:
        controller.list_targets(ctx)

    assert rejected.value.code == "DA_ADAPTER_FAILURE"
    assert rejected.value.category == "adapter_error"
    assert secret not in str(rejected.value)
    assert "correct-horse-battery-staple" not in repr(rejected.value)


def test_target_lease_store_prunes_expired_entries_and_stays_bounded() -> None:
    now = [10.0]
    controller = DesktopActionController(
        adapter=FakeNativeAdapter(), enabled=True, clock=lambda: now[0],
    )
    ctx = context(controller)
    expired_lease = controller.list_targets(ctx, ttl_seconds=1.0)["windows"][0]["target_lease"]

    now[0] = 12.0
    controller.list_targets(ctx)
    for _ in range(MAX_ACTIVE_LEASES):
        controller.list_targets(ctx)

    assert expired_lease not in controller._leases
    assert len(controller._leases) == MAX_ACTIVE_LEASES


def test_used_execution_permit_store_evicts_oldest_entry_at_its_cap(tmp_path) -> None:
    controller = DesktopActionController(adapter=FakeNativeAdapter(), enabled=True)
    ctx = context(controller)
    target_lease, preview = lease_and_preview(controller, ctx)
    for index in range(MAX_USED_PERMITS):
        controller._used_permits[f"seed-permit-{index}"] = None
    policy = PolicyEngine(store_file=tmp_path / "permissions.json")

    async def allow(**payload) -> None:
        policy.resolve_pending(payload["request_id"], True)

    result = asyncio.run(ToolExecutor(registered_tools(controller), policy).execute(
        "desktop.focus_window",
        live_args(target_lease, preview),
        permission_request_cb=allow,
        ctx=ctx,
    ))

    assert result.success
    assert len(controller._used_permits) == MAX_USED_PERMITS
    assert "seed-permit-0" not in controller._used_permits
    assert "seed-permit-1" in controller._used_permits


def test_model_discovery_without_host_app_grant_leaks_no_window_title() -> None:
    controller = DesktopActionController(adapter=FakeNativeAdapter(), enabled=True)
    ctx = context(controller, authorize=False)

    result = registered_tools(controller).get("desktop.list_windows")
    assert result is not None and result.context_handler is not None
    rejected = result.context_handler({}, ctx, None, None)

    assert not rejected.success
    assert rejected.data == {"code": "DA_APP_GRANT_REQUIRED"}
    assert "Editor" not in rejected.content
    assert "Editor" not in (rejected.error or "")


def test_host_hmac_identity_groups_same_app_and_isolates_other_electron_app() -> None:
    class MultiAppAdapter(FakeNativeAdapter):
        def discover(self, *, limit: int = 100) -> list[NativeWindowTarget]:
            del limit
            return [
                NativeWindowTarget(1, "Project A", "Chromium", "window-a", app_fingerprint="image:C:/apps/one.exe"),
                NativeWindowTarget(2, "Project B", "Chromium", "window-b", app_fingerprint="image:C:/apps/one.exe"),
                NativeWindowTarget(3, "Other App", "Chromium", "window-c", app_fingerprint="image:C:/apps/two.exe"),
            ]

    controller = DesktopActionController(
        adapter=MultiAppAdapter(), enabled=True, identity_secret=b"h" * 32,
    )
    first = controller.host_discover()
    second = controller.host_discover()

    assert len(first["apps"]) == 2
    grouped = next(app for app in first["apps"] if len(app["windows"]) == 2)
    other = next(app for app in first["apps"] if len(app["windows"]) == 1)
    assert grouped["app_id"] != other["app_id"]
    assert {app["app_id"] for app in first["apps"]} == {app["app_id"] for app in second["apps"]}
    serialized = repr(first)
    assert "image:C:/apps" not in serialized
    assert "native_id" not in serialized


def test_app_grant_rejects_stale_discovery_and_filters_model_titles() -> None:
    class MultiAppAdapter(FakeNativeAdapter):
        def discover(self, *, limit: int = 100) -> list[NativeWindowTarget]:
            del limit
            return [
                NativeWindowTarget(1, "Allowed title", "Allowed", "window-a", app_fingerprint="app-a"),
                NativeWindowTarget(2, "Secret other title", "Other", "window-b", app_fingerprint="app-b"),
            ]

    controller = DesktopActionController(adapter=MultiAppAdapter(), enabled=True)
    ctx = context(controller, authorize=False)
    stale = controller.host_discover()
    fresh = controller.host_discover()
    with pytest.raises(DesktopActionError) as replayed:
        controller.grant_app(
            app_id=stale["apps"][0]["app_id"],
            discovery_revision=stale["discovery_revision"],
            allowed_actions=["focus"],
        )
    assert replayed.value.code == "DA_DISCOVERY_STALE"

    allowed_app = next(app for app in fresh["apps"] if app["app_label"] == "Allowed")
    controller.grant_app(
        app_id=allowed_app["app_id"],
        discovery_revision=fresh["discovery_revision"],
        allowed_actions=["focus"],
    )
    listed = controller.list_targets(ctx)
    assert [window["title"] for window in listed["windows"]] == ["Allowed title"]
    lease = listed["windows"][0]["target_lease"]
    with pytest.raises(DesktopActionError) as denied:
        controller.preview(ctx, target_lease=lease, action="request_close")
    assert denied.value.code == "DA_APP_ACTION_DENIED"
    renewed_discovery = controller.host_discover()
    controller.grant_app(
        app_id=allowed_app["app_id"],
        discovery_revision=renewed_discovery["discovery_revision"],
        allowed_actions=["focus"],
    )
    with pytest.raises(DesktopActionError) as old_grant_replay:
        controller.preview(ctx, target_lease=lease, action="focus")
    assert old_grant_replay.value.code == "DA_TARGET_REVOKED"


def test_app_grant_store_prunes_mass_regrants_and_preserves_live_lease() -> None:
    now = [0.0]
    controller = DesktopActionController(
        adapter=FakeNativeAdapter(),
        enabled=True,
        clock=lambda: now[0],
    )
    ctx = context(controller, authorize=False)
    discovery = controller.host_discover(ttl_seconds=15)
    app_id = discovery["apps"][0]["app_id"]

    for _ in range(MAX_ACTIVE_APP_GRANTS + 50):
        controller.grant_app(
            app_id=app_id,
            discovery_revision=discovery["discovery_revision"],
            allowed_actions=["focus"],
            ttl_seconds=0.0005,
        )
        now[0] += 0.001

    controller.grant_app(
        app_id=app_id,
        discovery_revision=discovery["discovery_revision"],
        allowed_actions=["focus"],
        ttl_seconds=30,
    )
    issued = controller.list_targets(ctx)
    target_lease = issued["windows"][0]["target_lease"]
    preview = controller.preview(ctx, target_lease=target_lease, action="focus")

    assert len(controller._app_grants) <= MAX_ACTIVE_APP_GRANTS
    assert len(controller._app_grants) == 1
    assert preview["code"] == "DA_PREVIEW"


def test_private_host_heartbeat_route_rejects_backend_token_and_epoch_replay() -> None:
    now = [10.0]
    controller = DesktopActionController(adapter=FakeNativeAdapter(), clock=lambda: now[0])
    app = FastAPI()
    app.include_router(create_desktop_action_host_router(
        status=controller.status,
        enable=lambda **kwargs: controller.set_enabled(True, **kwargs),
        disable=lambda: controller.set_enabled(False),
        rearm=controller.rearm,
        stop=controller.emergency_stop,
        heartbeat=controller.heartbeat,
        discover=controller.host_discover,
        grant=controller.grant_app,
        host_token_provider=lambda: "host-secret",
        backend_token_provider=lambda: "backend-token",
    ))
    client = TestClient(app)
    enabled = client.post(
        "/api/desktop-actions/enable",
        json={"lease_ttl_seconds": 5},
        headers={"Authorization": "Bearer host-secret"},
    )
    epoch = enabled.json()["lease_epoch"]
    discovered = client.post(
        "/api/desktop-actions/discover",
        json={"ttl_seconds": 10},
        headers={"Authorization": "Bearer host-secret"},
    )
    assert discovered.status_code == 200
    discovery_body = discovered.json()
    app_id = discovery_body["apps"][0]["app_id"]
    assert app_id.startswith("das_app_")
    assert discovery_body["apps"][0]["windows"][0]["window_id"].startswith("das_window_")
    assert "4660" not in repr(discovery_body)
    granted = client.post(
        "/api/desktop-actions/grant",
        json={
            "app_id": app_id,
            "discovery_revision": discovery_body["discovery_revision"],
            "allowed_actions": ["focus"],
            "ttl_seconds": 10,
        },
        headers={"Authorization": "Bearer host-secret"},
    )
    assert granted.status_code == 200
    assert granted.json()["app_id"] == app_id
    assert client.post(
        "/api/desktop-actions/heartbeat",
        json={"lease_epoch": epoch, "lease_ttl_seconds": 5},
        headers={"Authorization": "Bearer backend-token"},
    ).status_code == 401
    renewed = client.post(
        "/api/desktop-actions/heartbeat",
        json={"lease_epoch": epoch, "lease_ttl_seconds": 5},
        headers={"Authorization": "Bearer host-secret"},
    )
    assert renewed.status_code == 200
    controller.emergency_stop()
    replay = client.post(
        "/api/desktop-actions/heartbeat",
        json={"lease_epoch": epoch, "lease_ttl_seconds": 5},
        headers={"Authorization": "Bearer host-secret"},
    )
    assert replay.status_code == 409


def test_discovery_and_grant_ttls_span_heartbeats_then_host_expiry_revokes_all() -> None:
    now = [0.0]
    adapter = FakeNativeAdapter()
    controller = DesktopActionController(adapter=adapter, clock=lambda: now[0])
    epoch = controller.rearm(lease_ttl_seconds=5)["lease_epoch"]
    ctx = context(controller, authorize=False)
    discovery = controller.host_discover(ttl_seconds=15)

    for timestamp in (4.0, 8.0, 12.0):
        now[0] = timestamp
        controller.heartbeat(lease_epoch=epoch, lease_ttl_seconds=5)

    app_id = discovery["apps"][0]["app_id"]
    grant = controller.grant_app(
        app_id=app_id,
        discovery_revision=discovery["discovery_revision"],
        allowed_actions=["focus"],
        ttl_seconds=30,
    )
    assert grant["expires_in_ms"] == 30_000

    for timestamp in (16.0, 20.0, 24.0, 28.0, 32.0, 36.0, 40.0):
        now[0] = timestamp
        controller.heartbeat(lease_epoch=epoch, lease_ttl_seconds=5)

    issued = controller.list_targets(ctx)
    assert [window["title"] for window in issued["windows"]] == ["Editor"]
    target_lease = issued["windows"][0]["target_lease"]
    preview = controller.preview(ctx, target_lease=target_lease, action="focus")

    now[0] = 46.0
    assert controller.status()["enabled"] is False
    assert controller._host_discovery is None
    assert all(grant.revoked for grant in controller._app_grants.values())
    assert all(lease.revoked for lease in controller._leases.values())
    assert controller._bindings == {}
    with pytest.raises(DesktopActionError):
        controller.list_targets(ctx)
    with pytest.raises(DesktopActionError):
        controller.preview(ctx, target_lease=target_lease, action="focus")
    assert preview["confirmation_summary"]["window_title"] == "Editor"
    assert adapter.effects == []


def test_host_lease_expiry_blocks_bind_list_preview_and_native_effect() -> None:
    now = [100.0]
    adapter = FakeNativeAdapter()
    controller = DesktopActionController(adapter=adapter, clock=lambda: now[0])
    controller.rearm(lease_ttl_seconds=1.0)
    ctx = context(controller)
    target_lease, _preview = lease_and_preview(controller, ctx)
    now[0] = 102.0

    assert controller.status()["enabled"] is False
    expired_ctx = AgentRequestContext(sid="expired", session_id="expired", messages=[])
    controller.bind_context(expired_ctx, trusted_scope=scope())
    with pytest.raises(DesktopActionError):
        controller.list_targets(expired_ctx)
    with pytest.raises(DesktopActionError):
        controller.list_targets(ctx)
    with pytest.raises(DesktopActionError):
        controller.preview(ctx, target_lease=target_lease, action="focus")
    assert adapter.effects == []


def test_host_lease_expiry_fences_inflight_effect_before_native_commit(tmp_path) -> None:
    now = [200.0]
    entered = threading.Event()
    release = threading.Event()

    class BlockingEffect(FakeNativeAdapter):
        def focus(self, target: NativeWindowTarget, fence: DesktopActionStopFence) -> NativeDesktopResult:
            del target
            entered.set()
            assert release.wait(timeout=2)
            fence.raise_if_stopped()
            self.effects.append("late-effect")
            return NativeDesktopResult("completed")

    adapter = BlockingEffect()
    controller = DesktopActionController(
        adapter=adapter, clock=lambda: now[0], action_timeout_seconds=1.0,
    )
    controller.rearm(lease_ttl_seconds=1.0)
    ctx = context(controller)
    target_lease, preview = lease_and_preview(controller, ctx)
    policy = PolicyEngine(store_file=tmp_path / "permissions.json")

    async def scenario():
        async def allow(**payload) -> None:
            policy.resolve_pending(payload["request_id"], True)

        pending = asyncio.create_task(ToolExecutor(registered_tools(controller), policy).execute(
            "desktop.focus_window", live_args(target_lease, preview), permission_request_cb=allow, ctx=ctx,
        ))
        assert await asyncio.to_thread(entered.wait, 1)
        now[0] = 202.0
        release.set()
        return await pending

    result = asyncio.run(scenario())
    assert not result.success
    assert adapter.effects == []
    assert controller.status()["enabled"] is False
