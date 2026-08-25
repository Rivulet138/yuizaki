from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.agent.context import AgentPipelineResult, AgentRequestContext
from modules.agent.failure_recovery import StepFailure
from modules.agent.pipeline import AgentPipeline
from modules.agent.planner import PlanResult, ToolStep
from modules.agent.step_executor import StepExecutor
from modules.agent.tool_result import ToolResultEnvelope
from modules.agent.turn_service import SemanticTurnRequest, TurnPorts, TurnService
from modules.agent.turn_store import TurnCommitStore
from modules.core.state import GenerationManager
from routes.ai_api import create_ai_router
from socket_server import DesktopPetSocketServer


class _Definition:
    parameters: ClassVar[dict[str, object]] = {
        "type": "object",
        "additionalProperties": True,
    }
    risk_level = "safe"
    require_confirm = False


class _Registry:
    def get(self, _name: str) -> _Definition:
        return _Definition()


class _FailingToolExecutor:
    registry = _Registry()

    def preview_policy(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(allowed=True, require_confirm=False, reason="test_safe")

    async def execute(self, name: str, _args: dict[str, Any], **_kwargs: object) -> ToolResultEnvelope:
        return ToolResultEnvelope(
            success=False,
            content="",
            source="builtin",
            tool_name=name,
            error="temporary failure",
            outcome="known_failure",
            retryable=True,
        )


class _UnknownToolExecutor(_FailingToolExecutor):
    async def execute(self, name: str, _args: dict[str, Any], **_kwargs: object) -> ToolResultEnvelope:
        return ToolResultEnvelope(
            success=False,
            content="",
            source="builtin",
            tool_name=name,
            error="effect cannot be verified",
            outcome="unknown_effect",
            retryable=False,
        )


class _SelectiveToolExecutor(_FailingToolExecutor):
    async def execute(self, name: str, args: dict[str, Any], **kwargs: object) -> ToolResultEnvelope:
        if name == "demo.done":
            return ToolResultEnvelope(
                success=True,
                content="done",
                source="builtin",
                tool_name=name,
                data={"args": args},
            )
        return await super().execute(name, args, **kwargs)


class _ChainedRecoveryToolExecutor(_SelectiveToolExecutor):
    def __init__(self) -> None:
        self.calls: dict[str, int] = {}

    async def execute(self, name: str, args: dict[str, Any], **kwargs: object) -> ToolResultEnvelope:
        self.calls[name] = self.calls.get(name, 0) + 1
        if name == "demo.flaky" and self.calls[name] > 1:
            return ToolResultEnvelope(
                success=True,
                content="recovered",
                source="builtin",
                tool_name=name,
                data={"args": args},
            )
        return await super().execute(name, args, **kwargs)


@pytest.mark.asyncio
async def test_step_failure_exposes_safe_recovery_descriptor_beside_private_token() -> None:
    executor = StepExecutor()
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        workspace_id="workspace",
        request_id="turn",
        messages=[],
        tool_executor=_FailingToolExecutor(),
    )

    result = await executor.execute_plan(
        ctx,
        [ToolStep(id="failed", title="Failed", tool_name="demo.fail")],
    )

    assert result["resume_token"]
    assert result["recovery"] == {
        "available": True,
        "action": "resume_failed_step",
        "failed_step_id": "failed",
        "retryable": True,
        "confirmation_required": False,
        "scope": "turn",
        "single_use": True,
        "ttl_seconds": 900,
        "handle": result["recovery"]["handle"],
    }
    assert result["recovery"]["handle"].startswith("rh_")
    assert "resume_token" not in json.dumps(result["recovery"])


@pytest.mark.asyncio
async def test_unknown_effect_exposes_inspection_only_and_no_resume_token() -> None:
    result = await StepExecutor().execute_plan(
        AgentRequestContext(
            sid="sid",
            session_id="session",
            messages=[],
            tool_executor=_UnknownToolExecutor(),
        ),
        [ToolStep(id="uncertain", title="Uncertain", tool_name="demo.write")],
    )

    assert "resume_token" not in result
    assert result["failure"]["retryable"] is False
    assert result["recovery"] == {
        "available": False,
        "action": "inspect_effect",
        "failed_step_id": "uncertain",
        "retryable": False,
        "confirmation_required": True,
        "reason": "unknown_effect",
    }


@pytest.mark.asyncio
async def test_pipeline_propagates_failure_and_recovery_without_resume_token() -> None:
    class FakeStepExecutor:
        max_tool_retries = 0

        async def execute_plan(self, _ctx: object, _steps: object) -> dict[str, Any]:
            return {
                "reply": "failed",
                "tool_calls": [],
                "pet_control": None,
                "step_results": [{"step_id": "failed", "kind": "tool", "status": "error"}],
                "execution_summary": {"status": "failed", "stopped_reason": "unhandled_step_error:failed"},
                "failure": {
                    "step_id": "failed",
                    "kind": "tool",
                    "message": "temporary failure",
                    "retryable": True,
                    "metadata": {"resume_token": "must-not-propagate"},
                },
                "recovery": {
                    "available": True,
                    "action": "resume_failed_step",
                    "failed_step_id": "failed",
                    "retryable": True,
                    "scope": "turn",
                    "single_use": True,
                    "ttl_seconds": 900,
                    "resume_token": "must-not-propagate",
                },
                "resume_token": "must-not-propagate",
            }

    step = ToolStep(id="failed", title="Failed", tool_name="demo.fail")
    plan = PlanResult(goal="test", steps=[step], immediate_steps=[step])
    pipeline = AgentPipeline()

    async def prepare(ctx: AgentRequestContext) -> tuple[AgentRequestContext, PlanResult]:
        return ctx, plan

    pipeline.prepare_context = prepare  # type: ignore[method-assign]
    result = await pipeline.run(AgentRequestContext(
        sid="sid",
        session_id="session",
        messages=[{"role": "user", "content": "run"}],
        step_executor=FakeStepExecutor(),  # type: ignore[arg-type]
    ))

    assert result.failure == {
        "step_id": "failed",
        "kind": "tool",
        "message": "temporary failure",
        "retryable": True,
    }
    assert result.recovery == {
        "available": True,
        "action": "resume_failed_step",
        "failed_step_id": "failed",
        "retryable": True,
        "scope": "turn",
        "single_use": True,
        "ttl_seconds": 900,
    }
    assert "resume_token" not in json.dumps(result.__dict__)


def test_failure_recovery_survive_durable_replay_and_socket_transport(tmp_path: Any) -> None:
    store = TurnCommitStore(tmp_path / "recovery.sqlite3")
    request = SemanticTurnRequest(
        session_id="session",
        workspace_id="workspace",
        request_id="request",
        turn_id="turn",
        messages=[{"role": "user", "content": "run"}],
    )
    failure = {
        "step_id": "failed",
        "kind": "tool",
        "message": "temporary failure",
        "retryable": True,
    }
    recovery = {
        "available": True,
        "action": "resume_failed_step",
        "failed_step_id": "failed",
        "retryable": True,
        "scope": "turn",
        "single_use": True,
        "ttl_seconds": 900,
    }

    async def run(_ctx: AgentRequestContext) -> AgentPipelineResult:
        return AgentPipelineResult(
            reply="failed",
            outcome="failed",
            retryable=True,
            failure=failure,
            recovery=recovery,
        )

    first_service = TurnService(TurnPorts(run=run, persist=store.persist, load=store.load))
    first = asyncio.run(first_service.execute_http(request))
    replay_service = TurnService(TurnPorts(
        run=lambda _ctx: (_ for _ in ()).throw(AssertionError("must replay")),
        persist=store.persist,
        load=store.load,
    ))
    replay = asyncio.run(replay_service.execute_http(request))
    transport = DesktopPetSocketServer._turn_commit_fields(replay)

    assert replay.replayed is True
    assert replay.result.failure == failure
    assert replay.result.recovery == recovery
    assert transport["failure"] == failure
    assert transport["recovery"] == recovery
    assert transport["retryable"] is True
    assert "resume_token" not in json.dumps(store.load(first.idempotency_key))
    assert "resume_token" not in json.dumps(transport)


def test_unknown_effect_cannot_advertise_resume_or_leak_nested_token() -> None:
    with pytest.raises(ValueError, match="cannot advertise automatic recovery"):
        AgentPipelineResult(
            reply="unknown",
            outcome="unknown_effect",
            recovery={"available": True, "action": "resume_failed_step"},
        )
    with pytest.raises(ValueError, match="must not expose a raw resume token"):
        AgentPipelineResult(
            reply="failed",
            outcome="failed",
            failure={"metadata": {"resume_token": "secret"}},
        )


def test_http_turn_commit_exposes_only_safe_failure_recovery_metadata() -> None:
    failure = {"step_id": "failed", "kind": "tool", "message": "temporary", "retryable": True}
    recovery = {
        "available": True,
        "action": "resume_failed_step",
        "failed_step_id": "failed",
        "retryable": True,
        "scope": "turn",
        "single_use": True,
        "ttl_seconds": 900,
    }

    class Pipeline:
        async def run(self, _ctx: AgentRequestContext) -> AgentPipelineResult:
            return AgentPipelineResult(
                reply="failed",
                outcome="failed",
                retryable=True,
                failure=failure,
                recovery=recovery,
            )

    pipeline = Pipeline()
    runtime = SimpleNamespace(
        agent_pipeline=pipeline,
        turn_service=TurnService.from_pipeline(pipeline),
        tool_registry=None,
        tool_executor=None,
        step_executor=None,
        scheduler=None,
        trace_store=None,
        plugin_manager=None,
    )
    app = FastAPI()
    app.include_router(create_ai_router(
        get_config=lambda: SimpleNamespace(llm=SimpleNamespace(model="model")),
        get_generation_mgr=GenerationManager,
        get_llm_client=lambda: object(),
        get_svc_client=lambda: None,
        get_agent_runtime=lambda: runtime,
        get_db_repo=lambda: None,
        get_relationship_writer=lambda: None,
        get_relationship_history=lambda: [],
        get_relationship_summary=lambda: {},
        logger=SimpleNamespace(error=lambda *_args, **_kwargs: None),
    ))

    response = TestClient(app).post("/v1/chat/completions", json={
        "model": "model",
        "messages": [{"role": "user", "content": "run"}],
        "session_id": "session",
        "request_id": "request",
    })

    assert response.status_code == 200
    commit = response.json()["turn_commit"]
    assert commit["failure"] == failure
    assert commit["recovery"] == recovery
    assert commit["retryable"] is True
    assert "resume_token" not in response.text


@pytest.mark.asyncio
async def test_opaque_recovery_handle_is_scoped_single_use_and_does_not_return_raw_token() -> None:
    executor = StepExecutor()
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        workspace_id="workspace",
        request_id="request",
        turn_id="turn:request",
        messages=[],
        tool_executor=_FailingToolExecutor(),
    )
    failed = await executor.execute_plan(ctx, [ToolStep(id="failed", title="Failed", tool_name="demo.fail")])
    handle = str(failed["recovery"]["handle"])
    wrong_scope = await executor.resume_recovery_handle(
        handle,
        workspace_id="other-workspace",
        session_id="session",
        turn_id="turn:request",
        failed_step_id="failed",
    )
    assert wrong_scope == {"ok": False, "error": "invalid_or_expired_recovery_handle"}
    resumed = await executor.resume_recovery_handle(
        handle,
        workspace_id="workspace",
        session_id="session",
        turn_id="turn:request",
        failed_step_id="failed",
    )
    assert resumed["ok"] is True, resumed
    assert "resume_token" not in json.dumps(resumed)
    replay = await executor.resume_recovery_handle(
        handle,
        workspace_id="workspace",
        session_id="session",
        turn_id="turn:request",
        failed_step_id="failed",
    )
    assert replay == {"ok": False, "error": "invalid_or_expired_recovery_handle"}


@pytest.mark.asyncio
async def test_chained_recovery_handle_preserves_full_dependency_authority() -> None:
    executor = StepExecutor()
    tool_executor = _ChainedRecoveryToolExecutor()
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        workspace_id="workspace",
        request_id="request",
        turn_id="turn:request",
        messages=[],
        tool_executor=tool_executor,
    )
    plan = [
        ToolStep(id="done", title="Done", tool_name="demo.done"),
        ToolStep(
            id="failed",
            title="Failed",
            tool_name="demo.flaky",
            depends_on=["done"],
        ),
        ToolStep(
            id="downstream",
            title="Downstream",
            tool_name="demo.fail",
            depends_on=["failed"],
        ),
    ]
    first = await executor.execute_plan(ctx, plan)
    assert first["failure"]["completed_steps"] == ["done"]
    first_handle = str(first["recovery"]["handle"])
    resumed = await executor.resume_recovery_handle(
        first_handle,
        workspace_id="workspace",
        session_id="session",
        turn_id="turn:request",
        failed_step_id="failed",
    )
    assert resumed["ok"] is True, resumed
    assert resumed["failure"]["step_id"] == "downstream"
    assert resumed["failure"]["completed_steps"] == ["done", "failed"]
    second_handle = str(resumed["recovery"]["handle"])
    assert second_handle.startswith("rh_")
    assert list(executor._recovery_handles) == [second_handle]
    next_record = executor._recovery_handles[second_handle]
    assert [step.id for step in next_record.steps] == ["done", "failed", "downstream"]
    second = await executor.resume_recovery_handle(
        second_handle,
        workspace_id="workspace",
        session_id="session",
        turn_id="turn:request",
        failed_step_id="downstream",
    )
    assert second["ok"] is True, second
    assert second["failure"]["step_id"] == "downstream"
    assert second["failure"]["completed_steps"] == ["done", "failed"]
    assert tool_executor.calls == {"demo.done": 1, "demo.flaky": 2, "demo.fail": 2}
    assert "resume_token" not in json.dumps(second)


@pytest.mark.asyncio
async def test_missing_retry_closure_authority_fails_closed() -> None:
    class MissingClosureExecutor(StepExecutor):
        async def resume_immediate_steps(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            result = await super().resume_immediate_steps(*args, **kwargs)
            token = result.get("resume_token")
            if isinstance(token, str):
                self._resume_steps.pop(token, None)
            return result

    executor = MissingClosureExecutor()
    ctx = AgentRequestContext(
        sid="sid", session_id="session", workspace_id="workspace",
        request_id="request", turn_id="turn:request", messages=[],
        tool_executor=_FailingToolExecutor(),
    )
    failed = await executor.execute_plan(
        ctx, [ToolStep(id="failed", title="Failed", tool_name="demo.fail")]
    )
    result = await executor.resume_recovery_handle(
        str(failed["recovery"]["handle"]),
        workspace_id="workspace", session_id="session",
        turn_id="turn:request", failed_step_id="failed",
    )

    assert result == {
        "ok": False,
        "error": "recovery_state_missing",
        "recovery": {
            "available": False,
            "action": "resume_failed_step",
            "failed_step_id": "failed",
            "retryable": False,
            "reason": "recovery_state_missing",
        },
    }
    assert "resume_token" not in json.dumps(result)


@pytest.mark.asyncio
async def test_missing_retry_capability_authority_fails_closed() -> None:
    class MissingCapabilityExecutor(StepExecutor):
        async def resume_immediate_steps(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            result = await super().resume_immediate_steps(*args, **kwargs)
            token = result.get("resume_token")
            if isinstance(token, str):
                self._resume_capabilities.pop(token, None)
            return result

    executor = MissingCapabilityExecutor()
    ctx = AgentRequestContext(
        sid="sid", session_id="session", workspace_id="workspace",
        request_id="request", turn_id="turn:request", messages=[],
        tool_executor=_FailingToolExecutor(),
    )
    failed = await executor.execute_plan(
        ctx, [ToolStep(id="failed", title="Failed", tool_name="demo.fail")]
    )
    result = await executor.resume_recovery_handle(
        str(failed["recovery"]["handle"]),
        workspace_id="workspace", session_id="session",
        turn_id="turn:request", failed_step_id="failed",
    )

    assert result["ok"] is False
    assert result["error"] == "recovery_state_missing"
    assert result["recovery"]["available"] is False
    assert "resume_token" not in json.dumps(result)


def test_recovery_authority_cache_is_bounded() -> None:
    executor = StepExecutor()
    executor._MAX_RECOVERY_ENTRIES = 2
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        workspace_id="workspace",
        request_id="request",
        turn_id="turn:request",
        messages=[],
    )
    step = ToolStep(id="failed", title="Failed", tool_name="demo.fail")
    failure = StepFailure(step_id="failed", kind="tool", message="temporary")
    for _ in range(6):
        token = executor.create_resume_token(ctx, [step], failure)
        executor._resume_capabilities[token] = object()  # type: ignore[assignment]
        executor._register_recovery_handle(ctx, [step], failure, token, ttl_seconds=900)
        executor._prune_recovery_state()

    assert len(executor._resume_steps) <= 2
    assert len(executor._resume_capabilities) <= 2
    assert len(executor._recovery_handles) <= 2


def test_recovery_endpoint_accepts_only_opaque_handle() -> None:
    runtime = SimpleNamespace(step_executor=StepExecutor())
    app = FastAPI()
    app.include_router(create_ai_router(
        get_config=lambda: SimpleNamespace(llm=SimpleNamespace(model="model")),
        get_generation_mgr=GenerationManager,
        get_llm_client=lambda: object(),
        get_svc_client=lambda: None,
        get_agent_runtime=lambda: runtime,
        get_db_repo=lambda: None,
        get_relationship_writer=lambda: None,
        get_relationship_history=lambda: [],
        get_relationship_summary=lambda: {},
        logger=SimpleNamespace(error=lambda *_args, **_kwargs: None),
        get_active_workspace_id=lambda: "workspace",
    ))
    response = TestClient(app).post("/api/agent/recovery/resume", json={
        "recovery_handle": "rh_missing_handle",
        "workspace_id": "workspace",
        "session_id": "session",
        "turn_id": "turn:request",
        "failed_step_id": "failed",
    })
    assert response.status_code == 409
    assert "resume_token" not in response.text
