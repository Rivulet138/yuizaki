# pyright: reportUnusedFunction=false

"""FastAPI routes for memory/RAG management.

Week 1 Task 1.3: Added typed memory write with importance filtering.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool

from .backend import MemoryBackend, MemorySearchIncompleteError
from .vector_store import Document, MemoryType
from .pipeline import RetrievalPipeline
from .schema import MemorySearchFilters, RetrievalRequest, RetrievalTrace
from .expiry import is_memory_expired, normalize_memory_expiry


VALID_MEMORY_LAYERS = {'profile', 'working', 'episodic', 'relationship', 'reflective', 'semantic', 'session'}
VALID_MEMORY_SCOPES = {'global', 'workspace', 'session'}


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
  metadata['audit'] = audit[-25:]
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
class MemoryState:
  """In-memory state for documents and vector index."""

  store: MemoryBackend
  pipeline: RetrievalPipeline | None = None
  status: str = "idle"   # idle | indexing | error
  io_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def create_memory_router(
  state: MemoryState,
  get_active_workspace_id: Callable[[], str] | None = None,
  clear_memory_references: Callable[[list[str]], int] | None = None,
) -> APIRouter:
  router = APIRouter(prefix="/memory", tags=["memory"])

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

  async def _delete_memory_documents(doc_ids: list[str]) -> int:
    for doc_id in doc_ids:
      await _run_store_call(state.store.delete_document, doc_id)
    if clear_memory_references is None:
      return 0
    return int(await run_in_threadpool(lambda: clear_memory_references(doc_ids)))

  def _normalize_expiry_for_write(metadata: Dict[str, Any]) -> Dict[str, Any]:
    try:
      return normalize_memory_expiry(metadata, reject_expired=True)
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
  ) -> Dict[str, Any]:
    try:
      resolved_scope = _validate_scope(scope) or 'workspace'
      resolved_layer = _validate_layer(layer) if layer else None
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
        and not is_memory_expired(doc.metadata)
      ]
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
  async def add_doc(payload: MemoryDocPayload) -> Dict[str, Any]:
    payload_dict = _payload_dict(payload)
    doc_id = str(payload_dict.get("id") or f"doc_{uuid4().hex}")
    text = str(payload_dict.get("text") or "")
    metadata = _normalize_expiry_for_write(dict(payload_dict.get("metadata") or {}))
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

    cleared_references = await _delete_memory_documents(doc_ids)
    return {
      "status": "deleted",
      "ids": doc_ids,
      "deleted_count": len(doc_ids),
      "cleared_message_references": cleared_references,
      "storage": await _compact_storage(),
    }

  @router.put("/docs/{doc_id:path}")
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
    _append_audit(metadata, action='update', reason=payload.edit_reason, before=before)

    await _write_memory_document(Document(id=doc_id, text=text, metadata=metadata))
    return {"status": "updated", "id": doc_id, "layer": layer, "scope": scope, "importance": importance}

  @router.post("/memory/add")
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
      metadata=payload_dict.get('metadata') if isinstance(payload_dict.get('metadata'), dict) else {},
      explicit_layer=payload_dict.get('layer') if isinstance(payload_dict.get('layer'), str) else None,
      explicit_scope=payload_dict.get('scope') if isinstance(payload_dict.get('scope'), str) else None,
    )
    layer = routing['layer']
    scope = routing['scope']
    metadata = routing['metadata']
    metadata = _normalize_expiry_for_write(metadata)
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
  async def delete_doc(doc_id: str) -> Dict[str, Any]:
    documents = await _run_store_call(state.store.list_documents)
    existing = next((doc for doc in documents if doc.id == doc_id), None)
    if existing is None:
      raise HTTPException(status_code=404, detail="memory document not found")
    _ensure_doc_in_active_workspace(existing)
    cleared_references = await _delete_memory_documents([doc_id])
    return {
      "status": "deleted",
      "id": doc_id,
      "cleared_message_references": cleared_references,
      "storage": await _compact_storage(),
    }

  @router.get("/index/status")
  async def index_status() -> Dict[str, Any]:
    backend_status = await _run_store_call(state.store.get_status)
    documents = await _run_store_call(state.store.list_documents)
    metadata = dict(backend_status.metadata or {})
    metadata.update({
      "document_count": len(documents),
      "recallable_count": len(documents),
    })
    return {
      "status": state.status,
      "count": len(documents),
      "backend": backend_status.backend,
      "healthy": backend_status.healthy,
      "message": backend_status.message,
      "metadata": metadata,
    }

  @router.post("/index/rebuild")
  async def rebuild_index() -> Dict[str, Any]:
    if state.status == "indexing":
      return {"status": "indexing", "index_status": state.status}
    state.status = "indexing"
    try:
      result = await _run_store_call(state.store.rebuild_index)
      state.status = "idle"
      backend_status = await _run_store_call(state.store.get_status)
      return {
        **result,
        "status": result.get("status", "rebuilt"),
        "index_status": state.status,
        "healthy": backend_status.healthy,
        "message": backend_status.message,
        "metadata": backend_status.metadata,
      }
    except Exception as exc:
      state.status = "error"
      raise HTTPException(status_code=500, detail=f"memory index rebuild failed: {exc}") from exc

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
    started = perf_counter()
    resolved_scope = payload.scope or 'workspace'
    resolved_workspace_id = _resolve_request_workspace_id(
      payload.workspace_id,
      scope=resolved_scope,
      default_for_workspace_scope=True,
    )
    filters = MemorySearchFilters(
      scope=resolved_scope,
      session_id=payload.session_id,
      workspace_id=resolved_workspace_id,
      layers=payload.layers,
    )

    if state.pipeline:
      request = RetrievalRequest(
          query=query,
          scope=resolved_scope,
          session_id=payload.session_id,
          workspace_id=resolved_workspace_id,
          top_k=top_k,
          layers=payload.layers or ['profile', 'working', 'episodic', 'relationship', 'reflective', 'semantic'],
          memory_types=memory_types,
          recency_weight=recency_weight,
        )
      try:
        result = await run_in_threadpool(state.pipeline.recall, request)
      except MemorySearchIncompleteError as exc:
        raise HTTPException(status_code=503, detail=exc.to_detail()) from exc
      result["query"] = query
      return result

    if memory_types or recency_weight > 0:
      results = await _run_store_call(
        state.store.search_with_rerank,
        query=query,
        top_k=top_k,
        memory_types=memory_types,
        recency_weight=recency_weight,
        filters=filters,
      )
    else:
      results = await _run_store_call(state.store.search, query, top_k=top_k, filters=filters)

    scores = [float(score) for _, score in results]
    trace = RetrievalTrace(
      query=query,
      scope=resolved_scope,
      session_id=payload.session_id,
      workspace_id=resolved_workspace_id,
      layers=payload.layers or ['profile', 'working', 'episodic', 'relationship', 'reflective', 'semantic'],
      recall_count=len(results),
      selected_ids=[doc.id for doc, _ in results],
      candidate_limit=top_k,
      candidate_count=len(results),
      filtered_count=len(results),
      filtered_out_count=0,
      filter_reasons={},
      top_score=max(scores) if scores else None,
      average_score=(sum(scores) / len(scores)) if scores else None,
      latency_ms=round((perf_counter() - started) * 1000, 3),
      backend_filter_downpushed=True,
    )

    return {
      "query": query,
      "results": [
        {"doc": doc.__dict__, "score": score} for (doc, score) in results
      ],
      "trace": asdict(trace),
    }

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
