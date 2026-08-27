"""Pure plan/result contract helpers shared by AgentPipeline execution paths."""

from __future__ import annotations

from typing import Any

from .context import AgentRequestContext, TerminalTurnOutcome
from .models import StepConditionRecord
from .planner import StepCondition


def coerce_pet_control(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def coerce_tool_calls(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def coerce_step_results(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def coerce_execution_summary(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def coerce_budget_record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def coerce_failure_record(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    result = {
        key: value[key]
        for key in ("step_id", "kind", "message", "retryable", "status", "cause", "timestamp")
        if key in value
    }
    completed_steps = value.get("completed_steps")
    if isinstance(completed_steps, (list, tuple)):
        result["completed_steps"] = [
            str(item).strip()[:120]
            for item in completed_steps[:20]
            if str(item).strip()
        ]
    return result


def coerce_recovery_record(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        key: value[key]
        for key in (
            "available", "action", "failed_step_id", "retryable",
            "confirmation_required", "reason", "scope", "single_use", "ttl_seconds",
            "handle",
        )
        if key in value
    }


def terminal_contract(
    payload: dict[str, Any],
    step_results: list[dict[str, Any]] | None = None,
) -> tuple[TerminalTurnOutcome, bool]:
    statuses = {
        str(item.get("status") or item.get("outcome") or "")
        for item in (step_results or [])
    }
    if payload.get("outcome") == "unknown_effect" or "unknown_effect" in statuses:
        return "unknown_effect", False
    if payload.get("outcome") == "cancelled":
        return "cancelled", False
    if payload.get("outcome") == "failed":
        return "failed", bool(payload.get("retryable"))
    receipt = payload.get("permission_receipt")
    summary = coerce_execution_summary(payload.get("execution_summary")) or {}
    usage = payload.get("consumed_usage")
    usage_payload = usage if isinstance(usage, dict) else {}
    stopped_reason = str(
        payload.get("stopped_reason")
        or summary.get("stopped_reason")
        or usage_payload.get("stop_reason")
        or ""
    )
    if stopped_reason == "cancelled":
        return "cancelled", False
    if stopped_reason in {"tool_budget_exhausted", "max_iterations"}:
        return "failed", True
    if stopped_reason == "invalid_stream_adapter_result":
        return "failed", False
    failure = payload.get("failure")
    if receipt is not None or stopped_reason.startswith("permission_") or summary.get("status") == "failed":
        retryable = bool(failure.get("retryable")) if isinstance(failure, dict) else False
        return "failed", retryable
    return "completed", False


def default_loop_budget(ctx: AgentRequestContext, *, max_iterations: int) -> dict[str, Any]:
    retry_budget = ctx.extra.get("retry_budget", ctx.extra.get("retry_limit", 0))
    tool_budget = ctx.extra.get("tool_budget", max(1, max_iterations) * 8)
    return {
        "max_iterations": max_iterations,
        "output_tokens": ctx.max_tokens,
        "retry_budget": int(retry_budget) if isinstance(retry_budget, int) and not isinstance(retry_budget, bool) else 0,
        "tool_budget": int(tool_budget) if isinstance(tool_budget, int) and not isinstance(tool_budget, bool) else max(1, max_iterations) * 8,
    }


def default_consumed_usage(*, iterations: int, output_tokens: int, stop_reason: str) -> dict[str, Any]:
    return {
        "iterations": max(0, iterations),
        "output_tokens": max(0, output_tokens),
        "retries": 0,
        "tool_calls": 0,
        "attempts": 0,
        "stop_reason": stop_reason,
    }


def planner_condition_record(condition: StepCondition | None) -> StepConditionRecord | None:
    if condition is None:
        return None
    return StepConditionRecord(
        source_step_id=condition.source_step_id,
        mode=condition.mode,
        status_in=list(condition.status_in),
        status_not_in=list(condition.status_not_in),
        content_contains=list(condition.content_contains),
        error_contains=list(condition.error_contains),
        all_of=[record for item in condition.all_of if (record := planner_condition_record(item)) is not None],
        any_of=[record for item in condition.any_of if (record := planner_condition_record(item)) is not None],
        none_of=[record for item in condition.none_of if (record := planner_condition_record(item)) is not None],
    )


def execution_trace_payload(
    step_results: list[dict[str, Any]],
    execution_summary: dict[str, Any] | None,
    execution_policy: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not step_results and execution_summary is None and not extra:
        return []
    payload: dict[str, Any] = dict(extra or {})
    payload["step_results"] = step_results
    if execution_summary is not None:
        payload["execution_summary"] = execution_summary
    payload["execution_policy"] = execution_policy
    return [payload]


def requires_structured_immediate_execution(steps: list[Any]) -> bool:
    return any(
        getattr(step, "kind", "") in {"tool", "join"} or getattr(step, "condition", None) is not None
        for step in steps
    ) or len(steps) > 1


def force_agent_tool_loop(ctx: AgentRequestContext, plan: Any) -> None:
    if not ctx.web_search_enabled or not getattr(plan, "immediate_steps", None):
        return
    for step in plan.immediate_steps:
        if getattr(step, "kind", "") == "agent":
            ctx.extra["force_tool_loop"] = True
            return
