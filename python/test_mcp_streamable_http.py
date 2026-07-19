from __future__ import annotations

from fastapi import FastAPI, Request
import httpx
import pytest

from modules.agent.mcp_manager import MCPManager, MCPServerConfig
from modules.agent.tool_registry import ToolRegistry


def _build_mcp_app() -> FastAPI:
    app = FastAPI()

    @app.post("/mcp")
    async def mcp_endpoint(request: Request):
        payload = await request.json()
        method = payload.get("method")
        request_id = payload.get("id")
        headers = {"Mcp-Session-Id": "session-test"}
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {"listChanged": True}},
                    "serverInfo": {"name": "fake-http-mcp", "version": "0.1.0"},
                },
            }
        if method == "notifications/initialized":
            return {}
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": [
                        {
                            "name": "remember",
                            "description": "Save a small memory",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}},
                                "required": ["text"],
                            },
                        }
                    ]
                },
            }
        if method in {"resources/list", "prompts/list"}:
            key = "resources" if method == "resources/list" else "prompts"
            return {"jsonrpc": "2.0", "id": request_id, "result": {key: []}}
        if method == "tools/call":
            text = payload.get("params", {}).get("arguments", {}).get("text", "")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": f"saved: {text}"}],
                    "isError": False,
                },
            }
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "unknown method"}}, headers

    return app


@pytest.mark.asyncio
async def test_streamable_http_mcp_inventory_call_and_dynamic_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = httpx.ASGITransport(app=_build_mcp_app())
    original_client = httpx.AsyncClient

    def _client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        kwargs["base_url"] = "http://testserver"
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory)

    manager = MCPManager()
    registry = ToolRegistry()
    manager.servers = {
        "daily_http": MCPServerConfig(
            name="daily_http",
            base_url="http://testserver/mcp",
            transport="streamable_http",
            enabled=True,
        )
    }
    manager.status = {}
    manager.register_tools(registry)

    status = await manager.refresh_one("daily_http")
    assert status is not None
    assert status["ok"] is True
    assert status["connected"] is True
    assert status["tools_count"] == 1
    assert status["tools"][0]["name"] == "remember"

    output = await manager.call_tool("daily_http", "remember", {"text": "buy milk"})
    assert output == "saved: buy milk"

    dynamic_tool = registry.get("mcp_daily_http_remember")
    assert dynamic_tool is not None
    assert dynamic_tool.parameters["required"] == ["text"]
