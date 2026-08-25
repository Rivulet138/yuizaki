"""Rebuildable activity-frame projection and proactive follow-up policy.

Activity frames are bounded, non-authoritative projections of committed turns.
They deliberately never contain chat text, screenshots, audio, credentials, tool
output, or action authority.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SOURCE_KIND = "completed_turn_followup"
PROJECTION_VERSION = "activity-frame.v1"
POLICY_VERSION = "proactive-policy.v1"
SCHEMA_VERSION = "yuizaki.activity-frame.v1"
FEEDBACK_KINDS = {
    "useful",
    "not_useful",
    "too_frequent",
    "wrong_time",
    "never_source",
}
GATE_ORDER = (
    "global_disabled",
    "source_disabled",
    "frame_inactive",
    "dnd",
    "quiet_hours",
    "not_interruptible",
    "cooldown",
    "daily_budget",
    "duplicate",
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_WINDOWS_TZDATA_FALLBACKS = {
    "UTC",
    "Etc/UTC",
    "Asia/Shanghai",
    "Asia/Tokyo",
    "America/New_York",
    "Europe/London",
}


def _bounded_id(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not _SAFE_ID.fullmatch(normalized):
        raise ValueError(f"{field} must be a safe identifier of 1-160 characters")
    return normalized


def deterministic_frame_id(source_kind: str, source_id: str) -> str:
    material = f"{source_kind}\0{source_id}\0{PROJECTION_VERSION}".encode()
    return "af_" + hashlib.sha256(material).hexdigest()


@dataclass(frozen=True)
class ProactiveSettings:
    enabled: bool = False
    completed_turn_followup_enabled: bool = True
    dnd: bool = False
    quiet_hours_enabled: bool = False
    quiet_hours_start: str = "22:00"
    quiet_hours_end: str = "08:00"
    timezone: str = "UTC"
    daily_budget: int = 3
    cooldown_seconds: int = 3600
    retention_days: int = 7

    def validate(self) -> "ProactiveSettings":
        _parse_hhmm(self.quiet_hours_start)
        _parse_hhmm(self.quiet_hours_end)
        _validate_timezone(self.timezone)
        if not 1 <= self.daily_budget <= 20:
            raise ValueError("dailyBudget must be between 1 and 20")
        if not 0 <= self.cooldown_seconds <= 604800:
            raise ValueError("cooldownSeconds must be between 0 and 604800")
        if not 1 <= self.retention_days <= 90:
            raise ValueError("retentionDays must be between 1 and 90")
        return self

    def to_api(self) -> dict[str, Any]:
        return {
            "schemaVersion": "yuizaki.proactive-settings.v1",
            "enabled": self.enabled,
            "sourceEnabled": {SOURCE_KIND: self.completed_turn_followup_enabled},
            "dnd": self.dnd,
            "quietHours": {
                "enabled": self.quiet_hours_enabled,
                "start": self.quiet_hours_start,
                "end": self.quiet_hours_end,
                "timezone": self.timezone,
            },
            "dailyBudget": self.daily_budget,
            "cooldownSeconds": self.cooldown_seconds,
            "retentionDays": self.retention_days,
            "policyVersion": POLICY_VERSION,
        }


@dataclass(frozen=True)
class ActivityFrame:
    frame_id: str
    workspace_id: str
    session_id: str
    source_kind: str
    source_id: str
    source_event_id: str
    source_created_at: float
    created_at: float
    expires_at: float
    projection_version: str
    policy_version: str
    signals: Mapping[str, Any]

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at

    def to_api(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "frameId": self.frame_id,
            "workspaceId": self.workspace_id,
            "sessionId": self.session_id,
            "sourceKind": self.source_kind,
            "sourceId": self.source_id,
            "sourceEventId": self.source_event_id,
            "sourceCreatedAt": self.source_created_at,
            "createdAt": self.created_at,
            "expiresAt": self.expires_at,
            "projectionVersion": self.projection_version,
            "policyVersion": self.policy_version,
            "redaction": {
                "version": "activity-frame-redaction.v1",
                "rawContentRetained": False,
                "excluded": [
                    "chat_text",
                    "screenshots",
                    "audio",
                    "credentials",
                    "tool_output",
                ],
            },
            "provenance": {
                "sourceKind": self.source_kind,
                "sourceId": self.source_id,
                "sourceEventId": self.source_event_id,
            },
            "signals": dict(self.signals),
            "authoritative": False,
            "allowedActions": [],
        }


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    evaluated_at: float
    local_date: str
    remaining_budget: int

    def to_api(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "evaluatedAt": self.evaluated_at,
            "localDate": self.local_date,
            "remainingBudget": self.remaining_budget,
            "gateOrder": list(GATE_ORDER),
            "policyVersion": POLICY_VERSION,
        }


def _parse_hhmm(value: str) -> int:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("quiet hour values must use HH:MM") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59) or value != f"{hour:02d}:{minute:02d}":
        raise ValueError("quiet hour values must use HH:MM")
    return hour * 60 + minute


def _validate_timezone(timezone_name: str) -> None:
    try:
        ZoneInfo(timezone_name)
        return
    except ZoneInfoNotFoundError:
        if timezone_name not in _WINDOWS_TZDATA_FALLBACKS:
            raise ValueError("timezone must be a supported IANA timezone") from None


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> datetime:
    first = datetime(year, month, 1, tzinfo=timezone.utc)
    day = 1 + (weekday - first.weekday()) % 7 + (occurrence - 1) * 7
    return datetime(year, month, day, tzinfo=timezone.utc)


def _last_weekday(year: int, month: int, weekday: int) -> datetime:
    if month == 12:
        next_month = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    candidate = next_month - timedelta(days=1)
    return candidate - timedelta(days=(candidate.weekday() - weekday) % 7)


def _fallback_offset(now_utc: datetime, timezone_name: str) -> timedelta:
    if timezone_name in {"UTC", "Etc/UTC"}:
        return timedelta(0)
    if timezone_name == "Asia/Shanghai":
        return timedelta(hours=8)
    if timezone_name == "Asia/Tokyo":
        return timedelta(hours=9)
    year = now_utc.year
    if timezone_name == "America/New_York":
        dst_start = _nth_weekday(year, 3, 6, 2) + timedelta(hours=7)
        dst_end = _nth_weekday(year, 11, 6, 1) + timedelta(hours=6)
        return timedelta(hours=-4 if dst_start <= now_utc < dst_end else -5)
    if timezone_name == "Europe/London":
        dst_start = _last_weekday(year, 3, 6) + timedelta(hours=1)
        dst_end = _last_weekday(year, 10, 6) + timedelta(hours=1)
        return timedelta(hours=1 if dst_start <= now_utc < dst_end else 0)
    raise ValueError("timezone must be a supported IANA timezone")


def _local_clock(now: float, timezone_name: str) -> tuple[str, int]:
    utc_value = datetime.fromtimestamp(now, tz=timezone.utc)
    try:
        local = utc_value.astimezone(ZoneInfo(timezone_name))
    except ZoneInfoNotFoundError:
        local = utc_value + _fallback_offset(utc_value, timezone_name)
    return local.date().isoformat(), local.hour * 60 + local.minute


def _in_quiet_hours(settings: ProactiveSettings, minute: int) -> bool:
    if not settings.quiet_hours_enabled:
        return False
    start = _parse_hhmm(settings.quiet_hours_start)
    end = _parse_hhmm(settings.quiet_hours_end)
    if start == end:
        return True
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end


class ActivityFrameStore:
    """SQLite projection store with tombstones and transactional budgets."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS activity_frames (
                  workspace_id TEXT NOT NULL,
                  frame_id TEXT NOT NULL,
                  session_id TEXT NOT NULL,
                  source_kind TEXT NOT NULL,
                  source_id TEXT NOT NULL,
                  source_event_id TEXT NOT NULL,
                  source_created_at REAL NOT NULL,
                  created_at REAL NOT NULL,
                  expires_at REAL NOT NULL,
                  projection_version TEXT NOT NULL,
                  policy_version TEXT NOT NULL,
                  signals_json TEXT NOT NULL,
                  PRIMARY KEY (workspace_id, frame_id),
                  UNIQUE (workspace_id, source_kind, source_id)
                );
                CREATE TABLE IF NOT EXISTS activity_frame_tombstones (
                  workspace_id TEXT NOT NULL,
                  source_kind TEXT NOT NULL,
                  source_id TEXT NOT NULL,
                  frame_id TEXT NOT NULL,
                  reason TEXT NOT NULL,
                  deleted_at REAL NOT NULL,
                  PRIMARY KEY (workspace_id, source_kind, source_id)
                );
                CREATE TABLE IF NOT EXISTS proactive_settings (
                  workspace_id TEXT PRIMARY KEY,
                  settings_json TEXT NOT NULL,
                  revision INTEGER NOT NULL DEFAULT 1,
                  updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS proactive_opportunities (
                  workspace_id TEXT NOT NULL,
                  job_id TEXT NOT NULL,
                  request_id TEXT NOT NULL,
                  frame_id TEXT NOT NULL,
                  source_kind TEXT NOT NULL,
                  local_date TEXT NOT NULL,
                  status TEXT NOT NULL,
                  created_at REAL NOT NULL,
                  resolved_at REAL,
                  expires_at REAL,
                  PRIMARY KEY (workspace_id, job_id)
                );
                CREATE TABLE IF NOT EXISTS proactive_feedback (
                  workspace_id TEXT NOT NULL,
                  feedback_id TEXT NOT NULL,
                  job_id TEXT NOT NULL,
                  request_id TEXT NOT NULL,
                  source_kind TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  created_at REAL NOT NULL,
                  PRIMARY KEY (workspace_id, feedback_id)
                );
                """
            )
            settings_columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(proactive_settings)").fetchall()
            }
            if "revision" not in settings_columns:
                conn.execute(
                    "ALTER TABLE proactive_settings ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"
                )
            opportunity_info = conn.execute(
                "PRAGMA table_info(proactive_opportunities)"
            ).fetchall()
            primary_key = [
                str(row["name"])
                for row in sorted(
                    (row for row in opportunity_info if int(row["pk"]) > 0),
                    key=lambda row: int(row["pk"]),
                )
            ]
            if primary_key != ["workspace_id", "job_id"]:
                conn.executescript(
                    """
                    ALTER TABLE proactive_opportunities
                      RENAME TO proactive_opportunities_legacy;
                    CREATE TABLE proactive_opportunities (
                      workspace_id TEXT NOT NULL,
                      job_id TEXT NOT NULL,
                      request_id TEXT NOT NULL,
                      frame_id TEXT NOT NULL,
                      source_kind TEXT NOT NULL,
                      local_date TEXT NOT NULL,
                      status TEXT NOT NULL,
                      created_at REAL NOT NULL,
                      resolved_at REAL,
                      expires_at REAL,
                      PRIMARY KEY (workspace_id, job_id)
                    );
                    INSERT OR IGNORE INTO proactive_opportunities(
                      workspace_id, job_id, request_id, frame_id, source_kind,
                      local_date, status, created_at, resolved_at
                    )
                    SELECT workspace_id, job_id, request_id, frame_id, source_kind,
                           local_date, status, created_at, resolved_at
                    FROM proactive_opportunities_legacy;
                    DROP TABLE proactive_opportunities_legacy;
                    """
                )
                opportunity_info = conn.execute(
                    "PRAGMA table_info(proactive_opportunities)"
                ).fetchall()
            opportunity_columns = {str(row["name"]) for row in opportunity_info}
            if "expires_at" not in opportunity_columns:
                conn.execute("ALTER TABLE proactive_opportunities ADD COLUMN expires_at REAL")
            conn.execute(
                """CREATE INDEX IF NOT EXISTS proactive_opportunity_budget_idx
                   ON proactive_opportunities(workspace_id, local_date, status)"""
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

    @staticmethod
    def _settings_from_json(raw: str | None) -> ProactiveSettings:
        data = json.loads(raw) if raw else {}
        return ProactiveSettings(**data).validate()

    def get_settings(self, workspace_id: str) -> ProactiveSettings:
        workspace = _bounded_id(workspace_id, "workspaceId")
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT settings_json FROM proactive_settings WHERE workspace_id = ?",
                (workspace,),
            ).fetchone()
        return self._settings_from_json(row["settings_json"] if row else None)

    def get_settings_record(self, workspace_id: str) -> tuple[ProactiveSettings, int, float | None]:
        workspace = _bounded_id(workspace_id, "workspaceId")
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT settings_json, revision, updated_at FROM proactive_settings WHERE workspace_id = ?",
                (workspace,),
            ).fetchone()
        if row is None:
            return ProactiveSettings().validate(), 0, None
        return (
            self._settings_from_json(row["settings_json"]),
            int(row["revision"]),
            float(row["updated_at"]),
        )

    def patch_settings(
        self,
        workspace_id: str,
        patch: Mapping[str, Any],
        *,
        expected_revision: int,
        cancelled_pending: list[dict[str, str]] | None = None,
    ) -> tuple[ProactiveSettings, int, float]:
        workspace = _bounded_id(workspace_id, "workspaceId")
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT settings_json, revision FROM proactive_settings WHERE workspace_id = ?",
                (workspace,),
            ).fetchone()
            revision = int(row["revision"]) if row else 0
            if revision != expected_revision:
                raise LookupError(f"settings revision conflict: expected {expected_revision}, current {revision}")
            current = asdict(self._settings_from_json(row["settings_json"] if row else None))
            current.update(dict(patch))
            settings = ProactiveSettings(**current).validate()
            updated_at = time.time()
            next_revision = revision + 1
            conn.execute(
                """INSERT INTO proactive_settings(workspace_id, settings_json, revision, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(workspace_id) DO UPDATE SET
                     settings_json = excluded.settings_json,
                     revision = excluded.revision,
                     updated_at = excluded.updated_at""",
                (
                    workspace,
                    json.dumps(asdict(settings), sort_keys=True),
                    next_revision,
                    updated_at,
                ),
            )
            conn.execute(
                """UPDATE activity_frames
                   SET expires_at = source_created_at + ?
                   WHERE workspace_id = ?""",
                (settings.retention_days * 86400, workspace),
            )
            _, minute = _local_clock(updated_at, settings.timezone)
            authority_blocked = (
                not settings.enabled
                or not settings.completed_turn_followup_enabled
                or settings.dnd
                or _in_quiet_hours(settings, minute)
            )
            if authority_blocked:
                pending = conn.execute(
                    """SELECT workspace_id, job_id, request_id, source_kind, frame_id
                       FROM proactive_opportunities
                       WHERE workspace_id = ? AND source_kind = ? AND status = 'pending'
                       ORDER BY created_at, job_id""",
                    (workspace, SOURCE_KIND),
                ).fetchall()
                conn.execute(
                    """UPDATE proactive_opportunities
                       SET status = 'cancelled', resolved_at = ?
                       WHERE workspace_id = ? AND source_kind = ? AND status = 'pending'""",
                    (updated_at, workspace, SOURCE_KIND),
                )
                if cancelled_pending is not None:
                    cancelled_pending.extend(self._opportunity_identities(pending))
            pruned = self._prune_expired_locked(conn, workspace, updated_at)
            if cancelled_pending is not None:
                cancelled_pending.extend(pruned)
        return settings, next_revision, updated_at

    def upsert_frame(self, frame: ActivityFrame) -> bool:
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            tombstone = conn.execute(
                """SELECT 1 FROM activity_frame_tombstones
                   WHERE workspace_id = ? AND source_kind = ? AND source_id = ?""",
                (frame.workspace_id, frame.source_kind, frame.source_id),
            ).fetchone()
            if tombstone is not None:
                return False
            conn.execute(
                """INSERT INTO activity_frames(
                     workspace_id, frame_id, session_id, source_kind, source_id,
                     source_event_id, source_created_at, created_at, expires_at,
                     projection_version, policy_version, signals_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(workspace_id, source_kind, source_id) DO UPDATE SET
                     frame_id = excluded.frame_id,
                     session_id = excluded.session_id,
                     source_event_id = excluded.source_event_id,
                     source_created_at = excluded.source_created_at,
                     expires_at = excluded.expires_at,
                     projection_version = excluded.projection_version,
                     policy_version = excluded.policy_version,
                     signals_json = excluded.signals_json""",
                (
                    frame.workspace_id,
                    frame.frame_id,
                    frame.session_id,
                    frame.source_kind,
                    frame.source_id,
                    frame.source_event_id,
                    frame.source_created_at,
                    frame.created_at,
                    frame.expires_at,
                    frame.projection_version,
                    frame.policy_version,
                    json.dumps(dict(frame.signals), sort_keys=True),
                ),
            )
        return True

    @staticmethod
    def _row_to_frame(row: sqlite3.Row) -> ActivityFrame:
        return ActivityFrame(
            frame_id=row["frame_id"],
            workspace_id=row["workspace_id"],
            session_id=row["session_id"],
            source_kind=row["source_kind"],
            source_id=row["source_id"],
            source_event_id=row["source_event_id"],
            source_created_at=float(row["source_created_at"]),
            created_at=float(row["created_at"]),
            expires_at=float(row["expires_at"]),
            projection_version=row["projection_version"],
            policy_version=row["policy_version"],
            signals=json.loads(row["signals_json"]),
        )

    def list_frames(self, workspace_id: str, *, limit: int = 50, now: float | None = None) -> list[ActivityFrame]:
        workspace = _bounded_id(workspace_id, "workspaceId")
        current = time.time() if now is None else float(now)
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM activity_frames WHERE workspace_id = ? AND expires_at > ?
                   ORDER BY source_created_at DESC, frame_id LIMIT ?""",
                (workspace, current, max(1, min(200, int(limit)))),
            ).fetchall()
        return [self._row_to_frame(row) for row in rows]

    def get_frame(self, workspace_id: str, frame_id: str) -> ActivityFrame | None:
        workspace = _bounded_id(workspace_id, "workspaceId")
        frame = _bounded_id(frame_id, "frameId")
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM activity_frames WHERE workspace_id = ? AND frame_id = ?",
                (workspace, frame),
            ).fetchone()
        return self._row_to_frame(row) if row else None

    def delete_frame(
        self,
        workspace_id: str,
        frame_id: str,
        *,
        reason: str = "user_deleted",
        now: float | None = None,
        cancelled_pending: list[dict[str, str]] | None = None,
    ) -> bool:
        workspace = _bounded_id(workspace_id, "workspaceId")
        frame = _bounded_id(frame_id, "frameId")
        current = time.time() if now is None else float(now)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT source_kind, source_id FROM activity_frames
                   WHERE workspace_id = ? AND frame_id = ?""",
                (workspace, frame),
            ).fetchone()
            if row is None:
                tombstone = conn.execute(
                    """SELECT 1 FROM activity_frame_tombstones
                       WHERE workspace_id = ? AND frame_id = ?""",
                    (workspace, frame),
                ).fetchone()
                return tombstone is not None
            conn.execute(
                """INSERT OR IGNORE INTO activity_frame_tombstones(
                     workspace_id, source_kind, source_id, frame_id, reason, deleted_at
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (workspace, row["source_kind"], row["source_id"], frame, reason, current),
            )
            conn.execute(
                "DELETE FROM activity_frames WHERE workspace_id = ? AND frame_id = ?",
                (workspace, frame),
            )
            pending = conn.execute(
                """SELECT workspace_id, job_id, request_id, source_kind, frame_id
                   FROM proactive_opportunities
                   WHERE workspace_id = ? AND frame_id = ? AND status = 'pending'
                   ORDER BY created_at, job_id""",
                (workspace, frame),
            ).fetchall()
            conn.execute(
                """UPDATE proactive_opportunities SET status = 'cancelled', resolved_at = ?
                   WHERE workspace_id = ? AND frame_id = ? AND status = 'pending'""",
                (current, workspace, frame),
            )
            if cancelled_pending is not None:
                cancelled_pending.extend(self._opportunity_identities(pending))
        return True

    def tombstone_source(
        self,
        workspace_id: str,
        source_kind: str,
        source_id: str,
        *,
        reason: str = "source_deleted",
        now: float | None = None,
    ) -> str:
        workspace = _bounded_id(workspace_id, "workspaceId")
        source = _bounded_id(source_id, "sourceId")
        if source_kind != SOURCE_KIND:
            raise ValueError("unknown activity frame source")
        frame_id = deterministic_frame_id(source_kind, source)
        current = time.time() if now is None else float(now)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT OR IGNORE INTO activity_frame_tombstones(
                     workspace_id, source_kind, source_id, frame_id, reason, deleted_at
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (workspace, source_kind, source, frame_id, reason, current),
            )
            conn.execute(
                "DELETE FROM activity_frames WHERE workspace_id = ? AND source_kind = ? AND source_id = ?",
                (workspace, source_kind, source),
            )
        return frame_id

    @staticmethod
    def _opportunity_identities(rows: Any) -> list[dict[str, str]]:
        return [
            {
                "workspace_id": str(row["workspace_id"]),
                "job_id": str(row["job_id"]),
                "request_id": str(row["request_id"]),
                "source_kind": str(row["source_kind"]),
                "frame_id": str(row["frame_id"]),
            }
            for row in rows
        ]

    @classmethod
    def _prune_expired_locked(
        cls,
        conn: sqlite3.Connection,
        workspace: str,
        current: float,
    ) -> list[dict[str, str]]:
        pending = conn.execute(
            """SELECT o.workspace_id, o.job_id, o.request_id, o.source_kind, o.frame_id
               FROM proactive_opportunities AS o
               JOIN activity_frames AS f
                 ON f.workspace_id = o.workspace_id AND f.frame_id = o.frame_id
               WHERE f.workspace_id = ? AND f.expires_at <= ? AND o.status = 'pending'
               ORDER BY o.created_at, o.job_id""",
            (workspace, current),
        ).fetchall()
        rows = conn.execute(
            """SELECT frame_id, source_kind, source_id FROM activity_frames
               WHERE workspace_id = ? AND expires_at <= ?""",
            (workspace, current),
        ).fetchall()
        for row in rows:
            conn.execute(
                """INSERT OR IGNORE INTO activity_frame_tombstones(
                     workspace_id, source_kind, source_id, frame_id, reason, deleted_at
                   ) VALUES (?, ?, ?, ?, 'retention_expired', ?)""",
                (workspace, row["source_kind"], row["source_id"], row["frame_id"], current),
            )
            conn.execute(
                """UPDATE proactive_opportunities
                   SET status = 'cancelled', resolved_at = ?
                   WHERE workspace_id = ? AND frame_id = ? AND status = 'pending'""",
                (current, workspace, row["frame_id"]),
            )
        conn.execute(
            "DELETE FROM activity_frames WHERE workspace_id = ? AND expires_at <= ?",
            (workspace, current),
        )
        return cls._opportunity_identities(pending)

    def prune_expired(
        self,
        workspace_id: str,
        *,
        now: float | None = None,
    ) -> list[dict[str, str]]:
        workspace = _bounded_id(workspace_id, "workspaceId")
        current = time.time() if now is None else float(now)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            return self._prune_expired_locked(conn, workspace, current)

    def evaluate(
        self,
        workspace_id: str,
        frame: ActivityFrame,
        *,
        now: float | None = None,
        interruptible: bool = True,
    ) -> PolicyDecision:
        workspace = _bounded_id(workspace_id, "workspaceId")
        current = time.time() if now is None else float(now)
        settings = self.get_settings(workspace)
        local_date, minute = _local_clock(current, settings.timezone)
        with self._lock, self._connect() as conn:
            delivered = int(
                conn.execute(
                    """SELECT COUNT(*) AS count FROM proactive_opportunities
                       WHERE workspace_id = ? AND local_date = ? AND status = 'delivered'""",
                    (workspace, local_date),
                ).fetchone()["count"]
            )
            pending = int(
                conn.execute(
                    """SELECT COUNT(*) AS count FROM proactive_opportunities
                       WHERE workspace_id = ? AND local_date = ? AND status = 'pending'""",
                    (workspace, local_date),
                ).fetchone()["count"]
            )
            last_delivered = conn.execute(
                """SELECT MAX(resolved_at) AS at FROM proactive_opportunities
                   WHERE workspace_id = ? AND source_kind = ? AND status = 'delivered'""",
                (workspace, frame.source_kind),
            ).fetchone()["at"]
            duplicate = conn.execute(
                """SELECT 1 FROM proactive_opportunities
                   WHERE workspace_id = ? AND frame_id = ? LIMIT 1""",
                (workspace, frame.frame_id),
            ).fetchone() is not None
        remaining = max(0, settings.daily_budget - delivered)
        reason = "allowed"
        if not settings.enabled:
            reason = "global_disabled"
        elif not settings.completed_turn_followup_enabled:
            reason = "source_disabled"
        elif frame.expires_at <= current or self.get_frame(workspace, frame.frame_id) is None:
            reason = "frame_inactive"
        elif settings.dnd:
            reason = "dnd"
        elif _in_quiet_hours(settings, minute):
            reason = "quiet_hours"
        elif not interruptible:
            reason = "not_interruptible"
        elif last_delivered is not None and current - float(last_delivered) < settings.cooldown_seconds:
            reason = "cooldown"
        elif delivered + pending >= settings.daily_budget:
            reason = "daily_budget"
        elif duplicate:
            reason = "duplicate"
        return PolicyDecision(reason == "allowed", reason, current, local_date, remaining)

    def reserve_opportunity(
        self,
        workspace_id: str,
        *,
        job_id: str,
        request_id: str,
        frame_id: str,
        source_kind: str,
        local_date: str,
        interruptible: bool = True,
        expires_at: float | None = None,
        now: float | None = None,
    ) -> bool:
        workspace = _bounded_id(workspace_id, "workspaceId")
        current = time.time() if now is None else float(now)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """SELECT workspace_id, request_id, frame_id, source_kind,
                          local_date, status, expires_at
                   FROM proactive_opportunities
                   WHERE workspace_id = ? AND job_id = ?""",
                (workspace, job_id),
            ).fetchone()
            settings_row = conn.execute(
                "SELECT settings_json FROM proactive_settings WHERE workspace_id = ?",
                (workspace,),
            ).fetchone()
            settings = self._settings_from_json(
                settings_row["settings_json"] if settings_row else None
            )
            if (
                not settings.enabled
                or not settings.completed_turn_followup_enabled
                or settings.dnd
            ):
                return False
            computed_local_date, minute = _local_clock(current, settings.timezone)
            if _in_quiet_hours(settings, minute) or not interruptible:
                return False
            frame = conn.execute(
                """SELECT source_kind, source_id, session_id, source_created_at, expires_at
                   FROM activity_frames
                   WHERE workspace_id = ? AND frame_id = ? AND source_kind = ?
                     AND expires_at > ?""",
                (workspace, frame_id, source_kind, current),
            ).fetchone()
            if frame is None:
                return False
            tombstoned = conn.execute(
                """SELECT 1 FROM activity_frame_tombstones
                   WHERE workspace_id = ? AND source_kind = ? AND source_id = ?""",
                (workspace, source_kind, frame["source_id"]),
            ).fetchone()
            if tombstoned is not None:
                return False
            effective_frame_expiry = min(
                float(frame["expires_at"]),
                float(frame["source_created_at"]) + settings.retention_days * 86400,
            )
            if effective_frame_expiry <= current:
                return False
            last_delivered = conn.execute(
                """SELECT MAX(resolved_at) AS at FROM proactive_opportunities
                   WHERE workspace_id = ? AND source_kind = ? AND status = 'delivered'""",
                (workspace, source_kind),
            ).fetchone()["at"]
            if (
                last_delivered is not None
                and current - float(last_delivered) < settings.cooldown_seconds
            ):
                return False
            exact_existing = bool(
                existing is not None
                and existing["request_id"] == request_id
                and existing["frame_id"] == frame_id
                and existing["source_kind"] == source_kind
                and existing["status"] == "pending"
                and (
                    existing["expires_at"] is None
                    or float(existing["expires_at"]) > current
                )
            )
            if existing is not None and not exact_existing:
                return False
            duplicate = conn.execute(
                """SELECT 1 FROM proactive_opportunities
                   WHERE workspace_id = ? AND frame_id = ?
                     AND NOT (workspace_id = ? AND job_id = ?)
                   LIMIT 1""",
                (workspace, frame_id, workspace, job_id),
            ).fetchone()
            if duplicate is not None:
                return False
            used = int(
                conn.execute(
                    """SELECT COUNT(*) AS count FROM proactive_opportunities
                       WHERE workspace_id = ? AND local_date = ?
                         AND status IN ('pending', 'delivered')
                         AND NOT (workspace_id = ? AND job_id = ?)""",
                    (workspace, computed_local_date, workspace, job_id),
                ).fetchone()["count"]
            )
            if used >= settings.daily_budget:
                return False
            opportunity_expires_at = (
                min(float(expires_at), effective_frame_expiry)
                if expires_at is not None
                else effective_frame_expiry
            )
            if opportunity_expires_at <= current:
                return False
            if exact_existing:
                conn.execute(
                    """UPDATE proactive_opportunities
                       SET local_date = ?, expires_at = ?
                       WHERE workspace_id = ? AND job_id = ? AND status = 'pending'""",
                    (computed_local_date, opportunity_expires_at, workspace, job_id),
                )
                return True
            conn.execute(
                """INSERT OR IGNORE INTO proactive_opportunities(
                     workspace_id, job_id, request_id, frame_id, source_kind,
                     local_date, status, created_at, expires_at
                   ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (
                    workspace,
                    job_id,
                    request_id,
                    frame_id,
                    source_kind,
                    computed_local_date,
                    current,
                    opportunity_expires_at,
                ),
            )
            return conn.execute("SELECT changes() AS count").fetchone()["count"] == 1

    def pending_for_frame(self, workspace_id: str, frame_id: str) -> dict[str, str] | None:
        workspace = _bounded_id(workspace_id, "workspaceId")
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """SELECT job_id, request_id, local_date, expires_at
                   FROM proactive_opportunities
                   WHERE workspace_id = ? AND frame_id = ? AND status = 'pending'""",
                (workspace, frame_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "job_id": str(row["job_id"]),
            "request_id": str(row["request_id"]),
            "local_date": str(row["local_date"]),
            "expires_at": str(row["expires_at"] or ""),
        }

    def list_pending_opportunities(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """SELECT o.workspace_id, o.job_id, o.request_id, o.frame_id,
                          o.source_kind, o.local_date, o.expires_at,
                          f.source_id, f.session_id
                   FROM proactive_opportunities AS o
                   LEFT JOIN activity_frames AS f
                     ON f.workspace_id = o.workspace_id AND f.frame_id = o.frame_id
                   WHERE o.status = 'pending'
                   ORDER BY o.created_at, o.workspace_id, o.job_id"""
            ).fetchall()
        return [dict(row) for row in rows]

    def resolve_opportunity(
        self,
        *,
        workspace_id: str,
        job_id: str,
        request_id: str,
        source_kind: str,
        outcome: str,
        now: float | None = None,
    ) -> bool:
        current = time.time() if now is None else float(now)
        if outcome not in {"delivered", "suppressed", "expired", "cancelled", "failed"}:
            raise ValueError("unknown proactive opportunity outcome")
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT workspace_id, request_id, frame_id, source_kind,
                          status, expires_at
                   FROM proactive_opportunities
                   WHERE workspace_id = ? AND job_id = ?""",
                (workspace_id, job_id),
            ).fetchone()
            if row is None or any(
                (
                    row["workspace_id"] != workspace_id,
                    row["request_id"] != request_id,
                    row["source_kind"] != source_kind,
                )
            ):
                return False
            if row["status"] == outcome:
                return True
            if row["status"] != "pending":
                return False
            local_date: str | None = None
            if outcome == "delivered":
                settings_row = conn.execute(
                    "SELECT settings_json FROM proactive_settings WHERE workspace_id = ?",
                    (workspace_id,),
                ).fetchone()
                settings = self._settings_from_json(
                    settings_row["settings_json"] if settings_row else None
                )
                local_date, minute = _local_clock(current, settings.timezone)
                if (
                    not settings.enabled
                    or not settings.completed_turn_followup_enabled
                    or settings.dnd
                    or _in_quiet_hours(settings, minute)
                    or (row["expires_at"] is not None and float(row["expires_at"]) <= current)
                ):
                    return False
                frame = conn.execute(
                    """SELECT source_created_at, expires_at FROM activity_frames
                       WHERE workspace_id = ? AND frame_id = ? AND source_kind = ?""",
                    (workspace_id, row["frame_id"], source_kind),
                ).fetchone()
                if frame is None or min(
                    float(frame["expires_at"]),
                    float(frame["source_created_at"]) + settings.retention_days * 86400,
                ) <= current:
                    return False
                delivered = int(
                    conn.execute(
                        """SELECT COUNT(*) AS count FROM proactive_opportunities
                           WHERE workspace_id = ? AND local_date = ? AND status = 'delivered'""",
                        (workspace_id, local_date),
                    ).fetchone()["count"]
                )
                if delivered >= settings.daily_budget:
                    return False
                last_delivered = conn.execute(
                    """SELECT MAX(resolved_at) AS at FROM proactive_opportunities
                       WHERE workspace_id = ? AND source_kind = ? AND status = 'delivered'""",
                    (workspace_id, source_kind),
                ).fetchone()["at"]
                if (
                    last_delivered is not None
                    and current - float(last_delivered) < settings.cooldown_seconds
                ):
                    return False
            cursor = conn.execute(
                """UPDATE proactive_opportunities
                   SET status = ?, resolved_at = ?, local_date = COALESCE(?, local_date)
                   WHERE workspace_id = ? AND job_id = ? AND request_id = ?
                     AND source_kind = ? AND status = 'pending'""",
                (
                    outcome,
                    current,
                    local_date,
                    workspace_id,
                    job_id,
                    request_id,
                    source_kind,
                ),
            )
            return cursor.rowcount == 1

    def cancel_pending(
        self,
        workspace_id: str,
        source_kind: str,
        *,
        frame_id: str | None = None,
        now: float | None = None,
    ) -> int:
        workspace = _bounded_id(workspace_id, "workspaceId")
        current = time.time() if now is None else float(now)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if frame_id is None:
                cursor = conn.execute(
                    """UPDATE proactive_opportunities SET status = 'cancelled', resolved_at = ?
                       WHERE workspace_id = ? AND source_kind = ? AND status = 'pending'""",
                    (current, workspace, source_kind),
                )
            else:
                cursor = conn.execute(
                    """UPDATE proactive_opportunities SET status = 'cancelled', resolved_at = ?
                       WHERE workspace_id = ? AND source_kind = ? AND frame_id = ?
                         AND status = 'pending'""",
                    (current, workspace, source_kind, frame_id),
                )
            return cursor.rowcount

    def record_feedback(
        self,
        workspace_id: str,
        *,
        feedback_id: str,
        job_id: str,
        request_id: str,
        source_kind: str,
        kind: str,
        now: float | None = None,
    ) -> tuple[bool, str, list[tuple[str, str]]]:
        workspace = _bounded_id(workspace_id, "workspaceId")
        feedback = _bounded_id(feedback_id, "feedbackId")
        if kind not in FEEDBACK_KINDS:
            raise ValueError("unknown feedback kind")
        current = time.time() if now is None else float(now)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """SELECT job_id, request_id, kind, source_kind FROM proactive_feedback
                   WHERE workspace_id = ? AND feedback_id = ?""",
                (workspace, feedback),
            ).fetchone()
            if existing is not None:
                same = (
                    existing["job_id"] == job_id
                    and existing["request_id"] == request_id
                    and existing["kind"] == kind
                )
                if not same:
                    raise ValueError("feedbackId is already bound to another feedback record")
                return False, str(existing["source_kind"]), []
            opportunity = conn.execute(
                """SELECT source_kind FROM proactive_opportunities
                   WHERE workspace_id = ? AND job_id = ? AND request_id = ? AND source_kind = ?""",
                (workspace, job_id, request_id, source_kind),
            ).fetchone()
            if opportunity is None:
                raise LookupError("proactive opportunity was not found")
            source_kind = str(opportunity["source_kind"])
            conn.execute(
                """INSERT INTO proactive_feedback(
                     workspace_id, feedback_id, job_id, request_id, source_kind, kind, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (workspace, feedback, job_id, request_id, source_kind, kind, current),
            )
            cancelled: list[tuple[str, str]] = []
            if kind == "never_source":
                row = conn.execute(
                    "SELECT settings_json, revision FROM proactive_settings WHERE workspace_id = ?",
                    (workspace,),
                ).fetchone()
                settings = self._settings_from_json(row["settings_json"] if row else None)
                disabled = ProactiveSettings(
                    **{**asdict(settings), "completed_turn_followup_enabled": False}
                ).validate()
                revision = int(row["revision"]) if row and "revision" in row else 0
                conn.execute(
                    """INSERT INTO proactive_settings(workspace_id, settings_json, revision, updated_at)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(workspace_id) DO UPDATE SET
                         settings_json = excluded.settings_json,
                         revision = proactive_settings.revision + 1,
                         updated_at = excluded.updated_at""",
                    (workspace, json.dumps(asdict(disabled), sort_keys=True), revision + 1, current),
                )
                pending = conn.execute(
                    """SELECT job_id, request_id FROM proactive_opportunities
                       WHERE workspace_id = ? AND source_kind = ? AND status = 'pending'""",
                    (workspace, source_kind),
                ).fetchall()
                cancelled = [(str(row["job_id"]), str(row["request_id"])) for row in pending]
                conn.execute(
                    """UPDATE proactive_opportunities SET status = 'cancelled', resolved_at = ?
                       WHERE workspace_id = ? AND source_kind = ? AND status = 'pending'""",
                    (current, workspace, source_kind),
                )
        return True, source_kind, cancelled


class ActivityFrameService:
    """Coordinates deterministic projection, policy, and existing heartbeat jobs."""

    def __init__(self, store: ActivityFrameStore, turn_store: Any) -> None:
        self.store = store
        self.turn_store = turn_store
        self._scheduler: Any | None = None

    def bind_scheduler(self, scheduler: Any | None) -> None:
        self._scheduler = scheduler
        if scheduler is not None:
            scheduler.set_proactive_outcome_observer(self.observe_outcome)
            self._restore_pending_opportunities(scheduler)

    def _restore_pending_opportunities(self, scheduler: Any) -> None:
        interruptible = bool(
            not hasattr(scheduler, "proactive_interruptible")
            or scheduler.proactive_interruptible()
        )
        for pending in self.store.list_pending_opportunities():
            workspace_id = str(pending.get("workspace_id") or "")
            frame_id = str(pending.get("frame_id") or "")
            frame = self.store.get_frame(workspace_id, frame_id)
            if frame is None:
                self.store.cancel_pending(
                    workspace_id,
                    str(pending.get("source_kind") or SOURCE_KIND),
                    frame_id=frame_id,
                )
                continue
            decision = self.store.evaluate(
                workspace_id,
                frame,
                interruptible=interruptible,
            )
            if not self._emit_opportunity(frame, decision, pending=pending):
                self.store.cancel_pending(
                    workspace_id,
                    frame.source_kind,
                    frame_id=frame.frame_id,
                )

    @staticmethod
    def project_event(event: Mapping[str, Any], retention_days: int) -> ActivityFrame | None:
        if event.get("event_type") != "turn.committed":
            return None
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            raise TypeError("activity frame projection requires a turn.committed payload")
        workspace_id = _bounded_id(payload.get("workspace_id") or "default", "workspaceId")
        session_id = _bounded_id(payload.get("session_id"), "sessionId")
        source_id = _bounded_id(event.get("idempotency_key"), "sourceId")
        source_event_id = _bounded_id(str(event.get("event_id")), "sourceEventId")
        authoritative_created_at = payload.get("committed_at") or event.get("created_at")
        if authoritative_created_at is None:
            raise ValueError(
                "turn.committed projection requires an authoritative committed timestamp"
            )
        source_created_at = float(authoritative_created_at)
        messages = payload.get("messages")
        user_message_count = 0
        if isinstance(messages, list):
            user_message_count = min(20, sum(1 for item in messages if isinstance(item, Mapping) and item.get("role") == "user"))
        signals = {
            "kind": SOURCE_KIND,
            "turnCompleted": True,
            "assistantReplyPresent": bool(str(payload.get("reply") or "").strip()),
            "userMessageCount": user_message_count,
            "hadToolCalls": bool(payload.get("tool_calls")),
            "trigger": (
                str(payload.get("trigger"))
                if str(payload.get("trigger") or "") in {"socket", "voice", "schedule", "plugin"}
                else "other"
            ),
        }
        return ActivityFrame(
            frame_id=deterministic_frame_id(SOURCE_KIND, source_id),
            workspace_id=workspace_id,
            session_id=session_id,
            source_kind=SOURCE_KIND,
            source_id=source_id,
            source_event_id=source_event_id,
            source_created_at=source_created_at,
            created_at=source_created_at,
            expires_at=source_created_at + retention_days * 86400,
            projection_version=PROJECTION_VERSION,
            policy_version=POLICY_VERSION,
            signals=signals,
        )

    def project(self, event: Mapping[str, Any], _context: Any | None = None) -> dict[str, Any]:
        payload = event.get("payload")
        workspace_id = str(payload.get("workspace_id") or "default") if isinstance(payload, Mapping) else "default"
        settings = self.store.get_settings(workspace_id)
        frame = self.project_event(event, settings.retention_days)
        if frame is None:
            return {"projected": False, "reason": "unsupported_event"}
        if not self.store.upsert_frame(frame):
            return {"projected": False, "reason": "tombstoned", "frameId": frame.frame_id}
        scheduler = self._scheduler
        interruptible = bool(
            scheduler is None
            or not hasattr(scheduler, "proactive_interruptible")
            or scheduler.proactive_interruptible()
        )
        decision = self.store.evaluate(
            frame.workspace_id,
            frame,
            interruptible=interruptible,
        )
        if decision.allowed:
            self._emit_opportunity(frame, decision)
        elif decision.reason in {"daily_budget", "duplicate"}:
            pending = self.store.pending_for_frame(frame.workspace_id, frame.frame_id)
            if pending is not None:
                self._emit_opportunity(frame, decision, pending=pending)
        return {"projected": True, "frameId": frame.frame_id, "policy": decision.to_api()}

    def _emit_opportunity(
        self,
        frame: ActivityFrame,
        decision: PolicyDecision,
        *,
        pending: Mapping[str, Any] | None = None,
    ) -> bool:
        scheduler = self._scheduler
        if scheduler is None:
            return False
        suffix = hashlib.sha256(
            f"{frame.workspace_id}\0{frame.frame_id}\0{frame.source_kind}".encode()
        ).hexdigest()[:20]
        job_id = str((pending or {}).get("job_id") or f"activityframejob_{suffix}")
        request_id = str((pending or {}).get("request_id") or f"activityframereq_{suffix}")
        local_date = str((pending or {}).get("local_date") or decision.local_date)
        interruptible = bool(
            not hasattr(scheduler, "proactive_interruptible")
            or scheduler.proactive_interruptible()
        )
        pending_expiry = (pending or {}).get("expires_at")
        if pending_expiry is None or pending_expiry == "":
            ttl_seconds = (
                float(scheduler.proactive_opportunity_ttl_seconds())
                if hasattr(scheduler, "proactive_opportunity_ttl_seconds")
                else 120.0
            )
            opportunity_expires_at = time.time() + ttl_seconds
        else:
            opportunity_expires_at = float(str(pending_expiry))
        if not self.store.reserve_opportunity(
            frame.workspace_id,
            job_id=job_id,
            request_id=request_id,
            frame_id=frame.frame_id,
            source_kind=frame.source_kind,
            local_date=local_date,
            interruptible=interruptible,
            expires_at=opportunity_expires_at,
        ):
            return False
        event = {
            "type": "completed_turn_followup",
            "tick": max(0, round(frame.source_created_at * 1000)),
            "at": datetime.fromtimestamp(frame.source_created_at, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "trigger_reason": "completed_turn_followup",
            "source_kind": frame.source_kind,
            "source_id": frame.source_id,
            "frame_id": frame.frame_id,
            "session_id": frame.session_id,
            "job_id": job_id,
            "request_id": request_id,
            "expires_at": opportunity_expires_at,
            "content_code": SOURCE_KIND,
            "message": "Would you like to continue where we left off?",
        }
        if not scheduler.emit_proactive_opportunity(event, workspace_id=frame.workspace_id):
            self.store.resolve_opportunity(
                workspace_id=frame.workspace_id,
                job_id=job_id,
                request_id=request_id,
                source_kind=frame.source_kind,
                outcome="failed",
            )
            return False
        return True

    def observe_outcome(self, record: Mapping[str, Any], outcome: str) -> bool:
        if str(record.get("source_kind") or "") != SOURCE_KIND:
            return True
        return self.store.resolve_opportunity(
            workspace_id=str(record.get("workspace_id") or ""),
            job_id=str(record.get("job_id") or ""),
            request_id=str(record.get("request_id") or ""),
            source_kind=str(record.get("source_kind") or ""),
            outcome=outcome,
        )

    def get_settings(self, workspace_id: str) -> dict[str, Any]:
        settings, revision, updated_at = self.store.get_settings_record(workspace_id)
        return {
            **settings.to_api(),
            "workspaceId": workspace_id,
            "revision": revision,
            "updatedAt": updated_at,
        }

    def patch_settings(self, workspace_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        allowed = {"expectedRevision", "enabled", "sourceEnabled", "dnd", "quietHours", "dailyBudget", "cooldownSeconds", "retentionDays"}
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"unknown settings fields: {', '.join(sorted(unknown))}")
        expected_revision = payload.get("expectedRevision")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
            raise ValueError("expectedRevision must be a non-negative integer")
        patch: dict[str, Any] = {}
        for key in ("enabled", "dnd"):
            if key in payload:
                if not isinstance(payload[key], bool):
                    raise ValueError(f"{key} must be a boolean")
                patch[key] = payload[key]
        source = payload.get("sourceEnabled")
        if source is not None:
            if not isinstance(source, Mapping) or set(source) != {SOURCE_KIND} or not isinstance(source[SOURCE_KIND], bool):
                raise ValueError(f"sourceEnabled must contain only boolean {SOURCE_KIND}")
            patch["completed_turn_followup_enabled"] = source[SOURCE_KIND]
        quiet = payload.get("quietHours")
        if quiet is not None:
            if not isinstance(quiet, Mapping) or set(quiet) - {"enabled", "start", "end", "timezone"}:
                raise ValueError("quietHours contains unknown fields")
            if "enabled" in quiet and not isinstance(quiet["enabled"], bool):
                raise ValueError("quietHours.enabled must be a boolean")
            mapping = {
                "enabled": "quiet_hours_enabled",
                "start": "quiet_hours_start",
                "end": "quiet_hours_end",
                "timezone": "timezone",
            }
            patch.update({mapping[key]: value for key, value in quiet.items()})
        integer_fields = {
            "dailyBudget": "daily_budget",
            "cooldownSeconds": "cooldown_seconds",
            "retentionDays": "retention_days",
        }
        for external, internal in integer_fields.items():
            if external in payload:
                value = payload[external]
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError(f"{external} must be an integer")
                patch[internal] = value
        cancelled_pending: list[dict[str, str]] = []
        settings, revision, updated_at = self.store.patch_settings(
            workspace_id,
            patch,
            expected_revision=expected_revision,
            cancelled_pending=cancelled_pending,
        )
        self._settle_cancelled_opportunities(
            cancelled_pending,
            reason="proactive_policy_changed",
        )
        return {
            **settings.to_api(),
            "workspaceId": workspace_id,
            "revision": revision,
            "updatedAt": updated_at,
        }

    def list_frames(self, workspace_id: str, limit: int = 50) -> dict[str, Any]:
        self._settle_cancelled_opportunities(
            self.store.prune_expired(workspace_id),
            reason="retention_expired",
        )
        frames = self.store.list_frames(workspace_id, limit=limit)
        return {
            "schemaVersion": SCHEMA_VERSION,
            "workspaceId": workspace_id,
            "frames": [frame.to_api() for frame in frames],
        }

    def delete_frame(self, workspace_id: str, frame_id: str) -> bool:
        cancelled_pending: list[dict[str, str]] = []
        deleted = self.store.delete_frame(
            workspace_id,
            frame_id,
            cancelled_pending=cancelled_pending,
        )
        self._settle_cancelled_opportunities(
            cancelled_pending,
            reason="activity_frame_deleted",
        )
        return deleted

    def rebuild(self, workspace_id: str, limit: int = 1000) -> dict[str, Any]:
        projected = 0
        tombstoned = 0
        for commit in self.turn_store.list_commits(workspace_id, limit=limit):
            frame = self.project_event(commit, self.store.get_settings(workspace_id).retention_days)
            if frame is None:
                continue
            if self.store.upsert_frame(frame):
                projected += 1
            else:
                tombstoned += 1
        return {
            "workspaceId": workspace_id,
            "projected": projected,
            "tombstoned": tombstoned,
            "projectionVersion": PROJECTION_VERSION,
        }

    def feedback(self, workspace_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        allowed = {"feedbackId", "jobId", "requestId", "sourceKind", "kind"}
        unknown = set(payload) - allowed
        if unknown or set(payload) != allowed:
            raise ValueError("feedback requires only feedbackId, jobId, requestId, sourceKind, and kind")
        if payload["sourceKind"] != SOURCE_KIND:
            raise ValueError("unknown proactive sourceKind")
        created, source_kind, cancelled = self.store.record_feedback(
            workspace_id,
            feedback_id=str(payload["feedbackId"]),
            job_id=str(payload["jobId"]),
            request_id=str(payload["requestId"]),
            source_kind=str(payload["sourceKind"]),
            kind=str(payload["kind"]),
        )
        if payload["kind"] == "never_source":
            self._cancel_source_pending(
                workspace_id,
                source_kind,
                "feedback_never_source",
            )
        return {
            "ok": True,
            "duplicate": not created,
            "feedbackId": payload["feedbackId"],
            "sourceKind": source_kind,
            "cancelledPending": len(cancelled),
        }

    def _cancel_source_pending(
        self,
        workspace_id: str,
        source_kind: str,
        reason: str,
        *,
        frame_id: str | None = None,
    ) -> int:
        self.store.cancel_pending(
            workspace_id,
            source_kind,
            frame_id=frame_id,
        )
        scheduler = self._scheduler
        if scheduler is None:
            return 0
        return int(
            scheduler.cancel_proactive_opportunities(
                workspace_id=workspace_id,
                source_kind=source_kind,
                reason=reason,
                frame_id=frame_id,
            )
        )

    def _settle_cancelled_opportunities(
        self,
        cancelled: list[dict[str, str]],
        *,
        reason: str,
    ) -> int:
        scheduler = self._scheduler
        if scheduler is None:
            return 0
        resolved = 0
        seen: set[tuple[str, str]] = set()
        for identity in cancelled:
            job_id = identity["job_id"]
            request_id = identity["request_id"]
            key = (job_id, request_id)
            if key in seen:
                continue
            seen.add(key)
            if scheduler.resolve_opportunity(
                job_id=job_id,
                request_id=request_id,
                outcome="cancelled",
                reason=reason,
            ):
                resolved += 1
        return resolved


# Retained as a compatibility helper for callers from earlier phases. It is not
# used as the durable policy authority.
class ProactiveBudget:
    def __init__(self, *, max_events: int = 3, window_seconds: float = 3600.0) -> None:
        if max_events < 1 or window_seconds <= 0:
            raise ValueError("proactive budget values must be positive")
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._events: dict[str, list[float]] = {}

    def consume(self, scope: str, *, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        events = [stamp for stamp in self._events.get(scope, []) if current - stamp < self.window_seconds]
        if len(events) >= self.max_events:
            self._events[scope] = events
            return False
        self._events[scope] = [*events, current]
        return True

    def remaining(self, scope: str, *, now: float | None = None) -> int:
        current = time.time() if now is None else now
        events = [stamp for stamp in self._events.get(scope, []) if current - stamp < self.window_seconds]
        self._events[scope] = events
        return max(0, self.max_events - len(events))


__all__ = [
    "FEEDBACK_KINDS",
    "GATE_ORDER",
    "POLICY_VERSION",
    "PROJECTION_VERSION",
    "SOURCE_KIND",
    "ActivityFrame",
    "ActivityFrameService",
    "ActivityFrameStore",
    "ProactiveBudget",
    "ProactiveSettings",
    "deterministic_frame_id",
]
