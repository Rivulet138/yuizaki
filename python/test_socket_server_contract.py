from __future__ import annotations

import asyncio
import base64
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, cast

import pytest

from socket_events import AudioEvents, AgentEvents, LLMEvents, MemoryEvents, ScreenshotEvents, SystemEvents, ToolEvents, TTSEvents
from socket_server import DesktopPetSocketServer, _parse_socket_allowed_origins, _socket_auth_allowed
from modules.core.state import GenerationManager


def test_socket_server_restricts_default_cors_origins() -> None:
    server = DesktopPetSocketServer()
    origins = getattr(getattr(server.sio, "eio", None), "cors_allowed_origins", None)

    assert origins == [
        "file://",
        "http://127.0.0.1:38945",
        "http://localhost:38945",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]


def test_socket_origin_parser_preserves_packaged_electron_file_origin() -> None:
    assert _parse_socket_allowed_origins("file://, http://localhost:5173/") == [
        "file://",
        "http://localhost:5173",
    ]


def test_socket_auth_uses_backend_api_token_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YUIZAKI_ALLOW_UNAUTHENTICATED_LOCAL_DEV", raising=False)

    assert _socket_auth_allowed({"token": "backend-token"}, "backend-token") is True
    assert _socket_auth_allowed({"authorization": "Bearer backend-token"}, "backend-token") is True
    assert _socket_auth_allowed({}, "backend-token") is False
    assert _socket_auth_allowed({"token": "wrong"}, "backend-token") is False
    assert _socket_auth_allowed({}, "") is False


def test_socket_auth_can_be_explicitly_disabled_for_local_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YUIZAKI_ALLOW_UNAUTHENTICATED_LOCAL_DEV", "1")

    assert _socket_auth_allowed({}, "", {"REMOTE_ADDR": "127.0.0.1"}) is True
    assert _socket_auth_allowed({}, "", {"REMOTE_ADDR": "192.168.1.20"}) is False


@pytest.mark.asyncio
async def test_socket_connect_rejects_missing_backend_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YUIZAKI_BACKEND_API_TOKEN", "backend-token")
    server = DesktopPetSocketServer()

    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object], object | None], Awaitable[object]], handlers["/"]["connect"])
    result = await handler("sid-unauthorized", {}, None)

    assert result is False
    assert server.sessions == {}


@pytest.mark.asyncio
async def test_socket_connect_rejects_loopback_without_explicit_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YUIZAKI_BACKEND_API_TOKEN", raising=False)
    monkeypatch.delenv("YUIZAKI_ALLOW_UNAUTHENTICATED_LOCAL_DEV", raising=False)
    server = DesktopPetSocketServer()
    monkeypatch.setattr(server, "_schedule_socket_tool_bridge_refresh", lambda: None)

    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object], object | None], Awaitable[object]], handlers["/"]["connect"])
    result = await handler("sid-local", {"REMOTE_ADDR": "127.0.0.1"}, None)

    assert result is False
    assert server.sessions == {}


@pytest.mark.asyncio
async def test_renderer_playback_start_marks_the_active_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    generation_mgr = GenerationManager()
    generation = generation_mgr.start("session-1")
    emitted: list[tuple[str, object, str | None]] = []

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    monkeypatch.setattr(server, "generation_mgr", generation_mgr)
    monkeypatch.setattr(server.sio, "emit", _emit)
    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][SystemEvents.CLIENT_TIMING])

    await handler("sid-1", {
        "stage": "playback_start",
        "session_id": "session-1",
        "generation_id": generation.generation_id,
    })

    assert "playback_start" in generation.timings_ms
    assert emitted[-1][0] == SystemEvents.LATENCY
    assert emitted[-1][2] == "sid-1"


@pytest.mark.asyncio
async def test_interrupt_emits_a_correlated_ack(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    generation_mgr = GenerationManager()
    generation = generation_mgr.start("session-1")
    emitted: list[tuple[str, object, str | None]] = []

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    monkeypatch.setattr(server, "generation_mgr", generation_mgr)
    monkeypatch.setattr(server.sio, "emit", _emit)
    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][SystemEvents.INTERRUPT])

    await handler("sid-1", {
        "session_id": "session-1",
        "request_id": "interrupt-1",
        "source": "voice",
    })

    assert generation.cancel.is_set()
    assert emitted[-1][0] == SystemEvents.INTERRUPT_ACK
    ack = cast(dict[str, object], emitted[-1][1])
    assert ack["request_id"] == "interrupt-1"
    assert ack["session_id"] == "session-1"
    assert ack["source"] == "voice"
    assert ack["generation_id"] == generation.generation_id
    assert ack["hit_active_generation"] is True
    assert cast(float, ack["server_processing_ms"]) >= 0
    assert emitted[-1][2] == "sid-1"
    assert server.experience_metrics.snapshot()["interrupts"]["by_source"]["voice"] == {
        "requests": 1,
        "hits": 1,
        "hit_rate": 1.0,
    }


class _AgentContext(Protocol):
    autonomy_mode: str
    web_search_enabled: bool | None
    reasoning_effort: str | None
    thinking_mode: str | None
    response_mode: str
    prompt_profile: dict[str, object] | None
    messages: list[dict[str, Any]]
    extra: dict[str, Any]


class _SocketServerWithHandlers(Protocol):
    handlers: dict[str, dict[str, object]]


class _FakeGeneration:
    generation_id: str = "gen-test"

    def __init__(self) -> None:
        self.tokens: list[str] = []
        self.llm_task: asyncio.Task[None] | None = None
        self.tts_task: asyncio.Task[None] | None = None

    @property
    def full_text(self) -> str:
        return "".join(self.tokens)


class _FakeGenerationManager:
    def __init__(self) -> None:
        self.generation: _FakeGeneration = _FakeGeneration()
        self.history: list[tuple[str, str, str]] = []
        self.session_id: str = ""

    def start(self, session_id: str) -> _FakeGeneration:
        self.session_id = session_id
        return self.generation

    def get(self, session_id: str) -> _FakeGeneration | None:
        if session_id != self.session_id:
            return None
        return self.generation

    def append_history(self, session_id: str, role: str, content: str) -> None:
        self.history.append((session_id, role, content))


class _FakePipelineResult:
    reply: str = "ok"
    pet_control: None = None
    action_envelope: None = None


class _FakeAgentPipeline:
    def __init__(self) -> None:
        self.autonomy_mode: str | None = None
        self.web_search_enabled: bool | None = None
        self.reasoning_effort: str | None = None
        self.thinking_mode: str | None = None
        self.response_mode: str | None = None
        self.prompt_profile: dict[str, object] | None = None
        self.messages: list[dict[str, Any]] = []
        self.extra: dict[str, Any] = {}

    async def run(self, ctx: _AgentContext) -> _FakePipelineResult:
        self.autonomy_mode = ctx.autonomy_mode
        self.web_search_enabled = ctx.web_search_enabled
        self.reasoning_effort = ctx.reasoning_effort
        self.thinking_mode = ctx.thinking_mode
        self.response_mode = ctx.response_mode
        self.prompt_profile = ctx.prompt_profile
        self.messages = list(ctx.messages)
        self.extra = dict(ctx.extra)
        return _FakePipelineResult()

    async def run_streaming(self, ctx: _AgentContext, ws_adapter: object, generation: _FakeGeneration) -> _FakePipelineResult:
        result = await self.run(ctx)
        generation.tokens = [result.reply]
        manager = cast(Any, ctx).generation_mgr
        manager.append_history(cast(Any, ctx).session_id, "assistant", result.reply)
        await cast(Any, ws_adapter).send_json({"type": "token", "content": result.reply})
        await cast(Any, ws_adapter).send_json({"type": "done", "content": result.reply})
        return result


class _FakeRetrievalPipeline:
    def __init__(self) -> None:
        self.requests: list[object] = []

    def recall(self, request: object) -> dict[str, object]:
        self.requests.append(request)
        return {"docs": [], "ok": True}


class _SlowRetrievalPipeline(_FakeRetrievalPipeline):
    def recall(self, request: object) -> dict[str, object]:
        time.sleep(0.08)
        return super().recall(request)


class _FakeChatRepository:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, str, str, str]] = []

    def get_workspace_companion(self, workspace_id: str) -> dict[str, object] | None:
        return None

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tokens: int = 0,
        model: str = "",
        workspace_id: str = "default",
    ) -> None:
        self.messages.append((session_id, role, content, model, workspace_id))


class _FakePolicyEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool, bool, str | None, str | None]] = []

    def resolve_pending(
        self,
        request_id: str,
        allowed: bool,
        remember: bool,
        tool_name: str | None,
        permission_scope: str | None,
    ) -> None:
        self.calls.append((request_id, allowed, remember, tool_name, permission_scope))


class _FakeToolOutcome:
    success = True
    content = "ok"
    error = None


class _FakeToolExecutor:
    def __init__(self) -> None:
        self.policy_engine = _FakePolicyEngine()

    async def execute(
        self,
        name: str,
        _args: dict[str, object],
        permission_request_cb: Callable[..., Awaitable[None]],
    ) -> _FakeToolOutcome:
        await permission_request_cb(
            request_id="perm-1",
            tool_name=name,
            permission_scope="scope-1",
        )
        return _FakeToolOutcome()


class _FakeOcrClient:
    is_available = True

    def __init__(self) -> None:
        self.payloads: list[str] = []

    async def recognize(self, image_base64: str) -> dict[str, object]:
        self.payloads.append(image_base64)
        return {"status": "ok", "text": "screen text", "blocks": []}


class _FakeAsrManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes, bool]] = []
        self.cleaned: list[str] = []

    def cleanup(self, session_id: str) -> None:
        self.cleaned.append(session_id)

    async def handle_audio_chunk(
        self,
        ws: object,
        session_id: str,
        _mgr: object,
        pcm16_bytes: bytes,
        is_final: bool = False,
    ) -> None:
        self.calls.append((session_id, pcm16_bytes, is_final))
        send_json = getattr(ws, "send_json")
        await send_json({
            "type": "asr_final" if is_final else "asr_partial",
            "session_id": session_id,
            "text": "voice text",
        })


class _FakeVadAsrManager(_FakeAsrManager):
    async def handle_audio_chunk(
        self,
        ws: object,
        session_id: str,
        _mgr: object,
        pcm16_bytes: bytes,
        is_final: bool = False,
    ) -> None:
        self.calls.append((session_id, pcm16_bytes, is_final))
        await getattr(ws, "send_json")({
            "type": "asr_vad_start",
            "session_id": session_id,
            "confirmed_ms": 96,
        })
        await getattr(ws, "send_json")({
            "type": "asr_speech_start",
            "session_id": session_id,
            "confirmed_ms": 192,
        })


@pytest.mark.asyncio
async def test_disconnect_clears_asr_and_visual_session_state(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    asr_manager = _FakeAsrManager()
    monkeypatch.setattr(server, "asr_manager", asr_manager)
    server.sessions["sid-disconnect"] = {"id": "sid-disconnect"}
    server._record_visual_frame(
        "sid-disconnect",
        base64.b64encode(b"png").decode("ascii"),
        {"frame_id": "frame-private"},
        estimated_bytes=3,
    )
    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str], Awaitable[None]], handlers["/"]["disconnect"])

    await handler("sid-disconnect")

    assert asr_manager.cleaned == ["sid-disconnect"]
    assert "sid-disconnect" not in server.sessions
    assert "sid-disconnect" not in server._latest_visual_frames


class _FakeTtsClient:
    def __init__(self) -> None:
        self.calls = 0

    async def synthesize(self, _ws: object, _gen: object) -> None:
        self.calls += 1


class _FakeVoicePreparationLlm:
    def __init__(self) -> None:
        self.preconnect_calls = 0

    def schedule_preconnect(self) -> bool:
        self.preconnect_calls += 1
        return True


class _FakeVoicePreparationTts:
    def __init__(self) -> None:
        self.warmup_calls: list[dict[str, bool]] = []

    async def warmup(self, *, background: bool = False, force: bool = False) -> bool:
        self.warmup_calls.append({"background": background, "force": force})
        return True


@pytest.mark.asyncio
async def test_tts_is_skipped_with_error_when_llm_reply_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    generation_mgr = _FakeGenerationManager()
    generation = generation_mgr.start("session-1")
    generation.tokens = ["   "]
    emitted: list[tuple[str, object, str | None]] = []

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    monkeypatch.setattr(server, "generation_mgr", generation_mgr)
    monkeypatch.setattr(server, "tts_client", object())
    monkeypatch.setattr(server.sio, "emit", _emit)

    await server._run_tts_for_generation("session-1", "sid-1")

    assert generation.tts_task is None
    assert emitted == [(
        SystemEvents.ERROR,
        {
            "code": "LLM_EMPTY_RESPONSE",
            "message": "模型没有返回可朗读内容，请重试，或把最大输出 tokens 调高到 256 以上。",
            "session_id": "session-1",
        },
        "sid-1",
    )]


@pytest.mark.asyncio
async def test_agent_chat_reads_autonomy_mode_from_socket_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    generation_mgr = _FakeGenerationManager()
    pipeline = _FakeAgentPipeline()
    repository = _FakeChatRepository()
    emitted: list[tuple[str, object, str | None]] = []

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    deepseek_client = type("DeepSeekClient", (), {"provider": "deepseek", "model": "deepseek-v4-flash"})()
    monkeypatch.setattr(server, "llm_client", deepseek_client)
    monkeypatch.setattr(server, "generation_mgr", generation_mgr)
    monkeypatch.setattr(server, "agent_pipeline", pipeline)
    monkeypatch.setattr(server.sio, "emit", _emit)
    server.inject_runtime_context(db_repo=repository)

    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][AgentEvents.CHAT])
    await handler("sid-1", {
        "messages": [{"role": "user", "content": "hello"}],
        "session_id": "session-1",
        "workspace_id": "workspace-1",
        "chat_options": {"model": "deepseek-v4-flash", "web_search_enabled": True, "prompt_mode": "work", "response_mode": "deep"},
        "autonomy_mode": "executor",
    })
    assert generation_mgr.generation.llm_task is not None
    await generation_mgr.generation.llm_task

    assert pipeline.autonomy_mode == "executor"
    assert pipeline.web_search_enabled is True
    assert pipeline.reasoning_effort == "max"
    assert pipeline.thinking_mode == "enabled"
    assert pipeline.response_mode == "deep"
    assert pipeline.prompt_profile == {"mode": "work"}
    assert generation_mgr.history == [("session-1", "assistant", "ok")]
    assert repository.messages == [
        ("session-1", "user", "hello", "", "workspace-1"),
        ("session-1", "assistant", "ok", "deepseek-v4-flash", "workspace-1"),
    ]
    assert emitted[-1] == (LLMEvents.FINAL, {"text": "ok", "session_id": "session-1", "total_tokens": 0, "finish_reason": "stop"}, "sid-1")


@pytest.mark.asyncio
async def test_agent_chat_silent_mode_completes_with_zero_runtime_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    emitted: list[tuple[str, object, str | None]] = []
    generation_starts: list[str] = []

    class ForbiddenGenerationManager:
        def start(self, session_id: str) -> None:
            generation_starts.append(session_id)
            raise AssertionError("silent mode must not start a generation")

    class ForbiddenPipeline:
        def take_speculative_context_prefetch(self, **_kwargs: object) -> None:
            raise AssertionError("silent mode must not read speculative context")

        async def run_streaming(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("silent mode must not invoke the planner/pipeline")

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    monkeypatch.setattr(server, "llm_client", None)
    monkeypatch.setattr(server, "generation_mgr", ForbiddenGenerationManager())
    monkeypatch.setattr(server, "agent_pipeline", ForbiddenPipeline())
    monkeypatch.setattr(server, "tts_client", object())
    monkeypatch.setattr(server.sio, "emit", _emit)
    monkeypatch.setattr(
        server,
        "_with_ready_visual_context",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("visual context must not run")),
    )
    server.inject_runtime_context(
        db_repo=cast(Any, object()),
        relationship_event_writer=lambda _event: (_ for _ in ()).throw(AssertionError("relationship write must not run")),
        relationship_history_provider=lambda: (_ for _ in ()).throw(AssertionError("relationship read must not run")),
        relationship_summary_provider=lambda: (_ for _ in ()).throw(AssertionError("relationship read must not run")),
    )

    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][AgentEvents.CHAT])
    await handler("sid-silent", {
        "messages": [{"role": "user", "content": "write, schedule, inspect screen and speak"}],
        "session_id": "session-silent",
        "request_id": "agent-silent-socket",
        "autonomy_mode": "silent",
        "chat_options": {"tts_enabled": True},
    })

    assert generation_starts == []
    assert [event for event, _, _ in emitted] == [LLMEvents.FINAL, AgentEvents.RESULT]
    assert emitted[0] == (
        LLMEvents.FINAL,
        {"text": "", "session_id": "session-silent", "total_tokens": 0, "finish_reason": "stop"},
        "sid-silent",
    )
    assert "silent_autonomy_mode" in str(emitted[1][1])


@pytest.mark.asyncio
async def test_agent_chat_includes_latest_visual_frame_context_without_persisting_it(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    generation_mgr = _FakeGenerationManager()
    pipeline = _FakeAgentPipeline()
    repository = _FakeChatRepository()
    image = base64.b64encode(b"png").decode("ascii")
    emitted: list[tuple[str, object, str | None]] = []

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    monkeypatch.setattr(server, "llm_client", object())
    monkeypatch.setattr(server, "generation_mgr", generation_mgr)
    monkeypatch.setattr(server, "agent_pipeline", pipeline)
    monkeypatch.setattr(server.sio, "emit", _emit)
    server.inject_runtime_context(db_repo=repository)

    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    screenshot_handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][ScreenshotEvents.REQUEST])
    await screenshot_handler("sid-1", {
        "image": image,
        "mode": "observe",
        "caption": "user is resizing a settings panel",
        "frame_id": "frame-vision",
    })

    chat_handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][AgentEvents.CHAT])
    await chat_handler("sid-1", {
        "messages": [{"role": "user", "content": "what changed on my screen?"}],
        "session_id": "session-1",
        "workspace_id": "workspace-1",
        "chat_options": {"model": "gpt-test"},
    })
    assert generation_mgr.generation.llm_task is not None
    await generation_mgr.generation.llm_task

    visual_blocks = pipeline.extra["additional_prompt_blocks"]
    assert len(visual_blocks) == 1
    assert "[PROMPT_BLOCK id=visual_evidence source=desktop_capture trust=untrusted authority=evidence order=550]" in visual_blocks[0].render()
    assert "A single frame cannot establish changes across time" in visual_blocks[0].content
    assert "user is resizing a settings panel" in visual_blocks[0].content
    assert pipeline.messages[0]["role"] == "user"
    assert pipeline.messages[0]["content"][0] == {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{image}"},
    }
    assert pipeline.messages[0]["content"][1]["type"] == "text"
    assert "user is resizing a settings panel" in pipeline.messages[0]["content"][1]["text"]
    assert pipeline.messages[1] == {"role": "user", "content": "what changed on my screen?"}
    assert pipeline.extra["latest_visual_frame"]["frame_id"] == "frame-vision"
    assert repository.messages == [
        ("session-1", "user", "what changed on my screen?", "", "workspace-1"),
        ("session-1", "assistant", "ok", "gpt-test", "workspace-1"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("visual_requested", [False, True])
async def test_voice_agent_chat_only_carries_visual_frame_when_final_query_requests_it(
    monkeypatch: pytest.MonkeyPatch,
    visual_requested: bool,
) -> None:
    class VoicePrefetchPipeline(_FakeAgentPipeline):
        def take_speculative_context_prefetch(self, **_: object) -> dict[str, object]:
            return {
                "voice": True,
                "visual_requested": visual_requested,
                "visual_frame_id": "frame-voice",
                "tool_candidates": ["browser_open_page"],
                "partial_match": True,
            }

    server = DesktopPetSocketServer()
    generation_mgr = _FakeGenerationManager()
    pipeline = VoicePrefetchPipeline()
    server._record_visual_frame(
        "sid-voice",
        base64.b64encode(b"png").decode("ascii"),
        {"frame_id": "frame-voice", "source": "desktop"},
        estimated_bytes=3,
    )

    async def _emit(_event: str, _data: object = None, _to: str | None = None, **_: object) -> None:
        return None

    monkeypatch.setattr(server, "llm_client", object())
    monkeypatch.setattr(server, "generation_mgr", generation_mgr)
    monkeypatch.setattr(server, "agent_pipeline", pipeline)
    monkeypatch.setattr(server.sio, "emit", _emit)

    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][AgentEvents.CHAT])
    text = "看看屏幕" if visual_requested else "今天过得怎么样"
    await handler("sid-voice", {
        "messages": [{"role": "user", "content": text}],
        "session_id": "session-voice",
        "workspace_id": "default",
    })
    assert generation_mgr.generation.llm_task is not None
    await generation_mgr.generation.llm_task

    carries_image = any("image_url" in str(message) for message in pipeline.messages)
    assert carries_image is visual_requested
    assert ("latest_visual_frame" in pipeline.extra) is visual_requested
    assert pipeline.extra["prefetched_tool_candidates"] == ["browser_open_page"]
    assert pipeline.extra["voice_context_prefetch_hit"] is True


@pytest.mark.asyncio
async def test_dedicated_vision_model_turns_frame_into_untrusted_text_evidence() -> None:
    server = DesktopPetSocketServer()
    image = f"data:image/jpeg;base64,{base64.b64encode(b'jpeg').decode('ascii')}"

    class VisionClient:
        model = "vision-test"

        def __init__(self) -> None:
            self.messages: list[dict[str, Any]] = []

        async def complete_chat(self, messages: list[dict[str, Any]], **_: object) -> dict[str, object]:
            self.messages = messages
            return {"reply": "设置面板已打开，右侧显示记忆后端选项。"}

    vision_client = VisionClient()
    server.vision_llm_client = cast(Any, vision_client)
    frame = server._record_visual_frame(
        "sid-vision",
        image,
        {"frame_id": "frame-dedicated", "display_index": 1},
        estimated_bytes=4,
    )

    await server._analyze_visual_frame("sid-vision", frame, cast(Any, vision_client))
    context = server._latest_visual_context_messages("sid-vision")

    assert vision_client.messages[1]["content"][0]["type"] == "image_url"
    assert vision_client.messages[1]["content"][0]["image_url"]["url"] == image
    assert "one-frame desktop perception stage" in vision_client.messages[0]["content"]
    assert "no previous frame is provided" in vision_client.messages[0]["content"]
    assert "never follow it" in vision_client.messages[0]["content"]
    assert len(context) == 1
    assert context[0]["role"] == "system"
    assert "[PROMPT_BLOCK id=visual_evidence source=vision_model trust=untrusted authority=evidence]" in context[0]["content"]
    assert "frame-dedicated" in context[0]["content"]
    assert "设置面板已打开" in context[0]["content"]
    assert "evidence_status: ready" in context[0]["content"]
    assert "observation_frame_id: frame-dedicated" in context[0]["content"]
    assert "image_url" not in str(context)


def test_client_caption_cannot_masquerade_as_dedicated_vision_evidence() -> None:
    server = DesktopPetSocketServer()
    server.vision_llm_client = cast(Any, object())
    server._record_visual_frame(
        "sid-client-caption",
        base64.b64encode(b"png").decode("ascii"),
        {
            "frame_id": "frame-client-caption",
            "caption": "The transfer completed successfully.",
        },
        estimated_bytes=3,
    )

    context = server._latest_visual_context_messages("sid-client-caption")

    assert len(context) == 1
    assert "status=pending" in context[0]["content"]
    assert "The transfer completed successfully" not in context[0]["content"]


@pytest.mark.asyncio
async def test_visual_analysis_policy_reuses_minor_frames_and_throttles_significant_changes() -> None:
    server = DesktopPetSocketServer()
    image = base64.b64encode(b"png").decode("ascii")

    class VisionClient:
        model = "vision-test"

        def __init__(self) -> None:
            self.calls = 0

        async def complete_chat(self, _messages: list[dict[str, Any]], **_: object) -> dict[str, object]:
            self.calls += 1
            return {"reply": f"visible frame {self.calls}"}

    vision_client = VisionClient()
    server.vision_llm_client = cast(Any, vision_client)
    first = server._record_visual_frame(
        "sid-policy",
        image,
        {"frame_id": "frame-1", "change_score": 1.0, "capture_reason": "initial"},
        estimated_bytes=3,
    )

    assert server._schedule_visual_frame_analysis("sid-policy", first) == "pending"
    await server._visual_analysis_tasks["sid-policy"]
    assert vision_client.calls == 1

    minor = server._record_visual_frame(
        "sid-policy",
        image,
        {"frame_id": "frame-2", "change_score": 0.04, "capture_reason": "change"},
        estimated_bytes=3,
    )
    assert server._schedule_visual_frame_analysis("sid-policy", minor) == "cached"
    assert server._latest_visual_frames["sid-policy"]["analysis_reason"] == "minor_change_cached"
    cached_context = server._latest_visual_context_messages("sid-policy")
    assert "evidence_status: cached" in cached_context[0]["content"]
    assert "observation_frame_id: frame-1" in cached_context[0]["content"]
    assert "visible frame 1" in cached_context[0]["content"]

    significant = server._record_visual_frame(
        "sid-policy",
        image,
        {"frame_id": "frame-3", "change_score": 0.2, "capture_reason": "change"},
        estimated_bytes=3,
    )
    assert server._schedule_visual_frame_analysis("sid-policy", significant) == "cached"
    assert server._latest_visual_frames["sid-policy"]["analysis_reason"] == "analysis_cooldown"

    server._visual_analysis_last_started["sid-policy"] -= 9.0
    assert server._schedule_visual_frame_analysis("sid-policy", significant) == "pending"
    await server._visual_analysis_tasks["sid-policy"]

    assert vision_client.calls == 2
    assert server._visual_analysis_attempts["sid-policy"] == 2
    assert server._visual_analysis_skipped["sid-policy"] == 2


@pytest.mark.asyncio
async def test_explicit_visual_request_forces_current_frame_analysis_before_context() -> None:
    server = DesktopPetSocketServer()
    image = base64.b64encode(b"png").decode("ascii")

    class VisionClient:
        model = "vision-test"

        async def complete_chat(self, _messages: list[dict[str, Any]], **_: object) -> dict[str, object]:
            return {"reply": "The current screen visibly shows the memory settings panel."}

    server.vision_llm_client = cast(Any, VisionClient())
    server._record_visual_frame(
        "sid-explicit",
        image,
        {"frame_id": "frame-explicit", "change_score": 0.04, "capture_reason": "voice_change"},
        estimated_bytes=3,
    )
    server._visual_analysis_last_started["sid-explicit"] = time.monotonic()
    server._visual_analysis_last_completed["sid-explicit"] = time.monotonic()

    messages = await server._with_ready_visual_context(
        "sid-explicit",
        [{"role": "user", "content": "What is on my screen?"}],
        force_analysis=True,
    )

    assert server._visual_analysis_attempts["sid-explicit"] == 1
    assert server._latest_visual_frames["sid-explicit"]["analysis_reason"] == "explicit_visual_request"
    assert "memory settings panel" in str(messages[0]["content"])
    assert messages[-1] == {"role": "user", "content": "What is on my screen?"}


@pytest.mark.asyncio
async def test_explicit_visual_request_reanalyzes_cached_current_frame() -> None:
    server = DesktopPetSocketServer()
    image = base64.b64encode(b"png").decode("ascii")

    class VisionClient:
        model = "vision-test"

        def __init__(self) -> None:
            self.calls = 0

        async def complete_chat(self, _messages: list[dict[str, Any]], **_: object) -> dict[str, object]:
            self.calls += 1
            return {"reply": f"current frame {self.calls}"}

    vision_client = VisionClient()
    server.vision_llm_client = cast(Any, vision_client)
    first = server._record_visual_frame("sid-cached", image, {"frame_id": "frame-1"}, estimated_bytes=3)
    assert server._schedule_visual_frame_analysis("sid-cached", first) == "pending"
    await server._visual_analysis_tasks["sid-cached"]
    second = server._record_visual_frame(
        "sid-cached",
        image,
        {"frame_id": "frame-2", "change_score": 0.01, "capture_reason": "change"},
        estimated_bytes=3,
    )
    assert server._schedule_visual_frame_analysis("sid-cached", second) == "cached"

    messages = await server._with_ready_visual_context(
        "sid-cached",
        [{"role": "user", "content": "What is on my screen now?"}],
        force_analysis=True,
    )

    assert vision_client.calls == 2
    assert server._latest_visual_frames["sid-cached"]["observation_frame_id"] == "frame-2"
    assert "current frame 2" in str(messages[0]["content"])


def test_text_only_registered_model_does_not_receive_visual_frame_image() -> None:
    server = DesktopPetSocketServer()
    image = base64.b64encode(b"png").decode("ascii")

    class TextOnlyClient:
        provider = "deepseek"
        model = "deepseek-v4-flash"

    server.llm_client = cast(Any, TextOnlyClient())
    server._record_visual_frame(
        "sid-text-only",
        image,
        {"frame_id": "frame-text-only", "display_index": 0},
        estimated_bytes=3,
    )

    context = server._latest_visual_context_messages("sid-text-only")

    assert len(context) == 1
    assert context[0]["role"] == "system"
    assert "status=unsupported" in context[0]["content"]
    assert "deepseek-v4-flash" in context[0]["content"]
    assert "image_url" not in str(context)


@pytest.mark.asyncio
async def test_agent_chat_skips_tts_when_chat_option_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    generation_mgr = _FakeGenerationManager()
    pipeline = _FakeAgentPipeline()
    tts_client = _FakeTtsClient()
    emitted: list[tuple[str, object, str | None]] = []

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    monkeypatch.setattr(server, "llm_client", object())
    monkeypatch.setattr(server, "generation_mgr", generation_mgr)
    monkeypatch.setattr(server, "tts_client", tts_client)
    monkeypatch.setattr(server, "agent_pipeline", pipeline)
    monkeypatch.setattr(server.sio, "emit", _emit)

    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][AgentEvents.CHAT])
    await handler("sid-1", {
        "messages": [{"role": "user", "content": "hello"}],
        "session_id": "session-1",
        "chat_options": {"tts_enabled": False},
    })
    assert generation_mgr.generation.llm_task is not None
    await generation_mgr.generation.llm_task

    assert generation_mgr.generation.tts_task is None
    assert tts_client.calls == 0
    assert emitted[-1] == (LLMEvents.FINAL, {"text": "ok", "session_id": "session-1", "total_tokens": 0, "finish_reason": "stop"}, "sid-1")


@pytest.mark.asyncio
async def test_agent_chat_prefers_prompt_profile_mode_over_legacy_prompt_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    generation_mgr = _FakeGenerationManager()
    pipeline = _FakeAgentPipeline()
    emitted: list[tuple[str, object, str | None]] = []

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    monkeypatch.setattr(server, "llm_client", object())
    monkeypatch.setattr(server, "generation_mgr", generation_mgr)
    monkeypatch.setattr(server, "agent_pipeline", pipeline)
    monkeypatch.setattr(server.sio, "emit", _emit)

    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][AgentEvents.CHAT])
    await handler("sid-1", {
        "messages": [{"role": "user", "content": "hello"}],
        "session_id": "session-1",
        "chat_options": {
            "prompt_mode": "work",
            "prompt_profile": {
                "mode": "daily",
                "promptEngineering": {
                    "workPrompt": "自定义工作提示词",
                    "dailyPrompt": "自定义日常提示词",
                },
            },
        },
    })
    assert generation_mgr.generation.llm_task is not None
    await generation_mgr.generation.llm_task

    assert pipeline.prompt_profile == {
        "mode": "daily",
        "promptEngineering": {
            "workPrompt": "自定义工作提示词",
            "dailyPrompt": "自定义日常提示词",
        },
    }


@pytest.mark.asyncio
async def test_agent_chat_emits_first_tts_sentence_before_llm_final(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    generation_mgr = _FakeGenerationManager()
    repository = _FakeChatRepository()
    first_audio_ready = asyncio.Event()
    emitted: list[tuple[str, object, str | None]] = []

    class StreamingPipeline(_FakeAgentPipeline):
        async def run_streaming(self, ctx: _AgentContext, ws_adapter: object, generation: _FakeGeneration) -> _FakePipelineResult:
            self.messages = list(ctx.messages)
            generation.tokens = ["第一句。"]
            await cast(Any, ws_adapter).send_json({"type": "token", "content": "第一句。"})
            await asyncio.wait_for(first_audio_ready.wait(), timeout=1)
            generation.tokens.append("第二句")
            cast(Any, ctx).generation_mgr.append_history(cast(Any, ctx).session_id, "assistant", generation.full_text)
            await cast(Any, ws_adapter).send_json({"type": "token", "content": "第二句"})
            await cast(Any, ws_adapter).send_json({"type": "done", "content": generation.full_text})
            return _FakePipelineResult()

    class StreamingTtsClient:
        async def synthesize_stream_segment(self, ws: object, generation: object, text: str, sequence: int) -> bool:
            await cast(Any, ws).send_json({
                "type": "tts_audio",
                "generation_id": cast(Any, generation).generation_id,
                "audio_url": f"/audio/{sequence}.wav",
                "sequence": sequence,
                "is_final": False,
                "text": text,
            })
            first_audio_ready.set()
            return True

        async def complete_stream(self, ws: object, generation: object, sequence: int) -> None:
            await cast(Any, ws).send_json({
                "type": "tts_complete",
                "generation_id": cast(Any, generation).generation_id,
                "sequence": sequence,
                "is_final": True,
            })

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    monkeypatch.setattr(server, "llm_client", object())
    monkeypatch.setattr(server, "generation_mgr", generation_mgr)
    monkeypatch.setattr(server, "agent_pipeline", StreamingPipeline())
    monkeypatch.setattr(server, "tts_client", StreamingTtsClient())
    monkeypatch.setattr(server.sio, "emit", _emit)
    server.inject_runtime_context(db_repo=repository)

    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][AgentEvents.CHAT])
    await handler("sid-1", {
        "messages": [{"role": "user", "content": "hello"}],
        "session_id": "session-stream",
        "chat_options": {"tts_enabled": True},
    })
    assert generation_mgr.generation.llm_task is not None
    await generation_mgr.generation.llm_task

    event_names = [event for event, _data, _sid in emitted]
    assert event_names.index("tts:chunk") < event_names.index(LLMEvents.FINAL)
    assert "tts:done" in event_names
    first_tts_payload = next(data for event, data, _sid in emitted if event == "tts:chunk")
    assert cast(dict[str, object], first_tts_payload)["text"] == "第一句。"


@pytest.mark.asyncio
async def test_socket_forwards_binary_pcm_tts_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    emitted: list[tuple[str, object, str | None]] = []

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    monkeypatch.setattr(server.sio, "emit", _emit)
    await server._forward_tts_message("sid-1", "session-1", {
        "type": "tts_pcm",
        "generation_id": "generation-1",
        "audio": b"\x00\x00" * 3200,
        "audio_format": "pcm_s16le",
        "sample_rate": 32000,
        "channels": 1,
        "sample_width_bytes": 2,
        "duration_ms": 100.0,
        "sequence": 0,
        "chunk_index": 0,
        "visemes": [
            {"viseme": "ih", "offset_ms": 70, "weight": 2},
            {"viseme": "aa", "offset_ms": 0},
            {"viseme": "invalid", "offset_ms": 10},
        ],
        "text": "第一句。",
    })

    assert len(emitted) == 1
    event, payload, target = emitted[0]
    assert event == TTSEvents.CHUNK
    assert target == "sid-1"
    assert cast(dict[str, object], payload)["audio"] == b"\x00\x00" * 3200
    assert cast(dict[str, object], payload)["audio_format"] == "pcm_s16le"
    assert cast(dict[str, object], payload)["duration_ms"] == 100.0
    assert cast(dict[str, object], payload)["visemes"] == [
        {"viseme": "aa", "offset_ms": 0.0},
        {"viseme": "ih", "offset_ms": 70.0, "weight": 1.0},
    ]


@pytest.mark.asyncio
async def test_llm_request_rejects_workspace_mismatch_before_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    generation_mgr = _FakeGenerationManager()
    emitted: list[tuple[str, object, str | None]] = []

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    monkeypatch.setattr(server, "llm_client", object())
    monkeypatch.setattr(server, "generation_mgr", generation_mgr)
    monkeypatch.setattr(server.sio, "emit", _emit)
    server.inject_runtime_context(active_workspace_provider=lambda: "workspace-active")

    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][LLMEvents.REQUEST])
    await handler("sid-1", {
        "messages": [{"role": "user", "content": "hello"}],
        "session_id": "session-1",
        "workspace_id": "workspace-other",
    })

    assert generation_mgr.session_id == ""
    assert emitted == [(
        SystemEvents.ERROR,
        {"code": "WORKSPACE_MISMATCH", "message": "Socket request workspace does not match the active workspace"},
        "sid-1",
    )]


@pytest.mark.asyncio
async def test_agent_chat_rejects_workspace_mismatch_before_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    generation_mgr = _FakeGenerationManager()
    emitted: list[tuple[str, object, str | None]] = []

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    monkeypatch.setattr(server, "llm_client", object())
    monkeypatch.setattr(server, "generation_mgr", generation_mgr)
    monkeypatch.setattr(server.sio, "emit", _emit)
    server.inject_runtime_context(active_workspace_provider=lambda: "workspace-active")

    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][AgentEvents.CHAT])
    await handler("sid-1", {
        "messages": [{"role": "user", "content": "hello"}],
        "session_id": "session-1",
        "workspace_id": "workspace-other",
    })

    assert generation_mgr.session_id == ""
    assert emitted == [(
        SystemEvents.ERROR,
        {"code": "WORKSPACE_MISMATCH", "message": "Socket request workspace does not match the active workspace"},
        "sid-1",
    )]


@pytest.mark.asyncio
async def test_permission_response_rejects_unknown_request(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    emitted: list[tuple[str, object, str | None]] = []

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    fake_executor = _FakeToolExecutor()
    monkeypatch.setattr(server, "tool_executor", fake_executor)
    monkeypatch.setattr(server.sio, "emit", _emit)

    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][SystemEvents.PERMISSION_RESPONSE])
    await handler("sid-1", {"request_id": "missing", "allowed": True})

    assert fake_executor.policy_engine.calls == []
    assert emitted == [(
        SystemEvents.ERROR,
        {"code": "PERMISSION_REQUEST_UNKNOWN", "message": "Permission response did not match a pending request"},
        "sid-1",
    )]


@pytest.mark.asyncio
async def test_direct_tool_permission_response_is_bound_to_requesting_sid(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    emitted: list[tuple[str, object, str | None]] = []

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    fake_executor = _FakeToolExecutor()
    monkeypatch.setattr(server, "tool_executor", fake_executor)
    monkeypatch.setattr(server.sio, "emit", _emit)

    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    tool_handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][ToolEvents.CALL])
    permission_handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][SystemEvents.PERMISSION_RESPONSE])

    await tool_handler("sid-1", {"id": "call-1", "name": "read_file", "args": {}})
    await permission_handler("sid-2", {"request_id": "perm-1", "allowed": True})
    await permission_handler("sid-1", {"request_id": "perm-1", "allowed": True, "remember": True})

    assert fake_executor.policy_engine.calls == [("perm-1", True, True, "read_file", "scope-1")]
    assert (
        SystemEvents.ERROR,
        {"code": "PERMISSION_SESSION_MISMATCH", "message": "Permission response did not come from the requesting client"},
        "sid-2",
    ) in emitted


@pytest.mark.asyncio
async def test_socket_rag_query_rejects_invalid_memory_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    pipeline = _FakeRetrievalPipeline()
    emitted: list[tuple[str, object, str | None]] = []

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    monkeypatch.setattr(server.runtime.agent_pipeline, "retrieval_pipeline", pipeline, raising=False)
    monkeypatch.setattr(server.sio, "emit", _emit)

    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][MemoryEvents.QUERY])
    await handler("sid-1", {"query": "hello", "scope": "everything"})

    assert pipeline.requests == []
    assert emitted[0][0] == MemoryEvents.RESULT
    assert emitted[0][2] == "sid-1"
    assert isinstance(emitted[0][1], dict)
    assert emitted[0][1]["error"] == "INVALID_MEMORY_QUERY"


@pytest.mark.asyncio
async def test_socket_rag_query_rejects_workspace_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    server.inject_runtime_context(active_workspace_provider=lambda: "workspace-active")
    pipeline = _FakeRetrievalPipeline()
    emitted: list[tuple[str, object, str | None]] = []

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    monkeypatch.setattr(server.runtime.agent_pipeline, "retrieval_pipeline", pipeline, raising=False)
    monkeypatch.setattr(server.sio, "emit", _emit)

    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][MemoryEvents.QUERY])
    await handler("sid-1", {"query": "hello", "scope": "workspace", "workspace_id": "workspace-other"})

    assert pipeline.requests == []
    assert emitted == [(
        MemoryEvents.RESULT,
        {"docs": [], "error": "WORKSPACE_MISMATCH", "message": "Socket RAG workspace does not match the active workspace"},
        "sid-1",
    )]


@pytest.mark.asyncio
async def test_socket_rag_query_uses_validated_memory_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    pipeline = _FakeRetrievalPipeline()
    emitted: list[tuple[str, object, str | None]] = []

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    monkeypatch.setattr(server.runtime.agent_pipeline, "retrieval_pipeline", pipeline, raising=False)
    monkeypatch.setattr(server.sio, "emit", _emit)

    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][MemoryEvents.QUERY])
    await handler("sid-1", {
        "query": "hello",
        "scope": "workspace",
        "workspace_id": "workspace-1",
        "top_k": 3,
        "layers": ["semantic"],
    })

    request = pipeline.requests[0]
    assert getattr(request, "query") == "hello"
    assert getattr(request, "scope") == "workspace"
    assert getattr(request, "workspace_id") == "workspace-1"
    assert getattr(request, "top_k") == 3
    assert getattr(request, "layers") == ["semantic"]
    assert emitted == [(MemoryEvents.RESULT, {"docs": [], "ok": True}, "sid-1")]


@pytest.mark.asyncio
async def test_socket_rag_query_offloads_sync_retrieval_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    pipeline = _SlowRetrievalPipeline()
    emitted: list[tuple[str, object, str | None]] = []

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    monkeypatch.setattr(server.runtime.agent_pipeline, "retrieval_pipeline", pipeline, raising=False)
    monkeypatch.setattr(server.sio, "emit", _emit)

    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][MemoryEvents.QUERY])

    slow_task = asyncio.create_task(handler("sid-1", {"query": "hello", "scope": "workspace"}))
    started = time.perf_counter()
    await asyncio.sleep(0.01)
    latency_ms = (time.perf_counter() - started) * 1000
    await slow_task

    assert latency_ms < 50
    assert pipeline.requests
    assert emitted == [(MemoryEvents.RESULT, {"docs": [], "ok": True}, "sid-1")]


@pytest.mark.asyncio
async def test_socket_screenshot_request_falls_back_to_ocr_without_vision_model(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    ocr_client = _FakeOcrClient()
    image = base64.b64encode(b"png").decode("ascii")
    emitted: list[tuple[str, object, str | None]] = []

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    monkeypatch.setattr(server.sio, "emit", _emit)
    server.inject_services(ocr_client=ocr_client)

    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][ScreenshotEvents.REQUEST])
    await handler("sid-1", {
        "image": image,
        "mode": "observe",
        "caption": "user is moving a browser window",
        "source": "desktop",
        "frame_id": "frame-1",
        "display_index": 2,
        "change_score": 0.08,
        "capture_reason": "change",
    })

    assert ocr_client.payloads == [image]
    assert emitted[0][0] == ScreenshotEvents.RESULT
    assert emitted[0][2] == "sid-1"
    assert isinstance(emitted[0][1], dict)
    assert emitted[0][1]["status"] == "ok"
    assert emitted[0][1]["mode"] == "observe"
    assert emitted[0][1]["frame_id"] == "frame-1"
    assert emitted[0][1]["caption"] == "user is moving a browser window"
    assert emitted[0][1]["change_score"] == 0.08
    assert emitted[0][1]["capture_reason"] == "change"
    assert emitted[0][1]["analysis_status"] == "ocr_ready"
    assert emitted[0][1]["analysis_attempts"] == 0
    assert emitted[0][1]["analysis_skipped"] == 0
    assert server._latest_visual_frames["sid-1"]["image"] == image


@pytest.mark.asyncio
async def test_socket_visual_clear_removes_frame_and_observation(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    emitted: list[tuple[str, object, str | None]] = []

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    monkeypatch.setattr(server.sio, "emit", _emit)
    server._record_visual_frame("sid-clear", base64.b64encode(b"png").decode("ascii"), {}, estimated_bytes=3)
    server._latest_visual_observations["sid-clear"] = {"caption": "private"}
    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][ScreenshotEvents.REQUEST])

    await handler("sid-clear", {"mode": "clear"})

    assert "sid-clear" not in server._latest_visual_frames
    assert "sid-clear" not in server._latest_visual_observations
    assert emitted[-1] == (ScreenshotEvents.RESULT, {"status": "ok", "mode": "clear"}, "sid-clear")


@pytest.mark.asyncio
async def test_visual_analysis_emits_final_frame_status_and_records_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    image = base64.b64encode(b"png").decode("ascii")
    emitted: list[tuple[str, object, str | None]] = []

    class VisionClient:
        model = "vision-test"

        async def complete_chat(self, _messages: list[dict[str, Any]], **_: object) -> dict[str, object]:
            return {"reply": "A browser window is visibly open."}

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    monkeypatch.setattr(server.sio, "emit", _emit)
    server.vision_llm_client = cast(Any, VisionClient())

    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][ScreenshotEvents.REQUEST])
    await handler("sid-visual-final", {
        "image": image,
        "mode": "observe",
        "frame_id": "frame-final",
        "change_score": 1.0,
        "capture_reason": "initial",
    })
    await server._visual_analysis_tasks["sid-visual-final"]

    results = [payload for event, payload, target in emitted if event == ScreenshotEvents.RESULT and target == "sid-visual-final"]
    assert len(results) == 2
    assert isinstance(results[0], dict)
    assert isinstance(results[1], dict)
    assert results[0]["frame_id"] == "frame-final"
    assert results[0]["analysis_status"] == "pending"
    assert results[1]["frame_id"] == "frame-final"
    assert results[1]["analysis_status"] == "ready"
    assert results[1]["analysis_latency_ms"] >= 0

    metrics = server.experience_metrics.snapshot()
    assert metrics["visual"]["frames"] == 1
    assert metrics["visual"]["analysis_requests"] == 1
    assert metrics["visual"]["usable"] == 1
    assert metrics["latency"]["visual_analysis"]["samples"] == 1
    assert "browser window" not in str(metrics)


@pytest.mark.asyncio
async def test_socket_screenshot_request_uses_ocr_client_without_generation_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    ocr_client = _FakeOcrClient()
    image = base64.b64encode(b"png").decode("ascii")
    emitted: list[tuple[str, object, str | None]] = []

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    monkeypatch.setattr(server.sio, "emit", _emit)
    server.inject_services(ocr_client=ocr_client)

    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][ScreenshotEvents.REQUEST])
    await handler("sid-1", {"image": image, "mode": "ocr"})

    assert ocr_client.payloads == [image]
    assert emitted == [(
        ScreenshotEvents.RESULT,
        {"status": "ok", "text": "screen text", "blocks": []},
        "sid-1",
    )]


@pytest.mark.asyncio
async def test_audio_chunk_routes_pcm16_bytes_to_asr_and_emits_transcript(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    asr_manager = _FakeAsrManager()
    generation_mgr = _FakeGenerationManager()
    emitted: list[tuple[str, object, str | None]] = []

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    monkeypatch.setattr(server, "asr_manager", asr_manager)
    monkeypatch.setattr(server, "generation_mgr", generation_mgr)
    monkeypatch.setattr(server.sio, "emit", _emit)

    pcm16_bytes = b"\x01\x00\x02\x00"
    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][AudioEvents.CHUNK])

    await handler("sid-voice", {
        "chunk": base64.b64encode(pcm16_bytes).decode("ascii"),
        "sample_rate": 16000,
        "is_final": True,
    })

    assert asr_manager.calls == [("sid-voice", pcm16_bytes, True)]
    assert emitted == [(
        AudioEvents.ASR_FINAL,
        {"text": "voice text", "confidence": 0.0, "lang": "zh"},
        "sid-voice",
    )]
    prepared = server.agent_pipeline.take_speculative_context_prefetch(
        cache_key="sid-voice",
        final_query="voice text",
        workspace_id="default",
    )
    assert prepared is not None
    assert prepared["voice"] is True
    assert prepared["confirmed"] is True


@pytest.mark.asyncio
async def test_first_voice_chunk_preconnects_once_without_blocking_asr(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    asr_manager = _FakeAsrManager()
    llm_client = _FakeVoicePreparationLlm()
    tts_client = _FakeVoicePreparationTts()

    async def _emit(_event: str, _data: object = None, _to: str | None = None, **_: object) -> None:
        return None

    monkeypatch.setattr(server, "asr_manager", asr_manager)
    monkeypatch.setattr(server, "generation_mgr", _FakeGenerationManager())
    monkeypatch.setattr(server, "llm_client", llm_client)
    monkeypatch.setattr(server, "tts_client", tts_client)
    monkeypatch.setattr(server.sio, "emit", _emit)

    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][AudioEvents.CHUNK])
    payload = {
        "chunk": base64.b64encode(b"\x01\x00").decode("ascii"),
        "sample_rate": 16000,
        "is_final": False,
    }
    await handler("sid-voice", payload)
    await handler("sid-voice", payload)
    await asyncio.sleep(0)

    assert llm_client.preconnect_calls == 1
    assert tts_client.warmup_calls == [{"background": True, "force": False}]
    assert asr_manager.calls == [
        ("sid-voice", b"\x01\x00", False),
        ("sid-voice", b"\x01\x00", False),
    ]

    await handler("sid-voice", {"chunk": "", "sample_rate": 16000, "is_final": True})
    await handler("sid-voice", payload)
    await asyncio.sleep(0)
    assert llm_client.preconnect_calls == 2
    assert len(tts_client.warmup_calls) == 2


@pytest.mark.asyncio
async def test_voice_preparation_failures_do_not_block_asr(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingLlm:
        def schedule_preconnect(self) -> bool:
            raise RuntimeError("preconnect unavailable")

    class FailingTts:
        async def warmup(self, *, background: bool = False, force: bool = False) -> bool:
            raise RuntimeError("warmup unavailable")

    server = DesktopPetSocketServer()
    asr_manager = _FakeAsrManager()

    async def _emit(_event: str, _data: object = None, _to: str | None = None, **_: object) -> None:
        return None

    monkeypatch.setattr(server, "asr_manager", asr_manager)
    monkeypatch.setattr(server, "generation_mgr", _FakeGenerationManager())
    monkeypatch.setattr(server, "llm_client", FailingLlm())
    monkeypatch.setattr(server, "tts_client", FailingTts())
    monkeypatch.setattr(server.sio, "emit", _emit)

    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][AudioEvents.CHUNK])
    await handler("sid-voice", {
        "chunk": base64.b64encode(b"\x01\x00").decode("ascii"),
        "sample_rate": 16000,
        "is_final": False,
    })
    await asyncio.sleep(0)

    assert asr_manager.calls == [("sid-voice", b"\x01\x00", False)]


@pytest.mark.asyncio
async def test_audio_chunk_forwards_vad_and_real_speech_start(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    asr_manager = _FakeVadAsrManager()
    emitted: list[tuple[str, object, str | None]] = []

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    monkeypatch.setattr(server, "asr_manager", asr_manager)
    monkeypatch.setattr(server, "generation_mgr", _FakeGenerationManager())
    monkeypatch.setattr(server.sio, "emit", _emit)

    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][AudioEvents.CHUNK])
    await handler("sid-voice", {
        "chunk": base64.b64encode(b"\x01\x00").decode("ascii"),
        "sample_rate": 16000,
        "is_final": False,
    })

    assert emitted == [
        (
            AudioEvents.ASR_VAD_START,
            {"session_id": "sid-voice", "confirmed_ms": 96},
            "sid-voice",
        ),
        (
            AudioEvents.ASR_SPEECH_START,
            {"session_id": "sid-voice", "confirmed_ms": 192},
            "sid-voice",
        ),
    ]


@pytest.mark.asyncio
async def test_socket_screenshot_request_rejects_oversized_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    ocr_client = _FakeOcrClient()
    emitted: list[tuple[str, object, str | None]] = []

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    monkeypatch.setattr("socket_server.MAX_OCR_IMAGE_BYTES", 2)
    monkeypatch.setattr(server.sio, "emit", _emit)
    server.inject_services(ocr_client=ocr_client)

    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][ScreenshotEvents.REQUEST])
    await handler("sid-1", {"image": base64.b64encode(b"abc").decode("ascii"), "mode": "ocr"})

    assert ocr_client.payloads == []
    assert emitted[0][0] == ScreenshotEvents.RESULT
    assert emitted[0][2] == "sid-1"
    assert isinstance(emitted[0][1], dict)
    assert emitted[0][1]["error"] == "IMAGE_TOO_LARGE"
    assert emitted[0][1]["max_bytes"] == 2


@pytest.mark.asyncio
async def test_socket_rag_query_defaults_to_active_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    server.inject_runtime_context(active_workspace_provider=lambda: "workspace-active")
    pipeline = _FakeRetrievalPipeline()
    emitted: list[tuple[str, object, str | None]] = []

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    monkeypatch.setattr(server.runtime.agent_pipeline, "retrieval_pipeline", pipeline, raising=False)
    monkeypatch.setattr(server.sio, "emit", _emit)

    handlers = cast(_SocketServerWithHandlers, cast(object, server.sio)).handlers
    handler = cast(Callable[[str, dict[str, object]], Awaitable[None]], handlers["/"][MemoryEvents.QUERY])
    await handler("sid-1", {"query": "hello", "scope": "workspace"})

    request = pipeline.requests[0]
    assert getattr(request, "workspace_id") == "workspace-active"
    assert emitted == [(MemoryEvents.RESULT, {"docs": [], "ok": True}, "sid-1")]
@pytest.mark.asyncio
async def test_emit_latency_records_snapshot_and_forwards_event(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DesktopPetSocketServer()
    emitted: list[tuple[str, object, str | None]] = []

    async def _emit(event: str, data: object = None, to: str | None = None, **_: object) -> None:
        emitted.append((event, data, to))

    monkeypatch.setattr(server.sio, "emit", _emit)
    snapshot = {
        "kind": "generation",
        "session_id": "session-metrics",
        "generation_id": "generation-metrics",
        "stages": {"llm_first_token": 125.0},
    }

    await server._emit_latency("sid-metrics", snapshot)

    metrics = server.experience_metrics.snapshot()
    assert metrics["latency"]["llm_first_token"]["latest_ms"] == 125.0
    assert emitted == [(SystemEvents.LATENCY, snapshot, "sid-metrics")]
