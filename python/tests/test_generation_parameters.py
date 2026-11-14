from __future__ import annotations

import json
from copy import deepcopy

import httpx
import pytest

from modules.core.state import Generation, GenerationManager
from modules.llm import client as llm_client
from modules.llm.client import LLMClient, _apply_generation_options
from modules.llm.generation_parameters import (
    NUMERIC_GENERATION_FIELDS,
    load_generation_parameter_registry,
    resolve_generation_capabilities,
)


@pytest.mark.parametrize(
    ("provider", "supported"),
    [
        ("custom", set(NUMERIC_GENERATION_FIELDS)),
        ("unregistered", set(NUMERIC_GENERATION_FIELDS)),
        ("chatgpt", {"temperature", "top_p", "frequency_penalty", "presence_penalty"}),
        ("deepseek", {"temperature", "top_p"}),
        (
            "qwen",
            {"temperature", "top_p", "top_k", "presence_penalty", "repetition_penalty"},
        ),
        ("gemini", {"temperature", "top_p", "top_k"}),
        ("claude", {"temperature", "top_p", "top_k"}),
        ("grok", {"temperature", "top_p", "frequency_penalty", "presence_penalty"}),
        ("ollama", {"temperature", "top_p", "frequency_penalty", "presence_penalty"}),
        (
            "lmstudio",
            {
                "temperature",
                "top_p",
                "top_k",
                "frequency_penalty",
                "presence_penalty",
                "repetition_penalty",
            },
        ),
    ],
)
def test_provider_defaults_are_scoped_and_unknown_reasoning_is_not_inferred(
    provider, supported
):
    caps = resolve_generation_capabilities(provider, "unlisted-model")
    assert set(caps["parameters"]) == supported
    assert caps["reasoningEfforts"] == []
    body = {
        "model": "unlisted-model",
        "reasoning_effort": "high",
        "thinking": {"type": "enabled"},
    }
    _apply_generation_options(body, provider=provider)
    assert "reasoning_effort" not in body
    assert "thinking" not in body


@pytest.mark.parametrize(
    "model", ["gpt-5", "gpt-5-mini", "gpt-5-nano", "o1", "o3", "o4-mini"]
)
def test_openai_reasoning_models_remove_all_stale_numeric_fields(model):
    body = dict(
        model=model, max_tokens=100, **dict.fromkeys(NUMERIC_GENERATION_FIELDS, 0.5)
    )
    _apply_generation_options(body, provider="chatgpt", reasoning_effort="high")
    assert not set(NUMERIC_GENERATION_FIELDS).intersection(body)
    assert body["reasoning_effort"] == "high"
    assert body["max_completion_tokens"] == 100
    assert "max_tokens" not in body


@pytest.mark.parametrize("model", ["gpt-5", "o3", "gpt-6.1-sol"])
def test_gateway_with_identical_model_name_does_not_inherit_openai_rules(model):
    body = {"model": model, "max_tokens": 100}
    _apply_generation_options(
        body, provider="custom", temperature=0.7, top_k=40, reasoning_effort="high"
    )
    assert body["temperature"] == 0.7
    assert body["top_k"] == 40
    assert body["max_tokens"] == 100
    assert "reasoning_effort" not in body


@pytest.mark.parametrize(
    "model", ["gpt-5.1", "gpt-5.2", "gpt-6-sol", "gpt-6-luna", "gpt-6.1-terra"]
)
@pytest.mark.parametrize("effort", [None, "default", "high", "none"])
def test_sampling_requires_explicit_supported_none(model, effort):
    body = {"model": model, "temperature": 0.7, "top_p": 0.9}
    _apply_generation_options(body, provider="chatgpt", reasoning_effort=effort)
    assert ("temperature" in body) == (effort == "none")
    assert ("top_p" in body) == (effort == "none")
    if effort == "none":
        assert body["reasoning_effort"] == "none"
    elif effort in (None, "default"):
        assert "reasoning_effort" not in body


@pytest.mark.parametrize("model", ["gpt-6-astra", "gpt-6.1-sol"])
def test_none_is_not_a_supported_effort_for_astra_or_sol_61(model):
    body = {"model": model, "temperature": 0.7, "top_p": 0.9}
    _apply_generation_options(body, provider="chatgpt", reasoning_effort="none")
    assert not {"temperature", "top_p", "reasoning_effort"}.intersection(body)
    assert (
        "none"
        not in resolve_generation_capabilities("chatgpt", model)["reasoningEfforts"]
    )


def test_gpt4_keeps_supported_sampling_and_drops_stale_reasoning_and_other_providers_fields():
    body = {
        "model": "gpt-4o",
        "reasoning_effort": "high",
        "thinking": {"type": "enabled"},
        "enable_thinking": True,
        "thinking_config": {"thinking_level": "high"},
        "output_config": {"effort": "high"},
        **dict.fromkeys(NUMERIC_GENERATION_FIELDS, 0.5),
    }
    _apply_generation_options(body, provider="chatgpt")
    assert set(body) == {
        "model",
        "temperature",
        "top_p",
        "frequency_penalty",
        "presence_penalty",
    }


def test_normalization_ordered_rule_replacement_and_registry_immutability():
    caps = resolve_generation_capabilities(" OpenAI ", " Models/GPT-6.1-SOL ")
    assert caps["parameters"] == {}
    assert "none" not in caps["reasoningEfforts"]
    caps["reasoningEfforts"].append("invented")
    assert (
        "invented"
        not in resolve_generation_capabilities("chatgpt", "gpt-6.1-sol")[
            "reasoningEfforts"
        ]
    )
    registry = load_generation_parameter_registry()
    assert set(registry) == {"providers", "rules"}
    assert all(
        "default" not in row.get("reasoningEfforts", [])
        for row in [*registry["providers"].values(), *registry["rules"]]
    )
    for row in [*registry["providers"].values(), *registry["rules"]]:
        assert set(row.get("parameters", {})) <= set(NUMERIC_GENERATION_FIELDS)


def test_model_override_wins_over_body_and_global_config(monkeypatch):
    monkeypatch.setattr(llm_client.config.llm, "model", "gpt-6.1-sol")
    body = {"model": "o3", "temperature": 0.4, "top_p": 0.8}
    _apply_generation_options(
        body, provider="chatgpt", model="gpt-4o", reasoning_effort="high"
    )
    assert body == {"model": "gpt-4o", "temperature": 0.4, "top_p": 0.8}
    body = {"model": "gpt-4o", "temperature": 0.4}
    _apply_generation_options(body, provider="chatgpt")
    assert body["temperature"] == 0.4


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        "NaN",
        "inf",
        "",
        "invalid",
        True,
        {},
        [],
    ],
)
def test_invalid_numbers_are_removed_without_raising_or_serializing_nan(value):
    body = {"model": "unknown", **dict.fromkeys(NUMERIC_GENERATION_FIELDS, value)}
    _apply_generation_options(body, provider="custom")
    assert body == {"model": "unknown"}
    json.dumps(body, allow_nan=False)


def test_clamps_integer_values_and_explicit_neutral_overrides():
    body = {"model": "gpt-4o"}
    _apply_generation_options(
        body,
        provider="chatgpt",
        temperature=-20,
        top_p=20,
        frequency_penalty=-20,
        presence_penalty=20,
    )
    assert body == {
        "model": "gpt-4o",
        "temperature": 0.0,
        "top_p": 1.0,
        "frequency_penalty": -2.0,
        "presence_penalty": 2.0,
    }
    body = {
        "model": "unknown",
        "top_k": 40,
        "min_p": 0.2,
        "frequency_penalty": 0.4,
        "presence_penalty": 0.5,
        "repetition_penalty": 1.5,
    }
    _apply_generation_options(
        body,
        provider="custom",
        top_k=0,
        min_p=0,
        frequency_penalty=0,
        presence_penalty=0,
        repetition_penalty=1,
    )
    assert body == {"model": "unknown"}
    _apply_generation_options(body, provider="custom", top_k=25.8)
    assert body["top_k"] == 25


@pytest.mark.parametrize(
    ("model", "effort", "expected"),
    [
        ("gemini-2.5-flash", "none", {"thinkingBudget": 0}),
        ("gemini-2.5-flash", "medium", {"thinkingBudget": 8192}),
        ("gemini-2.5-pro", "low", {"thinkingBudget": 1024}),
        ("gemini-3-flash-preview", "minimal", {"thinkingLevel": "minimal"}),
        ("gemini-3-pro-preview", "high", {"thinkingLevel": "high"}),
    ],
)
def test_native_gemini_maps_verified_reasoning_and_supported_numeric_fields(
    model, effort, expected
):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 4096,
        "reasoning_effort": effort,
        **dict.fromkeys(NUMERIC_GENERATION_FIELDS, 0.5),
    }
    original = deepcopy(body)
    payload = llm_client._messages_to_gemini_payload(body)
    assert body == original
    settings = payload["generationConfig"]
    assert settings["thinkingConfig"] == expected
    assert settings["maxOutputTokens"] == 4096
    assert settings["topK"] == 1
    assert not {"reasoning_effort", "frequency_penalty", "min_p"}.intersection(payload)


@pytest.mark.parametrize("model", ["gemini-2.5-pro", "gemini-3-pro-preview", "unknown"])
def test_gemini_drops_unsupported_none_or_unverified_reasoning(model):
    payload = llm_client._messages_to_gemini_payload(
        {"model": model, "reasoning_effort": "none"}
    )
    assert "thinkingConfig" not in payload.get("generationConfig", {})


@pytest.mark.parametrize(
    "model", ["gemini-3.6-flash", "gemini-3.8-flash", "gemini-4-argon"]
)
def test_new_gemini_flash_drops_ignored_sampling(model):
    payload = llm_client._messages_to_gemini_payload(
        {
            "model": model,
            "temperature": 0.5,
            "top_p": 0.9,
            "top_k": 20,
            "reasoning_effort": "low",
        }
    )
    assert payload["generationConfig"] == {"thinkingConfig": {"thinkingLevel": "low"}}


@pytest.mark.parametrize(
    ("model", "effort", "thinking"),
    [
        ("claude-opus-4-5", "high", None),
        ("claude-opus-4-6", "max", {"type": "adaptive"}),
        ("claude-sonnet-4-6", "medium", {"type": "adaptive"}),
        ("claude-opus-4-7", "high", {"type": "adaptive"}),
    ],
)
def test_native_claude_maps_effort_and_adaptive_thinking(model, effort, thinking):
    body = {
        "model": model,
        "max_completion_tokens": 4096,
        "reasoning_effort": effort,
        "temperature": 0.2,
        "top_p": 0.3,
        "top_k": 32,
        "min_p": 0.2,
        "frequency_penalty": 0.4,
    }
    payload = llm_client._messages_to_claude_payload(body)
    assert payload["output_config"] == {"effort": effort}
    assert payload.get("thinking") == thinking
    assert payload["max_tokens"] == 4096
    assert not {
        "reasoning_effort",
        "min_p",
        "frequency_penalty",
        "max_completion_tokens",
    }.intersection(payload)
    if model == "claude-opus-4-7":
        assert not {"temperature", "top_p", "top_k"}.intersection(payload)
    elif thinking:
        assert payload["temperature"] == 1.0
        assert payload["top_p"] == 0.99
        assert "top_k" not in payload
    else:
        assert payload["top_k"] == 32


def test_old_claude_drops_unknown_effort_and_keeps_supported_top_k():
    payload = llm_client._messages_to_claude_payload(
        {
            "model": "claude-3-5-sonnet-20241022",
            "reasoning_effort": "high",
            "thinking": {"type": "enabled"},
            "top_k": 40,
        }
    )
    assert payload["top_k"] == 40
    assert "thinking" not in payload and "output_config" not in payload


def test_deepseek_thinking_switch_and_flash_top_p_behavior():
    body = {
        "model": "deepseek-flash",
        "top_p": 0.2,
        "frequency_penalty": 0.3,
        "temperature": 0.5,
    }
    _apply_generation_options(body, provider="deepseek", reasoning_effort="low")
    assert body == {
        "model": "deepseek-flash",
        "thinking": {"type": "enabled"},
        "reasoning_effort": "low",
        "top_p": 0.95,
    }
    _apply_generation_options(body, provider="deepseek", reasoning_effort="none")
    assert body == {"model": "deepseek-flash", "thinking": {"type": "disabled"}}
    body = {"model": "deepseek-v4-pro", "top_p": 0.8}
    _apply_generation_options(body, provider="deepseek", reasoning_effort="max")
    assert body["reasoning_effort"] == "max" and "top_p" not in body


@pytest.mark.parametrize(
    ("effort", "expected"),
    [("none", {"enable_thinking": False}), ("auto", {"enable_thinking": True})],
)
def test_qwen_hybrid_uses_switch_without_invented_effort(effort, expected):
    body = {"model": "qwen3-32b", "reasoning_effort": effort}
    _apply_generation_options(body, provider="qwen")
    assert body == {"model": "qwen3-32b", **expected}


def test_qwen38_uses_supported_effort_and_output_token_field():
    body = {
        "model": "qwen3.8-flash",
        "max_tokens": 500,
        "temperature": 0.1,
        "min_p": 0.2,
        "frequency_penalty": 1,
    }
    _apply_generation_options(body, provider="qwen", reasoning_effort="xhigh")
    assert body == {
        "model": "qwen3.8-flash",
        "enable_thinking": True,
        "reasoning_effort": "xhigh",
        "max_completion_tokens": 500,
        "temperature": 0.6,
    }


def test_lmstudio_wire_name_and_ollama_openai_compat_limit():
    body = {
        "model": "local",
        "repetition_penalty": 1.2,
        "min_p": 0.1,
        "top_k": 25,
        "reasoning_effort": "high",
    }
    _apply_generation_options(body, provider="lmstudio")
    assert body == {"model": "local", "repeat_penalty": 1.2, "top_k": 25}
    _apply_generation_options(body, provider="ollama")
    assert body == {"model": "local"}


class _Socket:
    def __init__(self):
        self.sent = []

    async def send_json(self, value):
        self.sent.append(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    ("provider", "base", "model", "effort"),
    [
        ("chatgpt", "https://example.test/v1", "gpt-5.2", "none"),
        ("chatgpt", "https://example.test/v1", "o3", "high"),
        ("custom", "https://example.test/v1", "gpt-5.2", "high"),
        (
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta",
            "gemini-2.5-flash",
            "none",
        ),
        (
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            "gemini-3-pro-preview",
            "high",
        ),
        ("claude", "https://example.test/v1", "claude-opus-4-6", "high"),
        ("lmstudio", "http://localhost:1234/v1", "local-model", "high"),
    ],
)
async def test_complete_and_stream_use_actual_override_provider_and_native_wire_mapping(
    monkeypatch, stream, provider, base, model, effort
):
    monkeypatch.setattr(llm_client.config.llm, "model", "global-wrong-model")
    for field in NUMERIC_GENERATION_FIELDS:
        monkeypatch.setattr(
            llm_client.config.llm, field, 30 if field == "top_k" else 0.4
        )
    client = LLMClient(base, "key", "instance-wrong-model", provider=provider)
    sent = []
    native_gemini = provider == "gemini" and "/openai" not in base

    def handler(request):
        sent.append(json.loads(request.content))
        if stream:
            if provider == "claude":
                data = {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "ok"},
                }
            elif native_gemini:
                data = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
            else:
                data = {"choices": [{"delta": {"content": "ok"}}]}
            return httpx.Response(
                200,
                text="data: " + json.dumps(data) + "\n\n",
                headers={"content-type": "text/event-stream"},
            )
        if provider == "claude":
            return httpx.Response(
                200, json={"content": [{"type": "text", "text": "ok"}]}
            )
        if native_gemini:
            return httpx.Response(
                200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
            )
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client._http = http
        if stream:
            socket = _Socket()
            await client.stream_chat(
                socket,
                Generation("gen", "session"),
                GenerationManager(),
                [{"role": "user", "content": "hi"}],
                model=model,
                reasoning_effort=effort,
                max_output_tokens=512,
            )
            assert not [event for event in socket.sent if event["type"] == "error"]
            assert socket.sent[-1]["content"] == "ok"
        else:
            result = await client.complete_chat(
                [{"role": "user", "content": "hi"}],
                model=model,
                reasoning_effort=effort,
                max_output_tokens=512,
            )
            assert result["reply"] == "ok"
    payload = sent[-1]
    if native_gemini:
        assert payload["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}
        assert payload["generationConfig"]["maxOutputTokens"] == 512
    elif provider == "claude":
        assert payload["thinking"] == {"type": "adaptive"}
        assert payload["output_config"] == {"effort": "high"}
        assert payload["max_tokens"] == 512
    else:
        assert payload["model"] == model
        if provider == "chatgpt":
            assert (
                payload["max_completion_tokens"] == 512 and "max_tokens" not in payload
            )
            assert payload["reasoning_effort"] == effort
            assert ("temperature" in payload) == (effort == "none")
        elif provider == "custom":
            assert payload["temperature"] == 0.4 and "reasoning_effort" not in payload
        elif provider == "gemini":
            assert (
                payload["reasoning_effort"] == "high"
                and "thinking_config" not in payload
            )
        else:
            assert "repeat_penalty" in payload and "repetition_penalty" not in payload


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_generation_compat_retries_still_remove_rejected_supported_fields(stream):
    client = LLMClient("https://example.test/v1", "key", "gpt-5.2", provider="chatgpt")
    sent = []

    def handler(request):
        payload = json.loads(request.content)
        sent.append(payload)
        if len(sent) == 1:
            return httpx.Response(
                400, json={"error": {"message": "Unsupported parameter 'temperature'"}}
            )
        if stream:
            return httpx.Response(
                200, text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
            )
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client._http = http
        kwargs = {"reasoning_effort": "none", "temperature": 0.6}
        if stream:
            socket = _Socket()
            await client.stream_chat(
                socket,
                Generation("g", "s"),
                GenerationManager(),
                [{"role": "user", "content": "hi"}],
                **kwargs,
            )
            assert socket.sent[-1]["content"] == "ok"
        else:
            assert (
                await client.complete_chat(
                    [{"role": "user", "content": "hi"}], **kwargs
                )
            )["reply"] == "ok"
    assert len(sent) == 2
    assert sent[0]["temperature"] == 0.6 and "temperature" not in sent[1]
    assert sent[1]["reasoning_effort"] == "none"
    assert "max_completion_tokens" in sent[1]


@pytest.mark.asyncio
async def test_empty_reasoning_retry_preserves_completion_token_wire_field():
    client = LLMClient("https://example.test/v1", "key", "o3", provider="chatgpt")
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        message = (
            {"reasoning_content": "thinking", "content": ""}
            if len(sent) == 1
            else {"content": "ok"}
        )
        return httpx.Response(
            200, json={"choices": [{"message": message, "finish_reason": "length"}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client._http = http
        assert (
            await client.complete_chat(
                [{"role": "user", "content": "hi"}], max_output_tokens=8
            )
        )["reply"] == "ok"
    assert len(sent) == 2
    assert sent[1]["max_completion_tokens"] == 256
    assert all("max_tokens" not in body for body in sent)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["rewrite", "score", "connection"])
async def test_internal_summary_and_connection_requests_are_filtered(operation):
    sent = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(500)
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"overall":90,"facts":90,"preferences":90,"goals_open_tasks":90}'
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        if operation == "rewrite":
            await llm_client._rewrite_summary_with_llm(
                http, "https://example.test/v1", {}, "o3", "summary", provider="chatgpt"
            )
        elif operation == "score":
            await llm_client._score_summary_with_llm(
                http, "https://example.test/v1", {}, "o3", "summary", provider="chatgpt"
            )
        else:
            client = LLMClient(
                "https://example.test/v1", "key", "o3", provider="chatgpt"
            )
            client._http = http
            assert (await client.test_connection())["ok"]
    assert "max_completion_tokens" in sent[-1]
    assert not {"max_tokens", "temperature", "reasoning_effort"}.intersection(sent[-1])


@pytest.mark.parametrize(
    "model",
    [
        "claude-3-7-sonnet-20250219",
        "claude-sonnet-4-20250514",
        "claude-opus-4-20250514",
        "claude-opus-4-1-20250805",
        "claude-sonnet-4-5",
    ],
)
@pytest.mark.parametrize(
    ("effort", "budget"), [("low", 1024), ("medium", 4096), ("high", 8192)]
)
def test_legacy_claude_manual_thinking_budget_and_sampling(model, effort, budget):
    payload = llm_client._messages_to_claude_payload(
        {
            "model": model,
            "reasoning_effort": effort,
            "max_tokens": 16000,
            "temperature": 0.4,
            "top_p": 0.8,
            "top_k": 20,
        }
    )
    assert payload["thinking"] == {"type": "enabled", "budget_tokens": budget}
    assert payload["top_k"] == 20
    assert not {
        "temperature",
        "top_p",
        "output_config",
        "reasoning_effort",
    }.intersection(payload)


@pytest.mark.parametrize("output_tokens", [100, 1024, 1025, 3000])
def test_legacy_claude_thinking_respects_output_budget(output_tokens):
    payload = llm_client._messages_to_claude_payload(
        {
            "model": "claude-sonnet-4-5",
            "reasoning_effort": "high",
            "max_tokens": output_tokens,
        }
    )
    if output_tokens <= 1024:
        assert "thinking" not in payload
    else:
        assert payload["thinking"] == {
            "type": "enabled",
            "budget_tokens": output_tokens - 1,
        }


@pytest.mark.parametrize(
    "model",
    [
        "claude-3-7-sonnet-20250219",
        "claude-sonnet-4-20250514",
        "claude-opus-4-20250514",
        "claude-opus-4-1-20250805",
        "claude-sonnet-4-5",
    ],
)
def test_legacy_claude_explicit_none_disables_thinking_and_allows_sampling(model):
    payload = llm_client._messages_to_claude_payload(
        {
            "model": model,
            "reasoning_effort": "none",
            "max_tokens": 1024,
            "temperature": 0.7,
            "top_p": 0.8,
        }
    )
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["temperature"] == 0.7 and payload["top_p"] == 0.8
    assert "output_config" not in payload


def test_legacy_claude_rules_do_not_guess_unverified_haiku_reasoning():
    assert (
        resolve_generation_capabilities("claude", "claude-haiku-4-5")[
            "reasoningEfforts"
        ]
        == []
    )


@pytest.mark.parametrize(
    "model", ["gpt-oss", "gpt-oss:20b", "gpt-oss:120b", "gpt-oss:latest"]
)
@pytest.mark.parametrize("effort", ["none", "low", "medium", "high"])
def test_ollama_openai_compatible_gpt_oss_effort(model, effort):
    body = {"model": model, "max_tokens": 2048}
    _apply_generation_options(body, provider="ollama", reasoning_effort=effort)
    assert body == {"model": model, "max_tokens": 2048, "reasoning_effort": effort}
    assert (
        "none"
        in resolve_generation_capabilities("ollama", model)["reasoningEfforts"]
    )


def test_ollama_model_aliases_do_not_guess_thinking_support():
    for model in ("custom-thinking-model", "gpt-oss:unverified-tag", "deepseek-r1:8b"):
        body = {"model": model}
        _apply_generation_options(
            body, provider="ollama", reasoning_effort="high", thinking="enabled"
        )
        assert body == {"model": model}


@pytest.mark.parametrize(
    "model",
    [
        "claude-opus-4-7",
        "claude-opus-4-8",
        "claude-opus-5",
        "claude-opus-5-5",
        "claude-sonnet-5",
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
    ],
)
@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max"])
def test_current_claude_families_adaptive_effort_and_no_ignored_sampling(model, effort):
    caps = resolve_generation_capabilities("claude", model)
    assert caps["reasoningEfforts"] == ["low", "medium", "high", "xhigh", "max"]
    assert caps["parameters"] == {}
    body = {
        "model": model,
        "max_tokens": 16384,
        "reasoning_effort": effort,
        **dict.fromkeys(NUMERIC_GENERATION_FIELDS, 0.5),
    }
    payload = llm_client._messages_to_claude_payload(body)
    assert payload["thinking"] == {"type": "adaptive"}
    assert payload["output_config"] == {"effort": effort}
    assert not set(NUMERIC_GENERATION_FIELDS).intersection(payload)


@pytest.mark.parametrize(
    "model",
    [
        "claude-opus-4-7",
        "claude-opus-4-8",
        "claude-opus-5",
        "claude-opus-5-5",
        "claude-sonnet-5",
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
    ],
)
def test_current_claude_families_do_not_emit_unsupported_none_or_force_defaults(model):
    payload = llm_client._messages_to_claude_payload(
        {"model": model, "reasoning_effort": "none"}
    )
    assert not {"thinking", "reasoning_effort", "output_config"}.intersection(payload)
