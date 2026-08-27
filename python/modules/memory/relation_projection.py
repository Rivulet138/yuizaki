from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import pairwise
from typing import Any

from .vector_store import Document


@dataclass(frozen=True)
class RelationEdge:
    target_id: str
    relation: str
    evidence_type: str


class MemoryRelationProjection:
    """Rebuildable relation view derived only from authoritative documents."""

    def __init__(self, edges: dict[str, list[RelationEdge]]):
        self._edges = edges

    def neighbors(self, document_id: str) -> list[RelationEdge]:
        return list(self._edges.get(document_id, ()))


def _as_ids(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _timestamp(metadata: dict[str, Any]) -> float | None:
    for key in ('occurred_at', 'ingested_at', 'updated_at', 'created_at', 'timestamp'):
        raw = metadata.get(key)
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            continue
    return None


def build_relation_projection(
    documents: Iterable[Document],
    *,
    event_window_seconds: int = 24 * 60 * 60,
) -> MemoryRelationProjection:
    docs = list(documents)
    edges: dict[str, list[RelationEdge]] = {}
    seen: set[tuple[str, str, str, str]] = set()

    def add(source_id: str, target_id: str, relation: str, evidence_type: str) -> None:
        if not source_id or not target_id or source_id == target_id:
            return
        key = (source_id, target_id, relation, evidence_type)
        if key in seen:
            return
        seen.add(key)
        edges.setdefault(source_id, []).append(RelationEdge(target_id, relation, evidence_type))

    event_groups: dict[tuple[str, str], list[tuple[float, Document]]] = {}
    for doc in docs:
        metadata = dict(doc.metadata or {})
        for target_id in _as_ids(metadata.get('source_ids')):
            add(doc.id, target_id, 'source', 'source')
        for target_id in _as_ids(metadata.get('supersedes')):
            add(doc.id, target_id, 'supersedes', 'supersedes')
        for target_id in _as_ids(metadata.get('superseded_by')):
            add(doc.id, target_id, 'superseded_by', 'superseded_by')

        timestamp = _timestamp(metadata)
        if timestamp is None:
            continue
        for evidence_type in ('turn_id', 'source_id'):
            group_id = metadata.get(evidence_type)
            if isinstance(group_id, str) and group_id.strip():
                event_groups.setdefault((evidence_type, group_id.strip()), []).append((timestamp, doc))

    for (evidence_type, _group_id), entries in event_groups.items():
        ordered = sorted(entries, key=lambda item: (item[0], item[1].id))
        for (left_time, left), (right_time, right) in pairwise(ordered):
            if right_time - left_time > max(0, event_window_seconds):
                continue
            add(left.id, right.id, 'event_adjacent', evidence_type)
            add(right.id, left.id, 'event_adjacent', evidence_type)

    return MemoryRelationProjection(edges)
