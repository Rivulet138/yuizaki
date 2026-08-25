from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.agent.context import AgentPipelineResult, AgentRequestContext
from modules.agent.agent_trace_store import AgentTraceStore
from modules.agent.companion_events import CompanionJobEventLog
from modules.agent.runtime import create_agent_runtime
from modules.agent.runtime_context import RuntimeContext, RuntimeContextRegistry
from modules.agent.turn_service import TurnIdentityConflictError, TurnService
from modules.agent.turn_store import TurnCommitStore
from modules.core.state import GenerationManager
from routes.ai_api import create_ai_router
from socket_events import AgentEvents, LLMEvents, PetEvents, TTSEvents
from socket_server import DesktopPetSocketServer


class _SemanticPipeline:
    def take_speculative_context_prefetch(self, **_kwargs: object) -> None:
        return None

    def cancel_retrieval_prefetch(self, _sid: str) -> None:
        return None

    async def run(self, _ctx: AgentRequestContext) -> AgentPipelineResult:
        return AgentPipelineResult(reply="semantic reply")

    async def run_streaming(
        self,
        _ctx: AgentRequestContext,
        adapter: object,
        generation: object,
    ) -> AgentPipelineResult:
        cast(Any, generation).tokens = ["semantic reply"]
        if adapter is not None:
            await cast(Any, adapter).send_json({"type": "token", "content": "semantic reply"})
            await cast(Any, adapter).send_json({"type": "done", "content": "semantic reply"})
        return AgentPipelineResult(reply="semantic reply")


class _ActionPipeline(_SemanticPipeline):
    async def run(self, _ctx: AgentRequestContext) -> AgentPipelineResult:
        return self._result()

    async def run_streaming(
        self,
        _ctx: AgentRequestContext,
        adapter: object,
        generation: object,
    ) -> AgentPipelineResult:
        cast(Any, generation).tokens = ["semantic reply"]
        return self._result()

    @staticmethod
    def _result() -> AgentPipelineResult:
        return AgentPipelineResult(
            reply="semantic reply",
            pet_control={"emotion_id": "happy"},
            action_envelope={"actions": [{"type": "test_action"}]},
            configured_budget={"output_tokens": 321, "tool_budget": 2},
            consumed_usage={"output_tokens": 7},
        )


class _StaleProactivePipeline(_ActionPipeline):
    def __init__(self, generation_mgr: GenerationManager, stale_mode: str) -> None:
        self.generation_mgr = generation_mgr
        self.stale_mode = stale_mode

    async def run(self, ctx: AgentRequestContext) -> AgentPipelineResult:
        if self.stale_mode == "replace":
            self.generation_mgr.start(ctx.session_id, generation_id="replacement-generation")
        else:
            self.generation_mgr.interrupt(ctx.session_id)
        return self._result()


class _WorkspaceSwitchPipeline(_SemanticPipeline):
    def __init__(self, active_workspace: dict[str, str]) -> None:
        self.active_workspace = active_workspace
        self.contexts: list[AgentRequestContext] = []

    async def run(self, ctx: AgentRequestContext) -> AgentPipelineResult:
        self.contexts.append(ctx)
        if len(self.contexts) == 1:
            self.active_workspace["id"] = "workspace-b"
        return AgentPipelineResult(reply=f"reply:{ctx.workspace_id}")


def _runtime(pipeline: _SemanticPipeline, service: TurnService | None) -> SimpleNamespace:
    return SimpleNamespace(
        agent_pipeline=pipeline,
        turn_service=service,
        tool_registry=None,
        tool_executor=None,
        step_executor=None,
        scheduler=None,
        trace_store=None,
        plugin_manager=None,
    )


def test_http_stream_and_nonstream_share_commit_fingerprint_and_stage() -> None:
    pipeline = _SemanticPipeline()
    service = TurnService.from_pipeline(pipeline)
    generation_mgr = GenerationManager()
    app = FastAPI()
    app.include_router(create_ai_router(
        get_config=lambda: SimpleNamespace(llm=SimpleNamespace(model="model")),
        get_generation_mgr=lambda: generation_mgr,
        get_llm_client=lambda: object(),
        get_svc_client=lambda: None,
        get_agent_runtime=lambda: _runtime(pipeline, service),
        get_db_repo=lambda: None,
        get_relationship_writer=lambda: None,
        get_relationship_history=lambda: [],
        get_relationship_summary=lambda: {},
        logger=SimpleNamespace(error=lambda *_args, **_kwargs: None),
        get_active_workspace_id=lambda: "workspace-parity",
    ))
    client = TestClient(app)
    payload = {
        "model": "model",
        "messages": [{"role": "user", "content": "same request"}],
        "workspace_id": "workspace-parity",
        "session_id": "session-parity",
        "request_id": "request-parity",
    }

    nonstream = client.post("/v1/chat/completions", json=payload)
    stream = client.post("/v1/chat/completions", json={**payload, "stream": True})

    assert nonstream.status_code == 200
    terminal = next(
        json.loads(line.removeprefix("data: "))
        for line in stream.text.splitlines()
        if line.startswith("data: ") and "turn_commit" in line
    )
    nonstream_commit = nonstream.json()["turn_commit"]
    stream_commit = terminal["turn_commit"]
    assert nonstream_commit["semantic_fingerprint"] == stream_commit["semantic_fingerprint"]
    assert nonstream_commit["turn_stage"] == stream_commit["turn_stage"] == "committed"
    assert nonstream_commit["turn_id"] == stream_commit["turn_id"] == "turn:request-parity"
    assert nonstream_commit["generation_id"] == stream_commit["generation_id"]


def test_http_stream_emits_action_before_final_stop_and_nothing_after_terminal() -> None:
    pipeline = _ActionPipeline()
    service = TurnService.from_pipeline(pipeline)
    app = FastAPI()
    app.include_router(create_ai_router(
        get_config=lambda: SimpleNamespace(llm=SimpleNamespace(model="model")),
        get_generation_mgr=GenerationManager,
        get_llm_client=lambda: object(),
        get_svc_client=lambda: None,
        get_agent_runtime=lambda: _runtime(pipeline, service),
        get_db_repo=lambda: None,
        get_relationship_writer=lambda: None,
        get_relationship_history=lambda: [],
        get_relationship_summary=lambda: {},
        logger=SimpleNamespace(error=lambda *_args, **_kwargs: None),
    ))

    response = TestClient(app).post("/v1/chat/completions", json={
        "model": "model",
        "messages": [{"role": "user", "content": "ordered terminal"}],
        "stream": True,
    })
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]

    assert response.status_code == 200
    assert len(events) == 2
    assert events[0]["action_envelope"]["actions"][0]["type"] == "test_action"
    assert events[1]["choices"][0]["finish_reason"] == "stop"
    assert events[-1] == events[1]


@pytest.mark.asyncio
async def test_proactive_socket_emits_side_effects_then_result_and_final_with_commit_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = DesktopPetSocketServer(allow_legacy_turn_pipeline=False)
    pipeline = _ActionPipeline()
    generation_mgr = GenerationManager()
    emitted: list[tuple[str, object]] = []

    server.agent_pipeline = cast(Any, pipeline)
    server.turn_service = TurnService.from_pipeline(pipeline)
    monkeypatch.setattr(server, "llm_client", object())
    monkeypatch.setattr(server, "generation_mgr", generation_mgr)
    monkeypatch.setattr(server, "tts_client", object())
    server.sessions["sid-proactive"] = {}
    server.inject_runtime_context(active_workspace_provider=lambda: "workspace-parity")

    async def _emit(event: str, data: object = None, **_: object) -> None:
        emitted.append((event, data))

    async def _run_tts(_session_id: str, _sid: str) -> None:
        emitted.append((TTSEvents.DONE, {"is_final": True}))

    monkeypatch.setattr(server.sio, "emit", _emit)
    monkeypatch.setattr(server, "_run_tts_for_generation", _run_tts)

    result = await server._dispatch_plugin_proactive_message(
        plugin_id="plugin-parity",
        message="proactive message",
        session_id="session-proactive",
        sid="sid-proactive",
    )

    assert result["ok"] is True
    assert [event for event, _ in emitted] == [
        PetEvents.CONTROL,
        TTSEvents.DONE,
        AgentEvents.RESULT,
        LLMEvents.FINAL,
    ]
    for payload in (cast(dict[str, object], emitted[-2][1]), cast(dict[str, object], emitted[-1][1])):
        assert payload["semantic_fingerprint"]
        assert payload["turn_stage"] == "committed"
        assert payload["outcome"] == "completed"
        assert payload["configured_budget"] == {"output_tokens": 321, "tool_budget": 2}
        assert payload["consumed_usage"] == {"output_tokens": 7}


@pytest.mark.asyncio
@pytest.mark.parametrize("stale_mode", ["replace", "interrupt"])
async def test_proactive_socket_discards_all_stale_post_execution_outputs(
    monkeypatch: pytest.MonkeyPatch,
    stale_mode: str,
) -> None:
    server = DesktopPetSocketServer(allow_legacy_turn_pipeline=False)
    generation_mgr = GenerationManager()
    pipeline = _StaleProactivePipeline(generation_mgr, stale_mode)
    emitted: list[str] = []
    tts_calls: list[str] = []

    server.agent_pipeline = cast(Any, pipeline)
    server.turn_service = TurnService.from_pipeline(pipeline)
    monkeypatch.setattr(server, "llm_client", object())
    monkeypatch.setattr(server, "generation_mgr", generation_mgr)
    monkeypatch.setattr(server, "tts_client", object())
    server.sessions["sid-stale"] = {}
    server.inject_runtime_context(active_workspace_provider=lambda: "workspace-parity")

    async def _emit(event: str, _data: object = None, **_: object) -> None:
        emitted.append(event)

    async def _run_tts(session_id: str, _sid: str) -> None:
        tts_calls.append(session_id)

    monkeypatch.setattr(server.sio, "emit", _emit)
    monkeypatch.setattr(server, "_run_tts_for_generation", _run_tts)

    result = await server._dispatch_plugin_proactive_message(
        plugin_id="plugin-stale",
        message="must be discarded",
        session_id="session-stale",
        sid="sid-stale",
    )

    assert result["ok"] is False
    assert result["reason"] == "generation_replaced"
    assert generation_mgr.get_history_snapshot(result["session_id"]) == []
    assert emitted == []
    assert tts_calls == []


@pytest.mark.asyncio
async def test_proactive_socket_pins_workspace_through_delayed_outbox_replay(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YUIZAKI_DATA_DIR", str(tmp_path / "runtime-data"))
    active_workspace = {"id": "workspace-a"}
    saved_chats: list[dict[str, object]] = []
    relationship_events: list[tuple[str, dict[str, object]]] = []

    class Repository:
        def list_workspaces(self) -> list[dict[str, str]]:
            return [{"id": "workspace-a"}, {"id": "workspace-b"}]

        def save_message_pair(
            self,
            session_id: str,
            user_text: str,
            assistant_text: str,
            **kwargs: object,
        ) -> tuple[dict[str, int], dict[str, int]]:
            saved_chats.append({
                "session_id": session_id,
                "user_text": user_text,
                "assistant_text": assistant_text,
                **kwargs,
            })
            return {"id": 1}, {"id": 2}

    class RelationshipWriter:
        def __call__(self, event: dict[str, object]) -> None:
            relationship_events.append(("unscoped", event))

        def for_workspace(self, workspace_id: str):
            def _write(event: dict[str, object]) -> None:
                relationship_events.append((workspace_id, event))

            return _write

    server = DesktopPetSocketServer(allow_legacy_turn_pipeline=False)
    pipeline = _WorkspaceSwitchPipeline(active_workspace)
    generation_mgr = GenerationManager()
    emitted: list[tuple[str, object]] = []

    server.agent_pipeline = cast(Any, pipeline)
    server.turn_service.ports = replace(
        server.turn_service.ports,
        run=pipeline.run,
        run_streaming=pipeline.run_streaming,
        dispatch=lambda _commit: None,
    )
    monkeypatch.setattr(server, "llm_client", object())
    monkeypatch.setattr(server, "generation_mgr", generation_mgr)
    server.sessions["sid-workspace"] = {}
    server.inject_runtime_context(
        db_repo=cast(Any, Repository()),
        relationship_event_writer=cast(Any, RelationshipWriter()),
        active_workspace_provider=lambda: active_workspace["id"],
    )

    async def _emit(event: str, data: object = None, **_: object) -> None:
        emitted.append((event, data))

    monkeypatch.setattr(server.sio, "emit", _emit)

    first = await server._dispatch_plugin_proactive_message(
        plugin_id="plugin-shared",
        message="I prefer workspace A",
        session_id="shared/custom:session",
        sid="sid-workspace",
    )

    assert active_workspace["id"] == "workspace-b"
    assert first["session_id"].startswith("plugin:")
    assert first["caller_session_id"] == "shared/custom:session"
    first_ctx = pipeline.contexts[0]
    assert first_ctx.workspace_id == "workspace-a"
    assert first_ctx.extra["runtime_bindings"]["active_workspace_id"] == "workspace-a"
    expected_fingerprint = TurnService.semantic_fingerprint(first_ctx)
    result_payload = cast(
        dict[str, object],
        next(data for event, data in emitted if event == AgentEvents.RESULT),
    )
    assert result_payload["semantic_fingerprint"] == expected_fingerprint
    assert expected_fingerprint != TurnService.semantic_fingerprint(
        replace(first_ctx, workspace_id="workspace-b")
    )
    assert len(server.runtime.turn_store.list_commits("workspace-a")) == 1
    assert server.runtime.turn_store.list_commits("workspace-b") == []
    assert generation_mgr.get_history_snapshot(first["session_id"]) == [
        {"role": "assistant", "content": "reply:workspace-a"}
    ]

    replay = await server.runtime.turn_outbox_dispatcher.dispatch_pending(
        context=SimpleNamespace(workspace_id="workspace-b", extra={})
    )

    assert replay["delivered"] == 1
    assert [item["workspace_id"] for item in saved_chats] == ["workspace-a"]
    assert [workspace_id for workspace_id, _event in relationship_events] == ["workspace-a"]
    traces = server.trace_store.snapshot()["runtime_loop"]
    assert [item["data"]["workspace_id"] for item in traces] == ["workspace-a"]
    assert [item["workspaceId"] for item in server.job_events.snapshot()] == ["workspace-a"]

    second = await server._dispatch_plugin_proactive_message(
        plugin_id="plugin-shared",
        message="workspace B signal",
        session_id="shared/custom:session",
        sid="sid-workspace",
    )

    assert second["session_id"] != first["session_id"]
    first_generation = generation_mgr.get(first["session_id"])
    second_generation = generation_mgr.get(second["session_id"])
    assert first_generation is not None and not first_generation.invalidated
    assert second_generation is not None and not second_generation.invalidated
    assert generation_mgr.get_history_snapshot(second["session_id"]) == [
        {"role": "assistant", "content": "reply:workspace-b"}
    ]

    third = await server._dispatch_plugin_proactive_message(
        plugin_id="plugin-other",
        message="other plugin in workspace B",
        session_id="shared/custom:session",
        sid="sid-workspace",
    )
    third_generation = generation_mgr.get(third["session_id"])
    assert third["session_id"] not in {first["session_id"], second["session_id"]}
    assert third_generation is not None and not third_generation.invalidated
    assert not first_generation.invalidated
    assert not second_generation.invalidated

    fourth = await server._dispatch_plugin_proactive_message(
        plugin_id="plugin-shared",
        message="same scoped session again",
        session_id="shared/custom:session",
        sid="sid-workspace",
    )
    assert fourth["session_id"] == second["session_id"]
    assert second_generation.invalidated
    assert not first_generation.invalidated
    assert not third_generation.invalidated
    assert generation_mgr.get_history_snapshot(fourth["session_id"]) == [
        {"role": "assistant", "content": "reply:workspace-b"},
        {"role": "assistant", "content": "reply:workspace-b"},
    ]

    normalized_contexts = [
        replace(
            ctx,
            request_id=first_ctx.request_id,
            turn_id=first_ctx.turn_id,
            generation_id=first_ctx.generation_id,
        )
        for ctx in pipeline.contexts[:3]
    ]
    assert len({TurnService.semantic_fingerprint(ctx) for ctx in normalized_contexts}) == 3

    replay = await server.runtime.turn_outbox_dispatcher.dispatch_pending(
        context=SimpleNamespace(workspace_id="workspace-a", extra={})
    )
    assert replay["delivered"] == 3
    assert [item["workspace_id"] for item in saved_chats] == [
        "workspace-a", "workspace-b", "workspace-b", "workspace-b",
    ]
    assert [item["session_id"] for item in saved_chats] == [
        first["session_id"], second["session_id"], third["session_id"], fourth["session_id"],
    ]
    current_shared_generation = generation_mgr.interrupt(fourth["session_id"])
    assert current_shared_generation is not None and current_shared_generation.invalidated
    assert not first_generation.invalidated
    assert not third_generation.invalidated
    with pytest.raises(RuntimeError, match="workspace does not match"):
        await server._dispatch_plugin_proactive_message(
            plugin_id="plugin-shared",
            message="stale workspace signal",
            sid="sid-workspace",
            metadata={"workspace_id": "workspace-a"},
        )


def test_http_semantic_execution_fails_closed_without_turn_service() -> None:
    pipeline = _SemanticPipeline()
    app = FastAPI()
    app.include_router(create_ai_router(
        get_config=lambda: SimpleNamespace(llm=SimpleNamespace(model="model")),
        get_generation_mgr=GenerationManager,
        get_llm_client=lambda: object(),
        get_svc_client=lambda: None,
        get_agent_runtime=lambda: _runtime(pipeline, None),
        get_db_repo=lambda: None,
        get_relationship_writer=lambda: None,
        get_relationship_history=lambda: [],
        get_relationship_summary=lambda: {},
        logger=SimpleNamespace(error=lambda *_args, **_kwargs: None),
    ))

    response = TestClient(app).post("/v1/chat/completions", json={
        "model": "model",
        "messages": [{"role": "user", "content": "must not run legacy"}],
    })

    assert response.status_code == 500
    assert response.json()["error"] == "chat_error"


@pytest.mark.asyncio
async def test_scheduler_completion_projects_authoritative_commit_stage(tmp_path: Any) -> None:
    pipeline = _SemanticPipeline()
    relationships: list[dict[str, object]] = []
    registry = RuntimeContextRegistry()
    registry.register(RuntimeContext(
        workspace_id="workspace-parity",
        relationship_event_writer=relationships.append,
    ))
    turn_store = TurnCommitStore(tmp_path / "turns.sqlite3")
    trace_store = AgentTraceStore(tmp_path / "trace.json")
    job_log = CompanionJobEventLog()
    runtime = create_agent_runtime(
        schedule_context_factory=lambda task: AgentRequestContext(
            sid="scheduler",
            session_id=f"schedule:{task.id}",
            messages=[{"role": "user", "content": task.prompt}],
            workspace_id="workspace-parity",
        ),
        schedule_workspace_id_provider=lambda: "workspace-parity",
        schedule_interruption_epoch_provider=lambda: 4,
        runtime_context_registry=registry,
        turn_store=turn_store,
        trace_store=trace_store,
        job_event_log=job_log,
    )
    runtime.turn_service.ports = replace(
        runtime.turn_service.ports,
        run=pipeline.run,
        run_streaming=pipeline.run_streaming,
    )
    scheduler = runtime.scheduler
    task = await scheduler.add_once("Parity", "same request", 60)

    await scheduler.run_now(task.id)
    await scheduler.wait_for_task(task.id, timeout=1)

    completed = scheduler.snapshot_job_events()[-1]
    assert completed["type"] == "AgentJobCompleted"
    assert completed["data"]["turnStage"] == "committed"
    assert completed["data"]["semanticFingerprint"]
    assert completed["data"]["generationId"] == f"generation:{completed['turnId']}"
    assert completed["interruptionEpoch"] == 4
    assert completed["jobId"] == scheduler.store.tasks[task.id].last_job_id
    assert completed["runId"] == scheduler.store.tasks[task.id].last_run_id
    assert turn_store.pending_outbox() == []
    assert len(relationships) == 1
    assert [entry["stage"] for entry in trace_store.snapshot()["runtime_loop"]] == ["turn_commit"]

    before = list(scheduler.snapshot_job_events())
    replay = await runtime.turn_outbox_dispatcher.dispatch_pending()
    assert replay["delivered"] == 0
    assert scheduler.snapshot_job_events() == before


@pytest.mark.asyncio
async def test_socket_text_and_delegated_voice_share_terminal_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = DesktopPetSocketServer(allow_legacy_turn_pipeline=False)
    pipeline = _SemanticPipeline()
    service = TurnService.from_pipeline(pipeline)
    generation_mgr = GenerationManager()
    emitted: list[tuple[str, object, str | None]] = []

    server.agent_pipeline = cast(Any, pipeline)
    server.turn_service = service
    monkeypatch.setattr(server, "llm_client", object())
    monkeypatch.setattr(server, "generation_mgr", generation_mgr)
    server.inject_runtime_context(active_workspace_provider=lambda: "workspace-parity")

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    monkeypatch.setattr(server.sio, "emit", _emit)
    handlers = cast(Any, server.sio).handlers["/"]
    payload = {
        "messages": [{"role": "user", "content": "same request"}],
        "workspace_id": "workspace-parity",
        "session_id": "session-parity",
        "request_id": "request-parity",
        "turn_id": "turn-parity",
        "generation_id": "generation-parity",
        "interruption_epoch": 2,
        "chat_options": {"tts_enabled": False},
    }

    await handlers[LLMEvents.REQUEST]("sid-parity", payload)
    first = generation_mgr.get("session-parity")
    assert first is not None and first.llm_task is not None
    await first.llm_task
    socket_terminals = [item for item in emitted if item[0] in {AgentEvents.RESULT, LLMEvents.FINAL}]
    emitted.clear()

    voice_payload = {
        **payload,
        "request_id": "request-voice-parity",
        "turn_id": "turn-voice-parity",
        "generation_id": "generation-voice-parity",
    }
    await handlers[AgentEvents.CHAT]("sid-parity", voice_payload)
    second = generation_mgr.get("session-parity")
    assert second is not None and second.llm_task is not None
    await second.llm_task
    voice_terminals = [item for item in emitted if item[0] in {AgentEvents.RESULT, LLMEvents.FINAL}]

    assert [item[0] for item in socket_terminals] == [AgentEvents.RESULT, LLMEvents.FINAL]
    assert [item[0] for item in voice_terminals] == [AgentEvents.RESULT, LLMEvents.FINAL]
    socket_result = cast(dict[str, object], socket_terminals[0][1])
    voice_result = cast(dict[str, object], voice_terminals[0][1])
    assert socket_result["semantic_fingerprint"]
    assert voice_result["semantic_fingerprint"]
    assert socket_result["semantic_fingerprint"] != voice_result["semantic_fingerprint"]
    assert socket_result["turn_stage"] == voice_result["turn_stage"] == "committed"
    assert socket_result["outcome"] == voice_result["outcome"] == "completed"
    assert socket_result["configured_budget"] == voice_result["configured_budget"]
    assert socket_result["turn_id"] == "turn-parity"
    assert voice_result["turn_id"] == "turn-voice-parity"
    assert socket_result["generation_id"] == "generation-parity"
    assert voice_result["generation_id"] == "generation-voice-parity"


@pytest.mark.asyncio
async def test_socket_same_identity_from_changed_permission_scope_conflicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    class CountingPipeline(_SemanticPipeline):
        async def run_streaming(
            self,
            ctx: AgentRequestContext,
            adapter: object,
            generation: object,
        ) -> AgentPipelineResult:
            nonlocal calls
            calls += 1
            return await super().run_streaming(ctx, adapter, generation)

    server = DesktopPetSocketServer(allow_legacy_turn_pipeline=False)
    pipeline = CountingPipeline()
    generation_mgr = GenerationManager()
    server.agent_pipeline = cast(Any, pipeline)
    server.turn_service = TurnService.from_pipeline(pipeline)
    monkeypatch.setattr(server, "llm_client", object())
    monkeypatch.setattr(server, "generation_mgr", generation_mgr)
    server.inject_runtime_context(active_workspace_provider=lambda: "workspace-parity")

    async def _emit(_event: str, _data: object = None, **_: object) -> None:
        return None

    monkeypatch.setattr(server.sio, "emit", _emit)
    handler = cast(Any, server.sio).handlers["/"][LLMEvents.REQUEST]
    payload = {
        "messages": [{"role": "user", "content": "same scoped request"}],
        "workspace_id": "workspace-parity",
        "session_id": "session-scoped",
        "request_id": "request-scoped",
        "turn_id": "turn-scoped",
        "generation_id": "generation-scoped",
        "chat_options": {"tts_enabled": False},
    }

    await handler("sid-a", payload)
    first = generation_mgr.get("session-scoped")
    assert first is not None and first.llm_task is not None
    await first.llm_task
    await handler("sid-b", payload)
    second = generation_mgr.get("session-scoped")
    assert second is not None and second.llm_task is not None
    with pytest.raises(TurnIdentityConflictError):
        await second.llm_task
    assert calls == 1
