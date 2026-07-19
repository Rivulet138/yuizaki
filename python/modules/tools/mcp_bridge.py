"""Bridge to external Node-based Playwright MCP server.

This module sends tool calls over HTTP to a configured Node server that
performs browser automation using Playwright.

The protocol is intentionally simple:

POST /tools
  { "name": "browser.open_page", "args": { ... } }

Response:
  { "ok": true, "output": "..." }
or
  { "ok": false, "error": "..." }
"""

from __future__ import annotations

import os
from typing import Any, Dict

import httpx


class MCPToolError(Exception):
    """Error raised when the MCP/Playwright server reports a failure."""


def _browser_mcp_base_url() -> str:
    return (
        os.getenv("YUIZAKI_BROWSER_MCP_URL", "").strip()
        or os.getenv("YUIZAKI_MCP_PLAYWRIGHT_URL", "").strip()
    ).rstrip("/")


async def call_http_mcp_tool(base_url: str, name: str, args: Dict[str, Any], headers: Dict[str, str] | None = None) -> str:
    """Call a browser automation tool on the MCP server.

    Parameters
    ----------
    name: str
        Tool name, e.g. "browser.open_page".
    args: dict
        Tool arguments.
    """

    server_url = base_url.rstrip("/") + "/tools"

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(server_url, json={"name": name, "args": args}, headers=headers)
        except httpx.RequestError as exc:  # pragma: no cover - network
            raise MCPToolError(f"MCP server unreachable: {exc}") from exc

    try:
        data = resp.json()
    except ValueError as exc:
        raise MCPToolError(f"Invalid JSON from MCP server: {resp.text[:200]}") from exc

    if not data.get("ok", False):
        raise MCPToolError(str(data.get("error", "Unknown MCP error")))

    return str(data.get("output", ""))


async def call_browser_tool(name: str, args: Dict[str, Any]) -> str:
    base_url = _browser_mcp_base_url()
    if not base_url:
        raise MCPToolError("Browser MCP URL is not configured")
    return await call_http_mcp_tool(base_url, name, args)
