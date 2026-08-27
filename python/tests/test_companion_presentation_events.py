from __future__ import annotations

import pytest
from modules.agent.companion_events import (
    CompanionJobEventAdapter,
    CompanionJobEventLog,
    CompanionPresentationCapacityError,
    CompanionPresentationEventLog,
    CompanionPresentationStaleEventError,
    CompanionPresentationTerminalError,
)
from modules.system.companion_runtime import _project_job_events


def _append(log: CompanionPresentationEventLog, stream: str, event_type: str, revision: int | None = None):
    return log.append(
        stream_id=stream,
        event_type=event_type,
        revision=revision,
        workspace_id="ws",
        session_id="session",
        turn_id="turn",
        request_id="request",
        generation_id="generation",
        payload={"value": event_type},
    )


def test_presentation_log_enforces_identity_revision_and_terminal_state() -> None:
    log = CompanionPresentationEventLog()
    first = _append(log, "stream-1", "thinking", 1)
    assert first is not None and first["revision"] == 1

    duplicate = _append(log, "stream-1", "thinking", 1)
    assert duplicate is not None and duplicate["duplicate"] is True

    with pytest.raises(CompanionPresentationStaleEventError):
        _append(log, "stream-1", "different", 1)
    with pytest.raises(CompanionPresentationStaleEventError):
        _append(log, "stream-1", "progress", 3)
    with pytest.raises(ValueError, match="identity"):
        log.append(
            stream_id="stream-1",
            event_type="progress",
            revision=2,
            workspace_id="other",
            session_id="session",
            turn_id="turn",
        )

    _append(log, "stream-1", "progress", 2)
    _append(log, "stream-1", "completed", 3)
    with pytest.raises(CompanionPresentationTerminalError):
        _append(log, "stream-1", "progress", 4)
    assert [item["revision"] for item in log.snapshot()] == [1, 2, 3]


def test_high_frequency_events_are_excluded_before_stream_allocation() -> None:
    log = CompanionPresentationEventLog(max_streams=1)
    assert _append(log, "tokens", "token", 1) is None
    assert _append(log, "audio", "audio_chunk", 1) is None
    assert _append(log, "frames", "avatar_frame", 1) is None
    assert _append(log, "frame-ready", "AvatarFrameReady", 1) is None
    assert _append(log, "audio-ready", "AudioChunkReady", 1) is None
    assert _append(log, "viseme", "VisemeReady", 1) is None
    assert log.snapshot() == []
    assert log.active_stream_ids() == []


def test_low_frequency_voice_lifecycle_is_retained_and_terminal_suffixes_close_streams() -> None:
    log = CompanionPresentationEventLog()
    assert _append(log, "voice", "VoiceStarted", 1) is not None
    completed = _append(log, "voice", "VoiceCompleted", 2)
    assert completed is not None and completed["terminal"] is True

    assert _append(log, "cancelled", "VoiceStarted", 1) is not None
    cancelled = _append(log, "cancelled", "VoiceCancelled", 2)
    assert cancelled is not None and cancelled["terminal"] is True

    assert _append(log, "interrupted", "VoiceStarted", 1) is not None
    interrupted = _append(log, "interrupted", "VoiceInterrupted", 2)
    assert interrupted is not None and interrupted["terminal"] is True


def test_capacity_preserves_active_streams_and_evicts_terminal_streams() -> None:
    log = CompanionPresentationEventLog(max_streams=1)
    _append(log, "active", "thinking", 1)
    with pytest.raises(CompanionPresentationCapacityError):
        _append(log, "other", "thinking", 1)

    _append(log, "active", "completed", 2)
    with pytest.raises(CompanionPresentationStaleEventError):
        _append(log, "invalid", "thinking", 2)
    assert log.contains("active") is True
    _append(log, "other", "thinking", 1)
    assert log.contains("active") is False
    assert log.contains("other") is True


def test_job_log_projects_accepted_events_without_changing_legacy_behavior() -> None:
    presentation = CompanionPresentationEventLog()
    jobs = CompanionJobEventLog(presentation_log=presentation)
    common = {
        "workspace_id": "ws",
        "session_id": "session",
        "turn_id": "turn",
        "request_id": "request",
        "interruption_epoch": 0,
        "source": "tool",
        "timestamp": 1.0,
        "job_id": "job-1",
    }
    jobs.append(status="created", data={"name": "open"}, **common)
    jobs.append(status="running", data={"step": 1}, timestamp=2.0, **{key: value for key, value in common.items() if key != "timestamp"})
    jobs.append(status="completed", data={"ok": True}, timestamp=3.0, **{key: value for key, value in common.items() if key != "timestamp"})

    projected = presentation.snapshot()
    assert [item["type"] for item in projected] == [
        "AgentJobCreated", "AgentJobRunning", "AgentJobCompleted",
    ]
    assert [item["revision"] for item in projected] == [1, 2, 3]
    assert projected[-1]["terminal"] is True

    # High-frequency envelopes are ignored by the adapter before they allocate
    # presentation state; the legacy job log remains unchanged.
    adapter = CompanionJobEventAdapter(presentation)
    assert adapter.append({"type": "token", "streamId": "token-stream", "revision": 1}) is None
    assert len(jobs.snapshot()) == 3
    assert len(presentation.snapshot()) == 3


def test_redacted_job_args_disable_local_replay_without_server_recheck() -> None:
    projected = _project_job_events([{
        "type": "AgentJobFailed",
        "status": "failed",
        "args": {"path": "[REDACTED]"},
        "replayArgsAvailable": True,
    }])
    assert projected[0]["replayArgsAvailable"] is False


def test_redacted_job_args_allow_replay_when_server_recheck_is_available() -> None:
    projected = _project_job_events([{
        "type": "AgentJobFailed",
        "status": "failed",
        "args": {"path": "[REDACTED]"},
        "replayArgsAvailable": True,
        "recheckAvailable": True,
    }])
    assert projected[0]["replayArgsAvailable"] is True
