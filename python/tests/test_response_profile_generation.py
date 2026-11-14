from modules.agent.response_profile import (
    resolve_reasoning_effort,
    resolve_thinking_mode,
)


def test_explicit_no_reasoning_survives_profile_resolution():
    options = {
        "response_mode": "deep",
        "prompt_mode": "work",
        "mcp_enabled": True,
        "web_search_enabled": True,
        "messages": [{"role": "user", "content": "analyze this"}],
    }
    assert (
        resolve_reasoning_effort(
            "none", provider_hint="chatgpt", model_hint="gpt-5.2", **options
        )
        == "none"
    )
    assert (
        resolve_reasoning_effort(
            "none", provider_hint="qwen", model_hint="qwen3-32b", **options
        )
        == "none"
    )
    assert (
        resolve_reasoning_effort(
            "none", provider_hint="deepseek", model_hint="deepseek-flash", **options
        )
        is None
    )
    assert (
        resolve_thinking_mode(
            "none", provider_hint="deepseek", model_hint="deepseek-flash", **options
        )
        == "disabled"
    )


def test_deepseek_canonical_efforts_survive_profile_resolution():
    options = {
        "response_mode": "balanced",
        "prompt_mode": "daily",
        "mcp_enabled": False,
        "web_search_enabled": False,
        "messages": [{"role": "user", "content": "hi"}],
        "provider_hint": "deepseek",
        "model_hint": "deepseek-flash",
    }
    for effort in ("low", "high", "max"):
        assert resolve_reasoning_effort(effort, **options) == effort
    assert resolve_reasoning_effort("minimal", **options) == "low"
    assert resolve_reasoning_effort("xhigh", **options) == "high"
