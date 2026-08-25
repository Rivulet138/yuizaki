from __future__ import annotations

import pytest

from modules.agent.stage_port import (
    EncryptedSyncCodec,
    StageEvent,
    StageSession,
    SyncEncryptionUnavailable,
)


def test_stage_event_is_workspace_and_session_scoped() -> None:
    session = StageSession("web", "workspace-1", "session-1", "subject-1")
    event = StageEvent(1, "event-1", "workspace-1", "session-1", "turn-1", "gen-1", "turn.completed")
    event.validate(session)
    with pytest.raises(PermissionError, match="scope_mismatch"):
        StageEvent(1, "event-2", "workspace-2", "session-1", "turn-1", None, "turn.completed").validate(session)


def test_stage_event_rejects_unknown_schema() -> None:
    session = StageSession("web", "workspace-1", "session-1", "subject-1")
    with pytest.raises(ValueError, match="unsupported_stage_event_schema"):
        StageEvent(2, "event-1", "workspace-1", "session-1", "turn-1", None, "turn.completed").validate(session)


def test_sync_fails_closed_without_injected_aead() -> None:
    with pytest.raises(SyncEncryptionUnavailable):
        EncryptedSyncCodec().encode(b"private memory")
