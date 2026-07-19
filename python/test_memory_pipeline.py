from __future__ import annotations

import numpy as np
from typing import Any

from modules.memory.pipeline import RetrievalPipeline
from modules.memory.schema import RetrievalRequest
from modules.memory.vector_store import Document, VectorStore
from modules.memory.routes import MemoryState
from modules.system.memory_query import build_style_aware_retrieval_strategy
from modules.system.memory_write_pipeline import build_task_completed_event, build_tool_success_event, build_user_signal_event


class FakeEmbeddingService:
    def __init__(self):
        self.dimension: int = 4

    def embed(self, text: str) -> np.ndarray:
        base = float(len(text))
        return np.array([base, 1.0, 0.5, 0.25], dtype='float32')


class RankedStore:
    backend_name = 'ranked-test'

    def __init__(self, results: list[tuple[Document, float]]):
        self.results = results
        self.last_top_k: int | None = None

    def search_with_rerank(
        self,
        query: str,
        top_k: int = 5,
        memory_types=None,
        recency_weight: float = 0.2,
        quality_weight: float = 0.15,
        filters=None,
    ):
        self.last_top_k = top_k
        return self.results[:top_k]


def test_retrieval_pipeline_returns_trace_and_results():
    embedding_service: Any = FakeEmbeddingService()
    store = VectorStore(embedding_service=embedding_service)
    store.add_document(Document(id='profile-1', text='用户喜欢猫', metadata={'layer': 'profile'}))
    store.add_document(Document(id='session-1', text='当前正在部署项目', metadata={'layer': 'session', 'session_id': 's1'}))

    pipeline = RetrievalPipeline(store)
    result = pipeline.recall(RetrievalRequest(query='猫', session_id='s1', top_k=5))

    assert 'results' in result
    assert 'trace' in result
    assert result['trace']['query'] == '猫'
    assert result['trace']['recall_count'] >= 1


def test_retrieval_pipeline_oversamples_before_scope_filtering():
    wrong_scope = Document(id='wrong-scope', text='高相关但别的工作区', metadata={'layer': 'semantic', 'scope': 'workspace', 'workspace_id': 'ws-b'})
    matching_scope = Document(id='matching-scope', text='当前工作区记忆', metadata={'layer': 'semantic', 'scope': 'workspace', 'workspace_id': 'ws-a'})
    store = RankedStore([(wrong_scope, 0.99), (matching_scope, 0.8)])

    pipeline = RetrievalPipeline(store)  # type: ignore[arg-type]
    result = pipeline.recall(RetrievalRequest(query='记忆', scope='workspace', workspace_id='ws-a', top_k=1))

    selected_ids = [item['doc']['id'] for item in result['results']]
    assert selected_ids == ['matching-scope']
    assert store.last_top_k and store.last_top_k > 1
    trace = result['trace']
    assert trace['candidate_count'] == 2
    assert trace['filtered_out_count'] == 1
    assert trace['filter_reasons']['workspace'] == 1
    assert trace['latency_ms'] >= 0


def test_memory_state_can_hold_pipeline():
    embedding_service: Any = FakeEmbeddingService()
    store = VectorStore(embedding_service=embedding_service)
    pipeline = RetrievalPipeline(store)
    state = MemoryState(store=store, pipeline=pipeline)
    assert state.pipeline is pipeline


def test_retrieval_pipeline_global_scope_ignores_workspace_boundary():
    embedding_service: Any = FakeEmbeddingService()
    store = VectorStore(embedding_service=embedding_service)
    store.add_document(Document(id='global-1', text='全局记忆 A', metadata={'layer': 'semantic', 'scope': 'global', 'workspace_id': 'ws-a'}))
    store.add_document(Document(id='workspace-1', text='工作区记忆 B', metadata={'layer': 'semantic', 'scope': 'workspace', 'workspace_id': 'ws-b'}))

    pipeline = RetrievalPipeline(store)
    result = pipeline.recall(RetrievalRequest(query='记忆', scope='global', workspace_id='ws-b', top_k=5))

    selected_ids = [item['doc']['id'] for item in result['results']]
    assert 'global-1' in selected_ids
    assert 'workspace-1' not in selected_ids


def test_retrieval_pipeline_workspace_scope_filters_to_matching_workspace():
    embedding_service: Any = FakeEmbeddingService()
    store = VectorStore(embedding_service=embedding_service)
    store.add_document(Document(id='workspace-a', text='工作区 A 记忆', metadata={'layer': 'semantic', 'scope': 'workspace', 'workspace_id': 'ws-a'}))
    store.add_document(Document(id='workspace-b', text='工作区 B 记忆', metadata={'layer': 'semantic', 'scope': 'workspace', 'workspace_id': 'ws-b'}))

    pipeline = RetrievalPipeline(store)
    result = pipeline.recall(RetrievalRequest(query='工作区', scope='workspace', workspace_id='ws-a', top_k=5))

    selected_ids = [item['doc']['id'] for item in result['results']]
    assert selected_ids == ['workspace-a']


def test_retrieval_pipeline_session_scope_filters_to_matching_session():
    embedding_service: Any = FakeEmbeddingService()
    store = VectorStore(embedding_service=embedding_service)
    store.add_document(Document(id='session-a', text='会话 A 记忆', metadata={'layer': 'session', 'scope': 'session', 'session_id': 's-a'}))
    store.add_document(Document(id='session-b', text='会话 B 记忆', metadata={'layer': 'session', 'scope': 'session', 'session_id': 's-b'}))

    pipeline = RetrievalPipeline(store)
    result = pipeline.recall(RetrievalRequest(query='会话', scope='session', session_id='s-a', top_k=5, layers=['session']))

    selected_ids = [item['doc']['id'] for item in result['results']]
    assert selected_ids == ['session-a']


def test_build_user_signal_event_classifies_preference_to_profile_source():
    event = build_user_signal_event('我更喜欢你下次直接先总结重点')
    assert event is not None
    assert event['kind'] == 'preference_confirmed'
    assert event['metadata']['source'] == 'profile'


def test_build_task_completed_event_sets_reflective_source_metadata():
    event = build_task_completed_event(
        task_name='晚间复盘',
        task_id='sched_1',
        task_mode='once',
        owner_agent_id='yuizaki.task-router',
        owner_agent_role='router',
        session_id='s-1',
    )
    assert event['kind'] == 'task_completed'
    assert event['metadata']['source'] == 'reflection'
    assert event['metadata']['task_id'] == 'sched_1'


def test_build_tool_success_event_sets_reflective_source_metadata():
    event = build_tool_success_event(
        tool_name='read_file',
        args={'path': 'notes.txt'},
        text='結崎通过工具 read_file 成功完成了一次帮助。',
        importance=0.88,
        owner_agent_id='yuizaki.memory-reflector',
        owner_agent_role='reflector',
    )
    assert event['kind'] == 'tool_success'
    assert event['metadata']['source'] == 'reflection'
    assert event['tool_name'] == 'read_file'


def test_build_style_aware_retrieval_strategy_boosts_relationship_for_support_signals():
    strategy = build_style_aware_retrieval_strategy(
        support_style='gentle',
        relationship_stage='stable',
        milestone_salience='low',
        recent_signal_kinds=['support_request'],
    )
    assert strategy['layers'][0] == 'relationship'
    assert 'support' in strategy['reasoning']


def test_build_style_aware_retrieval_strategy_boosts_reflective_for_task_tool_signals():
    strategy = build_style_aware_retrieval_strategy(
        support_style='analytical',
        relationship_stage='stable',
        milestone_salience='low',
        recent_signal_kinds=['task_completed'],
    )
    assert strategy['layers'][0] == 'reflective'
