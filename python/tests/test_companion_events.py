from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from modules.agent.companion_events import (
    CompanionJobCapacityError,
    CompanionJobEventLog,
    CompanionPresentationEventLog,
)


def _append(
    log: CompanionJobEventLog,
    *,
    workspace_id: str = "workspace-1",
    job_id: str = "job-1",
    status: str,
    timestamp: float,
    data: dict[str, object] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    return log.append(
        workspace_id=workspace_id,
        session_id="session-1",
        turn_id="turn-1",
        job_id=job_id,
        request_id="request-1",
        interruption_epoch=0,
        source="test",
        timestamp=timestamp,
        status=status,
        data=data,
        idempotency_key=idempotency_key,
    )


def test_long_progress_keeps_terminal_and_rejects_post_terminal_events() -> None:
    log = CompanionJobEventLog(max_jobs=1, max_events_per_job=4)
    _append(log, status="created", timestamp=1.0)
    for index in range(100):
        _append(log, status="progress", timestamp=2.0 + index * 0.2, data={"index": index})

    completed = _append(log, status="completed", timestamp=30.0, data={"verified": True})
    assert completed["status"] == "completed"
    latest = log.latest("job-1", "workspace-1")
    assert latest is not None
    assert latest["status"] == "completed"
    assert latest["revision"] == 102
    assert len(log.snapshot()) == 4
    assert log.snapshot()[-1]["status"] == "completed"

    with pytest.raises(ValueError, match="terminal companion job"):
        _append(log, status="progress", timestamp=31.0)

    recheck = log.append_recheck(
        job_id="job-1",
        workspace_id="workspace-1",
        timestamp=32.0,
        data={"verificationStatus": "verified"},
    )
    assert recheck["status"] == "completed"
    assert recheck["data"]["recheck"] is True
    assert recheck["revision"] == 103


def test_capacity_evicts_terminal_jobs_but_preserves_active_jobs() -> None:
    log = CompanionJobEventLog(max_jobs=2)
    _append(log, job_id="terminal", status="created", timestamp=1.0)
    _append(log, job_id="terminal", status="completed", timestamp=2.0)
    _append(log, job_id="active-1", status="created", timestamp=3.0)

    _append(log, job_id="active-2", status="created", timestamp=4.0)
    assert log.contains("terminal") is False
    assert log.contains("active-1") is True
    assert log.contains("active-2") is True

    with pytest.raises(CompanionJobCapacityError):
        _append(log, job_id="active-3", status="created", timestamp=5.0)
    assert sorted(log.active_job_ids()) == ["active-1", "active-2"]


def test_workspace_identity_and_projection_failures_do_not_corrupt_authority() -> None:
    class BrokenPresentationLog:
        def append_event(self, _event: object) -> None:
            raise RuntimeError("presentation unavailable")

    log = CompanionJobEventLog(presentation_log=BrokenPresentationLog())
    _append(log, workspace_id="workspace-a", job_id="shared", status="created", timestamp=1.0)
    _append(log, workspace_id="workspace-a", job_id="shared", status="completed", timestamp=2.0)
    _append(log, workspace_id="workspace-b", job_id="shared", status="created", timestamp=3.0)
    assert log.latest("shared", "workspace-a")["status"] == "completed"
    assert log.latest("shared", "workspace-b")["status"] == "created"

    with pytest.raises(ValueError, match="identity changed"):
        log.append(
            workspace_id="workspace-b",
            session_id="other-session",
            turn_id="turn-1",
            job_id="shared",
            request_id="request-1",
            interruption_epoch=0,
            source="test",
            timestamp=4.0,
            status="progress",
        )

    duplicate = _append(
        log,
        workspace_id="workspace-b",
        job_id="shared",
        status="progress",
        timestamp=4.0,
        idempotency_key="progress-1",
    )
    repeated = _append(
        log,
        workspace_id="workspace-b",
        job_id="shared",
        status="progress",
        timestamp=4.2,
        idempotency_key="progress-1",
    )
    assert duplicate["revision"] == repeated["revision"]
    assert repeated["duplicate"] is True


def test_concurrent_progress_has_bounded_unique_revisions() -> None:
    log = CompanionJobEventLog(max_jobs=1, max_events_per_job=16)
    _append(log, status="created", timestamp=1.0)

    def append_progress(index: int) -> dict[str, object]:
        return _append(log, status="progress", timestamp=2.0 + index * 0.2, data={"index": index})

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(append_progress, range(40)))

    revisions = [int(event["revision"]) for event in log.snapshot()]
    assert revisions == sorted(set(revisions))
    assert len(log.snapshot()) <= 16
    assert all(result["status"] == "progress" for result in results)


def test_presentation_log_rejects_gaps_and_preserves_terminal_state() -> None:
    log = CompanionPresentationEventLog(max_streams=1)
    first = log.append(stream_id="stream-1", event_type="created", revision=1)
    assert first is not None
    with pytest.raises(ValueError, match="revision gap"):
        log.append(stream_id="stream-1", event_type="progress", revision=3)

    terminal = log.append(stream_id="stream-1", event_type="completed", revision=2)
    assert terminal is not None and terminal["terminal"] is True
    with pytest.raises(ValueError, match="terminal presentation"):
        log.append(stream_id="stream-1", event_type="progress", revision=3)


def test_job_payload_is_redacted_and_bounded_before_durable_storage() -> None:
    log = CompanionJobEventLog()
    payload = {
        "api_key": "do-not-store",
        "nested": {"authorization": "Bearer secret", "text": "x" * 700},
        "items": list(range(30)),
        "deep": {"a": {"b": {"c": {"d": {"e": {"f": "hidden"}}}}}},
    }
    event = _append(log, status="created", timestamp=1.0, data=payload)

    assert event["data"]["api_key"] == "[REDACTED]"
    assert event["data"]["nested"]["authorization"] == "[REDACTED]"
    assert event["data"]["nested"]["text"] == ("x" * 509) + "..."
    assert event["data"]["items"][-1] == "[TRUNCATED 14 ITEMS]"
    assert event["data"]["deep"]["a"]["b"]["c"]["d"]["e"] == "[TRUNCATED]"
    assert payload["api_key"] == "do-not-store"


def test_recheck_payload_is_sanitized_before_merge() -> None:
    log = CompanionJobEventLog()
    _append(log, status="created", timestamp=1.0, data={"existing": "ok"})
    event = log.append_recheck(
        job_id="job-1",
        workspace_id="workspace-1",
        timestamp=2.0,
        data={"token": "secret", "details": "y" * 700},
    )
    assert event["data"]["existing"] == "ok"
    assert event["data"]["token"] == "[REDACTED]"
    assert event["data"]["details"] == ("y" * 509) + "..."


def test_job_error_redacts_token_bearing_text() -> None:
    log = CompanionJobEventLog()
    error = "POST https://example.test/send?bot_token=secret-token failed: Bearer another-secret"

    event = _append(log, status="created", timestamp=1.0)
    assert event["status"] == "created"
    failed = _append(log, status="failed", timestamp=2.0, data={"error": error})

    assert "secret-token" not in str(failed)
    assert "another-secret" not in str(failed)
    assert failed["data"]["error"].count("[REDACTED]") == 2
