from __future__ import annotations

import importlib
import ipaddress
import logging
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import numpy as np

from .backend import MemoryBackendStatus, MemorySearchIncompleteError
from .reranker import lexical_overlap_score, normalize_scores
from .schema import MemorySearchFilters
from .vector_store import (
    Document,
    EmbeddingProvider,
    VectorStore,
    _embed_document,
    _embed_query,
    _memory_type_filter_values,
    _raise_if_rebuild_cancelled,
    memory_feedback_quality_score,
    memory_recency_score,
    memory_score_components,
    memory_score_weights,
)

logger = logging.getLogger(__name__)
QDRANT_SEARCH_SCAN_LIMIT = 4096
QDRANT_MANIFEST_PAGE_SIZE = 1024


def _loopback_http_client_options(qdrant_url: str) -> dict[str, bool]:
    parsed = urlparse(qdrant_url)
    if parsed.scheme.lower() != "http":
        return {}
    hostname = (parsed.hostname or "").lower()
    is_loopback = hostname == "localhost"
    if not is_loopback:
        try:
            is_loopback = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            is_loopback = False
    if not is_loopback:
        return {}
    return {"trust_env": False, "verify": False}


class QdrantVectorStore(VectorStore):
    """Qdrant-backed implementation of the VectorStore contract."""

    backend_name = "qdrant"
    supports_durable_rebuild_checkpoint = True

    def __init__(
        self,
        qdrant_url: str,
        qdrant_api_key: str = "",
        collection_name: str = "memories",
        timeout: float = 10.0,
        embedding_service: EmbeddingProvider | None = None,
        reranker: Any | None = None,
        reranker_candidate_count: int = 32,
    ):
        super().__init__(
            embedding_service=embedding_service,
            reranker=reranker,
            reranker_candidate_count=reranker_candidate_count,
        )
        qdrant_client_module = importlib.import_module("qdrant_client")
        qdrant_models_module = importlib.import_module("qdrant_client.models")
        qdrant_client_cls = getattr(qdrant_client_module, "QdrantClient")
        self._distance = getattr(qdrant_models_module, "Distance")
        self._point_ids_list = getattr(qdrant_models_module, "PointIdsList")
        self._point_struct = getattr(qdrant_models_module, "PointStruct")
        self._vector_params = getattr(qdrant_models_module, "VectorParams")
        self._filter = getattr(qdrant_models_module, "Filter")
        self._field_condition = getattr(qdrant_models_module, "FieldCondition")
        self._match_value = getattr(qdrant_models_module, "MatchValue")
        self._match_any = getattr(qdrant_models_module, "MatchAny")
        self._qdrant_url = qdrant_url.strip().rstrip("/")
        if not self._qdrant_url:
            raise ValueError("qdrant_url_required")
        self._qdrant_api_key = qdrant_api_key.strip()
        self._timeout = float(timeout)
        if self._qdrant_url == ":memory:":
            self.client = qdrant_client_cls(location=":memory:")
        else:
            self.client = qdrant_client_cls(
                url=self._qdrant_url,
                api_key=self._qdrant_api_key or None,
                timeout=self._timeout,
                **_loopback_http_client_options(self._qdrant_url),
            )
        self.collection_name = collection_name
        self._collection_ready = False

    def _point_id(self, doc_id: str) -> int | str:
        clean = str(doc_id).strip()
        if clean.isdigit():
            return int(clean)
        try:
            return str(uuid.UUID(clean))
        except ValueError:
            return str(uuid.uuid5(uuid.NAMESPACE_URL, f"yuizaki-memory:{clean}"))

    def _collection_exists(self) -> bool:
        if self._collection_ready:
            return True
        collection_exists = getattr(self.client, "collection_exists", None)
        if callable(collection_exists):
            self._collection_ready = bool(collection_exists(collection_name=self.collection_name))
            return self._collection_ready
        collections = self.client.get_collections().collections
        self._collection_ready = any(c.name == self.collection_name for c in collections)
        return self._collection_ready

    def _ensure_collection(self, vector_size: int) -> None:
        if not self._collection_exists():
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=self._vector_params(size=vector_size, distance=self._distance.COSINE),
            )
        self._collection_ready = True

    def _serialize_doc(self, doc: Document) -> dict[str, Any]:
        return {
            "doc_id": doc.id,
            "text": doc.text,
            "metadata": doc.metadata,
            "timestamp": doc.metadata.get("timestamp") or datetime.now().isoformat(),
            "type": doc.metadata.get("type"),
            "layer": doc.metadata.get("layer"),
            "scope": doc.metadata.get("scope"),
            "session_id": doc.metadata.get("session_id"),
            "workspace_id": doc.metadata.get("workspace_id"),
            "quality_score": doc.metadata.get("quality_score"),
            "confidence": doc.metadata.get("confidence"),
            "source": doc.metadata.get("source"),
        }

    def _deserialize_doc(self, point_id: Any, payload: dict[str, Any] | None) -> Document:
        data = payload or {}
        metadata = dict(data.get("metadata") or {})
        for key in ("timestamp", "type", "layer", "scope", "session_id", "workspace_id", "quality_score", "confidence", "source"):
            if key in data and data[key] is not None and key not in metadata:
                metadata[key] = data[key]
        doc_id = str(data.get("doc_id") or metadata.get("doc_id") or point_id)
        return Document(id=doc_id, text=str(data.get("text") or ""), metadata=metadata)

    def _build_query_filter(
        self,
        *,
        filters: MemorySearchFilters | None = None,
        memory_types: Sequence[Any] | None = None,
    ):
        must = []
        if filters and filters.scope:
            must.append(self._field_condition(key="scope", match=self._match_value(value=filters.scope)))
        # Keep workspace/session identity checks in the shared post-filter path.
        # Qdrant cannot reliably match both a concrete workspace_id and the
        # intentionally-unscoped workspace memories with one simple condition.
        if filters and filters.session_id and filters.scope == "session":
            must.append(self._field_condition(key="session_id", match=self._match_value(value=filters.session_id)))
        if filters and filters.layers:
            if len(filters.layers) == 1:
                must.append(self._field_condition(key="layer", match=self._match_value(value=filters.layers[0])))
            else:
                must.append(self._field_condition(key="layer", match=self._match_any(any=list(filters.layers))))
        allowed_type_values = _memory_type_filter_values(memory_types)
        if allowed_type_values:
            values = sorted(allowed_type_values)
            if len(values) == 1:
                must.append(self._field_condition(key="type", match=self._match_value(value=values[0])))
            else:
                must.append(self._field_condition(key="type", match=self._match_any(any=values)))
        if not must:
            return None
        kwargs: dict[str, Any] = {}
        if must:
            kwargs["must"] = must
        return self._filter(**kwargs)

    def _upsert_document(self, doc: Document, *, index_generation: str | None = None) -> None:
        self._docs.pop(doc.id, None)
        vector_array = _embed_document(self._embedding_service, doc.text).astype("float32")
        self._ensure_collection(int(vector_array.shape[0]))
        vector = vector_array.tolist()
        payload = self._serialize_doc(doc)
        if index_generation:
            payload["index_generation"] = index_generation
        point = self._point_struct(id=self._point_id(doc.id), vector=vector, payload=payload)
        self.client.upsert(collection_name=self.collection_name, points=[point], wait=True)

    def add_document(self, doc: Document) -> None:
        self._upsert_document(doc)

    def add_document_for_generation(self, doc: Document, index_generation: str) -> None:
        self._upsert_document(doc, index_generation=index_generation)

    def add_metadata_document(self, doc: Document) -> None:
        self._docs[doc.id] = doc

    def update_metadata(self, doc_id: str, metadata: dict[str, Any]) -> None:
        updated_metadata = dict(metadata)
        local_document = self._docs.get(doc_id)
        collection_exists = self._collection_exists()
        if not collection_exists:
            if local_document is None:
                raise KeyError(doc_id)
            local_document.metadata = updated_metadata
            return

        metadata_payload = {
            "metadata": updated_metadata,
            **{
                key: updated_metadata.get(key)
                for key in (
                    "timestamp",
                    "type",
                    "layer",
                    "scope",
                    "session_id",
                    "workspace_id",
                    "quality_score",
                    "confidence",
                    "source",
                )
            },
        }
        point_id = self._point_id(doc_id)
        set_payload = getattr(self.client, "set_payload", None)
        if callable(set_payload):
            set_payload(
                collection_name=self.collection_name,
                payload=metadata_payload,
                points=[point_id],
                wait=True,
            )
        else:
            overwrite_payload = getattr(self.client, "overwrite_payload", None)
            retrieve = getattr(self.client, "retrieve", None)
            if not callable(overwrite_payload) or not callable(retrieve):
                raise AttributeError("qdrant_client_payload_update_unavailable")
            points = retrieve(
                collection_name=self.collection_name,
                ids=[point_id],
                with_payload=True,
                with_vectors=False,
            )
            if not isinstance(points, Sequence):
                raise TypeError("qdrant_retrieve_must_return_sequence")
            if not points:
                raise KeyError(doc_id)
            point = points[0]
            retrieved_payload = getattr(point, "payload", None)
            if retrieved_payload is not None and not isinstance(retrieved_payload, dict):
                raise TypeError("qdrant_point_payload_must_be_mapping")
            current = self._deserialize_doc(
                getattr(point, "id", point_id),
                retrieved_payload,
            )
            current.metadata = updated_metadata
            serialized = self._serialize_doc(current)
            if retrieved_payload and retrieved_payload.get("index_generation"):
                serialized["index_generation"] = retrieved_payload["index_generation"]
            overwrite_payload(
                collection_name=self.collection_name,
                payload=serialized,
                points=[point_id],
                wait=True,
            )

        if local_document is not None:
            local_document.metadata = updated_metadata

    def delete_document(self, doc_id: str) -> None:
        self._docs.pop(doc_id, None)
        if not self._collection_exists():
            return
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=self._point_ids_list(points=[self._point_id(doc_id)]),
            wait=True,
        )

    def list_documents(self) -> list[Document]:
        if not self._collection_exists():
            return list(self._docs.values())
        documents: list[Document] = []
        offset = None
        while True:
            points, offset = self.client.scroll(
                collection_name=self.collection_name,
                with_payload=True,
                with_vectors=False,
                limit=128,
                offset=offset,
            )
            documents.extend(self._deserialize_doc(point.id, point.payload) for point in points)
            if offset is None:
                break
        known_ids = {doc.id for doc in documents}
        documents.extend(doc for doc in self._docs.values() if doc.id not in known_ids)
        return documents

    def get_index_manifest(self, index_generation: str) -> tuple[set[str], set[str]]:
        """Return current-generation and all document IDs without full payloads."""
        if not self._collection_exists():
            return set(), set()
        generation_ids: set[str] = set()
        all_ids: set[str] = set()
        offset = None
        while True:
            points, offset = self.client.scroll(
                collection_name=self.collection_name,
                with_payload=["doc_id", "index_generation"],
                with_vectors=False,
                limit=QDRANT_MANIFEST_PAGE_SIZE,
                offset=offset,
            )
            for point in points:
                payload = getattr(point, "payload", None)
                if not isinstance(payload, dict):
                    continue
                doc_id = str(payload.get("doc_id") or point.id)
                all_ids.add(doc_id)
                if payload.get("index_generation") == index_generation:
                    generation_ids.add(doc_id)
            if offset is None:
                break
        return generation_ids, all_ids

    def list_document_ids(self) -> set[str]:
        _generation_ids, document_ids = self.get_index_manifest("")
        document_ids.update(self._docs)
        return document_ids

    def get_rebuild_generation_ids(self, index_generation: str) -> set[str]:
        generation_ids, _all_ids = self.get_index_manifest(index_generation)
        return generation_ids

    def rebuild_index(
        self,
        progress_callback: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | Any | None = None,
    ) -> dict[str, Any]:
        documents = self.list_documents()
        total = len(documents)
        indexed = 0
        _raise_if_rebuild_cancelled(should_cancel, processed=0, total=total, phase="indexing")
        for doc in documents:
            self.add_document(doc)
            indexed += 1
            if progress_callback is not None:
                progress_callback(indexed, total, "indexing")
            _raise_if_rebuild_cancelled(
                should_cancel,
                processed=indexed,
                total=total,
                phase="indexing",
            )

        self._docs = {}
        if progress_callback is not None:
            progress_callback(indexed, total, "complete")
        return {
            "status": "rebuilt",
            "backend": self.backend_name,
            "collection": self.collection_name,
            "collection_deleted": False,
            "document_count": len(documents),
            "indexed_count": indexed,
            "skipped_count": 0,
        }

    def search(self, query: str, top_k: int = 5, filters: MemorySearchFilters | None = None) -> list[tuple[Document, float]]:
        if filters and filters.scope == "session" and not filters.session_id:
            return []
        if not self._collection_exists():
            return []
        vector = _embed_query(self._embedding_service, query).astype("float32").tolist()
        query_filter = self._build_query_filter(filters=filters)
        query_points = getattr(self.client, "query_points", None)
        filtered_results: list[tuple[Document, float]] = []
        offset = 0
        scanned_count = 0
        rejected_count = 0
        page_size = max(8, min(256, top_k * 8))

        while len(filtered_results) < top_k and scanned_count < QDRANT_SEARCH_SCAN_LIMIT:
            page_limit = min(page_size, QDRANT_SEARCH_SCAN_LIMIT - scanned_count)
            if query_points is not None:
                results = query_points(
                    collection_name=self.collection_name,
                    query=vector,
                    query_filter=query_filter,
                    limit=page_limit,
                    offset=offset,
                    with_payload=True,
                ).points
            else:
                search_method = getattr(self.client, "search")
                results = search_method(
                    collection_name=self.collection_name,
                    query_vector=vector,
                    query_filter=query_filter,
                    limit=page_limit,
                    offset=offset,
                    with_payload=True,
                )

            if not results:
                break
            scanned_count += len(results)
            offset += len(results)
            for result in results:
                payload = result.payload or {}
                doc = self._deserialize_doc(result.id, payload)
                if not self._doc_matches_filters(doc, filters=filters):
                    rejected_count += 1
                    continue
                filtered_results.append((doc, float(result.score)))
                if len(filtered_results) >= top_k:
                    break
            if len(results) < page_limit:
                break
            page_size = min(256, page_size * 2)

        if len(filtered_results) < top_k and scanned_count >= QDRANT_SEARCH_SCAN_LIMIT:
            logger.warning(
                "Qdrant memory search scan limit reached: requested=%s returned=%s scanned=%s rejected=%s",
                top_k,
                len(filtered_results),
                scanned_count,
                rejected_count,
            )
            raise MemorySearchIncompleteError(
                requested_count=top_k,
                selected_ids=[doc.id for doc, _score in filtered_results],
                scanned_count=scanned_count,
                rejected_count=rejected_count,
                scan_limit=QDRANT_SEARCH_SCAN_LIMIT,
            )
        return filtered_results

    def _collection_vector_size(self, info: Any) -> int | None:
        config = getattr(info, "config", None)
        params = getattr(config, "params", None)
        vectors = getattr(params, "vectors", None)
        if vectors is None:
            return None
        size = getattr(vectors, "size", None)
        if size is not None:
            return int(size)
        if isinstance(vectors, dict):
            first_vector = next(iter(vectors.values()), None)
            size = getattr(first_vector, "size", None)
            return int(size) if size is not None else None
        return None

    def search_with_rerank(
        self,
        query: str,
        top_k: int = 5,
        memory_types: Sequence[Any] | None = None,
        recency_weight: float = 0.2,
        quality_weight: float = 0.15,
        filters: MemorySearchFilters | None = None,
    ) -> list[tuple[Document, float]]:
        candidates = self.search(
            query=query,
            top_k=max(top_k * 8, self._reranker_candidate_count if getattr(self._reranker, "enabled", False) else top_k),
            filters=filters,
        )
        if not candidates:
            return []

        candidate_docs = [doc for doc, _ in candidates]
        learned_scores = np.zeros(len(candidate_docs), dtype=np.float32)
        learned_enabled = bool(getattr(self._reranker, "enabled", False))
        if learned_enabled and self._reranker is not None:
            try:
                learned_scores = normalize_scores(self._reranker.score(query, [doc.text for doc in candidate_docs]))
            except Exception as exc:
                learned_enabled = False
                logger.warning("Learned Qdrant reranker unavailable; using hybrid scores: %s", exc)

        now = datetime.now(timezone.utc)
        scored: list[tuple[float, Document]] = []
        allowed_types = _memory_type_filter_values(memory_types)
        score_components = self._score_component_cache()
        score_components.clear()

        for position, (doc, semantic_score) in enumerate(candidates):
            doc_type = str(doc.metadata.get("type") or "")
            if allowed_types is not None and doc_type not in allowed_types:
                continue
            if not self._doc_matches_filters(doc, filters=filters):
                continue

            recency_score = memory_recency_score(doc.metadata, now=now)

            quality_baseline = float(doc.metadata.get("quality_score") or doc.metadata.get("confidence") or 0.6)
            quality_score = memory_feedback_quality_score(doc.metadata, quality_baseline)
            lexical_score = lexical_overlap_score(query, doc.text)
            learned_score = float(learned_scores[position]) if learned_enabled and position < len(learned_scores) else 0.0
            weights = memory_score_weights(
                recency_weight=recency_weight,
                quality_weight=quality_weight,
                learned_enabled=learned_enabled,
            )
            components = memory_score_components(
                semantic=float(semantic_score),
                lexical=lexical_score,
                learned=learned_score,
                recency=recency_score,
                quality=quality_score,
                semantic_weight=weights["semantic"],
                lexical_weight=weights["lexical"],
                learned_weight=weights["learned"],
                recency_weight=weights["recency"],
                quality_weight=weights["quality"],
            )
            final_score = components["final"]
            score_components[(query, doc.id, recency_weight, quality_weight)] = components
            scored.append((final_score, doc))

        scored.sort(reverse=True, key=lambda item: item[0])
        return [(doc, score) for score, doc in scored[:top_k]]

    def get_status(self) -> MemoryBackendStatus:
        try:
            if not self._collection_exists():
                return MemoryBackendStatus(
                    backend=self.backend_name,
                    healthy=True,
                    message=f"Qdrant collection not initialized yet: {self.collection_name}",
                    document_count=0,
                    metadata={
                        "collection": self.collection_name,
                        "initialized": False,
                        "url": self._qdrant_url,
                        "api_key_configured": bool(self._qdrant_api_key),
                    },
                )
            info = self.client.get_collection(self.collection_name)
            approximate_count = int(getattr(info, "points_count", 0) or 0)
            count_result = self.client.count(
                collection_name=self.collection_name,
                exact=True,
            )
            count = int(getattr(count_result, "count", 0) or 0)
            vector_size = self._collection_vector_size(info)
            return MemoryBackendStatus(
                backend=self.backend_name,
                healthy=True,
                message=f"Qdrant collection ready: {self.collection_name}",
                document_count=count,
                metadata={
                    "collection": self.collection_name,
                    "initialized": True,
                    "url": self._qdrant_url,
                    "api_key_configured": bool(self._qdrant_api_key),
                    "vector_size": vector_size,
                    "points_count": approximate_count,
                    "exact_points_count": count,
                    "indexed_vectors_count": int(getattr(info, "indexed_vectors_count", 0) or 0),
                },
            )
        except Exception as exc:
            logger.error("Qdrant health check failed: %s", exc)
            return MemoryBackendStatus(
                backend=self.backend_name,
                healthy=False,
                message=f"Qdrant error: {exc}",
                metadata={
                    "collection": self.collection_name,
                    "url": self._qdrant_url,
                    "api_key_configured": bool(self._qdrant_api_key),
                },
            )
