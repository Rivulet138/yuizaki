from __future__ import annotations

from dataclasses import asdict
from time import perf_counter
from typing import Any

from .backend import MemoryBackend, MemorySearchIncompleteError
from .metadata import recall_rejection_reason
from .schema import MemorySearchFilters, RetrievalRequest, RetrievalTrace
from .vector_store import Document, memory_score_weights


class RetrievalPipeline:
    """Minimal retrieval pipeline skeleton for layered memory recall."""

    def __init__(self, store: MemoryBackend):
        self.store = store
        self.last_trace: dict[str, Any] | None = None

    def recall(self, request: RetrievalRequest) -> dict[str, Any]:
        started = perf_counter()
        top_k = max(1, request.top_k)
        candidate_limit = max(top_k * 8, top_k + 20)
        filters = MemorySearchFilters(
            scope=request.scope,
            session_id=request.session_id,
            workspace_id=request.workspace_id,
            layers=request.layers,
        )
        try:
            raw_results = self.store.search_with_rerank(
                query=request.query,
                top_k=candidate_limit,
                memory_types=request.memory_types,
                recency_weight=request.recency_weight,
                quality_weight=request.quality_weight,
                filters=filters,
            )
        except MemorySearchIncompleteError as exc:
            trace = RetrievalTrace(
                query=request.query,
                scope=request.scope,
                session_id=request.session_id,
                workspace_id=request.workspace_id,
                layers=request.layers,
                recall_count=exc.returned_count,
                selected_ids=exc.selected_ids,
                candidate_limit=exc.scan_limit,
                candidate_count=exc.scanned_count,
                filtered_count=exc.returned_count,
                filtered_out_count=exc.rejected_count,
                filter_reasons={"expired_or_filtered": exc.rejected_count},
                latency_ms=round((perf_counter() - started) * 1000, 3),
                backend_filter_downpushed=False,
                complete=False,
                error_code=exc.code,
                scan_limit_reached=True,
            )
            trace_dict = asdict(trace)
            self.last_trace = trace_dict
            exc.trace = trace_dict
            raise

        eligible: list[tuple[Document, float]] = []
        filter_reasons: dict[str, int] = {}

        def _reject_reason(doc: Document) -> str | None:
            metadata = doc.metadata or {}
            state_reason = recall_rejection_reason(metadata)
            if state_reason is not None:
                return state_reason
            layer = str(metadata.get('layer', 'semantic'))
            scope = str(metadata.get('scope', 'workspace'))
            if layer not in request.layers:
                return 'layer'
            if request.scope == 'global':
                if scope != 'global':
                    return 'scope'
                if request.session_id is not None and metadata.get('session_id') not in (None, request.session_id):
                    return 'session'
                return None
            if request.scope and scope != request.scope:
                return 'scope'
            if request.scope == 'session':
                if request.session_id is None or metadata.get('session_id') not in (request.session_id,):
                    return 'session'
            elif request.scope == 'workspace':
                document_workspace_id = metadata.get('workspace_id')
                if request.workspace_id is None:
                    if document_workspace_id is not None:
                        return 'workspace'
                elif document_workspace_id not in (request.workspace_id, None):
                    return 'workspace'
            else:
                if request.session_id is not None and metadata.get('session_id') not in (None, request.session_id):
                    return 'session'
                if request.workspace_id is not None and metadata.get('workspace_id') not in (None, request.workspace_id):
                    return 'workspace'
            return None

        for doc, score in raw_results:
            reason = _reject_reason(doc)
            if reason is not None:
                filter_reasons[reason] = filter_reasons.get(reason, 0) + 1
                continue
            eligible.append((doc, score))

        filtered = eligible[:top_k]
        scores = [float(score) for _, score in filtered]
        reranker = getattr(self.store, "_reranker", None)
        index = getattr(self.store, "index", None)
        if reranker is None and index is not None:
            reranker = getattr(index, "_reranker", None)
        weights = memory_score_weights(
            recency_weight=request.recency_weight,
            quality_weight=request.quality_weight,
            learned_enabled=bool(getattr(reranker, "enabled", False)),
        )

        trace = RetrievalTrace(
            query=request.query,
            scope=request.scope,
            session_id=request.session_id,
            workspace_id=request.workspace_id,
            layers=request.layers,
            recall_count=len(filtered),
            selected_ids=[doc.id for doc, _ in filtered],
            candidate_limit=candidate_limit,
            candidate_count=len(raw_results),
            filtered_count=len(eligible),
            filtered_out_count=sum(filter_reasons.values()),
            filter_reasons=filter_reasons,
            top_score=max(scores) if scores else None,
            average_score=(sum(scores) / len(scores)) if scores else None,
            latency_ms=round((perf_counter() - started) * 1000, 3),
            backend_filter_downpushed=True,
            ranking_strategy="hybrid_semantic_lexical_learned_optional",
            score_weights=weights,
        )
        trace_dict = asdict(trace)

        score_component_getter = getattr(self.store, "get_score_components", None)

        def _score_components(doc: Document, score: float) -> dict[str, float | None]:
            if callable(score_component_getter):
                components = score_component_getter(
                    request.query,
                    doc.id,
                    request.recency_weight,
                    request.quality_weight,
                )
                if (
                    isinstance(components, dict)
                    and abs(float(components.get("final", score)) - float(score)) < 1e-9
                ):
                    return {str(key): float(value) for key, value in components.items()}
            return {
                "semantic": None,
                "lexical": None,
                "learned": None,
                "recency": None,
                "quality": None,
                "final": float(score),
            }

        payload = {
            'results': [
                {
                    'doc': doc.__dict__,
                    'score': score,
                    'score_components': _score_components(doc, float(score)),
                }
                for doc, score in filtered[:top_k]
            ],
            'trace': trace_dict,
        }
        self.last_trace = trace_dict
        return payload
