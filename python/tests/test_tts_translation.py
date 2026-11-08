from __future__ import annotations

import pytest
from socket_server import _translate_tts_text_to_japanese


class _TranslationClient:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[dict[str, object]] = []

    async def complete_chat(self, messages, **options):
        self.calls.append({"messages": messages, **options})
        return {"reply": self.reply}


@pytest.mark.asyncio
async def test_tts_translation_translates_full_reply_once_and_uses_selected_model() -> None:
    client = _TranslationClient("こんにちは。今日は元気ですか？")

    translated = await _translate_tts_text_to_japanese(
        client, "你好。今天怎么样？", model="selected-model"
    )

    assert translated == "こんにちは。今日は元気ですか？"
    assert len(client.calls) == 1
    assert client.calls[0]["model"] == "selected-model"
    assert client.calls[0]["temperature"] == 0.1
    assert client.calls[0]["messages"][1]["content"] == "你好。今天怎么样？"


@pytest.mark.asyncio
async def test_tts_translation_fails_closed_when_translation_is_empty() -> None:
    with pytest.raises(RuntimeError, match="returned empty text"):
        await _translate_tts_text_to_japanese(_TranslationClient("  "), "需要朗读的内容")


@pytest.mark.asyncio
async def test_tts_translation_requires_the_configured_llm() -> None:
    with pytest.raises(RuntimeError, match="LLM client is unavailable"):
        await _translate_tts_text_to_japanese(None, "需要朗读的内容")
