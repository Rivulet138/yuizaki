from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.agent.context import AgentPipelineResult
from modules.agent.desktop_actions import (
    DesktopActionController,
    DesktopActionError,
    DesktopActionScope,
    DesktopActionStopFence,
    NativeDesktopResult,
    NativeWindowTarget,
    SystemDesktopActionAdapter,
    X11DesktopActionAdapter,
    register_desktop_action_tools,
)
from modules.agent.host_control import create_desktop_action_host_router
from modules.agent.policy_engine import PolicyEngine
from modules.agent.runtime import create_agent_runtime
from modules.agent.tool_executor import ToolExecutor
from modules.agent.tool_registry import ToolRegistry
from modules.agent.turn_service import SemanticTurnRequest, TurnPorts, TurnService


@dataclass
class Context:
    marker: str = "trusted"
    extra: dict = field(default_factory=dict)


def scope(*, workspace: str = "workspace-1", request: str = "request-1") -> DesktopActionScope:
    return DesktopActionScope(
        workspace_id=workspace,
        session_id="session-1",
        turn_id="turn-1",
        request_id=request,
        generation_id="generation-1",
        interruption_epoch=3,
    )


def target(*, fingerprint: str = "fingerprint-1") -> NativeWindowTarget:
    return NativeWindowTarget(
        native_id=177,
        title="Editor",
        app_label="Code editor",
        fingerprint=fingerprint,
    )


class FakeNativeAdapter:
    def __init__(self) -> None:
        self.current = target()
        self.calls: list[str] = []

    def discover(self, *, limit: int = 100) -> list[NativeWindowTarget]:
        assert limit <= 100
        return [self.current]

    def focus(self, selected: NativeWindowTarget, fence: DesktopActionStopFence) -> NativeDesktopResult:
        fence.raise_if_stopped()
        assert selected == self.current
        self.calls.append("focus")
        return NativeDesktopResult("completed", {"foreground_verified": "true"})

    def request_close(self, selected: NativeWindowTarget, fence: DesktopActionStopFence) -> NativeDesktopResult:
        fence.raise_if_stopped()
        assert selected == self.current
        self.calls.append("request_close")
        return NativeDesktopResult("requested", {"observed_state": "still_open"})


def setup_controller(*, clock=None, timeout: float = 1.0):
    adapter = FakeNativeAdapter()
    controller = DesktopActionController(
        adapter=adapter,
        clock=clock or time.monotonic,
        action_timeout_seconds=timeout,
    )
    controller.rearm(lease_ttl_seconds=30.0)
    discovery = controller.host_discover()
    controller.grant_app(
        app_id=discovery["apps"][0]["app_id"],
        discovery_revision=discovery["discovery_revision"],
        allowed_actions=["focus", "request_close"],
    )
    ctx = Context()
    controller.bind_context(ctx, trusted_scope=scope())
    return controller, adapter, ctx


def issue_preview(controller: DesktopActionController, ctx: Context, action: str = "focus"):
    discovery = controller.host_discover()
    for app in discovery["apps"]:
        controller.grant_app(
            app_id=app["app_id"],
            discovery_revision=discovery["discovery_revision"],
            allowed_actions=["focus", "request_close"],
        )
    listed = controller.list_targets(ctx)
    lease = listed["windows"][0]["target_lease"]
    return lease, controller.preview(ctx, target_lease=lease, action=action)


def test_tool_schemas_are_lease_only_and_direct_handlers_fail_closed() -> None:
    registry = ToolRegistry()
    adapter = FakeNativeAdapter()
    returned = register_desktop_action_tools(registry, adapter=adapter)
    assert returned is adapter

    for name in (
        "desktop.list_windows",
        "desktop.preview_action",
        "desktop.focus_window",
        "desktop.request_close",
        "desktop.close_window",
    ):
        tool = registry.get(name)
        assert tool is not None
        properties = tool.parameters.get("properties", {})
        assert "window_id" not in properties
        assert "process_id" not in properties
        direct = tool.handler({})
        assert not direct.success and direct.data["code"] == "DA_HOST_BINDING_REQUIRED"

    assert registry.get("desktop.focus_window").require_confirm is True  # type: ignore[union-attr]
    close = registry.get("desktop.request_close")
    assert close is not None and close.risk_level == "high"
    assert close.require_confirm and close.allow_remembered_decision is False


def test_random_leases_hide_native_identifiers_and_preview_is_pure() -> None:
    controller, adapter, ctx = setup_controller()
    first = controller.list_targets(ctx)["windows"][0]
    second = controller.list_targets(ctx)["windows"][0]

    assert first["target_lease"].startswith("da_")
    assert first["target_lease"] != second["target_lease"]
    assert "177" not in str(first)
    assert "fingerprint" not in str(first)
    assert "pid" not in str(first).lower()
    preview = controller.preview(ctx, target_lease=first["target_lease"], action="focus")
    assert len(preview["preview_digest"]) == 64
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_live_focus_requires_tool_executor_and_consumes_lease(tmp_path) -> None:
    controller, adapter, ctx = setup_controller()
    lease, preview = issue_preview(controller, ctx)
    registry = ToolRegistry()
    register_desktop_action_tools(registry, controller=controller)
    policy = PolicyEngine(store_file=tmp_path / "permissions.json")
    executor = ToolExecutor(registry, policy)
    args = {
        "target_lease": lease,
        "preview_digest": preview["preview_digest"],
        "confirmation_summary": preview["confirmation_summary"],
    }

    direct = registry.get("desktop.focus_window").context_handler(args, ctx, None, None)  # type: ignore[union-attr]
    assert not direct.success and direct.data["code"] == "DA_PERMISSION_REQUIRED"

    async def allow(**payload) -> None:
        policy.resolve_pending(payload["request_id"], True)

    result = await executor.execute(
        "desktop.focus_window", args, ctx=ctx, permission_request_cb=allow,
    )
    assert result.success and result.data["code"] == "DA_FOCUSED"
    assert adapter.calls == ["focus"]
    replay = await executor.execute(
        "desktop.focus_window", args, ctx=ctx, permission_request_cb=allow,
    )
    assert not replay.success
    assert replay.data["code"] == "DA_TARGET_REVOKED"


@pytest.mark.asyncio
async def test_remembered_allow_cannot_bypass_fresh_close_confirmation(tmp_path) -> None:
    controller, adapter, ctx = setup_controller()
    lease, preview = issue_preview(controller, ctx, "request_close")
    registry = ToolRegistry()
    register_desktop_action_tools(registry, controller=controller)
    policy = PolicyEngine(store_file=tmp_path / "permissions.json")
    policy._remembered["desktop.request_close::default"] = True
    result = await ToolExecutor(registry, policy).execute(
        "desktop.request_close",
        {
            "target_lease": lease,
            "preview_digest": preview["preview_digest"],
            "confirmation_summary": preview["confirmation_summary"],
        },
        ctx=ctx,
    )
    assert not result.success
    assert result.error and "requires user confirmation" in result.error
    assert adapter.calls == []


def test_scope_replay_expiry_revision_and_preview_mismatch_fail_closed() -> None:
    now = [100.0]
    controller, adapter, ctx = setup_controller(clock=lambda: now[0])
    lease, preview = issue_preview(controller, ctx)

    other = Context("other")
    controller.bind_context(other, trusted_scope=scope(workspace="workspace-2"))
    with pytest.raises(DesktopActionError, match="another request scope") as cross_scope:
        controller.preview(other, target_lease=lease, action="focus")
    assert cross_scope.value.code == "DA_SCOPE_MISMATCH"

    with pytest.raises(DesktopActionError) as mismatch:
        controller.perform(
            ctx,
            tool_name="desktop.focus_window",
            target_lease=lease,
            action="focus",
            preview_digest="0" * 64,
            confirmation_summary=preview["confirmation_summary"],
            permission_receipt=None,
            tool_args={},
            execution_permit=None,
        )
    assert mismatch.value.code == "DA_PREVIEW_MISMATCH"

    now[0] += 16
    with pytest.raises(DesktopActionError) as expired:
        controller.preview(ctx, target_lease=lease, action="focus")
    assert expired.value.code == "DA_TARGET_EXPIRED"
    assert adapter.calls == []

    controller.bind_context(ctx, trusted_scope=scope())
    lease2, _ = issue_preview(controller, ctx)
    controller.set_enabled(False)
    with pytest.raises(DesktopActionError) as disabled:
        controller.preview(ctx, target_lease=lease2, action="focus")
    assert disabled.value.code in {"DA_HOST_BINDING_REQUIRED", "DA_FEATURE_DISABLED"}


@pytest.mark.asyncio
async def test_recycled_target_is_detected_immediately_before_effect(tmp_path) -> None:
    controller, adapter, ctx = setup_controller()
    lease, preview = issue_preview(controller, ctx)
    adapter.current = target(fingerprint="fingerprint-recycled")
    registry = ToolRegistry()
    register_desktop_action_tools(registry, controller=controller)
    policy = PolicyEngine(store_file=tmp_path / "permissions.json")

    async def allow(**payload) -> None:
        policy.resolve_pending(payload["request_id"], True)

    result = await ToolExecutor(registry, policy).execute(
        "desktop.focus_window",
        {
            "target_lease": lease,
            "preview_digest": preview["preview_digest"],
            "confirmation_summary": preview["confirmation_summary"],
        },
        ctx=ctx,
        permission_request_cb=allow,
    )
    assert not result.success and result.data["code"] == "DA_TARGET_RECYCLED"
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_emergency_stop_is_immediate_and_late_adapter_result_fails(tmp_path) -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingAdapter(FakeNativeAdapter):
        def focus(self, selected, fence):
            del selected
            entered.set()
            assert release.wait(timeout=2)
            fence.raise_if_stopped()
            return NativeDesktopResult("completed")

    adapter = BlockingAdapter()
    controller = DesktopActionController(adapter=adapter, action_timeout_seconds=2)
    controller.rearm()
    discovery = controller.host_discover()
    controller.grant_app(
        app_id=discovery["apps"][0]["app_id"],
        discovery_revision=discovery["discovery_revision"],
        allowed_actions=["focus", "request_close"],
    )
    ctx = Context()
    controller.bind_context(ctx, trusted_scope=scope())
    lease, preview = issue_preview(controller, ctx)
    registry = ToolRegistry()
    register_desktop_action_tools(registry, controller=controller)
    policy = PolicyEngine(store_file=tmp_path / "permissions.json")

    async def allow(**payload) -> None:
        policy.resolve_pending(payload["request_id"], True)

    result_box = []

    def execute() -> None:
        import asyncio

        result_box.append(asyncio.run(ToolExecutor(registry, policy).execute(
            "desktop.focus_window",
            {
                "target_lease": lease,
                "preview_digest": preview["preview_digest"],
                "confirmation_summary": preview["confirmation_summary"],
            },
            ctx=ctx,
            permission_request_cb=allow,
        )))

    thread = threading.Thread(target=execute)
    thread.start()
    assert entered.wait(timeout=1)
    started = time.perf_counter()
    status = controller.emergency_stop()
    assert time.perf_counter() - started < 0.1
    assert status["stop_epoch"] >= 2
    assert status["enabled"] is False
    assert status["emergency_stopped"] is True
    release.set()
    thread.join(timeout=2)
    assert result_box and not result_box[0].success
    assert result_box[0].data["code"] == "DA_EMERGENCY_STOPPED"


def test_system_adapter_raw_legacy_methods_are_disabled() -> None:
    adapter = SystemDesktopActionAdapter()
    with pytest.raises(DesktopActionError) as rejected:
        adapter.focus_window("0x123")
    assert rejected.value.code == "DA_HOST_BINDING_REQUIRED"


def test_pure_wayland_is_explicitly_unsupported(monkeypatch) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("DISPLAY", ":1")
    with pytest.raises(DesktopActionError) as rejected:
        X11DesktopActionAdapter()
    assert rejected.value.code == "DA_WAYLAND_UNSUPPORTED"


def test_runtime_registers_controller_and_keeps_injected_adapter(tmp_path) -> None:
    adapter = FakeNativeAdapter()
    runtime = create_agent_runtime(
        schedule_context_factory=lambda _item: None,
        policy_engine=PolicyEngine(store_file=tmp_path / "permissions.json"),
        desktop_adapter=adapter,
    )
    assert runtime.desktop_adapter is adapter
    assert runtime.desktop_action_controller is not None
    assert runtime.desktop_action_controller.adapter is adapter
    assert runtime.computer_use_controller is not None
    assert runtime.computer_use_controller.adapter is None


@pytest.mark.asyncio
async def test_production_turn_binder_reaches_scoped_tools_through_executor(tmp_path) -> None:
    adapter = FakeNativeAdapter()
    runtime = create_agent_runtime(
        schedule_context_factory=lambda _item: None,
        policy_engine=PolicyEngine(store_file=tmp_path / "permissions.json"),
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
    binder = runtime.turn_service.ports.bind_context
    assert binder is not None

    async def run(ctx):
        # Caller-extensible data cannot select or authorize a native target.
        assert ctx.extra["app_id"] == "attacker-selected-app"
        listed = await runtime.tool_executor.execute("desktop.list_windows", {}, ctx=ctx)
        assert listed.success
        target_lease = listed.data["windows"][0]["target_lease"]
        previewed = await runtime.tool_executor.execute(
            "desktop.preview_action",
            {"target_lease": target_lease, "action": "focus"},
            ctx=ctx,
        )
        assert previewed.success
        args = {
            "target_lease": target_lease,
            "preview_digest": previewed.data["preview_digest"],
            "confirmation_summary": previewed.data["confirmation_summary"],
        }

        async def allow(**payload) -> None:
            runtime.policy_engine.resolve_pending(payload["request_id"], True)

        focused = await runtime.tool_executor.execute(
            "desktop.focus_window", args, ctx=ctx, permission_request_cb=allow,
        )
        assert focused.success
        return AgentPipelineResult(reply=focused.data["code"])

    service = TurnService(TurnPorts(run=run, bind_context=binder))
    commit = await service.execute_socket(SemanticTurnRequest(
        workspace_id="workspace-production",
        session_id="session-production",
        request_id="request-production",
        turn_id="turn-production",
        generation_id="generation-production",
        interruption_epoch=7,
        messages=[{"role": "user", "content": "focus the editor"}],
        extra={"app_id": "attacker-selected-app", "window_id": "0x123"},
    ))

    assert commit.result.reply == "DA_FOCUSED"
    assert adapter.calls == ["focus"]
    assert "desktop_action" not in commit.context.extra


def test_stop_latches_until_explicit_rearm_and_reports_no_native_input() -> None:
    controller, _adapter, ctx = setup_controller()
    stopped = controller.emergency_stop()
    assert stopped["enabled"] is False
    assert stopped["emergency_stopped"] is True
    assert stopped["native_input_available"] is False
    with pytest.raises(DesktopActionError) as rejected:
        controller.set_enabled(True)
    assert rejected.value.code == "DA_REARM_REQUIRED"
    rearmed = controller.rearm()
    assert rearmed["enabled"] is True and rearmed["emergency_stopped"] is False
    # Rearm revokes old private bindings; a new semantic turn must bind again.
    with pytest.raises(DesktopActionError):
        controller.list_targets(ctx)


def test_discovery_timeout_is_bounded_without_claiming_an_effect() -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingDiscovery(FakeNativeAdapter):
        def discover(self, *, limit=100):
            del limit
            entered.set()
            release.wait(timeout=1)
            return [self.current]

    controller = DesktopActionController(
        adapter=BlockingDiscovery(), enabled=True, action_timeout_seconds=0.05,
    )
    ctx = Context()
    controller.bind_context(ctx, trusted_scope=scope())
    with pytest.raises(DesktopActionError) as rejected:
        controller.list_targets(ctx)
    release.set()
    assert entered.is_set()
    assert rejected.value.code == "DA_ACTION_TIMEOUT"
    assert controller.status()["emergency_stopped"] is False


def test_host_routes_reject_general_token_and_require_private_token() -> None:
    app = FastAPI()
    state = {"enabled": False, "emergency_stopped": False}
    app.include_router(create_desktop_action_host_router(
        status=lambda: dict(state),
        enable=lambda **_kwargs: {**state, "enabled": True},
        disable=lambda: dict(state),
        rearm=lambda **_kwargs: dict(state),
        stop=lambda: {**state, "emergency_stopped": True},
        host_token_provider=lambda: "private-desktop-token",
        backend_token_provider=lambda: "renderer-backend-token",
    ))
    client = TestClient(app)
    paths = {
        "/api/desktop-actions/status": "GET",
        "/api/desktop-actions/enable": "POST",
        "/api/desktop-actions/disable": "POST",
        "/api/desktop-actions/rearm": "POST",
        "/api/desktop-actions/emergency-stop": "POST",
        "/api/desktop-actions/preview": "POST",
    }
    for path, method in paths.items():
        request = client.get if method == "GET" else client.post
        kwargs = {} if method == "GET" else {"json": {}}
        assert request(path, headers={"Authorization": "Bearer renderer-backend-token"}, **kwargs).status_code == 401
        response = request(path, headers={"Authorization": "Bearer private-desktop-token"}, **kwargs)
        assert response.status_code == (503 if path.endswith("/preview") else 200)


@pytest.mark.asyncio
async def test_effect_timeout_latches_unknown_outcome_and_requires_rearm(tmp_path) -> None:
    release = threading.Event()

    class UncertainAdapter(FakeNativeAdapter):
        def focus(self, selected, fence):
            del selected, fence
            release.wait(timeout=1)
            return NativeDesktopResult("completed")

    adapter = UncertainAdapter()
    controller = DesktopActionController(
        adapter=adapter, enabled=True, action_timeout_seconds=0.05,
    )
    ctx = Context()
    controller.bind_context(ctx, trusted_scope=scope())
    lease, preview = issue_preview(controller, ctx)
    args = {
        "target_lease": lease,
        "preview_digest": preview["preview_digest"],
        "confirmation_summary": preview["confirmation_summary"],
    }
    registry = ToolRegistry()
    register_desktop_action_tools(registry, controller=controller)
    policy = PolicyEngine(store_file=tmp_path / "permissions.json")

    async def allow(**payload) -> None:
        policy.resolve_pending(payload["request_id"], True)

    result = await ToolExecutor(registry, policy).execute(
        "desktop.focus_window", args, ctx=ctx, permission_request_cb=allow,
    )
    release.set()
    assert not result.success and result.data["code"] == "DA_OUTCOME_UNKNOWN"
    assert controller.status()["emergency_stopped"] is True
    with pytest.raises(DesktopActionError) as rejected:
        controller.set_enabled(True)
    assert rejected.value.code == "DA_REARM_REQUIRED"


@pytest.mark.asyncio
async def test_adapter_exception_is_sanitized_and_authority_state_is_capped(tmp_path, monkeypatch) -> None:
    import modules.agent.desktop_actions as desktop_module

    monkeypatch.setattr(desktop_module, "MAX_ACTIVE_LEASES", 3)
    monkeypatch.setattr(desktop_module, "MAX_USED_PERMITS", 2)

    class SecretFailureAdapter(FakeNativeAdapter):
        def focus(self, selected, fence):
            del selected, fence
            raise RuntimeError("password=super-secret-host-value")

    adapter = SecretFailureAdapter()
    adapter.discover = lambda *, limit=100: [  # type: ignore[method-assign]
        NativeWindowTarget(index, f"Window {index}", "Application", f"fp-{index}")
        for index in range(1, 6)
    ]
    controller = DesktopActionController(adapter=adapter, enabled=True)
    ctx = Context()
    controller.bind_context(ctx, trusted_scope=scope())
    discovery = controller.host_discover()
    for app in discovery["apps"]:
        controller.grant_app(
            app_id=app["app_id"],
            discovery_revision=discovery["discovery_revision"],
            allowed_actions=["focus", "request_close"],
        )
    listed = controller.list_targets(ctx)
    assert len(listed["windows"]) == 3
    assert len(controller._leases) == 3

    lease = listed["windows"][-1]["target_lease"]
    preview = controller.preview(ctx, target_lease=lease, action="focus")
    registry = ToolRegistry()
    register_desktop_action_tools(registry, controller=controller)
    policy = PolicyEngine(store_file=tmp_path / "permissions.json")

    async def allow(**payload) -> None:
        policy.resolve_pending(payload["request_id"], True)

    result = await ToolExecutor(registry, policy).execute(
        "desktop.focus_window",
        {
            "target_lease": lease,
            "preview_digest": preview["preview_digest"],
            "confirmation_summary": preview["confirmation_summary"],
        },
        ctx=ctx,
        permission_request_cb=allow,
    )
    assert not result.success and result.data["code"] == "DA_ADAPTER_FAILURE"
    assert "super-secret-host-value" not in (result.error or "")

    controller._used_permits["one"] = None
    controller._used_permits["two"] = None
    controller._used_permits["three"] = None
    while len(controller._used_permits) > desktop_module.MAX_USED_PERMITS:
        controller._used_permits.popitem(last=False)
    assert list(controller._used_permits) == ["two", "three"]
