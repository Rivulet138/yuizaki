from __future__ import annotations

from modules.agent.context import AgentPipelineResult, AgentRequestContext
from modules.agent.turn_service import TurnCommit
from modules.agent.turn_store import TurnCommitStore


def _persist_recovery(tmp_path):
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    context = AgentRequestContext(
        sid="sid-1",
        session_id="session-1",
        workspace_id="workspace-1",
        request_id="request-1",
        turn_id="turn-1",
        messages=[{"role": "user", "content": "retry"}],
    )
    result = AgentPipelineResult(
        reply="",
        outcome="failed",
        retryable=True,
        recovery={
            "available": True,
            "action": "resume_failed_step",
            "failed_step_id": "step-1",
            "retryable": True,
            "confirmation_required": False,
            "scope": "turn",
            "single_use": True,
            "handle": "rh_test_handle",
        },
    )
    commit = TurnCommit(
        idempotency_key="turn-key",
        semantic_fingerprint="fingerprint",
        trigger="http",
        context=context,
        result=result,
    )
    store.persist(commit)
    return store


def test_same_process_replay_keeps_recovery_handle_but_hides_epoch(tmp_path) -> None:
    store = _persist_recovery(tmp_path)

    loaded = store.load("turn-key")

    assert loaded is not None
    recovery = loaded["result"]["recovery"]
    assert recovery["available"] is True
    assert recovery["handle"] == "rh_test_handle"
    assert "_process_epoch" not in recovery


def test_recovery_descriptor_fails_closed_after_process_epoch_changes(tmp_path, monkeypatch) -> None:
    store = _persist_recovery(tmp_path)
    import modules.agent.turn_store as turn_store_module

    monkeypatch.setattr(turn_store_module, "_PROCESS_RECOVERY_EPOCH", "new-process")
    loaded = store.load("turn-key")

    assert loaded is not None
    recovery = loaded["result"]["recovery"]
    assert recovery == {
        "scope": "turn",
        "single_use": True,
        "failed_step_id": "step-1",
        "available": False,
        "action": "inspect_failure",
        "retryable": False,
        "confirmation_required": True,
        "reason": "process_state_missing",
    }
    assert "handle" not in recovery


def test_outbox_and_rebuild_replays_fail_closed_after_process_epoch_changes(tmp_path, monkeypatch) -> None:
    store = _persist_recovery(tmp_path)
    import modules.agent.turn_store as turn_store_module

    monkeypatch.setattr(turn_store_module, "_PROCESS_RECOVERY_EPOCH", "new-process")

    listed = store.list_commits("workspace-1")
    pending = store.pending_outbox()
    claimed = store.claim_next_outbox("replay-worker")

    payloads = [listed[0]["payload"], pending[0]["payload"], claimed["payload"]]
    for payload in payloads:
        recovery = payload["recovery"]
        assert recovery["available"] is False
        assert recovery["reason"] == "process_state_missing"
        assert "handle" not in recovery
        assert "_process_epoch" not in recovery
