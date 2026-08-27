from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from time import perf_counter
from typing import Any, cast

from .backend import MemoryBackend, MemorySearchIncompleteError
from .metadata import recall_rejection_reason
from .relation_projection import MemoryRelationProjection, build_relation_projection
from .schema import MemorySearchFilters, RetrievalRequest, RetrievalTrace
from .vector_store import Document, memory_score_weights


class RetrievalPipeline:
    """Minimal retrieval pipeline skeleton for layered memory recall."""

    def __init__(self, store: MemoryBackend):
        self.store = store
        self.last_trace: dict[str, Any] | None = None
        # Relation expansion is a derived view. Cache it only for authorities
        # that expose a revision, so writes invalidate the view without
        # changing behavior for simpler backends.
        self._relation_projection_revision: int | None = None
        self._relation_projection_documents: dict[str, Document] | None = None
        self._relation_projection: MemoryRelationProjection | None = None

    def _relation_snapshot(self) -> tuple[dict[str, Document], MemoryRelationProjection]:
        list_documents = getattr(self.store, 'list_documents', None)
        if not callable(list_documents):
            return {}, MemoryRelationProjection({})
        raw_revision = getattr(self.store, 'get_authority_revision', None)
        revision: int | None = None
        if callable(raw_revision):
            try:
                candidate = raw_revision()
                if isinstance(candidate, int) and not isinstance(candidate, bool):
                    revision = candidate
            except Exception:
                # A diagnostic-only revision must never break recall.
                revision = None
        if (
            revision is not None
            and self._relation_projection_revision == revision
            and self._relation_projection_documents is not None
            and self._relation_projection is not None
        ):
            return self._relation_projection_documents, self._relation_projection

        documents = cast(Callable[[], list[Document]], list_documents)()
        documents_by_id = {doc.id: doc for doc in documents}
        projection = build_relation_projection(documents)
        if revision is not None:
            self._relation_projection_revision = revision
            self._relation_projection_documents = documents_by_id
            self._relation_projection = projection
        else:
            self._relation_projection_revision = None
            self._relation_projection_documents = None
            self._relation_projection = None
        return documents_by_id, projection

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
        anchor_ids = [doc.id for doc, _ in filtered]
        expanded: list[tuple[Document, float]] = []
        expansion_edges: list[dict[str, str]] = []
        expansion_truncated = False
        max_expansion_depth = 0
        relation_attempted = 0
        relation_accepted = 0
        relation_token_estimate = 0

        relation_started = perf_counter()
        list_documents = getattr(self.store, 'list_documents', None)
        if request.relation_expansion and filtered and request.relation_limit > 0 and callable(list_documents):
            documents_by_id, relation_projection = self._relation_snapshot()
            relation_queue: list[tuple[str, Document, float, int]] = [
                (doc.id, doc, float(score), 0) for doc, score in filtered
            ]
            seen_refs: set[str] = set(anchor_ids)

            while relation_queue and len(expanded) < request.relation_limit:
                anchor_id, anchor, anchor_score, depth = relation_queue.pop(0)
                if depth >= request.relation_depth:
                    continue
                for edge in relation_projection.neighbors(anchor.id):
                    related_id = edge.target_id
                    if related_id in seen_refs:
                        continue
                    seen_refs.add(related_id)
                    relation_attempted += 1
                    related_doc = documents_by_id.get(related_id)
                    if related_doc is None:
                        filter_reasons['relation_missing'] = filter_reasons.get('relation_missing', 0) + 1
                        continue
                    reason = _reject_reason(related_doc)
                    if reason is not None:
                        filter_reasons[f'relation_{reason}'] = filter_reasons.get(f'relation_{reason}', 0) + 1
                        continue
                    related_score = anchor_score * 0.85
                    expanded.append((related_doc, related_score))
                    relation_accepted += 1
                    relation_token_estimate += max(1, (len(related_doc.text) + 3) // 4)
                    expansion_edges.append({
                        'from': anchor_id,
                        'to': related_id,
                        'relation': edge.relation,
                        'evidence_type': edge.evidence_type,
                    })
                    max_expansion_depth = max(max_expansion_depth, depth + 1)
                    if depth + 1 < request.relation_depth:
                        relation_queue.append((related_id, related_doc, related_score, depth + 1))

            if relation_queue:
                expansion_truncated = True

        selected = sorted(
            [*filtered, *expanded],
            key=lambda item: float(item[1]),
            reverse=True,
        )[:top_k]
        scores = [float(score) for _, score in selected]
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
            recall_count=len(selected),
            selected_ids=[doc.id for doc, _ in selected],
            candidate_limit=candidate_limit,
            candidate_count=len(raw_results),
            filtered_count=len(eligible) + len(expanded),
            filtered_out_count=sum(filter_reasons.values()),
            filter_reasons=filter_reasons,
            top_score=max(scores) if scores else None,
            average_score=(sum(scores) / len(scores)) if scores else None,
            latency_ms=round((perf_counter() - started) * 1000, 3),
            backend_filter_downpushed=True,
            ranking_strategy="hybrid_semantic_lexical_learned_optional",
            score_weights=weights,
            anchor_ids=anchor_ids,
            expanded_ids=[doc.id for doc, _ in expanded],
            expansion_edges=expansion_edges,
            evidence_ids=[doc.id for doc, _ in expanded],
            expansion_depth=max_expansion_depth,
            expansion_truncated=expansion_truncated,
            relation_latency_ms=round((perf_counter() - relation_started) * 1000, 3),
            relation_attempted=relation_attempted,
            relation_accepted=relation_accepted,
            evidence_coverage=(relation_accepted / relation_attempted) if relation_attempted else 0.0,
            relation_token_estimate=relation_token_estimate,
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

        expansion_by_id = {doc.id: edge for (doc, _score), edge in zip(expanded, expansion_edges)}
        anchor_set = set(anchor_ids)

        def _recall_explanation(doc: Document, score: float) -> tuple[str, str, str | None]:
            edge = expansion_by_id.get(doc.id)
            if edge is not None:
                relation = str(edge.get('relation') or '关联')
                evidence_type = str(edge.get('evidence_type') or 'relation')
                return f'通过{relation}关联到已匹配记忆', evidence_type, relation
            if doc.id in anchor_set:
                return '与当前请求直接匹配', 'anchor', None
            return '按相关性排序进入结果', 'ranking', None

        payload = {
            'results': [
                {
                    'doc': doc.__dict__,
                    'score': score,
                    'score_components': _score_components(doc, float(score)),
                    'why_recalled': _recall_explanation(doc, float(score))[0],
                    'evidence_type': _recall_explanation(doc, float(score))[1],
                    'association': _recall_explanation(doc, float(score))[2],
                }
                for doc, score in selected[:top_k]
            ],
            'trace': trace_dict,
        }
        self.last_trace = trace_dict
        return payload
