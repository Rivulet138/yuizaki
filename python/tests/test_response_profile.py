from modules.agent.response_profile import (
    normalize_response_mode,
    resolve_reasoning_effort,
    resolve_thinking_mode,
)


def test_response_mode_normalization_defaults_to_balanced() -> None:
    assert normalize_response_mode("instant") == "instant"
    assert normalize_response_mode("deep") == "deep"
    assert normalize_response_mode("unknown") == "balanced"


def test_explicit_reasoning_is_preserved_and_deepseek_effort_is_normalized() -> None:
    messages = [{"role": "user", "content": "你好"}]
    assert resolve_reasoning_effort(
        "medium", response_mode="instant", prompt_mode="daily",
        mcp_enabled=False, web_search_enabled=False, messages=messages,
    ) == "medium"
    assert resolve_reasoning_effort(
        "medium", response_mode="instant", prompt_mode="daily",
        mcp_enabled=False, web_search_enabled=False, messages=messages,
        model_hint="deepseek-v4-flash",
    ) == "high"


def test_automatic_reasoning_matches_latency_and_task_risk() -> None:
    simple = [{"role": "user", "content": "今天过得怎么样？"}]
    complex_turn = [{"role": "user", "content": "请分析并测试这个实现"}]

    assert resolve_reasoning_effort(
        "default", response_mode="instant", prompt_mode="daily",
        mcp_enabled=False, web_search_enabled=False, messages=simple,
    ) == "low"
    assert resolve_reasoning_effort(
        "default", response_mode="balanced", prompt_mode="work",
        mcp_enabled=False, web_search_enabled=False, messages=complex_turn,
    ) == "high"
    assert resolve_reasoning_effort(
        "default", response_mode="deep", prompt_mode="daily",
        mcp_enabled=False, web_search_enabled=False, messages=simple,
    ) == "high"


def test_deepseek_thinking_switch_follows_scene_and_explicit_choice() -> None:
    simple = [{"role": "user", "content": "你还记得我喜欢喝什么吗？"}]
    complex_turn = [{"role": "user", "content": "请分析这些文件并评估风险"}]
    common = {
        "prompt_mode": "daily",
        "mcp_enabled": False,
        "web_search_enabled": False,
        "model_hint": "deepseek-v4-flash",
    }

    assert resolve_thinking_mode("default", response_mode="instant", messages=simple, **common) is None
    assert resolve_thinking_mode("default", response_mode="balanced", messages=simple, **common) is None
    assert resolve_thinking_mode("default", response_mode="balanced", messages=complex_turn, **common) == "enabled"
    assert resolve_thinking_mode("default", response_mode="deep", messages=simple, **common) == "enabled"
    assert resolve_thinking_mode("none", response_mode="deep", messages=complex_turn, **common) == "disabled"
    assert resolve_thinking_mode("high", response_mode="instant", messages=simple, **common) == "enabled"
    assert resolve_thinking_mode(
        "default", response_mode="instant", prompt_mode="daily",
        mcp_enabled=False, web_search_enabled=False, messages=simple,
        model_hint="gpt-5",
    ) is None

    assert resolve_reasoning_effort(
        "default", response_mode="instant", messages=simple, **common,
    ) is None
    assert resolve_reasoning_effort(
        "default", response_mode="deep", messages=complex_turn, **common,
    ) == "max"
