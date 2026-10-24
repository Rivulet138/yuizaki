from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from socket_events import SOCKET_PROTOCOL_VERSION, protocol_version_status
from socket_handlers.audio import build_audio_chunk_handler
from socket_handlers.llm import LLMRequestSupport, build_llm_request_handler
from socket_handlers.system import register_system_handlers
from socket_server import DesktopPetSocketServer


@pytest.mark.parametrize("value", [0, 2, True, 1.5, float("nan"), "1.5", "v1", object()])
def test_socket_protocol_rejects_unknown_or_non_integral_versions(value: object) -> None:
    assert protocol_version_status(value) == (SOCKET_PROTOCOL_VERSION, False)


@pytest.mark.parametrize("value", [None, 1, 1.0, "1"])
def test_socket_protocol_accepts_only_current_version_forms(value: object) -> None:
    assert protocol_version_status(value) == (SOCKET_PROTOCOL_VERSION, True)


class _FakeSio:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object], str]] = []
        self.handlers: dict[str, object] = {}

    def on(self, event: str, *, handler: object) -> None:
        self.handlers[event] = handler

    async def emit(self, event: str, payload: dict[str, object], *, to: str) -> None:
        self.events.append((event, payload, to))


class _Policy:
    def __init__(self, result: bool = True, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[object, ...]] = []

    def resolve_pending(self, *args: object) -> bool:
        self.calls.append(args)
        if self.error is not None:
            raise self.error
        return self.result


def _system_permission_handler(
    sio: _FakeSio,
    policy: _Policy,
    sid_map: dict[str, str],
    tool_map: dict[str, str],
    scope_map: dict[str, str],
    resolved_map: dict[str, tuple[str, dict[str, object]]] | None = None,
):
    resolved_map = resolved_map if resolved_map is not None else {}
    register_system_handlers(
        sio=sio,
        generation_manager_provider=lambda: None,
        experience_metrics=SimpleNamespace(),
        emit_latency=lambda *_args: None,
        permission_request_sid_map=sid_map,
        permission_request_tool_map=tool_map,
        permission_request_scope_map=scope_map,
        permission_request_resolved_map=resolved_map,
        tool_executor=SimpleNamespace(policy_engine=policy),
    )
    return sio.handlers["permission:response"]


@pytest.mark.asyncio
async def test_permission_response_returns_ack_and_cleans_request_maps() -> None:
    sio = _FakeSio()
    policy = _Policy()
    sid_map = {"request-1": "sid-1"}
    tool_map = {"request-1": "tool"}
    scope_map = {"request-1": "scope"}
    handler = _system_permission_handler(sio, policy, sid_map, tool_map, scope_map)

    ack = await handler("sid-1", {"request_id": "request-1", "allowed": True, "remember": True})

    assert ack == {"ok": True, "request_id": "request-1"}
    assert policy.calls == [("request-1", True, True, "tool", "scope")]
    assert sid_map == tool_map == scope_map == {}
    assert sio.events == []


@pytest.mark.asyncio
async def test_permission_response_rejects_unknown_and_keeps_request_id_in_error() -> None:
    sio = _FakeSio()
    policy = _Policy()
    handler = _system_permission_handler(sio, policy, {}, {}, {})

    ack = await handler("sid-1", {"request_id": "missing", "allowed": True})

    assert ack == {
        "ok": False,
        "request_id": "missing",
        "code": "PERMISSION_REQUEST_UNKNOWN",
        "message": "Permission response did not match a pending request",
    }
    assert sio.events[-1][1]["request_id"] == "missing"


@pytest.mark.asyncio
async def test_permission_response_rejects_sid_mismatch_without_resolving() -> None:
    sio = _FakeSio()
    policy = _Policy()
    sid_map = {"request-1": "sid-1"}
    tool_map = {"request-1": "tool"}
    scope_map = {"request-1": "scope"}
    handler = _system_permission_handler(sio, policy, sid_map, tool_map, scope_map)

    ack = await handler("sid-2", {"request_id": "request-1", "allowed": True})

    assert ack["code"] == "PERMISSION_SESSION_MISMATCH"
    assert policy.calls == []
    assert sid_map == {"request-1": "sid-1"}
    assert tool_map == {"request-1": "tool"}
    assert scope_map == {"request-1": "scope"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("policy", "code"),
    [(_Policy(result=False), "PERMISSION_REQUEST_UNKNOWN"), (_Policy(error=RuntimeError("boom")), "PERMISSION_RESOLUTION_FAILED")],
)
async def test_permission_response_acknowledges_resolution_failures_without_cleanup(
    policy: _Policy,
    code: str,
) -> None:
    sio = _FakeSio()
    sid_map = {"request-1": "sid-1"}
    tool_map = {"request-1": "tool"}
    scope_map = {"request-1": "scope"}
    handler = _system_permission_handler(sio, policy, sid_map, tool_map, scope_map)

    ack = await handler("sid-1", {"request_id": "request-1", "allowed": False})

    assert ack["code"] == code
    assert sid_map and tool_map and scope_map
    assert sio.events[-1][1]["request_id"] == "request-1"


@pytest.mark.asyncio
async def test_permission_response_replays_successful_ack_for_same_sid() -> None:
    sio = _FakeSio()
    policy = _Policy()
    sid_map = {"request-1": "sid-1"}
    tool_map = {"request-1": "tool"}
    scope_map = {"request-1": "scope"}
    resolved_map: dict[str, tuple[str, dict[str, object]]] = {}
    handler = _system_permission_handler(sio, policy, sid_map, tool_map, scope_map, resolved_map)

    first = await handler("sid-1", {"request_id": "request-1", "allowed": True})
    replay = await handler("sid-1", {"request_id": "request-1", "allowed": False})

    assert first == {"ok": True, "request_id": "request-1"}
    assert replay == {"ok": True, "request_id": "request-1", "replayed": True}
    assert policy.calls == [("request-1", True, False, "tool", "scope")]


@pytest.mark.asyncio
async def test_permission_response_replay_preserves_sid_ownership() -> None:
    sio = _FakeSio()
    policy = _Policy()
    sid_map = {"request-1": "sid-1"}
    tool_map = {"request-1": "tool"}
    scope_map = {"request-1": "scope"}
    resolved_map: dict[str, tuple[str, dict[str, object]]] = {}
    handler = _system_permission_handler(sio, policy, sid_map, tool_map, scope_map, resolved_map)

    await handler("sid-1", {"request_id": "request-1", "allowed": True})
    replay = await handler("sid-2", {"request_id": "request-1", "allowed": True})

    assert replay["code"] == "PERMISSION_SESSION_MISMATCH"
    assert policy.calls == [("request-1", True, False, "tool", "scope")]


@pytest.mark.asyncio
async def test_permission_response_replay_cache_is_bounded() -> None:
    sio = _FakeSio()
    policy = _Policy()
    sid_map: dict[str, str] = {}
    tool_map: dict[str, str] = {}
    scope_map: dict[str, str] = {}
    resolved_map: dict[str, tuple[str, dict[str, object]]] = {}
    handler = _system_permission_handler(sio, policy, sid_map, tool_map, scope_map, resolved_map)

    for index in range(257):
        request_id = f"request-{index}"
        sid_map[request_id] = "sid-1"
        tool_map[request_id] = "tool"
        scope_map[request_id] = "scope"
        await handler("sid-1", {"request_id": request_id, "allowed": True})

    assert len(resolved_map) == 256
    assert "request-0" not in resolved_map
    assert "request-1" in resolved_map


def test_disconnect_cleanup_removes_permission_state_for_sid() -> None:
    cancelled: list[str] = []

    class _Policy:
        def cancel_pending(self, request_id: str) -> bool:
            cancelled.append(request_id)
            return True

    server = object.__new__(DesktopPetSocketServer)
    server.policy_engine = _Policy()
    server._permission_request_sid_map = {"pending-1": "sid-1", "pending-2": "sid-2"}
    server._permission_request_tool_map = {"pending-1": "tool-1", "pending-2": "tool-2"}
    server._permission_request_scope_map = {"pending-1": "scope-1", "pending-2": "scope-2"}
    server._permission_request_resolved_map = {
        "done-1": ("sid-1", {"ok": True, "request_id": "done-1"}),
        "done-2": ("sid-2", {"ok": True, "request_id": "done-2"}),
    }

    server._clear_permission_requests("sid-1")

    assert cancelled == ["pending-1"]
    assert server._permission_request_sid_map == {"pending-2": "sid-2"}
    assert server._permission_request_tool_map == {"pending-2": "tool-2"}
    assert server._permission_request_scope_map == {"pending-2": "scope-2"}
    assert server._permission_request_resolved_map == {
        "done-2": ("sid-2", {"ok": True, "request_id": "done-2"}),
    }


@pytest.mark.asyncio
async def test_llm_protocol_rejection_happens_before_generation() -> None:
    sio = _FakeSio()

    class GenerationManager:
        def __init__(self) -> None:
            self.started = False

        def start(self, *_args, **_kwargs):
            self.started = True
            raise AssertionError("generation must not start for an unsupported version")

    generation = GenerationManager()

    identity = lambda data, session: {"session_id": session, "version": 999}
    support = LLMRequestSupport(
        request_identity=identity,
        as_text=lambda value, default="": value if isinstance(value, str) else default,
        as_int=lambda value, default=0: default,
        as_json_dict=lambda value: {},
        as_messages=lambda value: [],
        optional_float=lambda value: None,
        optional_bool=lambda value: None,
        request_option=lambda data, key: None,
        request_tts_enabled=lambda data: False,
        request_prompt_profile=lambda data: None,
        request_response_mode=lambda data: None,
        prompt_mode=lambda profile: None,
        event_payload=lambda value: {},
        generation_identity=lambda generation: {},
        agent_result_payload=lambda value, session, identity: {},
    )
    server = SimpleNamespace(llm_client=object(), generation_mgr=generation, sio=sio)
    handler = build_llm_request_handler(server=server, support=support, logger=logging.getLogger("test.llm-protocol"))

    await handler("sid", {"session_id": "s", "version": 999})

    assert generation.started is False
    assert sio.events[0][1]["code"] == "UNSUPPORTED_PROTOCOL_VERSION"
    assert sio.events[0][1]["version"] == SOCKET_PROTOCOL_VERSION


@pytest.mark.asyncio
async def test_audio_protocol_rejection_happens_before_asr() -> None:
    sio = _FakeSio()
    asr_called = False

    class ASR:
        async def handle_audio_chunk(self, *_args, **_kwargs):
            nonlocal asr_called
            asr_called = True

    async def emit_latency(*_args, **_kwargs):
        raise AssertionError("latency should not be emitted")

    handler = build_audio_chunk_handler(
        sio=sio,
        asr_manager_provider=lambda: ASR(),
        generation_manager_provider=lambda: object(),
        agent_pipeline_provider=lambda: object(),
        tool_registry_provider=lambda: object(),
        active_workspace_id=lambda: "workspace",
        latest_visual_frame_for_sid=lambda _sid: None,
        voice_prepared_sessions=set(),
        schedule_voice_turn_preparation=lambda: None,
        emit_latency=emit_latency,
    )

    await handler("sid", {"version": 999, "chunk": ""})

    assert asr_called is False
    assert sio.events[0][1]["code"] == "UNSUPPORTED_PROTOCOL_VERSION"
    assert sio.events[0][1]["version"] == SOCKET_PROTOCOL_VERSION
