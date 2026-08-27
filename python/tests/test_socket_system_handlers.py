from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from socket_events import SystemEvents
from socket_handlers.system import register_system_handlers


class _Sio:
    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}
        self.events: list[tuple[str, dict[str, object], str]] = []

    def on(self, event: str, *, handler: Any) -> None:
        self.handlers[event] = handler

    async def emit(self, event: str, payload: dict[str, object], *, to: str) -> None:
        self.events.append((event, payload, to))


@dataclass
class _Generation:
    generation_id: str = "generation-1"
    marked: list[str] | None = None

    def mark(self, stage: str) -> None:
        if self.marked is None:
            self.marked = []
        self.marked.append(stage)

    def latency_snapshot(self) -> dict[str, object]:
        return {"generation_id": self.generation_id, "first_audio_ms": 42}


class _GenerationManager:
    def __init__(self, generation: _Generation) -> None:
        self.generation = generation

    def get(self, _session_id: str) -> _Generation:
        return self.generation


class _Metrics:
    def __init__(self) -> None:
        self.timings: list[tuple[str, object, dict[str, object]]] = []

    def record_client_timing(self, stage: str, elapsed_ms: object, metadata: dict[str, object]) -> None:
        self.timings.append((stage, elapsed_ms, dict(metadata)))


class _Policy:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def resolve_pending(self, *args: object) -> None:
        self.calls.append(args)


class _Executor:
    def __init__(self, policy: _Policy) -> None:
        self.policy_engine = policy


def _register(
    sio: _Sio,
    generation: _Generation,
    metrics: _Metrics,
    policy: _Policy,
    *,
    manager_provider: Any | None = None,
) -> None:
    manager = _GenerationManager(generation)
    register_system_handlers(
        sio=sio,
        generation_manager_provider=manager_provider or (lambda: manager),
        experience_metrics=metrics,
        emit_latency=lambda sid, payload: sio.emit(SystemEvents.LATENCY, dict(payload), to=sid),
        permission_request_sid_map={"permission-1": "sid-1"},
        permission_request_tool_map={"permission-1": "desktop.read"},
        permission_request_scope_map={"permission-1": "socket:sid-1"},
        tool_executor=_Executor(policy),
    )


def test_system_handlers_resolve_generation_manager_after_registration() -> None:
    sio = _Sio()
    generation = _Generation()
    metrics = _Metrics()
    policy = _Policy()
    manager: _GenerationManager | None = None
    _register(
        sio,
        generation,
        metrics,
        policy,
        manager_provider=lambda: manager,
    )
    manager = _GenerationManager(generation)

    asyncio.run(sio.handlers[SystemEvents.CLIENT_TIMING]("sid-1", {
        "stage": "playback_start",
        "generation_id": "generation-1",
    }))

    assert generation.marked == ["playback_start"]
    assert sio.events[-1][0] == SystemEvents.LATENCY


def test_system_handlers_preserve_heartbeat_and_playback_latency_contract() -> None:
    sio = _Sio()
    generation = _Generation()
    metrics = _Metrics()
    policy = _Policy()
    _register(sio, generation, metrics, policy)

    asyncio.run(sio.handlers[SystemEvents.HEARTBEAT]("sid-1", {}))
    asyncio.run(sio.handlers[SystemEvents.CLIENT_TIMING]("sid-1", {
        "stage": "playback_start",
        "generation_id": "generation-1",
    }))

    assert sio.events[0][0] == SystemEvents.HEARTBEAT
    assert sio.events[0][1]["client_id"] == "sid-1"
    assert sio.events[1] == (
        SystemEvents.LATENCY,
        {"generation_id": "generation-1", "first_audio_ms": 42},
        "sid-1",
    )
    assert generation.marked == ["playback_start"]


def test_system_handlers_keep_permission_response_session_binding() -> None:
    sio = _Sio()
    generation = _Generation()
    metrics = _Metrics()
    policy = _Policy()
    _register(sio, generation, metrics, policy)

    asyncio.run(sio.handlers[SystemEvents.PERMISSION_RESPONSE]("sid-1", {
        "request_id": "permission-1",
        "allowed": True,
        "remember": False,
    }))

    assert policy.calls == [("permission-1", True, False, "desktop.read", "socket:sid-1")]

    asyncio.run(sio.handlers[SystemEvents.PERMISSION_RESPONSE]("sid-2", {
        "request_id": "permission-unknown",
        "allowed": True,
    }))
    assert sio.events[-1][0] == SystemEvents.ERROR
    assert sio.events[-1][1]["code"] == "PERMISSION_REQUEST_UNKNOWN"


def test_system_handlers_record_non_playback_client_timing_without_touching_generation() -> None:
    sio = _Sio()
    generation = _Generation()
    metrics = _Metrics()
    policy = _Policy()
    _register(sio, generation, metrics, policy)

    asyncio.run(sio.handlers[SystemEvents.CLIENT_TIMING]("sid-1", {
        "stage": "audio_capture_start",
        "elapsed_ms": 13,
    }))

    assert metrics.timings == [(
        "audio_capture_start",
        13,
        {"stage": "audio_capture_start", "elapsed_ms": 13},
    )]
    assert generation.marked is None


def test_system_handlers_forward_content_free_playback_recovery_metadata() -> None:
    sio = _Sio()
    generation = _Generation()
    metrics = _Metrics()
    policy = _Policy()
    _register(sio, generation, metrics, policy)
    payload = {
        "stage": "realtime_playback_recovery",
        "elapsed_ms": 45,
        "ok": True,
        "recovered": True,
        "recovery_latency_ms": 41,
        "playback_underruns": 1,
    }

    asyncio.run(sio.handlers[SystemEvents.CLIENT_TIMING]("sid-1", payload))

    assert metrics.timings == [("realtime_playback_recovery", 45, payload)]
    assert generation.marked is None
