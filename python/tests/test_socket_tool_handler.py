from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from socket_handlers.tool import build_tool_call_handler


class _Sio:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any], str]] = []

    async def emit(self, event: str, payload: dict[str, Any], *, to: str) -> None:
        self.events.append((event, payload, to))


@dataclass
class _Outcome:
    success: bool
    content: str = ""
    error: str | None = None
    outcome: str | None = None


class _Executor:
    def __init__(self, outcome: _Outcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def execute(self, name: str, args: dict[str, object]) -> _Outcome:
        self.calls.append((name, args))
        return self.outcome


def _handler(executor: _Executor, sio: _Sio):
    return build_tool_call_handler(
        sio=sio,
        tool_executor=executor,
        tool_registry=object(),
        trace_store=object(),
        plugin_manager=object(),
        active_workspace_id=lambda: "workspace",
        bind_ctx_runtime=lambda ctx: None,
        tool_cancellation_signals={},
        permission_request_tool_map={},
        permission_request_scope_map={},
        permission_request_sid_map={},
    )


def test_direct_tool_handler_preserves_success_event_and_legacy_executor_signature() -> None:
    sio = _Sio()
    executor = _Executor(_Outcome(True, content="ok"))
    handler = _handler(executor, sio)

    asyncio.run(handler("sid", {"id": "call-1", "name": "filesystem.read", "args": {"path": "x"}}))

    assert executor.calls == [("filesystem.read", {"path": "x"})]
    assert sio.events[0][0] == "tool:result"
    assert sio.events[0][1] == {
        "id": "call-1", "output": "ok", "error": None, "version": 1,
        "status": "completed", "outcome": "known_success", "retryable": False,
        "data": {"effectOutcome": "known_success", "recheckAvailable": False}, "effectOutcome": "known_success", "verificationStatus": None,
        "recheckAvailable": False,
    }
    assert sio.events[0][2] == "sid"


def test_direct_tool_handler_projects_failure_without_leaking_internal_exception() -> None:
    sio = _Sio()
    executor = _Executor(_Outcome(False, error="permission denied"))
    handler = _handler(executor, sio)

    asyncio.run(handler("sid", {"id": "call-2", "name": "desktop.write", "args": {}}))

    assert sio.events[0][0] == "tool:error"
    assert sio.events[0][1]["id"] == "call-2"
    assert sio.events[0][1]["error"] == "permission denied"
    assert sio.events[0][1]["version"] == 1
    assert sio.events[0][1]["outcome"] == "known_failure"
    assert sio.events[0][2] == "sid"


def test_direct_tool_handler_normalizes_legacy_invalid_outcome() -> None:
    sio = _Sio()
    executor = _Executor(_Outcome(True, content="ok", outcome="provider_specific_success"))
    handler = _handler(executor, sio)

    asyncio.run(handler("sid", {"id": "call-3", "name": "filesystem.read", "args": {}}))

    assert sio.events[0][1]["outcome"] == "known_success"
    assert sio.events[0][1]["effectOutcome"] == "known_success"


def test_direct_tool_handler_rejects_unsupported_protocol_version() -> None:
    sio = _Sio()
    executor = _Executor(_Outcome(True, content="must not run"))
    handler = _handler(executor, sio)

    asyncio.run(handler("sid", {
        "id": "call-version",
        "name": "filesystem.read",
        "args": {},
        "version": 999,
    }))

    assert executor.calls == []
    assert sio.events[0][0] == "tool:error"
    assert sio.events[0][1]["error"] == "unsupported_protocol_version"
    assert sio.events[0][1]["data"] == {"code": "UNSUPPORTED_PROTOCOL_VERSION"}
