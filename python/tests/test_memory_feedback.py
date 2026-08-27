from __future__ import annotations

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from modules.memory.pipeline import RetrievalPipeline
from modules.memory.routes import MemoryState, create_memory_router
from modules.memory.schema import RetrievalRequest
from modules.memory.vector_store import (
    Document,
    VectorStore,
    memory_feedback_quality_score,
)


class _Embedding:
    dimension = 2

    def embed(self, _text: str) -> np.ndarray:
        return np.array([1.0, 0.0], dtype=np.float32)


def _client() -> tuple[TestClient, VectorStore]:
    store = VectorStore(embedding_service=_Embedding())
    app = FastAPI()
    app.include_router(create_memory_router(MemoryState(store=store)))
    return TestClient(app), store


def test_feedback_preserves_text_and_revision_and_returns_counts() -> None:
    client, store = _client()
    created = client.post('/memory/docs', json={'id': 'doc-1', 'text': 'user likes tea'})
    assert created.status_code == 200
    before = store.list_documents()[0]
    revision = before.metadata.get('revision')

    for value in ('helpful', 'helpful', 'incorrect'):
        response = client.post('/memory/docs/doc-1/feedback', json={'feedback': value})
        assert response.status_code == 200
    after = store.list_documents()[0]
    assert after.text == before.text
    assert after.metadata.get('revision') == revision
    assert after.metadata['recall_feedback']['summary'] == {'helpful': 2, 'incorrect': 1}
    assert len(after.metadata['recall_feedback']['events']) == 3


def test_feedback_rejects_invalid_and_missing_documents() -> None:
    client, _store = _client()
    assert client.post('/memory/docs/missing/feedback', json={'feedback': 'helpful'}).status_code == 404
    assert client.post('/memory/docs/missing/feedback', json={'feedback': 'spam'}).status_code == 422


def test_recall_results_explain_anchor_and_evidence_type() -> None:
    store = VectorStore(embedding_service=_Embedding())
    store.add_document(Document(id='doc-1', text='tea preference', metadata={'scope': 'workspace', 'layer': 'semantic'}))
    result = RetrievalPipeline(store).recall(RetrievalRequest(query='tea', top_k=1, relation_expansion=False))
    item = result['results'][0]
    assert item['evidence_type'] == 'anchor'
    assert item['why_recalled'] == '与当前请求直接匹配'
    assert item['association'] is None


def test_feedback_quality_requires_enough_samples_and_is_bounded() -> None:
    assert memory_feedback_quality_score(
        {'recall_feedback': {'summary': {'helpful': 2}}}, 0.6,
    ) == 0.6
    assert memory_feedback_quality_score(
        {'recall_feedback': {'summary': {'helpful': 100}}}, 0.6,
    ) == 0.8
    assert memory_feedback_quality_score(
        {'recall_feedback': {'summary': {'incorrect': 100}}}, 0.6,
    ) == pytest.approx(0.4)


def test_feedback_quality_changes_recall_order_after_sufficient_feedback() -> None:
    class _DistinctEmbedding:
        dimension = 2

        def embed(self, text: str) -> np.ndarray:
            return np.array([1.0, 0.0] if 'tea' in text else [0.98, 0.2], dtype=np.float32)

    store = VectorStore(embedding_service=_DistinctEmbedding())
    store.add_document(Document(
        id='feedback-favored', text='tea preference',
        metadata={'quality_score': 0.6, 'recall_feedback': {'summary': {'helpful': 8}}},
    ))
    store.add_document(Document(
        id='baseline', text='tea preference', metadata={'quality_score': 0.6},
    ))
    results = store.search_with_rerank('tea', top_k=2, recency_weight=0.0, quality_weight=0.5)
    assert results[0][0].id == 'feedback-favored'
    components = store.get_score_components('tea', 'feedback-favored', 0.0, 0.5)
    assert components is not None
    assert components['quality'] == 0.8

    before = store.list_documents()[0]
    assert before.text == 'tea preference'
    assert before.metadata['recall_feedback']['summary'] == {'helpful': 8}
