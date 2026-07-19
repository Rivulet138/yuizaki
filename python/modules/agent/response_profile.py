from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal


ResponseMode = Literal["instant", "balanced", "deep"]
ThinkingMode = Literal["enabled", "disabled"]
RESPONSE_MODES: tuple[ResponseMode, ...] = ("instant", "balanced", "deep")

_COMPLEXITY_MARKERS = (
    "分析", "比较", "评估", "规划", "计划", "实现", "修改", "调试", "测试",
    "文件", "代码", "风险", "步骤", "工具", "搜索", "浏览器", "终端",
    "research", "analyze", "compare", "evaluate", "plan", "implement",
    "modify", "debug", "test", "file", "code", "risk", "steps", "tool",
)


def normalize_response_mode(value: object) -> ResponseMode:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in RESPONSE_MODES else "balanced"


def _latest_user_text(messages: Sequence[Mapping[str, Any]]) -> str:
    for message in reversed(messages):
        if str(message.get("role") or "").strip().lower() != "user":
            continue
        content = message.get("content")
        return content.strip() if isinstance(content, str) else ""
    return ""


def _is_deepseek(model_hint: str | None, provider_hint: str | None) -> bool:
    return "deepseek" in f"{provider_hint or ''} {model_hint or ''}".lower()


def _requires_deep_reasoning(
    *,
    response_mode: ResponseMode,
    prompt_mode: str | None,
    mcp_enabled: bool | None,
    web_search_enabled: bool | None,
    user_text: str,
) -> bool:
    return (
        response_mode == "deep"
        or prompt_mode == "work"
        or bool(mcp_enabled)
        or bool(web_search_enabled)
        or any(marker in user_text.lower() for marker in _COMPLEXITY_MARKERS)
    )


def _is_simple_daily_turn(*, prompt_mode: str | None, user_text: str) -> bool:
    return (
        prompt_mode in {None, "", "auto", "daily"}
        and 0 < len(user_text) <= 80
        and not any(marker in user_text.lower() for marker in _COMPLEXITY_MARKERS)
    )


def resolve_thinking_mode(
    requested: str | None,
    *,
    response_mode: ResponseMode,
    prompt_mode: str | None,
    mcp_enabled: bool | None,
    web_search_enabled: bool | None,
    messages: Sequence[Mapping[str, Any]],
    model_hint: str | None = None,
    provider_hint: str | None = None,
) -> ThinkingMode | None:
    """Resolve the DeepSeek thinking switch while leaving other providers untouched."""
    if not _is_deepseek(model_hint, provider_hint):
        return None

    normalized_requested = str(requested or "").strip().lower()
    if normalized_requested == "none":
        return "disabled"
    if normalized_requested not in {"", "default"}:
        return "enabled"

    user_text = _latest_user_text(messages)
    if _requires_deep_reasoning(
        response_mode=response_mode,
        prompt_mode=prompt_mode,
        mcp_enabled=mcp_enabled,
        web_search_enabled=web_search_enabled,
        user_text=user_text,
    ):
        return "enabled"
    return None


def resolve_reasoning_effort(
    requested: str | None,
    *,
    response_mode: ResponseMode,
    prompt_mode: str | None,
    mcp_enabled: bool | None,
    web_search_enabled: bool | None,
    messages: Sequence[Mapping[str, Any]],
    model_hint: str | None = None,
    provider_hint: str | None = None,
) -> str | None:
    """Choose a conservative effort without overriding explicit user choices."""
    normalized_requested = str(requested or "").strip().lower()
    if normalized_requested not in {"", "default"}:
        if normalized_requested == "none":
            return None
        if _is_deepseek(model_hint, provider_hint):
            if normalized_requested in {"xhigh", "max"}:
                return "max"
            if normalized_requested == "auto":
                return None
            return "high"
        return normalized_requested

    user_text = _latest_user_text(messages)
    if _requires_deep_reasoning(
        response_mode=response_mode,
        prompt_mode=prompt_mode,
        mcp_enabled=mcp_enabled,
        web_search_enabled=web_search_enabled,
        user_text=user_text,
    ):
        if _is_deepseek(model_hint, provider_hint) and response_mode == "deep":
            return "max"
        return "high"
    if response_mode == "instant":
        return None if _is_deepseek(model_hint, provider_hint) else "low"

    if _is_simple_daily_turn(prompt_mode=prompt_mode, user_text=user_text):
        return None if _is_deepseek(model_hint, provider_hint) else "low"
    return None
