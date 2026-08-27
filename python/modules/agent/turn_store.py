"""SQLite authority for finalized semantic turns and projection outbox."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .turn_service import TurnClaimLostError

StoreBarrier = Callable[[str, dict[str, Any]], None]


class TurnCommitStore:
    def __init__(
        self,
        db_path: str | Path,
        *,
        wall_clock: Callable[[], float] | None = None,
        monotonic_clock: Callable[[], float] | None = None,
        barrier: StoreBarrier | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._wall_clock = wall_clock or time.time
        self._monotonic_clock = monotonic_clock or time.monotonic
        self._barrier = barrier
        self._lock = threading.RLock()
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS turn_commits (
                  idempotency_key TEXT PRIMARY KEY,
                  semantic_fingerprint TEXT NOT NULL,
                  trigger TEXT NOT NULL,
                  workspace_id TEXT,
                  session_id TEXT NOT NULL,
                  request_id TEXT,
                  result_json TEXT NOT NULL,
                  created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS turn_outbox (
                  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  idempotency_key TEXT NOT NULL UNIQUE,
                  event_type TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  available_at REAL NOT NULL DEFAULT 0,
                  attempt_count INTEGER NOT NULL DEFAULT 0,
                  claimed_by TEXT,
                  claim_expires_at REAL,
                  last_error TEXT,
                  dead_lettered_at REAL,
                  delivered_at REAL
                );
                CREATE TABLE IF NOT EXISTS turn_claims (
                  idempotency_key TEXT PRIMARY KEY,
                  semantic_fingerprint TEXT NOT NULL,
                  owner_id TEXT NOT NULL,
                  fencing_token INTEGER NOT NULL DEFAULT 0,
                  lease_expires_at REAL NOT NULL,
                  updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS turn_outbox_projection_acks (
                  event_id INTEGER NOT NULL,
                  projection_name TEXT NOT NULL,
                  delivered_at REAL NOT NULL,
                  PRIMARY KEY (event_id, projection_name),
                  FOREIGN KEY (event_id) REFERENCES turn_outbox(event_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS connector_deliveries (
                  delivery_key TEXT PRIMARY KEY,
                  idempotency_key TEXT NOT NULL,
                  connector_id TEXT NOT NULL,
                  event_id TEXT NOT NULL,
                  status TEXT NOT NULL,
                  attempt_count INTEGER NOT NULL DEFAULT 0,
                  claimed_by TEXT,
                  claim_expires_at REAL,
                  last_error TEXT,
                  updated_at REAL NOT NULL,
                  delivered_at REAL,
                  message_json TEXT,
                  reply_text TEXT
                );
                """
            )
            claim_columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(turn_claims)").fetchall()
            }
            if "fencing_token" not in claim_columns:
                conn.execute(
                    "ALTER TABLE turn_claims ADD COLUMN fencing_token INTEGER NOT NULL DEFAULT 0"
                )
            outbox_columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(turn_outbox)").fetchall()
            }
            outbox_migrations = {
                "available_at": "REAL NOT NULL DEFAULT 0",
                "attempt_count": "INTEGER NOT NULL DEFAULT 0",
                "claimed_by": "TEXT",
                "claim_expires_at": "REAL",
                "last_error": "TEXT",
                "dead_lettered_at": "REAL",
            }
            for column, declaration in outbox_migrations.items():
                if column not in outbox_columns:
                    conn.execute(
                        f"ALTER TABLE turn_outbox ADD COLUMN {column} {declaration}"
                    )
            delivery_columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(connector_deliveries)").fetchall()
            }
            for column, declaration in {
                "message_json": "TEXT",
                "reply_text": "TEXT",
            }.items():
                if column not in delivery_columns:
                    conn.execute(f"ALTER TABLE connector_deliveries ADD COLUMN {column} {declaration}")

    def _now(self) -> float:
        return float(self._wall_clock())

    def _reach_barrier(self, phase: str, **details: Any) -> None:
        if self._barrier is None:
            return
        self._barrier(
            phase,
            {
                **details,
                "wall_time": self._now(),
                "monotonic_time": float(self._monotonic_clock()),
            },
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def claim(
        self,
        idempotency_key: str,
        semantic_fingerprint: str,
        owner_id: str,
        lease_seconds: float = 30.0,
    ) -> dict[str, Any]:
        now = self._now()
        lease_expires_at = now + max(0.1, float(lease_seconds))
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            committed = conn.execute(
                "SELECT semantic_fingerprint FROM turn_commits WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if committed is not None:
                status = (
                    "committed"
                    if committed["semantic_fingerprint"] == semantic_fingerprint
                    else "conflict"
                )
                return {"status": status}
            current = conn.execute(
                """SELECT semantic_fingerprint, owner_id, fencing_token, lease_expires_at
                   FROM turn_claims WHERE idempotency_key = ?""",
                (idempotency_key,),
            ).fetchone()
            if current is not None and current["semantic_fingerprint"] != semantic_fingerprint:
                return {"status": "conflict"}
            if (
                current is None
                or current["owner_id"] == owner_id
                or float(current["lease_expires_at"]) <= now
            ):
                fencing_token = (
                    1
                    if current is None
                    else int(current["fencing_token"]) + int(
                        current["owner_id"] != owner_id
                        or float(current["lease_expires_at"]) <= now
                    )
                )
                conn.execute(
                    """INSERT INTO turn_claims
                       (idempotency_key, semantic_fingerprint, owner_id, fencing_token, lease_expires_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(idempotency_key) DO UPDATE SET
                         semantic_fingerprint = excluded.semantic_fingerprint,
                         owner_id = excluded.owner_id,
                         fencing_token = excluded.fencing_token,
                         lease_expires_at = excluded.lease_expires_at,
                         updated_at = excluded.updated_at""",
                    (
                        idempotency_key,
                        semantic_fingerprint,
                        owner_id,
                        fencing_token,
                        lease_expires_at,
                        now,
                    ),
                )
                outcome = {
                    "status": "claimed",
                    "fencing_token": fencing_token,
                    "lease_expires_at": lease_expires_at,
                }
            else:
                return {
                    "status": "busy",
                    "retry_after": max(0.01, float(current["lease_expires_at"]) - now),
                }
        self._reach_barrier(
            "turn_claim.acquired",
            idempotency_key=idempotency_key,
            owner_id=owner_id,
            fencing_token=fencing_token,
        )
        return outcome

    def renew_claim(
        self,
        idempotency_key: str,
        owner_id: str,
        fencing_token: int,
        lease_seconds: float = 30.0,
    ) -> bool:
        now = self._now()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """UPDATE turn_claims SET lease_expires_at = ?, updated_at = ?
                   WHERE idempotency_key = ? AND owner_id = ?
                     AND fencing_token = ? AND lease_expires_at > ?""",
                (
                    now + max(0.1, float(lease_seconds)),
                    now,
                    idempotency_key,
                    owner_id,
                    int(fencing_token),
                    now,
                ),
            )
            renewed = cursor.rowcount == 1
        if renewed:
            self._reach_barrier(
                "turn_claim.renewed",
                idempotency_key=idempotency_key,
                owner_id=owner_id,
                fencing_token=int(fencing_token),
            )
        return renewed

    def release_claim(
        self,
        idempotency_key: str,
        owner_id: str,
        fencing_token: int,
    ) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """DELETE FROM turn_claims
                   WHERE idempotency_key = ? AND owner_id = ? AND fencing_token = ?""",
                (idempotency_key, owner_id, int(fencing_token)),
            )
            return cursor.rowcount == 1

    def persist(self, commit: Any) -> dict[str, Any]:
        result = commit.result
        committed_at = self._now()
        extra = getattr(commit.context, "extra", {})
        self._reach_barrier(
            "persist.before",
            idempotency_key=commit.idempotency_key,
        )
        payload = {
            "schema_version": 1,
            "idempotency_key": commit.idempotency_key,
            "semantic_fingerprint": commit.semantic_fingerprint,
            "trigger": commit.trigger,
            "workspace_id": commit.context.workspace_id,
            "session_id": commit.context.session_id,
            "request_id": commit.context.request_id,
            "turn_id": getattr(commit.context, "turn_id", None) or extra.get("turn_id"),
            "generation_id": getattr(commit.context, "generation_id", None)
            or extra.get("generation_id"),
            "interruption_epoch": getattr(commit.context, "interruption_epoch", None)
            if getattr(commit.context, "interruption_epoch", None) is not None
            else extra.get("interruption_epoch", 0),
            "job_id": extra.get("job_id"),
            "run_id": extra.get("run_id"),
            "task_id": extra.get("task_id"),
            "task_name": extra.get("task_name"),
            "task_mode": extra.get("task_mode"),
            "owner_agent_id": extra.get("owner_agent_id"),
            "owner_agent_role": extra.get("owner_agent_role"),
            "route_reason": extra.get("route_reason"),
            "autonomy_mode": commit.context.autonomy_mode,
            "model": getattr(commit.context, "model", None),
            "messages": commit.context.messages,
            "reply": result.reply,
            "pet_control": result.pet_control,
            "tool_calls": result.tool_calls,
            "action_envelope": result.action_envelope,
            "failure": getattr(result, "failure", None),
            "recovery": getattr(result, "recovery", None),
            "outcome": getattr(result, "outcome", "completed"),
            "retryable": bool(getattr(result, "retryable", False)),
            "configured_budget": dict(
                getattr(result, "configured_budget", None) or {}
            ),
            "consumed_usage": dict(getattr(result, "consumed_usage", None) or {}),
            "committed_at": committed_at,
        }
        if payload["job_id"] or payload["run_id"]:
            payload["job_terminal"] = {
                "status": payload["outcome"],
                "job_id": payload["job_id"],
                "run_id": payload["run_id"],
                "task_id": payload["task_id"],
                "task_name": payload["task_name"],
                "task_mode": payload["task_mode"],
                "owner_agent_id": payload["owner_agent_id"],
                "owner_agent_role": payload["owner_agent_role"],
                "route_reason": payload["route_reason"],
            }
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT semantic_fingerprint FROM turn_commits WHERE idempotency_key = ?",
                (commit.idempotency_key,),
            ).fetchone()
            if existing is not None and existing["semantic_fingerprint"] != commit.semantic_fingerprint:
                raise ValueError(
                    "turn idempotency key already belongs to a different semantic fingerprint"
                )
            claim_owner = str(getattr(commit, "claim_owner", None) or "").strip()
            claim_fencing_token = getattr(commit, "claim_fencing_token", None)
            if claim_owner:
                claim = conn.execute(
                    """SELECT owner_id, fencing_token, lease_expires_at
                       FROM turn_claims WHERE idempotency_key = ?""",
                    (commit.idempotency_key,),
                ).fetchone()
                if (
                    claim is None
                    or claim["owner_id"] != claim_owner
                    or int(claim["fencing_token"]) != int(claim_fencing_token or 0)
                    or float(claim["lease_expires_at"]) <= committed_at
                ):
                    raise TurnClaimLostError(
                        "semantic turn claim is stale or expired; commit rejected"
                    )
            conn.execute(
                """INSERT OR IGNORE INTO turn_commits
                (idempotency_key, semantic_fingerprint, trigger, workspace_id, session_id, request_id, result_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    commit.idempotency_key,
                    commit.semantic_fingerprint,
                    commit.trigger,
                    commit.context.workspace_id,
                    commit.context.session_id,
                    commit.context.request_id,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    committed_at,
                ),
            )
            conn.execute(
                """INSERT OR IGNORE INTO turn_outbox
                   (idempotency_key, event_type, payload_json, available_at)
                   VALUES (?, ?, ?, ?)""",
                (
                    commit.idempotency_key,
                    "turn.committed",
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    committed_at,
                ),
            )
            if claim_owner:
                conn.execute(
                    """DELETE FROM turn_claims
                       WHERE idempotency_key = ? AND owner_id = ? AND fencing_token = ?""",
                    (
                        commit.idempotency_key,
                        claim_owner,
                        int(claim_fencing_token or 0),
                    ),
                )
        self._reach_barrier(
            "persist.committed",
            idempotency_key=commit.idempotency_key,
        )
        return {"stored": True, "outbox": "pending", "idempotency_key": commit.idempotency_key}

    def load(self, idempotency_key: str) -> dict[str, Any] | None:
        """Read a finalized commit for crash/reconnect replay.

        The caller supplies the current request context when rebuilding the
        in-memory ``TurnCommit``; SQLite remains the authority for the result
        and semantic identity.
        """
        key = str(idempotency_key or "").strip()
        if not key:
            return None
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """SELECT idempotency_key, semantic_fingerprint, trigger,
                          result_json, created_at
                   FROM turn_commits WHERE idempotency_key = ?""",
                (key,),
            ).fetchone()
        if row is None:
            return None
        result = json.loads(row["result_json"])
        result.setdefault("outcome", "completed")
        result.setdefault("retryable", False)
        result["configured_budget"] = dict(result.get("configured_budget") or {})
        result["consumed_usage"] = dict(result.get("consumed_usage") or {})
        return {
            "idempotency_key": row["idempotency_key"],
            "semantic_fingerprint": row["semantic_fingerprint"],
            "trigger": row["trigger"],
            "result": result,
            "created_at": row["created_at"],
            "persisted": True,
        }

    def connector_delivery(self, delivery_key: str) -> dict[str, Any] | None:
        key = str(delivery_key or "").strip()
        if not key:
            return None
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """SELECT delivery_key, idempotency_key, connector_id, event_id,
                          status, attempt_count, claimed_by, claim_expires_at,
                          last_error, updated_at, delivered_at, message_json, reply_text
                   FROM connector_deliveries WHERE delivery_key = ?""",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def record_connector_turn_pending(
        self,
        delivery_key: str,
        idempotency_key: str,
        connector_id: str,
        event_id: str,
        owner_id: str,
        *,
        lease_seconds: float = 30.0,
        message: Mapping[str, Any],
    ) -> bool:
        """Persist enough inbound context to retry a turn before it has a reply."""
        key = str(delivery_key or "").strip()
        if not key:
            raise ValueError("delivery_key is required")
        owner = str(owner_id or "").strip()
        if not owner:
            raise ValueError("owner_id is required")
        now = self._now()
        expires_at = now + max(0.1, float(lease_seconds))
        message_json = json.dumps(dict(message), ensure_ascii=False)
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO connector_deliveries
                   (delivery_key, idempotency_key, connector_id, event_id, status,
                    attempt_count, claimed_by, claim_expires_at, last_error, updated_at,
                    delivered_at, message_json, reply_text)
                   VALUES (?, ?, ?, ?, 'processing', 0, ?, ?, NULL, ?, NULL, ?, NULL)""",
                (key, idempotency_key, connector_id, event_id, owner, expires_at, now, message_json),
            )
            return cursor.rowcount == 1

    def mark_connector_turn_failed(self, delivery_key: str, owner_id: str, error: str) -> bool:
        """Make a pre-delivery turn failure visible and manually retryable."""
        now = self._now()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """UPDATE connector_deliveries
                   SET status = 'failed', claimed_by = NULL, claim_expires_at = NULL,
                       last_error = ?, updated_at = ?, delivered_at = NULL
                   WHERE delivery_key = ? AND claimed_by = ? AND status = 'processing'""",
                (str(error)[:2000], now, str(delivery_key), str(owner_id)),
            )
            return cursor.rowcount == 1

    def discard_connector_turn_pending(self, delivery_key: str, owner_id: str) -> bool:
        """Remove an unclaimed turn row when execution is cancelled before delivery."""
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """DELETE FROM connector_deliveries
                   WHERE delivery_key = ? AND status = 'processing'
                     AND claimed_by = ? AND reply_text IS NULL""",
                (str(delivery_key), str(owner_id)),
            )
            return cursor.rowcount == 1

    def recover_stale_connector_turn(self, delivery_key: str) -> bool:
        """Fence and expose a processing row whose owning process lease expired."""
        now = self._now()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """UPDATE connector_deliveries
                   SET status = 'failed', claimed_by = NULL, claim_expires_at = NULL,
                       last_error = 'connector_turn_interrupted', updated_at = ?
                   WHERE delivery_key = ? AND status = 'processing'
                     AND claim_expires_at IS NOT NULL AND claim_expires_at <= ?""",
                (now, str(delivery_key), now),
            )
            return cursor.rowcount == 1

    def claim_connector_delivery(
        self,
        delivery_key: str,
        idempotency_key: str,
        connector_id: str,
        event_id: str,
        owner_id: str,
        *,
        lease_seconds: float = 30.0,
        message: Mapping[str, Any] | None = None,
        reply_text: str | None = None,
    ) -> dict[str, Any]:
        key = str(delivery_key or "").strip()
        owner = str(owner_id or "").strip()
        if not key or not owner:
            raise ValueError("delivery_key and owner_id are required")
        now = self._now()
        expires_at = now + max(0.1, float(lease_seconds))
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT status, attempt_count, claimed_by, claim_expires_at,
                          delivered_at FROM connector_deliveries
                   WHERE delivery_key = ?""",
                (key,),
            ).fetchone()
            if row is not None and row["status"] == "delivered":
                return {
                    "status": "delivered",
                    "attempt_count": int(row["attempt_count"] or 0),
                    "delivered_at": row["delivered_at"],
                }
            current_owner = str(row["claimed_by"] or "") if row is not None else ""
            current_expires = float(row["claim_expires_at"] or 0) if row is not None else 0.0
            if current_owner and current_owner != owner and current_expires > now:
                return {
                    "status": "busy",
                    "retry_after": max(0.01, current_expires - now),
                }
            attempts = int(row["attempt_count"] or 0) + 1 if row is not None else 1
            message_json = json.dumps(dict(message), ensure_ascii=False) if message is not None else None
            conn.execute(
                """INSERT INTO connector_deliveries
                   (delivery_key, idempotency_key, connector_id, event_id, status,
                    attempt_count, claimed_by, claim_expires_at, last_error, updated_at, delivered_at,
                    message_json, reply_text)
                   VALUES (?, ?, ?, ?, 'sending', ?, ?, ?, NULL, ?, NULL, ?, ?)
                   ON CONFLICT(delivery_key) DO UPDATE SET
                     idempotency_key = excluded.idempotency_key,
                     connector_id = excluded.connector_id,
                     event_id = excluded.event_id,
                     status = 'sending',
                     attempt_count = excluded.attempt_count,
                     claimed_by = excluded.claimed_by,
                     claim_expires_at = excluded.claim_expires_at,
                     last_error = NULL,
                     updated_at = excluded.updated_at,
                     delivered_at = NULL,
                     message_json = COALESCE(excluded.message_json, connector_deliveries.message_json),
                     reply_text = COALESCE(excluded.reply_text, connector_deliveries.reply_text)""",
                (key, idempotency_key, connector_id, event_id, attempts, owner, expires_at, now, message_json, reply_text),
            )
        return {"status": "claimed", "attempt_count": attempts, "claim_expires_at": expires_at}

    def claim_connector_turn_retry(
        self,
        delivery_key: str,
        owner_id: str,
        *,
        lease_seconds: float = 15 * 60,
    ) -> dict[str, Any]:
        """Lease a failed pre-delivery turn without presenting it as sending."""
        key = str(delivery_key or "").strip()
        owner = str(owner_id or "").strip()
        if not key or not owner:
            raise ValueError("delivery_key and owner_id are required")
        now = self._now()
        expires_at = now + max(0.1, float(lease_seconds))
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT status, attempt_count, claimed_by, claim_expires_at
                   FROM connector_deliveries WHERE delivery_key = ?""",
                (key,),
            ).fetchone()
            if row is None:
                return {"status": "missing"}
            if row["status"] == "delivered":
                return {"status": "delivered", "attempt_count": int(row["attempt_count"] or 0)}
            if row["status"] != "failed":
                return {"status": "not_retryable"}
            current_owner = str(row["claimed_by"] or "")
            current_expires = float(row["claim_expires_at"] or 0)
            if current_owner and current_owner != owner and current_expires > now:
                return {"status": "busy", "retry_after": max(0.01, current_expires - now)}
            attempts = int(row["attempt_count"] or 0) + 1
            cursor = conn.execute(
                """UPDATE connector_deliveries
                   SET status = 'failed', attempt_count = ?, claimed_by = ?,
                       claim_expires_at = ?, updated_at = ?
                   WHERE delivery_key = ? AND status = 'failed' AND reply_text IS NULL""",
                (attempts, owner, expires_at, now, key),
            )
            if cursor.rowcount != 1:
                return {"status": "not_retryable"}
        return {"status": "claimed", "attempt_count": attempts, "claim_expires_at": expires_at}

    def promote_connector_turn_retry(
        self,
        delivery_key: str,
        owner_id: str,
        reply_text: str,
        *,
        send_lease_seconds: float = 60.0,
    ) -> bool:
        """Move a regenerated turn into the external delivery phase."""
        now = self._now()
        expires_at = now + max(0.1, float(send_lease_seconds))
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """UPDATE connector_deliveries
                   SET status = 'sending', reply_text = ?, last_error = NULL,
                       claim_expires_at = ?, updated_at = ?
                   WHERE delivery_key = ? AND claimed_by = ? AND status = 'failed'""",
                (str(reply_text), expires_at, now, str(delivery_key), str(owner_id)),
            )
            return cursor.rowcount == 1

    def release_connector_turn_retry(
        self,
        delivery_key: str,
        owner_id: str,
        error: str,
    ) -> bool:
        """Release a failed turn retry so the user can try again immediately."""
        now = self._now()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """UPDATE connector_deliveries
                   SET status = 'failed', claimed_by = NULL, claim_expires_at = NULL,
                       last_error = ?, updated_at = ?
                   WHERE delivery_key = ? AND claimed_by = ? AND status = 'failed'""",
                (str(error)[:2000], now, str(delivery_key), str(owner_id)),
            )
            return cursor.rowcount == 1

    def mark_connector_delivery_sent(self, delivery_key: str, owner_id: str) -> bool:
        now = self._now()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """UPDATE connector_deliveries
                   SET status = 'delivered', claimed_by = NULL, claim_expires_at = NULL,
                       updated_at = ?, delivered_at = ?
                   WHERE delivery_key = ? AND claimed_by = ? AND status = 'sending'""",
                (now, now, str(delivery_key), str(owner_id)),
            )
            return cursor.rowcount == 1

    def list_connector_deliveries(
        self,
        *,
        connector_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return recent connector delivery attempts for operational inspection."""
        clauses: list[str] = []
        params: list[Any] = []
        if connector_id:
            clauses.append("connector_id = ?")
            params.append(str(connector_id).strip().lower())
        if status:
            clauses.append("status = ?")
            params.append(str(status).strip().lower())
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(500, int(limit))))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """SELECT delivery_key, idempotency_key, connector_id, event_id, status,
                          attempt_count, claimed_by, claim_expires_at, last_error,
                          updated_at, delivered_at, message_json, reply_text
                   FROM connector_deliveries""" + where + " ORDER BY updated_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def reset_connector_delivery_for_retry(self, delivery_key: str) -> bool:
        """Release a failed/stale delivery so a caller can claim a new attempt."""
        key = str(delivery_key or "").strip()
        if not key:
            return False
        now = self._now()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """UPDATE connector_deliveries
                   SET status = 'failed', claimed_by = NULL, claim_expires_at = NULL,
                       updated_at = ?
                   WHERE delivery_key = ? AND status IN ('failed', 'sending')""",
                (now, key),
            )
            return cursor.rowcount == 1

    def mark_connector_delivery_failed(
        self,
        delivery_key: str,
        owner_id: str,
        error: str,
    ) -> bool:
        now = self._now()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """UPDATE connector_deliveries
                   SET status = 'failed', claimed_by = NULL, claim_expires_at = NULL,
                       last_error = ?, updated_at = ?, delivered_at = NULL
                   WHERE delivery_key = ? AND claimed_by = ? AND status = 'sending'""",
                (str(error)[:2000], now, str(delivery_key), str(owner_id)),
            )
            return cursor.rowcount == 1

    def list_commits(self, workspace_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        """List authoritative committed-turn events for deterministic rebuilds."""
        workspace = str(workspace_id or "").strip()
        if not workspace:
            raise ValueError("workspace_id is required")
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """SELECT c.idempotency_key, c.result_json, c.created_at,
                          o.event_id, o.event_type
                   FROM turn_commits AS c
                   JOIN turn_outbox AS o ON o.idempotency_key = c.idempotency_key
                   WHERE c.workspace_id = ?
                   ORDER BY c.created_at, c.idempotency_key
                   LIMIT ?""",
                (workspace, max(1, min(10000, int(limit)))),
            ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "idempotency_key": row["idempotency_key"],
                "payload": json.loads(row["result_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def pending_outbox(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """SELECT event_id, idempotency_key, event_type, payload_json,
                          available_at, attempt_count, claimed_by,
                          claim_expires_at, last_error, dead_lettered_at
                   FROM turn_outbox
                   WHERE delivered_at IS NULL AND dead_lettered_at IS NULL
                   ORDER BY event_id LIMIT ?""",
                (max(1, int(limit)),),
            ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "idempotency_key": row["idempotency_key"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "available_at": row["available_at"],
                "attempt_count": row["attempt_count"],
                "claimed_by": row["claimed_by"],
                "claim_expires_at": row["claim_expires_at"],
                "last_error": row["last_error"],
                "dead_lettered_at": row["dead_lettered_at"],
            }
            for row in rows
        ]

    def claim_next_outbox(
        self,
        owner_id: str,
        *,
        lease_seconds: float = 30.0,
    ) -> dict[str, Any] | None:
        """Claim the oldest pending event while preserving global ordering."""
        now = self._now()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT event_id, idempotency_key, event_type, payload_json,
                          available_at, attempt_count, claimed_by, claim_expires_at
                   FROM turn_outbox
                   WHERE delivered_at IS NULL AND dead_lettered_at IS NULL
                   ORDER BY event_id LIMIT 1"""
            ).fetchone()
            if row is None:
                return None
            available_at = float(row["available_at"] or 0)
            claim_expires_at = float(row["claim_expires_at"] or 0)
            current_owner = str(row["claimed_by"] or "")
            if available_at > now:
                return {"status": "waiting", "retry_after": available_at - now}
            if current_owner and claim_expires_at > now:
                return {"status": "busy", "retry_after": claim_expires_at - now}
            event_id = int(row["event_id"])
            expires_at = now + max(0.1, float(lease_seconds))
            cursor = conn.execute(
                """UPDATE turn_outbox
                   SET claimed_by = ?, claim_expires_at = ?
                   WHERE event_id = ? AND delivered_at IS NULL
                     AND dead_lettered_at IS NULL
                     AND (claimed_by IS NULL OR claim_expires_at <= ?)""",
                (owner_id, expires_at, event_id, now),
            )
            if cursor.rowcount != 1:
                return {"status": "busy", "retry_after": 0.05}
            outcome = {
                "status": "claimed",
                "event_id": event_id,
                "idempotency_key": row["idempotency_key"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "attempt_count": int(row["attempt_count"] or 0),
                "claim_expires_at": expires_at,
            }
        self._reach_barrier(
            "outbox_claim.acquired",
            event_id=event_id,
            owner_id=owner_id,
        )
        return outcome

    def fail_outbox(
        self,
        event_id: int,
        owner_id: str,
        error: str,
        *,
        retry_delay: float,
        max_attempts: int,
    ) -> dict[str, Any]:
        now = self._now()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT attempt_count FROM turn_outbox
                   WHERE event_id = ? AND claimed_by = ?
                     AND delivered_at IS NULL AND dead_lettered_at IS NULL""",
                (int(event_id), owner_id),
            ).fetchone()
            if row is None:
                return {"updated": False, "dead_lettered": False}
            attempt_count = int(row["attempt_count"] or 0) + 1
            dead_lettered = attempt_count >= max(1, int(max_attempts))
            conn.execute(
                """UPDATE turn_outbox SET attempt_count = ?, last_error = ?,
                          available_at = ?, claimed_by = NULL,
                          claim_expires_at = NULL, dead_lettered_at = ?
                   WHERE event_id = ? AND claimed_by = ?""",
                (
                    attempt_count,
                    str(error)[:2000],
                    now + max(0.0, float(retry_delay)),
                    now if dead_lettered else None,
                    int(event_id),
                    owner_id,
                ),
            )
        return {"updated": True, "dead_lettered": dead_lettered}

    def renew_outbox_claim(
        self,
        event_id: int,
        owner_id: str,
        *,
        lease_seconds: float = 30.0,
    ) -> bool:
        now = self._now()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """UPDATE turn_outbox SET claim_expires_at = ?
                   WHERE event_id = ? AND claimed_by = ?
                     AND claim_expires_at > ? AND delivered_at IS NULL
                     AND dead_lettered_at IS NULL""",
                (
                    now + max(0.1, float(lease_seconds)),
                    int(event_id),
                    owner_id,
                    now,
                ),
            )
            renewed = cursor.rowcount == 1
        if renewed:
            self._reach_barrier(
                "outbox_claim.renewed",
                event_id=int(event_id),
                owner_id=owner_id,
            )
        return renewed

    def acknowledge(self, event_id: int, owner_id: str | None = None) -> bool:
        now = self._now()
        with self._lock, self._connect() as conn:
            if owner_id is None:
                cursor = conn.execute(
                    "UPDATE turn_outbox SET delivered_at = ? WHERE event_id = ?",
                    (now, int(event_id)),
                )
            else:
                cursor = conn.execute(
                    """UPDATE turn_outbox SET delivered_at = ?, claimed_by = NULL,
                              claim_expires_at = NULL
                       WHERE event_id = ? AND claimed_by = ? AND claim_expires_at > ?""",
                    (now, int(event_id), owner_id, now),
                )
            acknowledged = cursor.rowcount == 1
        if acknowledged:
            self._reach_barrier(
                "outbox.acknowledged",
                event_id=int(event_id),
                owner_id=owner_id,
            )
        return acknowledged

    def acknowledged_projections(self, event_id: int) -> set[str]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT projection_name FROM turn_outbox_projection_acks WHERE event_id = ?",
                (int(event_id),),
            ).fetchall()
        return {str(row["projection_name"]) for row in rows}

    def acknowledge_projection(
        self,
        event_id: int,
        projection_name: str,
        owner_id: str | None = None,
    ) -> bool:
        now = self._now()
        with self._lock, self._connect() as conn:
            if owner_id is not None:
                claimed = conn.execute(
                    """SELECT 1 FROM turn_outbox
                       WHERE event_id = ? AND claimed_by = ? AND claim_expires_at > ?
                         AND delivered_at IS NULL AND dead_lettered_at IS NULL""",
                    (int(event_id), owner_id, now),
                ).fetchone()
                if claimed is None:
                    return False
            cursor = conn.execute(
                """INSERT OR IGNORE INTO turn_outbox_projection_acks
                   (event_id, projection_name, delivered_at) VALUES (?, ?, ?)""",
                (int(event_id), str(projection_name), now),
            )
            acknowledged = cursor.rowcount == 1
        if acknowledged:
            self._reach_barrier(
                "outbox_projection.acknowledged",
                event_id=int(event_id),
                projection_name=str(projection_name),
                owner_id=owner_id,
            )
        return acknowledged

    def outbox_diagnostics(self) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """SELECT
                     SUM(CASE WHEN delivered_at IS NULL AND dead_lettered_at IS NULL THEN 1 ELSE 0 END) AS pending,
                     SUM(CASE WHEN delivered_at IS NOT NULL THEN 1 ELSE 0 END) AS delivered,
                     SUM(CASE WHEN dead_lettered_at IS NOT NULL THEN 1 ELSE 0 END) AS dead_lettered,
                     MAX(attempt_count) AS max_attempts
                   FROM turn_outbox"""
            ).fetchone()
        return {
            "pending": int(row["pending"] or 0),
            "delivered": int(row["delivered"] or 0),
            "dead_lettered": int(row["dead_lettered"] or 0),
            "max_attempts": int(row["max_attempts"] or 0),
        }


__all__ = ["StoreBarrier", "TurnCommitStore"]
