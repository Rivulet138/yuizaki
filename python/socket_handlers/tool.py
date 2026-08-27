"""Direct Socket.IO tool-call handler.

This module owns only request coercion, permission bookkeeping and result/error
projection. The server façade still owns registration and supplies all runtime
dependencies, which keeps event names and cancellation identity stable.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, is_dataclass
from typing import Any, cast

from modules.agent.context import AgentRequestContext
from socket_events import (
    TOOL_PROTOCOL_VERSION,
    SystemEvents,
    ToolCallData,
    ToolEvents,
    ToolResultData,
)

JsonDict = dict[str, object]
PermissionRequestCallback = Callable[..., Awaitable[None]]


def _as_text(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _as_json_dict(value: object) -> JsonDict:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _version_status(value: object) -> tuple[int, bool]:
    if value is None:
        return TOOL_PROTOCOL_VERSION, True
    if not isinstance(value, (str, int, float)):
        return TOOL_PROTOCOL_VERSION, False
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return TOOL_PROTOCOL_VERSION, False
    return (parsed, True) if parsed == TOOL_PROTOCOL_VERSION else (TOOL_PROTOCOL_VERSION, False)


def _as_outcome(value: object, *, success: bool) -> str:
    candidate = str(value or "").strip().lower()
    if candidate in {"known_success", "known_failure", "unknown_effect"}:
        return candidate
    return "known_success" if success else "known_failure"


def _event_payload(data: object) -> JsonDict:
    if isinstance(data, Mapping):
        return {str(key): value for key, value in data.items()}
    if is_dataclass(data) and not isinstance(data, type):
        return {str(key): value for key, value in asdict(data).items()}
    return {}


def _terminal_payload(call: ToolCallData, outcome: object, *, error: str | None = None) -> JsonDict:
    success = bool(getattr(outcome, "success", False))
    resolved_outcome = _as_outcome(getattr(outcome, "outcome", None), success=success)
    raw_data = getattr(outcome, "data", None)
    data = dict(raw_data) if isinstance(raw_data, Mapping) else {}
    verification_status = data.get("verificationStatus") or data.get("verification_status")
    recheck_available = bool(data.get("recheckAvailable", data.get("recheck_available", False)))
    payload = _event_payload(ToolResultData(
        id=call.id,
        output=str(getattr(outcome, "content", "") or "") if success else "",
        error=error or (str(getattr(outcome, "error", "")) if not success and getattr(outcome, "error", None) else None),
        version=call.version,
        status="completed" if success else "failed",
        outcome=resolved_outcome,
        effect_outcome=resolved_outcome,
        verification_status=str(verification_status) if verification_status else None,
        recheck_available=recheck_available,
        retryable=bool(getattr(outcome, "retryable", False)),
        data=None,
        request_id=call.request_id,
        run_id=call.run_id,
        job_id=call.job_id,
        source=call.source,
    ))
    payload["effectOutcome"] = payload.pop("effect_outcome")
    payload["verificationStatus"] = payload.pop("verification_status")
    payload["recheckAvailable"] = payload.pop("recheck_available")
    payload.pop("verification_evidence", None)
    payload.pop("recheck_error", None)
    payload.pop("result_summary", None)
    payload["data"] = {
        key: value for key, value in {
            "verificationStatus": payload.get("verificationStatus"),
            "effectOutcome": payload.get("effectOutcome"),
            "recheckAvailable": payload.get("recheckAvailable"),
        }.items() if value is not None
    } or None
    if isinstance(data.get("verificationEvidence"), list):
        payload["verificationEvidence"] = [str(item)[:360] for item in data["verificationEvidence"][:6]]
    if data.get("recheckError") is not None:
        payload["recheckError"] = str(data["recheckError"])[:160]
    if data.get("resultSummary") is not None:
        payload["resultSummary"] = str(data["resultSummary"])[:360]
    for key in ("request_id", "run_id", "job_id", "source"):
        if payload.get(key) is None:
            payload.pop(key, None)
    return payload


def build_tool_call_handler(
    *,
    sio: Any,
    tool_executor: Any,
    tool_registry: Any,
    trace_store: Any,
    plugin_manager: Any,
    active_workspace_id: Callable[[], str],
    bind_ctx_runtime: Callable[[AgentRequestContext], None],
    tool_cancellation_signals: dict[str, tuple[str, str, asyncio.Event]],
    permission_request_tool_map: dict[str, str],
    permission_request_scope_map: dict[str, str],
    permission_request_sid_map: dict[str, str],
    logger: logging.Logger | None = None,
) -> Callable[[str, JsonDict], Awaitable[None]]:
    log = logger or logging.getLogger("socket-server.tool")

    async def on_tool_call(sid: str, data: JsonDict) -> None:
        version, version_supported = _version_status(data.get("version", data.get("protocol_version")))
        call = ToolCallData(
            id=_as_text(data.get("id")),
            name=_as_text(data.get("name")),
            args=_as_json_dict(data.get("args")),
            request_id=_as_text(data.get("requestId") or data.get("request_id")) or None,
            run_id=_as_text(data.get("runId") or data.get("run_id")) or None,
            job_id=_as_text(data.get("jobId") or data.get("job_id")) or None,
            source=_as_text(data.get("source")) or None,
            retry=bool(data.get("retry", False)),
            version=version,
        )

        if not version_supported:
            await sio.emit(ToolEvents.ERROR, {
                "id": call.id,
                "output": "",
                "error": "unsupported_protocol_version",
                "version": TOOL_PROTOCOL_VERSION,
                "status": "failed",
                "outcome": "known_failure",
                "effectOutcome": "known_failure",
                "verificationStatus": None,
                "recheckAvailable": False,
                "retryable": False,
                "data": {"code": "UNSUPPORTED_PROTOCOL_VERSION"},
            }, to=sid)
            return

        log.info("[SIO] tool:call from %s: %s", sid, call.name)
        tool_request_id = call.request_id or call.id or f"req:{uuid.uuid4().hex}"
        tool_signal_key = f"{sid}:{tool_request_id}:{uuid.uuid4().hex}"
        tool_cancellation_signal = asyncio.Event()
        tool_cancellation_signals[tool_signal_key] = (sid, tool_request_id, tool_cancellation_signal)
        permission_request_ids: set[str] = set()
        tool_ctx = AgentRequestContext(
            sid=sid,
            session_id=sid,
            request_id=tool_request_id,
            messages=[],
            workspace_id=active_workspace_id(),
            tool_registry=tool_registry,
            tool_executor=tool_executor,
            trace_store=trace_store,
            plugin_manager=plugin_manager,
            permission_scope=f"socket:{sid}",
        )
        tool_ctx.extra["turn_id"] = f"turn:{tool_request_id}"
        bind_ctx_runtime(tool_ctx)

        async def permission_request_cb(**payload: object) -> None:
            request_id = payload.get("request_id")
            if isinstance(request_id, str):
                permission_request_ids.add(request_id)
                permission_request_tool_map[request_id] = call.name
                permission_request_scope_map[request_id] = str(payload.get("permission_scope") or f"socket:{sid}")
                permission_request_sid_map[request_id] = sid
            await sio.emit(SystemEvents.PERMISSION_REQUEST, payload, to=sid)

        try:
            execute_kwargs: dict[str, object] = {
                "permission_request_cb": permission_request_cb,
                "ctx": tool_ctx,
                "request_id": tool_request_id,
                "run_id": call.run_id,
                "job_id": call.job_id,
                "source": call.source,
                "cancellation_signal": tool_cancellation_signal,
                "retry": call.retry,
            }
            execute = cast(Callable[..., Awaitable[Any]], tool_executor.execute)
            try:
                execute_signature = inspect.signature(execute)
            except (TypeError, ValueError):
                execute_signature = None
            if execute_signature is not None and not any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in execute_signature.parameters.values()
            ):
                execute_kwargs = {
                    key: value for key, value in execute_kwargs.items() if key in execute_signature.parameters
                }
            outcome = await execute(call.name, call.args, **execute_kwargs)

            await sio.emit(ToolEvents.RESULT if outcome.success else ToolEvents.ERROR, _terminal_payload(call, outcome), to=sid)
        except Exception as exc:  # noqa: BLE001 - preserve existing transport error contract
            failure = type("Failure", (), {"success": False, "error": str(exc), "outcome": "known_failure", "retryable": True})()
            await sio.emit(ToolEvents.ERROR, _terminal_payload(call, failure), to=sid)
        finally:
            tool_cancellation_signals.pop(tool_signal_key, None)
            if tool_cancellation_signal.is_set():
                for permission_request_id in permission_request_ids:
                    permission_request_sid_map.pop(permission_request_id, None)
                    permission_request_tool_map.pop(permission_request_id, None)
                    permission_request_scope_map.pop(permission_request_id, None)

    return on_tool_call


def build_tool_recheck_handler(
    *,
    sio: Any,
    tool_executor: Any,
    tool_registry: Any,
    trace_store: Any,
    plugin_manager: Any,
    active_workspace_id: Callable[[], str],
    bind_ctx_runtime: Callable[[AgentRequestContext], None],
    logger: logging.Logger | None = None,
) -> Callable[[str, JsonDict], Awaitable[None]]:
    """Build the side-effect-free tool status probe endpoint."""
    log = logger or logging.getLogger("socket-server.tool")

    async def on_tool_recheck(sid: str, data: JsonDict) -> None:
        tool_name = _as_text(data.get("name"))
        version, version_supported = _version_status(data.get("version", data.get("protocol_version")))
        args = _as_json_dict(data.get("args"))
        request_id = _as_text(data.get("requestId") or data.get("request_id")) or f"recheck:{uuid.uuid4().hex}"
        job_id = _as_text(data.get("jobId") or data.get("job_id")) or None
        run_id = _as_text(data.get("runId") or data.get("run_id")) or None
        if not version_supported:
            await sio.emit(ToolEvents.RECHECK_RESULT, {
                "id": _as_text(data.get("id")) or request_id,
                "name": tool_name,
                "job_id": job_id,
                "request_id": request_id,
                "version": TOOL_PROTOCOL_VERSION,
                "status": "error",
                "reason": "unsupported_protocol_version",
            }, to=sid)
            return
        ctx = AgentRequestContext(
            sid=sid,
            session_id=sid,
            request_id=request_id,
            messages=[],
            workspace_id=active_workspace_id(),
            tool_registry=tool_registry,
            tool_executor=tool_executor,
            trace_store=trace_store,
            plugin_manager=plugin_manager,
            permission_scope=f"socket:{sid}",
        )
        ctx.extra["turn_id"] = f"turn:{request_id}"
        bind_ctx_runtime(ctx)
        try:
            outcome = await tool_executor.recheck(
                tool_name,
                args,
                ctx=ctx,
                request_id=request_id,
                run_id=run_id,
                job_id=job_id,
                source=_as_text(data.get("source")) or "desktop",
            )
            await sio.emit(ToolEvents.RECHECK_RESULT, {
                "id": _as_text(data.get("id")) or request_id,
                "name": tool_name,
                "job_id": job_id,
                "request_id": request_id,
                "version": version,
                **outcome,
            }, to=sid)
        except Exception as exc:  # noqa: BLE001 - preserve transport contract
            log.debug("tool recheck failed: %s", exc)
            await sio.emit(ToolEvents.RECHECK_RESULT, {
                "id": _as_text(data.get("id")) or request_id,
                "name": tool_name,
                "job_id": job_id,
                "request_id": request_id,
                "status": "error",
                "reason": "status_probe_failed",
                "version": version,
            }, to=sid)

    return on_tool_recheck


__all__ = ["build_tool_call_handler", "build_tool_recheck_handler"]
