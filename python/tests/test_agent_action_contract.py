from __future__ import annotations

import pytest

from modules.agent.action_compiler import compile_action_envelope
from modules.agent.context import AgentPipelineResult, AgentRequestContext
from modules.agent.pipeline import AgentPipeline


class _MutatingPluginManager:
    async def after_llm(self, result: AgentPipelineResult, _ctx: AgentRequestContext) -> AgentPipelineResult:
        result.reply = "插件处理后的回复"
        result.pet_control = {"emotion_id": "happy", "motion_group": "Tap", "motion_index": 0}
        result.tool_calls = [{"name": "new_tool"}]
        return result

    async def before_dispatch(self, result: AgentPipelineResult, _ctx: AgentRequestContext) -> AgentPipelineResult:
        return result


@pytest.mark.asyncio
async def test_finalize_result_rebuilds_action_envelope_after_plugin_hooks() -> None:
    original_tool_calls = [{"name": "old_tool"}]
    trace_suffix = {"execution_summary": {"success": True}}
    result = AgentPipelineResult(
        reply="原始回复",
        pet_control=None,
        tool_calls=original_tool_calls,
        action_envelope=compile_action_envelope(
            reply="原始回复",
            pet_control=None,
            tool_calls=[*original_tool_calls, trace_suffix],
            source="agent",
            request_id="req-plugin",
        ),
    )
    ctx = AgentRequestContext(
        sid="sid-plugin",
        session_id="session-plugin",
        messages=[],
        request_id="req-plugin",
        plugin_manager=_MutatingPluginManager(),  # type: ignore[arg-type]
    )

    finalized = await AgentPipeline().finalize_result(ctx, result)

    assert finalized.action_envelope is not None
    assert finalized.action_envelope["reply"] == "插件处理后的回复"
    assert finalized.action_envelope["request_id"] == "req-plugin"
    assert [action["type"] for action in finalized.action_envelope["actions"]] == [
        "reply",
        "pet_control",
        "tool_trace",
    ]
    assert finalized.action_envelope["actions"][1]["payload"]["emotion_id"] == "happy"
    assert finalized.action_envelope["actions"][2]["payload"] == [{"name": "new_tool"}, trace_suffix]
