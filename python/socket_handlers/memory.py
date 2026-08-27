"""Socket.IO memory retrieval handler with explicit workspace scoping."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from modules.memory.routes import MemoryRagQueryPayload
from modules.memory.schema import RetrievalRequest
from pydantic import ValidationError
from socket_events import MemoryEvents
from starlette.concurrency import run_in_threadpool

JsonDict = dict[str, object]


class RetrievalPipelineProtocol(Protocol):
    def recall(self, request: RetrievalRequest) -> JsonDict: ...


def _as_text(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _as_int(value: object, default: int = 0) -> int:
    if not isinstance(value, (int, float, str)):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def build_memory_query_handler(
    *,
    sio: Any,
    retrieval_pipeline_provider: Callable[[], RetrievalPipelineProtocol | None],
    workspace_resolver: Callable[[str | None], tuple[str | None, bool]],
    default_layers: list[str],
    logger: logging.Logger | None = None,
) -> Callable[[str, JsonDict], Awaitable[None]]:
    log = logger or logging.getLogger("socket-server.memory")

    async def on_rag_query(sid: str, data: JsonDict) -> None:
        log.info("[SIO] rag:query from %s", sid)
        memory_pipeline = retrieval_pipeline_provider()
        if memory_pipeline is None:
            await sio.emit(MemoryEvents.RESULT, {
                "docs": [],
                "message": "retrieval pipeline not initialized",
            }, to=sid)
            return

        raw_layers = data.get("layers")
        raw_memory_types = data.get("memory_types")
        raw_recency_weight = data.get("recency_weight")
        requested_workspace_id = (
            _as_text(data.get("workspace_id"))
            if data.get("workspace_id") is not None
            else None
        )
        workspace_id, workspace_allowed = workspace_resolver(requested_workspace_id)
        if not workspace_allowed:
            await sio.emit(MemoryEvents.RESULT, {
                "docs": [],
                "error": "WORKSPACE_MISMATCH",
                "message": "Socket RAG workspace does not match the active workspace",
            }, to=sid)
            return

        try:
            payload = MemoryRagQueryPayload(
                query=_as_text(data.get("query")),
                top_k=_as_int(data.get("top_k"), 5),
                memory_types=[str(item) for item in raw_memory_types] if isinstance(raw_memory_types, list) else None,
                recency_weight=(
                    float(raw_recency_weight)
                    if isinstance(raw_recency_weight, (int, float, str))
                    else 0.2
                ),
                scope=_as_text(data.get("scope")) if data.get("scope") is not None else None,
                session_id=_as_text(data.get("session_id")) if data.get("session_id") is not None else None,
                workspace_id=workspace_id,
                layers=[str(item) for item in raw_layers] if isinstance(raw_layers, list) else None,
                expand_relations=bool(data.get("expand_relations", True)),
                relation_limit=_as_int(data.get("relation_limit"), 20),
                relation_depth=_as_int(data.get("relation_depth"), 1),
            )
        except (ValidationError, TypeError, ValueError) as exc:
            await sio.emit(MemoryEvents.RESULT, {
                "docs": [],
                "error": "INVALID_MEMORY_QUERY",
                "message": str(exc),
            }, to=sid)
            return

        request = RetrievalRequest(
            query=payload.query,
            scope=payload.scope,
            session_id=payload.session_id,
            workspace_id=payload.workspace_id,
            top_k=payload.top_k,
            layers=payload.layers or default_layers,
            memory_types=payload.memory_types,
            recency_weight=payload.recency_weight,
            relation_expansion=payload.expand_relations,
            relation_limit=payload.relation_limit,
            relation_depth=payload.relation_depth,
        )
        result = await run_in_threadpool(memory_pipeline.recall, request)
        await sio.emit(MemoryEvents.RESULT, result, to=sid)

    return on_rag_query


__all__ = ["RetrievalPipelineProtocol", "build_memory_query_handler"]
