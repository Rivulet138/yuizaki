from __future__ import annotations

import pytest

from modules.agent.policy_engine import PolicyEngine
from modules.agent.tool_registry import ToolDefinition
from modules.agent.tool_result import ToolResultEnvelope


def _tool(source="plugin", risk="high", **kwargs):
    return ToolDefinition(
        name="delegate.test",
        description="External write delegate",
        source=source,
        risk_level=risk,
        parameters={"type": "object"},
        handler=lambda _args: ToolResultEnvelope(True, "done", source, "delegate.test"),
        **kwargs,
    )


@pytest.mark.parametrize("source", ["builtin", "plugin", "mcp"])
@pytest.mark.parametrize("risk", ["high", "critical"])
@pytest.mark.parametrize("require_confirm", [False, True])
def test_high_risk_tools_require_confirmation(tmp_path, source, risk, require_confirm):
    engine = PolicyEngine(store_file=tmp_path / "permissions.json")
    tool = _tool(source, risk, require_confirm=require_confirm)

    preview = engine.preview_tool(tool)
    decision = engine.evaluate_tool(tool, request_id="request", parameters={"task": "work"})

    assert not preview.allowed and preview.require_confirm
    assert not decision.allowed and decision.require_confirm
    assert decision.permission_receipt is not None
    assert decision.permission_receipt.decision == "required"
    assert engine.get_audit_log()[-1]["decision"] == "required"


@pytest.mark.parametrize("source", ["plugin", "mcp"])
def test_selected_medium_external_tool_still_auto_allows(tmp_path, source):
    engine = PolicyEngine(store_file=tmp_path / "permissions.json")
    tool = _tool(source, "medium")
    assert engine.preview_tool(tool).allowed
    assert engine.evaluate_tool(tool).allowed
    assert engine.get_audit_log() == []


@pytest.mark.parametrize("source", ["plugin", "mcp"])
def test_force_confirmation_is_not_bypassed_by_enablement(tmp_path, source):
    engine = PolicyEngine(store_file=tmp_path / "permissions.json")
    tool = _tool(source, "medium")
    assert engine.preview_tool(tool, force_confirm=True).require_confirm
    assert engine.evaluate_tool(tool, force_confirm=True).require_confirm


@pytest.mark.asyncio
async def test_high_risk_remembered_decisions_are_scoped_and_can_require_fresh_approval(tmp_path):
    engine = PolicyEngine(store_file=tmp_path / "permissions.json")
    tool = _tool()
    engine.register_pending("allow")
    engine.register_pending("deny")
    engine.resolve_pending("allow", True, remember=True, tool_name=tool.name, permission_scope="repo-a")
    engine.resolve_pending("deny", False, remember=True, tool_name=tool.name, permission_scope="repo-b")

    assert engine.preview_tool(tool, permission_scope="repo-a").allowed
    assert engine.evaluate_tool(tool, permission_scope="repo-a").reason == "remembered"
    assert not engine.evaluate_tool(tool, permission_scope="repo-b").allowed
    assert engine.preview_tool(tool, permission_scope="repo-c").require_confirm
    assert engine.preview_tool(tool, permission_scope="repo-a", force_confirm=True).require_confirm
    tool.allow_remembered_decision = False
    assert engine.preview_tool(tool, permission_scope="repo-a").require_confirm
    assert not engine.preview_tool(tool, permission_scope="repo-b").allowed


@pytest.mark.asyncio
async def test_invalid_pending_responses_do_not_remember_or_audit(tmp_path):
    engine = PolicyEngine(store_file=tmp_path / "permissions.json")
    tool = _tool()

    assert engine.resolve_pending(
        "missing",
        True,
        remember=True,
        tool_name=tool.name,
        permission_scope="repo-a",
    ) is False
    assert engine.preview_tool(tool, permission_scope="repo-a").require_confirm
    assert engine.get_audit_log() == []

    engine.register_pending("request")
    assert engine.resolve_pending("request", True, tool_name=tool.name) is True
    assert engine.resolve_pending("request", False, remember=True, tool_name=tool.name) is False
    assert len(engine.get_audit_log()) == 1


@pytest.mark.asyncio
async def test_cancel_pending_unblocks_without_remembering_or_auditing(tmp_path):
    engine = PolicyEngine(store_file=tmp_path / "permissions.json")
    tool = _tool()
    future = engine.register_pending("request")

    assert engine.cancel_pending("request") is True
    assert await future is False
    assert engine.cancel_pending("request") is False
    assert engine.preview_tool(tool, permission_scope="repo-a").require_confirm
    assert engine.get_audit_log() == []
