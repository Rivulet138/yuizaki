from __future__ import annotations

import os
from typing import Any

import httpx

from .tool_registry import ToolDefinition, ToolRegistry
from .tool_result import ToolResultEnvelope


def _parse_port(value: str | None, fallback: int) -> int:
    try:
        port = int(str(value or "").strip())
    except ValueError:
        return fallback
    return port if 0 < port <= 65535 else fallback


def _control_origin() -> str:
    configured = os.getenv("YUIZAKI_CONTROL_ORIGIN", "").strip() or os.getenv("CONTROL_ORIGIN", "").strip()
    if configured:
        return configured.rstrip("/")
    return f"http://127.0.0.1:{_parse_port(os.getenv('CONTROL_SERVER_PORT'), 38945)}"


def _control_headers() -> dict[str, str]:
    token = os.getenv("YUIZAKI_BACKEND_API_TOKEN", "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def _infer_plugin_contribution_categories(plugin: dict[str, Any]) -> list[str]:
    categories: list[str] = []
    if plugin.get("toolCapabilities") or plugin.get("modelProviders"):
        categories.append("capability")
    if plugin.get("routes"):
        categories.append("event")
    permissions = plugin.get("permissions") or {}
    if isinstance(permissions, dict) and any(permissions.get(key) for key in ["routes", "toolScopes", "modelScopes", "allowedHosts", "allowedPaths"]):
        categories.append("policy")
    return categories


async def fetch_plugin_snapshot() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{_control_origin()}/api/plugin/list", headers=_control_headers())
        resp.raise_for_status()
        return resp.json()


def register_plugin_tools(registry: ToolRegistry, snapshot: dict[str, Any]) -> None:
    plugins = snapshot.get("plugins") or []
    routes = snapshot.get("routes") or []
    route_map = {route.get("id"): route for route in routes if isinstance(route, dict) and route.get("id")}

    for plugin in plugins:
        if not isinstance(plugin, dict):
            continue
        plugin_id = plugin.get("id")
        permissions = plugin.get("permissions") or {}
        allowed_tool_scopes = set(permissions.get("toolScopes") or [])
        allowed_routes = list(permissions.get("routes") or [])
        contribution_categories = _infer_plugin_contribution_categories(plugin)
        if not plugin_id:
            continue

        tool_capabilities = plugin.get("toolCapabilities") or []
        for capability in tool_capabilities:
            if not isinstance(capability, dict):
                continue
            capability_id = capability.get("id")
            if not capability_id or capability_id not in allowed_tool_scopes:
                continue

            target_route_id = allowed_routes[0] if allowed_routes else None
            if not target_route_id or target_route_id not in route_map:
                continue

            async def _handler(args: dict[str, Any], *, _plugin_id=plugin_id, _route_id=target_route_id, _capability_id=capability_id) -> ToolResultEnvelope:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        f"{_control_origin()}/api/plugin/{_plugin_id}/{_route_id}",
                        json={
                            "capabilityId": _capability_id,
                            "args": args,
                        },
                        headers=_control_headers(),
                    )
                    data = resp.json()
                    if resp.is_success:
                        return ToolResultEnvelope(
                            success=True,
                            content=str(data.get("message") or data.get("result") or data.get("ok") or "Plugin tool executed"),
                            source="plugin",
                            tool_name=f"plugin.{_plugin_id}.{_capability_id}",
                            data=data,
                        )
                    return ToolResultEnvelope(
                        success=False,
                        content="",
                        source="plugin",
                        tool_name=f"plugin.{_plugin_id}.{_capability_id}",
                        error=str(data.get("error") or f"Plugin tool failed with status {resp.status_code}"),
                        data=data,
                    )

            registry.register(ToolDefinition(
                name=f"plugin.{plugin_id}.{capability_id}",
                description=str(capability.get("desc") or capability.get("name") or capability_id),
                source="plugin",
                parameters={"type": "object", "properties": {"args": {"type": "object"}}},
                handler=_handler,
                risk_level="medium",
                require_confirm=True,
                tags=["plugin", str(plugin_id), *[f"contrib:{category}" for category in contribution_categories]],
                scopes=[f"plugin:{plugin_id}", f"plugin-capability:{capability_id}"],
            ))
