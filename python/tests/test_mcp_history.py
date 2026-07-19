import asyncio
import importlib

pytest = importlib.import_module("pytest")

mcp_manager_module = importlib.import_module("modules.agent.mcp_manager")
mcp_bridge_module = importlib.import_module("modules.tools.mcp_bridge")

MCPManager = mcp_manager_module.MCPManager
MCPServerConfig = mcp_manager_module.MCPServerConfig
MCPToolError = mcp_bridge_module.MCPToolError


@pytest.mark.asyncio
async def test_http_mcp_tool_success_records_structured_history(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    manager = MCPManager()
    manager.servers = {
        "alpha": MCPServerConfig(name="alpha", base_url="http://127.0.0.1:7777", transport="http"),
    }

    async def fake_call_http_mcp_tool(base_url: str, tool_name: str, args: dict[str, object]) -> str:
        assert base_url == "http://127.0.0.1:7777"
        assert tool_name == "browser.open_page"
        assert args == {"url": "https://example.test", "wait": 1}
        return "opened"

    monkeypatch.setattr(mcp_manager_module, "call_http_mcp_tool", fake_call_http_mcp_tool)

    output = await manager.call_tool("alpha", "browser.open_page", {"url": "https://example.test", "wait": 1})

    assert output == "opened"
    telemetry = manager._ensure_telemetry("alpha")
    manager.status["alpha"] = {"enabled": True, "ok": True, "transport": "http", "connected": True, **telemetry}
    history = manager.snapshot()["status"]["alpha"]["history"]

    started = history[-2]
    succeeded = history[-1]
    assert started["event"] == "tool_call_started"
    assert started["status"] == "started"
    assert started["transport"] == "http"
    assert started["tool"] == "browser.open_page"
    assert started["args_keys"] == ["url", "wait"]
    assert succeeded["event"] == "tool_call_succeeded"
    assert succeeded["status"] == "ok"
    assert succeeded["request_id"] == started["request_id"]
    assert isinstance(succeeded["duration_ms"], int)
    assert succeeded["output_chars"] == len("opened")
    assert succeeded["total_calls"] == 1
    assert succeeded["total_failures"] == 0


@pytest.mark.asyncio
async def test_http_mcp_tool_failure_records_error_history(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    manager = MCPManager()
    manager.servers = {
        "alpha": MCPServerConfig(name="alpha", base_url="http://127.0.0.1:7777", transport="http"),
    }

    async def fake_call_http_mcp_tool(base_url: str, tool_name: str, args: dict[str, object]) -> str:
        raise MCPToolError("boom")

    monkeypatch.setattr(mcp_manager_module, "call_http_mcp_tool", fake_call_http_mcp_tool)

    with pytest.raises(MCPToolError, match="boom"):
        await manager.call_tool("alpha", "browser.open_page", {"url": "https://example.test"})

    telemetry = manager._ensure_telemetry("alpha")
    failed = telemetry["history"][-1]
    assert failed["event"] == "tool_call_failed"
    assert failed["status"] == "error"
    assert failed["transport"] == "http"
    assert failed["tool"] == "browser.open_page"
    assert failed["error"] == "boom"
    assert failed["total_calls"] == 1
    assert failed["total_failures"] == 1
    assert telemetry["last_error"] == "boom"


@pytest.mark.asyncio
async def test_disabled_mcp_server_snapshot_preserves_history(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = MCPManager()
    manager.servers = {
        "alpha": MCPServerConfig(name="alpha", base_url="http://127.0.0.1:7777", transport="http"),
    }

    manager.set_enabled("alpha", False)
    await manager.refresh_one("alpha")

    status = manager.snapshot()["status"]["alpha"]
    assert status["enabled"] is False
    assert status["connected"] is False
    assert status["transport"] == "http"
    assert status["history"][-1]["event"] == "disabled"
    assert status["history"][-1]["status"] == "disabled"


@pytest.mark.asyncio
async def test_sse_pending_failure_records_request_id_and_pending_count(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = MCPManager()
    manager.servers = {
        "stream": MCPServerConfig(name="stream", base_url="http://127.0.0.1:7777", transport="sse"),
    }
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    session = {
        "server_name": "stream",
        "pending": {
            "req-1": {
                "future": future,
                "created_at": loop.time() - 80,
            },
        },
    }

    manager._sse_sessions["stream"] = session
    manager._fail_pending(session, "timed out", only_stale=True, ttl_seconds=65)

    assert future.done()
    with pytest.raises(MCPToolError, match="timed out"):
        future.result()
    entry = manager._ensure_telemetry("stream")["history"][-1]
    assert entry["event"] == "pending_failed"
    assert entry["status"] == "error"
    assert entry["transport"] == "sse"
    assert entry["request_id"] == "req-1"
    assert entry["error"] == "timed out"
    assert entry["pending_requests"] == 0


@pytest.mark.asyncio
async def test_sse_first_tool_call_waits_for_ready_event_before_dispatch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = MCPManager()
    manager.servers = {
        "stream": MCPServerConfig(name="stream", base_url="http://127.0.0.1:7777", transport="sse"),
    }
    ready_seen = False
    post_saw_ready = False

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def raise_for_status(self) -> None:
            return None

        async def aiter_lines(self):
            nonlocal ready_seen
            await asyncio.sleep(0)
            yield "event: ready"
            yield "data: {\"ok\":true}"
            yield ""
            ready_seen = True
            await asyncio.Event().wait()

    class FakeAsyncClient:
        def __init__(self, timeout=None):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def stream(self, method, url, headers=None):
            assert method == "GET"
            assert url == "http://127.0.0.1:7777/events"
            assert headers == {"Accept": "text/event-stream"}
            return FakeStream()

        async def post(self, url, json):
            nonlocal post_saw_ready
            assert url == "http://127.0.0.1:7777/tools"
            post_saw_ready = ready_seen
            request_id = json["requestId"]
            pending = manager._sse_sessions["stream"]["pending"][request_id]
            pending["future"].set_result({"ok": True, "output": "streamed", "requestId": request_id})
            return FakeResponse()

    monkeypatch.setattr(mcp_manager_module.httpx, "AsyncClient", FakeAsyncClient)

    output = await manager.call_tool("stream", "browser.open_page", {"url": "https://example.test"})
    await manager.shutdown()

    history = manager._ensure_telemetry("stream")["history"]
    assert output == "streamed"
    assert post_saw_ready is True
    assert [entry["event"] for entry in history].index("sse_connected") < [entry["event"] for entry in history].index("sse_request_queued")


@pytest.mark.asyncio
async def test_sse_quiet_timeout_records_pending_failed_with_same_request_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mcp_manager_module, "SSE_TOOL_TIMEOUT_SECONDS", 0.01)
    manager = MCPManager()
    manager.servers = {
        "stream": MCPServerConfig(name="stream", base_url="http://127.0.0.1:7777", transport="sse"),
    }

    async def fake_get_or_create_sse_session(server):
        ready = asyncio.Event()
        ready.set()
        session = {
            "server_name": server.name,
            "session_id": "sse_test",
            "pending": {},
            "ready": ready,
            "stop": asyncio.Event(),
        }
        manager._sse_sessions[server.name] = session
        return session

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, timeout=None):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            return FakeResponse()

    monkeypatch.setattr(manager, "_get_or_create_sse_session", fake_get_or_create_sse_session)
    monkeypatch.setattr(mcp_manager_module.httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(MCPToolError, match="timed out"):
        await manager.call_tool("stream", "browser.open_page", {"url": "https://example.test"})

    history = manager._ensure_telemetry("stream")["history"]
    queued = next(entry for entry in history if entry["event"] == "sse_request_queued")
    pending_failed = next(entry for entry in history if entry["event"] == "pending_failed")
    tool_failed = history[-1]
    assert pending_failed["request_id"] == queued["request_id"]
    assert pending_failed["pending_requests"] == 0
    assert pending_failed["error"] == "MCP SSE request timed out waiting for event"
    assert tool_failed["event"] == "tool_call_failed"
    assert tool_failed["request_id"] == queued["request_id"]
