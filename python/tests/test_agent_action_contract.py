from __future__ import annotations

import pytest

from modules.agent.action_compiler import compile_action_envelope
from modules.agent.context import AgentPipelineResult, AgentRequestContext
from modules.agent.pipeline import AgentPipeline
from socket_server import DesktopPetSocketServer


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


@pytest.mark.asyncio
async def test_finalize_result_exposes_only_retrieved_memory_provenance() -> None:
    memory_sources = [{
        "id": "memory-1",
        "text": "Prefers concise replies",
        "layer": "profile",
        "source": "conversation",
        "score": 0.91,
    }]
    result = AgentPipelineResult(
        reply="Short answer",
        action_envelope=compile_action_envelope(
            reply="Short answer",
            pet_control=None,
            request_id="req-memory",
        ),
    )
    ctx = AgentRequestContext(
        sid="sid-memory",
        session_id="session-memory",
        messages=[],
        request_id="req-memory",
        extra={"memory_sources": memory_sources},
    )

    finalized = await AgentPipeline().finalize_result(ctx, result)

    assert finalized.action_envelope is not None
    memory_trace = next(
        action for action in finalized.action_envelope["actions"]
        if action["type"] == "memory_trace"
    )
    assert memory_trace["payload"] == memory_sources
    assert all("reasoning" not in source for source in memory_trace["payload"])


def test_persisted_agent_metadata_excludes_tool_arguments_and_content() -> None:
    tool_steps, memory_sources = DesktopPetSocketServer._visible_message_metadata({
        "actions": [
            {
                "type": "tool_trace",
                "payload": [{
                    "step_results": [{
                        "step_id": "step-1",
                        "title": "Read notes",
                        "status": "completed",
                        "tool": "read_file",
                        "args": {"path": "C:/private.txt"},
                        "content": "private content",
                    }],
                }],
            },
            {
                "type": "memory_trace",
                "payload": [{
                    "id": "memory-1",
                    "text": "Prefers concise replies",
                    "layer": "profile",
                    "source": "conversation",
                }],
            },
        ],
    })

    assert tool_steps == [{
        "id": "step-1",
        "title": "Read notes",
        "status": "completed",
        "tool": "read_file",
    }]
    assert memory_sources == [{
        "id": "memory-1",
        "text": "Prefers concise replies",
        "layer": "profile",
        "source": "conversation",
    }]
