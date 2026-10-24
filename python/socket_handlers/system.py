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
    permission_request_resolved_map: dict[str, tuple[str, JsonDict]],
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

    async def on_permission_response(sid: str, data: JsonDict) -> JsonDict:
        request_id = _as_text(data.get("request_id"))
        allowed = bool(data.get("allowed", False))
        remember = bool(data.get("remember", False))

        async def reject(code: str, message: str) -> JsonDict:
            payload: JsonDict = {
                "ok": False,
                "request_id": request_id,
                "code": code,
                "message": message,
            }
            await sio.emit(SystemEvents.ERROR, payload, to=sid)
            return payload

        resolved_entry = permission_request_resolved_map.get(request_id)
        if resolved_entry is not None:
            resolved_sid, resolved_ack = resolved_entry
            if resolved_sid != sid:
                log.warning("Ignoring replayed permission response from unexpected sid %s for request %s", sid, request_id)
                return await reject(
                    "PERMISSION_SESSION_MISMATCH",
                    "Permission response did not come from the requesting client",
                )
            return {**resolved_ack, "replayed": True}

        expected_sid = permission_request_sid_map.get(request_id)
        if not request_id or expected_sid is None:
            log.warning("Ignoring unknown permission response %s from sid %s", request_id, sid)
            return await reject(
                "PERMISSION_REQUEST_UNKNOWN",
                "Permission response did not match a pending request",
            )
        if expected_sid != sid:
            log.warning("Ignoring permission response from unexpected sid %s for request %s", sid, request_id)
            return await reject(
                "PERMISSION_SESSION_MISMATCH",
                "Permission response did not come from the requesting client",
            )
        tool_name = permission_request_tool_map.get(request_id)
        permission_scope = permission_request_scope_map.get(request_id)
        try:
            resolved = tool_executor.policy_engine.resolve_pending(
                request_id,
                allowed,
                remember,
                tool_name,
                permission_scope,
            )
        except Exception:  # noqa: BLE001 - keep policy provider details out of the protocol
            log.exception("Failed to resolve permission request %s", request_id)
            return await reject(
                "PERMISSION_RESOLUTION_FAILED",
                "Permission response could not be applied",
            )
        if resolved is False:
            return await reject(
                "PERMISSION_REQUEST_UNKNOWN",
                "Permission response did not match a pending request",
            )
        permission_request_sid_map.pop(request_id, None)
        permission_request_tool_map.pop(request_id, None)
        permission_request_scope_map.pop(request_id, None)
        ack = {"ok": True, "request_id": request_id}
        permission_request_resolved_map[request_id] = (sid, ack)
        while len(permission_request_resolved_map) > 256:
            permission_request_resolved_map.pop(next(iter(permission_request_resolved_map)))
        return ack

    sio.on(SystemEvents.PERMISSION_RESPONSE, handler=on_permission_response)


__all__ = ["register_system_handlers"]
