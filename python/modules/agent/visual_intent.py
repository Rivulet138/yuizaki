from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

_VISUAL_QUERY_PHRASES = (
    "你看到",
    "看一下这个",
    "看看这个",
    "what do you see",
    "look at this",
)
_CHINESE_VISUAL_REQUEST = re.compile(
    r"(?:(?:请|帮我|你能)?(?:看|看看|看一下|查看|检查|识别|读取|分析|描述)"
    r".{0,12}(?:屏幕|画面|窗口|桌面|显示器|截图|这个页面))|"
    r"(?:(?:屏幕|画面|窗口|桌面|显示器|截图|页面)(?:上|里|中|现在)"
    r".{0,10}(?:有什么|是什么|显示什么|怎么了))"
)
_ENGLISH_VISUAL_REQUEST = re.compile(
    r"\b(?:(?:look at|check|inspect|read|analy[sz]e|describe)"
    r".{0,48}(?:screen|desktop|window|screenshot|page)|"
    r"(?:can|could) you see.{0,32}(?:screen|desktop|window|screenshot|page)|"
    r"what changed.{0,24}(?:screen|desktop|window|screenshot|page)|"
    r"(?:what(?:'s| is)|tell me what(?:'s| is))\s+(?:currently\s+)?on\s+"
    r"(?:my|the|this)\s+(?:screen|desktop|window|screenshot|page))\b"
)


@dataclass(frozen=True)
class VisualContextDecision:
    requested: bool
    confidence: float
    reason: str
    confirmation_required: bool = False


def normalize_query(value: str) -> str:
    return " ".join((value or "").lower().split())


def query_matches_partial(
    partial_query: str,
    final_query: str,
    *,
    min_coverage: float = 0.55,
) -> bool:
    partial = normalize_query(partial_query)
    final = normalize_query(final_query)
    if not partial or not final:
        return False
    coverage = len(partial) / max(1, len(final))
    similarity = SequenceMatcher(None, partial, final).ratio()
    return coverage >= min_coverage and (final.startswith(partial) or similarity >= 0.82)


def classify_visual_context_request(query: str) -> VisualContextDecision:
    normalized = normalize_query(query)
    if not normalized:
        return VisualContextDecision(False, 0.0, "empty_query")
    if _CHINESE_VISUAL_REQUEST.search(normalized):
        return VisualContextDecision(True, 0.98, "explicit_chinese_screen_request")
    if _ENGLISH_VISUAL_REQUEST.search(normalized):
        return VisualContextDecision(True, 0.98, "explicit_english_screen_request")

    matched_phrase = next(
        (phrase for phrase in _VISUAL_QUERY_PHRASES if phrase in normalized),
        None,
    )
    if matched_phrase is not None:
        return VisualContextDecision(
            False,
            0.62,
            f"ambiguous_deictic_request:{matched_phrase}",
            confirmation_required=True,
        )
    return VisualContextDecision(False, 0.05, "no_visual_request_signal")


def visual_context_requested(query: str) -> bool:
    return classify_visual_context_request(query).requested
