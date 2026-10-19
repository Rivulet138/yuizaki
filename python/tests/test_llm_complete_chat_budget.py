from __future__ import annotations

import json

import pytest

from modules.llm import client as llm_client_module
from modules.llm.client import LLMClient


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _RecordingHttp:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    async def post(self, _url: str, *, json: dict, headers: dict) -> _FakeResponse:  # noqa: A002 - mirrors httpx
        self.requests.append(json)
        return _FakeResponse({
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        })


@pytest.fixture()
def small_context(monkeypatch):
    monkeypatch.setattr(llm_client_module.config.llm, "context_max_tokens", 1024, raising=False)
    monkeypatch.setattr(llm_client_module.config.llm, "default_max_output_tokens", 256, raising=False)


@pytest.mark.asyncio
async def test_complete_chat_applies_the_context_window(small_context, monkeypatch) -> None:
    # Force an unregistered model so no registry clamp changes the budget.
    monkeypatch.setattr(llm_client_module.config.llm, "model", "unlisted-test-model", raising=False)
    llm = LLMClient("https://example.test/v1", "k", "unlisted-test-model", provider="custom")
    http = _RecordingHttp()
    llm._http = http  # type: ignore[assignment]

    huge_history = [
        {"role": "system", "content": "core policy"},
        {"role": "user", "content": "old question " + "x" * 8000},
        {"role": "assistant", "content": "old answer " + "y" * 8000},
        {"role": "user", "content": "latest question"},
    ]

    result = await llm.complete_chat(huge_history)

    assert result["reply"] == "ok"
    sent = http.requests[-1]["messages"]
    assert sent[-1]["content"] == "latest question"
    assert any(message["role"] == "system" for message in sent)
    # The oversized history must have been dropped instead of being sent whole.
    assert sum(len(str(message.get("content") or "")) for message in sent) < 12000


@pytest.mark.asyncio
async def test_complete_chat_counts_tool_schema_tokens(small_context, monkeypatch) -> None:
    monkeypatch.setattr(llm_client_module.config.llm, "model", "unlisted-test-model", raising=False)
    llm = LLMClient("https://example.test/v1", "k", "unlisted-test-model", provider="custom")
    http = _RecordingHttp()
    llm._http = http  # type: ignore[assignment]

    tools = [{
        "type": "function",
        "function": {
            "name": "demo",
            "description": "d" * 200,
            "parameters": {"type": "object", "properties": {"value": {"type": "string"}}},
        },
    }]
    messages = [
        {"role": "system", "content": "core policy"},
        {"role": "user", "content": "latest question"},
    ]

    await llm.complete_chat(messages, tools=tools)

    sent = http.requests[-1]
    assert sent["tools"] == tools
    assert sent["messages"][-1]["content"] == "latest question"


@pytest.mark.asyncio
async def test_complete_chat_drops_tools_that_cannot_fit(small_context, monkeypatch) -> None:
    monkeypatch.setattr(llm_client_module.config.llm, "model", "unlisted-test-model", raising=False)
    monkeypatch.setattr(llm_client_module.config.llm, "context_max_tokens", 512, raising=False)
    llm = LLMClient("https://example.test/v1", "k", "unlisted-test-model", provider="custom")
    http = _RecordingHttp()
    llm._http = http  # type: ignore[assignment]

    tools = [{
        "type": "function",
        "function": {
            "name": "demo",
            "description": "d" * 8000,
            "parameters": {"type": "object", "properties": {}},
        },
    }]

    await llm.complete_chat(
        [{"role": "system", "content": "core policy"}, {"role": "user", "content": "hi"}],
        tools=tools,
    )

    sent = http.requests[-1]
    assert "tools" not in sent
    assert "tool_choice" not in sent
    assert sent["messages"][-1]["content"] == "hi"


@pytest.mark.asyncio
async def test_complete_chat_keeps_short_conversations_intact(small_context, monkeypatch) -> None:
    monkeypatch.setattr(llm_client_module.config.llm, "model", "unlisted-test-model", raising=False)
    llm = LLMClient("https://example.test/v1", "k", "unlisted-test-model", provider="custom")
    http = _RecordingHttp()
    llm._http = http  # type: ignore[assignment]

    messages = [
        {"role": "system", "content": "core policy"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": "how are you"},
    ]

    await llm.complete_chat(messages)

    sent = http.requests[-1]["messages"]
    assert [message["role"] for message in sent] == ["system", "user", "assistant", "user"]
    assert json.dumps(sent, ensure_ascii=False).count("hello") == 1
