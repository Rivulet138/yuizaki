from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest

from modules.agent.turn_service import TurnClaimLostError
from modules.agent.turn_store import TurnCommitStore


_CHILD = Path(__file__).parent / "fixtures" / "turn_store_crash_child.py"


def _run_crash_child(
    db_path: Path,
    marker_path: Path,
    *,
    scenario: str,
    phase: str,
    wall_time: float = 1000.0,
) -> dict[str, object]:
    environment = os.environ.copy()
    python_root = str(Path(__file__).parents[1])
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (python_root, environment.get("PYTHONPATH", "")) if value
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(_CHILD),
            "--db",
            str(db_path),
            "--marker",
            str(marker_path),
            "--scenario",
            scenario,
            "--phase",
            phase,
            "--wall-time",
            str(wall_time),
        ],
        cwd=python_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    assert completed.returncode == 91, completed.stderr or completed.stdout
    with marker_path.open(encoding="utf-8") as handle:
        marker = json.load(handle)
    assert marker["phase"] == phase
    return marker


def _row_counts(db_path: Path) -> tuple[int, int]:
    with sqlite3.connect(db_path) as conn:
        commits = int(conn.execute("SELECT COUNT(*) FROM turn_commits").fetchone()[0])
        outbox = int(conn.execute("SELECT COUNT(*) FROM turn_outbox").fetchone()[0])
    return commits, outbox


def _stale_commit(owner_id: str, fencing_token: int) -> SimpleNamespace:
    context = SimpleNamespace(
        workspace_id="crash-workspace",
        session_id="crash-session",
        request_id="crash-request",
        turn_id="crash-turn",
        generation_id="crash-generation",
        interruption_epoch=7,
        autonomy_mode="read_only",
        model=None,
        messages=[],
        extra={},
    )
    result = SimpleNamespace(
        reply="stale result",
        pet_control=None,
        tool_calls=[],
        action_envelope=None,
    )
    return SimpleNamespace(
        idempotency_key="turn:crashed-owner",
        semantic_fingerprint="claim-fingerprint",
        trigger="http",
        context=context,
        result=result,
        claim_owner=owner_id,
        claim_fencing_token=fencing_token,
    )


def test_crash_before_persist_leaves_no_partial_commit_or_outbox(tmp_path: Path) -> None:
    db_path = tmp_path / "before-persist.sqlite3"
    _run_crash_child(
        db_path,
        tmp_path / "before-persist.marker",
        scenario="persist",
        phase="persist.before",
    )

    assert _row_counts(db_path) == (0, 0)
    assert TurnCommitStore(db_path).load("turn:crash-boundary") is None


def test_crash_after_atomic_commit_reopens_one_commit_and_pending_outbox(tmp_path: Path) -> None:
    db_path = tmp_path / "after-commit.sqlite3"
    _run_crash_child(
        db_path,
        tmp_path / "after-commit.marker",
        scenario="persist",
        phase="persist.committed",
    )

    reopened = TurnCommitStore(db_path)
    stored = reopened.load("turn:crash-boundary")
    assert _row_counts(db_path) == (1, 1)
    assert stored is not None
    assert stored["result"]["turn_id"] == "crash-turn"
    assert stored["result"]["generation_id"] == "crash-generation"
    assert stored["result"]["interruption_epoch"] == 7
    assert stored["result"]["configured_budget"] == {"max_steps": 4}
    assert stored["result"]["consumed_usage"] == {"steps": 1}
    assert len(reopened.pending_outbox()) == 1


def test_crash_after_projection_ack_replays_delivery_idempotently(tmp_path: Path) -> None:
    db_path = tmp_path / "after-projection-ack.sqlite3"
    _run_crash_child(
        db_path,
        tmp_path / "after-projection-ack.marker",
        scenario="projection_ack",
        phase="outbox_projection.acknowledged",
    )

    reopened = TurnCommitStore(
        db_path,
        wall_clock=lambda: 1011.0,
        monotonic_clock=lambda: 1011.0,
    )
    event = reopened.claim_next_outbox("recovery-dispatcher", lease_seconds=10.0)
    assert event is not None and event["status"] == "claimed"
    event_id = int(event["event_id"])
    assert reopened.acknowledged_projections(event_id) == {"idempotent-projection"}
    assert (
        reopened.acknowledge_projection(
            event_id,
            "idempotent-projection",
            "recovery-dispatcher",
        )
        is False
    )
    assert reopened.acknowledge(event_id, "recovery-dispatcher") is True
    assert reopened.pending_outbox() == []
    assert _row_counts(db_path) == (1, 1)


def test_crashed_claim_is_fenced_after_lease_takeover(tmp_path: Path) -> None:
    db_path = tmp_path / "stale-claim.sqlite3"
    marker = _run_crash_child(
        db_path,
        tmp_path / "stale-claim.marker",
        scenario="claim",
        phase="turn_claim.acquired",
    )
    stale_token = int(marker["details"]["fencing_token"])  # type: ignore[index]

    reopened = TurnCommitStore(
        db_path,
        wall_clock=lambda: 1011.0,
        monotonic_clock=lambda: 1011.0,
    )
    takeover = reopened.claim(
        "turn:crashed-owner",
        "claim-fingerprint",
        "owner-after-crash",
        lease_seconds=10.0,
    )
    assert takeover["status"] == "claimed"
    assert int(takeover["fencing_token"]) > stale_token

    with pytest.raises(TurnClaimLostError):
        reopened.persist(_stale_commit("owner-before-crash", stale_token))
    assert reopened.load("turn:crashed-owner") is None

    current = _stale_commit("owner-after-crash", int(takeover["fencing_token"]))
    reopened.persist(current)
    reopened.persist(SimpleNamespace(**{**current.__dict__, "claim_owner": None}))
    assert reopened.load("turn:crashed-owner") is not None
    assert _row_counts(db_path) == (1, 1)
