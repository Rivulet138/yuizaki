from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from modules.agent.activity_frames import (
    ActivityFrame,
    ActivityFrameService,
    ActivityFrameStore,
)
from modules.system.runtime_endpoints import build_activity_frame_endpoints
from routes.system_api import create_system_router


class _SchedulerSpy:
    """Small scheduler double for replaying the policy/service boundary."""

    def __init__(self, *, interruptible: bool = True, ttl: float = 120.0) -> None:
        self.interruptible = interruptible
        self.ttl = ttl
        self.events: list[dict[str, object]] = []
        self.cancelled: list[dict[str, object]] = []
        self.resolved: list[dict[str, object]] = []
        self.observer = None

    def set_proactive_outcome_observer(self, observer) -> None:
        self.observer = observer

    def proactive_interruptible(self) -> bool:
        return self.interruptible

    def proactive_opportunity_ttl_seconds(self) -> float:
        return self.ttl

    def emit_proactive_opportunity(self, event, *, workspace_id: str) -> bool:
        self.events.append({**event, "workspace_id": workspace_id})
        return True

    def cancel_proactive_opportunities(self, **kwargs) -> int:
        self.cancelled.append(dict(kwargs))
        return 1

    def resolve_opportunity(self, **kwargs) -> bool:
        self.resolved.append(dict(kwargs))
        return True


def _turn_event(source_id: str, *, committed_at: float | None = None) -> dict[str, object]:
    timestamp = time.time() if committed_at is None else committed_at
    return {
        "event_type": "turn.committed",
        "event_id": f"event-{source_id}",
        "idempotency_key": source_id,
        "created_at": timestamp,
        "payload": {
            "workspace_id": "workspace-1",
            "session_id": "session-1",
            "committed_at": timestamp,
            "reply": "继续刚才的任务吗？",
            "messages": [{"role": "user", "content": "继续"}],
            "trigger": "socket",
        },
    }


def _service(tmp_path):
    store = ActivityFrameStore(tmp_path / "activity.sqlite3")
    frame = ActivityFrame(
        frame_id="frame-1",
        workspace_id="workspace-1",
        session_id="session-1",
        source_kind="completed_turn_followup",
        source_id="source-1",
        source_event_id="event-1",
        source_created_at=1_800_000_000,
        created_at=1_800_000_000,
        expires_at=1_900_000_000,
        projection_version="activity-frame.v1",
        policy_version="proactive-policy.v1",
        signals={"activityCategory": "conversation"},
    )
    assert store.upsert_frame(frame)
    store.patch_settings(
        "workspace-1",
        {"enabled": True, "quiet_hours_enabled": False},
        expected_revision=0,
    )
    assert store.reserve_opportunity(
        "workspace-1",
        job_id="job-1",
        request_id="request-1",
        frame_id="frame-1",
        source_kind="completed_turn_followup",
        local_date="2026-08-30",
        expires_at=1_850_000_000,
        now=1_800_100_000,
    )
    return ActivityFrameService(store, SimpleNamespace())


def test_snooze_feedback_is_persisted_and_visible_in_summary(tmp_path) -> None:
    service = _service(tmp_path)

    result = service.feedback(
        "workspace-1",
        {
            "feedbackId": "feedback-1",
            "jobId": "job-1",
            "requestId": "request-1",
            "sourceKind": "completed_turn_followup",
            "kind": "snoozed",
        },
    )

    assert result["ok"] is True
    summary = service.feedback_summary("workspace-1")
    assert summary["counts"] == {"snoozed": 1}
    assert summary["behavioralTotal"] == 1
    assert summary["acceptanceRate"] == 0


def test_activity_endpoints_and_router_expose_feedback_summary(tmp_path) -> None:
    service = _service(tmp_path)
    endpoints = build_activity_frame_endpoints(
        service_provider=lambda: service,
        active_workspace_id_provider=lambda: "workspace-1",
    )
    assert endpoints["feedback_summary"]()["workspaceId"] == "workspace-1"

    router = create_system_router(
        health_handler=dict,
        readiness_handler=dict,
        system_status_handler=dict,
        proactive_feedback_handler=endpoints["feedback"],
        proactive_feedback_summary_handler=endpoints["feedback_summary"],
    )
    paths = {route.path for route in router.routes}
    assert "/api/system/proactive/feedback" in paths
    assert "/api/system/proactive/feedback-summary" in paths


def test_never_source_is_persistent_and_reenable_is_explicit(tmp_path) -> None:
    store = ActivityFrameStore(tmp_path / "activity.sqlite3")
    service = ActivityFrameService(store, SimpleNamespace())
    now = time.time()
    frame = ActivityFrame(
        frame_id="frame-never-source",
        workspace_id="workspace-1",
        session_id="session-1",
        source_kind="completed_turn_followup",
        source_id="source-never-source",
        source_event_id="event-never-source",
        source_created_at=now,
        created_at=now,
        expires_at=now + 86400,
        projection_version="activity-frame.v1",
        policy_version="proactive-policy.v1",
        signals={"activityCategory": "conversation"},
    )
    assert store.upsert_frame(frame)
    service.patch_settings(
        "workspace-1",
        {"expectedRevision": 0, "enabled": True, "quietHours": {"enabled": False}},
    )
    assert store.reserve_opportunity(
        "workspace-1",
        job_id="job-never-source",
        request_id="request-never-source",
        frame_id=frame.frame_id,
        source_kind=frame.source_kind,
        local_date="2026-08-30",
        expires_at=now + 3600,
        now=now,
    )

    result = service.feedback(
        "workspace-1",
        {
            "feedbackId": "feedback-never-source",
            "jobId": "job-never-source",
            "requestId": "request-never-source",
            "sourceKind": frame.source_kind,
            "kind": "never_source",
        },
    )
    assert result["ok"] is True
    assert store.evaluate("workspace-1", frame, now=now).reason == "source_disabled"
    assert store.reserve_opportunity(
        "workspace-1",
        job_id="job-blocked",
        request_id="request-blocked",
        frame_id="frame-blocked",
        source_kind=frame.source_kind,
        local_date="2026-08-30",
        expires_at=now + 3600,
        now=now,
    ) is False

    restarted = ActivityFrameStore(tmp_path / "activity.sqlite3")
    assert restarted.get_settings("workspace-1").completed_turn_followup_enabled is False
    assert restarted.evaluate("workspace-1", frame, now=now).reason == "source_disabled"

    revision = restarted.get_settings_record("workspace-1")[1]
    reenabled = ActivityFrameService(restarted, SimpleNamespace()).patch_settings(
        "workspace-1",
        {
            "expectedRevision": revision,
            "enabled": True,
            "sourceEnabled": {"completed_turn_followup": True},
        },
    )
    assert reenabled["sourceEnabled"]["completed_turn_followup"] is True
    replacement = ActivityFrame(**{**frame.__dict__, "frame_id": "frame-reenabled", "source_id": "source-reenabled"})
    assert restarted.upsert_frame(replacement)
    assert restarted.evaluate("workspace-1", replacement, now=now).allowed is True


def test_policy_gate_reason_codes_are_replayable(tmp_path) -> None:
    store = ActivityFrameStore(tmp_path / "activity.sqlite3")
    service = ActivityFrameService(store, SimpleNamespace())
    now = time.time()
    frame = ActivityFrame(
        frame_id="frame-gates",
        workspace_id="workspace-1",
        session_id="session-1",
        source_kind="completed_turn_followup",
        source_id="source-gates",
        source_event_id="event-gates",
        source_created_at=now,
        created_at=now,
        expires_at=now + 86400,
        projection_version="activity-frame.v1",
        policy_version="proactive-policy.v1",
        signals={"activityCategory": "conversation"},
    )
    assert store.upsert_frame(frame)
    assert store.evaluate("workspace-1", frame, now=now).reason == "global_disabled"

    service.patch_settings("workspace-1", {"expectedRevision": 0, "enabled": True})
    assert store.evaluate("workspace-1", frame, now=now, interruptible=False).reason == "not_interruptible"
    service.patch_settings("workspace-1", {"expectedRevision": 1, "paused": True})
    assert store.evaluate("workspace-1", frame, now=now).reason == "user_paused"
    service.patch_settings("workspace-1", {"expectedRevision": 2, "paused": False, "dnd": True})
    assert store.evaluate("workspace-1", frame, now=now).reason == "dnd"
    service.patch_settings(
        "workspace-1",
        {"expectedRevision": 3, "dnd": False, "quietHours": {"enabled": True, "start": "00:00", "end": "23:59"}},
    )
    assert store.evaluate("workspace-1", frame, now=now).reason == "quiet_hours"


def test_budget_and_cooldown_reason_codes_are_replayable(tmp_path) -> None:
    local_date = time.strftime("%Y-%m-%d", time.gmtime(time.time()))

    daily_store = ActivityFrameStore(tmp_path / "daily-budget.sqlite3")
    daily_service = ActivityFrameService(daily_store, SimpleNamespace())
    daily_service.patch_settings(
        "workspace-1",
        {"expectedRevision": 0, "enabled": True, "dailyBudget": 1},
    )
    now = time.time()
    daily_frame = ActivityFrame(
        frame_id="frame-daily-budget",
        workspace_id="workspace-1",
        session_id="session-1",
        source_kind="completed_turn_followup",
        source_id="source-daily-budget",
        source_event_id="event-daily-budget",
        source_created_at=now,
        created_at=now,
        expires_at=now + 86400,
        projection_version="activity-frame.v1",
        policy_version="proactive-policy.v1",
        signals={"activityCategory": "conversation"},
    )
    assert daily_store.upsert_frame(daily_frame)
    assert daily_store.reserve_opportunity(
        "workspace-1",
        job_id="job-daily-budget",
        request_id="request-daily-budget",
        frame_id=daily_frame.frame_id,
        source_kind=daily_frame.source_kind,
        local_date=local_date,
        expires_at=now + 3600,
        now=now,
    )
    assert daily_store.evaluate("workspace-1", daily_frame, now=now).reason == "daily_budget"

    category_store = ActivityFrameStore(tmp_path / "category-budget.sqlite3")
    category_service = ActivityFrameService(category_store, SimpleNamespace())
    category_service.patch_settings(
        "workspace-1",
        {
            "expectedRevision": 0,
            "enabled": True,
            "dailyBudget": 2,
            "cooldownSeconds": 0,
            "categoryBudgets": {"conversation": 1},
        },
    )
    first = ActivityFrame(**{**daily_frame.__dict__, "frame_id": "frame-category-1", "source_id": "source-category-1"})
    second = ActivityFrame(**{**daily_frame.__dict__, "frame_id": "frame-category-2", "source_id": "source-category-2"})
    assert category_store.upsert_frame(first)
    assert category_store.upsert_frame(second)
    assert category_store.reserve_opportunity(
        "workspace-1",
        job_id="job-category-1",
        request_id="request-category-1",
        frame_id=first.frame_id,
        source_kind=first.source_kind,
        local_date=local_date,
        expires_at=now + 3600,
        now=now,
    )
    assert category_store.resolve_opportunity(
        workspace_id="workspace-1",
        job_id="job-category-1",
        request_id="request-category-1",
        source_kind=first.source_kind,
        outcome="delivered",
        now=now,
    )
    assert category_store.evaluate("workspace-1", second, now=now).reason == "category_budget"

    cooldown_store = ActivityFrameStore(tmp_path / "cooldown.sqlite3")
    cooldown_service = ActivityFrameService(cooldown_store, SimpleNamespace())
    cooldown_service.patch_settings(
        "workspace-1",
        {"expectedRevision": 0, "enabled": True, "dailyBudget": 2, "cooldownSeconds": 3600},
    )
    assert cooldown_store.upsert_frame(first)
    assert cooldown_store.upsert_frame(second)
    assert cooldown_store.reserve_opportunity(
        "workspace-1",
        job_id="job-cooldown-1",
        request_id="request-cooldown-1",
        frame_id=first.frame_id,
        source_kind=first.source_kind,
        local_date=local_date,
        expires_at=now + 3600,
        now=now,
    )
    assert cooldown_store.resolve_opportunity(
        workspace_id="workspace-1",
        job_id="job-cooldown-1",
        request_id="request-cooldown-1",
        source_kind=first.source_kind,
        outcome="delivered",
        now=now,
    )
    assert cooldown_store.evaluate("workspace-1", second, now=now).reason == "cooldown"


def test_activity_projection_lifecycle_is_idempotent_and_restartable(tmp_path) -> None:
    db_path = tmp_path / "activity.sqlite3"
    store = ActivityFrameStore(db_path)
    service = ActivityFrameService(store, SimpleNamespace())
    scheduler = _SchedulerSpy()
    service.bind_scheduler(scheduler)
    service.patch_settings("workspace-1", {"expectedRevision": 0, "enabled": True})

    projected = service.project(_turn_event("source-lifecycle"))
    assert projected["projected"] is True
    assert len(scheduler.events) == 1
    pending = store.list_pending_opportunities()
    assert len(pending) == 1
    event = scheduler.events[0]

    accepted = service.feedback(
        "workspace-1",
        {
            "feedbackId": "feedback-accepted",
            "jobId": str(event["job_id"]),
            "requestId": str(event["request_id"]),
            "sourceKind": "completed_turn_followup",
            "kind": "accepted",
        },
    )
    assert accepted["behavioral"] is True
    assert len(store.list_pending_opportunities()) == 1
    assert service.observe_outcome(event, "delivered") is True
    assert store.list_pending_opportunities() == []
    assert service.observe_outcome(event, "delivered") is True

    duplicate = service.feedback(
        "workspace-1",
        {
            "feedbackId": "feedback-accepted",
            "jobId": str(event["job_id"]),
            "requestId": str(event["request_id"]),
            "sourceKind": "completed_turn_followup",
            "kind": "accepted",
        },
    )
    assert duplicate["duplicate"] is True
    assert service.feedback_summary("workspace-1")["counts"] == {"accepted": 1}

    restart_store = ActivityFrameStore(db_path)
    restart_service = ActivityFrameService(restart_store, SimpleNamespace())
    restart_scheduler = _SchedulerSpy()
    restart_service.bind_scheduler(restart_scheduler)
    assert restart_scheduler.events == []
    assert restart_store.feedback_summary("workspace-1")["counts"] == {"accepted": 1}


def test_pending_opportunity_is_re_emitted_after_restart_and_expiry_is_cancelled(tmp_path) -> None:
    db_path = tmp_path / "activity.sqlite3"
    now = time.time()
    store = ActivityFrameStore(db_path)
    service = ActivityFrameService(store, SimpleNamespace())
    service.patch_settings("workspace-1", {"expectedRevision": 0, "enabled": True})
    frame = ActivityFrame(
        frame_id="frame-restart-pending",
        workspace_id="workspace-1",
        session_id="session-1",
        source_kind="completed_turn_followup",
        source_id="source-restart-pending",
        source_event_id="event-restart-pending",
        source_created_at=now,
        created_at=now,
        expires_at=now + 86400,
        projection_version="activity-frame.v1",
        policy_version="proactive-policy.v1",
        signals={"activityCategory": "conversation"},
    )
    assert store.upsert_frame(frame)
    assert store.reserve_opportunity(
        "workspace-1",
        job_id="job-restart-pending",
        request_id="request-restart-pending",
        frame_id=frame.frame_id,
        source_kind=frame.source_kind,
        local_date="2026-08-30",
        expires_at=now + 3600,
        now=now,
    )
    assert len(store.list_pending_opportunities()) == 1

    restarted = ActivityFrameStore(db_path)
    restart_service = ActivityFrameService(restarted, SimpleNamespace())
    scheduler = _SchedulerSpy()
    restart_service.bind_scheduler(scheduler)
    assert len(scheduler.events) == 1
    assert scheduler.events[0]["job_id"] == "job-restart-pending"
    assert len(restarted.list_pending_opportunities()) == 1

    assert restarted.prune_expired("workspace-1", now=now + 90000)
    assert restarted.list_pending_opportunities() == []
    assert restarted.list_frames("workspace-1", now=now + 90000) == []


@pytest.mark.parametrize(
    ("kind", "expected_reason"),
    [("ignored", "feedback_ignored"), ("snoozed", "feedback_snoozed")],
)
def test_negative_feedback_temporarily_gates_new_opportunities(tmp_path, kind: str, expected_reason: str) -> None:
    store = ActivityFrameStore(tmp_path / f"activity-{kind}.sqlite3")
    service = ActivityFrameService(store, SimpleNamespace())
    now = time.time()
    frame = ActivityFrame(
        frame_id=f"frame-{kind}",
        workspace_id="workspace-1",
        session_id="session-1",
        source_kind="completed_turn_followup",
        source_id=f"source-{kind}",
        source_event_id=f"event-{kind}",
        source_created_at=now,
        created_at=now,
        expires_at=now + 86400,
        projection_version="activity-frame.v1",
        policy_version="proactive-policy.v1",
        signals={"activityCategory": "conversation"},
    )
    assert store.upsert_frame(frame)
    service.patch_settings("workspace-1", {"expectedRevision": 0, "enabled": True})
    assert store.reserve_opportunity(
        "workspace-1",
        job_id=f"job-{kind}",
        request_id=f"request-{kind}",
        frame_id=frame.frame_id,
        source_kind=frame.source_kind,
        local_date="2026-08-30",
        expires_at=now + 3600,
        now=now,
    )
    assert service.feedback(
        "workspace-1",
        {
            "feedbackId": f"feedback-{kind}",
            "jobId": f"job-{kind}",
            "requestId": f"request-{kind}",
            "sourceKind": frame.source_kind,
            "kind": kind,
        },
    )["ok"] is True
    replacement = ActivityFrame(**{**frame.__dict__, "frame_id": f"frame-{kind}-next", "source_id": f"source-{kind}-next"})
    assert store.upsert_frame(replacement)
    assert store.evaluate("workspace-1", replacement, now=now).reason == expected_reason
