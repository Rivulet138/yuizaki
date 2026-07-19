from __future__ import annotations

import asyncio
import base64
import json
import time
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.ai_api as ai_api
from state.schemas import ChatCompletionRequest


class _FakeSvcClient:
    def __init__(self) -> None:
        self.calls = 0

    async def convert(self, generation_id: str, audio_base64: str, **_kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        return {"generation_id": generation_id, "status": "done", "bytes": len(base64.b64decode(audio_base64))}


class _FakeOcrClient:
    is_available = True

    def __init__(self) -> None:
        self.calls = 0

    async def recognize(self, image_base64: str) -> dict[str, Any]:
        self.calls += 1
        return {"status": "ok", "text": "ok", "bytes": len(base64.b64decode(image_base64)), "blocks": []}


class _FakeLazyOcrClient(_FakeOcrClient):
    is_available = False


class _FakeAgentPipeline:
    def __init__(self) -> None:
        self.contexts: list[Any] = []

    async def run(self, ctx: Any) -> SimpleNamespace:
        self.contexts.append(ctx)
        return SimpleNamespace(reply="ok", pet_control=None, action_envelope=None)


class _FakeAgentRuntime:
    def __init__(self) -> None:
        self.agent_pipeline = _FakeAgentPipeline()
        self.tool_registry = None
        self.tool_executor = None
        self.step_executor = None
        self.scheduler = None
        self.trace_store = None
        self.plugin_manager = None


def _endpoint(router: Any, path: str) -> Any:
    return next(item.endpoint for item in router.routes if getattr(item, "path", "") == path)


async def _assert_event_loop_responsive(coro: Any) -> Any:
    slow_task = asyncio.create_task(coro)
    started = time.perf_counter()
    await asyncio.sleep(0.01)
    latency_ms = (time.perf_counter() - started) * 1000
    result = await slow_task

    assert latency_ms < 50
    return result


def _build_client(
    *,
    ocr_client: _FakeOcrClient | None = None,
    svc_client: _FakeSvcClient | None = None,
    agent_runtime: Any | None = None,
    llm_client: Any | None = None,
    active_workspace_id: str | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(
        ai_api.create_ai_router(
            get_config=lambda: SimpleNamespace(llm=SimpleNamespace(model="test-model")),
            get_generation_mgr=lambda: None,
            get_llm_client=lambda: llm_client,
            get_ocr_client=lambda: ocr_client,
            get_svc_client=lambda: svc_client,
            get_agent_runtime=lambda: agent_runtime or SimpleNamespace(),
            get_db_repo=lambda: None,
            get_relationship_writer=lambda: None,
            get_relationship_history=lambda: [],
            get_relationship_summary=lambda: {},
            logger=SimpleNamespace(error=lambda *_args, **_kwargs: None),
            get_active_workspace_id=(lambda: active_workspace_id) if active_workspace_id is not None else None,
        )
    )
    return TestClient(app)


def test_ocr_upload_rejects_files_over_limit(monkeypatch):
    monkeypatch.setattr(ai_api, "MAX_OCR_UPLOAD_BYTES", 4)
    ocr_client = _FakeOcrClient()
    client = _build_client(ocr_client=ocr_client)

    response = client.post("/vision/ocr", files={"file": ("large.png", b"12345", "image/png")})

    assert response.status_code == 413
    assert response.json() == {"error": "file_too_large", "max_bytes": 4}
    assert ocr_client.calls == 0


def test_ocr_upload_allows_client_to_initialize_on_demand():
    ocr_client = _FakeLazyOcrClient()
    client = _build_client(ocr_client=ocr_client)

    response = client.post("/vision/ocr", files={"file": ("small.png", b"1234", "image/png")})

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert ocr_client.calls == 1


def test_svc_upload_rejects_files_over_limit(monkeypatch):
    monkeypatch.setattr(ai_api, "MAX_SVC_UPLOAD_BYTES", 4)
    svc_client = _FakeSvcClient()
    client = _build_client(svc_client=svc_client)

    response = client.post("/svc/convert", files={"file": ("large.wav", b"12345", "audio/wav")})

    assert response.status_code == 413
    assert response.json() == {"error": "file_too_large", "max_bytes": 4}
    assert svc_client.calls == 0


def test_chat_completion_defaults_to_active_workspace():
    runtime = _FakeAgentRuntime()
    client = _build_client(agent_runtime=runtime, llm_client=object(), active_workspace_id="ws-active")

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "ok"
    assert runtime.agent_pipeline.contexts[0].workspace_id == "ws-active"


@pytest.mark.asyncio
async def test_chat_completion_offloads_sync_relationship_context_providers() -> None:
    runtime = _FakeAgentRuntime()
    relationship_events: list[dict[str, Any]] = []

    def slow_relationship_writer(event: dict[str, Any]) -> None:
        time.sleep(0.08)
        relationship_events.append(event)

    def slow_relationship_history() -> list[dict[str, str]]:
        time.sleep(0.08)
        return [{"kind": "support_request"}]

    def slow_relationship_summary() -> dict[str, str]:
        time.sleep(0.08)
        return {"relationship_stage": "stable"}

    router = ai_api.create_ai_router(
        get_config=lambda: SimpleNamespace(llm=SimpleNamespace(model="test-model")),
        get_generation_mgr=lambda: None,
        get_llm_client=lambda: object(),
        get_ocr_client=lambda: None,
        get_svc_client=lambda: None,
        get_agent_runtime=lambda: runtime,
        get_db_repo=lambda: None,
        get_relationship_writer=lambda: slow_relationship_writer,
        get_relationship_history=slow_relationship_history,
        get_relationship_summary=slow_relationship_summary,
        logger=SimpleNamespace(error=lambda *_args, **_kwargs: None),
        get_active_workspace_id=lambda: "ws-active",
    )
    endpoint = _endpoint(router, "/v1/chat/completions")
    request = ChatCompletionRequest(
        model="test-model",
        messages=[{"role": "user", "content": "help me with this"}],
    )

    response = await _assert_event_loop_responsive(endpoint(request))

    assert response.status_code == 200
    assert json.loads(response.body)["choices"][0]["message"]["content"] == "ok"
    ctx = runtime.agent_pipeline.contexts[0]
    assert ctx.extra["relationship_history"] == [{"kind": "support_request"}]
    assert ctx.extra["relationship_summary"] == {"relationship_stage": "stable"}
    assert relationship_events


def test_chat_completion_uses_requested_session_id():
    runtime = _FakeAgentRuntime()
    client = _build_client(agent_runtime=runtime, llm_client=object(), active_workspace_id="ws-active")

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "test-model",
            "session_id": "plugin:test-session",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 200
    assert runtime.agent_pipeline.contexts[0].session_id == "plugin:test-session"


def test_chat_completion_rejects_workspace_mismatch():
    runtime = _FakeAgentRuntime()
    client = _build_client(agent_runtime=runtime, llm_client=object(), active_workspace_id="ws-active")

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "hello"}],
            "workspace_id": "ws-other",
        },
    )

    assert response.status_code == 403
    assert response.json() == {
        "error": "workspace_mismatch",
        "message": "Chat workspace does not match the active workspace",
        "active_workspace_id": "ws-active",
    }
    assert runtime.agent_pipeline.contexts == []
