"""Final response and action projection stage for AgentPipeline."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..pet_control import filter_pet_control_payload
from .action_compiler import compile_action_envelope
from .context import AgentPipelineResult, AgentRequestContext, get_runtime_bindings
from .pipeline_contracts import coerce_tool_calls

RuntimeLoopAppender = Callable[..., None]


class ProjectionStage:
    """Apply post-LLM hooks and rebuild the user-visible action envelope."""

    async def run(
        self,
        ctx: AgentRequestContext,
        result_obj: AgentPipelineResult,
        *,
        append_runtime_loop: RuntimeLoopAppender,
    ) -> AgentPipelineResult:
        if result_obj.outcome == "unknown_effect":
            result_obj.retryable = False
        original_envelope = dict(result_obj.action_envelope or {})
        original_tool_calls = list(result_obj.tool_calls or [])
        if ctx.plugin_manager:
            result_obj = await ctx.plugin_manager.after_llm(result_obj, ctx)
            result_obj = await ctx.plugin_manager.before_dispatch(result_obj, ctx)

        # Hooks may return a fresh result object, so enforce terminal invariants
        # again after the extension boundary. Unknown real-world effects are
        # never safe to advertise as automatically retryable.
        if result_obj.outcome == "unknown_effect":
            result_obj.retryable = False

        trace_suffix = self._trace_suffix(original_envelope, original_tool_calls)
        result_obj.pet_control = filter_pet_control_payload(
            result_obj.pet_control,
            ctx.pet_control_context,
        )
        result_obj.tool_calls = coerce_tool_calls(result_obj.tool_calls)
        result_obj.action_envelope = compile_action_envelope(
            reply=str(result_obj.reply or ""),
            pet_control=result_obj.pet_control,
            tool_calls=[*result_obj.tool_calls, *trace_suffix],
            memory_sources=[
                source
                for source in (ctx.extra.get("memory_sources") or [])
                if isinstance(source, dict)
            ],
            source=str(original_envelope.get("source") or "agent"),
            request_id=str(original_envelope.get("request_id") or ctx.request_id or "") or None,
        )
        append_runtime_loop(
            ctx,
            stage="ask_act",
            summary="Prepared reply and actions for dispatch.",
            agent_id="yuizaki.companion-orchestrator",
            agent_role="orchestrator",
            data={
                "reply_length": len(result_obj.reply or ""),
                "tool_call_count": len(result_obj.tool_calls or []),
                "has_pet_control": bool(result_obj.pet_control),
                "outcome": result_obj.outcome,
                "retryable": result_obj.retryable,
                "configured_budget": dict(result_obj.configured_budget),
                "consumed_usage": dict(result_obj.consumed_usage),
            },
        )
        self._append_reflection_traces(ctx, append_runtime_loop)
        return result_obj

    @staticmethod
    def _trace_suffix(
        original_envelope: dict[str, Any],
        original_tool_calls: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        original_actions = original_envelope.get("actions")
        if not isinstance(original_actions, list):
            return []
        tool_trace = next(
            (
                action
                for action in original_actions
                if isinstance(action, dict) and action.get("type") == "tool_trace"
            ),
            None,
        )
        payload = tool_trace.get("payload") if isinstance(tool_trace, dict) else None
        if not isinstance(payload, list) or payload[:len(original_tool_calls)] != original_tool_calls:
            return []
        return [
            item
            for item in payload[len(original_tool_calls):]
            if isinstance(item, dict)
        ]

    @staticmethod
    def _append_reflection_traces(
        ctx: AgentRequestContext,
        append_runtime_loop: RuntimeLoopAppender,
    ) -> None:
        bindings = get_runtime_bindings(ctx)
        relationship_summary = bindings.relationship_summary or {}
        append_runtime_loop(
            ctx,
            stage="reflect",
            summary="Recorded execution outcome for future policy and memory adjustment.",
            agent_id="yuizaki.memory-reflector",
            agent_role="reflector",
            data={
                "relationship_stage": relationship_summary.get("relationship_stage"),
                "proactive_budget": relationship_summary.get("proactive_budget"),
            },
        )
        append_runtime_loop(
            ctx,
            stage="update_relationship",
            summary="Prepared relationship update signals from current execution.",
            agent_id="yuizaki.memory-reflector",
            agent_role="reflector",
            data={
                "relationship_history_count": len(bindings.relationship_history or []),
                "retrieved_chunk_count": len(bindings.retrieved_chunks or []),
            },
        )


__all__ = ["ProjectionStage"]
