"""Pluggable vector store interface for RAG/memory.

Week 1 Task 1.2: Upgraded with real sentence-transformers embeddings.
Supports both in-memory (legacy) and Qdrant (production) backends.
"""

from __future__ import annotations

import importlib
import logging
import os
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Protocol, Tuple

import numpy as np

from ..core.config import DEFAULT_EMBEDDING_MODEL
from .backend import MemoryBackendStatus
from .metadata import is_metadata_recallable
from .reranker import LearnedReranker, lexical_overlap_score, normalize_scores
from .schema import MemorySearchFilters

logger = logging.getLogger(__name__)


def memory_recency_score(metadata: Dict[str, Any], *, now: datetime | None = None) -> float:
  """Return a stable 30-day recency score using event time before system time."""
  raw = next(
    (
      metadata.get(key)
      for key in ("occurred_at", "updated_at", "timestamp")
      if metadata.get(key)
    ),
    None,
  )
  if not isinstance(raw, str):
    return 0.5
  try:
    instant = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
  except ValueError:
    return 0.5
  if instant.tzinfo is None or instant.utcoffset() is None:
    instant = instant.replace(tzinfo=timezone.utc)
  current = now or datetime.now(timezone.utc)
  if current.tzinfo is None or current.utcoffset() is None:
    current = current.replace(tzinfo=timezone.utc)
  age_days = max(0.0, (current.astimezone(timezone.utc) - instant.astimezone(timezone.utc)).total_seconds() / 86400)
  return 1.0 / (1.0 + age_days / 30.0)


def memory_score_components(
  *,
  semantic: float,
  lexical: float,
  learned: float,
  recency: float,
  quality: float,
  semantic_weight: float,
  lexical_weight: float,
  learned_weight: float,
  recency_weight: float,
  quality_weight: float,
) -> Dict[str, float]:
  final = (
    semantic * semantic_weight
    + lexical * lexical_weight
    + learned * learned_weight
    + recency * recency_weight
    + quality * quality_weight
  )
  return {
    "semantic": float(semantic),
    "lexical": float(lexical),
    "learned": float(learned),
    "recency": float(recency),
    "quality": float(quality),
    "final": float(final),
  }


def memory_score_weights(
  *,
  recency_weight: float,
  quality_weight: float,
  learned_enabled: bool,
) -> Dict[str, float]:
  weights = {
    "lexical": 0.10,
    "learned": 0.45 if learned_enabled else 0.0,
    "recency": max(0.0, float(recency_weight)),
    "quality": max(0.0, float(quality_weight)),
  }
  weights["semantic"] = max(0.0, 1.0 - sum(weights.values()))
  total = sum(weights.values())
  if total > 1.0:
    weights = {key: value / total for key, value in weights.items()}
  return weights


def _resolve_huggingface_snapshot(cache_root: Path, model_name: str) -> str:
  """Return a local HuggingFace snapshot path when the model is already cached."""
  repo_cache_name = f"models--{model_name.replace('/', '--')}"
  candidates = [cache_root / repo_cache_name, cache_root / "hub" / repo_cache_name]

  for model_cache in candidates:
    refs_main = model_cache / "refs" / "main"
    snapshots_dir = model_cache / "snapshots"
    if not snapshots_dir.exists():
      continue

    if refs_main.exists():
      revision = refs_main.read_text(encoding="utf-8").strip()
      candidate = snapshots_dir / revision
      if candidate.exists():
        return str(candidate)

    snapshot_candidates = [item for item in snapshots_dir.iterdir() if item.is_dir()]
    if snapshot_candidates:
      snapshot_candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
      return str(snapshot_candidates[0])

  return ""


def _resolve_embedding_model_path(model_name: str) -> tuple[str, str | None, bool]:
  """Resolve embedding model target, cache folder and whether loading can be offline."""
  local_model_path = os.getenv("EMBEDDING_MODEL_LOCAL_PATH", "").strip()
  hf_home = os.getenv("HF_HOME", "").strip()
  sentence_transformers_home = os.getenv("SENTENCE_TRANSFORMERS_HOME", "").strip()
  cache_dir = sentence_transformers_home or hf_home or None

  if local_model_path:
    local_path = Path(local_model_path)
    refs_main = local_path / "refs" / "main"
    snapshots_dir = local_path / "snapshots"
    if refs_main.exists() and snapshots_dir.exists():
      revision = refs_main.read_text(encoding="utf-8").strip()
      candidate = snapshots_dir / revision
      if candidate.exists():
        return str(candidate), cache_dir, True
    if snapshots_dir.exists():
      snapshot_candidates = [item for item in snapshots_dir.iterdir() if item.is_dir()]
      if snapshot_candidates:
        snapshot_candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        return str(snapshot_candidates[0]), cache_dir, True
    if local_path.exists():
      return str(local_path), cache_dir, True

  cache_roots = []
  for raw in [sentence_transformers_home, hf_home, str(Path.cwd() / ".cache" / "huggingface")]:
    if raw:
      root = Path(raw)
      if root not in cache_roots:
        cache_roots.append(root)

  for cache_root in cache_roots:
    snapshot = _resolve_huggingface_snapshot(cache_root, model_name)
    if snapshot:
      return snapshot, cache_dir, True

  return model_name, cache_dir, False


class MemoryType(str, Enum):
  """Memory classification types"""
  FACT = "fact"           # 事实："用户喜欢猫"
  PREFERENCE = "preference"  # 偏好："用户讨厌早起"
  EVENT = "event"         # 事件："2024-03-15 一起看了电影"


def _memory_type_filter_values(memory_types: Sequence[Any] | None) -> set[str] | None:
  if memory_types is None:
    return None
  values: set[str] = set()
  for item in memory_types:
    values.add(item.value if isinstance(item, MemoryType) else str(item))
  return values


@dataclass
class Document:
  """Single memory document chunk."""

  id: str
  text: str
  metadata: Dict[str, Any]


def is_memory_recallable(
  doc: Document,
  filters: MemorySearchFilters | None = None,
  memory_types: Sequence[Any] | None = None,
) -> bool:
  metadata = doc.metadata or {}
  if not is_metadata_recallable(metadata):
    return False
  allowed_types = _memory_type_filter_values(memory_types)
  if allowed_types is not None and str(metadata.get("type") or "") not in allowed_types:
    return False
  if not filters:
    return True
  if filters.layers and str(metadata.get("layer") or "semantic") not in filters.layers:
    return False
  doc_scope = str(metadata.get("scope") or "workspace")
  if filters.scope == "global":
    return doc_scope == "global"
  if filters.scope == "session":
    return doc_scope == "session" and bool(filters.session_id) and metadata.get("session_id") == filters.session_id
  if filters.scope == "workspace":
    if doc_scope != "workspace":
      return False
    return not filters.workspace_id or metadata.get("workspace_id") in (filters.workspace_id, None)
  if filters.session_id is not None and metadata.get("session_id") not in (None, filters.session_id):
    return False
  if filters.workspace_id is not None and metadata.get("workspace_id") not in (None, filters.workspace_id):
    return False
  return True


class EmbeddingProvider(Protocol):
  @property
  def dimension(self) -> int: ...

  def embed(self, text: str) -> np.ndarray: ...


def _embed_document(embedding_service: EmbeddingProvider, text: str) -> np.ndarray:
  method = getattr(embedding_service, "embed_document", None)
  if callable(method):
    return np.asarray(method(text), dtype=np.float32)
  return np.asarray(embedding_service.embed(text), dtype=np.float32)


def _embed_query(embedding_service: EmbeddingProvider, text: str) -> np.ndarray:
  method = getattr(embedding_service, "embed_query", None)
  if callable(method):
    return np.asarray(method(text), dtype=np.float32)
  return np.asarray(embedding_service.embed(text), dtype=np.float32)


class EmbeddingService:
  """Real embedding service using sentence-transformers"""

  def __init__(self, model_name: str = DEFAULT_EMBEDDING_MODEL):
    """
    Initialize with Chinese-optimized model.
    Alternatives: 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
    """
    try:
      sentence_transformers = importlib.import_module("sentence_transformers")
      SentenceTransformer = getattr(sentence_transformers, "SentenceTransformer")
    except ImportError as exc:
      raise RuntimeError(
        "sentence-transformers is required for default EmbeddingService. "
        "Install python/requirements.txt or pass a custom embedding_service to VectorStore."
      ) from exc

    load_target, cache_dir, offline = _resolve_embedding_model_path(model_name)
    if offline:
      os.environ.setdefault("HF_HUB_OFFLINE", "1")
      os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
      logger.info("Loading embedding model from local snapshot: %s", load_target)
    else:
      logger.info("Loading embedding model: %s", model_name)

    self.model = SentenceTransformer(load_target, cache_folder=cache_dir)
    dimension = self.model.get_sentence_embedding_dimension()
    if dimension is None:
      raise RuntimeError("embedding_model_dimension_unavailable")
    self.dimension = int(dimension)
    logger.info(f"Embedding dimension: {self.dimension}")

  def embed(self, text: str) -> np.ndarray:
    """Generate embedding vector for text"""
    return np.asarray(self.model.encode(text, convert_to_numpy=True), dtype=np.float32)

  def embed_query(self, text: str) -> np.ndarray:
    """Generate an embedding optimized for retrieval queries when the model supports it."""
    encode_query = getattr(self.model, "encode_query", None)
    if callable(encode_query):
      return np.asarray(encode_query(text, convert_to_numpy=True), dtype=np.float32)
    return self.embed(text)

  def embed_document(self, text: str) -> np.ndarray:
    """Generate an embedding optimized for indexed memory documents when supported."""
    encode_document = getattr(self.model, "encode_document", None)
    if callable(encode_document):
      return np.asarray(encode_document(text, convert_to_numpy=True), dtype=np.float32)
    return self.embed(text)

  def embed_batch(self, texts: List[str]) -> np.ndarray:
    """Batch embedding for efficiency"""
    return np.asarray(self.model.encode(texts, convert_to_numpy=True), dtype=np.float32)


class LazyEmbeddingService:
  """Load the sentence-transformers model only when memory vectors need it."""

  def __init__(self, model_name: str = DEFAULT_EMBEDDING_MODEL):
    self._model_name = model_name
    self._service: EmbeddingService | None = None

  @property
  def is_loaded(self) -> bool:
    return self._service is not None

  def _ensure_service(self) -> EmbeddingService:
    if self._service is None:
      self._service = EmbeddingService(model_name=self._model_name)
    return self._service

  @property
  def dimension(self) -> int:
    return self._ensure_service().dimension

  def embed(self, text: str) -> np.ndarray:
    return self._ensure_service().embed(text)

  def embed_query(self, text: str) -> np.ndarray:
    service = self._ensure_service()
    method = getattr(service, "embed_query", None)
    if callable(method):
      return np.asarray(method(text), dtype=np.float32)
    return service.embed(text)

  def embed_document(self, text: str) -> np.ndarray:
    service = self._ensure_service()
    method = getattr(service, "embed_document", None)
    if callable(method):
      return np.asarray(method(text), dtype=np.float32)
    return service.embed(text)

  def embed_batch(self, texts: List[str]) -> np.ndarray:
    return self._ensure_service().embed_batch(texts)


class VectorStore:
  """Minimal vector store abstraction with real embeddings."""

  backend_name = "inmemory"

  def __init__(
    self,
    embedding_service: EmbeddingProvider | None = None,
    reranker: LearnedReranker | None = None,
    reranker_candidate_count: int = 32,
  ):
    self._embedding_service = embedding_service or LazyEmbeddingService()
    self._reranker = reranker
    self._reranker_candidate_count = max(5, min(100, int(reranker_candidate_count)))
    self._docs: Dict[str, Document] = {}
    self._vectors: Dict[str, np.ndarray] = {}
    self._score_context = threading.local()

  def _score_component_cache(self) -> Dict[tuple[str, str, float, float], Dict[str, float]]:
    context = getattr(self, "_score_context", None)
    if context is None:
      context = threading.local()
      self._score_context = context
    cache = getattr(context, "components", None)
    if not isinstance(cache, dict):
      cache = {}
      context.components = cache
    return cache

  def get_score_components(
    self,
    query: str,
    doc_id: str,
    recency_weight: float,
    quality_weight: float,
  ) -> Dict[str, float] | None:
    components = self._score_component_cache().get((query, doc_id, recency_weight, quality_weight))
    return dict(components) if components is not None else None

  def add_document(self, doc: Document) -> None:
    vec = _embed_document(self._embedding_service, doc.text)
    self._docs[doc.id] = doc
    self._vectors[doc.id] = vec.astype(np.float32)

  def add_metadata_document(self, doc: Document) -> None:
    self._docs[doc.id] = doc

  def delete_document(self, doc_id: str) -> None:
    self._docs.pop(doc_id, None)
    self._vectors.pop(doc_id, None)

  def list_documents(self) -> List[Document]:
    return list(self._docs.values())

  def rebuild_index(self) -> dict[str, Any]:
    docs = list(self._docs.values())
    self._vectors = {}
    indexed = 0
    skipped = 0
    for doc in docs:
      self._vectors[doc.id] = _embed_document(self._embedding_service, doc.text).astype(np.float32)
      indexed += 1
    return {
      "status": "rebuilt",
      "backend": self.backend_name,
      "document_count": len(docs),
      "indexed_count": indexed,
      "skipped_count": skipped,
    }

  def _doc_matches_filters(
    self,
    doc: Document,
    filters: MemorySearchFilters | None = None,
    memory_types: Sequence[Any] | None = None,
  ) -> bool:
    return is_memory_recallable(doc, filters=filters, memory_types=memory_types)

  def search(
    self,
    query: str,
    top_k: int = 5,
    filters: MemorySearchFilters | None = None,
  ) -> List[Tuple[Document, float]]:
    if not self._docs:
      return []
    active_ids = [doc_id for doc_id, doc in self._docs.items() if self._doc_matches_filters(doc, filters=filters)]
    if not active_ids:
      return []
    q = _embed_query(self._embedding_service, query).astype(np.float32)
    doc_ids = [doc_id for doc_id in active_ids if doc_id in self._vectors]
    if not doc_ids:
      return []
    mats = np.stack([self._vectors[i] for i in doc_ids], axis=0)
    # cosine similarity
    mats_norm = mats / (np.linalg.norm(mats, axis=1, keepdims=True) + 1e-8)
    q_norm = q / (np.linalg.norm(q) + 1e-8)
    scores = mats_norm @ q_norm
    idx = np.argsort(scores)[::-1][: top_k]
    return [
      (self._docs[doc_ids[i]], float(scores[i]))
      for i in idx
    ]

  def search_with_rerank(
    self,
    query: str,
    top_k: int = 5,
    memory_types: Sequence[Any] | None = None,
    recency_weight: float = 0.2,
    quality_weight: float = 0.15,
    filters: MemorySearchFilters | None = None,
  ) -> List[Tuple[Document, float]]:
    """
    Advanced search with type filtering and recency reranking (Task 1.4).

    Args:
      query: Search query text
      top_k: Number of results to return
      memory_types: Filter by memory types (None = all types)
      recency_weight: Weight for recency score (0-1, default 0.2)

    Returns:
      List of (Document, final_score) tuples
    """
    if not self._docs:
      return []

    filtered_ids = []
    for doc_id, doc in self._docs.items():
      if self._doc_matches_filters(doc, filters=filters, memory_types=memory_types):
        filtered_ids.append(doc_id)

    if not filtered_ids:
      return []

    # Semantic search
    vector_ids = [doc_id for doc_id in filtered_ids if doc_id in self._vectors]
    if not vector_ids:
      return []
    q = _embed_query(self._embedding_service, query).astype(np.float32)
    mats = np.stack([self._vectors[i] for i in vector_ids], axis=0)
    mats_norm = mats / (np.linalg.norm(mats, axis=1, keepdims=True) + 1e-8)
    q_norm = q / (np.linalg.norm(q) + 1e-8)
    semantic_scores = mats_norm @ q_norm
    candidate_count = max(top_k, self._reranker_candidate_count)
    semantic_indices = np.argsort(semantic_scores)[::-1][:candidate_count]
    semantic_by_id = {vector_ids[index]: float(semantic_scores[index]) for index in range(len(vector_ids))}
    lexical_ids = sorted(
      vector_ids,
      key=lambda doc_id: lexical_overlap_score(query, self._docs[doc_id].text),
      reverse=True,
    )[:candidate_count]
    candidate_ids = list(dict.fromkeys([vector_ids[int(index)] for index in semantic_indices] + lexical_ids))
    candidate_docs = [self._docs[doc_id] for doc_id in candidate_ids]
    learned_scores = np.zeros(len(candidate_docs), dtype=np.float32)
    learned_enabled = bool(getattr(self._reranker, "enabled", False))
    if learned_enabled and self._reranker is not None:
      try:
        learned_scores = normalize_scores(self._reranker.score(query, [doc.text for doc in candidate_docs]))
      except Exception as exc:
        learned_enabled = False
        logger.warning("Learned memory reranker unavailable; using hybrid scores: %s", exc)

    # Blend semantic relevance with lexical precision and business signals.
    now = datetime.now(timezone.utc)
    scored = []
    score_components = self._score_component_cache()
    score_components.clear()

    for position, doc_id in enumerate(candidate_ids):
      doc = self._docs[doc_id]
      semantic_score = semantic_by_id[doc_id]

      recency_score = memory_recency_score(doc.metadata, now=now)

      quality_score = float(doc.metadata.get("quality_score") or doc.metadata.get("confidence") or 0.6)
      quality_score = max(0.0, min(1.0, quality_score))
      lexical_score = lexical_overlap_score(query, doc.text)
      learned_score = float(learned_scores[position]) if learned_enabled and position < len(learned_scores) else 0.0
      weights = memory_score_weights(
        recency_weight=recency_weight,
        quality_weight=quality_weight,
        learned_enabled=learned_enabled,
      )
      components = memory_score_components(
        semantic=semantic_score,
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
      score_components[(query, doc_id, recency_weight, quality_weight)] = components
      scored.append((final_score, doc, semantic_score))

    # Sort and return top_k
    scored.sort(reverse=True, key=lambda x: x[0])
    return [(doc, final_score) for final_score, doc, _ in scored[:top_k]]

  def get_status(self) -> MemoryBackendStatus:
    metadata: dict[str, Any] = {}
    is_loaded = getattr(self._embedding_service, "is_loaded", None)
    if isinstance(is_loaded, bool):
      metadata["embedding_model_loaded"] = is_loaded
      if is_loaded:
        metadata["embedding_dimension"] = self._embedding_service.dimension
    else:
      metadata["embedding_dimension"] = self._embedding_service.dimension
    return MemoryBackendStatus(
      backend=self.backend_name,
      healthy=True,
      message="In-memory vector store ready",
      document_count=len(self._docs),
      metadata=metadata,
    )
