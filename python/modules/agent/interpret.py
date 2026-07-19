from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InterpretResult:
    intent: str
    urgency: str
    emotional_signal: bool
    tool_hint: bool
    raw_text: str


def interpret_user_text(text: str) -> InterpretResult:
    normalized = (text or "").strip()
    lowered = normalized.lower()
    tool_hint = any(keyword in normalized for keyword in ["打开网页", "打开网址", "打开链接", "打开 ", "读文件", "读取文件", "写文件", "http://", "https://"])
    emotional_signal = any(keyword in lowered for keyword in ["谢谢", "thank", "thanks", "难过", "开心", "累", "害怕", "喜欢", "安慰我", "陪陪我"])
    has_schedule = any(keyword in normalized for keyword in ["每隔", "秒后", "分钟后", "分后", "小时后"])
    urgency = "deferred" if has_schedule else "immediate"
    if has_schedule:
        intent = "schedule"
    elif tool_hint:
        intent = "task"
    elif emotional_signal:
        intent = "reflect"
    elif normalized:
        intent = "chat"
    else:
        intent = "unknown"
    return InterpretResult(
        intent=intent,
        urgency=urgency,
        emotional_signal=emotional_signal,
        tool_hint=tool_hint,
        raw_text=normalized,
    )
