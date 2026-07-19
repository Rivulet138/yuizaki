import asyncio
import json

import httpx
import pytest

from modules.core.state import Generation, GenerationManager
from modules.llm.client import (
    LLMClient,
    _messages_to_claude_payload,
    fetch_available_models,
    normalize_openai_base_url,
)


def _json_response(status_code: int, payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(status_code, json=payload)


PET_CONTEXT = {
    "emotions": ["happy"],
    "motionGroups": ["Tap"],
    "motionOptions": [{"group": "Tap", "index": 0}],
    "expressions": ["smile"],
    "parameters": [{"id": "ParamMouthOpenY", "min": 0, "max": 1}],
}


@pytest.mark.asyncio
async def test_preconnect_uses_models_get_without_generation_and_respects_cooldown() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _json_response(200, {"data": [{"id": "model-test"}]})

    client = LLMClient("https://llm.example/v1/chat/completions", "secret-key", "model-test")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert await client.preconnect(force=True) is True
        assert await client.preconnect() is True
        snapshot = client.status_snapshot()
    finally:
        await client.disconnect()

    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert str(requests[0].url) == "https://llm.example/v1/models"
    assert requests[0].headers.get("authorization") == "Bearer secret-key"
    assert requests[0].content == b""
    assert snapshot["preconnect_attempts"] == 1
    assert snapshot["preconnect_failures"] == 0
    assert snapshot["last_preconnect_reached_upstream"] is True
    assert snapshot["last_preconnect_ok"] is True
    assert snapshot["last_preconnect_http_status"] == 200
    assert "secret-key" not in str(snapshot)


@pytest.mark.asyncio
async def test_schedule_preconnect_deduplicates_concurrent_attempts() -> None:
    request_started = asyncio.Event()
    release_request = asyncio.Event()
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        request_started.set()
        await release_request.wait()
        return _json_response(200, {"data": []})

    client = LLMClient("https://llm.example/v1", "key", "model-test")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert client.schedule_preconnect() is True
        await request_started.wait()
        assert client.schedule_preconnect() is False
        release_request.set()
        task = client._preconnect_task
        assert task is not None
        assert await task is True
    finally:
        await client.disconnect()

    assert len(requests) == 1


def test_claude_payload_converts_openai_image_url_to_native_image_block() -> None:
    payload = _messages_to_claude_payload({
        "model": "claude-sonnet-4-5",
        "messages": [
            {"role": "system", "content": "system rule"},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,cG5n"}},
                    {"type": "text", "text": "inspect the live frame"},
                ],
            },
        ],
        "max_tokens": 64,
    })

    content = payload["messages"][0]["content"]
    assert payload["system"] == "system rule"
    assert content[0] == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": "cG5n",
        },
    }
    assert content[1] == {"type": "text", "text": "inspect the live frame"}


def test_claude_payload_converts_tool_contract_and_results() -> None:
    payload = _messages_to_claude_payload({
        "model": "claude-sonnet-4-5",
        "messages": [
            {"role": "user", "content": "what time is it"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "toolu_1",
                    "type": "function",
                    "function": {"name": "time_now", "arguments": "{}"},
                }],
            },
            {"role": "tool", "tool_call_id": "toolu_1", "content": "12:30"},
        ],
        "tools": [{
            "type": "function",
            "function": {
                "name": "time_now",
                "description": "Read the current time",
                "parameters": {"type": "object", "properties": {}},
            },
        }],
        "tool_choice": "auto",
        "max_tokens": 64,
    })

    assert payload["tools"] == [{
        "name": "time_now",
        "description": "Read the current time",
        "input_schema": {"type": "object", "properties": {}},
    }]
    assert payload["tool_choice"] == {"type": "auto"}
    assert payload["messages"][1] == {
        "role": "assistant",
        "content": [{"type": "tool_use", "id": "toolu_1", "name": "time_now", "input": {}}],
    }
    assert payload["messages"][2] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "12:30"}],
    }


@pytest.mark.parametrize(
    ("base_url", "normalized"),
    [
        ("https://api.deepseek.com/v1/chat/completions", "https://api.deepseek.com/v1"),
        ("https://dashscope.aliyuncs.com/compatible-mode/v1/models", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        ("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "https://generativelanguage.googleapis.com/v1beta/openai"),
        ("https://api.openai.com/v1/models", "https://api.openai.com/v1"),
        ("https://api.anthropic.com/v1/chat/completions", "https://api.anthropic.com/v1"),
        ("https://api.x.ai/v1/models", "https://api.x.ai/v1"),
    ],
)
def test_provider_presets_share_openai_compatible_endpoint_normalization(base_url: str, normalized: str) -> None:
    assert normalize_openai_base_url(base_url) == normalized


@pytest.mark.asyncio
async def test_fetch_available_models_uses_claude_models_endpoint_and_headers() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _json_response(200, {"data": [{"id": "claude-sonnet-4-5"}]})

    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    def fake_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    httpx.AsyncClient = fake_client  # type: ignore[assignment]
    try:
        models = await fetch_available_models("https://api.anthropic.com/v1/messages", "anthropic-key", 30, "claude")
    finally:
        httpx.AsyncClient = original_client  # type: ignore[assignment]

    assert models == ["claude-sonnet-4-5"]
    assert str(seen[0].url) == "https://api.anthropic.com/v1/models"
    assert seen[0].headers.get("authorization") is None
    assert seen[0].headers.get("x-api-key") == "anthropic-key"
    assert seen[0].headers.get("anthropic-version") == "2023-06-01"


@pytest.mark.asyncio
async def test_complete_chat_uses_claude_messages_endpoint() -> None:
    requests: list[httpx.Request] = []
    bodies: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        bodies.append(json.loads(request.content.decode("utf-8")))
        return _json_response(200, {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-5",
            "content": [{"type": "text", "text": "hello from claude"}],
            "stop_reason": "end_turn",
        })

    client = LLMClient("https://api.anthropic.com/v1/chat/completions", "anthropic-key", "claude-sonnet-4-5", provider="claude")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await client.complete_chat(
            [{"role": "system", "content": "system rule"}, {"role": "user", "content": "hello"}],
            max_output_tokens=64,
        )
    finally:
        await client.disconnect()

    assert str(requests[0].url) == "https://api.anthropic.com/v1/messages"
    assert requests[0].headers.get("authorization") is None
    assert requests[0].headers.get("x-api-key") == "anthropic-key"
    assert requests[0].headers.get("anthropic-version") == "2023-06-01"
    assert bodies[0]["system"] == "system rule"
    assert bodies[0]["messages"] == [{"role": "user", "content": "hello"}]
    assert bodies[0]["max_tokens"] == 64
    assert result["reply"] == "hello from claude"


@pytest.mark.asyncio
async def test_complete_chat_returns_claude_tool_use_as_normalized_tool_call() -> None:
    bodies: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content.decode("utf-8")))
        return _json_response(200, {
            "id": "msg_tool",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-5",
            "content": [{
                "type": "tool_use",
                "id": "toolu_123",
                "name": "time_now",
                "input": {"timezone": "Asia/Shanghai"},
            }],
            "stop_reason": "tool_use",
        })

    client = LLMClient("https://api.anthropic.com/v1", "anthropic-key", "claude-sonnet-4-5", provider="claude")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await client.complete_chat(
            [{"role": "user", "content": "what time is it"}],
            tools=[{
                "type": "function",
                "function": {
                    "name": "time_now",
                    "description": "Read the current time",
                    "parameters": {
                        "type": "object",
                        "properties": {"timezone": {"type": "string"}},
                    },
                },
            }],
        )
    finally:
        await client.disconnect()

    assert bodies[0]["tools"] == [{
        "name": "time_now",
        "description": "Read the current time",
        "input_schema": {
            "type": "object",
            "properties": {"timezone": {"type": "string"}},
        },
    }]
    assert result["reply"] == ""
    assert result["tool_calls"] == [{
        "id": "toolu_123",
        "type": "function",
        "function": {
            "name": "time_now",
            "arguments": '{"timezone":"Asia/Shanghai"}',
        },
    }]


@pytest.mark.asyncio
async def test_complete_chat_retries_without_rejected_temperature() -> None:
    requests: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content.decode("utf-8")))
        if len(requests) == 1:
            return _json_response(400, {"error": {"message": "Unsupported parameter: 'temperature' is not supported"}})
        return _json_response(200, {"choices": [{"message": {"content": "ok"}}]})

    client = LLMClient("https://llm.example/v1", "key", "model-test")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await client.complete_chat(
            [{"role": "user", "content": "hello"}],
            temperature=0.7,
            top_p=1.0,
            reasoning_effort="high",
            max_output_tokens=256,
        )
    finally:
        await client.disconnect()

    assert result["reply"] == "ok"
    assert len(requests) == 2
    assert "temperature" in requests[0]
    assert "temperature" not in requests[1]
    assert requests[1]["top_p"] == 1.0
    assert requests[1]["reasoning_effort"] == "high"


@pytest.mark.asyncio
async def test_complete_chat_sends_deepseek_thinking_switch() -> None:
    requests: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content.decode("utf-8")))
        return _json_response(200, {"choices": [{"message": {"content": "ok"}}]})

    client = LLMClient("https://api.deepseek.com/v1", "key", "deepseek-v4-flash")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await client.complete_chat(
            [{"role": "user", "content": "你好"}],
            thinking="disabled",
            max_output_tokens=256,
        )
    finally:
        await client.disconnect()

    assert result["reply"] == "ok"
    assert requests[0]["thinking"] == {"type": "disabled"}


@pytest.mark.asyncio
async def test_complete_chat_retries_text_only_when_image_input_is_rejected() -> None:
    requests: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        requests.append(payload)
        if len(requests) == 1:
            return _json_response(400, {"error": {"message": "image_url content is not supported by this model"}})
        return _json_response(200, {"choices": [{"message": {"content": "ok"}}]})

    client = LLMClient("https://llm.example/v1", "key", "model-test")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await client.complete_chat(
            [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,cG5n"}},
                    {"type": "text", "text": "what changed?"},
                ],
            }],
            max_output_tokens=128,
        )
    finally:
        await client.disconnect()

    assert result["reply"] == "ok"
    first_user = next(message for message in requests[0]["messages"] if message["role"] == "user")
    second_user = next(message for message in requests[1]["messages"] if message["role"] == "user")
    assert first_user["content"][0]["type"] == "image_url"
    assert isinstance(second_user["content"], str)
    assert "what changed?" in second_user["content"]
    assert "image_url" not in second_user["content"]


@pytest.mark.asyncio
async def test_complete_chat_retries_without_rejected_top_k() -> None:
    requests: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content.decode("utf-8")))
        if len(requests) == 1:
            return _json_response(400, {"error": {"message": "Unsupported parameter: 'top_k' is not supported"}})
        return _json_response(200, {"choices": [{"message": {"content": "ok"}}]})

    client = LLMClient("https://llm.example/v1", "key", "model-test")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await client.complete_chat(
            [{"role": "user", "content": "hello"}],
            top_k=500,
            frequency_penalty=0.2,
            max_output_tokens=256,
        )
    finally:
        await client.disconnect()

    assert result["reply"] == "ok"
    assert len(requests) == 2
    assert requests[0]["top_k"] == 500
    assert "top_k" not in requests[1]
    assert requests[1]["frequency_penalty"] == 0.2


@pytest.mark.asyncio
async def test_complete_chat_retries_with_max_completion_tokens_when_required() -> None:
    requests: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content.decode("utf-8")))
        if len(requests) == 1:
            return _json_response(400, {"error": {"message": "Unsupported parameter: 'max_tokens'. Use 'max_completion_tokens' instead."}})
        return _json_response(200, {"choices": [{"message": {"content": "ok"}}]})

    client = LLMClient("https://llm.example/v1", "key", "model-test")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await client.complete_chat(
            [{"role": "user", "content": "hello"}],
            max_output_tokens=512,
        )
    finally:
        await client.disconnect()

    assert result["reply"] == "ok"
    assert requests[0]["max_tokens"] == 512
    assert "max_tokens" not in requests[1]
    assert requests[1]["max_completion_tokens"] == 512


@pytest.mark.asyncio
async def test_complete_chat_sends_pet_control_json_schema_response_format() -> None:
    requests: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        requests.append(payload)
        content = json.dumps({
            "reply": "ok",
            "pet_control": {
                "emotion_id": "happy",
                "motion_group": "Tap",
                "motion_index": 0,
                "expression_name": "smile",
                "intensity": 0.6,
                "duration_ms": 1800,
                "expression_mix": [],
                "parameter_overrides": [],
                "sentence_emotions": [],
            },
        })
        return _json_response(200, {"choices": [{"message": {"content": content}}]})

    client = LLMClient("https://llm.example/v1", "key", "model-test")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await client.complete_chat(
            [{"role": "user", "content": "hello"}],
            pet_control_context=PET_CONTEXT,
        )
    finally:
        await client.disconnect()

    response_format = requests[0]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert result["pet_control"]["emotion_id"] == "happy"
    assert result["pet_control"]["motion_group"] == "Tap"


@pytest.mark.asyncio
async def test_complete_chat_retries_without_structured_response_format_when_rejected() -> None:
    requests: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        requests.append(payload)
        if len(requests) == 1:
            return _json_response(400, {"error": {"message": "Unsupported parameter: response_format json_schema strict"}})
        content = json.dumps({
            "reply": "ok",
            "pet_control": {
                "emotion_id": "happy",
                "motion_group": "Tap",
                "motion_index": 0,
                "intensity": 0.4,
                "duration_ms": 1200,
            },
        })
        return _json_response(200, {"choices": [{"message": {"content": content}}]})

    client = LLMClient("https://llm.example/v1", "key", "model-test")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await client.complete_chat(
            [{"role": "user", "content": "hello"}],
            pet_control_context=PET_CONTEXT,
        )
    finally:
        await client.disconnect()

    assert "response_format" in requests[0]
    assert "response_format" not in requests[1]
    assert result["reply"] == "ok"
    assert result["pet_control"]["motion_group"] == "Tap"


@pytest.mark.asyncio
async def test_stream_chat_retries_without_structured_response_format_when_rejected() -> None:
    requests: list[dict[str, object]] = []
    emitted: list[dict[str, object]] = []

    class FakeWs:
        async def send_json(self, payload: dict[str, object]) -> None:
            emitted.append(payload)

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        requests.append(payload)
        if len(requests) == 1:
            return _json_response(400, {"error": {"message": "This response_format type is unavailable now"}})
        content = json.dumps({
            "reply": "ok",
            "pet_control": {
                "emotion_id": "happy",
                "motion_group": "Tap",
                "motion_index": 0,
                "intensity": 0.4,
                "duration_ms": 1200,
            },
        })
        chunk = json.dumps({"choices": [{"delta": {"content": content}}]})
        return httpx.Response(200, content=f"data: {chunk}\n\ndata: [DONE]\n\n")

    client = LLMClient("https://llm.example/v1", "key", "model-test")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    generation = Generation(generation_id="gen-1", session_id="session-1")
    manager = GenerationManager()
    try:
        await client.stream_chat(
            FakeWs(),
            generation,
            manager,
            [{"role": "user", "content": "hello"}],
            pet_control_context=PET_CONTEXT,
            max_output_tokens=512,
        )
    finally:
        await client.disconnect()

    assert "response_format" in requests[0]
    assert "response_format" not in requests[1]
    assert getattr(generation, "pet_control")["motion_group"] == "Tap"
    assert emitted[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_stream_chat_uses_claude_messages_sse_and_emits_pet_control() -> None:
    requests: list[httpx.Request] = []
    bodies: list[dict[str, object]] = []
    emitted: list[dict[str, object]] = []

    class FakeWs:
        async def send_json(self, payload: dict[str, object]) -> None:
            emitted.append(payload)

    content = json.dumps({
        "reply": "hi",
        "pet_control": {
            "emotion_id": "happy",
            "motion_group": "Tap",
            "motion_index": 0,
            "intensity": 0.5,
            "duration_ms": 1200,
        },
    })
    first = content[:12]
    second = content[12:]

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        bodies.append(json.loads(request.content.decode("utf-8")))
        events = [
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": first},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": second},
            },
            {"type": "message_stop"},
        ]
        body = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)
        return httpx.Response(200, content=body)

    client = LLMClient("https://api.anthropic.com/v1/chat/completions", "anthropic-key", "claude-sonnet-4-5", provider="claude")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    generation = Generation(generation_id="gen-1", session_id="session-1")
    manager = GenerationManager()
    try:
        await client.stream_chat(
            FakeWs(),
            generation,
            manager,
            [{"role": "system", "content": "system rule"}, {"role": "user", "content": "hello"}],
            pet_control_context=PET_CONTEXT,
            max_output_tokens=512,
        )
    finally:
        await client.disconnect()

    assert str(requests[0].url) == "https://api.anthropic.com/v1/messages"
    assert requests[0].headers.get("authorization") is None
    assert requests[0].headers.get("x-api-key") == "anthropic-key"
    assert requests[0].headers.get("anthropic-version") == "2023-06-01"
    assert bodies[0]["stream"] is True
    assert bodies[0]["model"] == "claude-sonnet-4-5"
    assert bodies[0]["max_tokens"] == 512
    assert "system rule" in bodies[0]["system"]
    assert bodies[0]["messages"] == [{"role": "user", "content": "hello"}]
    assert "response_format" not in bodies[0]
    assert [event["content"] for event in emitted if event["type"] == "token"] == ["h", "i"]
    assert all("pet_control" not in str(event.get("content", "")) for event in emitted if event["type"] == "token")
    assert getattr(generation, "pet_control")["motion_group"] == "Tap"
    assert emitted[-2]["type"] == "pet_control"
    assert emitted[-1] == {
        "type": "done",
        "session_id": "session-1",
        "generation_id": "gen-1",
        "content": "hi",
    }
