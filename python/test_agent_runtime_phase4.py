from __future__ import annotations

import pytest
from typing import Any, cast

from modules.agent.context import AgentRequestContext
from modules.agent.interpret import interpret_user_text
from modules.agent.pipeline import AgentPipeline
from modules.agent.planner import Planner
from modules.agent.route_policy import resolve_route_from_intent
from modules.agent.step_executor import StepExecutor
from modules.agent.tool_result import ToolResultEnvelope


class TraceStore:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def append(self, category: str, payload: dict[str, Any]) -> None:
        self.events.append((category, payload))


class ToolExecutor:
    def __init__(self, *, fail_first: bool = False, fail_always: bool = False) -> None:
        self.fail_first = fail_first
        self.fail_always = fail_always
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, tool_name: str, args: dict[str, Any], **_kwargs: Any):
        self.calls.append((tool_name, args))
        if self.fail_always or (self.fail_first and len(self.calls) == 1):
            return ToolResultEnvelope(success=False, content="", source="builtin", tool_name=tool_name, error="policy_denied")
        return ToolResultEnvelope(success=True, content=f"ok:{tool_name}", source="builtin", tool_name=tool_name)


class Scheduler:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.removed: list[str] = []

    async def add_interval(self, name: str, prompt: str, interval_seconds: int, source: str):
        task_id = f"interval-{len(self.created) + 1}"
        self.created.append(task_id)
        return type("Task", (), {"id": task_id})()

    async def add_once(self, name: str, prompt: str, run_after_seconds: int, source: str):
        task_id = f"once-{len(self.created) + 1}"
        self.created.append(task_id)
        return type("Task", (), {"id": task_id})()

    async def remove_task(self, task_id: str) -> None:
        self.removed.append(task_id)


class FailingImmediateStepExecutor(StepExecutor):
    async def execute_immediate_steps(self, ctx: AgentRequestContext, steps):
        return {
            'reply': 'failed',
            'tool_calls': [],
            'pet_control': None,
            'step_results': [{'status': 'error', 'kind': 'agent', 'error': 'forced_failure'}],
        }


def test_interpret_user_text_detects_schedule_intent():
    result = interpret_user_text('每隔 5 分钟提醒我喝水')
    assert result.intent == 'schedule'
    assert result.urgency == 'deferred'


def test_resolve_route_from_intent_prefers_task_router_for_executor_mode():
    interpret_result = interpret_user_text('陪我聊聊今天做了什么')
    route = resolve_route_from_intent(interpret_result, relationship_stage='stable', autonomy_mode='executor')
    assert route.owner_agent_role == 'router'


def test_planner_uses_interpret_hint_for_tool_task():
    planner = Planner()
    interpret_result = interpret_user_text('打开 https://example.com 然后读取文件 notes.txt')
    plan = planner.plan('打开 https://example.com 然后读取文件 notes.txt', interpret_result=interpret_result)
    assert plan.immediate_steps
    assert any(step.kind == 'tool' for step in plan.immediate_steps)


def test_planner_uses_interpret_hint_for_schedule_without_explicit_delay_match():
    planner = Planner()
    interpret_result = interpret_user_text('每隔 3 分钟提醒我站起来活动')
    plan = planner.plan('每隔 3 分钟提醒我站起来活动', interpret_result=interpret_result)
    assert plan.mode == 'scheduled_interval'


def test_agent_request_context_defaults_to_companion_autonomy_mode():
    ctx = AgentRequestContext(sid='s1', session_id='s1', messages=[])
    assert ctx.autonomy_mode == 'companion'


def test_pipeline_can_be_instantiated_for_phase4_runtime_tests():
    pipeline = AgentPipeline()
    assert pipeline.planner is not None


def test_planner_builds_multi_step_tool_chain_with_owner_metadata():
    planner = Planner()
    prompt = '打开 https://example.com 然后读取文件 notes.txt'

    plan = planner.plan(prompt, interpret_result=interpret_user_text(prompt))

    assert len(plan.immediate_steps) == 3
    assert [step.kind for step in plan.immediate_steps] == ['tool', 'tool', 'agent']
    assert all(step.owner_agent_id for step in plan.immediate_steps)
    assert plan.immediate_steps[0].owner_agent_role == 'router'
    assert plan.immediate_steps[-1].owner_agent_role == 'orchestrator'


@pytest.mark.asyncio
async def test_step_executor_traces_owner_agent_through_multi_step_execution(monkeypatch):
    planner = Planner()
    prompt = '打开 https://example.com 然后读取文件 notes.txt'
    plan = planner.plan(prompt, interpret_result=interpret_user_text(prompt))
    trace_store = TraceStore()

    async def fake_tool_loop(*_args, **_kwargs):
        return {'reply': 'done', 'tool_calls': [], 'pet_control': None}

    import modules.agent.step_executor as step_executor_module
    monkeypatch.setattr(step_executor_module, 'run_tool_loop', fake_tool_loop)

    ctx = AgentRequestContext(
        sid='s1',
        session_id='s1',
        messages=[{'role': 'user', 'content': prompt}],
        tool_registry=cast(Any, object()),
        tool_executor=cast(Any, ToolExecutor()),
        trace_store=cast(Any, trace_store),
    )

    result = await StepExecutor().execute_immediate_steps(ctx, plan.immediate_steps)

    step_results = result['step_results']
    assert [item['owner_agent_role'] for item in step_results] == ['router', 'router', 'orchestrator']
    step_events = [payload for category, payload in trace_store.events if category == 'steps']
    assert [item['owner_agent_role'] for item in step_events] == ['router', 'router', 'orchestrator']


@pytest.mark.asyncio
async def test_mixed_schedule_rolls_back_created_task_when_immediate_step_fails():
    prompt = '每隔 3 分钟提醒我站起来活动，现在打开 https://example.com'
    pipeline = AgentPipeline()
    scheduler = Scheduler()
    trace_store = TraceStore()
    ctx = AgentRequestContext(
        sid='s1',
        session_id='s1',
        messages=[{'role': 'user', 'content': prompt}],
        step_executor=FailingImmediateStepExecutor(),
        tool_executor=cast(Any, ToolExecutor(fail_always=True)),
        scheduler=cast(Any, scheduler),
        trace_store=cast(Any, trace_store),
    )

    result = await pipeline.run(ctx)

    assert scheduler.created == ['interval-1']
    assert scheduler.removed == ['interval-1']
    assert '已回滚' in result.reply
    assert result.action_envelope is not None
    tool_trace = next(action for action in result.action_envelope['actions'] if action['type'] == 'tool_trace')
    step_results = tool_trace['payload'][0]['step_results']
    assert any(item.get('status') == 'rolled_back' for item in step_results)


@pytest.mark.asyncio
async def test_failed_tool_policy_denial_stops_later_tool_steps():
    planner = Planner()
    prompt = '打开 https://example.com 然后读取文件 notes.txt'
    plan = planner.plan(prompt, interpret_result=interpret_user_text(prompt))
    tool_executor = ToolExecutor(fail_always=True)
    ctx = AgentRequestContext(
        sid='s1',
        session_id='s1',
        messages=[{'role': 'user', 'content': prompt}],
        tool_executor=cast(Any, tool_executor),
        trace_store=cast(Any, TraceStore()),
    )

    tool_steps = [step for step in plan.immediate_steps if step.kind == 'tool']
    result = await StepExecutor().execute_tool_steps(ctx, tool_steps)

    assert len(tool_executor.calls) == 2
    assert len(result) == 1
    first_tool_result = result[0]
    assert first_tool_result.status == 'error'
    assert first_tool_result.error == 'policy_denied'


def test_ambiguous_empty_intent_stays_unknown_and_plans_no_steps():
    interpretation = interpret_user_text('   ')
    plan = Planner().plan('   ', interpret_result=interpretation)

    assert interpretation.intent == 'unknown'
    assert plan.steps == []
