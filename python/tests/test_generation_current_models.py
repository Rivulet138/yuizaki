import pytest

from modules.llm.generation_parameters import (
    filter_generation_parameters,
    resolve_generation_capabilities,
)


@pytest.mark.parametrize(
    "model",
    ["gpt-5.4", "gpt-5.5", "gpt-5.6", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"],
)
@pytest.mark.parametrize("effort", ["high", "none"])
def test_current_openai_models_match_their_reasoning_and_sampling(model, effort):
    body = {
        "model": model,
        "temperature": 0.7,
        "top_p": 0.9,
        "frequency_penalty": 0.2,
        "reasoning_effort": effort,
        "max_tokens": 100,
    }
    filter_generation_parameters(body, "chatgpt")
    assert body["reasoning_effort"] == effort
    assert ("temperature" in body) == (effort == "none")
    assert ("top_p" in body) == (effort == "none")
    assert "frequency_penalty" not in body
    assert body["max_completion_tokens"] == 100
    assert "max_tokens" not in body


@pytest.mark.parametrize(
    "model",
    [
        "gpt-5.6-sol",
        "gpt-6-astra",
        "gpt-6-sol",
        "gpt-6-luna",
        "gpt-6.1-sol",
        "gpt-6.1-terra",
    ],
)
def test_documented_models_preserve_max_effort(model):
    body = {"model": model, "reasoning_effort": "max", "temperature": 1}
    filter_generation_parameters(body, "chatgpt")
    assert body["reasoning_effort"] == "max"
    assert "temperature" not in body


@pytest.mark.parametrize("effort", ["none", "low", "medium", "high"])
def test_ollama_gpt_oss_uses_only_its_compatible_effort_enum(effort):
    body = {"model": "gpt-oss:20b", "reasoning_effort": effort, "temperature": 0.7}
    filter_generation_parameters(body, "ollama")
    assert body["reasoning_effort"] == effort
    assert body["temperature"] == 0.7
    assert (
        resolve_generation_capabilities("ollama", "unknown-local-model")[
            "reasoningEfforts"
        ]
        == []
    )
