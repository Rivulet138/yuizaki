"""Socket.IO system handlers with a narrow dependency surface.

The server keeps ownership of runtime state and passes callbacks here. This
module only projects heartbeat, client timing and permission responses, so the
event names and terminal payloads remain identical while registration logic is
isolated from voice/agent handlers.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from socket_events import HeartbeatData, SystemEvents

JsonDict = dict[str, object]
EmitLatency = Callable[[str, Mapping[str, object]], Awaitable[None]]
GenerationManagerProvider = Callable[[], Any]


def _as_text(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _event_payload(data: object) -> JsonDict:
    if hasattr(data, "__dataclass_fields__"):
        return {
            str(name): getattr(data, name)
            for name in getattr(data, "__dataclass_fields__", {})
        }
    if isinstance(data, Mapping):
        return {str(key): value for key, value in data.items()}
    return {}


def register_system_handlers(
    *,
    sio: Any,
    generation_manager_provider: GenerationManagerProvider,
    experience_metrics: Any,
    emit_latency: EmitLatency,
    permission_request_sid_map: dict[str, str],
    permission_request_tool_map: dict[str, str],
    permission_request_scope_map: dict[str, str],
    tool_executor: Any,
    logger: logging.Logger | None = None,
) -> None:
    """Register low-risk system events without creating a second protocol."""

    log = logger or logging.getLogger("socket-server.system")

    async def on_heartbeat(sid: str, _data: JsonDict) -> None:
        await sio.emit(
            SystemEvents.HEARTBEAT,
            _event_payload(HeartbeatData(timestamp=time.time(), client_id=sid)),
            to=sid,
        )

    sio.on(SystemEvents.HEARTBEAT, handler=on_heartbeat)

    async def on_client_timing(sid: str, data: JsonDict) -> None:
        stage = _as_text(data.get("stage")).strip().lower()
        if stage != "playback_start":
            experience_metrics.record_client_timing(stage, data.get("elapsed_ms"), data)
            return
        generation_mgr = generation_manager_provider()
        if generation_mgr is None:
            return
        session_id = _as_text(data.get("session_id"), sid)
        generation = generation_mgr.get(session_id)
        generation_id = _as_text(data.get("generation_id"))
        if generation is None or (generation_id and generation.generation_id != generation_id):
            return
        generation.mark("playback_start")
        await emit_latency(sid, generation.latency_snapshot())

    sio.on(SystemEvents.CLIENT_TIMING, handler=on_client_timing)

    async def on_permission_response(sid: str, data: JsonDict) -> None:
        request_id = _as_text(data.get("request_id"))
        allowed = bool(data.get("allowed", False))
        remember = bool(data.get("remember", False))
        expected_sid = permission_request_sid_map.get(request_id)
        if not request_id or expected_sid is None:
            log.warning("Ignoring unknown permission response %s from sid %s", request_id, sid)
            await sio.emit(
                SystemEvents.ERROR,
                {
                    "code": "PERMISSION_REQUEST_UNKNOWN",
                    "message": "Permission response did not match a pending request",
                },
                to=sid,
            )
            return
        if expected_sid != sid:
            log.warning("Ignoring permission response from unexpected sid %s for request %s", sid, request_id)
            await sio.emit(
                SystemEvents.ERROR,
                {
                    "code": "PERMISSION_SESSION_MISMATCH",
                    "message": "Permission response did not come from the requesting client",
                },
                to=sid,
            )
            return
        permission_request_sid_map.pop(request_id, None)
        tool_name = permission_request_tool_map.pop(request_id, None)
        permission_scope = permission_request_scope_map.pop(request_id, None)
        tool_executor.policy_engine.resolve_pending(
            request_id,
            allowed,
            remember,
            tool_name,
            permission_scope,
        )

    sio.on(SystemEvents.PERMISSION_RESPONSE, handler=on_permission_response)


__all__ = ["register_system_handlers"]
