from __future__ import annotations

import asyncio
from typing import Any

from socket_events import MemoryEvents
from socket_handlers.memory import build_memory_query_handler


class _Sio:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object], str]] = []

    async def emit(self, event: str, payload: dict[str, object], *, to: str) -> None:
        self.events.append((event, payload, to))


class _Pipeline:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def recall(self, request: Any) -> dict[str, object]:
        self.requests.append(request)
        return {"docs": [{"id": "memory-1"}], "trace": {"relation_depth": request.relation_depth}}


def _handler(sio: _Sio, pipeline: _Pipeline | None, allowed: bool = True):
    return build_memory_query_handler(
        sio=sio,
        retrieval_pipeline_provider=lambda: pipeline,
        workspace_resolver=lambda requested: (requested or "workspace-1", allowed),
        default_layers=["profile", "semantic"],
    )


def test_memory_handler_forwards_relation_and_ranking_options() -> None:
    sio = _Sio()
    pipeline = _Pipeline()
    handler = _handler(sio, pipeline)

    asyncio.run(handler("sid", {
        "query": "what changed",
        "top_k": 7,
        "memory_types": ["fact"],
        "recency_weight": 0.4,
        "scope": "workspace",
        "session_id": "session-1",
        "workspace_id": "workspace-1",
        "layers": ["semantic"],
        "expand_relations": True,
        "relation_limit": 12,
        "relation_depth": 2,
    }))

    request = pipeline.requests[0]
    assert request.query == "what changed"
    assert request.top_k == 7
    assert request.memory_types == ["fact"]
    assert request.recency_weight == 0.4
    assert request.relation_expansion is True
    assert request.relation_limit == 12
    assert request.relation_depth == 2
    assert sio.events == [(MemoryEvents.RESULT, {"docs": [{"id": "memory-1"}], "trace": {"relation_depth": 2}}, "sid")]


def test_memory_handler_keeps_workspace_mismatch_and_invalid_query_errors() -> None:
    sio = _Sio()
    pipeline = _Pipeline()
    asyncio.run(_handler(sio, pipeline, allowed=False)("sid", {"query": "x"}))
    assert sio.events[-1][1]["error"] == "WORKSPACE_MISMATCH"

    asyncio.run(_handler(sio, pipeline)("sid", {"query": "x", "top_k": 0}))
    assert sio.events[-1][1]["error"] == "INVALID_MEMORY_QUERY"


def test_memory_handler_reports_missing_pipeline() -> None:
    sio = _Sio()
    asyncio.run(_handler(sio, None)("sid", {"query": "x"}))
    assert sio.events == [(MemoryEvents.RESULT, {
        "docs": [],
        "message": "retrieval pipeline not initialized",
    }, "sid")]
