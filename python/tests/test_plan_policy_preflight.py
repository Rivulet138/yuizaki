from __future__ import annotations

from typing import Any

import pytest

from modules.agent.context import AgentRequestContext
from modules.agent.planner import ToolStep
from modules.agent.policy_engine import PolicyEngine
from modules.agent.step_executor import StepExecutor
from modules.agent.tool_executor import ToolExecutor
from modules.agent.tool_registry import ToolDefinition, ToolRegistry
from modules.agent.tool_result import ToolResultEnvelope


def _runtime(tmp_path: Any, effects: list[str]) -> tuple[AgentRequestContext, PolicyEngine]:
    registry = ToolRegistry()

    def handler(name: str):
        def execute(_arguments: dict[str, Any]) -> ToolResultEnvelope:
            effects.append(name)
            return ToolResultEnvelope(True, "ok", "builtin", name)

        return execute

    for name in ("safe.effect", "blocked.effect"):
        registry.register(
            ToolDefinition(
                name=name,
                description=name,
                source="builtin",
                parameters={"type": "object", "additionalProperties": False},
                handler=handler(name),
            )
        )
    policy = PolicyEngine(store_file=tmp_path / "permissions.json")
    executor = ToolExecutor(registry, policy)
    return (
        AgentRequestContext(
            sid="sid",
            session_id="session",
            workspace_id="workspace",
            request_id="request",
            turn_id="turn",
            generation_id="generation",
            messages=[],
            permission_scope="test",
            tool_registry=registry,
            tool_executor=executor,
        ),
        policy,
    )


@pytest.mark.asyncio
async def test_later_policy_deny_rejects_whole_plan_before_any_effect(tmp_path: Any) -> None:
    effects: list[str] = []
    ctx, policy = _runtime(tmp_path, effects)
    policy._remembered["blocked.effect::test"] = False
    steps = [
        ToolStep(id="safe", title="safe", tool_name="safe.effect", arguments={}),
        ToolStep(
            id="blocked",
            title="blocked",
            tool_name="blocked.effect",
            arguments={},
            depends_on=["safe"],
        ),
    ]

    result = await StepExecutor().execute_plan(ctx, steps)

    assert result["error"].startswith("invalid_plan:policy denied tool step blocked")
    assert effects == []
    assert policy.get_audit_log() == []
    assert policy._permission_metadata == {}


@pytest.mark.asyncio
async def test_confirmation_step_cannot_follow_an_effectful_step(tmp_path: Any) -> None:
    effects: list[str] = []
    ctx, policy = _runtime(tmp_path, effects)
    definition = ctx.tool_registry.get("blocked.effect")
    assert definition is not None
    definition.require_confirm = True
    definition.risk_level = "high"
    steps = [
        ToolStep(id="safe", title="safe", tool_name="safe.effect", arguments={}),
        ToolStep(
            id="confirm",
            title="confirm",
            tool_name="blocked.effect",
            arguments={},
            depends_on=["safe"],
        ),
    ]

    result = await StepExecutor().execute_plan(ctx, steps)

    assert result["error"].startswith(
        "invalid_plan:tool step confirm requires confirmation before prior effects"
    )
    assert effects == []
    assert policy.get_audit_log() == []
    assert policy._permission_metadata == {}


def test_policy_preview_is_read_only(tmp_path: Any) -> None:
    effects: list[str] = []
    ctx, policy = _runtime(tmp_path, effects)
    executor = ctx.tool_executor
    assert executor is not None

    decision = executor.preview_policy("safe.effect", {}, ctx=ctx)

    assert decision.allowed is True
    assert policy.get_audit_log() == []
    assert policy._permission_metadata == {}
    assert effects == []


@pytest.mark.asyncio
async def test_missing_policy_preview_fails_closed_before_executor_call() -> None:
    calls: list[str] = []

    class UnsafeExecutor:
        def __init__(self) -> None:
            self.registry = ToolRegistry()
            self.registry.register(
                ToolDefinition(
                    name="danger.effect",
                    description="danger",
                    source="builtin",
                    parameters={"type": "object", "additionalProperties": False},
                    handler=lambda _arguments: ToolResultEnvelope(
                        True, "ok", "builtin", "danger.effect"
                    ),
                    require_confirm=True,
                    risk_level="high",
                )
            )

        async def execute(self, tool_name: str, _args: dict[str, Any], **_kwargs: Any):
            calls.append(tool_name)
            return ToolResultEnvelope(True, "ok", "builtin", tool_name)

    executor = UnsafeExecutor()
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        workspace_id="workspace",
        request_id="request",
        turn_id="turn",
        generation_id="generation",
        messages=[],
        tool_registry=executor.registry,
        tool_executor=executor,  # type: ignore[arg-type]
    )

    result = await StepExecutor().execute_plan(
        ctx,
        [ToolStep(id="danger", title="danger", tool_name="danger.effect", arguments={})],
    )

    assert result["error"] == (
        "invalid_plan:tool executor does not provide side-effect-free policy preview"
    )
    assert calls == []
