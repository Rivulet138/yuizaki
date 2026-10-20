"""Legacy workspace context sidecar, kept for one-way upgrade.

Workspace prompt context (role card, world book, prompt engineering, vision
and memory policy) now lives on the workspace row in SQLite, so it commits in
the same transaction as the rest of the workspace metadata. This module
remains for three reasons: it holds the shared payload validator, it lets the
startup migration read an existing ``workspace_contexts.json`` exactly once,
and it keeps the file-lock primitive available to the other JSON stores.

Each entry carries a monotonically increasing revision so two clients could
detect a lost update. File writes are serialized with an OS file lock, so two
processes doing a read-modify-write of the same file cannot drop one another's
entry.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.file_lock import exclusive_file_lock
from ..core.paths import data_dir_from_env

logger = logging.getLogger(__name__)

MAX_CONTEXT_BYTES = 2 * 1024 * 1024
_STORE_VERSION = 2


class WorkspaceContextConflict(RuntimeError):
    """Raised when a write is based on a stale context revision."""

    def __init__(self, workspace_id: str, expected: int, current: int) -> None:
        super().__init__(
            f"workspace context revision conflict for {workspace_id}: expected {expected}, current {current}"
        )
        self.workspace_id = workspace_id
        self.expected = expected
        self.current = current


def validate_context_payload(context: Any) -> None:
    """Reject a context payload that cannot be stored safely.

    Shared by the API (database-backed context) and the legacy sidecar store so
    both enforce the same shape and size limits.
    """
    if not isinstance(context, dict):
        raise ValueError("workspace context must be a JSON object")
    serialized = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > MAX_CONTEXT_BYTES:
        raise ValueError("workspace context is too large")


class WorkspaceContextStore:
    def __init__(self, storage_path: str | Path | None = None) -> None:
        self.storage_path = (
            Path(storage_path)
            if storage_path is not None
            else data_dir_from_env() / "workspace_contexts.json"
        )
        self.lock_path = self.storage_path.with_name(f"{self.storage_path.name}.lock")
        self._lock = threading.RLock()
        self._entries: dict[str, dict[str, Any]] = self._load()

    # -- serialization -----------------------------------------------------

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.storage_path.exists():
            return {}
        # Read under the same lock. On Windows an open reader makes
        # os.replace fail, so an unlocked load can break a concurrent writer.
        with exclusive_file_lock(self.lock_path):
            for attempt in range(3):
                parsed = self._parse(self.storage_path, quarantine=True)
                if parsed is not None:
                    return parsed
                if not self.storage_path.exists():
                    return {}
                # Another process may be replacing the file right now; a short
                # retry avoids treating a transient read error as corruption.
                if attempt < 2:
                    time.sleep(0.02)
            return {}

    def _parse(self, path: Path, *, quarantine: bool) -> dict[str, dict[str, Any]] | None:
        """Return parsed entries, or ``None`` when the file cannot be trusted."""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            # Transient: the file may be mid-replace by another process.
            logger.warning("Workspace context store unreadable at %s: %s", path, exc)
            return None
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("Workspace context store is not valid JSON at %s: %s", path, exc)
            if quarantine:
                self._quarantine_corrupt_store()
            return None
        if not isinstance(payload, dict) or not isinstance(payload.get("workspaces"), dict):
            logger.warning("Workspace context store at %s has an unsupported shape", path)
            if quarantine:
                self._quarantine_corrupt_store()
            return None
        raw_contexts = payload["workspaces"]
        entries: dict[str, dict[str, Any]] = {}
        for workspace_id, value in raw_contexts.items():
            if not isinstance(workspace_id, str) or not workspace_id.strip():
                continue
            if not isinstance(value, dict):
                continue
            # Version 1 stored the context object directly.
            if isinstance(value.get("context"), dict):
                context = value["context"]
                revision = value.get("revision")
                updated_at = value.get("updatedAt")
            else:
                context = value
                revision = 0
                updated_at = None
            entries[workspace_id] = {
                "context": deepcopy(context),
                "revision": int(revision) if isinstance(revision, int) and revision >= 0 else 0,
                "updatedAt": updated_at if isinstance(updated_at, str) else None,
            }
        return entries

    def _write(self, entries: dict[str, dict[str, Any]]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": _STORE_VERSION, "workspaces": entries}
        fd, temporary_name = tempfile.mkstemp(
            dir=self.storage_path.parent,
            prefix=".workspace-contexts.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            for attempt in range(5):
                try:
                    os.replace(temporary_name, self.storage_path)
                    break
                except PermissionError:
                    # Windows denies replace while another handle briefly holds
                    # the target; retry instead of failing the write.
                    if attempt == 4:
                        raise
                    time.sleep(0.02)
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise

    def _quarantine_corrupt_store(self) -> None:
        """Keep the damaged file instead of silently overwriting user contexts."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = self.storage_path.with_name(f"{self.storage_path.name}.corrupt-{timestamp}")
        try:
            os.replace(self.storage_path, backup)
            logger.warning("Quarantined corrupt workspace context store at %s", backup)
        except OSError as exc:
            logger.warning(
                "Could not quarantine corrupt workspace context store at %s: %s",
                self.storage_path,
                exc,
            )

    # -- public API --------------------------------------------------------

    def validate(self, context: dict[str, Any]) -> None:
        validate_context_payload(context)

    def get(self, workspace_id: str) -> dict[str, Any] | None:
        entry = self.get_entry(workspace_id)
        return entry["context"] if entry is not None else None

    def get_entry(self, workspace_id: str) -> dict[str, Any] | None:
        normalized = str(workspace_id or "").strip()
        if not normalized:
            return None
        with self._lock, exclusive_file_lock(self.lock_path):
            if self.storage_path.exists():
                parsed = self._parse(self.storage_path, quarantine=False)
                if parsed is None:
                    raise RuntimeError("workspace_context_store_unreadable")
                self._entries = parsed
            entry = self._entries.get(normalized)
            return deepcopy(entry) if entry is not None else None

    def entries(self) -> dict[str, dict[str, Any]]:
        """Return every stored entry, used by the one-time database migration."""
        with self._lock, exclusive_file_lock(self.lock_path):
            if not self.storage_path.exists():
                return {}
            parsed = self._parse(self.storage_path, quarantine=False)
            if parsed is None:
                raise RuntimeError("workspace_context_store_unreadable")
            self._entries = parsed
            return deepcopy(parsed)

    def put(
        self,
        workspace_id: str,
        context: dict[str, Any],
        *,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        normalized = str(workspace_id or "").strip()
        if not normalized:
            raise ValueError("workspace_id is required")
        self.validate(context)
        return self._mutate(normalized, context, expected_revision=expected_revision)

    def _mutate(
        self,
        workspace_id: str,
        context: dict[str, Any] | None,
        *,
        expected_revision: int | None,
    ) -> dict[str, Any]:
        with self._lock, exclusive_file_lock(self.lock_path):
            # Re-read under the OS lock: another process may have written since
            # this instance loaded the file. A damaged file is quarantined
            # before being replaced, so its content is never silently dropped.
            if self.storage_path.exists():
                parsed = self._parse(self.storage_path, quarantine=True)
                if parsed is None:
                    # Never replace a file we could not read: that would drop
                    # every other workspace entry. The caller surfaces an error.
                    raise RuntimeError("workspace_context_store_unreadable")
                entries = parsed
            else:
                entries = {}
            current = entries.get(workspace_id)
            current_revision = int(current["revision"]) if current else 0
            if expected_revision is not None and expected_revision != current_revision:
                self._entries = entries
                raise WorkspaceContextConflict(workspace_id, expected_revision, current_revision)
            if context is None:
                if current is None:
                    self._entries = entries
                    return {"context": None, "revision": current_revision, "updatedAt": None}
                entries.pop(workspace_id, None)
                self._write(entries)
                self._entries = entries
                return {"context": None, "revision": current_revision + 1, "updatedAt": None}
            next_entry = {
                "context": deepcopy(context),
                "revision": current_revision + 1,
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
            entries[workspace_id] = next_entry
            self._write(entries)
            self._entries = entries
            return deepcopy(next_entry)

    def current_revision(self, workspace_id: str) -> int:
        entry = self.get_entry(workspace_id)
        return int(entry["revision"]) if entry is not None else 0

    def delete(self, workspace_id: str, *, expected_revision: int | None = None) -> dict[str, Any]:
        normalized = str(workspace_id or "").strip()
        if not normalized:
            return {"context": None, "revision": 0, "updatedAt": None}
        return self._mutate(normalized, None, expected_revision=expected_revision)


__all__ = [
    "MAX_CONTEXT_BYTES",
    "WorkspaceContextConflict",
    "WorkspaceContextStore",
    "validate_context_payload",
]
