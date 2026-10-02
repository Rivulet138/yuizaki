"""Durable, bounded storage for retryable typed tool steps.

This module deliberately stores a canonical ToolStep document rather than an
opaque pickle.  Recovery consumers can therefore fail closed on schema drift
or malformed rows after a process restart.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .planner import ToolStep, strict_json_loads, validate_plan


class RecoverySerializationError(ValueError):
    """Raised when a recovery row cannot be safely serialized or reloaded."""

    pass


_MAX_RECOVERY_JSON_BYTES = 256 * 1024
_MAX_RECOVERY_ATTEMPTS = 3


def _serialize_snapshot(value: Any, *, label: str) -> str | None:
    """Serialize restart metadata as bounded JSON.

    Snapshots are advisory inputs for a fresh runtime.  They are rejected when
    they contain non-JSON values, secret-looking keys, or exceed the size
    budget; executable objects and credentials therefore never cross the
    process boundary.
    """
    if value is None:
        return None
    if label == "context" and not isinstance(value, dict):
        raise RecoverySerializationError("recovery_context_invalid")
    try:
        _check_args(value)
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except RecoverySerializationError:
        raise
    except Exception as exc:
        raise RecoverySerializationError(f"recovery_{label}_invalid") from exc
    if len(encoded.encode("utf-8")) > _MAX_RECOVERY_JSON_BYTES:
        raise RecoverySerializationError(f"recovery_{label}_too_large")
    return encoded


def _deserialize_snapshot(document: str | None, *, label: str) -> Any:
    """Decode and re-validate one persisted snapshot before it reaches runtime."""
    if document is None:
        return None
    try:
        value = strict_json_loads(document, path=f"recovery {label}")
        _check_args(value)
        return value
    except RecoverySerializationError:
        raise
    except Exception as exc:
        raise RecoverySerializationError(f"recovery_{label}_invalid") from exc


def serialize_tool_step(step: ToolStep) -> str:
    """Encode one independent typed ToolStep using the durable schema.

    Validation happens before writing so a row is either a complete, reloadable
    step or no row is written.  Dependency-bearing and conditional steps are
    intentionally excluded because their upstream execution context is not
    persisted here.
    """
    if not isinstance(step, ToolStep):
        raise RecoverySerializationError("recovery_step_must_be_tool_step")
    # The durable document currently has one strict schema.  Accepting a
    # future version here would write a row that this process cannot reload.
    if step.plan_version != 2:
        raise RecoverySerializationError("recovery_step_requires_typed_plan")
    if step.condition is not None or step.depends_on:
        raise RecoverySerializationError("recovery_step_requires_independent_step")
    try:
        _check_args(step.arguments)
        validate_plan([step])
        payload = step.to_dict()
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 256 * 1024:
            raise RecoverySerializationError("recovery_step_too_large")
        return encoded
    except RecoverySerializationError:
        raise
    except Exception as exc:
        raise RecoverySerializationError("recovery_step_invalid") from exc


def deserialize_tool_step(document: str | bytes | dict[str, Any]) -> ToolStep:
    """Strictly decode a stored ToolStep and reject schema or effect drift."""
    try:
        value = strict_json_loads(document, path="recovery step") if isinstance(document, (str, bytes)) else document
    except (TypeError, ValueError) as exc:
        raise RecoverySerializationError("recovery_step_invalid_json") from exc
    if not isinstance(value, dict):
        raise RecoverySerializationError("recovery_step_document_must_be_object")
    allowed = set(asdict(ToolStep(id="_", title="_")).keys())
    if set(value) - allowed:
        raise RecoverySerializationError("recovery_step_unknown_field")
    if value.get("kind") != "tool" or value.get("plan_version") != 2:
        raise RecoverySerializationError("recovery_step_requires_typed_tool")
    required = ("id", "title", "tool_name", "arguments", "timeout_seconds", "retry_budget", "retry_owner", "idempotency_key", "success_criteria")
    if any(key not in value for key in required):
        raise RecoverySerializationError("recovery_step_missing_field")
    if not isinstance(value["id"], str) or not value["id"] or not isinstance(value["title"], str):
        raise RecoverySerializationError("recovery_step_invalid_identity")
    if not isinstance(value["tool_name"], str) or not value["tool_name"].strip():
        raise RecoverySerializationError("recovery_step_invalid_tool_name")
    if not isinstance(value["arguments"], dict) or type(value["retry_budget"]) is not int or value["retry_budget"] < 0:
        raise RecoverySerializationError("recovery_step_invalid_arguments")
    if value.get("condition") is not None or value.get("depends_on"):
        raise RecoverySerializationError("recovery_step_requires_independent_step")
    _check_args(value["arguments"])
    try:
        constructor = dict(value)
        constructor.pop("kind", None)
        step = ToolStep(**constructor)
        validate_plan([step])
        return step
    except Exception as exc:
        raise RecoverySerializationError("recovery_step_invalid") from exc


class SQLiteStepRecoveryStore:
    """SQLite authority for retry records; claims are single-writer atomic.

    The row contains only a bounded, non-secret ToolStep and identity snapshot.
    It never contains request messages, callables, capability tokens, or
    credentials. A row is therefore an input to a fresh runtime preflight, not
    execution authority by itself.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS step_recoveries (
                recovery_id TEXT PRIMARY KEY,
                step_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','claimed','succeeded','failed')),
                attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
                next_attempt_at REAL NOT NULL,
                lease_owner TEXT,
                lease_expires_at REAL,
                fencing_token TEXT,
                workspace_id TEXT,
                session_id TEXT,
                turn_id TEXT,
                failed_step_id TEXT,
                plan_hash TEXT,
                context_json TEXT,
                result_json TEXT,
                completed_at REAL,
                expires_at REAL,
                updated_at REAL NOT NULL
            )""")
            for column, definition in (
                ("lease_expires_at", "REAL"),
                ("fencing_token", "TEXT"),
                ("workspace_id", "TEXT"),
                ("session_id", "TEXT"),
                ("turn_id", "TEXT"),
                ("failed_step_id", "TEXT"),
                ("plan_hash", "TEXT"),
                ("context_json", "TEXT"),
                ("result_json", "TEXT"),
                ("completed_at", "REAL"),
                ("expires_at", "REAL"),
            ):
                # Older databases may lack columns added by the recovery
                # protocol.  Each migration is additive and idempotent; an
                # existing column is the only expected SQLite error here.
                try:
                    db.execute(f"ALTER TABLE step_recoveries ADD COLUMN {column} {definition}")
                except sqlite3.OperationalError:
                    pass
            db.execute("CREATE INDEX IF NOT EXISTS idx_step_recoveries_due ON step_recoveries(status, next_attempt_at)")

    def _connect(self) -> sqlite3.Connection:
        """Open a short-lived connection with row mappings enabled."""
        db = sqlite3.connect(self.path, timeout=10.0)
        db.row_factory = sqlite3.Row
        return db

    def put(
        self,
        recovery_id: str,
        step: ToolStep,
        *,
        next_attempt_at: float | None = None,
        expires_at: float | None = None,
        workspace_id: str | None = None,
        session_id: str | None = None,
        turn_id: str | None = None,
        failed_step_id: str | None = None,
        plan_hash: str | None = None,
        context_snapshot: dict[str, Any] | None = None,
        result: Any = None,
    ) -> None:
        """Insert or refresh a pending marker while preserving bounded data.

        A refresh is allowed only while the marker is still ``pending``.  Once
        another worker has claimed it, this method cannot overwrite its lease
        or completion state.
        """
        if not recovery_id or len(recovery_id) > 256:
            raise ValueError("recovery_id_invalid")
        scoped_values = {
            "workspace_id": workspace_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "failed_step_id": failed_step_id,
            "plan_hash": plan_hash,
        }
        for field, value in scoped_values.items():
            if value is not None and (not isinstance(value, str) or len(value) > 256):
                raise ValueError(f"{field}_invalid")
        encoded = serialize_tool_step(step)
        context_json = _serialize_snapshot(context_snapshot, label="context")
        result_json = _serialize_snapshot(result, label="result")
        now = time.time() if next_attempt_at is None else float(next_attempt_at)
        with self._connect() as db:
            db.execute("""INSERT INTO step_recoveries(
                recovery_id,step_json,status,attempts,next_attempt_at,
                workspace_id,session_id,turn_id,failed_step_id,plan_hash,
                context_json,result_json,expires_at,updated_at
            ) VALUES(?,?, 'pending', 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(recovery_id) DO UPDATE SET
                step_json=excluded.step_json,next_attempt_at=excluded.next_attempt_at,
                workspace_id=excluded.workspace_id,session_id=excluded.session_id,
                turn_id=excluded.turn_id,failed_step_id=excluded.failed_step_id,
                context_json=excluded.context_json,result_json=excluded.result_json,
                plan_hash=excluded.plan_hash,expires_at=excluded.expires_at,
                updated_at=excluded.updated_at
                WHERE step_recoveries.status='pending'""", (
                recovery_id,
                encoded,
                now,
                workspace_id,
                session_id,
                turn_id,
                failed_step_id,
                plan_hash,
                context_json,
                result_json,
                expires_at,
                time.time(),
            ))

    def get(self, recovery_id: str) -> ToolStep | None:
        """Return the validated step payload, without granting claim authority."""
        with self._connect() as db:
            row = db.execute("SELECT step_json FROM step_recoveries WHERE recovery_id=?", (recovery_id,)).fetchone()
        return None if row is None else deserialize_tool_step(row["step_json"])

    def get_recovery(self, recovery_id: str) -> dict[str, Any] | None:
        """Read the bounded recovery record, including safe snapshots and status."""
        with self._connect() as db:
            row = db.execute("SELECT * FROM step_recoveries WHERE recovery_id=?", (recovery_id,)).fetchone()
        if row is None:
            return None
        return {
            "recovery_id": row["recovery_id"],
            "status": row["status"],
            "step": deserialize_tool_step(row["step_json"]),
            "context_snapshot": _deserialize_snapshot(row["context_json"], label="context"),
            "result": _deserialize_snapshot(row["result_json"], label="result"),
            "plan_hash": row["plan_hash"],
            "workspace_id": row["workspace_id"], "session_id": row["session_id"],
            "turn_id": row["turn_id"], "failed_step_id": row["failed_step_id"],
            "attempts": row["attempts"], "fencing_token": row["fencing_token"],
        }

    def claim_recovery(
        self, recovery_id: str, owner: str, *, workspace_id: str | None = None,
        session_id: str | None = None, turn_id: str | None = None,
        failed_step_id: str | None = None, now: float | None = None,
    ) -> dict[str, Any] | None:
        """Atomically claim one marker after scope and lease checks.

        The returned fencing token must accompany completion.  A stale worker
        can therefore finish neither a newer lease nor a marker claimed by a
        different owner.
        """
        if not isinstance(owner, str) or not owner.strip() or len(owner) > 160:
            raise ValueError("recovery_owner_invalid")
        moment = time.time() if now is None else float(now)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM step_recoveries WHERE recovery_id=? AND (expires_at IS NULL OR expires_at>?)", (recovery_id, moment)).fetchone()
            if row is None or row["status"] not in ("pending", "claimed"):
                return None
            if int(row["attempts"] or 0) >= _MAX_RECOVERY_ATTEMPTS:
                return None
            if row["status"] == "claimed" and row["lease_expires_at"] and row["lease_expires_at"] > moment:
                return None
            for column, expected in (("workspace_id", workspace_id), ("session_id", session_id), ("turn_id", turn_id), ("failed_step_id", failed_step_id)):
                # A durable record with scope metadata must never be claimed
                # by a caller that omits or changes that scope.
                if row[column] is not None and row[column] != expected:
                    return None
            token = secrets.token_hex(16)
            db.execute("UPDATE step_recoveries SET status='claimed',lease_owner=?,lease_expires_at=?,fencing_token=?,attempts=attempts+1,updated_at=? WHERE recovery_id=?", (owner, moment + 60, token, moment, recovery_id))
            record = dict(row)
        record.update({"status": "claimed", "fencing_token": token, "attempts": int(record["attempts"]) + 1})
        record["context_snapshot"] = _deserialize_snapshot(record.get("context_json"), label="context")
        record["result"] = _deserialize_snapshot(record.get("result_json"), label="result")
        return {"status": "claimed", "record": record, "step": deserialize_tool_step(record["step_json"]), "fencing_token": token}

    def delete(self, recovery_id: str) -> bool:
        """Remove a legacy marker; normal attempts finish with an audit result."""
        with self._connect() as db:
            result = db.execute("DELETE FROM step_recoveries WHERE recovery_id=?", (recovery_id,))
        return result.rowcount == 1

    def reap_expired(self, *, now: float | None = None) -> int:
        """Bound storage for abandoned markers without touching active claims."""
        moment = time.time() if now is None else float(now)
        with self._connect() as db:
            result = db.execute(
                "DELETE FROM step_recoveries WHERE expires_at IS NOT NULL AND expires_at<=?",
                (moment,),
            )
        return result.rowcount

    def claim_due(self, owner: str, *, now: float | None = None) -> tuple[str, ToolStep, str] | None:
        """Claim the earliest due marker for the background recovery worker."""
        if not isinstance(owner, str) or not owner.strip() or len(owner) > 160:
            raise ValueError("recovery_owner_invalid")
        moment = time.time() if now is None else float(now)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT recovery_id,step_json,attempts FROM step_recoveries WHERE (status='pending' OR (status='claimed' AND lease_expires_at<=?)) AND attempts < ? AND next_attempt_at<=? AND (expires_at IS NULL OR expires_at>?) ORDER BY next_attempt_at,recovery_id LIMIT 1", (moment, _MAX_RECOVERY_ATTEMPTS, moment, moment)).fetchone()
            if row is None:
                return None
            step = deserialize_tool_step(row["step_json"])
            fencing_token = secrets.token_hex(16)
            db.execute("UPDATE step_recoveries SET status='claimed',lease_owner=?,lease_expires_at=?,fencing_token=?,attempts=attempts+1,updated_at=? WHERE recovery_id=?", (owner, moment + 60, fencing_token, moment, row["recovery_id"]))
        return row["recovery_id"], step, fencing_token

    def finish(self, recovery_id: str, *, success: bool, owner: str, fencing_token: str,
               result: Any = None, error: Any = None) -> bool:
        """Record a terminal attempt only when owner and fencing token match."""
        if not isinstance(fencing_token, str) or not fencing_token.strip() or len(fencing_token) > 128:
            raise ValueError("recovery_fencing_token_invalid")
        if result is not None and error is not None:
            raise ValueError("recovery_result_error_exclusive")
        completed = _serialize_snapshot(result if success else error, label="result")
        with self._connect() as db:
            changed = db.execute("UPDATE step_recoveries SET status=?,result_json=?,completed_at=?,lease_owner=NULL,lease_expires_at=NULL,fencing_token=NULL,updated_at=? WHERE recovery_id=? AND status='claimed' AND lease_owner=? AND fencing_token=?", ("succeeded" if success else "failed", completed, time.time(), time.time(), recovery_id, owner, fencing_token.strip()))
        return changed.rowcount == 1


__all__ = ["RecoverySerializationError", "SQLiteStepRecoveryStore", "deserialize_tool_step", "serialize_tool_step"]
_SECRET_KEYS = {"authorization", "token", "access_token", "api_key", "apikey", "password", "secret", "cookie", "set-cookie"}

def _check_args(value: Any, *, depth: int = 0) -> None:
    """Validate bounded JSON arguments and reject credential-shaped keys."""
    if depth > 8:
        raise RecoverySerializationError("recovery_arguments_too_deep")
    if isinstance(value, dict):
        if len(value) > 128:
            raise RecoverySerializationError("recovery_arguments_too_large")
        for key, child in value.items():
            if not isinstance(key, str) or len(key) > 128:
                raise RecoverySerializationError("recovery_argument_key_invalid")
            if key.lower().replace("-", "_") in _SECRET_KEYS or any(part in key.lower() for part in ("token", "secret", "password", "authorization", "api_key")):
                raise RecoverySerializationError("recovery_secret_argument_rejected")
            _check_args(child, depth=depth + 1)
    elif isinstance(value, list):
        if len(value) > 128:
            raise RecoverySerializationError("recovery_arguments_too_large")
        for child in value:
            _check_args(child, depth=depth + 1)
    elif isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > 65536:
            raise RecoverySerializationError("recovery_argument_value_too_large")
    else:
        raise RecoverySerializationError("recovery_argument_value_invalid")
