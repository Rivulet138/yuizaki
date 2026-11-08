from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from modules.agent import mcp_manager
from modules.agent.mcp_manager import MCPManager, MCPServerConfig
from modules.tools.mcp_bridge import MCPToolError


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_at", ["initialize", "initialized"])
@pytest.mark.parametrize("cleanup", ["exited", "timeout", "already_gone"])
async def test_stdio_initialization_cancellation_cleans_up(
    tmp_path, monkeypatch, caplog, cancel_at, cleanup
):
    manager = MCPManager(tmp_path / "mcp.json")
    server = MCPServerConfig("probe", "", transport="stdio", command="probe")
    cancellation = asyncio.CancelledError("initialization cancelled")
    initialize = AsyncMock(return_value={"serverInfo": {"name": "probe"}})
    initialized = AsyncMock()
    if cancel_at == "initialize":
        initialize.side_effect = cancellation
    else:
        initialized.side_effect = cancellation
    process = SimpleNamespace(returncode=None, kill=Mock(), wait=AsyncMock(return_value=0))
    if cleanup == "timeout":
        process.wait.side_effect = TimeoutError("private-upstream-detail")
    elif cleanup == "already_gone":
        process.kill.side_effect = ProcessLookupError("private-upstream-detail")
    wait_for = Mock(wraps=asyncio.wait_for)
    monkeypatch.setattr(manager, "_stdio_launch_allowed", lambda _: True)
    monkeypatch.setattr(manager, "_stdio_jsonrpc_request_locked", initialize)
    monkeypatch.setattr(manager, "_stdio_notification_locked", initialized)
    monkeypatch.setattr(mcp_manager.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    monkeypatch.setattr(mcp_manager.asyncio, "wait_for", wait_for)

    with pytest.raises(asyncio.CancelledError) as caught:
        await manager._get_or_create_stdio_session(server)

    assert caught.value is cancellation
    process.kill.assert_called_once_with()
    if cleanup != "already_gone":
        process.wait.assert_awaited_once_with()
        assert wait_for.call_args.kwargs["timeout"] == 3.0
    assert server.name not in manager._stdio_sessions
    assert "private-upstream-detail" not in caplog.text
    if cleanup != "exited":
        assert "cleanup failed" in caplog.text


@pytest.mark.asyncio
async def test_stdio_task_cancellation_bounds_unresponsive_child_wait(tmp_path, monkeypatch, caplog):
    manager = MCPManager(tmp_path / "mcp.json")
    server = MCPServerConfig("probe", "", transport="stdio", command="probe")
    initializing = asyncio.Event()
    never_finishes = asyncio.Event()
    wait_cancelled = asyncio.Event()

    async def initialize(*args, **kwargs):
        initializing.set()
        await never_finishes.wait()

    async def wait_for_exit():
        try:
            await never_finishes.wait()
        finally:
            wait_cancelled.set()

    real_wait_for = asyncio.wait_for

    async def bounded_wait(awaitable, *, timeout):
        assert timeout == 3.0
        return await real_wait_for(awaitable, timeout=0.01)

    process = SimpleNamespace(returncode=None, kill=Mock(), wait=AsyncMock(side_effect=wait_for_exit))
    monkeypatch.setattr(manager, "_stdio_launch_allowed", lambda _: True)
    monkeypatch.setattr(manager, "_stdio_jsonrpc_request_locked", initialize)
    monkeypatch.setattr(mcp_manager.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    monkeypatch.setattr(mcp_manager.asyncio, "wait_for", bounded_wait)
    task = asyncio.create_task(manager._get_or_create_stdio_session(server))
    try:
        await real_wait_for(initializing.wait(), timeout=1.0)
        task.cancel("initialization cancelled")
        with pytest.raises(asyncio.CancelledError, match="initialization cancelled"):
            await real_wait_for(task, timeout=1.0)
        process.kill.assert_called_once_with()
        process.wait.assert_awaited_once_with()
        assert wait_cancelled.is_set()
        assert server.name not in manager._stdio_sessions
        assert "cleanup failed" in caplog.text
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_stdio_initialization_preserves_success_and_legacy(tmp_path, monkeypatch, legacy):
    manager = MCPManager(tmp_path / "mcp.json")
    server = MCPServerConfig("probe", "", transport="stdio", command="probe")
    process = SimpleNamespace(returncode=None, kill=Mock(), wait=AsyncMock(return_value=0))
    initialize = AsyncMock(return_value={"serverInfo": {"name": "probe"}})
    if legacy:
        initialize.side_effect = RuntimeError("private-upstream-detail")
    monkeypatch.setattr(manager, "_stdio_launch_allowed", lambda _: True)
    monkeypatch.setattr(manager, "_stdio_jsonrpc_request_locked", initialize)
    monkeypatch.setattr(manager, "_stdio_notification_locked", AsyncMock())
    monkeypatch.setattr(mcp_manager.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))

    session = await manager._get_or_create_stdio_session(server)

    assert manager._stdio_sessions[server.name] is session
    assert session["protocol"] == ("legacy" if legacy else "mcp-jsonrpc")
    if legacy:
        assert session["initialization_error"] == "mcp_error:runtimeerror"
    else:
        assert session["server_info"] == {"name": "probe"}
    process.kill.assert_not_called()
    process.wait.assert_not_awaited()


@pytest.mark.asyncio
async def test_sse_timeout_leaves_other_request_pending(tmp_path, monkeypatch):
    manager = MCPManager(tmp_path / "mcp.json")
    server = MCPServerConfig("probe", "https://example.test", transport="sse")
    session = {"pending": {}, "server_name": server.name}
    monkeypatch.setattr(manager, "_get_or_create_sse_session", AsyncMock(return_value=session))
    client_type = httpx.AsyncClient
    transport = httpx.MockTransport(lambda _: httpx.Response(200))
    monkeypatch.setattr(
        mcp_manager.httpx, "AsyncClient", lambda **kwargs: client_type(transport=transport, **kwargs)
    )
    real_wait_for = asyncio.wait_for
    first_waiting = asyncio.Event()
    second_waiting = asyncio.Event()
    expire_first = asyncio.Event()

    async def wait_for_result(future, *, timeout):
        assert timeout == mcp_manager.SSE_TOOL_TIMEOUT_SECONDS
        if not first_waiting.is_set():
            first_waiting.set()
            await expire_first.wait()
            future.cancel()
            raise TimeoutError
        second_waiting.set()
        return await real_wait_for(future, timeout=1.0)

    monkeypatch.setattr(mcp_manager.asyncio, "wait_for", wait_for_result)
    tasks = []
    try:
        first = asyncio.create_task(manager._call_sse_tool(server, "read", {}, "r1", []))
        tasks.append(first)
        await real_wait_for(first_waiting.wait(), timeout=1.0)
        second = asyncio.create_task(manager._call_sse_tool(server, "read", {}, "r2", []))
        tasks.append(second)
        await real_wait_for(second_waiting.wait(), timeout=1.0)
        first_future = session["pending"]["r1"]["future"]

        expire_first.set()
        with pytest.raises(MCPToolError, match="timed out waiting for event"):
            await first

        assert "r1" not in session["pending"]
        assert first_future.cancelled()
        assert "r2" in session["pending"]
        second_future = session["pending"]["r2"]["future"]
        assert not second_future.done()
        second_future.set_result({"ok": True, "output": "second succeeded"})
        assert await second == "second succeeded"
        assert not session["pending"]
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("registration", ["current", "detached", "replacement"])
async def test_sse_listener_cleanup_respects_session_ownership(tmp_path, registration):
    manager = MCPManager(tmp_path / "mcp.json")
    server = MCPServerConfig("probe", "https://example.test", transport="sse")
    old_session = {
        "session_id": "sse_old",
        "server_name": server.name,
        "pending": {},
        "stop": asyncio.Event(),
    }
    old_session["stop"].set()
    future = asyncio.get_running_loop().create_future()
    old_session["pending"]["r1"] = {"future": future}
    replacement = {"session_id": "sse_new", "pending": {}}
    telemetry = manager._ensure_telemetry(server.name)
    telemetry["session_id"] = old_session["session_id"]
    if registration == "current":
        manager._sse_sessions[server.name] = old_session
    elif registration == "replacement":
        manager._sse_sessions[server.name] = replacement
        telemetry["session_id"] = replacement["session_id"]

    await manager._run_sse_listener(server, old_session)

    telemetry = manager._ensure_telemetry(server.name)
    if registration == "replacement":
        assert manager._sse_sessions[server.name] is replacement
        assert telemetry["session_id"] == replacement["session_id"]
    else:
        assert server.name not in manager._sse_sessions
        assert telemetry["session_id"] is None
    assert not old_session["pending"]
    with pytest.raises(MCPToolError, match="MCP SSE session closed"):
        await future
    assert [entry["event"] for entry in telemetry["history"]] == ["sse_closed", "pending_failed"]
    assert all(entry["session_id"] == old_session["session_id"] for entry in telemetry["history"])


@pytest.mark.asyncio
async def test_stdio_shutdown_bounds_wait_after_kill(tmp_path, monkeypatch, caplog):
    manager = MCPManager(tmp_path / "mcp.json")
    never_finishes = asyncio.Event()
    process = SimpleNamespace(
        returncode=None,
        terminate=Mock(),
        kill=Mock(),
        wait=AsyncMock(side_effect=never_finishes.wait),
    )
    manager._stdio_sessions["probe"] = {"process": process, "server_name": "probe"}
    real_wait_for = asyncio.wait_for
    timeouts = []

    async def bounded_wait(awaitable, *, timeout):
        timeouts.append(timeout)
        return await real_wait_for(awaitable, timeout=0.01)

    monkeypatch.setattr(mcp_manager.asyncio, "wait_for", bounded_wait)

    await real_wait_for(manager.shutdown(), timeout=1.0)

    process.terminate.assert_called_once_with()
    process.kill.assert_called_once_with()
    assert process.wait.await_count == 2
    assert timeouts == [3.0, 3.0]
    assert "cleanup failed" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_mode", ["graceful", "kill", "terminate_race", "kill_race", "already_exited"])
async def test_stdio_close_handles_normal_exit_and_process_exit_races(tmp_path, exit_mode):
    manager = MCPManager(tmp_path / "mcp.json")
    process = SimpleNamespace(
        returncode=0 if exit_mode == "already_exited" else None,
        terminate=Mock(),
        kill=Mock(),
        wait=AsyncMock(return_value=0),
    )
    if exit_mode in {"kill", "kill_race"}:
        process.wait.side_effect = [TimeoutError(), 0]
    if exit_mode == "terminate_race":
        process.terminate.side_effect = ProcessLookupError()
    elif exit_mode == "kill_race":
        process.kill.side_effect = ProcessLookupError()

    await manager._close_stdio_session({"process": process, "server_name": "probe"})

    assert process.terminate.call_count == (0 if exit_mode == "already_exited" else 1)
    assert process.kill.call_count == (1 if exit_mode in {"kill", "kill_race"} else 0)
    expected_waits = {"graceful": 1, "kill": 2, "terminate_race": 0, "kill_race": 1, "already_exited": 0}
    assert process.wait.await_count == expected_waits[exit_mode]


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_after_kill", [False, True])
async def test_stdio_close_preserves_caller_cancellation(tmp_path, cancel_after_kill):
    manager = MCPManager(tmp_path / "mcp.json")
    cancellation = asyncio.CancelledError("shutdown cancelled")
    process = SimpleNamespace(
        returncode=None,
        terminate=Mock(),
        kill=Mock(),
        wait=AsyncMock(side_effect=[TimeoutError(), cancellation] if cancel_after_kill else cancellation),
    )

    with pytest.raises(asyncio.CancelledError) as caught:
        await manager._close_stdio_session({"process": process, "server_name": "probe"})

    assert caught.value is cancellation
    assert process.kill.call_count == int(cancel_after_kill)


@pytest.mark.asyncio
async def test_sse_reader_cancellation_fails_pending_and_clears_registration(tmp_path, monkeypatch):
    manager = MCPManager(tmp_path / "mcp.json")
    server = MCPServerConfig("probe", "https://example.test", transport="sse")
    reader_started = asyncio.Event()
    never_finishes = asyncio.Event()

    async def handle_request(request):
        reader_started.set()
        await never_finishes.wait()
        return httpx.Response(200)

    client_type = httpx.AsyncClient
    transport = httpx.MockTransport(handle_request)
    monkeypatch.setattr(
        mcp_manager.httpx, "AsyncClient", lambda **kwargs: client_type(transport=transport, **kwargs)
    )
    future = asyncio.get_running_loop().create_future()
    session = {
        "session_id": "sse_cancelled",
        "server_name": server.name,
        "pending": {"r1": {"future": future}},
        "stop": asyncio.Event(),
        "backoff_seconds": 1.0,
    }
    manager._sse_sessions[server.name] = session
    manager._ensure_telemetry(server.name)["session_id"] = session["session_id"]
    task = asyncio.create_task(manager._run_sse_listener(server, session))
    session["task"] = task
    try:
        await asyncio.wait_for(reader_started.wait(), timeout=1.0)
        await asyncio.wait_for(manager._close_sse_session(session), timeout=1.0)

        assert task.cancelled()
        assert session["stop"].is_set()
        assert not session["pending"]
        assert server.name not in manager._sse_sessions
        assert manager._ensure_telemetry(server.name)["session_id"] is None
        with pytest.raises(MCPToolError, match="MCP SSE session closed"):
            await future
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if future.done() and not future.cancelled():
            future.exception()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_at", ["dispatch", "result"])
async def test_sse_call_cancellation_cleans_only_its_pending_request(tmp_path, monkeypatch, cancel_at):
    manager = MCPManager(tmp_path / "mcp.json")
    server = MCPServerConfig("probe", "https://example.test", transport="sse")
    other_future = asyncio.get_running_loop().create_future()
    session = {"pending": {"other": {"future": other_future}}, "server_name": server.name}
    monkeypatch.setattr(manager, "_get_or_create_sse_session", AsyncMock(return_value=session))
    dispatch_started = asyncio.Event()
    result_wait_started = asyncio.Event()
    never_finishes = asyncio.Event()

    async def handle_request(request):
        dispatch_started.set()
        if cancel_at == "dispatch":
            await never_finishes.wait()
        return httpx.Response(200)

    client_type = httpx.AsyncClient
    transport = httpx.MockTransport(handle_request)
    monkeypatch.setattr(
        mcp_manager.httpx, "AsyncClient", lambda **kwargs: client_type(transport=transport, **kwargs)
    )
    real_wait_for = asyncio.wait_for

    async def wait_for_result(awaitable, *, timeout):
        result_wait_started.set()
        return await real_wait_for(awaitable, timeout=timeout)

    monkeypatch.setattr(mcp_manager.asyncio, "wait_for", wait_for_result)
    task = asyncio.create_task(manager._call_sse_tool(server, "read", {}, "cancelled", []))
    try:
        started = dispatch_started if cancel_at == "dispatch" else result_wait_started
        await real_wait_for(started.wait(), timeout=1.0)
        future = session["pending"]["cancelled"]["future"]
        task.cancel("tool call cancelled")

        with pytest.raises(asyncio.CancelledError, match="tool call cancelled"):
            await real_wait_for(task, timeout=1.0)

        assert set(session["pending"]) == {"other"}
        assert future.cancelled()
        assert not other_future.done()
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for pending in session["pending"].values():
            pending["future"].cancel()


@pytest.mark.asyncio
@pytest.mark.parametrize("dispatch_error", ["connection", "status"])
async def test_sse_dispatch_failure_settles_its_future(tmp_path, monkeypatch, dispatch_error):
    manager = MCPManager(tmp_path / "mcp.json")
    server = MCPServerConfig("probe", "https://example.test", transport="sse")
    other_future = asyncio.get_running_loop().create_future()
    session = {"pending": {"other": {"future": other_future}}, "server_name": server.name}
    monkeypatch.setattr(manager, "_get_or_create_sse_session", AsyncMock(return_value=session))
    dispatched = []

    async def handle_request(request):
        dispatched.append(session["pending"]["failed"]["future"])
        if dispatch_error == "connection":
            raise httpx.ConnectError("private-upstream-detail", request=request)
        return httpx.Response(503, text="private-upstream-detail")

    client_type = httpx.AsyncClient
    transport = httpx.MockTransport(handle_request)
    monkeypatch.setattr(
        mcp_manager.httpx, "AsyncClient", lambda **kwargs: client_type(transport=transport, **kwargs)
    )
    try:
        with pytest.raises(MCPToolError) as caught:
            await manager._call_sse_tool(server, "read", {}, "failed", [])

        assert "private-upstream-detail" not in str(caught.value)
        assert dispatched[0].cancelled()
        assert set(session["pending"]) == {"other"}
        assert not other_future.done()
        history = manager._ensure_telemetry(server.name)["history"]
        assert history[-1]["event"] == "sse_request_dispatch_failed"
        assert history[-1]["pending_requests"] == 1
        assert "private-upstream-detail" not in repr(history)
    finally:
        other_future.cancel()


@pytest.mark.asyncio
async def test_sse_listener_failure_during_dispatch_reaches_caller(tmp_path, monkeypatch):
    manager = MCPManager(tmp_path / "mcp.json")
    server = MCPServerConfig("probe", "https://example.test", transport="sse")
    session = {"pending": {}, "server_name": server.name}
    monkeypatch.setattr(manager, "_get_or_create_sse_session", AsyncMock(return_value=session))

    async def handle_request(request):
        manager._fail_pending(session, "MCP SSE session closed", only_stale=False)
        return httpx.Response(200)

    client_type = httpx.AsyncClient
    transport = httpx.MockTransport(handle_request)
    monkeypatch.setattr(
        mcp_manager.httpx, "AsyncClient", lambda **kwargs: client_type(transport=transport, **kwargs)
    )

    with pytest.raises(MCPToolError, match="MCP SSE session closed"):
        await manager._call_sse_tool(server, "read", {}, "failed", [])

    assert not session["pending"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["read", "process_exit"])
@pytest.mark.parametrize("registration", ["current", "detached", "replacement"])
async def test_legacy_stdio_failure_preserves_replacement_session(
    tmp_path, monkeypatch, failure, registration
):
    manager = MCPManager(tmp_path / "mcp.json")
    server = MCPServerConfig("probe", "", transport="stdio", command="probe")
    process = SimpleNamespace(
        returncode=None,
        stdin=SimpleNamespace(write=Mock(), drain=AsyncMock()),
        stdout=object(),
        terminate=Mock(),
        kill=Mock(),
        wait=AsyncMock(return_value=0),
    )
    session = {"process": process, "lock": asyncio.Lock(), "protocol": "legacy"}
    replacement_process = Mock()
    replacement = {"process": replacement_process}
    manager._stdio_sessions[server.name] = session
    monkeypatch.setattr(manager, "_get_or_create_stdio_session", AsyncMock(return_value=session))

    async def readline(child, *, timeout):
        assert child is process
        if registration == "replacement":
            manager._stdio_sessions[server.name] = replacement
        elif registration == "detached":
            manager._stdio_sessions.pop(server.name)
        if failure == "read":
            raise MCPToolError("mcp_error:stdio_process_exit")
        process.returncode = 1
        return b'{"ok": true, "output": "stale response"}\n'

    monkeypatch.setattr(manager, "_stdio_readline", readline)

    with pytest.raises(MCPToolError, match="mcp_error:stdio_process_exit"):
        await manager._call_stdio_tool(server, "read", {})

    if registration == "replacement":
        assert manager._stdio_sessions.get(server.name) is replacement
    else:
        assert server.name not in manager._stdio_sessions
    assert process.terminate.call_count == int(failure == "read")
    replacement_process.terminate.assert_not_called()
    replacement_process.kill.assert_not_called()


@pytest.mark.asyncio
async def test_sse_close_preserves_caller_cancellation(tmp_path):
    manager = MCPManager(tmp_path / "mcp.json")
    reader_started = asyncio.Event()
    cleanup_started = asyncio.Event()
    never_finishes = asyncio.Event()

    async def reader():
        reader_started.set()
        try:
            await never_finishes.wait()
        finally:
            cleanup_started.set()
            await never_finishes.wait()

    reader_task = asyncio.create_task(reader())
    close_task = None
    try:
        await asyncio.wait_for(reader_started.wait(), timeout=1.0)
        close_task = asyncio.create_task(
            manager._close_sse_session({"stop": asyncio.Event(), "task": reader_task})
        )
        await asyncio.wait_for(cleanup_started.wait(), timeout=1.0)
        close_task.cancel("shutdown cancelled")

        with pytest.raises(asyncio.CancelledError, match="shutdown cancelled"):
            await asyncio.wait_for(close_task, timeout=1.0)

        assert reader_task.cancelled()
    finally:
        tasks = [reader_task]
        if close_task is not None:
            tasks.append(close_task)
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
