from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from modules.agent.activity_frames import (
    ActivityFrame,
    ActivityFrameService,
    ActivityFrameStore,
    GATE_ORDER,
    POLICY_VERSION,
    PROJECTION_VERSION,
    SOURCE_KIND,
    deterministic_frame_id,
)
from modules.agent.companion_events import CompanionJobEventLog
from modules.system.heartbeat import HeartbeatScheduler


def _event(
    *,
    workspace: str = "workspace-a",
    source_id: str = "turn:one",
    event_id: int = 7,
    created_at: float = 1_800_000_000.0,
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "event_type": "turn.committed",
        "idempotency_key": source_id,
        "created_at": created_at,
        "payload": {
            "workspace_id": workspace,
            "session_id": "session:one",
            "trigger": "socket",
            "messages": [
                {"role": "user", "content": "SECRET user chat sk-live-123"},
                {"role": "assistant", "content": "old reply"},
            ],
            "reply": "SECRET assistant reply",
            "tool_calls": [{"name": "danger", "output": "SECRET tool output"}],
            "action_envelope": {"actions": [{"payload": "SECRET action"}]},
            "screenshot": "data:image/png;base64,SECRET",
            "audio": "SECRET audio",
            "credential": "SECRET credential",
        },
    }


def _frame(
    *,
    workspace: str = "workspace-a",
    source_id: str = "turn:one",
    created_at: float = 1_850_000_000.0,
    expires_at: float = 1_900_000_000.0,
) -> ActivityFrame:
    return ActivityFrame(
        frame_id=deterministic_frame_id(SOURCE_KIND, source_id),
        workspace_id=workspace,
        session_id="session:one",
        source_kind=SOURCE_KIND,
        source_id=source_id,
        source_event_id="7",
        source_created_at=created_at,
        created_at=created_at,
        expires_at=expires_at,
        projection_version=PROJECTION_VERSION,
        policy_version=POLICY_VERSION,
        signals={"kind": SOURCE_KIND, "turnCompleted": True},
    )


def _enable(store: ActivityFrameStore, workspace: str = "workspace-a", **patch: Any) -> int:
    _, revision, _ = store.patch_settings(
        workspace,
        {"enabled": True, "cooldown_seconds": 0, **patch},
        expected_revision=0,
    )
    return revision


def test_projection_is_deterministic_bounded_and_raw_content_free(tmp_path: Path) -> None:
    first = ActivityFrameService.project_event(_event(), retention_days=7)
    second = ActivityFrameService.project_event(_event(event_id=99), retention_days=7)
    assert first is not None and second is not None
    assert first.frame_id == second.frame_id == deterministic_frame_id(SOURCE_KIND, "turn:one")
    assert first.frame_id == "af_" + __import__("hashlib").sha256(
        f"{SOURCE_KIND}\0turn:one\0{PROJECTION_VERSION}".encode()
    ).hexdigest()
    serialized = json.dumps(first.to_api(), sort_keys=True)
    for canary in (
        "SECRET",
        "sk-live",
        "user chat",
        "assistant reply",
        "tool output",
        "data:image",
        "SECRET credential",
    ):
        assert canary not in serialized
    assert first.to_api()["authoritative"] is False
    assert first.to_api()["allowedActions"] == []


def test_store_is_idempotent_and_workspace_isolated(tmp_path: Path) -> None:
    store = ActivityFrameStore(tmp_path / "frames.sqlite3")
    a = _frame(workspace="workspace-a")
    b = _frame(workspace="workspace-b")
    assert a.frame_id == b.frame_id
    assert store.upsert_frame(a)
    assert store.upsert_frame(a)
    assert store.upsert_frame(b)
    assert len(store.list_frames("workspace-a", now=a.created_at)) == 1
    assert len(store.list_frames("workspace-b", now=b.created_at)) == 1


def test_delete_before_late_event_and_restart_rebuild_never_revives(tmp_path: Path) -> None:
    db_path = tmp_path / "frames.sqlite3"
    store = ActivityFrameStore(db_path)
    frame = _frame()
    assert store.tombstone_source(frame.workspace_id, frame.source_kind, frame.source_id) == frame.frame_id
    assert not store.upsert_frame(frame)
    restarted = ActivityFrameStore(db_path)
    assert not restarted.upsert_frame(frame)
    assert restarted.list_frames(frame.workspace_id, now=frame.created_at) == []


def test_retention_expiry_creates_permanent_tombstone(tmp_path: Path) -> None:
    db_path = tmp_path / "frames.sqlite3"
    store = ActivityFrameStore(db_path)
    frame = _frame(expires_at=100.0, created_at=1.0)
    _enable(store, daily_budget=3)
    assert store.upsert_frame(frame)
    assert store.reserve_opportunity(
        frame.workspace_id,
        job_id="job:retention",
        request_id="request:retention",
        frame_id=frame.frame_id,
        source_kind=frame.source_kind,
        local_date="1970-01-01",
        now=50.0,
    )
    assert store.prune_expired(frame.workspace_id, now=101.0) == [
        {
            "workspace_id": frame.workspace_id,
            "job_id": "job:retention",
            "request_id": "request:retention",
            "source_kind": frame.source_kind,
            "frame_id": frame.frame_id,
        }
    ]
    assert not ActivityFrameStore(db_path).upsert_frame(frame)


@pytest.mark.asyncio
async def test_retention_shrink_atomically_settles_running_scheduler_and_restart(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "frames.sqlite3"
    store = ActivityFrameStore(db_path)
    service = ActivityFrameService(store, _TurnStore([]))
    jobs = CompanionJobEventLog()
    scheduler = HeartbeatScheduler(interval_seconds=3600, job_event_log=jobs)
    service.bind_scheduler(scheduler)
    service.patch_settings(
        "workspace-a",
        {"expectedRevision": 0, "enabled": True, "dailyBudget": 3, "retentionDays": 7},
    )
    event = _event(created_at=time.time() - 2 * 86400)
    await scheduler.start()
    try:
        projected = service.project(event)
        frame_id = str(projected["frameId"])
        visible = scheduler.state.behavior_events[0]
        job_id = str(visible["job_id"])
        goal_id = str(scheduler._opportunities[job_id]["goal_id"])

        service.patch_settings(
            "workspace-a",
            {"expectedRevision": 1, "retentionDays": 1},
        )

        assert store.get_frame("workspace-a", frame_id) is None
        assert store.pending_for_frame("workspace-a", frame_id) is None
        assert scheduler._opportunities == {}
        assert scheduler.state.behavior_events == []
        assert jobs.active_job_ids() == []
        goal = next(item for item in scheduler.goal_snapshot() if item["goal_id"] == goal_id)
        assert goal["state"] == "cancelled"
        assert jobs.snapshot()[-1]["data"]["outcome"] == "cancelled"

        service.patch_settings(
            "workspace-a",
            {"expectedRevision": 2, "retentionDays": 1},
        )
        restarted_scheduler = HeartbeatScheduler(job_event_log=CompanionJobEventLog())
        restarted = ActivityFrameService(ActivityFrameStore(db_path), _TurnStore([event]))
        restarted.bind_scheduler(restarted_scheduler)
        assert restarted.rebuild("workspace-a")["projected"] == 0
        assert restarted_scheduler._opportunities == {}
        assert restarted_scheduler.state.behavior_events == []
    finally:
        await scheduler.stop()


@pytest.mark.parametrize(
    ("settings_patch", "frame_active", "interruptible", "expected"),
    [
        ({}, True, True, "global_disabled"),
        ({"enabled": True, "completed_turn_followup_enabled": False}, True, True, "source_disabled"),
        ({"enabled": True}, False, True, "frame_inactive"),
        ({"enabled": True, "dnd": True}, True, True, "dnd"),
        (
            {
                "enabled": True,
                "quiet_hours_enabled": True,
                "quiet_hours_start": "00:00",
                "quiet_hours_end": "23:59",
            },
            True,
            True,
            "quiet_hours",
        ),
        ({"enabled": True}, True, False, "not_interruptible"),
    ],
)
def test_policy_gate_precedence_before_stateful_gates(
    tmp_path: Path,
    settings_patch: dict[str, Any],
    frame_active: bool,
    interruptible: bool,
    expected: str,
) -> None:
    store = ActivityFrameStore(tmp_path / expected / "frames.sqlite3")
    frame = _frame()
    if frame_active:
        assert store.upsert_frame(frame)
    if settings_patch:
        store.patch_settings("workspace-a", settings_patch, expected_revision=0)
    decision = store.evaluate(
        "workspace-a",
        frame,
        now=1_850_000_000.0,
        interruptible=interruptible,
    )
    assert decision.reason == expected
    assert decision.to_api()["gateOrder"] == list(GATE_ORDER)


def test_policy_orders_cooldown_then_budget_then_dedupe(tmp_path: Path) -> None:
    store = ActivityFrameStore(tmp_path / "frames.sqlite3")
    frame = _frame()
    assert store.upsert_frame(frame)
    _enable(store, cooldown_seconds=300, daily_budget=1)
    allowed = store.evaluate("workspace-a", frame, now=1_850_000_000.0)
    assert allowed.allowed
    assert store.reserve_opportunity(
        "workspace-a",
        job_id="job:one",
        request_id="request:one",
        frame_id=frame.frame_id,
        source_kind=SOURCE_KIND,
        local_date=allowed.local_date,
        now=1_850_000_000.0,
    )
    assert store.resolve_opportunity(
        workspace_id="workspace-a",
        job_id="job:one",
        request_id="request:one",
        source_kind=SOURCE_KIND,
        outcome="delivered",
        now=1_850_000_000.0,
    )
    assert store.evaluate("workspace-a", frame, now=1_850_000_001.0).reason == "cooldown"
    store.patch_settings("workspace-a", {"cooldown_seconds": 0}, expected_revision=1)
    assert store.evaluate("workspace-a", frame, now=1_850_000_001.0).reason == "daily_budget"


def test_duplicate_gate_after_budget_when_capacity_remains(tmp_path: Path) -> None:
    store = ActivityFrameStore(tmp_path / "frames.sqlite3")
    frame = _frame()
    assert store.upsert_frame(frame)
    _enable(store, daily_budget=2)
    assert store.reserve_opportunity(
        "workspace-a",
        job_id="job:one",
        request_id="request:one",
        frame_id=frame.frame_id,
        source_kind=SOURCE_KIND,
        local_date="2028-08-16",
    )
    assert store.evaluate("workspace-a", frame, now=1_850_000_001.0).reason == "duplicate"


def test_quiet_hours_use_iana_half_open_cross_midnight_and_dst(tmp_path: Path) -> None:
    store = ActivityFrameStore(tmp_path / "frames.sqlite3")
    frame = _frame()
    assert store.upsert_frame(frame)
    store.patch_settings(
        "workspace-a",
        {
            "enabled": True,
            "quiet_hours_enabled": True,
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "08:00",
            "timezone": "America/New_York",
            "cooldown_seconds": 0,
        },
        expected_revision=0,
    )
    at_start = datetime(2026, 11, 2, 3, 0, tzinfo=timezone.utc).timestamp()  # 22:00 local
    at_end = datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc).timestamp()  # 08:00 local
    assert store.evaluate("workspace-a", frame, now=at_start).reason == "quiet_hours"
    assert store.evaluate("workspace-a", frame, now=at_end).reason == "allowed"


def test_invalid_timezone_and_quiet_clock_fail_closed_on_patch(tmp_path: Path) -> None:
    store = ActivityFrameStore(tmp_path / "frames.sqlite3")
    with pytest.raises(ValueError):
        store.patch_settings("workspace-a", {"timezone": "Mars/Olympus"}, expected_revision=0)
    with pytest.raises(ValueError):
        store.patch_settings("workspace-a", {"quiet_hours_start": "8:00"}, expected_revision=0)


def test_budget_is_reserved_concurrently_but_consumed_only_on_delivered_ack(tmp_path: Path) -> None:
    db_path = tmp_path / "frames.sqlite3"
    store = ActivityFrameStore(db_path)
    frame = _frame()
    assert store.upsert_frame(frame)
    _enable(store, daily_budget=1)
    decision = store.evaluate("workspace-a", frame, now=1_850_000_000.0)
    barrier = threading.Barrier(3)
    results: list[bool] = []

    def reserve(index: int) -> None:
        barrier.wait()
        results.append(
            ActivityFrameStore(db_path).reserve_opportunity(
                "workspace-a",
                job_id=f"job:{index}",
                request_id=f"request:{index}",
                frame_id=frame.frame_id,
                source_kind=SOURCE_KIND,
                local_date=decision.local_date,
            )
        )

    threads = [threading.Thread(target=reserve, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert sorted(results) == [False, True]
    with store._connect() as conn:
        row = conn.execute("SELECT job_id, request_id, status FROM proactive_opportunities").fetchone()
    assert row["status"] == "pending"
    assert store.evaluate("workspace-a", frame, now=1_850_000_001.0).remaining_budget == 1
    assert ActivityFrameStore(db_path).resolve_opportunity(
        workspace_id="workspace-a",
        job_id=row["job_id"],
        request_id=row["request_id"],
        source_kind=SOURCE_KIND,
        outcome="delivered",
        now=1_850_000_001.0,
    )
    assert ActivityFrameStore(db_path).resolve_opportunity(
        workspace_id="workspace-a",
        job_id=row["job_id"],
        request_id=row["request_id"],
        source_kind=SOURCE_KIND,
        outcome="delivered",
        now=1_850_000_002.0,
    )
    assert ActivityFrameStore(db_path).evaluate(
        "workspace-a", frame, now=1_850_000_002.0
    ).remaining_budget == 0


def test_stale_late_or_wrong_identity_outcomes_do_not_consume_budget(tmp_path: Path) -> None:
    store = ActivityFrameStore(tmp_path / "frames.sqlite3")
    frame = _frame()
    assert store.upsert_frame(frame)
    _enable(store, daily_budget=2)
    decision = store.evaluate("workspace-a", frame, now=1_850_000_000.0)
    assert store.reserve_opportunity(
        "workspace-a",
        job_id="job:one",
        request_id="request:one",
        frame_id=frame.frame_id,
        source_kind=SOURCE_KIND,
        local_date=decision.local_date,
    )
    assert not store.resolve_opportunity(
        workspace_id="workspace-b",
        job_id="job:one",
        request_id="request:one",
        source_kind=SOURCE_KIND,
        outcome="delivered",
    )
    assert not store.resolve_opportunity(
        workspace_id="workspace-a",
        job_id="job:one",
        request_id="wrong",
        source_kind=SOURCE_KIND,
        outcome="delivered",
    )
    assert store.resolve_opportunity(
        workspace_id="workspace-a",
        job_id="job:one",
        request_id="request:one",
        source_kind=SOURCE_KIND,
        outcome="expired",
    )
    assert not store.resolve_opportunity(
        workspace_id="workspace-a",
        job_id="job:one",
        request_id="request:one",
        source_kind=SOURCE_KIND,
        outcome="delivered",
    )
    assert store.evaluate("workspace-a", frame, now=1_850_000_001.0).remaining_budget == 2


def test_delivered_ack_rechecks_cooldown_across_restart_and_windows(tmp_path: Path) -> None:
    db_path = tmp_path / "frames.sqlite3"
    store = ActivityFrameStore(db_path)
    _enable(store, daily_budget=3, cooldown_seconds=3600)
    first = _frame(source_id="turn:cooldown:first")
    second = _frame(source_id="turn:cooldown:second")
    assert store.upsert_frame(first)
    assert store.upsert_frame(second)
    for frame, suffix in ((first, "first"), (second, "second")):
        assert store.reserve_opportunity(
            "workspace-a",
            job_id=f"job:cooldown:{suffix}",
            request_id=f"request:cooldown:{suffix}",
            frame_id=frame.frame_id,
            source_kind=SOURCE_KIND,
            local_date="2028-08-16",
            now=1_850_000_000.0,
        )
    assert store.resolve_opportunity(
        workspace_id="workspace-a",
        job_id="job:cooldown:first",
        request_id="request:cooldown:first",
        source_kind=SOURCE_KIND,
        outcome="delivered",
        now=1_850_000_001.0,
    )

    restarted = ActivityFrameStore(db_path)
    assert not restarted.resolve_opportunity(
        workspace_id="workspace-a",
        job_id="job:cooldown:second",
        request_id="request:cooldown:second",
        source_kind=SOURCE_KIND,
        outcome="delivered",
        now=1_850_000_002.0,
    )
    assert restarted.evaluate(
        "workspace-a", second, now=1_850_000_002.0
    ).remaining_budget == 2
    assert restarted.resolve_opportunity(
        workspace_id="workspace-a",
        job_id="job:cooldown:second",
        request_id="request:cooldown:second",
        source_kind=SOURCE_KIND,
        outcome="delivered",
        now=1_850_003_602.0,
    )
    assert restarted.evaluate(
        "workspace-a", second, now=1_850_003_602.0
    ).remaining_budget == 1


def test_feedback_is_idempotent_and_never_source_atomically_fences_pending(tmp_path: Path) -> None:
    store = ActivityFrameStore(tmp_path / "frames.sqlite3")
    frame = _frame()
    assert store.upsert_frame(frame)
    _enable(store, daily_budget=3)
    decision = store.evaluate("workspace-a", frame, now=1_850_000_000.0)
    assert store.reserve_opportunity(
        "workspace-a",
        job_id="job:one",
        request_id="request:one",
        frame_id=frame.frame_id,
        source_kind=SOURCE_KIND,
        local_date=decision.local_date,
    )
    created, source, cancelled = store.record_feedback(
        "workspace-a",
        feedback_id="feedback:one",
        job_id="job:one",
        request_id="request:one",
        source_kind=SOURCE_KIND,
        kind="never_source",
    )
    assert created and source == SOURCE_KIND and cancelled == [("job:one", "request:one")]
    duplicate = store.record_feedback(
        "workspace-a",
        feedback_id="feedback:one",
        job_id="job:one",
        request_id="request:one",
        source_kind=SOURCE_KIND,
        kind="never_source",
    )
    assert duplicate == (False, SOURCE_KIND, [])
    assert store.get_settings("workspace-a").completed_turn_followup_enabled is False
    assert not store.reserve_opportunity(
        "workspace-a",
        job_id="job:late",
        request_id="request:late",
        frame_id=frame.frame_id,
        source_kind=SOURCE_KIND,
        local_date=decision.local_date,
    )
    assert not store.resolve_opportunity(
        workspace_id="workspace-a",
        job_id="job:one",
        request_id="request:one",
        source_kind=SOURCE_KIND,
        outcome="delivered",
    )


def test_negative_feedback_cancels_current_opportunity_and_temporarily_gates_future_ones(tmp_path: Path) -> None:
    store = ActivityFrameStore(tmp_path / "frames.sqlite3")
    service = ActivityFrameService(store, _TurnStore([]))
    now = time.time()
    frame = _frame(created_at=now, expires_at=now + 100_000)
    assert store.upsert_frame(frame)
    _enable(store, daily_budget=3, cooldown_seconds=0)
    decision = store.evaluate("workspace-a", frame, now=now)
    assert decision.allowed
    assert store.reserve_opportunity(
        "workspace-a",
        job_id="job:feedback",
        request_id="request:feedback",
        frame_id=frame.frame_id,
        source_kind=SOURCE_KIND,
        local_date=decision.local_date,
        now=now,
    )

    result = service.feedback("workspace-a", {
        "feedbackId": "feedback:too-frequent",
        "jobId": "job:feedback",
        "requestId": "request:feedback",
        "sourceKind": SOURCE_KIND,
        "kind": "too_frequent",
    })
    assert result["ok"] is True
    assert result["cancelledPending"] == 1
    assert store.evaluate("workspace-a", frame, now=now + 1.0).reason == "feedback_too_frequent"
    next_frame = _frame(source_id="turn:two", created_at=now, expires_at=now + 100_000)
    assert store.upsert_frame(next_frame)
    assert store.evaluate("workspace-a", next_frame, now=now + 3_601.0).allowed


class _TurnStore:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.events = events

    def list_commits(self, workspace_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        return [event for event in self.events[:limit] if event["payload"]["workspace_id"] == workspace_id]


class _Scheduler:
    def __init__(self) -> None:
        self.observer = None
        self.events: list[dict[str, Any]] = []

    def set_proactive_outcome_observer(self, observer: Any) -> None:
        self.observer = observer

    def proactive_interruptible(self) -> bool:
        return True

    def emit_proactive_opportunity(self, event: dict[str, Any], *, workspace_id: str) -> bool:
        if any(item["job_id"] == event["job_id"] for item in self.events):
            return True
        self.events.append({**event, "workspace_id": workspace_id})
        return True

    def resolve_opportunity(self, **payload: Any) -> bool:
        return True

    def cancel_proactive_opportunities(self, **payload: Any) -> int:
        return 1


def test_outbox_crash_replay_dedupes_frame_and_opportunity(tmp_path: Path) -> None:
    store = ActivityFrameStore(tmp_path / "frames.sqlite3")
    _enable(store, daily_budget=3)
    service = ActivityFrameService(store, _TurnStore([]))
    scheduler = _Scheduler()
    service.bind_scheduler(scheduler)
    event = _event(created_at=1_800_000_000.0)
    first = service.project(event)
    second = service.project(event)
    assert first["projected"] and second["projected"]
    assert len(store.list_frames("workspace-a", now=1_800_100_000.0)) == 1
    assert len(scheduler.events) == 1


def test_rebuild_is_idempotent_and_respects_tombstones(tmp_path: Path) -> None:
    event = _event()
    store = ActivityFrameStore(tmp_path / "frames.sqlite3")
    service = ActivityFrameService(store, _TurnStore([event]))
    first = service.rebuild("workspace-a")
    second = service.rebuild("workspace-a")
    assert first["projected"] == second["projected"] == 1
    frame_id = deterministic_frame_id(SOURCE_KIND, "turn:one")
    assert service.delete_frame("workspace-a", frame_id)
    third = service.rebuild("workspace-a")
    assert third["projected"] == 0
    assert third["tombstoned"] == 1


def test_settings_revision_and_feedback_source_are_strict(tmp_path: Path) -> None:
    store = ActivityFrameStore(tmp_path / "frames.sqlite3")
    service = ActivityFrameService(store, _TurnStore([]))
    initial = service.get_settings("workspace-a")
    assert initial["revision"] == 0 and initial["enabled"] is False
    updated = service.patch_settings(
        "workspace-a",
        {"expectedRevision": 0, "enabled": True},
    )
    assert updated["revision"] == 1 and updated["workspaceId"] == "workspace-a"
    with pytest.raises(LookupError):
        service.patch_settings("workspace-a", {"expectedRevision": 0, "dnd": True})
    with pytest.raises(ValueError):
        service.feedback(
            "workspace-a",
            {
                "feedbackId": "feedback:one",
                "jobId": "job:one",
                "requestId": "request:one",
                "sourceKind": "other",
                "kind": "useful",
            },
        )


def test_projection_without_authoritative_timestamp_fails_closed() -> None:
    event = _event()
    event.pop("created_at")
    event["payload"].pop("committed_at", None)
    with pytest.raises(ValueError, match="authoritative committed timestamp"):
        ActivityFrameService.project_event(event, retention_days=7)


def test_reservation_atomically_rechecks_frame_and_policy_after_evaluation(tmp_path: Path) -> None:
    store = ActivityFrameStore(tmp_path / "frames.sqlite3")
    frame = _frame()
    assert store.upsert_frame(frame)
    _enable(store, daily_budget=3)
    decision = store.evaluate("workspace-a", frame, now=1_850_000_000.0)
    assert decision.allowed
    assert store.delete_frame("workspace-a", frame.frame_id, now=1_850_000_001.0)
    assert not store.reserve_opportunity(
        "workspace-a",
        job_id="job:deleted-race",
        request_id="request:deleted-race",
        frame_id=frame.frame_id,
        source_kind=SOURCE_KIND,
        local_date=decision.local_date,
        interruptible=True,
        now=1_850_000_002.0,
    )


def test_concurrent_delete_and_reserve_always_finishes_without_pending(tmp_path: Path) -> None:
    store = ActivityFrameStore(tmp_path / "frames.sqlite3")
    _enable(store, daily_budget=20)
    now = time.time()
    for index in range(8):
        frame = _frame(
            source_id=f"turn:race:{index}",
            created_at=now,
            expires_at=now + 600,
        )
        assert store.upsert_frame(frame)
        barrier = threading.Barrier(3)

        def reserve(
            current_barrier: threading.Barrier = barrier,
            current_frame: ActivityFrame = frame,
            current_index: int = index,
        ) -> None:
            current_barrier.wait()
            store.reserve_opportunity(
                "workspace-a",
                job_id=f"job:race:{current_index}",
                request_id=f"request:race:{current_index}",
                frame_id=current_frame.frame_id,
                source_kind=SOURCE_KIND,
                local_date=datetime.now(timezone.utc).date().isoformat(),
                interruptible=True,
                now=now,
            )

        def delete(
            current_barrier: threading.Barrier = barrier,
            current_frame: ActivityFrame = frame,
        ) -> None:
            current_barrier.wait()
            store.delete_frame("workspace-a", current_frame.frame_id, now=now + 1)

        threads = [threading.Thread(target=reserve), threading.Thread(target=delete)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()
        assert store.pending_for_frame("workspace-a", frame.frame_id) is None

    other = _frame(source_id="turn:policy-race")
    assert store.upsert_frame(other)
    store.patch_settings("workspace-a", {"dnd": True}, expected_revision=1)
    assert not store.reserve_opportunity(
        "workspace-a",
        job_id="job:policy-race",
        request_id="request:policy-race",
        frame_id=other.frame_id,
        source_kind=SOURCE_KIND,
        local_date="2028-08-16",
        interruptible=True,
        now=1_850_000_002.0,
    )


def test_reservation_rechecks_quiet_hours_interruptibility_cooldown_and_dedupe(tmp_path: Path) -> None:
    store = ActivityFrameStore(tmp_path / "frames.sqlite3")
    frame = _frame()
    assert store.upsert_frame(frame)
    store.patch_settings(
        "workspace-a",
        {
            "enabled": True,
            "quiet_hours_enabled": True,
            "quiet_hours_start": "00:00",
            "quiet_hours_end": "23:59",
            "cooldown_seconds": 300,
        },
        expected_revision=0,
    )
    assert not store.reserve_opportunity(
        "workspace-a",
        job_id="job:quiet",
        request_id="request:quiet",
        frame_id=frame.frame_id,
        source_kind=SOURCE_KIND,
        local_date="2028-08-16",
        interruptible=True,
        now=1_850_000_000.0,
    )
    store.patch_settings(
        "workspace-a",
        {"quiet_hours_enabled": False},
        expected_revision=1,
    )
    assert not store.reserve_opportunity(
        "workspace-a",
        job_id="job:busy",
        request_id="request:busy",
        frame_id=frame.frame_id,
        source_kind=SOURCE_KIND,
        local_date="2028-08-16",
        interruptible=False,
        now=1_850_000_000.0,
    )
    assert store.reserve_opportunity(
        "workspace-a",
        job_id="job:first",
        request_id="request:first",
        frame_id=frame.frame_id,
        source_kind=SOURCE_KIND,
        local_date="2028-08-16",
        interruptible=True,
        now=1_850_000_000.0,
    )
    assert store.resolve_opportunity(
        workspace_id="workspace-a",
        job_id="job:first",
        request_id="request:first",
        source_kind=SOURCE_KIND,
        outcome="delivered",
        now=1_850_000_001.0,
    )
    second = _frame(source_id="turn:second")
    assert store.upsert_frame(second)
    assert not store.reserve_opportunity(
        "workspace-a",
        job_id="job:cooldown",
        request_id="request:cooldown",
        frame_id=second.frame_id,
        source_kind=SOURCE_KIND,
        local_date="2028-08-16",
        interruptible=True,
        now=1_850_000_002.0,
    )


def test_opportunity_identity_is_workspace_scoped_for_same_source(tmp_path: Path) -> None:
    store = ActivityFrameStore(tmp_path / "frames.sqlite3")
    _enable(store, "workspace-a", daily_budget=3)
    _enable(store, "workspace-b", daily_budget=3)
    service = ActivityFrameService(store, _TurnStore([]))
    scheduler = HeartbeatScheduler(job_event_log=CompanionJobEventLog())
    service.bind_scheduler(scheduler)
    service.project(_event(workspace="workspace-a", source_id="turn:same"))
    service.project(_event(workspace="workspace-b", source_id="turn:same", event_id=8))

    pending_a = store.pending_for_frame(
        "workspace-a", deterministic_frame_id(SOURCE_KIND, "turn:same")
    )
    pending_b = store.pending_for_frame(
        "workspace-b", deterministic_frame_id(SOURCE_KIND, "turn:same")
    )
    assert pending_a is not None and pending_b is not None
    assert pending_a["job_id"] != pending_b["job_id"]
    assert len(scheduler._opportunities) == 2


def test_old_job_primary_key_schema_migrates_without_losing_pending(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE proactive_opportunities (
              workspace_id TEXT NOT NULL,
              job_id TEXT PRIMARY KEY,
              request_id TEXT NOT NULL,
              frame_id TEXT NOT NULL,
              source_kind TEXT NOT NULL,
              local_date TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at REAL NOT NULL,
              resolved_at REAL
            );
            CREATE INDEX proactive_opportunity_budget_idx
              ON proactive_opportunities(workspace_id, local_date, status);
            INSERT INTO proactive_opportunities VALUES (
              'workspace-a', 'job:legacy', 'request:legacy', 'af_legacy',
              'completed_turn_followup', '2028-08-16', 'pending', 1, NULL
            );
            """
        )
    store = ActivityFrameStore(db_path)
    with store._connect() as conn:
        pk_columns = [
            row["name"]
            for row in conn.execute("PRAGMA table_info(proactive_opportunities)")
            if row["pk"]
        ]
        legacy = conn.execute(
            "SELECT workspace_id, job_id, status FROM proactive_opportunities"
        ).fetchone()
    assert pk_columns == ["workspace_id", "job_id"]
    assert tuple(legacy) == ("workspace-a", "job:legacy", "pending")


def test_bind_scheduler_restores_pending_once_with_visible_safe_payload(tmp_path: Path) -> None:
    db_path = tmp_path / "frames.sqlite3"
    store = ActivityFrameStore(db_path)
    _enable(store, daily_budget=3)
    frame = _frame(created_at=time.time(), expires_at=time.time() + 600)
    assert store.upsert_frame(frame)
    assert store.reserve_opportunity(
        "workspace-a",
        job_id="activityframejob_restart",
        request_id="activityframereq_restart",
        frame_id=frame.frame_id,
        source_kind=SOURCE_KIND,
        local_date=datetime.now(timezone.utc).date().isoformat(),
        interruptible=True,
        now=time.time(),
    )

    scheduler = HeartbeatScheduler(job_event_log=CompanionJobEventLog())
    restarted = ActivityFrameService(ActivityFrameStore(db_path), _TurnStore([]))
    restarted.bind_scheduler(scheduler)
    restarted.bind_scheduler(scheduler)

    assert scheduler._opportunities.keys() == {"activityframejob_restart"}
    assert len(scheduler.state.behavior_events) == 1
    visible = scheduler.state.behavior_events[0]
    assert {
        "job_id": visible["job_id"],
        "request_id": visible["request_id"],
        "source_kind": visible["source_kind"],
        "source_id": visible["source_id"],
        "frame_id": visible["frame_id"],
        "content_code": visible["content_code"],
    } == {
        "job_id": "activityframejob_restart",
        "request_id": "activityframereq_restart",
        "source_kind": SOURCE_KIND,
        "source_id": frame.source_id,
        "frame_id": frame.frame_id,
        "content_code": "completed_turn_followup",
    }
    assert isinstance(visible["tick"], int)
    assert visible["tick"] >= 0
    assert visible["at"].endswith("Z")
    datetime.fromisoformat(visible["at"].replace("Z", "+00:00"))
    assert visible["message"]
    stable_identity = (visible["tick"], visible["at"])
    restarted.bind_scheduler(scheduler)
    assert (scheduler.state.behavior_events[0]["tick"], scheduler.state.behavior_events[0]["at"]) == stable_identity
    serialized = json.dumps(visible, sort_keys=True)
    assert "SECRET" not in serialized
    assert scheduler.resolve_opportunity(
        job_id="activityframejob_restart",
        request_id="activityframereq_restart",
        outcome="delivered",
    )
    assert scheduler.state.behavior_events == []


@pytest.mark.parametrize(
    "policy_patch",
    [
        {"quietHours": {"enabled": True, "start": "00:00", "end": "00:00", "timezone": "UTC"}},
        {"dnd": True},
        {"enabled": False},
        {"sourceEnabled": {SOURCE_KIND: False}},
    ],
    ids=("quiet-hours", "dnd", "global-disabled", "source-disabled"),
)
def test_policy_patch_atomically_hides_pending_and_rejects_late_delivery(
    tmp_path: Path,
    policy_patch: dict[str, Any],
) -> None:
    store = ActivityFrameStore(tmp_path / "frames.sqlite3")
    _enable(store, daily_budget=2)
    scheduler = HeartbeatScheduler(job_event_log=CompanionJobEventLog())
    service = ActivityFrameService(store, _TurnStore([]))
    service.bind_scheduler(scheduler)
    now = time.time()
    projected = service.project(_event(created_at=now))
    frame_id = str(projected["frameId"])
    pending = store.pending_for_frame("workspace-a", frame_id)
    assert pending is not None
    assert len(scheduler.state.behavior_events) == 1

    service.patch_settings(
        "workspace-a",
        {"expectedRevision": 1, **policy_patch},
    )

    assert scheduler.state.behavior_events == []
    assert scheduler._opportunities == {}
    assert store.pending_for_frame("workspace-a", frame_id) is None
    assert not scheduler.resolve_opportunity(
        job_id=pending["job_id"],
        request_id=pending["request_id"],
        outcome="delivered",
    )
    frame = store.get_frame("workspace-a", frame_id)
    assert frame is not None
    assert store.evaluate("workspace-a", frame).remaining_budget == 2


def test_restart_cancels_disabled_deleted_and_expired_pending(tmp_path: Path) -> None:
    store = ActivityFrameStore(tmp_path / "frames.sqlite3")
    _enable(store, daily_budget=3)
    now = time.time()
    frame = _frame(created_at=now, expires_at=now + 600)
    assert store.upsert_frame(frame)
    assert store.reserve_opportunity(
        "workspace-a",
        job_id="job:disabled",
        request_id="request:disabled",
        frame_id=frame.frame_id,
        source_kind=SOURCE_KIND,
        local_date=datetime.now(timezone.utc).date().isoformat(),
        interruptible=True,
        now=now,
    )
    store.patch_settings(
        "workspace-a",
        {"completed_turn_followup_enabled": False},
        expected_revision=1,
    )
    scheduler = HeartbeatScheduler(job_event_log=CompanionJobEventLog())
    ActivityFrameService(store, _TurnStore([])).bind_scheduler(scheduler)
    assert scheduler.state.behavior_events == []
    assert store.pending_for_frame("workspace-a", frame.frame_id) is None


def test_restart_does_not_reanimate_deleted_or_expired_pending(tmp_path: Path) -> None:
    store = ActivityFrameStore(tmp_path / "frames.sqlite3")
    _enable(store, daily_budget=3)
    now = time.time()
    deleted = _frame(source_id="turn:deleted", created_at=now, expires_at=now + 600)
    expired = _frame(source_id="turn:expired", created_at=now, expires_at=now + 600)
    assert store.upsert_frame(deleted)
    assert store.upsert_frame(expired)
    for frame, suffix in ((deleted, "deleted"), (expired, "expired")):
        assert store.reserve_opportunity(
            "workspace-a",
            job_id=f"job:{suffix}",
            request_id=f"request:{suffix}",
            frame_id=frame.frame_id,
            source_kind=SOURCE_KIND,
            local_date=datetime.now(timezone.utc).date().isoformat(),
            interruptible=True,
            now=now,
        )
    assert store.delete_frame("workspace-a", deleted.frame_id, now=now + 1)
    with store._connect() as conn:
        conn.execute(
            "UPDATE activity_frames SET expires_at = ? WHERE workspace_id = ? AND frame_id = ?",
            (now - 1, "workspace-a", expired.frame_id),
        )
        conn.execute(
            "UPDATE proactive_opportunities SET expires_at = ? WHERE workspace_id = ? AND job_id = ?",
            (now - 1, "workspace-a", "job:expired"),
        )
    scheduler = HeartbeatScheduler(job_event_log=CompanionJobEventLog())
    ActivityFrameService(store, _TurnStore([])).bind_scheduler(scheduler)

    assert scheduler.state.behavior_events == []
    assert scheduler._opportunities == {}
    assert store.pending_for_frame("workspace-a", deleted.frame_id) is None
    assert store.pending_for_frame("workspace-a", expired.frame_id) is None
