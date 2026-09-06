import asyncio
import json
import traceback
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from modules.agent.mcp_manager import MCPManager, MCPServerConfig, _log_task_exception
from modules.tools.mcp_bridge import MCPToolError, call_http_mcp_tool
from routes.workspace_api import create_workspace_router

SECRET = "https://user:token-secret@example.test/mcp?access_token=query-secret Authorization: Bearer header-secret"


def assert_safe_error(exc):
    rendered = "".join(traceback.format_exception(exc))
    for secret in ("token-secret", "query-secret", "header-secret"):
        assert secret not in rendered
    assert str(exc).startswith("mcp_error:")


@pytest.mark.asyncio
async def test_http_status_redacts_auth_url_exception(tmp_path, monkeypatch):
    manager = MCPManager(tmp_path / "mcp.json")
    server = MCPServerConfig(
        name="private",
        base_url="https://user:secret@example.test/mcp?token=hidden",
        transport="http",
    )

    class FailingClient:
        async def __aenter__(self):
            raise RuntimeError("GET https://user:secret@example.test/mcp Authorization: Bearer hidden")

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("modules.agent.mcp_manager.httpx.AsyncClient", lambda **kwargs: FailingClient())
    status = await manager._check_server_status(server)

    serialized = repr(status)
    assert "secret" not in serialized
    assert "Bearer" not in serialized
    assert "example.test" not in serialized
    assert status["message"] == "mcp_error:runtimeerror"
    assert status["last_error"] == "mcp_error:runtimeerror"


def test_history_error_field_is_bounded_to_safe_code(tmp_path):
    manager = MCPManager(tmp_path / "mcp.json")
    manager._append_history(
        "private",
        "failed",
        "failed",
        status="error",
        error="https://user:secret@example.test Authorization: Bearer hidden",
    )
    history = manager._telemetry["private"]["history"]
    assert history[0]["error"] == "mcp_error:internal"


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["http", "stdio", "sse", "streamable_http"])
async def test_tool_boundary_suppresses_upstream_error_traceback(tmp_path, monkeypatch, transport):
    manager = MCPManager(tmp_path / "mcp.json")
    manager.servers["private"] = MCPServerConfig("private", "https://example.test", transport=transport)
    failure = AsyncMock(side_effect=RuntimeError(SECRET))
    if transport == "http":
        monkeypatch.setattr("modules.agent.mcp_manager.call_http_mcp_tool", failure)
    else:
        method = {"stdio": "_call_stdio_tool", "sse": "_call_sse_tool", "streamable_http": "_streamable_http_request"}[transport]
        monkeypatch.setattr(manager, method, failure)
    with pytest.raises(MCPToolError) as caught:
        await manager.call_tool("private", "read", {})
    assert str(caught.value) == "mcp_error:runtimeerror"
    assert_safe_error(caught.value)
    assert manager._telemetry["private"]["total_failures"] == 1
    assert SECRET not in repr(manager._telemetry)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["provider_error", "invalid_json", "invalid_shape", "http_error", "connection_error"])
async def test_http_bridge_rejects_unsafe_errors(monkeypatch, mode):
    def respond(request):
        if mode == "connection_error":
            raise httpx.ConnectError(SECRET, request=request)
        if mode == "http_error":
            return httpx.Response(503, text=SECRET)
        if mode == "invalid_json":
            return httpx.Response(200, text=SECRET)
        return httpx.Response(200, json=[] if mode == "invalid_shape" else {"ok": False, "error": SECRET})

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    monkeypatch.setattr("modules.tools.mcp_bridge.httpx.AsyncClient", lambda **kwargs: client)
    endpoint = "https://user:token-secret@example.test"
    with pytest.raises(MCPToolError) as caught:
        await call_http_mcp_tool(endpoint, "read", {})
    assert_safe_error(caught.value)


@pytest.mark.asyncio
async def test_http_bridge_preserves_success_output_and_auth_headers(monkeypatch):
    def respond(request):
        assert request.headers["Authorization"] == "Bearer runtime-only"
        assert json.loads(request.content) == {"name": "read", "args": {"path": "notes"}}
        return httpx.Response(200, json={"ok": True, "output": "read result"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    monkeypatch.setattr("modules.tools.mcp_bridge.httpx.AsyncClient", lambda **kwargs: client)
    output = await call_http_mcp_tool("https://example.test", "read", {"path": "notes"}, headers={"Authorization": "Bearer runtime-only"})
    assert output == "read result"


@pytest.mark.asyncio
async def test_streamable_jsonrpc_error_hides_provider_message(tmp_path, monkeypatch):
    def respond(request):
        payload = json.loads(request.content)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "error": {"message": SECRET}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    monkeypatch.setattr("modules.agent.mcp_manager.httpx.AsyncClient", lambda **kwargs: client)
    manager = MCPManager(tmp_path / "mcp.json")
    with pytest.raises(MCPToolError) as caught:
        await manager._streamable_http_raw_request(
            MCPServerConfig("private", "https://example.test"), "tools/call", {}, session_id=None, timeout=1,
        )
    assert str(caught.value) == "mcp_error:jsonrpc_error"
    assert_safe_error(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["provider_error", "invalid_json", "eof"])
async def test_stdio_jsonrpc_error_and_stderr_do_not_escape(tmp_path, mode):
    request = {}

    async def readline():
        if mode == "eof":
            return b""
        if mode == "invalid_json":
            return SECRET.encode()
        return json.dumps({"jsonrpc": "2.0", "id": request["id"], "error": {"message": SECRET}}).encode()

    process = SimpleNamespace(
        stdin=SimpleNamespace(write=lambda raw: request.update(json.loads(raw)), drain=AsyncMock()),
        stdout=SimpleNamespace(readline=readline),
        stderr=SimpleNamespace(read=AsyncMock(return_value=SECRET.encode())),
    )
    manager = MCPManager(tmp_path / "mcp.json")
    with pytest.raises(MCPToolError) as caught:
        await manager._stdio_jsonrpc_request_locked({"process": process}, "tools/call", {})
    assert_safe_error(caught.value)
    process.stderr.read.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["provider_error", "invalid_json", "process_exit"])
async def test_legacy_stdio_errors_hide_payloads(tmp_path, monkeypatch, mode):
    payload = SECRET.encode() if mode == "invalid_json" else json.dumps({"ok": False, "error": SECRET}).encode()
    process = SimpleNamespace(
        stdin=SimpleNamespace(write=lambda raw: None, drain=AsyncMock()),
        stdout=SimpleNamespace(readline=AsyncMock(return_value=payload)),
        stderr=SimpleNamespace(read=AsyncMock(return_value=SECRET.encode())),
        returncode=1 if mode == "process_exit" else None,
    )
    manager = MCPManager(tmp_path / "mcp.json")
    session = {"process": process, "protocol": "legacy", "lock": asyncio.Lock()}
    monkeypatch.setattr(manager, "_get_or_create_stdio_session", AsyncMock(return_value=session))
    with pytest.raises(MCPToolError) as caught:
        await manager._call_stdio_tool(MCPServerConfig("private", "", command="test"), "read", {})
    assert_safe_error(caught.value)
    process.stderr.read.assert_not_awaited()


@pytest.mark.asyncio
async def test_sse_provider_failure_hides_event_payload(tmp_path, monkeypatch):
    session = {"pending": {}}

    def respond(request):
        request_id = json.loads(request.content)["requestId"]
        session["pending"][request_id]["future"].set_result({"ok": False, "error": SECRET})
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    monkeypatch.setattr("modules.agent.mcp_manager.httpx.AsyncClient", lambda **kwargs: client)
    manager = MCPManager(tmp_path / "mcp.json")
    monkeypatch.setattr(manager, "_get_or_create_sse_session", AsyncMock(return_value=session))
    with pytest.raises(MCPToolError) as caught:
        await manager._call_sse_tool(MCPServerConfig("private", "https://example.test"), "read", {}, "request", [])
    assert str(caught.value) == "mcp_error:sse_tool_error"
    assert_safe_error(caught.value)
    assert session["pending"] == {}


def test_tool_result_keeps_success_content_and_hides_error_content(tmp_path):
    manager = MCPManager(tmp_path / "mcp.json")
    assert manager._format_stdio_tool_result({"content": [{"type": "text", "text": "read result"}]}) == "read result"
    with pytest.raises(MCPToolError) as caught:
        manager._format_stdio_tool_result({"isError": True, "structuredContent": {"error": SECRET}})
    assert_safe_error(caught.value)


@pytest.mark.asyncio
async def test_background_task_log_omits_exception_and_task_name(caplog):
    async def fail():
        raise RuntimeError(SECRET)

    task = asyncio.create_task(fail(), name=SECRET)
    await asyncio.gather(task, return_exceptions=True)
    _log_task_exception(task)
    assert "mcp_error:runtimeerror" in caplog.text
    assert "token-secret" not in caplog.text
    assert "header-secret" not in caplog.text


def test_public_endpoint_projection_preserves_canonical_config(tmp_path, monkeypatch):
    vault = {}
    class FakeResponse:
        status_code = 200
        def __init__(self, payload): self._payload = payload
        def json(self): return self._payload
    class FakeClient:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def post(self, url, json, headers):
            assert headers["Authorization"] == "Bearer test-vault-token"
            operation = json["operation"]
            if operation == "store":
                ref = f"ref-{len(vault) + 1}"
                vault[ref] = json["document"]
                return FakeResponse({"ok": True, "reference": ref})
            if operation == "read":
                return FakeResponse({"ok": True, "document": vault[json["reference"]]})
            if operation == "prune":
                vault.pop(json["reference"], None)
                return FakeResponse({"ok": True})
            return FakeResponse({"ok": False})
    monkeypatch.setattr("modules.agent.mcp_manager.httpx.Client", FakeClient)
    monkeypatch.setenv("YUIZAKI_MCP_VAULT_URL", "http://127.0.0.1:9876/api/internal/mcp-config-vault")
    monkeypatch.setenv("YUIZAKI_MCP_VAULT_TOKEN", "test-vault-token")
    url = "https://user:token-secret@[::1]:8443/mcp?custom=query-secret&tools=read#header-secret"
    monkeypatch.setenv("YUIZAKI_MCP_GITHUB_URL", url)
    manager = MCPManager(tmp_path / "mcp.json")
    env = {"MEMORY_FILE_PATH": "local.jsonl", "PORT": "{env:MCP_PORT|9222}"}
    headers = {"Authorization": "Bearer {env:MCP_TEST_TOKEN}"}
    mutation = manager.add_server("private", url, env=env, headers=headers)
    snapshot = manager.snapshot()
    for public in (mutation, snapshot):
        assert "token-secret" not in repr(public)
        assert "query-secret" not in repr(public)
        assert "header-secret" not in repr(public)
        assert "[::1]:8443" in repr(public)
    reloaded = MCPManager(tmp_path / "mcp.json")
    assert reloaded.servers["private"].base_url == url
    assert reloaded.servers["private"].env == env
    assert reloaded.servers["private"].headers == headers
    assert reloaded._matches_stdio_preset(reloaded.servers["memory_graph"])
    monkeypatch.setenv("MCP_TEST_TOKEN", "runtime-only")
    assert reloaded._request_headers(reloaded.servers["private"])["Authorization"] == "Bearer runtime-only"
    pointer = json.loads((tmp_path / "mcp.json").read_text())
    assert "vault_ref" in pointer and "token-secret" not in repr(pointer)


def test_vault_outage_does_not_overwrite_pointer(tmp_path, monkeypatch):
    store = tmp_path / "mcp.json"
    store.write_text(json.dumps({"version": 1, "vault_ref": {"namespace": "wrong", "reference": "old"}}))
    monkeypatch.setenv("YUIZAKI_MCP_VAULT_URL", "http://127.0.0.1:9876/api/internal/mcp-config-vault")
    monkeypatch.setenv("YUIZAKI_MCP_VAULT_TOKEN", "test-vault-token")
    class Down:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def post(self, *args, **kwargs): raise OSError("offline")
    monkeypatch.setattr("modules.agent.mcp_manager.httpx.Client", Down)
    before = store.read_text()
    manager = MCPManager(store)
    assert manager.servers == {}
    assert manager.snapshot()["storageError"] == "mcp_error:mcptoolerror"
    assert store.read_text() == before


def test_vault_endpoint_rejects_query_and_userinfo(tmp_path, monkeypatch):
    monkeypatch.setenv("YUIZAKI_MCP_VAULT_TOKEN", "test-vault-token")
    monkeypatch.setenv("YUIZAKI_MCP_VAULT_URL", "http://user:secret@127.0.0.1:9876/vault?token=leak")
    manager = MCPManager(tmp_path / "mcp.json")
    assert manager._vault_configured() is False


def test_server_mutations_restore_replaced_config_when_persist_fails(tmp_path, monkeypatch):
    manager = MCPManager(tmp_path / "mcp.json")
    original = MCPServerConfig("private", "http://old.example/mcp", enabled=False)
    manager.servers[original.name] = original

    def fail_save():
        raise MCPToolError("mcp_error:vault_unavailable")

    monkeypatch.setattr(manager, "_save_store", fail_save)
    with pytest.raises(MCPToolError):
        manager.add_server("private", "http://new.example/mcp")
    assert manager.servers["private"] is original

    existing_preset = manager.servers["memory_graph"]
    with pytest.raises(MCPToolError):
        manager.install_preset("memory_graph")
    assert manager.servers["memory_graph"] is existing_preset


@pytest.mark.asyncio
async def test_workspace_effective_preset_uses_public_endpoint(tmp_path):
    manager = MCPManager(tmp_path / "mcp.json")
    manager.servers["private"] = MCPServerConfig("private", "https://user:token-secret@example.test?key=query-secret")
    repo = SimpleNamespace(list_workspaces=lambda: [{"id": "local", "mcp_preset_id": "private"}])
    app = FastAPI()
    app.include_router(create_workspace_router(lambda: repo, get_mcp_manager=lambda: manager))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/workspaces/local/effective-preset")
    assert response.status_code == 200
    assert response.json()["mcp_server"]["base_url"].startswith("https://example.test")
    assert "token-secret" not in response.text
    assert "query-secret" not in response.text
