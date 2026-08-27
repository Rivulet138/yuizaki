"""Intent, routing and plan construction stage for AgentPipeline."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from .context import AgentRequestContext, get_runtime_bindings
from .interpret import InterpretResult, interpret_user_text
from .models import PlannerStepRecord, PlannerTrace
from .pipeline_contracts import force_agent_tool_loop, planner_condition_record
from .planner import Planner, PlanResult
from .prompt_assembly import PromptBlock
from .route_policy import resolve_route_from_intent
from .visual_intent import VisualContextDecision, classify_visual_context_request

RuntimeLoopAppender = Callable[..., None]


def apply_visual_context_decision(
    ctx: AgentRequestContext,
    user_text: str,
) -> VisualContextDecision:
    existing = ctx.extra.get("visual_context_decision")
    visual_decision = (
        existing
        if isinstance(existing, VisualContextDecision)
        else classify_visual_context_request(user_text)
    )
    ctx.extra["visual_context_decision"] = visual_decision
    ctx.extra["visual_context_requested"] = visual_decision.requested
    ctx.extra["visual_context_confidence"] = visual_decision.confidence
    ctx.extra["visual_context_reason"] = visual_decision.reason
    ctx.extra["visual_confirmation_required"] = visual_decision.confirmation_required
    if visual_decision.confirmation_required:
        prompt_blocks = [
            block
            for block in (ctx.extra.get("additional_prompt_blocks") or [])
            if isinstance(block, PromptBlock)
        ]
        if not any(block.block_id == "visual_confirmation_required" for block in prompt_blocks):
            prompt_blocks.append(PromptBlock(
                block_id="visual_confirmation_required",
                source="agent_pipeline",
                trust="trusted",
                authority="policy",
                order=210,
                content=(
                    "The user's wording may refer to visual context, but it does not explicitly authorize "
                    "screen or window capture. Do not claim to see the desktop. Ask the user to explicitly "
                    "confirm that Yuizaki should inspect the screen, window, or screenshot."
                ),
            ))
        ctx.extra["additional_prompt_blocks"] = prompt_blocks
    return visual_decision


class PlanningStage:
    """Build the interpreted route and executable plan after context enrichment."""

    def run(
        self,
        ctx: AgentRequestContext,
        *,
        user_text: str,
        planner: Planner,
        append_runtime_loop: RuntimeLoopAppender,
    ) -> PlanResult:
        visual_decision = apply_visual_context_decision(ctx, user_text)

        existing_interpretation = ctx.extra.get("interpret_result")
        interpret_result = (
            existing_interpretation
            if isinstance(existing_interpretation, InterpretResult)
            else interpret_user_text(user_text)
        )
        ctx.extra["interpret_result"] = interpret_result
        bindings = get_runtime_bindings(ctx)
        relationship_summary = bindings.relationship_summary or {}
        relationship_stage = str(relationship_summary.get("relationship_stage") or "warming")
        autonomy_mode = getattr(ctx, "autonomy_mode", "companion")
        recent_signal_kinds = [
            str(item.get("kind") or "")
            for item in (ctx.extra.get("recent_signal_docs") or [])
            if isinstance(item, dict)
        ]
        has_workspace_tool_preset = bool(ctx.extra.get("workspace_tool_preset"))
        top_route = resolve_route_from_intent(
            interpret_result,
            relationship_stage,
            autonomy_mode,
            recent_signal_kinds=recent_signal_kinds,
            has_workspace_tool_preset=has_workspace_tool_preset,
        )
        ctx.extra["top_route"] = top_route
        plan = planner.plan(user_text, interpret_result=interpret_result)
        force_agent_tool_loop(ctx, plan)
        append_runtime_loop(
            ctx,
            stage="interpret",
            summary=(
                f"Intent={interpret_result.intent}, urgency={interpret_result.urgency}, "
                f"route={top_route.owner_agent_role}"
            ),
            agent_id=top_route.owner_agent_id,
            agent_role=top_route.owner_agent_role,
            data={
                "goal": plan.goal,
                "mode": plan.mode,
                "step_count": len(plan.steps),
                "intent": interpret_result.intent,
                "urgency": interpret_result.urgency,
                "emotional_signal": interpret_result.emotional_signal,
                "tool_hint": interpret_result.tool_hint,
                "web_search_enabled": ctx.web_search_enabled is True,
                "force_tool_loop": ctx.extra.get("force_tool_loop") is True,
                "autonomy_mode": autonomy_mode,
                "relationship_stage": relationship_stage,
                "top_route_reason": top_route.route_reason,
                "has_workspace_tool_preset": has_workspace_tool_preset,
                "visual_context_requested": visual_decision.requested,
                "visual_context_confidence": visual_decision.confidence,
                "visual_context_reason": visual_decision.reason,
                "visual_confirmation_required": visual_decision.confirmation_required,
            },
        )
        self._append_planner_trace(ctx, plan)
        return plan

    @staticmethod
    def _append_planner_trace(ctx: AgentRequestContext, plan: PlanResult) -> None:
        if ctx.trace_store is None:
            return
        trace = PlannerTrace(
            timestamp=datetime.now(UTC).isoformat(),
            session_id=ctx.session_id,
            goal=plan.goal,
            mode=plan.mode,
            steps=[
                PlannerStepRecord(
                    id=step.id,
                    title=step.title,
                    kind=step.kind,
                    description=step.description,
                    depends_on=list(step.depends_on),
                    condition=planner_condition_record(step.condition),
                )
                for step in plan.steps
            ],
            request_id=ctx.request_id,
        )
        ctx.trace_store.append("planner", trace.to_dict())


__all__ = ["PlanningStage", "apply_visual_context_decision"]
