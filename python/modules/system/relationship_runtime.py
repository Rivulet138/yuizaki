from __future__ import annotations

from collections.abc import Callable
from typing import Any, Dict

from .memory_write_pipeline import normalize_relationship_memory_payload, persist_relationship_memory
from ..memory.metadata import is_metadata_recallable

__all__ = [
    "collect_relationship_events",
    "write_relationship_memory",
    "recent_relationship_history",
    "relationship_evolution_summary",
    "build_relationship_history_payload",
    "build_companion_relationship_history_endpoint",
    "build_relationship_memory_writer",
    "build_recent_relationship_history_provider",
    "build_relationship_summary_provider",
]


def collect_relationship_events(
    *,
    memory_store: Any,
    companion_id: str | None,
    limit: int,
    allowed_scopes: set[str] | None = None,
    workspace_id: str | None = None,
    ) -> list[Dict[str, Any]]:
    docs = memory_store.list_documents()
    events: list[Dict[str, Any]] = []
    for doc in reversed(docs):
        meta = doc.metadata or {}
        if not is_metadata_recallable(meta):
            continue
        if meta.get("event_type") != "relationship_state":
            continue
        if companion_id and meta.get("companion_id") != companion_id:
            continue
        if allowed_scopes is not None and meta.get("scope") not in allowed_scopes:
            continue
        if workspace_id and meta.get("scope") != "global" and meta.get("workspace_id") != workspace_id:
            continue
        rel = meta.get("relationship_event")
        if isinstance(rel, dict):
            payload: Dict[str, Any] = {**rel}
            if "text" not in payload:
                payload["text"] = doc.text
            if "timestamp" not in payload:
                payload["timestamp"] = meta.get("timestamp")
            if "workspace_id" not in payload:
                payload["workspace_id"] = meta.get("workspace_id")
            if "scope" not in payload:
                payload["scope"] = meta.get("scope")
            if "importance" not in payload:
                payload["importance"] = meta.get("importance")
            events.append(payload)
        if len(events) >= max(1, min(limit, 100)):
            break
    return events


def write_relationship_memory(
    payload: dict[str, Any],
    *,
    get_active_workspace_id: Callable[[], str],
    get_db_repo: Callable[[], Any],
    get_memory_store: Callable[[], Any],
    resolve_relationship_scope: Callable[[str, str | None], str],
    normalize_relationship_importance: Callable[[str, float | int | None], float],
) -> None:
    db_repo = get_db_repo()
    companion = db_repo.get_workspace_companion(get_active_workspace_id()) if db_repo else None
    normalized = normalize_relationship_memory_payload(
        payload,
        active_workspace_id=get_active_workspace_id(),
        companion_id=companion.get("id") if isinstance(companion, dict) else None,
        resolve_relationship_scope=resolve_relationship_scope,
        normalize_relationship_importance=normalize_relationship_importance,
    )
    persist_relationship_memory(normalized, memory_store=get_memory_store())


def recent_relationship_history(
    *,
    get_active_workspace_id: Callable[[], str],
    get_db_repo: Callable[[], Any],
    get_memory_store: Callable[[], Any],
    limit: int = 5,
) -> list[Dict[str, Any]]:
    db_repo = get_db_repo()
    active_workspace_id = get_active_workspace_id()
    companion = db_repo.get_workspace_companion(active_workspace_id) if db_repo else None
    companion_id = companion.get("id") if isinstance(companion, dict) else None
    return collect_relationship_events(
        memory_store=get_memory_store(),
        companion_id=companion_id,
        limit=limit,
        allowed_scopes={"global", "workspace"},
        workspace_id=active_workspace_id,
    )


def relationship_evolution_summary(
    *,
    get_recent_relationship_history: Callable[[], list[Dict[str, Any]]],
    summarize_relationship_events: Callable[[list[Dict[str, Any]]], Dict[str, Any]],
) -> Dict[str, Any]:
    return summarize_relationship_events(get_recent_relationship_history())


def build_relationship_memory_writer(
    *,
    get_active_workspace_id: Callable[[], str],
    get_db_repo: Callable[[], Any],
    get_memory_store: Callable[[], Any],
    resolve_relationship_scope: Callable[[str, str | None], str],
    normalize_relationship_importance: Callable[[str, float | int | None], float],
) -> Callable[[dict[str, Any]], None]:
    class _WorkspaceAwareWriter:
        def _write(self, payload: dict[str, Any], workspace_id: str) -> None:
            write_relationship_memory(
                payload,
                get_active_workspace_id=lambda: workspace_id,
                get_db_repo=get_db_repo,
                get_memory_store=get_memory_store,
                resolve_relationship_scope=resolve_relationship_scope,
                normalize_relationship_importance=normalize_relationship_importance,
            )

        def __call__(self, payload: dict[str, Any]) -> None:
            self._write(payload, get_active_workspace_id())

        def for_workspace(self, workspace_id: str) -> Callable[[dict[str, Any]], None]:
            bound_workspace_id = str(workspace_id or "").strip()
            if not bound_workspace_id:
                raise ValueError("workspace_id is required")
            return lambda payload: self._write(payload, bound_workspace_id)

    return _WorkspaceAwareWriter()


def build_recent_relationship_history_provider(
    *,
    get_active_workspace_id: Callable[[], str],
    get_db_repo: Callable[[], Any],
    get_memory_store: Callable[[], Any],
    limit: int = 5,
) -> Callable[[], list[Dict[str, Any]]]:
    def _provider() -> list[Dict[str, Any]]:
        return recent_relationship_history(
            get_active_workspace_id=get_active_workspace_id,
            get_db_repo=get_db_repo,
            get_memory_store=get_memory_store,
            limit=limit,
        )

    return _provider


def build_relationship_summary_provider(
    *,
    get_recent_relationship_history: Callable[[], list[Dict[str, Any]]],
    summarize_relationship_events: Callable[[list[Dict[str, Any]]], Dict[str, Any]],
) -> Callable[[], Dict[str, Any]]:
    def _provider() -> Dict[str, Any]:
        return relationship_evolution_summary(
            get_recent_relationship_history=get_recent_relationship_history,
            summarize_relationship_events=summarize_relationship_events,
        )

    return _provider


def build_relationship_history_payload(
    *,
    companion_id: str,
    events: list[Dict[str, Any]],
    summarize_relationship_events,
    is_relationship_milestone,
) -> Dict[str, Any]:
    grouped: Dict[str, Dict[str, list[Dict[str, Any]]]] = {}
    milestones: list[Dict[str, Any]] = []
    summary = summarize_relationship_events(events)
    for item in events:
        scope = str(item.get("scope") or "workspace")
        kind = str(item.get("kind") or "event")
        is_milestone = is_relationship_milestone(kind, item.get("importance"))
        item["milestone"] = is_milestone
        grouped.setdefault(scope, {}).setdefault(kind, []).append(item)
        if is_milestone:
            milestones.append(item)
    return {
        "companion_id": companion_id,
        "events": events,
        "grouped": grouped,
        "milestones": milestones,
        "summary": summary,
    }


def build_companion_relationship_history_endpoint(
    *,
    memory_store_provider: Callable[[], Any],
    summarize_relationship_events,
    is_relationship_milestone,
) -> Callable[[str, int], Dict[str, Any]]:
    def _endpoint(companion_id: str, limit: int = 20) -> Dict[str, Any]:
        events = collect_relationship_events(
            memory_store=memory_store_provider(),
            companion_id=companion_id,
            limit=limit,
        )
        return build_relationship_history_payload(
            companion_id=companion_id,
            events=events,
            summarize_relationship_events=summarize_relationship_events,
            is_relationship_milestone=is_relationship_milestone,
        )

    return _endpoint
