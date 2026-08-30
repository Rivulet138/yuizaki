from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from typing import Any

SENSITIVE_MARKERS = (
    "密码", "口令", "token", "api key", "apikey", "密钥", "身份证",
    "银行卡", "信用卡", "摄像头", "屏幕截图", "录屏",
)
_ALLOWED_INTENTS = {"chat", "task", "reflect", "schedule", "unknown"}
_ALLOWED_SENSITIVITY = {"normal", "high"}
_EVIDENCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")


@dataclass(frozen=True)
class InterpretResult:
    intent: str
    urgency: str
    emotional_signal: bool
    tool_hint: bool
    raw_text: str

    def to_envelope(
        self,
        *,
        evidence_ids: list[str] | None = None,
        confirmation_required: bool = False,
        now: float | None = None,
    ) -> IntentEnvelope:
        """Expose bounded planning metadata without changing the user prompt."""
        normalized = self.raw_text.strip()
        lowered = normalized.lower()
        sensitivity = "high" if any(marker in lowered for marker in SENSITIVE_MARKERS) else "normal"
        confidence_by_intent = {
            "schedule": 0.95,
            "task": 0.9,
            "reflect": 0.82,
            "chat": 0.7,
            "unknown": 0.2,
        }
        ttl_seconds = 300.0 if self.urgency == "immediate" else 86400.0
        timestamp = time.time() if now is None else float(now)
        return IntentEnvelope(
            intent_type=self.intent,
            normalized_goal=normalized,
            confidence=confidence_by_intent.get(self.intent, 0.4),
            evidence_ids=list(evidence_ids or ["user_text"]),
            requires_confirmation=bool(confirmation_required or sensitivity == "high"),
            sensitivity=sensitivity,
            expires_at=timestamp + ttl_seconds,
        )


@dataclass(frozen=True)
class IntentEnvelope:
    """Stable, inspectable intent contract shared by planning and policy."""

    intent_type: str
    normalized_goal: str
    confidence: float
    evidence_ids: list[str]
    requires_confirmation: bool
    sensitivity: str
    expires_at: float

    def __post_init__(self) -> None:
        """Reject malformed planning metadata before it reaches a trace/store."""
        if self.intent_type not in _ALLOWED_INTENTS:
            raise ValueError("intent_type is not supported")
        if not isinstance(self.normalized_goal, str) or len(self.normalized_goal) > 2000:
            raise ValueError("normalized_goal must be a string of at most 2000 characters")
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not math.isfinite(float(self.confidence))
            or not 0.0 <= float(self.confidence) <= 1.0
        ):
            raise ValueError("confidence must be finite and between 0 and 1")
        if not isinstance(self.evidence_ids, (list, tuple)) or len(self.evidence_ids) > 16:
            raise ValueError("evidence_ids must contain at most 16 identifiers")
        normalized_ids: list[str] = []
        for evidence_id in self.evidence_ids:
            if not isinstance(evidence_id, str) or not _EVIDENCE_ID.fullmatch(evidence_id):
                raise ValueError("evidence_ids must contain safe identifiers")
            normalized_ids.append(evidence_id)
        object.__setattr__(self, "evidence_ids", normalized_ids)
        if not isinstance(self.requires_confirmation, bool):
            raise ValueError("requires_confirmation must be boolean")
        if self.sensitivity not in _ALLOWED_SENSITIVITY:
            raise ValueError("sensitivity must be normal or high")
        if (
            isinstance(self.expires_at, bool)
            or not isinstance(self.expires_at, (int, float))
            or not math.isfinite(float(self.expires_at))
        ):
            raise ValueError("expires_at must be finite")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": "yuizaki.intent-envelope.v1",
            "intentType": self.intent_type,
            "normalizedGoal": self.normalized_goal,
            "confidence": self.confidence,
            "evidenceIds": list(self.evidence_ids),
            "requiresConfirmation": self.requires_confirmation,
            "sensitivity": self.sensitivity,
            "expiresAt": self.expires_at,
        }


def interpret_user_text(text: str) -> InterpretResult:
    normalized = (text or "").strip()
    lowered = normalized.lower()
    tool_hint = any(keyword in normalized for keyword in ["打开网页", "打开网址", "打开链接", "打开 ", "读文件", "读取文件", "写文件", "http://", "https://"])
    # Sensitive resource requests are tasks even when they omit an explicit
    # action verb; this keeps confirmation policy explainable and testable.
    tool_hint = tool_hint or any(marker in lowered for marker in SENSITIVE_MARKERS)
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
