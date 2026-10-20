"""One-time import of the legacy workspace context sidecar into SQLite.

Workspace context used to live in ``workspace_contexts.json`` beside the
database while the workspace row itself lived in SQLite, so every change was
two independent writes. Context is now a column on the workspace row; this
module copies existing payloads across exactly once, keeps an archived copy of
the sidecar, and never discards entries it cannot import.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _archive_path(storage_path: Path, marker: str, stamp: str) -> Path:
    return storage_path.with_name(f"{storage_path.name}.{marker}-{stamp}")


def _move_aside(storage_path: Path, marker: str, stamp: str) -> str | None:
    target = _archive_path(storage_path, marker, stamp)
    try:
        os.replace(storage_path, target)
    except OSError as exc:
        logger.warning("Could not archive workspace context sidecar at %s: %s", storage_path, exc)
        return None
    logger.info("Archived legacy workspace context sidecar at %s", target)
    return str(target)


def _write_json(path: Path, payload: dict[str, Any]) -> str | None:
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write %s: %s", path, exc)
        return None
    return str(path)


def _existing_workspace_ids(repo: Any) -> set[str] | None:
    try:
        workspaces = repo.list_workspaces()
    except Exception as exc:  # noqa: BLE001 - caller degrades to no-op
        logger.warning("Could not list workspaces for legacy context import: %s", exc)
        return None
    return {
        str(workspace.get("id") or "").strip()
        for workspace in workspaces
        if isinstance(workspace, dict)
    }


def import_legacy_workspace_contexts(repo: Any, store: Any) -> dict[str, int]:
    """Copy sidecar contexts into the workspace rows once, then archive it.

    Returns counters for imported / existing / orphaned / failed entries. The
    active sidecar is only archived when nothing failed, so a transient
    database error leaves the data available for the next start.
    """
    summary = {"imported": 0, "existing": 0, "orphaned": 0, "failed": 0}
    if repo is None or store is None:
        return summary
    storage_path = Path(getattr(store, "storage_path", "") or "")
    if not str(storage_path) or not storage_path.exists():
        return summary
    try:
        entries = store.entries()
    except RuntimeError as exc:
        logger.warning("Skipping legacy workspace context import: %s", exc)
        summary["failed"] = 1
        return summary

    workspace_ids = _existing_workspace_ids(repo)
    if workspace_ids is None:
        summary["failed"] = 1
        return summary

    orphans: dict[str, Any] = {}
    for workspace_id, entry in entries.items():
        context = entry.get("context") if isinstance(entry, dict) else None
        if not isinstance(context, dict):
            continue
        if workspace_id not in workspace_ids:
            orphans[workspace_id] = entry
            continue
        try:
            imported = repo.import_workspace_context(
                workspace_id,
                context,
                int(entry.get("revision") or 0),
            )
        except Exception as exc:  # noqa: BLE001 - reported, retried next start
            summary["failed"] += 1
            logger.warning("Failed to import context for workspace %s: %s", workspace_id, exc)
            continue
        if imported:
            summary["imported"] += 1
        else:
            summary["existing"] += 1

    stamp = _timestamp()
    if orphans:
        # The workspace row is gone, so the payload has no home in the database.
        # Keep it in a dedicated file rather than dropping it silently.
        summary["orphaned"] = len(orphans)
        _write_json(
            _archive_path(storage_path, "orphaned", stamp),
            {
                "version": 1,
                "archivedAt": datetime.now(timezone.utc).isoformat(),
                "workspaces": orphans,
            },
        )
    if summary["failed"]:
        return summary
    _move_aside(storage_path, "migrated", stamp)
    return summary


__all__ = ["import_legacy_workspace_contexts"]
