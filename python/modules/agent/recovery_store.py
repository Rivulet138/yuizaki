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
    pass


def serialize_tool_step(step: ToolStep) -> str:
    if not isinstance(step, ToolStep):
        raise RecoverySerializationError("recovery_step_must_be_tool_step")
    if step.plan_version < 2:
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
    """SQLite authority for retry records; claims are single-writer atomic."""

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
                expires_at REAL,
                updated_at REAL NOT NULL
            )""")
            for column, definition in (("lease_expires_at", "REAL"), ("fencing_token", "TEXT"), ("expires_at", "REAL")):
                try:
                    db.execute(f"ALTER TABLE step_recoveries ADD COLUMN {column} {definition}")
                except sqlite3.OperationalError:
                    pass
            db.execute("CREATE INDEX IF NOT EXISTS idx_step_recoveries_due ON step_recoveries(status, next_attempt_at)")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10.0)
        db.row_factory = sqlite3.Row
        return db

    def put(self, recovery_id: str, step: ToolStep, *, next_attempt_at: float | None = None, expires_at: float | None = None) -> None:
        if not recovery_id or len(recovery_id) > 256:
            raise ValueError("recovery_id_invalid")
        encoded = serialize_tool_step(step)
        now = time.time() if next_attempt_at is None else float(next_attempt_at)
        with self._connect() as db:
            db.execute("""INSERT INTO step_recoveries(recovery_id,step_json,status,attempts,next_attempt_at,expires_at,updated_at)
                VALUES(?,?, 'pending', 0, ?, ?, ?) ON CONFLICT(recovery_id) DO UPDATE SET
                step_json=excluded.step_json,next_attempt_at=excluded.next_attempt_at,expires_at=excluded.expires_at,updated_at=excluded.updated_at
                WHERE step_recoveries.status='pending'""", (recovery_id, encoded, now, expires_at, time.time()))

    def get(self, recovery_id: str) -> ToolStep | None:
        with self._connect() as db:
            row = db.execute("SELECT step_json FROM step_recoveries WHERE recovery_id=?", (recovery_id,)).fetchone()
        return None if row is None else deserialize_tool_step(row["step_json"])

    def claim_due(self, owner: str, *, now: float | None = None) -> tuple[str, ToolStep, str] | None:
        if not isinstance(owner, str) or not owner.strip() or len(owner) > 160:
            raise ValueError("recovery_owner_invalid")
        moment = time.time() if now is None else float(now)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT recovery_id,step_json,attempts FROM step_recoveries WHERE (status='pending' OR (status='claimed' AND lease_expires_at<=?)) AND next_attempt_at<=? AND (expires_at IS NULL OR expires_at>?) ORDER BY next_attempt_at,recovery_id LIMIT 1", (moment, moment, moment)).fetchone()
            if row is None:
                return None
            step = deserialize_tool_step(row["step_json"])
            fencing_token = secrets.token_hex(16)
            db.execute("UPDATE step_recoveries SET status='claimed',lease_owner=?,lease_expires_at=?,fencing_token=?,attempts=attempts+1,updated_at=? WHERE recovery_id=?", (owner, moment + 60, fencing_token, moment, row["recovery_id"]))
        return row["recovery_id"], step, fencing_token

    def finish(self, recovery_id: str, *, success: bool, owner: str, fencing_token: str) -> bool:
        if not isinstance(fencing_token, str) or not fencing_token.strip() or len(fencing_token) > 128:
            raise ValueError("recovery_fencing_token_invalid")
        with self._connect() as db:
            result = db.execute("UPDATE step_recoveries SET status=?,lease_owner=NULL,lease_expires_at=NULL,fencing_token=NULL,updated_at=? WHERE recovery_id=? AND status='claimed' AND lease_owner=? AND fencing_token=?", ("succeeded" if success else "failed", time.time(), recovery_id, owner, fencing_token.strip()))
        return result.rowcount == 1


__all__ = ["RecoverySerializationError", "SQLiteStepRecoveryStore", "deserialize_tool_step", "serialize_tool_step"]
_SECRET_KEYS = {"authorization", "token", "access_token", "api_key", "apikey", "password", "secret", "cookie", "set-cookie"}

def _check_args(value: Any, *, depth: int = 0) -> None:
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
