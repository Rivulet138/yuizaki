from __future__ import annotations

import pytest

from modules.agent.policy_engine import PolicyEngine
from modules.agent.tool_registry import ToolRegistry
from modules.agent_plugins.manager import PluginManager


@pytest.mark.asyncio
async def test_dsh_delegate_plugin_registers_a_confirm_required_tool(tmp_path) -> None:
    """The plugin is discovered by package scan; its tool must reach the registry."""
    registry = ToolRegistry()
    manager = PluginManager(store_file=tmp_path / "agent_plugins.json")
    await manager.discover_and_load(registry)

    tool = registry.get("ask_dsh")
    assert tool is not None, "ask_dsh must be registered by the dsh-delegate plugin"
    assert tool.source == "plugin"
    assert tool.risk_level == "high"
    assert tool.require_confirm is True
    assert tool.effect_kind == "write"
    assert tool.context_handler is not None
    assert tool.parameters["required"] == ["task"]
    assert tool.parameters["additionalProperties"] is False

    names = {item["name"] for item in registry.list_capabilities()}
    assert "ask_dsh" in names


@pytest.mark.asyncio
async def test_dsh_tool_requires_permission_even_when_plugin_is_enabled(tmp_path) -> None:
    """Plugin enablement must not authorize a high-risk tool."""
    registry = ToolRegistry()
    manager = PluginManager(store_file=tmp_path / "agent_plugins.json")
    await manager.discover_and_load(registry)
    tool = registry.get("ask_dsh")
    assert tool is not None

    engine = PolicyEngine()
    preview = engine.preview_tool(tool)
    assert preview.allowed is False
    assert preview.require_confirm is True

    decision = engine.evaluate_tool(tool, request_id="req-ask-dsh")
    assert decision.allowed is False
    assert decision.require_confirm is True
    assert decision.permission_receipt is not None
    assert decision.permission_receipt.decision == "required"
