"""Deterministic, replayable evaluation contract for intent interpretation.

The evaluator consumes redacted golden cases rather than model traces.  It is
deliberately separate from policy/authorization: a passing interpretation
case never grants permission to execute an action.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .interpret import IntentEnvelope, interpret_user_text

SCHEMA_VERSION = "yuizaki.intent-evaluation.v1"
_ALLOWED_SENSITIVITY = {"normal", "high"}
_ALLOWED_INTENTS = {"chat", "task", "reflect", "schedule", "unknown"}


@dataclass(frozen=True)
class IntentEvaluationResult:
    case_id: str
    passed: bool
    expected_intent: str
    observed_intent: str
    expected_sensitivity: str
    observed_sensitivity: str
    confidence: float
    confidence_ok: bool
    confirmation_ok: bool
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "caseId": self.case_id,
            "passed": self.passed,
            "expectedIntent": self.expected_intent,
            "observedIntent": self.observed_intent,
            "expectedSensitivity": self.expected_sensitivity,
            "observedSensitivity": self.observed_sensitivity,
            "confidence": self.confidence,
            "confidenceOk": self.confidence_ok,
            "confirmationOk": self.confirmation_ok,
            "errors": list(self.errors),
        }


def evaluate_intent_case(
    case: Mapping[str, Any], *, now: float = 0.0
) -> IntentEvaluationResult:
    """Replay one golden case and report every contract mismatch."""
    if not isinstance(case, Mapping):
        raise TypeError("intent evaluation case must be an object")
    if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(float(now)):
        raise ValueError("now must be a finite number")
    case_id = str(case.get("case_id") or case.get("caseId") or "").strip()
    if not case_id:
        raise ValueError("intent evaluation case requires case_id")
    text = str(case.get("text") or "")
    expected_intent = str(case.get("expected_intent") or case.get("expectedIntent") or "")
    if expected_intent not in _ALLOWED_INTENTS:
        raise ValueError("expected_intent is not supported")
    expected_sensitivity = str(
        case.get("expected_sensitivity") or case.get("expectedSensitivity") or "normal"
    )
    if expected_sensitivity not in _ALLOWED_SENSITIVITY:
        raise ValueError("expected_sensitivity must be normal or high")
    confirmation_value = (
        case.get("expected_confirmation")
        if "expected_confirmation" in case
        else case.get("expectedConfirmation", expected_sensitivity == "high")
    )
    if not isinstance(confirmation_value, bool):
        raise TypeError("expected_confirmation must be boolean")
    expected_confirmation = confirmation_value
    minimum_value = case.get("minimum_confidence", case.get("minimumConfidence", 0.0))
    if isinstance(minimum_value, bool) or not isinstance(minimum_value, (int, float)) or not math.isfinite(float(minimum_value)):
        raise ValueError("minimum_confidence must be finite")
    minimum_confidence = float(minimum_value)
    maximum_confidence = case.get("maximum_confidence", case.get("maximumConfidence"))
    if maximum_confidence is None:
        maximum = None
    else:
        if isinstance(maximum_confidence, bool) or not isinstance(maximum_confidence, (int, float)) or not math.isfinite(float(maximum_confidence)):
            raise ValueError("maximum_confidence must be finite")
        maximum = float(maximum_confidence)
    if not 0.0 <= minimum_confidence <= 1.0 or (maximum is not None and not 0.0 <= maximum <= 1.0):
        raise ValueError("confidence bounds must be between 0 and 1")
    if maximum is not None and minimum_confidence > maximum:
        raise ValueError("minimum_confidence cannot exceed maximum_confidence")
    result = interpret_user_text(text)
    envelope: IntentEnvelope = result.to_envelope(now=now)
    errors: list[str] = []
    if envelope.intent_type != expected_intent:
        errors.append("intent_mismatch")
    if envelope.sensitivity != expected_sensitivity:
        errors.append("sensitivity_mismatch")
    confidence_ok = envelope.confidence >= minimum_confidence and (
        maximum is None or envelope.confidence <= maximum
    )
    if not confidence_ok:
        errors.append("confidence_out_of_range")
    confirmation_ok = envelope.requires_confirmation is expected_confirmation
    if not confirmation_ok:
        errors.append("confirmation_mismatch")
    return IntentEvaluationResult(
        case_id=case_id,
        passed=not errors,
        expected_intent=expected_intent,
        observed_intent=envelope.intent_type,
        expected_sensitivity=expected_sensitivity,
        observed_sensitivity=envelope.sensitivity,
        confidence=envelope.confidence,
        confidence_ok=confidence_ok,
        confirmation_ok=confirmation_ok,
        errors=tuple(errors),
    )


def load_golden_cases(path: str | Path) -> list[dict[str, Any]]:
    """Load and validate a bounded JSON fixture for CI/replay use."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list) or len(raw) > 500:
        raise ValueError("intent golden fixture must be a list of at most 500 cases")
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise TypeError("intent golden fixture entries must be objects")
        case = dict(item)
        case_id = str(case.get("case_id") or case.get("caseId") or "").strip()
        if not case_id or case_id in seen:
            raise ValueError("intent golden fixture case ids must be unique")
        seen.add(case_id)
        cases.append(case)
    return cases


def summarize_intent_results(results: Iterable[IntentEvaluationResult]) -> dict[str, Any]:
    """Build bounded aggregate metrics for CI and longitudinal evaluation."""
    rows = list(results)
    if len(rows) > 500:
        raise ValueError("intent evaluation results are limited to 500 rows")
    for row in rows:
        if not isinstance(row, IntentEvaluationResult):
            raise TypeError("intent evaluation results must use IntentEvaluationResult")
        if not math.isfinite(float(row.confidence)) or not 0.0 <= float(row.confidence) <= 1.0:
            raise ValueError("intent evaluation confidence must be between 0 and 1")
    total = len(rows)
    if total == 0:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "total": 0,
            "passed": 0,
            "passRate": 0.0,
            "intentAccuracy": 0.0,
            "sensitivityAccuracy": 0.0,
            "confirmationAccuracy": 0.0,
            "meanConfidence": 0.0,
        }
    intent_matches = sum(item.expected_intent == item.observed_intent for item in rows)
    sensitivity_matches = sum(item.expected_sensitivity == item.observed_sensitivity for item in rows)
    confirmation_matches = sum(item.confirmation_ok for item in rows)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "total": total,
        "passed": sum(item.passed for item in rows),
        "passRate": round(sum(item.passed for item in rows) / total, 4),
        "intentAccuracy": round(intent_matches / total, 4),
        "sensitivityAccuracy": round(sensitivity_matches / total, 4),
        "confirmationAccuracy": round(confirmation_matches / total, 4),
        "meanConfidence": round(sum(item.confidence for item in rows) / total, 4),
    }


__all__ = [
    "SCHEMA_VERSION",
    "IntentEvaluationResult",
    "evaluate_intent_case",
    "load_golden_cases",
    "summarize_intent_results",
]
