from __future__ import annotations

import importlib
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any
import logging

from .backend import MemoryBackendStatus
from .schema import MemorySearchFilters
from .vector_store import (
    Document,
    EmbeddingProvider,
    VectorStore,
    _embed_document,
    _embed_query,
    _memory_type_filter_values,
)

logger = logging.getLogger(__name__)


class QdrantVectorStore(VectorStore):
    """Qdrant-backed implementation of the VectorStore contract."""

    backend_name = "qdrant"

    def __init__(
        self,
        qdrant_url: str,
        qdrant_api_key: str = "",
        collection_name: str = "memories",
        timeout: float = 10.0,
        embedding_service: EmbeddingProvider | None = None,
    ):
        super().__init__(embedding_service=embedding_service)
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
            self.client = qdrant_client_cls(url=self._qdrant_url, api_key=self._qdrant_api_key or None, timeout=self._timeout)
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

    def _delete_collection_if_exists(self) -> bool:
        if not self._collection_exists():
            return False
        delete_collection = getattr(self.client, "delete_collection", None)
        if not callable(delete_collection):
            raise RuntimeError("qdrant_client_delete_collection_unavailable")
        delete_collection(collection_name=self.collection_name)
        self._collection_ready = False
        return True

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

    def add_document(self, doc: Document) -> None:
        self._docs.pop(doc.id, None)
        vector_array = _embed_document(self._embedding_service, doc.text).astype("float32")
        self._ensure_collection(int(vector_array.shape[0]))
        vector = vector_array.tolist()
        point = self._point_struct(id=self._point_id(doc.id), vector=vector, payload=self._serialize_doc(doc))
        self.client.upsert(collection_name=self.collection_name, points=[point])

    def add_metadata_document(self, doc: Document) -> None:
        self._docs[doc.id] = doc

    def delete_document(self, doc_id: str) -> None:
        self._docs.pop(doc_id, None)
        if not self._collection_exists():
            return
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=self._point_ids_list(points=[self._point_id(doc_id)]),
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

    def rebuild_index(self) -> dict[str, Any]:
        documents = self.list_documents()
        deleted_collection = self._delete_collection_if_exists()
        indexed = 0
        for doc in documents:
            self.add_document(doc)
            indexed += 1

        self._docs = {}
        return {
            "status": "rebuilt",
            "backend": self.backend_name,
            "collection": self.collection_name,
            "collection_deleted": deleted_collection,
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
        limit = max(top_k, min(256, top_k * 8 if filters else top_k))
        query_points = getattr(self.client, "query_points", None)
        if query_points is not None:
            results = query_points(
                collection_name=self.collection_name,
                query=vector,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            ).points
        else:
            search_method = getattr(self.client, "search")
            results = search_method(
                collection_name=self.collection_name,
                query_vector=vector,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
        filtered_results: list[tuple[Document, float]] = []
        for result in results:
            payload = result.payload or {}
            doc = self._deserialize_doc(result.id, payload)
            if not self._doc_matches_filters(doc, filters=filters):
                continue
            filtered_results.append((doc, float(result.score)))
            if len(filtered_results) >= top_k:
                break
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
        from datetime import datetime

        candidates = self.search(query=query, top_k=max(top_k * 3, top_k), filters=filters)
        if not candidates:
            return []

        now = datetime.now()
        scored: list[tuple[float, Document]] = []
        allowed_types = _memory_type_filter_values(memory_types)

        for doc, semantic_score in candidates:
            doc_type = str(doc.metadata.get("type") or "")
            if allowed_types is not None and doc_type not in allowed_types:
                continue
            if not self._doc_matches_filters(doc, filters=filters):
                continue

            timestamp_str = str(doc.metadata.get("timestamp") or "").strip()
            if timestamp_str:
                try:
                    timestamp = datetime.fromisoformat(timestamp_str)
                    age_days = (now - timestamp).days
                    recency_score = 1.0 / (1 + age_days / 30.0)
                except Exception:
                    recency_score = 0.5
            else:
                recency_score = 0.5

            quality_score = float(doc.metadata.get("quality_score") or doc.metadata.get("confidence") or 0.6)
            quality_score = max(0.0, min(1.0, quality_score))
            semantic_weight = max(0.0, 1 - recency_weight - quality_weight)
            final_score = float(semantic_score) * semantic_weight + recency_score * recency_weight + quality_score * quality_weight
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
