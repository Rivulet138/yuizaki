from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

from modules.system.relationship_runtime import (
    build_companion_relationship_history_endpoint,
    build_recent_relationship_history_provider,
    build_relationship_history_payload,
    collect_relationship_events,
)


@dataclass
class _Document:
    id: str
    text: str
    metadata: dict[str, Any]


class _MemoryStore:
    def __init__(self, docs: list[_Document]):
        self._docs: list[_Document] = docs

    def list_documents(self) -> list[_Document]:
        return list(self._docs)


class _Repo:
    def __init__(self, companion_id: str | None):
        self._companion_id: str | None = companion_id

    def get_workspace_companion(self, workspace_id: str):
        if self._companion_id is None:
            return None
        return {"id": self._companion_id, "workspace_id": workspace_id}


def test_collect_relationship_events_filters_scope_and_backfills_fields():
    store = _MemoryStore(
        [
            _Document(
                id="old",
                text="旧事件",
                metadata={
                    "event_type": "relationship_state",
                    "companion_id": "comp-1",
                    "scope": "workspace",
                    "timestamp": "2026-04-22T10:00:00Z",
                    "workspace_id": "ws-1",
                    "importance": 0.6,
                    "relationship_event": {"kind": "trust_shift"},
                },
            ),
            _Document(
                id="skip-scope",
                text="会话事件",
                metadata={
                    "event_type": "relationship_state",
                    "companion_id": "comp-1",
                    "scope": "session",
                    "relationship_event": {"kind": "care_signal"},
                },
            ),
            _Document(
                id="new",
                text="最新事件",
                metadata={
                    "event_type": "relationship_state",
                    "companion_id": "comp-1",
                    "scope": "global",
                    "timestamp": "2026-04-23T08:00:00Z",
                    "workspace_id": "ws-1",
                    "importance": 0.9,
                    "relationship_event": {"kind": "support_request"},
                },
            ),
            _Document(
                id="ignored",
                text="已删除事件",
                metadata={
                    "event_type": "profile_update",
                    "companion_id": "comp-1",
                    "scope": "workspace",
                    "relationship_event": {"kind": "ignored_signal"},
                },
            ),
        ]
    )

    events = collect_relationship_events(
        memory_store=store,
        companion_id="comp-1",
        limit=10,
        allowed_scopes={"global", "workspace"},
    )

    assert [item["kind"] for item in events] == ["support_request", "trust_shift"]
    assert events[0]["text"] == "最新事件"
    assert events[1]["timestamp"] == "2026-04-22T10:00:00Z"
    assert events[1]["workspace_id"] == "ws-1"
    assert events[1]["importance"] == 0.6


def test_build_recent_relationship_history_provider_uses_active_workspace_companion():
    store = _MemoryStore(
        [
            _Document(
                id="comp-1-event",
                text="comp-1",
                metadata={
                        "event_type": "relationship_state",
                        "companion_id": "comp-1",
                        "scope": "workspace",
                        "workspace_id": "ws-1",
                        "relationship_event": {"kind": "trust_shift"},
                },
            ),
            _Document(
                id="comp-2-event",
                text="comp-2",
                metadata={
                        "event_type": "relationship_state",
                        "companion_id": "comp-2",
                        "scope": "workspace",
                        "workspace_id": "ws-1",
                        "relationship_event": {"kind": "care_signal"},
                },
            ),
        ]
    )
    provider = build_recent_relationship_history_provider(
        get_active_workspace_id=lambda: "ws-1",
        get_db_repo=lambda: _Repo("comp-1"),
        get_memory_store=lambda: store,
        limit=5,
    )

    events = provider()

    assert len(events) == 1
    assert events[0]["kind"] == "trust_shift"


@pytest.mark.asyncio
async def test_build_companion_relationship_history_endpoint_groups_milestones():
    store = _MemoryStore(
        [
            _Document(
                id="event-1",
                text="谢谢你",
                metadata={
                    "event_type": "relationship_state",
                    "companion_id": "comp-1",
                    "scope": "workspace",
                    "relationship_event": {"kind": "gratitude", "importance": 0.95},
                },
            ),
            _Document(
                id="event-2",
                text="普通交流",
                metadata={
                    "event_type": "relationship_state",
                    "companion_id": "comp-1",
                    "scope": "global",
                    "relationship_event": {"kind": "care_signal", "importance": 0.4},
                },
            ),
        ]
    )

    endpoint: Callable[[str, int], dict[str, Any]] = build_companion_relationship_history_endpoint(
        memory_store_provider=lambda: store,
        summarize_relationship_events=lambda events: {
            "relationship_stage": "stable",
            "event_count": len(events),
        },
        is_relationship_milestone=lambda kind, importance: kind == "gratitude" and float(importance or 0) >= 0.9,
    )

    payload = endpoint("comp-1", 20)

    assert payload["summary"] == {"relationship_stage": "stable", "event_count": 2}
    assert payload["grouped"]["workspace"]["gratitude"][0]["milestone"] is True
    assert payload["grouped"]["global"]["care_signal"][0]["milestone"] is False
    assert len(payload["milestones"]) == 1
    assert payload["milestones"][0]["kind"] == "gratitude"


def test_build_relationship_history_payload_marks_milestones_per_event():
    events = [
        {"kind": "trust_shift", "scope": "workspace", "importance": 0.91},
        {"kind": "care_signal", "scope": "workspace", "importance": 0.3},
    ]

    payload = build_relationship_history_payload(
        companion_id="comp-9",
        events=events,
        summarize_relationship_events=lambda items: {"count": len(items)},
        is_relationship_milestone=lambda kind, importance: kind == "trust_shift" and float(importance or 0) >= 0.9,
    )

    assert payload["summary"] == {"count": 2}
    assert payload["events"][0]["milestone"] is True
    assert payload["events"][1]["milestone"] is False
    assert payload["grouped"]["workspace"]["trust_shift"][0]["importance"] == 0.91
