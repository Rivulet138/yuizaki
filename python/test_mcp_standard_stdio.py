from __future__ import annotations

import sys
from pathlib import Path

import pytest

from modules.agent.mcp_manager import MCPManager, MCPServerConfig
from modules.agent.tool_registry import ToolRegistry


def _write_fake_mcp_server(path: Path) -> None:
    path.write_text(
        """
import json
import sys


def send(payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\\n")
    sys.stdout.flush()


for line in sys.stdin:
    if not line.strip():
        continue
    payload = json.loads(line)
    method = payload.get("method")
    request_id = payload.get("id")
    if method == "initialize":
        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": payload.get("params", {}).get("protocolVersion"),
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "fake-yuizaki-mcp", "version": "0.1.0"},
            },
        })
    elif method == "notifications/initialized":
        continue
    elif method == "tools/list":
        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo text back",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                    }
                ]
            },
        })
    elif method in {"resources/list", "prompts/list"}:
        key = "resources" if method == "resources/list" else "prompts"
        send({"jsonrpc": "2.0", "id": request_id, "result": {key: []}})
    elif method == "tools/call":
        params = payload.get("params", {})
        args = params.get("arguments", {})
        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": "echo: " + str(args.get("text", ""))}],
                "isError": False,
            },
        })
    else:
        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": "unknown method"},
        })
""".strip(),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_standard_stdio_mcp_inventory_call_and_dynamic_registration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YUIZAKI_ALLOW_CUSTOM_MCP_STDIO", "true")
    server_script = tmp_path / "fake_mcp_server.py"
    _write_fake_mcp_server(server_script)

    manager = MCPManager()
    registry = ToolRegistry()
    manager.servers = {
        "daily": MCPServerConfig(
            name="daily",
            base_url="",
            transport="stdio",
            enabled=True,
            command=sys.executable,
            args=[str(server_script)],
        )
    }
    manager.status = {}
    manager.register_tools(registry)

    try:
        status = await manager.refresh_one("daily")
        assert status is not None
        assert status["ok"] is True
        assert status["connected"] is True
        assert status["tools_count"] == 1
        assert status["tools"][0]["name"] == "echo"

        output = await manager.call_tool("daily", "echo", {"text": "hello"})
        assert output == "echo: hello"

        dynamic_tool = registry.get("mcp_daily_echo")
        assert dynamic_tool is not None
        assert dynamic_tool.parameters["required"] == ["text"]
        assert dynamic_tool.require_confirm is True
    finally:
        await manager.shutdown()
