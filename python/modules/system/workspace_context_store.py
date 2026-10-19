"""Durable workspace prompt/context storage.

Workspace records live in SQLite, but the renderer-owned prompt context
(role card, world book, prompt engineering, vision and memory policy) is a
nested JSON document. Keeping it in a small sidecar file avoids a schema
migration while still making it survive browser storage resets and workspace
switches.
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

logger = logging.getLogger(__name__)

MAX_CONTEXT_BYTES = 2 * 1024 * 1024
_STORE_VERSION = 1


class WorkspaceContextStore:
    def __init__(self, storage_path: str | Path | None = None) -> None:
        self.storage_path = (
            Path(storage_path)
            if storage_path is not None
            else data_dir_from_env() / "workspace_contexts.json"
        )
        self._lock = threading.RLock()
        self._contexts: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.storage_path.exists():
            return {}
        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "Workspace context store unreadable at %s: %s",
                self.storage_path,
                exc,
            )
            self._quarantine_corrupt_store()
            return {}
        if not isinstance(payload, dict):
            logger.warning("Workspace context store at %s is not a JSON object", self.storage_path)
            self._quarantine_corrupt_store()
            return {}
        raw_contexts = payload.get("workspaces")
        if not isinstance(raw_contexts, dict):
            self._quarantine_corrupt_store()
            return {}
        contexts: dict[str, dict[str, Any]] = {}
        for workspace_id, context in raw_contexts.items():
            if not isinstance(workspace_id, str) or not workspace_id.strip():
                continue
            if not isinstance(context, dict):
                continue
            contexts[workspace_id] = deepcopy(context)
        return contexts

    def get(self, workspace_id: str) -> dict[str, Any] | None:
        normalized = str(workspace_id or "").strip()
        if not normalized:
            return None
        with self._lock:
            context = self._contexts.get(normalized)
            return deepcopy(context) if context is not None else None

    def validate(self, context: dict[str, Any]) -> None:
        if not isinstance(context, dict):
            raise ValueError("workspace context must be a JSON object")
        serialized = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
        if len(serialized.encode("utf-8")) > MAX_CONTEXT_BYTES:
            raise ValueError("workspace context is too large")

    def put(self, workspace_id: str, context: dict[str, Any]) -> dict[str, Any]:
        normalized = str(workspace_id or "").strip()
        if not normalized:
            raise ValueError("workspace_id is required")
        self.validate(context)
        with self._lock:
            next_contexts = dict(self._contexts)
            next_contexts[normalized] = deepcopy(context)
            self._write(next_contexts)
            self._contexts = next_contexts
        return deepcopy(context)

    def delete(self, workspace_id: str) -> None:
        normalized = str(workspace_id or "").strip()
        if not normalized:
            return
        with self._lock:
            if normalized not in self._contexts:
                return
            next_contexts = dict(self._contexts)
            next_contexts.pop(normalized, None)
            self._write(next_contexts)
            self._contexts = next_contexts

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

    def _write(self, contexts: dict[str, dict[str, Any]]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": _STORE_VERSION, "workspaces": contexts}
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
            os.replace(temporary_name, self.storage_path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise


__all__ = ["MAX_CONTEXT_BYTES", "WorkspaceContextStore"]
