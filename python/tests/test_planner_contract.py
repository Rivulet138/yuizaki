from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from modules.agent.planner import (
    AgentStep,
    AnalysisStep,
    JoinStep,
    Planner,
    PlanStep,
    PlanValidationError,
    PredicateNode,
    ScheduleStep,
    ToolStep,
    validate_plan,
)


def test_typed_plan_supports_five_kinds_and_legacy_action_alias() -> None:
    assert PlanStep(id="legacy", title="legacy").kind == "agent"
    steps = [
        PlanStep(id="analysis", title="analysis", kind="analysis"),
        PlanStep(id="agent", title="agent", kind="agent", depends_on=["analysis"]),
        PlanStep(id="tool", title="tool", kind="tool", depends_on=["agent"]),
        PlanStep(id="schedule", title="schedule", kind="schedule", depends_on=["tool"]),
        PlanStep(id="join", title="join", kind="join", depends_on=["schedule"]),
    ]
    validate_plan(steps)


def test_planner_emits_v2_tool_without_legacy_telemetry() -> None:
    prompt = "open https://example.com"
    step = next(step for step in Planner().plan(prompt).steps if step.kind == "tool")
    assert step.payload is None
    assert step.plan_version == 2
    assert step.compatibility_trace is None
    assert step.tool_name == "browser.open_page"
    assert step.arguments == {"url": "https://example.com"}


@pytest.mark.parametrize(
    "criteria",
    [
        {"op": "status_in", "values": ["ok"], "eval": "1 + 1"},
        PredicateNode(op="eval"),
    ],
)
def test_success_predicate_is_closed_data_only(criteria: object) -> None:
    with pytest.raises(PlanValidationError):
        validate_plan([PlanStep(id="a", title="a", kind="agent", success_criteria=criteria)])


def test_cycle_and_budget_validation_reject_before_execution() -> None:
    with pytest.raises(PlanValidationError, match="cycle"):
        validate_plan([
            PlanStep(id="a", title="a", kind="agent", depends_on=["b"]),
            PlanStep(id="b", title="b", kind="agent", depends_on=["a"]),
        ])
    with pytest.raises(PlanValidationError, match="step budget"):
        validate_plan([PlanStep(id="a", title="a", kind="agent")], max_steps=0)
    with pytest.raises(PlanValidationError, match="retry budget"):
        validate_plan([PlanStep(id="a", title="a", kind="tool", retry_budget=2)], max_retry_budget=1)


def test_typed_tool_contract_is_serializable() -> None:
    step = PlanStep(
        id="tool",
        title="tool",
        kind="tool",
        tool_name="open_app",
        arguments={"name": "calculator"},
    )
    assert step.to_dict()["tool_name"] == "open_app"
    assert step.to_dict()["arguments"] == {"name": "calculator"}


def test_planner_emits_concrete_discriminated_variants() -> None:
    plan = Planner().plan("open https://example.com")
    assert isinstance(plan.steps[0], AnalysisStep)
    assert any(isinstance(step, ToolStep) for step in plan.steps)
    assert not hasattr(plan.steps[0], "tool_name")
    assert not hasattr(plan.steps[0], "arguments")
    with pytest.raises(TypeError, match="unexpected keyword argument 'kind'"):
        ToolStep(id="bad", title="bad", kind="agent", tool_name="open_app")

    with pytest.raises(AttributeError):
        plan.steps[0].title = "mutated"  # type: ignore[misc]


def test_legacy_payload_has_versioned_compatibility_trace() -> None:
    step = PlanStep(id="legacy", title="兼容", kind="tool", payload={"prompt": "open https://example.com"})
    data = step.to_dict()
    assert data["plan_version"] == 1
    assert data["compatibility_trace"] == {
        "adapter": "legacy_prompt",
        "from_version": 1,
        "to_version": 2,
        "preserved_payload": True,
    }


@pytest.mark.parametrize(
    ("text", "outcome"),
    [
        ("删除文件", "clarification_required"),
        ("删除所有文件", "refused"),
        ("write file", "clarification_required"),
    ],
)
def test_ambiguous_or_unsafe_destructive_text_produces_no_steps(text: str, outcome: str) -> None:
    plan = Planner().plan(text)
    assert plan.outcome == outcome
    assert plan.steps == []
    assert text.encode("utf-8").decode("utf-8") == text


def test_non_destructive_writing_request_is_not_misclassified() -> None:
    plan = Planner().plan("write a short poem")
    assert plan.outcome == "execute"
    assert plan.steps


def test_typed_v2_payload_is_closed_and_v1_adapter_is_explicit() -> None:
    with pytest.raises(PlanValidationError, match="typed v2"):
        AgentStep(id="agent", title="Agent", payload={"prompt": "legacy"})

    adapted = ScheduleStep(
        id="schedule",
        title="Schedule",
        payload={"mode": "interval", "prompt": "later", "interval_seconds": 120},
        plan_version=1,
    )
    assert adapted.schedule_mode == "interval"
    assert adapted.prompt == "later"
    assert adapted.interval_seconds == 120
    assert adapted.compatibility_trace == {
        "adapter": "legacy_typed_payload",
        "from_version": 1,
        "to_version": 2,
        "preserved_payload": True,
    }


@pytest.mark.parametrize(
    ("steps", "limit_name", "limit", "message"),
    [
        ([AnalysisStep(id="a", title="A", max_input_chars=11)], "max_analysis_input_chars", 10, "analysis input"),
        ([AnalysisStep(id="a", title="A", max_output_chars=11)], "max_analysis_output_chars", 10, "analysis output"),
        ([AgentStep(id="a", title="A", max_tokens=11)], "max_agent_tokens", 10, "agent token"),
        ([AgentStep(id="a", title="A", capability_budget=11)], "max_agent_capability_budget", 10, "agent capability"),
        ([ScheduleStep(id="a", title="A", run_after_seconds=11)], "max_schedule_seconds", 10, "schedule bounds"),
        ([JoinStep(id="a", title="A", max_merged_chars=11)], "max_join_chars", 10, "join merge"),
    ],
)
def test_variant_budgets_are_aggregated(
    steps: list[object], limit_name: str, limit: int, message: str
) -> None:
    with pytest.raises(PlanValidationError, match=message):
        validate_plan(steps, **{limit_name: limit})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "step",
    [
        AnalysisStep(id="a", title="A", max_input_chars=0),
        AgentStep(id="a", title="A", max_tokens=0),
        ScheduleStep(id="a", title="A", timezone="not/a-real-timezone"),
        JoinStep(id="a", title="A", merge_policy="unknown"),  # type: ignore[arg-type]
    ],
)
def test_variant_bounds_are_closed(step: object) -> None:
    with pytest.raises(PlanValidationError):
        validate_plan([step])  # type: ignore[list-item]


@pytest.mark.parametrize("retry_budget", [True, 1.0, "1", -1])
def test_tool_retry_budget_requires_exact_non_negative_integer(
    retry_budget: object,
) -> None:
    step = ToolStep(
        id="tool",
        title="Tool",
        tool_name="browser.open_page",
        retry_budget=retry_budget,  # type: ignore[arg-type]
    )
    with pytest.raises(PlanValidationError, match="retry_budget"):
        validate_plan([step])


@pytest.mark.parametrize(
    "timeout_seconds",
    [True, "30", float("nan"), float("inf"), 0, -0.1],
)
def test_tool_timeout_requires_finite_positive_number(timeout_seconds: object) -> None:
    step = ToolStep(
        id="tool",
        title="Tool",
        tool_name="browser.open_page",
        timeout_seconds=timeout_seconds,  # type: ignore[arg-type]
    )
    with pytest.raises(PlanValidationError, match="timeout_seconds|non-finite"):
        validate_plan([step])


@pytest.mark.parametrize("idempotency_key", ["", "   ", 7, b"key"])
def test_tool_idempotency_key_requires_non_empty_string(
    idempotency_key: object,
) -> None:
    step = ToolStep(
        id="tool",
        title="Tool",
        tool_name="browser.open_page",
        idempotency_key=idempotency_key,  # type: ignore[arg-type]
    )
    with pytest.raises(PlanValidationError, match="idempotency_key|non-JSON"):
        validate_plan([step])


@pytest.mark.parametrize(
    "arguments",
    [
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": {"not", "json"}},
        {"value": b"not-json"},
        {1: "non-string-key"},
    ],
)
def test_tool_arguments_require_strict_canonical_json(arguments: object) -> None:
    step = ToolStep(
        id="tool",
        title="Tool",
        tool_name="browser.open_page",
        arguments=arguments,  # type: ignore[arg-type]
    )
    with pytest.raises(PlanValidationError, match="non-finite|non-JSON|non-string"):
        validate_plan([step])


def test_explicit_legacy_tool_adapter_normalizes_integer_strings() -> None:
    step = ToolStep(
        id="legacy",
        title="Legacy",
        payload={
            "tool_name": "browser.open_page",
            "timeout_seconds": "45",
            "retry_budget": "2",
        },
        plan_version=1,
    )
    validate_plan([step])
    assert step.timeout_seconds == 45
    assert step.retry_budget == 2


def test_planner_step_ids_are_stable_across_python_hash_seeds() -> None:
    script = (
        "from modules.agent.planner import Planner; "
        "print(','.join(step.id for step in Planner().plan('open https://example.com').steps))"
    )
    python_root = Path(__file__).resolve().parents[1]
    outputs: list[str] = []
    for seed in ("1", "999"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        outputs.append(subprocess.check_output(
            [sys.executable, "-c", script],
            cwd=python_root,
            env=env,
            text=True,
        ).strip())
    assert outputs[0] == outputs[1]


def test_chinese_write_command_preserves_exact_unicode_contract() -> None:
    plan = Planner().plan("写入文件 C:/tmp/测试.txt 内容: 你好")
    tool_steps = [step for step in plan.steps if isinstance(step, ToolStep)]
    assert len(tool_steps) == 1
    assert tool_steps[0].tool_name == "write_file"
    assert tool_steps[0].arguments == {"path": "C:/tmp/测试.txt", "content": "你好"}
