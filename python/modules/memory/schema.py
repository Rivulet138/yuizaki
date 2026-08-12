from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


MemoryLayer = str  # profile | working | episodic | relationship | reflective | semantic | session(legacy)
MemoryScope = str  # global | workspace | session


@dataclass
class MemoryRecord:
    id: str
    layer: MemoryLayer
    text: str
    scope: MemoryScope = 'workspace'
    session_id: str | None = None
    workspace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    # Provenance is immutable origin context. Legacy records may leave these unset.
    source_kind: str | None = None
    source_id: str | None = None
    turn_id: str | None = None
    evidence: Any = None
    confidence_history: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RetrievalRequest:
    query: str
    scope: MemoryScope | None = None
    session_id: str | None = None
    workspace_id: str | None = None
    top_k: int = 5
    layers: list[MemoryLayer] = field(default_factory=lambda: ['profile', 'working', 'episodic', 'relationship', 'reflective', 'semantic'])
    memory_types: list[str] | None = None
    recency_weight: float = 0.2
    quality_weight: float = 0.15


@dataclass
class MemorySearchFilters:
    scope: MemoryScope | None = None
    session_id: str | None = None
    workspace_id: str | None = None
    layers: list[MemoryLayer] | None = None


@dataclass
class RetrievalTrace:
    query: str
    scope: MemoryScope | None
    session_id: str | None
    workspace_id: str | None
    layers: list[MemoryLayer]
    recall_count: int
    selected_ids: list[str]
    candidate_limit: int = 0
    candidate_count: int = 0
    filtered_count: int = 0
    filtered_out_count: int = 0
    filter_reasons: dict[str, int] = field(default_factory=dict)
    top_score: float | None = None
    average_score: float | None = None
    latency_ms: float = 0.0
    backend_filter_downpushed: bool = False
    complete: bool = True
    error_code: str | None = None
    scan_limit_reached: bool = False
