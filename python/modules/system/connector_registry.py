"""Unified connector status projection for local governance UI.

The registry is deliberately read-only. It projects existing MCP and Agent
plugin state and lists planned adapters without initializing external services.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = 1
CONNECTOR_STATES = ("uninstalled", "disabled", "running", "failure")

_PLANNED_CONNECTORS = (
    {
        "id": "telegram",
        "name": "Telegram",
        "kind": "external_message",
        "capabilities": ["message-in", "message-out"],
        "dataFlow": ["Telegram -> Agent 会话", "Agent -> Telegram"],
        "message": "Telegram 适配器尚未安装",
    },
    {
        "id": "discord",
        "name": "Discord",
        "kind": "external_message",
        "capabilities": ["message-in", "message-out"],
        "dataFlow": ["Discord -> Agent 会话", "Agent -> Discord"],
        "message": "Discord 适配器尚未安装",
    },
    {
        "id": "qq",
        "name": "QQ 个人账号兼容桥",
        "kind": "external_message",
        "capabilities": ["message-in", "message-out", "webhook"],
        "dataFlow": ["QQ 兼容桥事件 -> Agent 会话", "Agent -> QQ 兼容桥"],
        "message": "QQ 个人账号兼容桥尚未配置",
    },
    {
        "id": "wechat",
        "name": "微信个人账号兼容桥",
        "kind": "external_message",
        "capabilities": ["message-in", "message-out", "callback"],
        "dataFlow": ["微信兼容桥事件 -> Agent 会话", "Agent -> 微信兼容桥"],
        "message": "微信个人账号兼容桥尚未配置",
    },
    {
        "id": "game",
        "name": "游戏 Agent",
        "kind": "game_adapter",
        "capabilities": ["game-state", "game-action"],
        "dataFlow": ["游戏状态 -> Agent", "Agent -> 游戏输入"],
        "message": "游戏 adapter 尚未安装",
    },
)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _planned_connector(spec: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _text(spec.get("id")),
        "name": _text(spec.get("name"), "未命名连接器"),
        "kind": _text(spec.get("kind"), "planned"),
        "state": "uninstalled",
        "installed": False,
        "enabled": False,
        "canDisable": False,
        "experimental": True,
        "capabilities": list(spec.get("capabilities") or []),
        "dataFlow": list(spec.get("dataFlow") or []),
        "permissionScope": f"connector:{_text(spec.get('id'))}",
        "message": _text(spec.get("message"), "适配器尚未安装"),
        "lastError": None,
        "source": "planned",
    }


def _mcp_connector(name: str, config: Mapping[str, Any], status: Mapping[str, Any]) -> dict[str, Any]:
    enabled = bool(status.get("enabled", config.get("enabled", False)))
    connected = status.get("connected") is True
    last_error = _text(status.get("last_error") or status.get("inventory_error"))
    message = _text(status.get("message"))
    if not enabled:
        state = "disabled"
        message = "已停用"
    elif connected:
        state = "running"
        message = message or "连接正常"
    else:
        state = "failure"
        message = message or "连接未建立"
    return {
        "id": f"mcp:{name}",
        "name": name,
        "kind": "mcp",
        "state": state,
        "installed": True,
        "enabled": enabled,
        "canDisable": True,
        "experimental": False,
        "capabilities": ["tools", "resources", "prompts"],
        "dataFlow": ["Agent -> MCP 服务", "MCP 服务 -> 工具/资源"],
        "permissionScope": f"mcp:{name}",
        "message": message,
        "lastError": last_error or None,
        "transport": _text(status.get("transport") or config.get("transport")),
        "toolsCount": int(status.get("tools_count") or 0),
        "source": "mcp",
    }


def _plugin_connector(plugin: Mapping[str, Any]) -> dict[str, Any]:
    plugin_id = _text(plugin.get("id"), "unknown")
    enabled = bool(plugin.get("enabled", True))
    loaded = bool(plugin.get("loaded", False))
    last_error = _text(plugin.get("error"))
    if not enabled:
        state = "disabled"
        message = "已停用"
    elif loaded and not last_error:
        state = "running"
        message = "插件已加载"
    else:
        state = "failure"
        message = last_error or "插件未加载"
    return {
        "id": f"plugin:{plugin_id}",
        "name": _text(plugin.get("name"), plugin_id),
        "kind": "agent_plugin",
        "state": state,
        "installed": True,
        "enabled": enabled,
        "canDisable": True,
        "experimental": False,
        "capabilities": ["agent-hooks", "agent-tools"],
        "dataFlow": ["Agent 生命周期 -> 插件", "插件 -> Agent 工具/事件"],
        "permissionScope": f"plugin:{plugin_id}",
        "message": message,
        "lastError": last_error or None,
        "source": "agent_plugin",
    }


def build_connector_registry_snapshot(
    *,
    mcp_snapshot: Mapping[str, Any] | None,
    plugin_snapshot: Mapping[str, Any] | None,
    adapter_registry: Any | None = None,
) -> dict[str, Any]:
    """Project existing runtime state without starting any connector."""

    mcp = _mapping(mcp_snapshot)
    plugin = _mapping(plugin_snapshot)
    servers = _mapping(mcp.get("servers"))
    statuses = _mapping(mcp.get("status"))
    connectors = [
        _mcp_connector(name, _mapping(config), _mapping(statuses.get(name)))
        for name, config in sorted(servers.items())
    ]
    plugins = plugin.get("plugins")
    if isinstance(plugins, list):
        connectors.extend(_plugin_connector(_mapping(item)) for item in plugins)
    if adapter_registry is None:
        connectors.extend(_planned_connector(spec) for spec in _PLANNED_CONNECTORS)
    else:
        snapshot = adapter_registry.snapshot()
        if isinstance(snapshot, list):
            connectors.extend(dict(item) for item in snapshot if isinstance(item, Mapping))
        else:
            connectors.extend(_planned_connector(spec) for spec in _PLANNED_CONNECTORS)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": _now(),
        "connectors": connectors,
        "summary": {
            "total": len(connectors),
            "installed": sum(1 for item in connectors if item["installed"]),
            "enabled": sum(1 for item in connectors if item["enabled"]),
            "running": sum(1 for item in connectors if item["state"] == "running"),
            "failures": sum(1 for item in connectors if item["state"] == "failure"),
            "uninstalled": sum(1 for item in connectors if item["state"] == "uninstalled"),
            "canDisable": sum(1 for item in connectors if item["canDisable"]),
        },
    }


__all__ = ["CONNECTOR_STATES", "SCHEMA_VERSION", "build_connector_registry_snapshot"]
