"""Deterministic replay evaluation for proactive opportunity policy.

The evaluator rebuilds a small, temporary SQLite state from redacted cases and
then calls the same policy authority used at runtime.  It never invokes an
LLM, scheduler, connector, or external provider, so a passing case is evidence
only about policy behavior and cannot authorize a proactive contact.
"""

from __future__ import annotations

import json
import math
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .activity_frames import (
    POLICY_VERSION,
    PROJECTION_VERSION,
    SOURCE_KIND,
    ActivityFrame,
    ActivityFrameService,
    ActivityFrameStore,
)

SCHEMA_VERSION = "yuizaki.proactive-evaluation.v1"
MAX_CASES = 500
MAX_HISTORY_ROWS = 100
_FEEDBACK_KINDS = {
    "accepted",
    "ignored",
    "cancelled",
    "snoozed",
    "not_useful",
    "too_frequent",
    "wrong_time",
    "never_source",
}


def _value(case: Mapping[str, Any], snake: str, camel: str, default: Any = None) -> Any:
    return case[snake] if snake in case else case.get(camel, default)


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _bounded_text(value: Any, field: str, *, default: str, limit: int = 160) -> str:
    result = str(value if value is not None else default).strip()
    if not result or len(result) > limit:
        raise ValueError(f"{field} must be a non-empty string of at most {limit} characters")
    return result


def _local_date(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()


def _frame(
    *,
    workspace_id: str,
    frame_id: str,
    source_id: str,
    source_kind: str,
    source_created_at: float,
    expires_at: float,
    category: str,
) -> ActivityFrame:
    return ActivityFrame(
        frame_id=frame_id,
        workspace_id=workspace_id,
        session_id="proactive-evaluation-session",
        source_kind=source_kind,
        source_id=source_id,
        source_event_id=f"evaluation-event-{source_id}",
        source_created_at=source_created_at,
        created_at=source_created_at,
        expires_at=expires_at,
        projection_version=PROJECTION_VERSION,
        policy_version=POLICY_VERSION,
        signals={"activityCategory": category},
    )


@dataclass(frozen=True)
class ProactiveEvaluationResult:
    case_id: str
    passed: bool
    expected_allowed: bool
    observed_allowed: bool
    expected_reason: str
    observed_reason: str
    remaining_budget: int
    remaining_category_budget: int
    preference_score: float
    errors: tuple[str, ...]
    expected_remaining_budget: int | None = None
    expected_remaining_category_budget: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "caseId": self.case_id,
            "passed": self.passed,
            "expectedAllowed": self.expected_allowed,
            "observedAllowed": self.observed_allowed,
            "expectedReason": self.expected_reason,
            "observedReason": self.observed_reason,
            "remainingBudget": self.remaining_budget,
            "remainingCategoryBudget": self.remaining_category_budget,
            "preferenceScore": self.preference_score,
            "errors": list(self.errors),
        }
        if self.expected_remaining_budget is not None:
            payload["expectedRemainingBudget"] = self.expected_remaining_budget
        if self.expected_remaining_category_budget is not None:
            payload["expectedRemainingCategoryBudget"] = self.expected_remaining_category_budget
        return payload


def _seed_opportunity(
    store: ActivityFrameStore,
    *,
    workspace_id: str,
    frame: ActivityFrame,
    job_id: str,
    request_id: str,
    now: float,
    outcome: str | None = None,
) -> None:
    if not store.upsert_frame(frame):
        raise ValueError(f"history frame could not be inserted: {frame.frame_id}")
    if not store.reserve_opportunity(
        workspace_id,
        job_id=job_id,
        request_id=request_id,
        frame_id=frame.frame_id,
        source_kind=frame.source_kind,
        local_date=_local_date(now),
        expires_at=frame.expires_at,
        now=now,
    ):
        raise ValueError(f"history opportunity could not be reserved: {job_id}")
    if outcome is not None and not store.resolve_opportunity(
        workspace_id=workspace_id,
        job_id=job_id,
        request_id=request_id,
        source_kind=frame.source_kind,
        outcome=outcome,
        now=now,
    ):
        raise ValueError(f"history opportunity could not be resolved: {job_id}")


def _seed_history(
    store: ActivityFrameStore,
    *,
    workspace_id: str,
    source_kind: str,
    category: str,
    now: float,
    history: Mapping[str, Any],
) -> None:
    delivered = history.get("delivered", [])
    pending = history.get("pending", [])
    feedback = history.get("feedback", [])
    for name, rows in (("delivered", delivered), ("pending", pending), ("feedback", feedback)):
        if not isinstance(rows, list) or len(rows) > MAX_HISTORY_ROWS:
            raise ValueError(f"history.{name} must be a list of at most {MAX_HISTORY_ROWS} rows")

    for index, raw in enumerate(delivered):
        if not isinstance(raw, Mapping):
            raise TypeError("history.delivered rows must be objects")
        at = _finite_number(_value(raw, "at", "at", now), f"history.delivered[{index}].at")
        row_source_kind = _bounded_text(
            _value(raw, "source_kind", "sourceKind", source_kind),
            f"history.delivered[{index}].sourceKind",
            default=source_kind,
        )
        row_category = _bounded_text(
            _value(raw, "category", "activityCategory", category),
            f"history.delivered[{index}].category",
            default=category,
        )
        frame_id = f"evaluation-delivered-frame-{index}"
        frame = _frame(
            workspace_id=workspace_id,
            frame_id=frame_id,
            source_id=f"evaluation-delivered-{index}",
            source_kind=row_source_kind,
            source_created_at=at,
            expires_at=max(now + 86400, at + 86400),
            category=row_category,
        )
        _seed_opportunity(
            store,
            workspace_id=workspace_id,
            frame=frame,
            job_id=f"evaluation-delivered-job-{index}",
            request_id=f"evaluation-delivered-request-{index}",
            now=at,
            outcome="delivered",
        )

    for index, raw in enumerate(pending):
        if not isinstance(raw, Mapping):
            raise TypeError("history.pending rows must be objects")
        at = _finite_number(_value(raw, "at", "at", now), f"history.pending[{index}].at")
        row_category = _bounded_text(
            _value(raw, "category", "activityCategory", category),
            f"history.pending[{index}].category",
            default=category,
        )
        frame = _frame(
            workspace_id=workspace_id,
            frame_id=f"evaluation-pending-frame-{index}",
            source_id=f"evaluation-pending-{index}",
            source_kind=source_kind,
            source_created_at=at,
            expires_at=max(now + 86400, at + 86400),
            category=row_category,
        )
        _seed_opportunity(
            store,
            workspace_id=workspace_id,
            frame=frame,
            job_id=f"evaluation-pending-job-{index}",
            request_id=f"evaluation-pending-request-{index}",
            now=at,
        )

    for index, raw in enumerate(feedback):
        if not isinstance(raw, Mapping):
            raise TypeError("history.feedback rows must be objects")
        kind = _bounded_text(
            _value(raw, "kind", "kind"),
            f"history.feedback[{index}].kind",
            default="ignored",
            limit=40,
        )
        if kind not in _FEEDBACK_KINDS:
            raise ValueError(f"history.feedback[{index}].kind is unsupported")
        at = _finite_number(_value(raw, "at", "at", now), f"history.feedback[{index}].at")
        frame = _frame(
            workspace_id=workspace_id,
            frame_id=f"evaluation-feedback-frame-{index}",
            source_id=f"evaluation-feedback-{index}",
            source_kind=source_kind,
            source_created_at=at,
            expires_at=max(now + 86400, at + 86400),
            category=category,
        )
        job_id = f"evaluation-feedback-job-{index}"
        request_id = f"evaluation-feedback-request-{index}"
        _seed_opportunity(
            store,
            workspace_id=workspace_id,
            frame=frame,
            job_id=job_id,
            request_id=request_id,
            now=at,
        )
        recorded, _, _ = store.record_feedback(
            workspace_id,
            feedback_id=f"evaluation-feedback-{index}",
            job_id=job_id,
            request_id=request_id,
            source_kind=source_kind,
            kind=kind,
            now=at,
        )
        if not recorded:
            raise ValueError(f"history feedback could not be recorded: {index}")


def evaluate_proactive_case(
    case: Mapping[str, Any], *, now: float = 0.0
) -> ProactiveEvaluationResult:
    """Replay one redacted policy case against the runtime policy authority."""
    if not isinstance(case, Mapping):
        raise TypeError("proactive evaluation case must be an object")
    evaluation_now = _finite_number(now, "now")
    case_id = _bounded_text(
        _value(case, "case_id", "caseId"),
        "caseId",
        default="",
        limit=120,
    )
    expected_allowed = _value(case, "expected_allowed", "expectedAllowed")
    if not isinstance(expected_allowed, bool):
        raise TypeError("expectedAllowed must be boolean")
    expected_reason = _bounded_text(
        _value(case, "expected_reason", "expectedReason"),
        "expectedReason",
        default="",
        limit=80,
    )
    expected_remaining_budget = _value(
        case, "expected_remaining_budget", "expectedRemainingBudget", None
    )
    if expected_remaining_budget is not None:
        if isinstance(expected_remaining_budget, bool) or not isinstance(expected_remaining_budget, int):
            raise TypeError("expectedRemainingBudget must be a non-negative integer")
        if expected_remaining_budget < 0:
            raise ValueError("expectedRemainingBudget must be a non-negative integer")
    expected_remaining_category_budget = _value(
        case,
        "expected_remaining_category_budget",
        "expectedRemainingCategoryBudget",
        None,
    )
    if expected_remaining_category_budget is not None:
        if isinstance(expected_remaining_category_budget, bool) or not isinstance(expected_remaining_category_budget, int):
            raise TypeError("expectedRemainingCategoryBudget must be a non-negative integer")
        if expected_remaining_category_budget < 0:
            raise ValueError("expectedRemainingCategoryBudget must be a non-negative integer")
    workspace_id = _bounded_text(
        _value(case, "workspace_id", "workspaceId", "evaluation-workspace"),
        "workspaceId",
        default="evaluation-workspace",
    )
    source_kind = _bounded_text(
        _value(case, "source_kind", "sourceKind", SOURCE_KIND),
        "sourceKind",
        default=SOURCE_KIND,
    )
    category = _bounded_text(
        _value(case, "category", "activityCategory", "conversation"),
        "activityCategory",
        default="conversation",
    )
    settings = _value(case, "settings", "settings", {})
    if not isinstance(settings, Mapping):
        raise TypeError("settings must be an object")
    history = _value(case, "history", "history", {})
    if not isinstance(history, Mapping):
        raise TypeError("history must be an object")
    interruptible = _value(case, "interruptible", "interruptible", True)
    if not isinstance(interruptible, bool):
        raise TypeError("interruptible must be boolean")

    frame_payload = _value(case, "frame", "frame", {})
    if not isinstance(frame_payload, Mapping):
        raise TypeError("frame must be an object")
    source_created_at = _finite_number(
        _value(frame_payload, "source_created_at", "sourceCreatedAt", evaluation_now),
        "frame.sourceCreatedAt",
    )
    expires_at = _finite_number(
        _value(frame_payload, "expires_at", "expiresAt", evaluation_now + 86400),
        "frame.expiresAt",
    )
    frame_id = _bounded_text(
        _value(frame_payload, "frame_id", "frameId", "evaluation-current-frame"),
        "frameId",
        default="evaluation-current-frame",
    )
    frame = _frame(
        workspace_id=workspace_id,
        frame_id=frame_id,
        source_id="evaluation-current-source",
        source_kind=source_kind,
        source_created_at=source_created_at,
        expires_at=expires_at,
        category=category,
    )

    with tempfile.TemporaryDirectory(prefix="yuizaki-proactive-eval-") as directory:
        store = ActivityFrameStore(Path(directory) / "activity.sqlite3")
        service = ActivityFrameService(store, object())
        settings_payload = dict(settings)
        settings_payload.setdefault("expectedRevision", 0)
        service.patch_settings(workspace_id, settings_payload)
        _seed_history(
            store,
            workspace_id=workspace_id,
            source_kind=source_kind,
            category=category,
            now=evaluation_now,
            history=history,
        )
        if not store.upsert_frame(frame):
            raise ValueError("current frame could not be inserted")
        decision = store.evaluate(
            workspace_id,
            frame,
            now=evaluation_now,
            interruptible=interruptible,
        )

    errors: list[str] = []
    if decision.allowed is not expected_allowed:
        errors.append("allowed_mismatch")
    if decision.reason != expected_reason:
        errors.append("reason_mismatch")
    if expected_remaining_budget is not None and decision.remaining_budget != expected_remaining_budget:
        errors.append("remaining_budget_mismatch")
    if (
        expected_remaining_category_budget is not None
        and decision.remaining_category_budget != expected_remaining_category_budget
    ):
        errors.append("remaining_category_budget_mismatch")
    return ProactiveEvaluationResult(
        case_id=case_id,
        passed=not errors,
        expected_allowed=expected_allowed,
        observed_allowed=decision.allowed,
        expected_reason=expected_reason,
        observed_reason=decision.reason,
        remaining_budget=decision.remaining_budget,
        remaining_category_budget=decision.remaining_category_budget,
        preference_score=decision.preference_score,
        errors=tuple(errors),
        expected_remaining_budget=expected_remaining_budget,
        expected_remaining_category_budget=expected_remaining_category_budget,
    )


def load_golden_cases(path: str | Path) -> list[dict[str, Any]]:
    """Load a bounded list of redacted proactive policy cases."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list) or len(raw) > MAX_CASES:
        raise ValueError(f"proactive golden fixture must be a list of at most {MAX_CASES} cases")
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise TypeError("proactive golden fixture entries must be objects")
        case = dict(item)
        case_id = str(_value(case, "case_id", "caseId", "")).strip()
        if not case_id or case_id in seen:
            raise ValueError("proactive golden fixture case ids must be unique")
        seen.add(case_id)
        cases.append(case)
    return cases


def summarize_proactive_results(
    results: Iterable[ProactiveEvaluationResult],
) -> dict[str, Any]:
    """Build bounded aggregate metrics for CI and policy replay reports."""
    rows = list(results)
    if len(rows) > MAX_CASES:
        raise ValueError(f"proactive evaluation results are limited to {MAX_CASES} rows")
    for row in rows:
        if not isinstance(row, ProactiveEvaluationResult):
            raise TypeError("proactive evaluation results use ProactiveEvaluationResult")
        if not math.isfinite(row.preference_score):
            raise ValueError("proactive preference scores must be finite")
    total = len(rows)
    if total == 0:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "total": 0,
            "passed": 0,
            "passRate": 0.0,
            "allowedAccuracy": 0.0,
            "reasonAccuracy": 0.0,
        }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "total": total,
        "passed": sum(row.passed for row in rows),
        "passRate": round(sum(row.passed for row in rows) / total, 4),
        "allowedAccuracy": round(sum(row.observed_allowed == row.expected_allowed for row in rows) / total, 4),
        "reasonAccuracy": round(sum(row.observed_reason == row.expected_reason for row in rows) / total, 4),
    }


__all__ = [
    "SCHEMA_VERSION",
    "ProactiveEvaluationResult",
    "evaluate_proactive_case",
    "load_golden_cases",
    "summarize_proactive_results",
]
