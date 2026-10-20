"""Durable settings snapshots so rollback survives a backend restart.

The in-memory list this replaces was lost on every restart, which made the
rollback action silently unavailable after a crash or a supervised restart.
Snapshots are scrubbed of provider credentials before they reach disk; the
rollback path merges the current secrets back in.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.paths import data_dir_from_env
from .settings_store import scrub_sensitive_settings
from .settings_schema import PersistedSettingsSchema
from ..core.file_lock import exclusive_file_lock

logger = logging.getLogger(__name__)

MAX_SETTINGS_SNAPSHOTS = 20
_STORE_VERSION = 1

SettingsSnapshot = dict[str, Any]


class SettingsHistoryStoreCorrupt(RuntimeError):
    """Durable history exists but cannot be trusted for rollback."""


class SettingsHistoryStore:
    """Bounded, atomic, process-local settings snapshot history."""

    def __init__(self, storage_path: str | Path | None = None) -> None:
        self.storage_path = (
            Path(storage_path)
            if storage_path is not None
            else data_dir_from_env() / "settings_history.json"
        )
        self._lock = threading.RLock()
        self.lock_path = self.storage_path.with_name(f"{self.storage_path.name}.lock")
        self._snapshots: list[SettingsSnapshot] = self._load()

    def _load(self) -> list[SettingsSnapshot]:
        if not self.storage_path.exists():
            return []
        with exclusive_file_lock(self.lock_path):
            return self._read()

    def _read(self) -> list[SettingsSnapshot]:
        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except OSError as exc:
            if not self.storage_path.exists():
                return []
            logger.warning("Settings history store unreadable at %s: %s", self.storage_path, exc)
            raise RuntimeError("settings_history_store_unreadable") from exc
        except json.JSONDecodeError as exc:
            logger.warning("Settings history store is not valid JSON at %s: %s", self.storage_path, exc)
            self._quarantine_corrupt_store()
            raise SettingsHistoryStoreCorrupt("settings_history_store_corrupt") from exc
        if not isinstance(payload, dict):
            self._quarantine_corrupt_store()
            raise SettingsHistoryStoreCorrupt("settings_history_store_corrupt")
        raw_snapshots = payload.get("snapshots")
        if payload.get("version") != _STORE_VERSION or not isinstance(raw_snapshots, list):
            self._quarantine_corrupt_store()
            raise SettingsHistoryStoreCorrupt("settings_history_store_corrupt")
        snapshots: list[SettingsSnapshot] = []
        for entry in raw_snapshots:
            if not isinstance(entry, dict):
                self._quarantine_corrupt_store()
                raise SettingsHistoryStoreCorrupt("settings_history_store_corrupt")
            try:
                validated = PersistedSettingsSchema.model_validate(entry).model_dump()
            except Exception as exc:
                self._quarantine_corrupt_store()
                raise SettingsHistoryStoreCorrupt("settings_history_store_corrupt") from exc
            snapshots.append(deepcopy(validated))
        return snapshots[-MAX_SETTINGS_SNAPSHOTS:]

    def _quarantine_corrupt_store(self) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = self.storage_path.with_name(f"{self.storage_path.name}.corrupt-{timestamp}")
        try:
            os.replace(self.storage_path, backup)
            logger.warning("Quarantined corrupt settings history at %s", backup)
        except OSError as exc:
            logger.warning("Could not quarantine settings history at %s: %s", self.storage_path, exc)

    def _write(self, snapshots: list[SettingsSnapshot]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": _STORE_VERSION, "snapshots": snapshots}
        fd, temporary_name = tempfile.mkstemp(
            dir=self.storage_path.parent,
            prefix=".settings-history.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.storage_path)
            try:
                os.chmod(self.storage_path, 0o600)
            except OSError:
                pass
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise

    def append(self, snapshot: SettingsSnapshot) -> None:
        if not isinstance(snapshot, dict):
            raise ValueError("settings snapshot must be a JSON object")
        sanitized = deepcopy(scrub_sensitive_settings(snapshot))
        with self._lock, exclusive_file_lock(self.lock_path):
            current = self._read()
            next_snapshots = [*current, sanitized][-MAX_SETTINGS_SNAPSHOTS:]
            self._write(next_snapshots)
            self._snapshots = next_snapshots

    def __len__(self) -> int:
        with self._lock, exclusive_file_lock(self.lock_path):
            return len(self._read())

    def peek(self, steps: int) -> SettingsSnapshot | None:
        if steps <= 0:
            return None
        with self._lock, exclusive_file_lock(self.lock_path):
            snapshots = self._read()
            if steps > len(snapshots):
                return None
            return deepcopy(snapshots[-steps])

    def pop(self, steps: int) -> SettingsSnapshot | None:
        """Return the target snapshot and drop it plus newer entries."""
        if steps <= 0:
            return None
        with self._lock, exclusive_file_lock(self.lock_path):
            snapshots = self._read()
            if steps > len(snapshots):
                return None
            target = deepcopy(snapshots[-steps])
            next_snapshots = snapshots[:-steps]
            self._write(next_snapshots)
            self._snapshots = next_snapshots
            return target

    def clear(self) -> None:
        with self._lock, exclusive_file_lock(self.lock_path):
            self._write([])
            self._snapshots = []


__all__ = [
    "MAX_SETTINGS_SNAPSHOTS",
    "SettingsHistoryStore",
    "SettingsHistoryStoreCorrupt",
    "SettingsSnapshot",
]
