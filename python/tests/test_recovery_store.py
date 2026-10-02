import sqlite3

import pytest
from modules.agent.planner import ToolStep
from modules.agent.recovery_store import (
    RecoverySerializationError,
    SQLiteStepRecoveryStore,
    deserialize_tool_step,
    serialize_tool_step,
)


def _step() -> ToolStep:
    return ToolStep(id="s1", title="call", tool_name="web_search", arguments={"q": "x"})


def test_typed_tool_step_round_trip_is_canonical() -> None:
    encoded = serialize_tool_step(_step())
    restored = deserialize_tool_step(encoded)
    assert restored == _step()
    assert encoded == serialize_tool_step(restored)


@pytest.mark.parametrize("payload", [{"kind": "tool"}, {"kind": "agent", "plan_version": 2}])
def test_parser_rejects_incomplete_or_wrong_kind(payload) -> None:
    with pytest.raises(RecoverySerializationError):
        deserialize_tool_step(payload)


def test_parser_rejects_duplicate_or_non_finite_json() -> None:
    with pytest.raises(RecoverySerializationError):
        deserialize_tool_step('{"kind":"tool","kind":"tool"}')
    with pytest.raises(RecoverySerializationError):
        deserialize_tool_step('{"kind":"tool","plan_version":2,"id":"s1","title":"x","tool_name":"x","arguments":{"q":NaN},"timeout_seconds":30,"retry_budget":0,"retry_owner":"step_executor","idempotency_key":"plan:s1","success_criteria":{"op":"status_in","values":["ok"]}}')


def test_store_claim_is_atomic_and_survives_restart(tmp_path) -> None:
    path = tmp_path / "recovery.sqlite3"
    store = SQLiteStepRecoveryStore(path)
    store.put("r1", _step(), next_attempt_at=10)
    assert store.get("r1") == _step()
    claimed = store.claim_due("worker-a", now=10)
    assert claimed is not None and claimed[0] == "r1"
    assert store.claim_due("worker-b", now=10) is None
    assert store.finish("r1", success=True, owner="worker-a", fencing_token=claimed[2]) is True
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT status, attempts FROM step_recoveries WHERE recovery_id='r1'").fetchone() == ("succeeded", 1)


def test_store_persists_scope_metadata_and_reaps_expired_markers(tmp_path) -> None:
    path = tmp_path / "recovery.sqlite3"
    store = SQLiteStepRecoveryStore(path)
    store.put(
        "scoped",
        _step(),
        next_attempt_at=10,
        expires_at=20,
        workspace_id="workspace-a",
        session_id="session-a",
        turn_id="turn-a",
        failed_step_id="s1",
        plan_hash="hash-a",
    )
    with sqlite3.connect(path) as db:
        row = db.execute(
            "SELECT workspace_id,session_id,turn_id,failed_step_id,plan_hash FROM step_recoveries WHERE recovery_id='scoped'"
        ).fetchone()
    assert row == ("workspace-a", "session-a", "turn-a", "s1", "hash-a")
    assert store.reap_expired(now=20) == 1
    assert store.get("scoped") is None


def test_store_never_persists_untyped_or_malformed_step(tmp_path) -> None:
    store = SQLiteStepRecoveryStore(tmp_path / "recovery.sqlite3")
    with pytest.raises(RecoverySerializationError):
        store.put("bad", ToolStep(id="x", title="x", tool_name="x", plan_version=1, payload={"tool_name": "x"}))


def test_store_rejects_unsupported_future_plan_version(tmp_path) -> None:
    store = SQLiteStepRecoveryStore(tmp_path / "recovery.sqlite3")
    with pytest.raises(RecoverySerializationError, match="typed_plan"):
        store.put("future", ToolStep(id="x", title="x", tool_name="x", plan_version=3))


def test_store_rejects_steps_that_need_upstream_state(tmp_path) -> None:
    store = SQLiteStepRecoveryStore(tmp_path / "recovery.sqlite3")
    with pytest.raises(RecoverySerializationError, match="independent"):
        store.put("dependent", ToolStep(id="x", title="x", tool_name="x", depends_on=["prior"]))


def test_secret_arguments_are_rejected(tmp_path) -> None:
    store = SQLiteStepRecoveryStore(tmp_path / "nested" / "recovery.sqlite3")
    with pytest.raises(RecoverySerializationError, match="secret"):
        store.put("secret", ToolStep(id="x", title="x", tool_name="x", arguments={"authorization": "Bearer x"}))


def test_expired_claim_can_be_reclaimed_and_owner_is_fenced(tmp_path) -> None:
    store = SQLiteStepRecoveryStore(tmp_path / "recovery.sqlite3")
    store.put("r1", _step(), next_attempt_at=0)
    first_claim = store.claim_due("a", now=0)
    assert first_claim is not None
    with pytest.raises(TypeError):
        store.finish("r1", success=True)  # owner is mandatory
    second_claim = store.claim_due("b", now=61)
    assert second_claim is not None
    assert store.finish("r1", success=True, owner="a", fencing_token=first_claim[2]) is False
    assert store.finish("r1", success=True, owner="b", fencing_token=second_claim[2]) is True


def test_finish_requires_the_current_fencing_token(tmp_path) -> None:
    store = SQLiteStepRecoveryStore(tmp_path / "recovery.sqlite3")
    store.put("r1", _step(), next_attempt_at=0)
    claimed = store.claim_due("worker", now=0)
    assert claimed is not None
    with pytest.raises(TypeError):
        store.finish("r1", success=True, owner="worker")  # fencing token is mandatory
    assert store.finish("r1", success=True, owner="worker", fencing_token="wrong") is False
    assert store.finish("r1", success=True, owner="worker", fencing_token=claimed[2]) is True


def test_recovery_attempts_are_bounded_after_expired_leases(tmp_path) -> None:
    store = SQLiteStepRecoveryStore(tmp_path / "recovery.sqlite3")
    store.put("bounded", _step(), next_attempt_at=0)
    claims = []
    for now in (0, 61, 122):
        claim = store.claim_due(f"worker-{now}", now=now)
        assert claim is not None
        claims.append(claim)
    assert store.claim_due("worker-183", now=183) is None


def test_durable_context_result_and_scoped_claim_are_bounded_and_fenced(tmp_path) -> None:
    store = SQLiteStepRecoveryStore(tmp_path / "recovery.sqlite3")
    store.put(
        "durable", _step(), workspace_id="w", session_id="s", turn_id="t",
        failed_step_id="s1", plan_hash="p", context_snapshot={"input": "safe"},
    )
    assert store.claim_recovery("durable", "worker", workspace_id="wrong") is None
    assert store.claim_recovery("durable", "worker", workspace_id="w", session_id="s", turn_id="t") is None
    claim = store.claim_recovery("durable", "worker", workspace_id="w", session_id="s", turn_id="t", failed_step_id="s1", now=1)
    assert claim is not None and claim["record"]["context_snapshot"] == {"input": "safe"}
    assert store.finish("durable", success=True, owner="worker", fencing_token=claim["fencing_token"], result={"ok": True})
    record = store.get_recovery("durable")
    assert record is not None and record["status"] == "succeeded" and record["result"] == {"ok": True}


@pytest.mark.parametrize("field", ["context_snapshot", "result"])
def test_durable_snapshots_reject_secrets_and_oversize(tmp_path, field) -> None:
    store = SQLiteStepRecoveryStore(tmp_path / "recovery.sqlite3")
    with pytest.raises(RecoverySerializationError, match="secret"):
        store.put("secret", _step(), **{field: {"api_key": "hidden"}})
    with pytest.raises(RecoverySerializationError, match="too_large"):
        store.put("large", _step(), **{field: {"value": "x" * (256 * 1024)}})
