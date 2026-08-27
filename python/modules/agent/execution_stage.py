"""Plan preparation and non-streaming execution stage for AgentPipeline."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from ..core.state import Generation
from .action_compiler import compile_action_envelope
from .context import AgentPipelineResult, AgentRequestContext
from .failure_recovery import (
    ProviderRuntimeFailure,
    classify_provider_runtime_exception,
)
from .pipeline_contracts import (
    coerce_budget_record,
    coerce_execution_summary,
    coerce_failure_record,
    coerce_pet_control,
    coerce_recovery_record,
    coerce_step_results,
    coerce_tool_calls,
    default_consumed_usage,
    default_loop_budget,
    execution_trace_payload,
    requires_structured_immediate_execution,
    terminal_contract,
)
from .planner import PlanResult, PlanStep, PlanStepUnion, PlanValidationError
from .tool_loop import run_streaming_tool_loop

RuntimeLoopAppender = Callable[..., None]


@dataclass(frozen=True)
class StreamingStageResult:
    result: AgentPipelineResult
    reply_emitted: bool = False
    persist_history: bool = False
    terminal_metadata: dict[str, Any] | None = None


class _DeferredHistoryManager:
    """Delegate generation services while deferring assistant history until projection."""

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def append_history(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _DiscardStreamAdapter:
    """Satisfy the LLM streaming port when the caller only needs the result."""

    async def send_json(self, _payload: dict[str, Any]) -> None:
        return None


class _FinalizationStreamAdapter:
    """Forward deltas and errors while reserving final actions for ProjectionStage."""

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self.reply_emitted = False

    async def send_json(self, payload: dict[str, Any]) -> None:
        event_type = str(payload.get("type") or "")
        if event_type in {"done", "pet_control"}:
            return
        if event_type == "token":
            self.reply_emitted = True
        await self._delegate.send_json(payload)


class ExecutionStage:
    """Apply autonomy rules and execute a prepared plan."""

    @staticmethod
    def prepare_plan(ctx: AgentRequestContext, plan: PlanResult) -> PlanResult:
        autonomy_mode = getattr(ctx, "autonomy_mode", "companion")
        if autonomy_mode == "assistant" and any(step.kind == "schedule" for step in plan.steps):
            plan.steps = [step for step in plan.steps if step.kind != "schedule"]
            if any(step.kind in {"agent", "tool", "join"} for step in plan.steps):
                plan.mode = "immediate"
        if autonomy_mode == "reflector" and any(step.kind == "tool" for step in plan.steps):
            plan.outcome = "refused"
            plan.refusal_reason = "reflector_mode_cannot_execute_tools"

        plan.scheduled_steps = [step for step in plan.steps if step.kind == "schedule"]
        plan.immediate_steps = [
            step for step in plan.steps if step.kind in {"agent", "tool", "join"}
        ]
        if (
            plan.outcome == "execute"
            and ctx.step_executor is not None
            and any(isinstance(step, PlanStep) for step in plan.steps)
        ):
            legacy_steps = cast(list[PlanStep], cast(object, plan.steps))
            adapted_steps = ctx.step_executor.adapt_legacy_plan(legacy_steps)
            adapted_by_id = {step.id: step for step in adapted_steps}
            plan.steps = adapted_steps
            plan.immediate_steps = [adapted_by_id[step.id] for step in plan.immediate_steps]
            plan.scheduled_steps = [adapted_by_id[step.id] for step in plan.scheduled_steps]
        return plan

    async def run(
        self,
        ctx: AgentRequestContext,
        plan: PlanResult,
        *,
        append_runtime_loop: RuntimeLoopAppender,
    ) -> AgentPipelineResult:
        plan = self.prepare_plan(ctx, plan)
        if plan.outcome != "execute":
            reply = plan.clarification_question or plan.refusal_reason or "The plan cannot be executed safely."
            append_runtime_loop(
                ctx,
                stage="decide",
                status="stopped",
                summary="Planning produced a non-execution outcome.",
                data={"plan_outcome": plan.outcome, "reason": plan.refusal_reason},
            )
            return AgentPipelineResult(
                reply=reply,
                pet_control=None,
                tool_calls=[],
                action_envelope=compile_action_envelope(
                    reply=reply,
                    pet_control=None,
                    tool_calls=[{
                        "plan_outcome": plan.outcome,
                        "clarification_question": plan.clarification_question,
                        "refusal_reason": plan.refusal_reason,
                    }],
                    source="planner",
                    request_id=ctx.request_id,
                ),
            )

        if ctx.step_executor is None:
            plan.outcome = "refused"
            plan.refusal_reason = "step_executor_not_available"
            return AgentPipelineResult(
                reply=plan.refusal_reason,
                pet_control=None,
                tool_calls=[],
                action_envelope=compile_action_envelope(
                    reply=plan.refusal_reason,
                    pet_control=None,
                    tool_calls=[{"plan_outcome": plan.outcome, "refusal_reason": plan.refusal_reason}],
                    source="planner",
                    request_id=ctx.request_id,
                ),
            )

        result = await ctx.step_executor.execute_plan(ctx, plan.steps)
        return self._project_execution_result(ctx, plan, result)

    async def run_streaming(
        self,
        ctx: AgentRequestContext,
        plan: PlanResult,
        *,
        ws_adapter: Any,
        generation: Generation,
    ) -> StreamingStageResult:
        """Execute a prepared plan while preserving the streaming transport contract."""
        plan = self.prepare_plan(ctx, plan)
        if plan.outcome != "execute":
            reply = plan.clarification_question or plan.refusal_reason or "The plan cannot be executed safely."
            generation.tokens = [reply]
            return StreamingStageResult(AgentPipelineResult(
                reply=reply,
                pet_control=None,
                tool_calls=[],
                action_envelope=compile_action_envelope(
                    reply=reply,
                    pet_control=None,
                    tool_calls=[{
                        "plan_outcome": plan.outcome,
                        "refusal_reason": plan.refusal_reason,
                    }],
                    source="planner",
                    request_id=ctx.request_id,
                ),
            ), terminal_metadata={"plan_outcome": plan.outcome})

        if ctx.step_executor is None:
            return StreamingStageResult(AgentPipelineResult(
                reply="step_executor_not_available",
                pet_control=None,
                tool_calls=[],
                outcome="failed",
            ))
        try:
            validation_capability = ctx.step_executor.preflight_plan(ctx, plan.steps)
        except PlanValidationError as exc:
            reason = f"invalid_plan:{exc}"
            generation.tokens = [reason]
            return StreamingStageResult(AgentPipelineResult(
                reply=reason,
                pet_control=None,
                tool_calls=[],
                action_envelope=compile_action_envelope(
                    reply=reason,
                    pet_control=None,
                    tool_calls=[{"plan_outcome": "refused", "refusal_reason": reason}],
                    source="planner",
                    request_id=ctx.request_id,
                ),
                outcome="failed",
            ))

        sliced_step_ids = {
            step.id for step in [*plan.scheduled_steps, *plan.immediate_steps]
        }
        analysis_steps = [
            step
            for step in plan.steps
            if step.kind == "analysis" and step.id not in sliced_step_ids
        ]
        if analysis_steps:
            await ctx.step_executor.execute_analysis_steps(
                ctx,
                cast(list[PlanStepUnion], analysis_steps),
                validation_capability=validation_capability,
            )
        schedule_results: list[Any] = []
        if plan.scheduled_steps and ctx.scheduler:
            schedule_results = await ctx.step_executor.execute_schedule_steps(
                ctx,
                plan.scheduled_steps,
                validation_capability=validation_capability,
            )

        # A schedule-only request is already complete once the scheduler has
        # accepted (or rejected) its steps. Do not spend another model turn to
        # narrate it, since that can hide a successful task behind an LLM error.
        if plan.scheduled_steps and not plan.immediate_steps:
            step_results = [
                item.to_dict() if callable(getattr(item, "to_dict", None)) else dict(item)
                for item in schedule_results
            ]
            if not step_results and ctx.scheduler is None:
                step_results = [{
                    "step_id": step.id,
                    "title": step.title,
                    "kind": "schedule",
                    "status": "error",
                    "success": False,
                    "error": "scheduler_not_available",
                } for step in plan.scheduled_steps]
            created = sum(1 for item in step_results if item.get("status") == "created")
            failed = sum(1 for item in step_results if item.get("status") in {"error", "failed"})
            status = "failed" if failed else "completed"
            result = {
                "reply": "",
                "tool_calls": [],
                "step_results": step_results,
                "execution_summary": {
                    "status": status,
                    "total_steps": len(step_results),
                    "completed_steps": created,
                    "failed_steps": failed,
                    "skipped_steps": sum(1 for item in step_results if item.get("status") == "skipped"),
                    "pending_steps": [],
                },
            }
            projected = self._project_execution_result(ctx, plan, result)
            return StreamingStageResult(
                projected,
                persist_history=bool(projected.reply),
            )

        if plan.immediate_steps and (
            ctx.extra.get("force_tool_loop") is True
            or requires_structured_immediate_execution(plan.immediate_steps)
        ):
            result = await ctx.step_executor.execute_immediate_steps(
                ctx,
                plan.immediate_steps,
                validation_capability=validation_capability,
            )
            reply = str(result.get("reply") or "")
            pet_control = coerce_pet_control(result.get("pet_control"))
            tool_calls = coerce_tool_calls(result.get("tool_calls"))
            step_results = coerce_step_results(result.get("step_results"))
            execution_summary = coerce_execution_summary(result.get("execution_summary"))

            generation.tokens = [reply] if reply else []
            if pet_control:
                cast(Any, generation).pet_control = pet_control

            outcome, retryable = terminal_contract(result, step_results)
            return StreamingStageResult(AgentPipelineResult(
                reply=reply,
                pet_control=pet_control,
                tool_calls=tool_calls,
                action_envelope=compile_action_envelope(
                    reply=reply,
                    pet_control=pet_control,
                    tool_calls=tool_calls + execution_trace_payload(
                        step_results,
                        execution_summary,
                        {
                            "stop_on_failure": True,
                            "tool_retry_limit": getattr(ctx.step_executor, "max_tool_retries", 0),
                        },
                    ),
                    source="agent",
                    request_id=ctx.request_id,
                ),
                failure=coerce_failure_record(result.get("failure")),
                recovery=coerce_recovery_record(result.get("recovery")),
                outcome=outcome,
                retryable=retryable,
                configured_budget=coerce_budget_record(result.get("configured_budget")),
                consumed_usage=coerce_budget_record(result.get("consumed_usage")),
            ), persist_history=True)

        if not ctx.llm_client or not ctx.generation_mgr:
            raise RuntimeError("LLM client or generation manager not available")
        streaming_result = None
        reply_emitted = False
        if ctx.tool_registry is not None and ctx.tool_executor is not None:
            async def emit_token(content: str) -> None:
                nonlocal reply_emitted
                reply_emitted = True
                if ws_adapter is not None:
                    await ws_adapter.send_json({
                        "type": "token",
                        "session_id": generation.session_id,
                        "generation_id": generation.generation_id,
                        "content": content,
                    })

            streaming_result = await run_streaming_tool_loop(
                ctx.llm_client,
                ctx.messages,
                tool_registry=ctx.tool_registry,
                tool_executor=ctx.tool_executor,
                generation=generation,
                emit=emit_token if ws_adapter is not None else None,
                ctx=ctx,
                permission_request_cb=ctx.permission_request_cb,
                plugin_manager=ctx.plugin_manager,
                max_iterations=int(ctx.extra.get("streaming_tool_max_iterations", 3)),
                max_output_tokens=ctx.max_tokens,
                retry_budget=ctx.extra.get("retry_budget", ctx.extra.get("retry_limit", 0)),
                tool_budget=ctx.extra.get("tool_budget"),
                model=ctx.model,
                allowed_tool_names=ctx.extra.get("allowed_tool_names"),
                allowed_mcp_server_names=ctx.extra.get("allowed_mcp_server_names"),
                preferred_tool_names=ctx.extra.get("preferred_tool_names"),
                include_mcp_tools=ctx.mcp_enabled is not False,
                include_web_search_tools=bool(ctx.web_search_enabled),
            )
        if streaming_result is not None:
            reply = str(streaming_result.get("reply") or "")
            generation.tokens = [reply] if reply else []
            tool_calls = coerce_tool_calls(streaming_result.get("tool_calls"))
            outcome, retryable = terminal_contract(streaming_result)
            failure = coerce_failure_record(streaming_result.get("failure"))
            if failure is None and outcome == "failed":
                usage = streaming_result.get("consumed_usage")
                usage_payload = usage if isinstance(usage, dict) else {}
                stopped_reason = str(
                    streaming_result.get("stopped_reason")
                    or usage_payload.get("stop_reason")
                    or "streaming_tool_loop_failed"
                )
                failure = {
                    "kind": "streaming_tool_loop",
                    "message": stopped_reason,
                    "status": "failed",
                    "retryable": retryable,
                }
            result_obj = AgentPipelineResult(
                reply=reply,
                pet_control=None,
                tool_calls=tool_calls,
                action_envelope=compile_action_envelope(
                    reply=reply,
                    pet_control=None,
                    tool_calls=tool_calls,
                    source="agent",
                    request_id=ctx.request_id or f"act_{generation.generation_id}",
                ),
                outcome=outcome,
                retryable=retryable,
                failure=failure,
                recovery=coerce_recovery_record(streaming_result.get("recovery")),
                configured_budget=coerce_budget_record(streaming_result.get("configured_budget")),
                consumed_usage=coerce_budget_record(streaming_result.get("consumed_usage")),
            )
            return StreamingStageResult(
                result_obj,
                reply_emitted=reply_emitted,
                persist_history=bool(streaming_result.get("persist_history", True)),
            )

        filtered_adapter = _FinalizationStreamAdapter(
            ws_adapter if ws_adapter is not None else _DiscardStreamAdapter()
        )
        try:
            await ctx.llm_client.stream_chat(
                filtered_adapter,
                generation,
                _DeferredHistoryManager(ctx.generation_mgr),
                ctx.messages,
                max_output_tokens=ctx.max_tokens,
                pet_control_context=ctx.pet_control_context,
                model=ctx.model,
                temperature=ctx.temperature,
                top_p=ctx.top_p,
                top_k=ctx.top_k,
                min_p=ctx.min_p,
                frequency_penalty=ctx.frequency_penalty,
                presence_penalty=ctx.presence_penalty,
                repetition_penalty=ctx.repetition_penalty,
                reasoning_effort=ctx.reasoning_effort,
                thinking=ctx.thinking_mode,
            )
        except Exception as exc:
            provider_failure = classify_provider_runtime_exception(exc)
            if provider_failure is None:
                raise
            cast(Any, generation).pet_control = None
            return self._provider_failure_result(
                ctx,
                generation,
                provider_failure,
                reply_emitted=filtered_adapter.reply_emitted,
            )

        pet_control = getattr(generation, "pet_control", None)
        return StreamingStageResult(AgentPipelineResult(
            reply=generation.full_text,
            pet_control=pet_control,
            tool_calls=[],
            action_envelope=compile_action_envelope(
                reply=generation.full_text,
                pet_control=pet_control,
                tool_calls=[{
                    "mode": plan.mode,
                    "plan_steps": [step.title for step in plan.steps],
                }],
                source="agent",
                request_id=ctx.request_id or f"act_{generation.generation_id}",
            ),
            configured_budget=default_loop_budget(ctx, max_iterations=1),
            consumed_usage=default_consumed_usage(
                iterations=1,
                output_tokens=len(generation.tokens),
                stop_reason="completed",
            ),
        ), reply_emitted=bool(filtered_adapter and filtered_adapter.reply_emitted), persist_history=True)

    @staticmethod
    def _provider_failure_result(
        ctx: AgentRequestContext,
        generation: Generation,
        failure: ProviderRuntimeFailure,
        *,
        reply_emitted: bool,
    ) -> StreamingStageResult:
        if failure.reason == "provider_timeout":
            reply = "模型响应超时，请稍后重试。"
        elif failure.reason == "provider_request_rejected":
            reply = "模型请求未被服务接受，请检查模型配置。"
        else:
            reply = "模型服务暂时不可用，请检查连接后重试。"
        recovery_available = bool(failure.retryable)
        recovery_action = "retry_turn" if recovery_available else "check_provider_settings"
        generation.tokens = [reply]
        return StreamingStageResult(
            AgentPipelineResult(
                reply=reply,
                pet_control=None,
                tool_calls=[],
                failure={
                    "kind": failure.kind,
                    "message": failure.reason,
                    "status": "failed",
                    "retryable": failure.retryable,
                },
                recovery={
                    "available": recovery_available,
                    "action": recovery_action,
                    "retryable": failure.retryable,
                    "confirmation_required": False,
                    "reason": failure.reason,
                },
                outcome="failed",
                retryable=failure.retryable,
                configured_budget=default_loop_budget(ctx, max_iterations=1),
                consumed_usage=default_consumed_usage(
                    iterations=0,
                    output_tokens=0,
                    stop_reason=failure.reason,
                ),
            ),
            reply_emitted=reply_emitted,
            persist_history=False,
        )

    @staticmethod
    def _project_execution_result(
        ctx: AgentRequestContext,
        plan: PlanResult,
        result: dict[str, object],
    ) -> AgentPipelineResult:
        reply = str(result.get("reply") or "")
        pet_control = coerce_pet_control(result.get("pet_control"))
        tool_calls = coerce_tool_calls(result.get("tool_calls"))
        step_results = coerce_step_results(result.get("step_results"))
        execution_summary = coerce_execution_summary(result.get("execution_summary"))
        rollback_results = coerce_step_results(result.get("rollback_results"))
        created_tasks = [
            item
            for item in step_results
            if item.get("kind") == "schedule" and item.get("status") == "created"
        ]
        if rollback_results:
            reply = "计划任务的即时执行部分失败，已回滚已创建的调度任务。"
        elif created_tasks:
            if plan.mode == "scheduled_once":
                schedule_reply = f"已为你创建一次性任务，将在 {plan.delay_seconds} 秒后执行。"
            elif plan.mode == "scheduled_interval":
                schedule_reply = f"已为你创建循环任务，将每隔 {plan.interval_seconds} 秒执行一次。"
            else:
                schedule_reply = "已为你创建计划任务，并将继续执行即时部分。"
            reply = f"{schedule_reply}\n\n{reply}" if reply else schedule_reply
        elif not reply and result.get("error"):
            reply = str(result["error"])

        outcome, retryable = terminal_contract(result, step_results)
        return AgentPipelineResult(
            reply=reply,
            pet_control=pet_control,
            tool_calls=tool_calls,
            action_envelope=compile_action_envelope(
                reply=reply,
                pet_control=pet_control,
                tool_calls=tool_calls + execution_trace_payload(
                    step_results,
                    execution_summary,
                    {
                        "stop_on_failure": True,
                        "tool_retry_limit": getattr(ctx.step_executor, "max_tool_retries", 0),
                        "schedule_rollback_on_immediate_failure": True,
                    },
                    {
                        "scheduled_tasks": [item.get("task_id") for item in created_tasks if item.get("task_id")],
                        "mode": plan.mode,
                        "plan_steps": [step.title for step in plan.steps],
                    },
                ),
                source="planner" if created_tasks else "agent",
                request_id=ctx.request_id,
            ),
            failure=coerce_failure_record(result.get("failure")),
            recovery=coerce_recovery_record(result.get("recovery")),
            outcome=outcome,
            retryable=retryable,
            configured_budget=coerce_budget_record(result.get("configured_budget")),
            consumed_usage=coerce_budget_record(result.get("consumed_usage")),
        )


__all__ = ["ExecutionStage", "StreamingStageResult"]
