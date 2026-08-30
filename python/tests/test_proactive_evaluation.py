from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from modules.agent.activity_frames import (
    ActivityFrame,
    ActivityFrameService,
    ActivityFrameStore,
)
from modules.agent.proactive_evaluation import (
    SCHEMA_VERSION,
    evaluate_proactive_case,
    load_golden_cases,
    summarize_proactive_results,
)

NOW = 1_800_000_000.0


def _case(case_id: str, *, expected_allowed: bool, expected_reason: str, **extra: object) -> dict[str, object]:
    return {
        "caseId": case_id,
        "expectedAllowed": expected_allowed,
        "expectedReason": expected_reason,
        "settings": {"enabled": True, "dailyBudget": 2, "cooldownSeconds": 0},
        "frame": {"sourceCreatedAt": NOW, "expiresAt": NOW + 86400},
        **extra,
    }


def test_replay_allows_eligible_opportunity() -> None:
    result = evaluate_proactive_case(
        _case("eligible", expected_allowed=True, expected_reason="allowed"),
        now=NOW,
    )

    assert result.passed is True
    assert result.observed_allowed is True
    assert result.to_dict()["schemaVersion"] == SCHEMA_VERSION


def test_replay_respects_pause_gate() -> None:
    result = evaluate_proactive_case(
        _case(
            "paused",
            expected_allowed=False,
            expected_reason="user_paused",
            settings={"enabled": True, "paused": True},
        ),
        now=NOW,
    )

    assert result.passed is True
    assert result.observed_reason == "user_paused"


def test_replay_respects_recent_negative_feedback() -> None:
    result = evaluate_proactive_case(
        _case(
            "ignored",
            expected_allowed=False,
            expected_reason="feedback_ignored",
            history={"feedback": [{"kind": "ignored", "at": NOW - 60}]},
        ),
        now=NOW,
    )

    assert result.passed is True
    assert result.observed_reason == "feedback_ignored"


@pytest.mark.parametrize(
    ("case_id", "expected_reason"),
    [
        ("snoozed-feedback", "feedback_snoozed"),
        ("source-disabled", "source_disabled"),
        ("category-budget", "category_budget"),
        ("cooldown-active", "cooldown"),
        ("cooldown-expired", "allowed"),
    ],
)
def test_replay_covers_reversible_comfort_gates(case_id: str, expected_reason: str) -> None:
    fixture_path = __import__("pathlib").Path(__file__).parents[1] / "evals" / "fixtures" / "proactive_policy.json"
    case = next(item for item in load_golden_cases(fixture_path) if item["caseId"] == case_id)

    result = evaluate_proactive_case(case, now=NOW)

    assert result.passed is True
    assert result.observed_reason == expected_reason


def test_all_golden_cases_pass_with_budget_assertions() -> None:
    fixture_path = __import__("pathlib").Path(__file__).parents[1] / "evals" / "fixtures" / "proactive_policy.json"
    cases = load_golden_cases(fixture_path)

    results = [evaluate_proactive_case(case, now=NOW) for case in cases]

    assert len(results) == 11
    assert all(result.passed for result in results), [result.to_dict() for result in results if not result.passed]


def test_replay_respects_daily_budget() -> None:
    result = evaluate_proactive_case(
        _case(
            "budget",
            expected_allowed=False,
            expected_reason="daily_budget",
            settings={"enabled": True, "dailyBudget": 1, "cooldownSeconds": 0},
            history={"delivered": [{"at": NOW - 60}]},
        ),
        now=NOW,
    )

    assert result.passed is True
    assert result.observed_reason == "daily_budget"


def test_cancelled_feedback_fences_pending_opportunity_and_survives_restart(tmp_path) -> None:
    db_path = tmp_path / "activity.sqlite3"
    workspace_id = "evaluation-workspace"
    source_kind = "completed_turn_followup"
    frame = ActivityFrame(
        frame_id="frame-cancelled-restart",
        workspace_id=workspace_id,
        session_id="evaluation-session",
        source_kind=source_kind,
        source_id="source-cancelled-restart",
        source_event_id="event-cancelled-restart",
        source_created_at=NOW,
        created_at=NOW,
        expires_at=NOW + 86400,
        projection_version="activity-frame.v1",
        policy_version="proactive-policy.v1",
        signals={"activityCategory": "conversation"},
    )
    store = ActivityFrameStore(db_path)
    service = ActivityFrameService(store, SimpleNamespace())
    service.patch_settings(workspace_id, {"expectedRevision": 0, "enabled": True, "cooldownSeconds": 0})
    assert store.upsert_frame(frame)
    assert store.reserve_opportunity(
        workspace_id,
        job_id="job-cancelled-restart",
        request_id="request-cancelled-restart",
        frame_id=frame.frame_id,
        source_kind=source_kind,
        local_date="2027-01-15",
        expires_at=NOW + 3600,
        now=NOW,
    )
    recorded, _, cancelled = store.record_feedback(
        workspace_id,
        feedback_id="feedback-cancelled-restart",
        job_id="job-cancelled-restart",
        request_id="request-cancelled-restart",
        source_kind=source_kind,
        kind="cancelled",
        now=NOW + 1,
    )

    assert recorded is True
    assert cancelled == [("job-cancelled-restart", "request-cancelled-restart")]
    assert store.list_pending_opportunities() == []

    restarted = ActivityFrameStore(db_path)
    assert restarted.pending_for_frame(workspace_id, frame.frame_id) is None
    assert restarted.list_feedback(workspace_id)[0]["kind"] == "cancelled"


def test_golden_loader_rejects_duplicate_case_ids(tmp_path) -> None:
    path = tmp_path / "proactive.json"
    path.write_text(json.dumps([{"caseId": "same"}, {"caseId": "same"}]), encoding="utf-8")

    with pytest.raises(ValueError, match="case ids must be unique"):
        load_golden_cases(path)


def test_summary_reports_policy_and_reason_accuracy() -> None:
    rows = [
        evaluate_proactive_case(
            _case("one", expected_allowed=True, expected_reason="allowed"),
            now=NOW,
        ),
        evaluate_proactive_case(
            _case("two", expected_allowed=False, expected_reason="user_paused", settings={"enabled": True, "paused": True}),
            now=NOW,
        ),
    ]

    summary = summarize_proactive_results(rows)

    assert summary == {
        "schemaVersion": SCHEMA_VERSION,
        "total": 2,
        "passed": 2,
        "passRate": 1.0,
        "allowedAccuracy": 1.0,
        "reasonAccuracy": 1.0,
    }
