# pyright: reportUnusedFunction=false

"""FastAPI routes for memory/RAG management.

Week 1 Task 1.3: Added typed memory write with importance filtering.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from functools import wraps
from typing import Any, Callable, Dict, Mapping
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool

from .backend import MemoryBackend, MemorySearchIncompleteError
from .expiry import is_memory_expired, normalize_memory_expiry
from .metadata import (
  append_memory_version,
  has_prior_version_snapshot,
  memory_state,
  normalize_memory_metadata,
  normalize_memory_validity,
  recall_rejection_reason,
)
from .pipeline import RetrievalPipeline
from .schema import MemorySearchFilters, RetrievalRequest
from .vector_store import Document, MemoryType, is_memory_recallable

VALID_MEMORY_LAYERS = {'profile', 'working', 'episodic', 'relationship', 'reflective', 'semantic', 'session'}
VALID_MEMORY_SCOPES = {'global', 'workspace', 'session'}
logger = logging.getLogger(__name__)
SERVER_OWNED_METADATA_FIELDS = frozenset({
  'schema_version',
  'revision',
  'created_at',
  'ingested_at',
  'version_history',
  'version_history_truncated',
  'audit',
  'audit_truncated',
  'confidence_history',
  'correction_history',
  'soft_forgotten',
  'soft_forgotten_at',
  'soft_forget_turn_id',
  'candidate_deleted',
  'candidate_deleted_at',
  'superseded_by',
  'candidate',
  'candidate_id',
  'review_status',
  'review_required',
  'sensitive_category',
  'sensitivity',
  'source_kind',
  'source_id',
  'turn_id',
  'evidence',
})


def _sanitize_create_metadata(metadata: Mapping[str, Any] | None) -> Dict[str, Any]:
  return {
    key: value
    for key, value in (metadata or {}).items()
    if key not in SERVER_OWNED_METADATA_FIELDS
  }


class MemoryDocPayload(BaseModel):
  model_config = ConfigDict(extra='forbid')

  id: str | None = None
  text: str = ''
  metadata: Dict[str, Any] = Field(default_factory=dict)
  scope: str | None = None
  workspace_id: str | None = None
  session_id: str | None = None
  layer: str | None = None
  type: str | None = None
  importance: float | None = None
  confidence: float | None = None
  confidence_source: str | None = None
  source_kind: str | None = None
  source_id: str | None = None
  turn_id: str | None = None
  evidence: Any = None
  confidence_history: list[Dict[str, Any]] | None = None
  dedupe: bool = True
  dedupe_threshold: float = Field(default=0.92, ge=0, le=1)

  @field_validator('scope')
  @classmethod
  def validate_scope(cls, value: str | None) -> str | None:
    return _validate_scope(value)

  @field_validator('layer')
  @classmethod
  def validate_layer(cls, value: str | None) -> str | None:
    return _validate_layer(value)

  @field_validator('importance', 'confidence')
  @classmethod
  def validate_unit(cls, value: float | None) -> float | None:
    return _validate_unit_field(value)


class MemoryDocUpdatePayload(BaseModel):
  model_config = ConfigDict(extra='forbid')

  text: str | None = None
  metadata: Dict[str, Any] = Field(default_factory=dict)
  scope: str | None = None
  workspace_id: str | None = None
  session_id: str | None = None
  layer: str | None = None
  type: str | None = None
  importance: float | None = None
  confidence: float | None = None
  confidence_source: str | None = None
  edit_reason: str | None = None
  turn_id: str | None = None
  evidence: Any = None

  @field_validator('scope')
  @classmethod
  def validate_scope(cls, value: str | None) -> str | None:
    return _validate_scope(value)

  @field_validator('layer')
  @classmethod
  def validate_layer(cls, value: str | None) -> str | None:
    return _validate_layer(value)

  @field_validator('importance', 'confidence')
  @classmethod
  def validate_unit(cls, value: float | None) -> float | None:
    return _validate_unit_field(value)


class MemoryDocBatchDeletePayload(BaseModel):
  model_config = ConfigDict(extra='forbid')

  ids: list[str] = Field(min_length=1, max_length=5000)

  @field_validator('ids')
  @classmethod
  def validate_ids(cls, value: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
      doc_id = str(item or '').strip()
      if not doc_id:
        raise ValueError('ids must not contain empty values')
      if doc_id not in seen:
        cleaned.append(doc_id)
        seen.add(doc_id)
    return cleaned


class MemoryCorrectionPayload(BaseModel):
  model_config = ConfigDict(extra='forbid')
  text: str = Field(min_length=1)
  reason: str | None = None
  turn_id: str | None = None
  evidence: Any = None
  confidence: float | None = None

  @field_validator('confidence')
  @classmethod
  def validate_confidence(cls, value: float | None) -> float | None:
    return _validate_unit_field(value)


class MemorySoftForgetPayload(BaseModel):
  model_config = ConfigDict(extra='forbid')
  reason: str | None = None
  turn_id: str | None = None


class MemoryFeedbackPayload(BaseModel):
  model_config = ConfigDict(extra='forbid')
  feedback: str

  @field_validator('feedback')
  @classmethod
  def validate_feedback(cls, value: str) -> str:
    normalized = str(value or '').strip().lower()
    if normalized not in {'helpful', 'not_helpful', 'incorrect', 'dismissed'}:
      raise ValueError('feedback must be helpful, not_helpful, incorrect, or dismissed')
    return normalized


class MemoryReviewPayload(BaseModel):
  model_config = ConfigDict(extra='forbid')
  decision: str
  reason: str | None = None

  @field_validator('decision')
  @classmethod
  def validate_decision(cls, value: str) -> str:
    normalized = str(value or '').strip().lower()
    if normalized not in {'approve', 'reject'}:
      raise ValueError('decision must be approve or reject')
    return normalized


class MemoryImportPayload(BaseModel):
  model_config = ConfigDict(extra='forbid')

  format: str
  version: int = Field(ge=1)
  docs: list[MemoryDocPayload] = Field(min_length=1, max_length=5000)
  scope: str = 'workspace'
  workspace_id: str | None = None
  session_id: str | None = None
  conflict: str = 'skip'

  @field_validator('format')
  @classmethod
  def validate_format(cls, value: str) -> str:
    if value != 'yuizaki-memory-export':
      raise ValueError('format must be yuizaki-memory-export')
    return value

  @field_validator('scope')
  @classmethod
  def validate_scope(cls, value: str) -> str:
    return _validate_scope(value) or 'workspace'

  @field_validator('conflict')
  @classmethod
  def validate_conflict(cls, value: str) -> str:
    normalized = str(value or '').strip().lower()
    if normalized not in {'skip'}:
      raise ValueError('conflict must be skip')
    return normalized


class MemoryRollbackPayload(BaseModel):
  model_config = ConfigDict(extra='forbid')
  revision: int = Field(ge=1)
  reason: str | None = None


class MemoryMaintenancePayload(BaseModel):
  model_config = ConfigDict(extra='forbid')

  scope: str | None = None
  workspace_id: str | None = None
  session_id: str | None = None
  working_retention_days: int = Field(default=14, ge=1, le=365)
  low_quality_threshold: float = Field(default=0.55, ge=0, le=1)
  include_stale_working: bool = True
  include_low_quality: bool = True
  include_exact_duplicates: bool = True

  @field_validator('scope')
  @classmethod
  def validate_scope(cls, value: str | None) -> str | None:
    return _validate_scope(value)


class MemoryMaintenanceApplyPayload(MemoryMaintenancePayload):
  confirmation: str | None = None
  preview_token: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')


class MemoryAddPayload(BaseModel):
  model_config = ConfigDict(extra='forbid')

  text: str
  type: str | None = None
  layer: str | None = None
  importance: float | None = None
  metadata: Dict[str, Any] = Field(default_factory=dict)
  session_id: str | None = None
  workspace_id: str | None = None
  scope: str | None = None
  confidence: float | None = None
  confidence_source: str | None = None
  source_kind: str | None = None
  source_id: str | None = None
  turn_id: str | None = None
  evidence: Any = None
  confidence_history: list[Dict[str, Any]] | None = None
  dedupe: bool = True
  dedupe_threshold: float = Field(default=0.92, ge=0, le=1)

  @field_validator('scope')
  @classmethod
  def validate_scope(cls, value: str | None) -> str | None:
    return _validate_scope(value)

  @field_validator('layer')
  @classmethod
  def validate_layer(cls, value: str | None) -> str | None:
    return _validate_layer(value)

  @field_validator('importance', 'confidence')
  @classmethod
  def validate_unit(cls, value: float | None) -> float | None:
    return _validate_unit_field(value)


class MemoryRagQueryPayload(BaseModel):
  model_config = ConfigDict(extra='forbid')

  query: str
  top_k: int = Field(default=5, ge=1, le=50)
  memory_types: list[str] | None = None
  recency_weight: float = Field(default=0.2, ge=0, le=1)
  scope: str | None = None
  session_id: str | None = None
  workspace_id: str | None = None
  layers: list[str] | None = None
  expand_relations: bool = True
  relation_limit: int = Field(default=20, ge=0, le=100)
  relation_depth: int = Field(default=1, ge=1, le=3)

  @field_validator('scope')
  @classmethod
  def validate_scope(cls, value: str | None) -> str | None:
    return _validate_scope(value)

  @field_validator('layers')
  @classmethod
  def validate_layers(cls, value: list[str] | None) -> list[str] | None:
    if value is None:
      return None
    layers: list[str] = []
    for item in value:
      layer = _validate_layer(item)
      if layer:
        layers.append(layer)
    return layers


def _payload_dict(payload: BaseModel) -> Dict[str, Any]:
  return payload.model_dump(exclude_none=True)


def _validate_scope(value: str | None) -> str | None:
  if value is None:
    return None
  normalized = value.strip()
  if normalized not in VALID_MEMORY_SCOPES:
    raise ValueError(f"scope must be one of {sorted(VALID_MEMORY_SCOPES)}")
  return normalized


def _validate_layer(value: str | None) -> str | None:
  if value is None:
    return None
  normalized = value.strip()
  if normalized not in VALID_MEMORY_LAYERS:
    raise ValueError(f"layer must be one of {sorted(VALID_MEMORY_LAYERS)}")
  return normalized


def _validate_unit_field(value: float | None) -> float | None:
  if value is None:
    return None
  if value < 0 or value > 1:
    raise ValueError("value must be between 0 and 1")
  return value


def _normalize_optional_workspace_id(value: Any) -> str | None:
  workspace_id = str(value or '').strip()
  return workspace_id or None


def build_memory_metadata(payload: Dict[str, Any], *, layer: str, scope: str, memory_type: str, importance: float) -> Dict[str, Any]:
  now = datetime.now().isoformat()
  metadata = {
    **(payload.get('metadata') or {}),
    'layer': layer,
    'scope': scope,
    'type': memory_type,
    'importance': importance,
    'timestamp': now,
    'session_id': payload.get('session_id'),
    'workspace_id': payload.get('workspace_id'),
  }
  metadata.update(_score_memory_quality(payload, metadata, importance=importance))
  return metadata


def _coerce_importance(value: Any, default: float = 0.5) -> float:
  try:
    return float(value)
  except (TypeError, ValueError):
    return default


def _memory_type_value(value: Any) -> str:
  if isinstance(value, MemoryType):
    return value.value
  raw = str(value or MemoryType.FACT.value).strip()
  if raw.startswith('MemoryType.'):
    return raw.split('.', 1)[1].lower()
  return raw or MemoryType.FACT.value


def _coerce_unit(value: Any, default: float) -> float:
  try:
    number = float(value)
  except (TypeError, ValueError):
    number = default
  return min(1.0, max(0.0, number))


def _score_memory_quality(payload: Dict[str, Any], metadata: Dict[str, Any], *, importance: float) -> Dict[str, Any]:
  explicit_confidence = payload.get('confidence', metadata.get('confidence'))
  source = str(metadata.get('source') or payload.get('source') or 'manual').strip() or 'manual'
  if explicit_confidence is not None:
    confidence = _coerce_unit(explicit_confidence, 0.7)
    confidence_source = str(payload.get('confidence_source') or metadata.get('confidence_source') or 'explicit')
  elif source in {'manual', 'profile', 'relationship', 'reflection'}:
    confidence = 0.86
    confidence_source = 'source'
  elif payload.get('session_id'):
    confidence = 0.68
    confidence_source = 'session'
  else:
    confidence = 0.72
    confidence_source = 'default'

  text = str(payload.get('text') or '')
  completeness = min(1.0, max(0.35, len(text.strip()) / 80.0))
  quality_score = round((_coerce_unit(importance, 0.5) * 0.35) + (confidence * 0.45) + (completeness * 0.2), 3)
  return {
    'confidence': round(confidence, 3),
    'confidence_source': confidence_source,
    'quality_score': quality_score,
  }


def _append_audit(metadata: Dict[str, Any], *, action: str, reason: str | None = None, before: Dict[str, Any] | None = None) -> Dict[str, Any]:
  history = metadata.get('audit')
  audit = list(history) if isinstance(history, list) else []
  event: Dict[str, Any] = {
    'at': datetime.now().isoformat(),
    'action': action,
    'actor': 'memory-api',
  }
  if reason:
    event['reason'] = reason
  if before:
    event['before'] = before
  audit.append(event)
  audit_limit = 100
  truncated_count = max(0, int(metadata.get('audit_truncated', 0) or 0))
  if len(audit) > audit_limit:
    truncated_count += len(audit) - audit_limit
    audit = audit[-audit_limit:]
  metadata['audit'] = audit
  if truncated_count:
    metadata['audit_truncated'] = truncated_count
  else:
    metadata.pop('audit_truncated', None)
  return metadata


def _apply_provenance(metadata: Dict[str, Any], payload: Dict[str, Any], *, preserve: bool = True) -> Dict[str, Any]:
  """Normalize provenance fields while keeping the original origin immutable."""
  keys = ('source_kind', 'source_id', 'turn_id', 'evidence')
  for key in keys:
    value = payload.get(key)
    if value is None and isinstance(payload.get('metadata'), dict):
      value = payload['metadata'].get(key)
    if value is not None and (not preserve or key not in metadata):
      metadata[key] = value
  history = metadata.get('confidence_history')
  if not isinstance(history, list):
    history = []
  supplied = payload.get('confidence_history')
  if isinstance(supplied, list) and not history:
    history = [item for item in supplied if isinstance(item, dict)]
  metadata['confidence_history'] = history[-50:]
  return metadata


def _timestamp_value(metadata: Dict[str, Any]) -> datetime | None:
  raw = metadata.get('updated_at') or metadata.get('timestamp')
  if not isinstance(raw, str) or not raw.strip():
    return None
  normalized = raw.strip().replace('Z', '+00:00')
  try:
    parsed = datetime.fromisoformat(normalized)
  except ValueError:
    return None
  if parsed.tzinfo is None:
    return parsed.replace(tzinfo=timezone.utc)
  return parsed.astimezone(timezone.utc)


def _normalized_memory_text(text: str) -> str:
  return ' '.join(str(text or '').lower().split())


def _candidate_payload(doc: Document, score: float) -> Dict[str, Any]:
  metadata = doc.metadata or {}
  return {
    'id': doc.id,
    'text': doc.text,
    'score': round(float(score), 4),
    'layer': metadata.get('layer'),
    'scope': metadata.get('scope'),
    'type': metadata.get('type'),
    'importance': metadata.get('importance'),
    'confidence': metadata.get('confidence'),
    'quality_score': metadata.get('quality_score'),
  }


def _find_merge_candidates(
  store: MemoryBackend,
  *,
  text: str,
  layer: str,
  scope: str,
  workspace_id: str | None,
  session_id: str | None,
  threshold: float,
  exclude_id: str | None = None,
) -> list[Dict[str, Any]]:
  query = text.strip()
  if not query:
    return []
  filters = MemorySearchFilters(
    scope=scope,
    workspace_id=workspace_id,
    session_id=session_id,
    layers=[layer],
  )
  results = store.search_with_rerank(query=query, top_k=5, filters=filters, quality_weight=0.0, recency_weight=0.0)
  normalized = ' '.join(query.lower().split())
  candidates: list[Dict[str, Any]] = []
  for doc, score in results:
    if exclude_id and doc.id == exclude_id:
      continue
    doc_normalized = ' '.join((doc.text or '').lower().split())
    text_similarity = SequenceMatcher(None, normalized, doc_normalized).ratio() if normalized and doc_normalized else 0.0
    exact = bool(normalized and normalized == doc_normalized)
    if exact or (float(score) >= threshold and text_similarity >= threshold):
      candidate = _candidate_payload(doc, score)
      candidate['text_similarity'] = round(float(text_similarity), 4)
      candidate['match_reason'] = 'exact_text' if exact else 'semantic_and_text'
      candidates.append(candidate)
  return candidates


def _resolve_memory_layer(payload: Dict[str, Any]) -> str:
  explicit = payload.get('layer')
  if isinstance(explicit, str) and explicit.strip() in VALID_MEMORY_LAYERS:
    return explicit.strip()

  memory_type = _memory_type_value(payload.get('type', MemoryType.FACT))
  metadata = payload.get('metadata') or {}
  importance = float(payload.get('importance', 0.5))

  if isinstance(metadata, dict) and metadata.get('source') == 'profile':
    return 'profile'
  if isinstance(metadata, dict) and metadata.get('source') == 'relationship':
    return 'relationship'
  if isinstance(metadata, dict) and metadata.get('source') == 'reflection':
    return 'reflective'
  if memory_type == MemoryType.PREFERENCE:
    return 'profile'
  if memory_type == MemoryType.EVENT:
    return 'episodic'
  if payload.get('session_id'):
    return 'working'
  if importance >= 0.8:
    return 'semantic'
  return 'semantic'


def route_memory_write(
  *,
  text: str,
  memory_type: str,
  importance: float,
  session_id: str | None,
  workspace_id: str | None,
  metadata: Dict[str, Any] | None = None,
  explicit_layer: str | None = None,
  explicit_scope: str | None = None,
) -> Dict[str, Any]:
  payload: Dict[str, Any] = {
    'text': text,
    'type': memory_type,
    'importance': importance,
    'session_id': session_id,
    'workspace_id': workspace_id,
    'metadata': metadata or {},
  }
  if explicit_layer:
    payload['layer'] = explicit_layer
  if explicit_scope:
    payload['scope'] = explicit_scope
  layer = _resolve_memory_layer(payload)
  scope = _resolve_memory_scope(payload)
  return {
    'layer': layer,
    'scope': scope,
    'metadata': build_memory_metadata(payload, layer=layer, scope=scope, memory_type=memory_type, importance=importance),
  }


def _resolve_memory_scope(payload: Dict[str, Any]) -> str:
  explicit = payload.get('scope')
  if isinstance(explicit, str) and explicit.strip() in VALID_MEMORY_SCOPES:
    return explicit.strip()

  if payload.get('session_id'):
    return 'session'
  if payload.get('workspace_id'):
    return 'workspace'
  return 'global'


@dataclass
class MemoryIndexRebuildJob:
  job_id: str
  state: str
  phase: str
  total_count: int
  processed_count: int = 0
  started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
  updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
  finished_at: str | None = None
  last_error: str | None = None
  recoverable: bool = False
  retry_of: str | None = None
  result: Dict[str, Any] | None = None
  index_generation: str | None = None
  snapshot_revision: int | None = None
  cursor_key: str | None = None
  embedding_config_revision: str | None = None

  @classmethod
  def from_snapshot(cls, snapshot: Mapping[str, Any]) -> "MemoryIndexRebuildJob":
    return cls(
      job_id=str(snapshot.get("job_id") or ""),
      state=str(snapshot.get("state") or "unknown"),
      phase=str(snapshot.get("phase") or "unknown"),
      total_count=max(0, int(snapshot.get("total_count") or 0)),
      processed_count=max(0, int(snapshot.get("processed_count") or 0)),
      started_at=str(snapshot.get("started_at") or datetime.now(timezone.utc).isoformat()),
      updated_at=str(snapshot.get("updated_at") or datetime.now(timezone.utc).isoformat()),
      finished_at=str(snapshot["finished_at"]) if snapshot.get("finished_at") else None,
      last_error=str(snapshot["last_error"]) if snapshot.get("last_error") else None,
      recoverable=bool(snapshot.get("recoverable")),
      retry_of=str(snapshot["retry_of"]) if snapshot.get("retry_of") else None,
      result=dict(snapshot["result"]) if isinstance(snapshot.get("result"), Mapping) else None,
      index_generation=(
        str(snapshot["index_generation"])
        if snapshot.get("index_generation")
        else None
      ),
      snapshot_revision=(
        int(snapshot["snapshot_revision"])
        if snapshot.get("snapshot_revision") is not None
        else None
      ),
      cursor_key=str(snapshot["cursor_key"]) if snapshot.get("cursor_key") else None,
      embedding_config_revision=(
        str(snapshot["embedding_config_revision"])
        if snapshot.get("embedding_config_revision")
        else None
      ),
    )

  def snapshot(self) -> Dict[str, Any]:
    return {
      "job_id": self.job_id,
      "state": self.state,
      "phase": self.phase,
      "processed_count": self.processed_count,
      "total_count": self.total_count,
      "started_at": self.started_at,
      "updated_at": self.updated_at,
      "finished_at": self.finished_at,
      "last_error": self.last_error,
      "recoverable": self.recoverable,
      "retry_of": self.retry_of,
      "result": self.result,
      "index_generation": self.index_generation,
      "snapshot_revision": self.snapshot_revision,
      "cursor_key": self.cursor_key,
      "embedding_config_revision": self.embedding_config_revision,
    }


@dataclass
class MemoryState:
  """In-memory state for documents and vector index."""

  store: MemoryBackend
  pipeline: RetrievalPipeline | None = None
  status: str = "idle"   # idle | indexing | error
  io_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
  mutation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
  rebuild_job: MemoryIndexRebuildJob | None = None
  rebuild_task: asyncio.Task[Any] | None = field(default=None, repr=False)
  rebuild_cancel_event: threading.Event | None = field(default=None, repr=False)
  rebuild_launch_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


def create_memory_router(
  state: MemoryState,
  get_active_workspace_id: Callable[[], str] | None = None,
  clear_memory_references: Callable[[list[str]], int] | None = None,
  count_memory_references: Callable[[list[str]], int] | None = None,
) -> APIRouter:
  router = APIRouter(prefix="/memory", tags=["memory"])

  def _persist_rebuild_job(job: MemoryIndexRebuildJob) -> None:
    persist = getattr(state.store, "persist_rebuild_job", None)
    if not callable(persist):
      return
    try:
      persist(job.snapshot())
    except Exception as exc:
      logger.warning("Failed to persist memory index rebuild job %s: %s", job.job_id, exc)

  if state.rebuild_job is None:
    load = getattr(state.store, "load_latest_rebuild_job", None)
    if callable(load):
      try:
        persisted = load()
        if isinstance(persisted, Mapping) and persisted.get("job_id"):
          restored_job = MemoryIndexRebuildJob.from_snapshot(persisted)
          if restored_job.state in {"queued", "running", "cancelling"}:
            restored_job.state = "interrupted"
            restored_job.phase = "interrupted"
            restored_job.finished_at = datetime.now(timezone.utc).isoformat()
            restored_job.updated_at = restored_job.finished_at
            restored_job.last_error = "memory service restarted before index rebuild completed"
            restored_job.recoverable = True
            state.status = "error"
            mark_dirty = getattr(state.store, "mark_index_dirty", None)
            if callable(mark_dirty):
              mark_dirty()
            _persist_rebuild_job(restored_job)
          elif restored_job.state in {"failed", "interrupted"}:
            state.status = "error"
            mark_dirty = getattr(state.store, "mark_index_dirty", None)
            if callable(mark_dirty):
              mark_dirty()
          state.rebuild_job = restored_job
      except Exception as exc:
        logger.warning("Failed to restore memory index rebuild state: %s", exc)

  def _active_workspace_id() -> str | None:
    if get_active_workspace_id is None:
      return None
    return _normalize_optional_workspace_id(get_active_workspace_id()) or 'default'

  def _resolve_request_workspace_id(
    requested_workspace_id: Any,
    *,
    scope: str | None,
    default_for_workspace_scope: bool = False,
  ) -> str | None:
    requested = _normalize_optional_workspace_id(requested_workspace_id)
    active = _active_workspace_id()
    if active and requested and requested != active:
      raise HTTPException(
        status_code=403,
        detail={
          "error": "workspace_mismatch",
          "message": "Memory workspace does not match the active workspace",
          "active_workspace_id": active,
          "requested_workspace_id": requested,
        },
      )
    if active and not requested and scope == 'workspace' and default_for_workspace_scope:
      return active
    return requested

  def _ensure_doc_in_active_workspace(doc: Document) -> None:
    active = _active_workspace_id()
    if not active:
      return
    metadata = doc.metadata or {}
    doc_workspace_id = _normalize_optional_workspace_id(metadata.get('workspace_id'))
    if doc_workspace_id and doc_workspace_id != active:
      raise HTTPException(
        status_code=403,
        detail={
          "error": "workspace_mismatch",
          "message": "Memory document does not belong to the active workspace",
          "active_workspace_id": active,
          "document_workspace_id": doc_workspace_id,
        },
      )

  async def _run_store_call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
      async with state.io_lock:
        return await run_in_threadpool(lambda: fn(*args, **kwargs))
    except MemorySearchIncompleteError as exc:
      raise HTTPException(status_code=503, detail=exc.to_detail()) from exc

  def _serialized_mutation(handler: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(handler)
    async def wrapped(*args: Any, **kwargs: Any) -> Any:
      async with state.mutation_lock:
        return await handler(*args, **kwargs)

    return wrapped

  async def _delete_memory_documents(doc_ids: list[str]) -> int:
    documents = await _run_store_call(state.store.list_documents)
    candidate_docs = [
      doc for doc in documents
      if doc.id in set(doc_ids) and bool((doc.metadata or {}).get('candidate'))
    ]
    for doc_id in doc_ids:
      await _run_store_call(state.store.delete_document, doc_id)
    # Keep a metadata-only tombstone for review candidates. This is the
    # candidate-specific replay guard; ordinary document deletion remains a
    # physical delete as before.
    for existing in candidate_docs:
      metadata = dict(existing.metadata or {})
      metadata['review_status'] = 'deleted'
      metadata['candidate_deleted'] = True
      metadata['candidate_deleted_at'] = datetime.now(timezone.utc).isoformat()
      _append_audit(metadata, action='delete_candidate', reason='candidate_deleted')
      add_metadata = getattr(state.store, 'add_metadata_document', None)
      writer = add_metadata if callable(add_metadata) else state.store.add_document
      await _run_store_call(
        writer,
        Document(id=existing.id, text=existing.text, metadata=metadata),
      )
    clear_references = clear_memory_references
    if clear_references is None:
      return 0
    return int(await run_in_threadpool(lambda: clear_references(doc_ids)))

  def _normalize_expiry_for_write(metadata: Dict[str, Any]) -> Dict[str, Any]:
    try:
      return normalize_memory_validity(normalize_memory_expiry(metadata, reject_expired=True))
    except ValueError as exc:
      raise HTTPException(status_code=400, detail=str(exc)) from exc

  async def _write_memory_document(doc: Document) -> None:
    metadata = _normalize_expiry_for_write(dict(doc.metadata or {}))
    retired_fields = {'state', 'deleted_at', 'archived_at', 'superseded_at', 'maintenance_reasons'}
    rejected_fields = sorted(retired_fields.intersection(metadata))
    if rejected_fields:
      raise HTTPException(
        status_code=422,
        detail={
          "error": "retired_memory_fields",
          "fields": rejected_fields,
          "message": "Memory lifecycle fields are not supported",
        },
      )
    documents = await _run_store_call(state.store.list_documents)
    existing = next((item for item in documents if item.id == doc.id), None)
    if existing is not None:
      _ensure_doc_in_active_workspace(existing)
    metadata = normalize_memory_metadata(metadata)
    if existing is not None:
      old_revision = int(normalize_memory_metadata(existing.metadata).get('revision', 1))
      if not has_prior_version_snapshot(metadata, revision=old_revision, text=existing.text):
        metadata = append_memory_version(
          doc_id=doc.id,
          old_text=existing.text,
          old_metadata=existing.metadata,
          new_metadata=metadata,
        )
    await _run_store_call(state.store.add_document, Document(id=doc.id, text=doc.text, metadata=metadata))

  async def _compact_storage() -> Dict[str, Any] | None:
    compact_storage = getattr(state.store, 'compact_storage', None)
    if not callable(compact_storage):
      return None
    try:
      return await _run_store_call(compact_storage)
    except Exception as exc:
      return {
        'backend': getattr(state.store, 'backend_name', 'unknown'),
        'status': 'failed',
        'error': type(exc).__name__,
      }

  def _doc_matches_scope(
    doc: Document,
    *,
    scope: str,
    workspace_id: str | None,
    session_id: str | None,
    layer: str | None = None,
  ) -> bool:
    metadata = doc.metadata or {}
    doc_layer = str(metadata.get('layer') or 'semantic')
    doc_scope = str(metadata.get('scope') or 'workspace')
    if layer and doc_layer != layer:
      return False
    if scope == 'global':
      return doc_scope == 'global'
    if scope == 'session':
      return doc_scope == 'session' and bool(session_id) and metadata.get('session_id') == session_id
    if scope == 'workspace':
      if doc_scope != 'workspace':
        return False
      if not workspace_id:
        return metadata.get('workspace_id') is None
      return metadata.get('workspace_id') in (workspace_id, None)
    return False

  def _build_maintenance_plan(
    documents: list[Document],
    payload: MemoryMaintenancePayload,
    *,
    scope: str,
    workspace_id: str | None,
  ) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    working_cutoff = now - timedelta(days=payload.working_retention_days)
    scoped_docs = [
      doc for doc in documents
      if _doc_matches_scope(
        doc,
        scope=scope,
        workspace_id=workspace_id,
        session_id=payload.session_id,
      )
    ]
    candidates: dict[str, Dict[str, Any]] = {}

    def _add_candidate(doc: Document, reason: str) -> None:
      metadata = doc.metadata or {}
      existing = candidates.get(doc.id)
      if existing is None:
        existing = {
          'id': doc.id,
          'text': doc.text,
          'action': 'delete',
          'reasons': [],
          'layer': str(metadata.get('layer') or 'semantic'),
          'importance': _coerce_unit(metadata.get('importance'), 0.5),
          'confidence': _coerce_unit(metadata.get('confidence'), 0.72),
          'quality_score': _coerce_unit(metadata.get('quality_score'), 0.72),
          'updated_at': metadata.get('updated_at') or metadata.get('timestamp'),
        }
        candidates[doc.id] = existing
      if reason not in existing['reasons']:
        existing['reasons'].append(reason)

    for doc in scoped_docs:
      if is_memory_expired(doc.metadata):
        _add_candidate(doc, 'expired')

    if payload.include_stale_working or payload.include_low_quality:
      for doc in scoped_docs:
        metadata = doc.metadata or {}
        layer_value = str(metadata.get('layer') or 'semantic')
        timestamp = _timestamp_value(metadata)
        importance = _coerce_unit(metadata.get('importance'), 0.5)
        quality = _coerce_unit(metadata.get('quality_score'), 0.72)
        protected = metadata.get('protected') is True or layer_value in {'profile', 'relationship'} or importance >= 0.8
        if payload.include_stale_working and layer_value in {'working', 'session'} and timestamp and timestamp <= working_cutoff:
          _add_candidate(doc, 'stale_working')
        if (
          payload.include_low_quality
          and not protected
          and quality <= payload.low_quality_threshold
          and timestamp
          and timestamp <= now - timedelta(days=1)
        ):
          _add_candidate(doc, 'low_quality')

    if payload.include_exact_duplicates:
      duplicate_groups: dict[tuple[str, str], list[Document]] = {}
      for doc in scoped_docs:
        normalized = _normalized_memory_text(doc.text)
        if normalized:
          layer_value = str((doc.metadata or {}).get('layer') or 'semantic')
          duplicate_groups.setdefault((layer_value, normalized), []).append(doc)
      for group in duplicate_groups.values():
        if len(group) < 2:
          continue
        ranked = sorted(
          group,
          key=lambda doc: (
            _coerce_unit((doc.metadata or {}).get('quality_score'), 0.72),
            _coerce_unit((doc.metadata or {}).get('importance'), 0.5),
            (_timestamp_value(doc.metadata or {}) or datetime(1970, 1, 1, tzinfo=timezone.utc)).timestamp(),
          ),
          reverse=True,
        )
        for duplicate in ranked[1:]:
          _add_candidate(duplicate, 'exact_duplicate')

    ordered_candidates = sorted(
      candidates.values(),
      key=lambda item: str(item['id']),
    )
    policy_snapshot = {
      'scope': scope,
      'workspace_id': workspace_id,
      'session_id': payload.session_id,
      'working_retention_days': payload.working_retention_days,
      'low_quality_threshold': payload.low_quality_threshold,
      'include_stale_working': payload.include_stale_working,
      'include_low_quality': payload.include_low_quality,
      'include_exact_duplicates': payload.include_exact_duplicates,
    }
    document_snapshot = [
      {
        'id': doc.id,
        'text': doc.text,
        'metadata': doc.metadata or {},
      }
      for doc in sorted(scoped_docs, key=lambda item: item.id)
    ]
    preview_token = hashlib.sha256(
      json.dumps(
        {
          'policy': policy_snapshot,
          'documents': document_snapshot,
          'candidates': ordered_candidates,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
      ).encode('utf-8')
    ).hexdigest()
    return {
      'status': 'preview',
      'preview_token': preview_token,
      'policy': policy_snapshot,
      'summary': {
        'scanned_count': len(scoped_docs),
        'active_count': len(scoped_docs),
        'delete_count': len(ordered_candidates),
      },
      'candidates': ordered_candidates,
    }

  @router.get("/docs")
  async def list_docs(
    scope: str | None = None,
    workspace_id: str | None = None,
    session_id: str | None = None,
    layer: str | None = None,
    include_state: str = 'active',
  ) -> Dict[str, Any]:
    try:
      resolved_scope = _validate_scope(scope) or 'workspace'
      resolved_layer = _validate_layer(layer) if layer else None
      if include_state not in {'active', 'forgotten', 'all'}:
        raise ValueError('include_state must be active, forgotten, or all')
      resolved_workspace_id = _resolve_request_workspace_id(
        workspace_id,
        scope=resolved_scope,
        default_for_workspace_scope=True,
      )
    except ValueError as exc:
      raise HTTPException(status_code=400, detail=str(exc)) from exc

    documents = await _run_store_call(state.store.list_documents)
    return {
      "docs": [
        doc.__dict__ for doc in documents
        if _doc_matches_scope(
          doc,
          scope=resolved_scope,
          workspace_id=resolved_workspace_id,
          session_id=session_id,
          layer=resolved_layer,
        )
        and (
          include_state == 'all'
          or (include_state == 'forgotten' and memory_state(doc.metadata) == 'forgotten')
          or (include_state == 'active' and memory_state(doc.metadata) == 'active')
        )
      ]
    }

  @router.get("/export")
  async def export_memory(
    scope: str | None = None,
    workspace_id: str | None = None,
    session_id: str | None = None,
    include_state: str = 'active',
  ) -> JSONResponse:
    """Export memory records for an explicit local backup scope.

    The export is intentionally metadata-first and excludes vector/index data;
    the index can be rebuilt from the exported records after restore.
    """
    try:
      resolved_scope = _validate_scope(scope) or 'workspace'
      if include_state not in {'active', 'forgotten', 'all'}:
        raise ValueError('include_state must be active, forgotten, or all')
      resolved_workspace_id = _resolve_request_workspace_id(
        workspace_id,
        scope=resolved_scope,
        default_for_workspace_scope=True,
      )
    except ValueError as exc:
      raise HTTPException(status_code=400, detail=str(exc)) from exc

    documents = await _run_store_call(state.store.list_documents)
    exported_docs = [
      {
        'id': doc.id,
        'text': doc.text,
        'metadata': dict(doc.metadata or {}),
      }
      for doc in documents
      if _doc_matches_scope(
        doc,
        scope=resolved_scope,
        workspace_id=resolved_workspace_id,
        session_id=session_id,
      )
      and (
        include_state == 'all'
        or (include_state == 'forgotten' and memory_state(doc.metadata) == 'forgotten')
        or (include_state == 'active' and memory_state(doc.metadata) == 'active')
      )
    ]
    payload = {
      'format': 'yuizaki-memory-export',
      'version': 1,
      'exported_at': datetime.now(timezone.utc).isoformat(),
      'scope': resolved_scope,
      'workspace_id': resolved_workspace_id,
      'session_id': session_id,
      'include_state': include_state,
      'count': len(exported_docs),
      'docs': exported_docs,
    }
    return JSONResponse(
      content=payload,
      headers={'Content-Disposition': 'attachment; filename="yuizaki-memory-export.json"'},
    )

  @router.get('/overview')
  async def memory_overview(
    scope: str | None = None,
    workspace_id: str | None = None,
    session_id: str | None = None,
  ) -> Dict[str, Any]:
    try:
      resolved_scope = _validate_scope(scope) or 'workspace'
      resolved_workspace_id = _resolve_request_workspace_id(
        workspace_id,
        scope=resolved_scope,
        default_for_workspace_scope=True,
      )
    except ValueError as exc:
      raise HTTPException(status_code=400, detail=str(exc)) from exc
    documents = await _run_store_call(state.store.list_documents)
    scoped = [
      doc for doc in documents
      if _doc_matches_scope(
        doc,
        scope=resolved_scope,
        workspace_id=resolved_workspace_id,
        session_id=session_id,
      )
    ]
    backend_status = await _run_store_call(state.store.get_status)

    def _counts(key_fn: Callable[[Document], str]) -> Dict[str, int]:
      counts: Dict[str, int] = {}
      for document in scoped:
        key = key_fn(document)
        counts[key] = counts.get(key, 0) + 1
      return counts

    latest = sorted(
      (
        {
          'id': doc.id,
          'text': doc.text,
          'updated_at': (doc.metadata or {}).get('updated_at') or (doc.metadata or {}).get('timestamp'),
          'state': memory_state(doc.metadata),
          'layer': (doc.metadata or {}).get('layer') or 'semantic',
          'source': (doc.metadata or {}).get('source_kind') or (doc.metadata or {}).get('source') or 'unknown',
          'action': (
            ((doc.metadata or {}).get('audit') or [{}])[-1].get('action')
            if isinstance((doc.metadata or {}).get('audit'), list)
            and ((doc.metadata or {}).get('audit') or [])
            and isinstance(((doc.metadata or {}).get('audit') or [{}])[-1], dict)
            else None
          ),
        }
        for doc in scoped
      ),
      key=lambda item: str(item.get('updated_at') or ''),
      reverse=True,
    )[:10]
    review_counts = _counts(lambda doc: str((doc.metadata or {}).get('review_status') or 'unreviewed'))
    recallable_count = sum(1 for doc in scoped if recall_rejection_reason(doc.metadata) is None)
    return {
      'total': len(scoped),
      'recallable': recallable_count,
      'by_state': _counts(lambda doc: memory_state(doc.metadata)),
      'by_layer': _counts(lambda doc: str((doc.metadata or {}).get('layer') or 'semantic')),
      'by_source': _counts(
        lambda doc: str((doc.metadata or {}).get('source_kind') or (doc.metadata or {}).get('source') or 'unknown')
      ),
      'by_review_status': review_counts,
      'index_health': {
        'backend': backend_status.backend,
        'healthy': backend_status.healthy,
        'message': backend_status.message,
        'status': state.status,
        'metadata': backend_status.metadata or {},
      },
      'latest_activity': latest,
    }

  @router.post('/import')
  async def import_memory(payload: MemoryImportPayload) -> Dict[str, Any]:
    """Restore safe records from a Yuizaki memory export.

    Imported lifecycle metadata is rebuilt by the normal create path. Terminal
    records are skipped so an export can never revive rejected, deleted, or
    superseded memory entries.
    """
    if payload.version != 1:
      raise HTTPException(status_code=400, detail='unsupported memory export version')
    resolved_workspace_id = _resolve_request_workspace_id(
      payload.workspace_id,
      scope=payload.scope,
      default_for_workspace_scope=True,
    )
    target_workspace_id = resolved_workspace_id if payload.scope == 'workspace' else None
    target_session_id = payload.session_id if payload.scope == 'session' else None
    existing_ids = {
      doc.id for doc in await _run_store_call(state.store.list_documents)
    }
    imported: list[str] = []
    skipped: list[Dict[str, Any]] = []
    restored_count = 0
    for source_doc in payload.docs:
      source_metadata = dict(source_doc.metadata or {})
      source_status = str(source_metadata.get('review_status') or '').strip().lower()
      if source_metadata.get('candidate') or source_status in {'pending', 'rejected', 'deleted', 'superseded'}:
        skipped.append({'id': source_doc.id, 'reason': 'terminal_or_review_candidate'})
        continue
      if source_doc.id and source_doc.id in existing_ids:
        skipped.append({'id': source_doc.id, 'reason': 'id_exists'})
        continue
      imported_payload = MemoryDocPayload(
        id=source_doc.id,
        text=source_doc.text,
        metadata=_sanitize_create_metadata(source_metadata),
        scope=payload.scope,
        workspace_id=target_workspace_id,
        session_id=target_session_id,
        type=source_doc.type,
        layer=source_doc.layer,
        importance=source_doc.importance,
        confidence=source_doc.confidence,
        confidence_source=source_doc.confidence_source,
        source_kind=source_doc.source_kind,
        source_id=source_doc.source_id,
        turn_id=source_doc.turn_id,
        evidence=source_doc.evidence,
        dedupe=False,
      )
      try:
        result = await add_doc(imported_payload)
      except HTTPException as exc:
        skipped.append({'id': source_doc.id, 'reason': 'write_failed', 'detail': exc.detail})
        continue
      if result.get('status') != 'ok':
        skipped.append({'id': source_doc.id, 'reason': str(result.get('status') or 'write_skipped')})
        continue
      imported_id = str(result.get('id') or source_doc.id)
      imported.append(imported_id)
      existing_ids.add(imported_id)
      if source_metadata.get('soft_forgotten'):
        try:
          await soft_forget_doc(imported_id, MemorySoftForgetPayload(reason='memory_import_restore'))
          restored_count += 1
        except HTTPException as exc:
          skipped.append({'id': imported_id, 'reason': 'restore_state_failed', 'detail': exc.detail})
    reason_counts: Dict[str, int] = {}
    for item in skipped:
      reason = str(item.get('reason') or 'unknown')
      reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return {
      'status': 'ok',
      'imported_ids': imported,
      'imported_count': len(imported),
      'skipped': skipped,
      'skipped_count': len(skipped),
      'skipped_reason_counts': reason_counts,
      'restored_soft_forgotten_count': restored_count,
      'effects': {
        'authority_store': 'updated' if imported else 'unchanged',
        'index': 'rebuild_required' if imported else 'unchanged',
        'chat_references': 'preserved',
      },
      'scope': payload.scope,
      'workspace_id': target_workspace_id,
      'session_id': target_session_id,
    }

  @router.post('/maintenance/preview')
  async def preview_memory_maintenance(payload: MemoryMaintenancePayload) -> Dict[str, Any]:
    resolved_scope = payload.scope or 'workspace'
    resolved_workspace_id = _resolve_request_workspace_id(
      payload.workspace_id,
      scope=resolved_scope,
      default_for_workspace_scope=True,
    )
    documents = await _run_store_call(state.store.list_documents)
    return _build_maintenance_plan(
      documents,
      payload,
      scope=resolved_scope,
      workspace_id=resolved_workspace_id,
    )

  @router.post('/maintenance/apply')
  @_serialized_mutation
  async def apply_memory_maintenance(payload: MemoryMaintenanceApplyPayload) -> Dict[str, Any]:
    if payload.confirmation != 'PERMANENT_DELETE':
      raise HTTPException(
        status_code=400,
        detail={
          'error': 'memory_purge_confirmation_required',
          'message': 'confirmation must be PERMANENT_DELETE',
        },
      )
    resolved_scope = payload.scope or 'workspace'
    resolved_workspace_id = _resolve_request_workspace_id(
      payload.workspace_id,
      scope=resolved_scope,
      default_for_workspace_scope=True,
    )
    documents = await _run_store_call(state.store.list_documents)
    plan = _build_maintenance_plan(
      documents,
      payload,
      scope=resolved_scope,
      workspace_id=resolved_workspace_id,
    )
    if payload.preview_token != plan['preview_token']:
      raise HTTPException(
        status_code=409,
        detail={
          'error': 'memory_maintenance_preview_stale',
          'message': 'Memory changed after preview; preview again before applying maintenance',
        },
      )
    purge_ids = [str(item['id']) for item in plan['candidates']]
    cleared_references = await _delete_memory_documents(purge_ids)
    return {
      'status': 'purged',
      'changed_ids': purge_ids,
      'changed_count': len(purge_ids),
      'cleared_message_references': cleared_references,
      'storage': await _compact_storage(),
    }

  @router.post("/docs")
  @_serialized_mutation
  async def add_doc(payload: MemoryDocPayload) -> Dict[str, Any]:
    payload_dict = _payload_dict(payload)
    doc_id = str(payload_dict.get("id") or f"doc_{uuid4().hex}")
    if payload.id is not None:
      documents = await _run_store_call(state.store.list_documents)
      existing = next((doc for doc in documents if doc.id == doc_id), None)
      if existing is not None:
        _ensure_doc_in_active_workspace(existing)
        existing_metadata = dict(existing.metadata or {})
        review_status = str(existing_metadata.get('review_status') or '').strip().lower()
        if (
          existing_metadata.get('candidate')
          or existing_metadata.get('candidate_deleted')
          or existing_metadata.get('candidate_id')
          or existing_metadata.get('review_required')
          or review_status in {'pending', 'approved', 'rejected', 'deleted'}
        ):
          raise HTTPException(
            status_code=409,
            detail={
              'error': 'memory_candidate_id_collision',
              'message': 'Review candidate documents cannot be replaced through the create endpoint',
              'id': doc_id,
              'review_status': review_status or None,
            },
          )
    text = str(payload_dict.get("text") or "")
    metadata = _normalize_expiry_for_write(
      _sanitize_create_metadata(dict(payload_dict.get("metadata") or {}))
    )
    memory_type = _memory_type_value(payload_dict.get("type") or metadata.get("type") or MemoryType.FACT)
    importance = _coerce_importance(payload_dict.get("importance", metadata.get("importance", 0.5)))
    routing_payload = {
      **payload_dict,
      "type": memory_type,
      "importance": importance,
      "metadata": metadata,
    }
    layer = _resolve_memory_layer(routing_payload)
    scope = _resolve_memory_scope(routing_payload)
    workspace_id = _resolve_request_workspace_id(
      payload_dict.get("workspace_id"),
      scope=scope,
      default_for_workspace_scope=True,
    )
    now = datetime.now().isoformat()
    metadata = {
      **metadata,
      "layer": layer,
      "scope": scope,
      "type": memory_type,
      "importance": importance,
      "timestamp": now,
      "session_id": payload_dict.get("session_id"),
      "workspace_id": workspace_id,
    }
    metadata.update(_score_memory_quality({**payload_dict, "text": text}, metadata, importance=importance))
    _apply_provenance(metadata, payload_dict, preserve=False)
    metadata['confidence_history'].append({'at': now, 'confidence': metadata.get('confidence'), 'source': 'create'})
    _append_audit(metadata, action='create')
    if payload.dedupe:
      candidates = await _run_store_call(
        _find_merge_candidates,
        state.store,
        text=text,
        layer=layer,
        scope=scope,
        workspace_id=workspace_id,
        session_id=payload_dict.get("session_id"),
        threshold=_coerce_unit(payload.dedupe_threshold, 0.92),
      )
      if candidates:
        return {"status": "duplicate_candidates", "skipped": True, "id": doc_id, "duplicate_candidates": candidates}
    doc = Document(id=doc_id, text=text, metadata=metadata)
    await _write_memory_document(doc)
    return {"status": "ok", "id": doc_id}

  @router.post("/docs/batch-delete")
  @_serialized_mutation
  async def batch_delete_docs(payload: MemoryDocBatchDeletePayload) -> Dict[str, Any]:
    doc_ids = payload.ids
    documents = await _run_store_call(state.store.list_documents)
    docs_by_id = {doc.id: doc for doc in documents}
    missing_ids = [doc_id for doc_id in doc_ids if doc_id not in docs_by_id]
    if missing_ids:
      raise HTTPException(
        status_code=404,
        detail={
          "error": "memory_documents_not_found",
          "message": "Some memory documents were not found",
          "missing_count": len(missing_ids),
          "ids": missing_ids[:20],
        },
      )

    for doc_id in doc_ids:
      _ensure_doc_in_active_workspace(docs_by_id[doc_id])

    candidate_ids = [doc_id for doc_id in doc_ids if (docs_by_id[doc_id].metadata or {}).get('candidate')]
    hard_delete_ids = [doc_id for doc_id in doc_ids if doc_id not in candidate_ids]
    for doc_id in candidate_ids:
      metadata = dict(docs_by_id[doc_id].metadata or {})
      metadata['review_status'] = 'deleted'
      metadata['candidate_deleted_at'] = datetime.now(timezone.utc).isoformat()
      metadata['candidate_deleted'] = True
      _append_audit(metadata, action='delete_candidate', reason='candidate_deleted')
      await _write_memory_document(Document(id=doc_id, text=docs_by_id[doc_id].text, metadata=metadata))
    cleared_references = await _delete_memory_documents(hard_delete_ids) if hard_delete_ids else 0
    return {
      "status": "deleted",
      "ids": doc_ids,
      "deleted_count": len(doc_ids),
      "cleared_message_references": cleared_references,
      "storage": await _compact_storage(),
    }

  @router.post("/docs/delete-preview")
  async def preview_delete_docs(payload: MemoryDocBatchDeletePayload) -> Dict[str, Any]:
    doc_ids = payload.ids
    documents = await _run_store_call(state.store.list_documents)
    docs_by_id = {doc.id: doc for doc in documents}
    missing_ids = [doc_id for doc_id in doc_ids if doc_id not in docs_by_id]
    if missing_ids:
      raise HTTPException(
        status_code=404,
        detail={
          'error': 'memory_documents_not_found',
          'message': 'Some memory documents were not found',
          'missing_count': len(missing_ids),
          'ids': missing_ids[:20],
        },
      )
    for doc_id in doc_ids:
      _ensure_doc_in_active_workspace(docs_by_id[doc_id])
    candidate_count = sum(1 for doc_id in doc_ids if (docs_by_id[doc_id].metadata or {}).get('candidate'))
    hard_delete_count = len(doc_ids) - candidate_count
    reference_count = 0
    reference_counter = count_memory_references
    if reference_counter is not None and hard_delete_count:
      hard_delete_ids = [doc_id for doc_id in doc_ids if not (docs_by_id[doc_id].metadata or {}).get('candidate')]
      reference_count = int(await run_in_threadpool(lambda: reference_counter(hard_delete_ids)))
    return {
      'status': 'preview',
      'ids': doc_ids,
      'total_count': len(doc_ids),
      'hard_delete_count': hard_delete_count,
      'candidate_tombstone_count': candidate_count,
      'affected_message_count': reference_count,
      'effects': {
        'authority_store': 'delete_or_tombstone',
        'index': 'entries_removed',
        'chat_references': 'cleared' if reference_count else 'unchanged',
        'recoverable': False,
      },
    }

  @router.put("/docs/{doc_id:path}")
  @_serialized_mutation
  async def update_doc(doc_id: str, payload: MemoryDocUpdatePayload) -> Dict[str, Any]:
    payload_dict = _payload_dict(payload)
    documents = await _run_store_call(state.store.list_documents)
    existing = next((doc for doc in documents if doc.id == doc_id), None)
    if existing is None:
      raise HTTPException(status_code=404, detail="memory document not found")
    _ensure_doc_in_active_workspace(existing)

    text = str(payload_dict.get("text") if payload_dict.get("text") is not None else existing.text).strip()
    if not text:
      raise HTTPException(status_code=400, detail="text is required")

    existing_metadata = dict(existing.metadata or {})
    incoming_metadata = dict(payload_dict.get("metadata") or {})
    merged_metadata = {**existing_metadata, **incoming_metadata}
    # Origin, lifecycle, history, and audit state cannot be rewritten by a client update.
    immutable_fields = SERVER_OWNED_METADATA_FIELDS | {
      'source_kind', 'source_id', 'source_ids', 'turn_id', 'evidence',
    }
    for immutable_key in immutable_fields:
      if immutable_key in existing_metadata:
        merged_metadata[immutable_key] = existing_metadata[immutable_key]
      else:
        merged_metadata.pop(immutable_key, None)
    memory_type = _memory_type_value(payload_dict.get("type") or merged_metadata.get("type") or MemoryType.FACT)
    importance = _coerce_importance(payload_dict.get("importance", merged_metadata.get("importance", 0.5)))
    routing_payload = {
      **payload_dict,
      "type": memory_type,
      "importance": importance,
      "layer": payload_dict.get("layer") or merged_metadata.get("layer"),
      "scope": payload_dict.get("scope") or merged_metadata.get("scope"),
      "session_id": payload_dict.get("session_id", merged_metadata.get("session_id")),
      "workspace_id": payload_dict.get("workspace_id", merged_metadata.get("workspace_id")),
      "metadata": merged_metadata,
      "text": text,
    }
    layer = _resolve_memory_layer(routing_payload)
    scope = _resolve_memory_scope(routing_payload)
    workspace_id = _resolve_request_workspace_id(
      routing_payload.get("workspace_id"),
      scope=scope,
      default_for_workspace_scope=True,
    )
    now = datetime.now().isoformat()
    before = {
      "text": existing.text,
      "layer": existing_metadata.get("layer"),
      "scope": existing_metadata.get("scope"),
      "importance": existing_metadata.get("importance"),
    }
    metadata = {
      **merged_metadata,
      "layer": layer,
      "scope": scope,
      "type": memory_type,
      "importance": importance,
      "timestamp": str(merged_metadata.get("timestamp") or now),
      "updated_at": now,
      "session_id": routing_payload.get("session_id"),
      "workspace_id": workspace_id,
    }
    metadata.update(_score_memory_quality(routing_payload, metadata, importance=importance))
    _apply_provenance(metadata, routing_payload, preserve=True)
    if payload_dict.get('confidence') is not None and payload_dict.get('confidence') != existing_metadata.get('confidence'):
      metadata['confidence_history'].append({'at': now, 'confidence': metadata.get('confidence'), 'source': 'update', 'reason': payload.edit_reason})
    if payload.turn_id or payload.evidence is not None:
      correction_history = metadata.get('correction_history')
      corrections = list(correction_history) if isinstance(correction_history, list) else []
      correction: Dict[str, Any] = {
        'at': now,
        'reason': payload.edit_reason or 'memory_update',
      }
      if payload.turn_id:
        correction['turn_id'] = payload.turn_id
      if payload.evidence is not None:
        correction['evidence'] = payload.evidence
      corrections.append(correction)
      metadata['correction_history'] = corrections[-25:]
    _append_audit(metadata, action='update', reason=payload.edit_reason, before=before)

    await _write_memory_document(Document(id=doc_id, text=text, metadata=metadata))
    return {"status": "updated", "id": doc_id, "layer": layer, "scope": scope, "importance": importance}

  @router.post("/memory/add")
  @_serialized_mutation
  async def add_memory(payload: MemoryAddPayload) -> Dict[str, Any]:
    """Add typed memory with importance filtering (Week 1 Task 1.3)"""
    payload_dict = _payload_dict(payload)
    text = payload.text.strip()
    if not text:
      raise HTTPException(status_code=400, detail="text is required")

    memory_type = _memory_type_value(payload_dict.get("type", MemoryType.FACT))
    importance = _coerce_importance(payload_dict.get("importance", 0.5))

    # Filter low-importance memories
    if importance < 0.3:
      return {"skipped": True, "reason": "low_importance", "threshold": 0.3}

    doc_id = str(uuid4())
    layer = _resolve_memory_layer(payload_dict)
    scope = _resolve_memory_scope(payload_dict)
    workspace_id = _resolve_request_workspace_id(
      payload_dict.get('workspace_id'),
      scope=scope,
      default_for_workspace_scope=True,
    )
    routing = route_memory_write(
      text=str(text),
      memory_type=_memory_type_value(memory_type),
      importance=importance,
      session_id=payload_dict.get('session_id'),
      workspace_id=workspace_id,
      metadata=_sanitize_create_metadata(
        payload_dict.get('metadata') if isinstance(payload_dict.get('metadata'), dict) else {}
      ),
      explicit_layer=payload_dict.get('layer') if isinstance(payload_dict.get('layer'), str) else None,
      explicit_scope=payload_dict.get('scope') if isinstance(payload_dict.get('scope'), str) else None,
    )
    layer = routing['layer']
    scope = routing['scope']
    metadata = routing['metadata']
    metadata = _normalize_expiry_for_write(metadata)
    _apply_provenance(metadata, payload_dict, preserve=False)
    metadata['confidence_history'].append({'at': metadata.get('timestamp'), 'confidence': metadata.get('confidence'), 'source': 'create'})
    _append_audit(metadata, action='create')
    if payload.dedupe:
      candidates = await _run_store_call(
        _find_merge_candidates,
        state.store,
        text=str(text),
        layer=layer,
        scope=scope,
        workspace_id=workspace_id,
        session_id=payload_dict.get('session_id'),
        threshold=_coerce_unit(payload.dedupe_threshold, 0.92),
      )
      if candidates:
        return {
          "status": "duplicate_candidates",
          "skipped": True,
          "reason": "similar_memory_exists",
          "duplicate_candidates": candidates,
          "layer": layer,
          "scope": scope,
          "importance": importance,
        }

    doc = Document(id=doc_id, text=text, metadata=metadata)
    await _write_memory_document(doc)

    return {"status": "ok", "id": doc_id, "type": memory_type, "layer": layer, "scope": scope, "importance": importance}

  @router.delete("/docs/{doc_id:path}")
  @_serialized_mutation
  async def delete_doc(doc_id: str) -> Dict[str, Any]:
    documents = await _run_store_call(state.store.list_documents)
    existing = next((doc for doc in documents if doc.id == doc_id), None)
    if existing is None:
      raise HTTPException(status_code=404, detail="memory document not found")
    _ensure_doc_in_active_workspace(existing)
    if (existing.metadata or {}).get('candidate'):
      metadata = dict(existing.metadata or {})
      metadata['review_status'] = 'deleted'
      # Candidate deletion keeps a small tombstone so replaying the same
      # deterministic candidate id cannot recreate the rejected record. Use
      # candidate-specific lifecycle keys; legacy ``deleted_at`` is rejected
      # by the normal write contract and remains reserved for old payloads.
      metadata['candidate_deleted_at'] = datetime.now(timezone.utc).isoformat()
      metadata['candidate_deleted'] = True
      _append_audit(metadata, action='delete_candidate', reason='candidate_deleted')
      await _write_memory_document(Document(id=doc_id, text=existing.text, metadata=metadata))
      return {
        'status': 'deleted',
        'id': doc_id,
        'tombstone': True,
        'cleared_message_references': 0,
      }
    cleared_references = await _delete_memory_documents([doc_id])
    return {
      "status": "deleted",
      "id": doc_id,
      "cleared_message_references": cleared_references,
      "storage": await _compact_storage(),
    }

  @router.post("/docs/{doc_id:path}/feedback")
  @_serialized_mutation
  async def feedback_doc(doc_id: str, payload: MemoryFeedbackPayload) -> Dict[str, Any]:
    """Record recall feedback without changing memory text or revision."""
    documents = await _run_store_call(state.store.list_documents)
    existing = next((doc for doc in documents if doc.id == doc_id), None)
    if existing is None:
      raise HTTPException(status_code=404, detail="memory document not found")
    _ensure_doc_in_active_workspace(existing)
    metadata = dict(existing.metadata or {})
    summary = metadata.get('recall_feedback')
    summary = dict(summary) if isinstance(summary, dict) else {}
    counts = summary.get('summary') or summary.get('counts')
    counts = dict(counts) if isinstance(counts, dict) else {}
    counts[payload.feedback] = int(counts.get(payload.feedback, 0) or 0) + 1
    summary['summary'] = {str(key): max(0, int(value or 0)) for key, value in counts.items()}
    summary.pop('counts', None)
    events = summary.get('events')
    events = list(events) if isinstance(events, list) else []
    events.append({'feedback': payload.feedback, 'at': datetime.now(timezone.utc).isoformat()})
    summary['events'] = events[-50:]
    metadata['recall_feedback'] = summary
    updater = getattr(state.store, 'update_metadata', None)
    if not callable(updater):
      raise HTTPException(status_code=501, detail='memory backend does not support metadata feedback')
    await _run_store_call(updater, doc_id, metadata)
    return {'status': 'recorded', 'id': doc_id, 'feedback': payload.feedback, 'counts': summary['summary']}

  @router.post("/docs/{doc_id:path}/correction")
  async def correct_doc(doc_id: str, payload: MemoryCorrectionPayload) -> Dict[str, Any]:
    """Apply a conversational correction while retaining origin provenance and audit history."""
    result = await update_doc(doc_id, MemoryDocUpdatePayload(
      text=payload.text.strip(),
      edit_reason=payload.reason or 'conversational_correction',
      turn_id=payload.turn_id,
      evidence=payload.evidence,
      confidence=payload.confidence,
    ))
    result['action'] = 'correction'
    return result

  @router.post("/docs/{doc_id:path}/review")
  @_serialized_mutation
  async def review_doc(doc_id: str, payload: MemoryReviewPayload) -> Dict[str, Any]:
    """Approve or reject a review-only candidate without changing provenance."""
    documents = await _run_store_call(state.store.list_documents)
    existing = next((doc for doc in documents if doc.id == doc_id), None)
    if existing is None:
      raise HTTPException(status_code=404, detail="memory document not found")
    _ensure_doc_in_active_workspace(existing)
    metadata = dict(existing.metadata or {})
    if not metadata.get('candidate'):
      raise HTTPException(status_code=409, detail="memory document is not a review candidate")
    review_status = str(metadata.get('review_status') or '').lower()
    if metadata.get('candidate_deleted') or review_status in {'deleted', 'rejected'}:
      detail = "deleted memory candidate cannot be reviewed" if review_status == 'deleted' or metadata.get('candidate_deleted') else "rejected memory candidate cannot be reviewed"
      raise HTTPException(status_code=409, detail=detail)
    now = datetime.now(timezone.utc).isoformat()
    metadata['review_status'] = 'approved' if payload.decision == 'approve' else 'rejected'
    metadata['reviewed_at'] = now
    metadata['review_reason'] = payload.reason
    _append_audit(metadata, action=f"review_{payload.decision}", reason=payload.reason)
    await _write_memory_document(Document(id=doc_id, text=existing.text, metadata=metadata))
    return {'status': metadata['review_status'], 'id': doc_id}

  @router.get("/candidates")
  async def list_memory_candidates(
    status: str | None = None,
    scope: str | None = None,
    workspace_id: str | None = None,
    session_id: str | None = None,
  ) -> Dict[str, Any]:
    """List review candidates for the active memory scope.

    Candidates are separate from recallable documents. The UI must not infer
    review state from confidence alone because low-quality active memories and
    review-only candidates have different lifecycle rules.
    """
    requested = str(status or 'pending').strip().lower()
    if requested not in {'pending', 'approved', 'rejected', 'deleted', 'all'}:
      raise HTTPException(status_code=400, detail='unsupported candidate status')
    try:
      resolved_scope = _validate_scope(scope) if scope else None
      resolved_workspace_id = _resolve_request_workspace_id(
        workspace_id,
        scope=resolved_scope,
        default_for_workspace_scope=resolved_scope == 'workspace',
      )
    except ValueError as exc:
      raise HTTPException(status_code=400, detail=str(exc)) from exc

    documents = await _run_store_call(state.store.list_documents)
    items: list[Dict[str, Any]] = []
    for doc in documents:
      metadata = dict(doc.metadata or {})
      if not metadata.get('candidate'):
        continue
      review_status = str(metadata.get('review_status') or 'pending').lower()
      if requested != 'all' and review_status != requested:
        continue
      if resolved_scope is None:
        try:
          _ensure_doc_in_active_workspace(doc)
        except HTTPException:
          continue
      elif not _doc_matches_scope(
          doc,
          scope=resolved_scope,
          workspace_id=resolved_workspace_id,
          session_id=session_id,
        ):
          continue
      items.append({'id': doc.id, 'text': doc.text, 'metadata': metadata})
    return {'status': 'ok', 'candidates': items, 'count': len(items)}

  @router.post("/docs/{doc_id:path}/soft-forget")
  @_serialized_mutation
  async def soft_forget_doc(doc_id: str, payload: MemorySoftForgetPayload) -> Dict[str, Any]:
    """Hide a memory without deleting its immutable record or provenance."""
    documents = await _run_store_call(state.store.list_documents)
    existing = next((doc for doc in documents if doc.id == doc_id), None)
    if existing is None:
      raise HTTPException(status_code=404, detail="memory document not found")
    _ensure_doc_in_active_workspace(existing)
    metadata = dict(existing.metadata or {})
    now = datetime.now().isoformat()
    metadata['soft_forgotten'] = True
    metadata['soft_forgotten_at'] = now
    if payload.turn_id:
      metadata['soft_forget_turn_id'] = payload.turn_id
    _append_audit(metadata, action='soft_forget', reason=payload.reason or 'conversational_soft_forget', before={'text': existing.text})
    await _write_memory_document(Document(id=doc_id, text=existing.text, metadata=metadata))
    return {'status': 'soft_forgotten', 'id': doc_id, 'action': 'soft_forget'}

  @router.post("/docs/{doc_id:path}/restore")
  @_serialized_mutation
  async def restore_doc(doc_id: str, payload: MemorySoftForgetPayload) -> Dict[str, Any]:
    documents = await _run_store_call(state.store.list_documents)
    existing = next((doc for doc in documents if doc.id == doc_id), None)
    if existing is None:
      raise HTTPException(status_code=404, detail="memory document not found")
    _ensure_doc_in_active_workspace(existing)
    metadata = dict(existing.metadata or {})
    if not metadata.get('soft_forgotten'):
      return {'status': 'active', 'id': doc_id, 'action': 'restore', 'changed': False}
    metadata.pop('soft_forgotten', None)
    metadata.pop('soft_forgotten_at', None)
    metadata.pop('soft_forget_turn_id', None)
    _append_audit(metadata, action='restore', reason=payload.reason or 'memory_restore')
    await _write_memory_document(Document(id=doc_id, text=existing.text, metadata=metadata))
    return {'status': 'active', 'id': doc_id, 'action': 'restore', 'changed': True}

  @router.post("/docs/{doc_id:path}/rollback")
  @_serialized_mutation
  async def rollback_doc(doc_id: str, payload: MemoryRollbackPayload) -> Dict[str, Any]:
    """Restore a retained snapshot by appending a new revision."""
    documents = await _run_store_call(state.store.list_documents)
    existing = next((doc for doc in documents if doc.id == doc_id), None)
    if existing is None:
      raise HTTPException(status_code=404, detail="memory document not found")
    _ensure_doc_in_active_workspace(existing)

    current_metadata = normalize_memory_metadata(existing.metadata)
    current_revision = int(current_metadata.get("revision", 1))
    if payload.revision == current_revision:
      return {
        "status": "active",
        "id": doc_id,
        "action": "rollback",
        "changed": False,
        "revision": current_revision,
      }

    history = current_metadata.get("version_history")
    snapshots = history if isinstance(history, list) else []
    snapshot = next(
      (
        item for item in reversed(snapshots)
        if isinstance(item, dict) and item.get("revision") == payload.revision
      ),
      None,
    )
    if snapshot is None or not isinstance(snapshot.get("metadata"), dict):
      raise HTTPException(
        status_code=404,
        detail={
          "error": "memory_revision_not_found",
          "revision": payload.revision,
          "retained_revisions": [
            item.get("revision") for item in snapshots if isinstance(item, dict)
          ],
          "truncated_count": int(current_metadata.get("version_history_truncated", 0) or 0),
        },
      )

    restored_text = str(snapshot.get("text") or "").strip()
    if not restored_text:
      raise HTTPException(status_code=409, detail="memory revision contains no text")
    restored_metadata = dict(snapshot["metadata"])
    restored_metadata["version_history"] = snapshots
    if current_metadata.get("version_history_truncated"):
      restored_metadata["version_history_truncated"] = current_metadata["version_history_truncated"]
    for history_key in ("audit", "confidence_history", "correction_history"):
      if history_key in current_metadata:
        restored_metadata[history_key] = current_metadata[history_key]
    for lifecycle_key in (
      "soft_forgotten", "soft_forgotten_at", "soft_forget_turn_id", "superseded_by",
      "candidate_deleted", "candidate_deleted_at",
    ):
      if lifecycle_key in current_metadata:
        restored_metadata[lifecycle_key] = current_metadata[lifecycle_key]
    current_review_status = str(current_metadata.get("review_status") or "").strip().lower()
    if current_review_status in {"deleted", "rejected"}:
      restored_metadata["review_status"] = current_review_status
      for review_key in ("reviewed_at", "review_reason"):
        if review_key in current_metadata:
          restored_metadata[review_key] = current_metadata[review_key]
    _append_audit(
      restored_metadata,
      action="rollback",
      reason=payload.reason or "user_requested_rollback",
      before={"revision": current_revision, "text": existing.text},
    )
    await _write_memory_document(Document(id=doc_id, text=restored_text, metadata=restored_metadata))
    return {
      "status": "rolled_back",
      "id": doc_id,
      "action": "rollback",
      "changed": True,
      "restored_revision": payload.revision,
      "revision": current_revision + 1,
    }

  def _touch_rebuild_job(job: MemoryIndexRebuildJob) -> None:
    job.updated_at = datetime.now(timezone.utc).isoformat()
    _persist_rebuild_job(job)

  def _rebuild_progress(processed: int, total: int, phase: str) -> None:
    job = state.rebuild_job
    if job is None:
      return
    normalized_phase = str(phase or "indexing")
    if normalized_phase in {"indexing", "complete"}:
      job.processed_count = max(job.processed_count, int(processed), 0)
      job.total_count = max(job.total_count, job.processed_count, int(total))
    job.phase = normalized_phase
    _touch_rebuild_job(job)

  def _rebuild_checkpoint(cursor_key: str, processed: int, total: int, phase: str) -> None:
    job = state.rebuild_job
    if job is None:
      return
    job.cursor_key = str(cursor_key) or None
    job.processed_count = max(job.processed_count, int(processed), 0)
    job.total_count = max(job.total_count, job.processed_count, int(total))
    job.phase = str(phase or "indexing")
    _touch_rebuild_job(job)

  def _invoke_index_rebuild(
    job: MemoryIndexRebuildJob,
    cancel_event: threading.Event,
  ) -> Dict[str, Any]:
    rebuild = state.store.rebuild_index
    parameters = inspect.signature(rebuild).parameters
    kwargs: Dict[str, Any] = {}
    if "progress_callback" in parameters:
      kwargs["progress_callback"] = _rebuild_progress
    if "should_cancel" in parameters:
      kwargs["should_cancel"] = cancel_event.is_set
    if "checkpoint_callback" in parameters:
      kwargs["checkpoint_callback"] = _rebuild_checkpoint
    for name, value in (
      ("snapshot_revision", job.snapshot_revision),
      ("index_generation", job.index_generation),
      ("cursor_key", job.cursor_key),
      ("embedding_config_revision", job.embedding_config_revision),
      ("processed_count", job.processed_count),
    ):
      if name in parameters and value is not None:
        kwargs[name] = value
    return rebuild(**kwargs)

  async def _run_index_rebuild_job(job: MemoryIndexRebuildJob, cancel_event: threading.Event) -> None:
    job.state = "running"
    job.phase = "indexing"
    _touch_rebuild_job(job)
    try:
      result = await run_in_threadpool(lambda: _invoke_index_rebuild(job, cancel_event))
      if cancel_event.is_set() or str(result.get("status", "")).lower() == "cancelled":
        job.state = "cancelled"
        job.phase = "cancelled"
        job.recoverable = True
        state.status = "idle"
      else:
        job.result = dict(result)
        job.processed_count = int(result.get("indexed_count", job.processed_count))
        job.total_count = int(result.get("document_count", job.total_count))
        job.state = "completed"
        job.phase = "completed"
        job.recoverable = False
        state.status = "idle"
    except asyncio.CancelledError:
      cancel_event.set()
      job.state = "interrupted"
      job.phase = "interrupted"
      job.last_error = "memory service stopped while rebuilding the index"
      job.recoverable = True
      state.status = "error"
      raise
    except Exception as exc:
      cancelled = cancel_event.is_set() or exc.__class__.__name__ == "MemoryIndexRebuildCancelled"
      job.state = "cancelled" if cancelled else "failed"
      job.phase = job.state
      job.last_error = None if cancelled else str(exc)
      job.recoverable = True
      state.status = "idle" if cancelled else "error"
    finally:
      job.finished_at = datetime.now(timezone.utc).isoformat()
      _touch_rebuild_job(job)

  async def _start_index_rebuild(*, retry_of: str | None = None) -> Dict[str, Any]:
    async with state.rebuild_launch_lock:
      if state.rebuild_task is not None and not state.rebuild_task.done():
        current = state.rebuild_job
        return {
          "status": "indexing",
          "index_status": state.status,
          "job": current.snapshot() if current else None,
        }

      documents = await _run_store_call(state.store.list_documents)
      checkpoint_context: Mapping[str, Any] | None = None
      get_checkpoint_context = getattr(state.store, "get_rebuild_checkpoint_context", None)
      if callable(get_checkpoint_context):
        resolved_context = await _run_store_call(get_checkpoint_context)
        if isinstance(resolved_context, Mapping):
          checkpoint_context = resolved_context

      previous_job = state.rebuild_job if retry_of else None
      snapshot_revision: int | None = None
      embedding_config_revision: str | None = None
      index_generation: str | None = None
      cursor_key: str | None = None
      processed_count = 0
      if checkpoint_context is not None:
        snapshot_revision = int(checkpoint_context["snapshot_revision"])
        embedding_config_revision = str(checkpoint_context["embedding_config_revision"])
        resumable_job = previous_job if (
          previous_job is not None
          and checkpoint_context.get("durable_resume")
          and previous_job.index_generation
          and previous_job.snapshot_revision == snapshot_revision
          and previous_job.embedding_config_revision == embedding_config_revision
        ) else None
        if resumable_job is not None:
          index_generation = resumable_job.index_generation
          cursor_key = resumable_job.cursor_key
          processed_count = resumable_job.processed_count
        else:
          index_generation = uuid4().hex

      job = MemoryIndexRebuildJob(
        job_id=uuid4().hex,
        state="queued",
        phase="queued",
        total_count=len(documents),
        processed_count=processed_count,
        retry_of=retry_of,
        index_generation=index_generation,
        snapshot_revision=snapshot_revision,
        cursor_key=cursor_key,
        embedding_config_revision=embedding_config_revision,
      )
      cancel_event = threading.Event()
      state.rebuild_job = job
      state.rebuild_cancel_event = cancel_event
      state.status = "indexing"
      mark_dirty = getattr(state.store, "mark_index_dirty", None)
      if callable(mark_dirty):
        mark_dirty()
      _persist_rebuild_job(job)
      state.rebuild_task = asyncio.create_task(_run_index_rebuild_job(job, cancel_event))
      return {
        "status": "indexing",
        "index_status": state.status,
        "job": job.snapshot(),
      }

  @router.get("/index/status")
  async def index_status() -> Dict[str, Any]:
    backend_status = await _run_store_call(state.store.get_status)
    documents = await _run_store_call(state.store.list_documents)
    recallable_count = sum(1 for document in documents if is_memory_recallable(document))
    metadata = dict(backend_status.metadata or {})
    metadata.update({
      "document_count": len(documents),
      "recallable_count": recallable_count,
      "rebuild_job": state.rebuild_job.snapshot() if state.rebuild_job else None,
    })
    return {
      "status": state.status,
      "count": len(documents),
      "backend": backend_status.backend,
      "healthy": backend_status.healthy,
      "message": backend_status.message,
      "metadata": metadata,
      "job": state.rebuild_job.snapshot() if state.rebuild_job else None,
    }

  @router.post("/index/rebuild")
  async def rebuild_index() -> Dict[str, Any]:
    return await _start_index_rebuild()

  @router.get("/index/rebuild/{job_id}")
  async def rebuild_index_job(job_id: str) -> Dict[str, Any]:
    job = state.rebuild_job
    if job is None or job.job_id != job_id:
      raise HTTPException(status_code=404, detail="memory index rebuild job not found")
    return {"status": job.state, "index_status": state.status, "job": job.snapshot()}

  @router.post("/index/rebuild/{job_id}/cancel")
  async def cancel_rebuild_index_job(job_id: str) -> Dict[str, Any]:
    job = state.rebuild_job
    if job is None or job.job_id != job_id:
      raise HTTPException(status_code=404, detail="memory index rebuild job not found")
    if job.state not in {"queued", "running", "cancelling"}:
      return {"status": job.state, "index_status": state.status, "job": job.snapshot()}
    if state.rebuild_cancel_event is not None:
      state.rebuild_cancel_event.set()
    job.state = "cancelling"
    job.phase = "cancelling"
    job.recoverable = True
    _touch_rebuild_job(job)
    return {"status": "cancelling", "index_status": state.status, "job": job.snapshot()}

  @router.post("/index/rebuild/{job_id}/retry")
  async def retry_rebuild_index_job(job_id: str) -> Dict[str, Any]:
    job = state.rebuild_job
    if job is None or job.job_id != job_id:
      raise HTTPException(status_code=404, detail="memory index rebuild job not found")
    if job.state not in {"cancelled", "failed", "interrupted"}:
      raise HTTPException(status_code=409, detail="memory index rebuild job is not recoverable")
    return await _start_index_rebuild(retry_of=job_id)

  @router.post("/query")
  @router.post("/rag/query")
  async def rag_query(payload: MemoryRagQueryPayload) -> Dict[str, Any]:
    """
    RAG query with optional type filtering and recency reranking (Week 1 Task 1.5).

    Payload:
      - query: str (required)
      - top_k: int (default 5)
      - memory_types: list[str] (optional, e.g., ["fact", "preference"])
      - recency_weight: float (default 0.2, range 0-1)
    """
    query = str(payload.query or "")
    top_k = int(payload.top_k or 5)
    memory_types = payload.memory_types
    recency_weight = float(payload.recency_weight)
    resolved_scope = payload.scope or 'workspace'
    resolved_workspace_id = _resolve_request_workspace_id(
      payload.workspace_id,
      scope=resolved_scope,
      default_for_workspace_scope=True,
    )
    request = RetrievalRequest(
      query=query,
      scope=resolved_scope,
      session_id=payload.session_id,
      workspace_id=resolved_workspace_id,
      top_k=top_k,
      layers=payload.layers or ['profile', 'working', 'episodic', 'relationship', 'reflective', 'semantic'],
      memory_types=memory_types,
      recency_weight=recency_weight,
      relation_expansion=payload.expand_relations,
      relation_limit=payload.relation_limit,
      relation_depth=payload.relation_depth,
    )
    pipeline = state.pipeline or RetrievalPipeline(state.store)
    try:
      result = await run_in_threadpool(pipeline.recall, request)
    except MemorySearchIncompleteError as exc:
      raise HTTPException(status_code=503, detail=exc.to_detail()) from exc
    result["query"] = query
    return result

  return router


def create_memory_pipeline_router(query_handler, get_active_workspace_id: Callable[[], str] | None = None) -> APIRouter:
  router = APIRouter(tags=["memory"])

  def _active_workspace_id() -> str | None:
    if get_active_workspace_id is None:
      return None
    return _normalize_optional_workspace_id(get_active_workspace_id()) or 'default'

  def _resolve_query_workspace_id(workspace_id: str | None, scope: str | None) -> str | None:
    requested = _normalize_optional_workspace_id(workspace_id)
    active = _active_workspace_id()
    if active and requested and requested != active:
      raise HTTPException(
        status_code=403,
        detail={
          "error": "workspace_mismatch",
          "message": "Memory workspace does not match the active workspace",
          "active_workspace_id": active,
          "requested_workspace_id": requested,
        },
      )
    resolved_scope = scope or 'workspace'
    if active and not requested and resolved_scope == 'workspace':
      return active
    return requested

  @router.get("/api/memory/pipeline/query")
  async def memory_pipeline_query(
    query: str,
    session_id: str | None = None,
    workspace_id: str | None = None,
    scope: str | None = None,
    layers: str | None = None,
    top_k: int = 5,
  ):
    resolved_scope = scope or 'workspace'
    resolved_workspace_id = _resolve_query_workspace_id(workspace_id, resolved_scope)
    try:
      return await run_in_threadpool(
        query_handler,
        query=query,
        session_id=session_id,
        workspace_id=resolved_workspace_id,
        scope=resolved_scope,
        layers=layers,
        top_k=top_k,
      )
    except MemorySearchIncompleteError as exc:
      raise HTTPException(status_code=503, detail=exc.to_detail()) from exc

  return router
