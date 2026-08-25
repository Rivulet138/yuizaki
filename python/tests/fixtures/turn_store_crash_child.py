"""Isolated process used by the TurnCommitStore crash-boundary tests."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from modules.agent.turn_store import TurnCommitStore


def _fsync_marker(path: Path, phase: str, details: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump({"phase": phase, "details": details}, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())


def _commit() -> SimpleNamespace:
    context = SimpleNamespace(
        workspace_id="crash-workspace",
        session_id="crash-session",
        request_id="crash-request",
        turn_id="crash-turn",
        generation_id="crash-generation",
        interruption_epoch=7,
        autonomy_mode="read_only",
        model="crash-model",
        messages=[{"role": "user", "content": "persist safely"}],
        extra={
            "turn_id": "legacy-turn",
            "generation_id": "legacy-generation",
            "interruption_epoch": 1,
        },
    )
    result = SimpleNamespace(
        reply="durable reply",
        pet_control=None,
        tool_calls=[],
        action_envelope=None,
        outcome="completed",
        retryable=False,
        configured_budget={"max_steps": 4},
        consumed_usage={"steps": 1},
    )
    return SimpleNamespace(
        idempotency_key="turn:crash-boundary",
        semantic_fingerprint="crash-fingerprint",
        trigger="http",
        context=context,
        result=result,
        claim_owner=None,
        claim_fencing_token=None,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--marker", type=Path, required=True)
    parser.add_argument("--scenario", choices=("persist", "claim", "projection_ack"), required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--wall-time", type=float, default=1000.0)
    args = parser.parse_args()

    def barrier(phase: str, details: dict[str, Any]) -> None:
        if phase != args.phase:
            return
        _fsync_marker(args.marker, phase, details)
        os._exit(91)

    store = TurnCommitStore(
        args.db,
        wall_clock=lambda: args.wall_time,
        monotonic_clock=lambda: args.wall_time,
        barrier=barrier,
    )
    if args.scenario == "persist":
        store.persist(_commit())
    elif args.scenario == "claim":
        store.claim(
            "turn:crashed-owner",
            "claim-fingerprint",
            "owner-before-crash",
            lease_seconds=10.0,
        )
    else:
        store.persist(_commit())
        event = store.claim_next_outbox("crashed-dispatcher", lease_seconds=10.0)
        if event is None or event.get("status") != "claimed":
            raise RuntimeError("fixture could not claim its outbox event")
        store.acknowledge_projection(
            int(event["event_id"]),
            "idempotent-projection",
            "crashed-dispatcher",
        )
    raise RuntimeError(f"crash barrier was not reached: {args.phase}")


if __name__ == "__main__":
    main()
