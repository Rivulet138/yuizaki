from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from socket_events import SOCKET_PROTOCOL_VERSION, protocol_version_status
from socket_handlers.audio import build_audio_chunk_handler
from socket_handlers.llm import LLMRequestSupport, build_llm_request_handler


@pytest.mark.parametrize("value", [0, 2, True, 1.5, float("nan"), "1.5", "v1", object()])
def test_socket_protocol_rejects_unknown_or_non_integral_versions(value: object) -> None:
    assert protocol_version_status(value) == (SOCKET_PROTOCOL_VERSION, False)


@pytest.mark.parametrize("value", [None, 1, 1.0, "1"])
def test_socket_protocol_accepts_only_current_version_forms(value: object) -> None:
    assert protocol_version_status(value) == (SOCKET_PROTOCOL_VERSION, True)


class _FakeSio:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object], str]] = []

    async def emit(self, event: str, payload: dict[str, object], *, to: str) -> None:
        self.events.append((event, payload, to))


@pytest.mark.asyncio
async def test_llm_protocol_rejection_happens_before_generation() -> None:
    sio = _FakeSio()

    class GenerationManager:
        def __init__(self) -> None:
            self.started = False

        def start(self, *_args, **_kwargs):
            self.started = True
            raise AssertionError("generation must not start for an unsupported version")

    generation = GenerationManager()

    identity = lambda data, session: {"session_id": session, "version": 999}
    support = LLMRequestSupport(
        request_identity=identity,
        as_text=lambda value, default="": value if isinstance(value, str) else default,
        as_int=lambda value, default=0: default,
        as_json_dict=lambda value: {},
        as_messages=lambda value: [],
        optional_float=lambda value: None,
        optional_bool=lambda value: None,
        request_option=lambda data, key: None,
        request_tts_enabled=lambda data: False,
        request_prompt_profile=lambda data: None,
        request_response_mode=lambda data: None,
        prompt_mode=lambda profile: None,
        event_payload=lambda value: {},
        generation_identity=lambda generation: {},
        agent_result_payload=lambda value, session, identity: {},
    )
    server = SimpleNamespace(llm_client=object(), generation_mgr=generation, sio=sio)
    handler = build_llm_request_handler(server=server, support=support, logger=logging.getLogger("test.llm-protocol"))

    await handler("sid", {"session_id": "s", "version": 999})

    assert generation.started is False
    assert sio.events[0][1]["code"] == "UNSUPPORTED_PROTOCOL_VERSION"
    assert sio.events[0][1]["version"] == SOCKET_PROTOCOL_VERSION


@pytest.mark.asyncio
async def test_audio_protocol_rejection_happens_before_asr() -> None:
    sio = _FakeSio()
    asr_called = False

    class ASR:
        async def handle_audio_chunk(self, *_args, **_kwargs):
            nonlocal asr_called
            asr_called = True

    async def emit_latency(*_args, **_kwargs):
        raise AssertionError("latency should not be emitted")

    handler = build_audio_chunk_handler(
        sio=sio,
        asr_manager_provider=lambda: ASR(),
        generation_manager_provider=lambda: object(),
        agent_pipeline_provider=lambda: object(),
        tool_registry_provider=lambda: object(),
        active_workspace_id=lambda: "workspace",
        latest_visual_frame_for_sid=lambda _sid: None,
        voice_prepared_sessions=set(),
        schedule_voice_turn_preparation=lambda: None,
        emit_latency=emit_latency,
    )

    await handler("sid", {"version": 999, "chunk": ""})

    assert asr_called is False
    assert sio.events[0][1]["code"] == "UNSUPPORTED_PROTOCOL_VERSION"
    assert sio.events[0][1]["version"] == SOCKET_PROTOCOL_VERSION
