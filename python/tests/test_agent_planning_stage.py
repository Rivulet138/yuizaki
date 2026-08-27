from __future__ import annotations

from typing import Any

from modules.agent.context import AgentRequestContext, bind_runtime_bindings
from modules.agent.planner import Planner
from modules.agent.planning_stage import PlanningStage
from modules.agent.prompt_assembly import PromptBlock


class _TraceStore:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def append(self, kind: str, payload: dict[str, Any]) -> None:
        self.events.append((kind, payload))


def test_planning_stage_projects_visual_confirmation_route_and_trace() -> None:
    trace = _TraceStore()
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        request_id="request",
        messages=[{"role": "user", "content": "你看到这个了吗"}],
        trace_store=trace,  # type: ignore[arg-type]
    )
    bind_runtime_bindings(ctx, relationship_summary={"relationship_stage": "trusted"})
    runtime_events: list[dict[str, Any]] = []

    plan = PlanningStage().run(
        ctx,
        user_text="你看到这个了吗",
        planner=Planner(),
        append_runtime_loop=lambda _ctx, **payload: runtime_events.append(payload),
    )

    assert plan.steps
    assert ctx.extra["visual_context_requested"] is False
    assert ctx.extra["visual_confirmation_required"] is True
    blocks = ctx.extra["additional_prompt_blocks"]
    assert len([block for block in blocks if isinstance(block, PromptBlock) and block.block_id == "visual_confirmation_required"]) == 1
    assert ctx.extra["interpret_result"] is not None
    assert ctx.extra["top_route"] is not None
    assert runtime_events[0]["stage"] == "interpret"
    assert runtime_events[0]["data"]["relationship_stage"] == "trusted"
    assert trace.events[0][0] == "planner"
    assert trace.events[0][1]["request_id"] == "request"


def test_planning_stage_does_not_duplicate_visual_confirmation_prompt() -> None:
    existing = PromptBlock(
        block_id="visual_confirmation_required",
        source="test",
        trust="trusted",
        authority="policy",
        order=1,
        content="existing",
    )
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        messages=[{"role": "user", "content": "look at this"}],
        extra={"additional_prompt_blocks": [existing]},
    )

    PlanningStage().run(
        ctx,
        user_text="look at this",
        planner=Planner(),
        append_runtime_loop=lambda *_args, **_kwargs: None,
    )

    assert ctx.extra["additional_prompt_blocks"] == [existing]
