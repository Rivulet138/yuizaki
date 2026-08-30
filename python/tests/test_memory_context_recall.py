from __future__ import annotations

import asyncio
import time

from modules.agent.context import AgentRequestContext, bind_runtime_bindings
from modules.agent.context_prefetch import ContextPrefetchCoordinator
from modules.agent.context_stage import ContextStage
from modules.memory.pipeline import RetrievalPipeline
from modules.memory.schema import RetrievalRequest
from modules.memory.vector_store import Document


class _Backend:
    def __init__(self, documents: list[Document]) -> None:
        self.documents = documents
        self.revision = 1

    def get_authority_revision(self) -> int:
        return self.revision

    def list_documents(self) -> list[Document]:
        return list(self.documents)

    def search_with_rerank(self, **_: object) -> list[tuple[Document, float]]:
        return [(document, 1.0 - index * 0.1) for index, document in enumerate(self.documents)]


class _MutatingBackend(_Backend):
    def search_with_rerank(self, **_: object) -> list[tuple[Document, float]]:
        results = super().search_with_rerank()
        self.revision += 1
        return results


def _document(doc_id: str, text: str, **metadata: object) -> Document:
    return Document(
        id=doc_id,
        text=text,
        metadata={"layer": "semantic", "scope": "workspace", "workspace_id": "w1", **metadata},
    )


def test_recall_applies_context_budget_and_reports_truncation() -> None:
    backend = _Backend([
        _document("one", "a" * 240),
        _document("two", "b" * 240),
        _document("three", "c" * 240),
    ])
    result = RetrievalPipeline(backend).recall(
        RetrievalRequest(
            query="memory",
            scope="workspace",
            workspace_id="w1",
            top_k=3,
            relation_expansion=False,
            context_budget_tokens=128,
        )
    )

    assert [item["doc"]["id"] for item in result["results"]] == ["one", "two"]
    assert result["trace"]["context_budget_tokens"] == 128
    assert result["trace"]["context_token_estimate"] == 120
    assert result["trace"]["budget_truncated"] is True


def test_recall_trace_reports_anchor_and_relation_evidence_ids() -> None:
    backend = _Backend([
        _document("anchor", "项目 alpha 发布计划", turn_id="turn-alpha", occurred_at="2026-01-01T10:00:00Z"),
        _document("related", "项目 alpha 灰度策略", turn_id="turn-alpha", occurred_at="2026-01-01T10:05:00Z"),
    ])
    result = RetrievalPipeline(backend).recall(
        RetrievalRequest(
            query="发布计划",
            scope="workspace",
            workspace_id="w1",
            top_k=1,
            relation_expansion=True,
            relation_limit=5,
        )
    )

    trace = result["trace"]
    assert trace["anchor_ids"] == ["anchor"]
    assert trace["expanded_ids"] == ["related"]
    assert trace["evidence_ids"] == ["anchor", "related"]


def test_recall_post_filter_normalizes_legacy_scope_ids() -> None:
    backend = _Backend([
        _document(
            "legacy",
            "会话记忆",
            scope="session",
            session_id=" session-1 ",
            workspace_id=" ws-1 ",
        ),
    ])
    result = RetrievalPipeline(backend).recall(
        RetrievalRequest(
            query="会话记忆",
            scope="session",
            session_id="session-1",
            workspace_id="ws-1",
            relation_expansion=False,
        )
    )

    assert [item["doc"]["id"] for item in result["results"]] == ["legacy"]


def test_context_stage_preserves_memory_provenance_in_trace() -> None:
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        workspace_id="w1",
        messages=[{"role": "user", "content": "what do I prefer?"}],
    )
    bind_runtime_bindings(ctx)
    runtime_events: list[dict[str, object]] = []

    def append_runtime_loop(_ctx: AgentRequestContext, **kwargs: object) -> None:
        runtime_events.append(kwargs)

    ContextStage._apply_recall_results(
        ctx,
        [
            {
                "doc": {
                    "id": "m1",
                    "text": "prefers quiet notifications",
                    "metadata": {
                        "layer": "profile",
                        "source_kind": "conversation",
                        "source_id": "msg-1",
                        "turn_id": "turn-1",
                        "evidence": {"ids": ["e-1", "e-2"]},
                    },
                },
                "score": 0.9,
            }
        ],
        "what do I prefer?",
        append_runtime_loop,
        retrieval_trace={"authority_revision": 4, "budget_truncated": False},
    )

    assert ctx.extra["memory_sources"] == [
        {
            "id": "m1",
            "text": "prefers quiet notifications",
            "layer": "profile",
            "source_kind": "conversation",
            "source_id": "msg-1",
            "turn_id": "turn-1",
            "evidence_ids": ["e-1", "e-2"],
            "score": 0.9,
        }
    ]
    assert ctx.extra["memory_retrieval_trace"]["authority_revision"] == 4
    assert runtime_events[-1]["data"]["memory_sources"][0]["source_id"] == "msg-1"


def test_prefetch_rejects_evidence_from_an_older_authority_revision() -> None:
    backend = _Backend([])
    pipeline = RetrievalPipeline(backend)
    coordinator = ContextPrefetchCoordinator(pipeline)
    coordinator.retrieval_prefetch_cache["sid"] = {
        "query": "memory",
        "workspace_id": "w1",
        "recorded_at": time.monotonic(),
        "context_budget_tokens": 1200,
        "data": {"results": [{"doc": {"id": "old"}}], "trace": {"authority_revision": 1}},
    }

    async def run() -> dict[str, object] | None:
        backend.revision = 2
        return await coordinator.take_retrieval_prefetch(
            cache_key="sid",
            final_query="memory",
            workspace_id="w1",
        )

    assert asyncio.run(run()) is None


def test_context_stage_skips_recall_when_authority_changes_mid_turn() -> None:
    backend = _MutatingBackend([_document("m1", "old evidence")])
    pipeline = RetrievalPipeline(backend)
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        workspace_id="w1",
        messages=[{"role": "user", "content": "recall this"}],
    )
    events: list[dict[str, object]] = []

    async def no_prefetch(**_: object) -> dict[str, object] | None:
        return None

    def append_runtime_loop(_ctx: AgentRequestContext, **kwargs: object) -> None:
        events.append(kwargs)

    async def run() -> None:
        await ContextStage()._recall(
            ctx,
            user_text="recall this",
            retrieval_pipeline=pipeline,
            take_retrieval_prefetch=no_prefetch,
            append_runtime_loop=append_runtime_loop,
        )

    asyncio.run(run())
    assert ctx.extra["rag_error"] == "memory_revision_changed_during_recall"
    assert "retrieved_chunks" not in ctx.extra
    assert events[-1]["status"] == "stale"
