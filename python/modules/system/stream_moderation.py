"""Local, deterministic moderation policy for outbound stream chat.

The policy is deliberately conservative: it only inspects the text supplied
for an explicit preview/execute request, never stores that text, and returns a
bounded reason that the UI can explain to the operator.
"""

from __future__ import annotations

import math
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

SCHEMA_VERSION = "yuizaki.stream-moderation.v1"
MAX_BLOCKED_TERMS = 64
MAX_BLOCKED_TERM_LENGTH = 80
MAX_SLOW_MODE_SECONDS = 3_600.0
MAX_MESSAGES_PER_MINUTE = 600
DEFAULT_MAX_MESSAGES_PER_MINUTE = 30


def _finite_number(value: object, *, name: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be a number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _normalize_terms(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise TypeError("blockedTerms must be an array")
    terms: list[str] = []
    for raw in value:
        if not isinstance(raw, str):
            raise TypeError("blockedTerms entries must be strings")
        term = raw.strip()
        if not term:
            continue
        if len(term) > MAX_BLOCKED_TERM_LENGTH:
            raise ValueError(f"blockedTerms entries must be {MAX_BLOCKED_TERM_LENGTH} characters or less")
        folded = term.casefold()
        if folded not in terms:
            terms.append(folded)
        if len(terms) > MAX_BLOCKED_TERMS:
            raise ValueError(f"blockedTerms must contain {MAX_BLOCKED_TERMS} terms or less")
    return tuple(terms)


@dataclass(frozen=True)
class StreamModerationDecision:
    allowed: bool
    reason_code: str
    retry_after_seconds: float | None = None
    matched_term_count: int = 0

    def snapshot(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "reasonCode": self.reason_code,
            "retryAfterSeconds": self.retry_after_seconds,
            "matchedTermCount": self.matched_term_count,
        }

    def error_message(self) -> str:
        if self.reason_code == "blocked_term":
            return "直播消息命中本地敏感词策略"
        if self.reason_code == "slow_mode":
            return f"直播慢模式生效，请等待 {self.retry_after_seconds or 0:.1f} 秒"
        if self.reason_code == "rate_limit":
            return f"直播发送频率已达上限，请等待 {self.retry_after_seconds or 0:.1f} 秒"
        if self.reason_code == "empty_text":
            return "直播消息不能为空"
        return "直播消息未通过内容治理"


class StreamModerationPolicy:
    """Immutable policy object used by the runtime under its own lock."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        blocked_terms: Iterable[str] = (),
        slow_mode_seconds: float = 0.0,
        max_messages_per_minute: int = DEFAULT_MAX_MESSAGES_PER_MINUTE,
    ) -> None:
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a boolean")
        terms = _normalize_terms(blocked_terms)
        slow = _finite_number(slow_mode_seconds, name="slowModeSeconds")
        if slow < 0 or slow > MAX_SLOW_MODE_SECONDS:
            raise ValueError(f"slowModeSeconds must be between 0 and {int(MAX_SLOW_MODE_SECONDS)}")
        if isinstance(max_messages_per_minute, bool) or not isinstance(max_messages_per_minute, int):
            raise TypeError("maxMessagesPerMinute must be an integer")
        if not 1 <= max_messages_per_minute <= MAX_MESSAGES_PER_MINUTE:
            raise ValueError(f"maxMessagesPerMinute must be between 1 and {MAX_MESSAGES_PER_MINUTE}")
        self.enabled = enabled
        self.blocked_terms = terms
        self.slow_mode_seconds = slow
        self.max_messages_per_minute = max_messages_per_minute

    @classmethod
    def from_mapping(cls, value: Mapping[str, object] | None) -> StreamModerationPolicy:
        payload = dict(value or {})
        return cls(
            enabled=payload.get("enabled", True),
            blocked_terms=payload.get("blockedTerms", payload.get("blocked_terms", ())),
            slow_mode_seconds=payload.get("slowModeSeconds", payload.get("slow_mode_seconds", 0.0)),
            max_messages_per_minute=payload.get(
                "maxMessagesPerMinute",
                payload.get("max_messages_per_minute", DEFAULT_MAX_MESSAGES_PER_MINUTE),
            ),
        )

    def with_patch(self, value: Mapping[str, object]) -> StreamModerationPolicy:
        unknown = set(value) - {"enabled", "blockedTerms", "slowModeSeconds", "maxMessagesPerMinute"}
        if unknown:
            raise ValueError(f"unknown moderation fields: {', '.join(sorted(str(item) for item in unknown))}")
        return StreamModerationPolicy(
            enabled=value.get("enabled", self.enabled),
            blocked_terms=value.get("blockedTerms", self.blocked_terms),
            slow_mode_seconds=value.get("slowModeSeconds", self.slow_mode_seconds),
            max_messages_per_minute=value.get("maxMessagesPerMinute", self.max_messages_per_minute),
        )

    def snapshot(self) -> dict[str, object]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "enabled": self.enabled,
            "blockedTerms": list(self.blocked_terms),
            "slowModeSeconds": self.slow_mode_seconds,
            "maxMessagesPerMinute": self.max_messages_per_minute,
        }

    def evaluate(
        self,
        text: str,
        sent_at: Iterable[float] = (),
        *,
        now: float | None = None,
    ) -> StreamModerationDecision:
        normalized = str(text or "").strip()
        if not normalized:
            return StreamModerationDecision(False, "empty_text")
        if not self.enabled:
            return StreamModerationDecision(True, "disabled")
        folded = normalized.casefold()
        matched = sum(1 for term in self.blocked_terms if term in folded)
        if matched:
            return StreamModerationDecision(False, "blocked_term", matched_term_count=matched)

        current = time.time() if now is None else _finite_number(now, name="now")
        timestamps = sorted(
            timestamp for timestamp in sent_at
            if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool) and math.isfinite(float(timestamp))
        )
        if timestamps and self.slow_mode_seconds > 0:
            retry_after = self.slow_mode_seconds - (current - timestamps[-1])
            if retry_after > 0:
                return StreamModerationDecision(False, "slow_mode", retry_after_seconds=round(retry_after, 2))
        window_start = current - 60.0
        recent = [timestamp for timestamp in timestamps if timestamp >= window_start]
        if len(recent) >= self.max_messages_per_minute:
            retry_after = max(0.01, recent[0] + 60.0 - current)
            return StreamModerationDecision(False, "rate_limit", retry_after_seconds=round(retry_after, 2))
        return StreamModerationDecision(True, "allowed")


__all__ = [
    "DEFAULT_MAX_MESSAGES_PER_MINUTE",
    "SCHEMA_VERSION",
    "StreamModerationDecision",
    "StreamModerationPolicy",
]
