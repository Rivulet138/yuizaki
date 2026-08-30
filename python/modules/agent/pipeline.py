from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, cast

from ..core.state import Generation
from ..memory.pipeline import RetrievalPipeline
from .action_compiler import compile_action_envelope
from .context import (
    AgentPipelineResult,
    AgentRequestContext,
)
from .context_prefetch import ContextPrefetchCoordinator
from .context_stage import ContextStage
from .execution_stage import ExecutionStage
from .models import (
    RuntimeLoopRecord,
)
from .pipeline_contracts import (
    execution_trace_payload as _execution_trace_payload,
)
from .planner import Planner
from .planning_stage import PlanningStage
from .projection_stage import ProjectionStage
from .visual_intent import (
    VisualContextDecision,
    classify_visual_context_request,
    visual_context_requested,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AgentPipeline",
    "VisualContextDecision",
    "classify_visual_context_request",
    "visual_context_requested",
]

class AgentPipeline:

    @staticmethod
    def _silent_result(ctx: AgentRequestContext) -> AgentPipelineResult:
        execution_summary = {
            "status": "stopped",
            "total_steps": 0,
            "completed_steps": 0,
            "failed_steps": 0,
            "skipped_steps": 0,
            "pending_steps": [],
            "stopped_reason": "silent_autonomy_mode",
        }
        return AgentPipelineResult(
            reply="",
            pet_control=None,
            tool_calls=[],
            action_envelope=compile_action_envelope(
                reply="",
                pet_control=None,
                tool_calls=_execution_trace_payload(
                    [], execution_summary, {"stop_on_failure": True, "tool_retry_limit": 0}
                ),
                source="agent",
                request_id=ctx.request_id,
            ),
        )
    def __init__(self, retrieval_pipeline: RetrievalPipeline | None = None) -> None:
        self.planner = Planner()
        self._planning_stage = PlanningStage()
        self._projection_stage = ProjectionStage()
        self._execution_stage = ExecutionStage()
        self._context_stage = ContextStage()
        self._context_prefetch = ContextPrefetchCoordinator(retrieval_pipeline)

    @property
    def retrieval_pipeline(self) -> RetrievalPipeline | None:
        return self._context_prefetch.retrieval_pipeline

    @retrieval_pipeline.setter
    def retrieval_pipeline(self, value: RetrievalPipeline | None) -> None:
        self._context_prefetch.retrieval_pipeline = value

    def bind_retrieval_pipeline(self, retrieval_pipeline: RetrievalPipeline) -> None:
        self._context_prefetch.bind_retrieval_pipeline(retrieval_pipeline)

    def schedule_speculative_context_prefetch(
        self,
        *,
        cache_key: str,
        query: str,
        workspace_id: str | None,
        tool_registry: Any,
        visual_frame_id: str | None,
    ) -> bool:
        return self._context_prefetch.schedule_speculative_context_prefetch(
            cache_key=cache_key, query=query, workspace_id=workspace_id,
            tool_registry=tool_registry, visual_frame_id=visual_frame_id,
        )

    def confirm_speculative_context_prefetch(
        self,
        *,
        cache_key: str,
        final_query: str,
        workspace_id: str | None,
        tool_registry: Any,
    ) -> bool:
        return self._context_prefetch.confirm_speculative_context_prefetch(
            cache_key=cache_key, final_query=final_query,
            workspace_id=workspace_id, tool_registry=tool_registry,
        )

    def take_speculative_context_prefetch(
        self,
        *,
        cache_key: str,
        final_query: str,
        workspace_id: str | None,
    ) -> dict[str, Any] | None:
        return self._context_prefetch.take_speculative_context_prefetch(
            cache_key=cache_key, final_query=final_query, workspace_id=workspace_id,
        )

    def cancel_speculative_context_prefetch(self, cache_key: str) -> None:
        self._context_prefetch.cancel_speculative_context_prefetch(cache_key)

    def speculative_visual_requested(self, cache_key: str) -> bool:
        return self._context_prefetch.speculative_visual_requested(cache_key)

    def schedule_retrieval_prefetch(
        self,
        *,
        cache_key: str,
        query: str,
        session_id: str | None,
        workspace_id: str | None,
        context_budget_tokens: int = 1200,
    ) -> bool:
        return self._context_prefetch.schedule_retrieval_prefetch(
            cache_key=cache_key,
            query=query,
            session_id=session_id,
            workspace_id=workspace_id,
            context_budget_tokens=context_budget_tokens,
        )

    def cancel_retrieval_prefetch(self, cache_key: str, *, clear_cache: bool = True) -> None:
        self._context_prefetch.cancel_retrieval_prefetch(cache_key, clear_cache=clear_cache)

    async def _take_retrieval_prefetch(
        self,
        *,
        cache_key: str,
        final_query: str,
        workspace_id: str | None,
        context_budget_tokens: int = 1200,
    ) -> dict[str, Any] | None:
        return await self._context_prefetch.take_retrieval_prefetch(
            cache_key=cache_key,
            final_query=final_query,
            workspace_id=workspace_id,
            context_budget_tokens=context_budget_tokens,
        )

    def _extract_user_text(self, ctx: AgentRequestContext) -> str:
        for message in reversed(ctx.messages):
            if message.get("role") == "user":
                return str(message.get("content", ""))
        return ""

    def _append_runtime_loop(
        self,
        ctx: AgentRequestContext,
        *,
        stage: str,
        summary: str,
        status: str = "ok",
        agent_id: str | None = None,
        agent_role: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        if ctx.trace_store is None:
            return
        ctx.trace_store.append(
            "runtime_loop",
            RuntimeLoopRecord(
                timestamp=datetime.now(UTC).isoformat(),
                session_id=ctx.session_id,
                request_id=ctx.request_id,
                stage=stage,
                status=status,
                summary=summary,
                agent_id=agent_id,
                agent_role=agent_role,
                data=data,
            ).to_dict(),
        )

    async def prepare_context(self, ctx: AgentRequestContext):
        ctx = await self.normalize_input(ctx)
        self._append_runtime_loop(
            ctx,
            stage="observe",
            summary="Collected input state from request/session/workspace/runtime bindings.",
            agent_id="yuizaki.companion-orchestrator",
            agent_role="orchestrator",
            data={
                "message_count": len(ctx.messages),
                "workspace_id": ctx.workspace_id,
                "session_id": ctx.session_id,
                "has_pet_control_context": bool(ctx.pet_control_context),
            },
        )
        if ctx.plugin_manager:
            ctx = await ctx.plugin_manager.before_pipeline(ctx)
        ctx = await self.enrich_context(ctx)

        if ctx.plugin_manager:
            ctx = await ctx.plugin_manager.before_llm(ctx)

        plan = self._planning_stage.run(
            ctx,
            user_text=self._extract_user_text(ctx),
            planner=self.planner,
            append_runtime_loop=self._append_runtime_loop,
        )
        return ctx, plan

    async def finalize_result(self, ctx: AgentRequestContext, result_obj: AgentPipelineResult) -> AgentPipelineResult:
        return await self._projection_stage.run(
            ctx,
            result_obj,
            append_runtime_loop=self._append_runtime_loop,
        )

    async def normalize_input(self, ctx: AgentRequestContext) -> AgentRequestContext:
        ctx.messages = list(ctx.messages or [])
        ctx.session_id = ctx.session_id or ctx.sid
        return ctx

    async def enrich_context(self, ctx: AgentRequestContext) -> AgentRequestContext:
        return await self._context_stage.run(
            ctx,
            retrieval_pipeline=self.retrieval_pipeline,
            take_retrieval_prefetch=self._take_retrieval_prefetch,
            append_runtime_loop=self._append_runtime_loop,
            logger=logger,
        )

    async def run(self, ctx: AgentRequestContext) -> AgentPipelineResult:
        if ctx.autonomy_mode == "silent":
            return self._silent_result(ctx)
        ctx, plan = await self.prepare_context(ctx)
        result_obj = await self._execution_stage.run(
            ctx,
            plan,
            append_runtime_loop=self._append_runtime_loop,
        )
        return await self.finalize_result(ctx, result_obj)

    async def run_streaming(self, ctx: AgentRequestContext, ws_adapter: Any, generation: Generation) -> AgentPipelineResult:
        if ctx.autonomy_mode == "silent":
            result_obj = self._silent_result(ctx)
            generation.tokens = []
            cast_generation = cast(Any, generation)
            cast_generation.pet_control = None
            if ws_adapter is not None:
                await ws_adapter.send_json({
                    "type": "done",
                    "session_id": generation.session_id,
                    "generation_id": generation.generation_id,
                    "content": "",
                    "outcome": result_obj.outcome,
                    "retryable": result_obj.retryable,
                    "stopped_reason": "silent_autonomy_mode",
                })
            return result_obj
        ctx, plan = await self.prepare_context(ctx)
        stage_result = await self._execution_stage.run_streaming(
            ctx,
            plan,
            ws_adapter=ws_adapter,
            generation=generation,
        )
        result_obj = await self.finalize_result(ctx, stage_result.result)
        generation.tokens = [result_obj.reply] if result_obj.reply else []
        cast_generation = cast(Any, generation)
        cast_generation.pet_control = result_obj.pet_control

        if stage_result.persist_history and result_obj.reply and ctx.generation_mgr:
            append_history = getattr(ctx.generation_mgr, "append_history", None)
            if callable(append_history):
                append_history(ctx.session_id, "assistant", result_obj.reply)

        if ws_adapter is not None:
            if result_obj.reply and not stage_result.reply_emitted:
                await ws_adapter.send_json({
                    "type": "token",
                    "session_id": generation.session_id,
                    "generation_id": generation.generation_id,
                    "content": result_obj.reply,
                })
            if result_obj.pet_control is not None:
                await ws_adapter.send_json({
                    "type": "pet_control",
                    "session_id": generation.session_id,
                    "generation_id": generation.generation_id,
                    "pet_control": result_obj.pet_control,
                })
            await ws_adapter.send_json({
                "type": "done",
                "session_id": generation.session_id,
                "generation_id": generation.generation_id,
                "content": result_obj.reply,
                "outcome": result_obj.outcome,
                "retryable": result_obj.retryable,
                **(stage_result.terminal_metadata or {}),
            })
        return result_obj
