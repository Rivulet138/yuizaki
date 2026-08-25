from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, cast
import hashlib

from ..memory.routes import route_memory_write
from ..memory.expiry import normalize_memory_expiry
from ..memory.vector_store import Document


USER_SIGNAL_KIND_SOURCE_MAP: dict[str, str] = {
    "gratitude": "relationship",
    "preference_confirmed": "profile",
    "support_request": "relationship",
    "comfort_event": "relationship",
}

EventWriteRule = dict[str, str | float]

EVENT_WRITE_RULES: dict[str, EventWriteRule] = {
    "gratitude": {"source": "relationship", "default_importance": 0.84},
    "preference_confirmed": {"source": "profile", "default_importance": 0.82},
    "support_request": {"source": "relationship", "default_importance": 0.9},
    "comfort_event": {"source": "relationship", "default_importance": 0.9},
    "tool_success": {"source": "reflection", "default_importance": 0.88},
    "task_completed": {"source": "reflection", "default_importance": 0.82},
    "reflection": {"source": "reflection", "default_importance": 0.8},
    "adjustment": {"source": "reflection", "default_importance": 0.82},
    "strategy_update": {"source": "reflection", "default_importance": 0.84},
    "state_snapshot": {"source": "relationship", "default_importance": 0.85},
    "mood_shift": {"source": "relationship", "default_importance": 0.85},
    "trust_shift": {"source": "relationship", "default_importance": 0.85},
    "care_signal": {"source": "relationship", "default_importance": 0.85},
}

SENSITIVE_CATEGORIES = frozenset({
    "none",
    "identity",
    "health",
    "finance",
    "relationship_boundary",
    "operational",
    "secret",
    "personality",
})
TRUST_LEVELS = frozenset({"untrusted", "verified", "trusted"})
LOW_RISK_ADMISSION_SOURCE_KINDS = frozenset({"builtin", "runtime"})
TOOL_SOURCE_KINDS = frozenset({"builtin", "web", "ocr", "mcp", "plugin"})
AUTOMATIC_MEMORY_EVENT_KINDS = frozenset(EVENT_WRITE_RULES)


def _sensitive_category(value: Any) -> str:
    normalized = str(value or "none").strip().lower()
    if normalized not in SENSITIVE_CATEGORIES:
        raise ValueError(f"unsupported memory sensitivity: {normalized}")
    return normalized


def _trust_level(value: Any, *, default: str) -> str:
    normalized = str(value or default).strip().lower()
    if normalized not in TRUST_LEVELS:
        raise ValueError(f"unsupported memory trust_level: {normalized}")
    return normalized


def classify_tool_source_kind(tool_name: str, tool_source: Any = None) -> str:
    """Preserve the evidence origin instead of flattening every tool event."""
    source = str(tool_source or "builtin").strip().lower()
    if source not in TOOL_SOURCE_KINDS:
        raise ValueError(f"unsupported tool source: {source}")
    if source != "builtin":
        return source
    normalized_name = str(tool_name or "").strip().lower()
    if "ocr" in normalized_name:
        return "ocr"
    if normalized_name == "web_search" or normalized_name.startswith(("web.", "browser.")):
        return "web"
    return "builtin"


def _authoritative_source_kind(
    *,
    event_kind: str,
    payload: dict[str, Any],
    metadata: dict[str, Any],
) -> str:
    """Derive provenance from the local event envelope, not candidate metadata."""
    if event_kind not in AUTOMATIC_MEMORY_EVENT_KINDS:
        raise ValueError(f"unsupported automatic memory event kind: {event_kind}")
    if event_kind != "tool_success":
        return event_kind
    tool_name = str(payload.get("tool_name") or metadata.get("tool_name") or "")
    tool_source = payload.get("tool_source")
    if tool_source is None:
        tool_source = metadata.get("tool_source")
    return classify_tool_source_kind(tool_name, tool_source)


def _default_trust_level(source_kind: str) -> str:
    return "verified" if source_kind in LOW_RISK_ADMISSION_SOURCE_KINDS or source_kind in {
        "task_completed",
        "reflection",
    } else "untrusted"


def _candidate_admission(
    *,
    source_kind: str,
    sensitivity: str,
    trust_level: str,
    allow_low_risk_admission: bool,
) -> dict[str, Any]:
    eligible = (
        allow_low_risk_admission
        and sensitivity == "none"
        and trust_level in {"verified", "trusted"}
        and source_kind in LOW_RISK_ADMISSION_SOURCE_KINDS
    )
    if eligible:
        return {
            "review_status": "approved",
            "review_required": False,
            "low_risk_admission_requested": True,
            "admission_policy": "low_risk_auto",
            "admission_reason": "explicit_low_risk_trusted_source",
        }
    if not allow_low_risk_admission:
        reason = "low_risk_admission_not_requested"
    elif sensitivity != "none":
        reason = "sensitive_memory_requires_review"
    elif trust_level not in {"verified", "trusted"}:
        reason = "untrusted_source_requires_review"
    else:
        reason = "source_not_eligible_for_low_risk_admission"
    return {
        "review_status": "pending",
        "review_required": True,
        "low_risk_admission_requested": allow_low_risk_admission,
        "admission_policy": "manual_review",
        "admission_reason": reason,
    }


def _resolve_sensitivity(*values: Any) -> str:
    supplied = [_sensitive_category(value) for value in values if value not in (None, "")]
    if not supplied:
        return "none"
    # ``none`` is the legacy/default alias. A non-default explicit category
    # overrides that alias, while two concrete categories remain an error.
    concrete = [value for value in supplied if value != "none"]
    if concrete:
        supplied = concrete
    if len(set(supplied)) != 1:
        raise ValueError("conflicting memory sensitivity values")
    return supplied[0]


def _candidate_provenance(
    *,
    kind: str,
    source_id: str | None,
    turn_id: str | None,
    evidence: Any = None,
    sensitive_category: Any = None,
    source_kind: str | None = None,
    trust_level: Any = None,
    allow_low_risk_admission: bool = False,
) -> dict[str, Any]:
    """Build immutable origin metadata for review-only event memories."""
    resolved_source_kind = str(source_kind or kind).strip().lower()
    sensitivity = _sensitive_category(sensitive_category)
    resolved_trust_level = _trust_level(
        trust_level,
        default=_default_trust_level(resolved_source_kind),
    )
    provenance = {
        "event_kind": kind,
        "source_kind": resolved_source_kind,
        "source_id": source_id,
        "turn_id": turn_id,
        "evidence": evidence,
        "candidate": True,
        "trust_level": resolved_trust_level,
        "sensitive_category": sensitivity,
        "sensitivity": sensitivity,
        **_candidate_admission(
            source_kind=resolved_source_kind,
            sensitivity=sensitivity,
            trust_level=resolved_trust_level,
            allow_low_risk_admission=allow_low_risk_admission,
        ),
    }
    return {key: value for key, value in provenance.items() if value is not None}


def candidate_id(*, kind: str, source_id: str | None, turn_id: str | None, text: str, workspace_id: str | None = None) -> str:
    """Return a stable idempotency key for an event candidate."""
    raw = "|".join((workspace_id or "", kind, source_id or "", turn_id or "", text.strip()))
    return "candidate_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def classify_user_signal_kind(text: str) -> tuple[str | None, str | None]:
    lowered = (text or "").lower()
    if any(token in lowered for token in ["谢谢", "thank", "thanks", "辛苦", "多亏你"]):
        return "gratitude", USER_SIGNAL_KIND_SOURCE_MAP["gratitude"]
    if any(token in lowered for token in ["我喜欢", "我更喜欢", "prefer", "更偏好", "下次请"]):
        return "preference_confirmed", USER_SIGNAL_KIND_SOURCE_MAP["preference_confirmed"]
    if any(token in lowered for token in ["帮帮我", "能帮我吗", "我需要你", "support me", "help me"]):
        return "support_request", USER_SIGNAL_KIND_SOURCE_MAP["support_request"]
    if any(token in lowered for token in ["我好累", "我有点难过", "安慰我", "陪陪我", "comfort me"]):
        return "comfort_event", USER_SIGNAL_KIND_SOURCE_MAP["comfort_event"]
    return None, None


def build_user_signal_event(
    text: str,
    *,
    workspace_id: str | None = None,
    turn_id: str | None = None,
) -> dict[str, Any] | None:
    kind, source = classify_user_signal_kind(text)
    if not kind or not source:
        return None
    label_map = {
        "gratitude": "用户表达了感谢",
        "preference_confirmed": "用户表达了偏好",
        "support_request": "用户表达了求助",
        "comfort_event": "用户表达了情绪支持需求",
    }
    return {
        "kind": kind,
        "text": f"{label_map[kind]}：{(text or '')[:80]}",
        "importance": float(cast(float, EVENT_WRITE_RULES.get(kind, {}).get("default_importance", 0.8))),
        "workspace_id": workspace_id,
        "turn_id": turn_id,
        "metadata": {
            "source": source,
            "workspace_id": workspace_id,
            **_candidate_provenance(
                kind=kind,
                source_id=None,
                turn_id=turn_id,
                evidence=text,
            ),
        },
    }


def build_task_completed_event(*, task_name: str, task_id: str, task_mode: str | None, owner_agent_id: str | None, owner_agent_role: str | None, session_id: str | None) -> dict[str, Any]:
    return {
        "text": f"結崎完成了一次任务：{task_name}",
        "kind": "task_completed",
        "importance": float(cast(float, EVENT_WRITE_RULES["task_completed"]["default_importance"])),
        "session_id": session_id,
        "metadata": {
            "source": cast(str, EVENT_WRITE_RULES["task_completed"]["source"]),
            "task_id": task_id,
            "task_mode": task_mode,
            "owner_agent_id": owner_agent_id,
            "owner_agent_role": owner_agent_role,
            **_candidate_provenance(kind="task_completed", source_id=task_id, turn_id=None),
        },
    }


def build_tool_success_event(
    *,
    tool_name: str,
    args: dict[str, Any],
    text: str,
    importance: float,
    owner_agent_id: str | None,
    owner_agent_role: str | None,
    turn_id: str | None = None,
    tool_source: Any = None,
    sensitivity: Any = None,
    trust_level: Any = None,
    allow_low_risk_admission: bool = False,
) -> dict[str, Any]:
    normalized_tool_source = str(tool_source or "builtin").strip().lower()
    source_kind = classify_tool_source_kind(tool_name, normalized_tool_source)
    return {
        "text": text,
        "kind": "tool_success",
        "tool_name": tool_name,
        "tool_source": normalized_tool_source,
        "args": args,
        "importance": importance,
        "metadata": {
            "source": cast(str, EVENT_WRITE_RULES["tool_success"]["source"]),
            "tool_source": normalized_tool_source,
            "owner_agent_id": owner_agent_id,
            "owner_agent_role": owner_agent_role,
            **_candidate_provenance(
                kind="tool_success",
                source_kind=source_kind,
                source_id=tool_name,
                turn_id=turn_id,
                evidence=args,
                sensitive_category=sensitivity,
                trust_level=trust_level,
                allow_low_risk_admission=allow_low_risk_admission,
            ),
        },
    }


def normalize_relationship_memory_payload(
    payload: dict[str, Any],
    *,
    active_workspace_id: str,
    companion_id: str | None,
    resolve_relationship_scope: Callable[[str, str | None], str],
    normalize_relationship_importance: Callable[[str, float | int | None], float],
    allow_low_risk_admission: bool = False,
) -> dict[str, Any]:
    event_kind = str(payload.get("kind") or "state_snapshot")
    authoritative_workspace_id = str(active_workspace_id or "").strip()
    if not authoritative_workspace_id:
        raise ValueError("active_workspace_id is required for relationship memory candidates")
    metadata_payload = cast(dict[str, Any], payload.get("metadata")) if isinstance(payload.get("metadata"), dict) else {}
    supplied_workspace_ids = {
        str(value).strip()
        for value in (payload.get("workspace_id"), metadata_payload.get("workspace_id"))
        if value is not None and str(value).strip()
    }
    if any(workspace_id != authoritative_workspace_id for workspace_id in supplied_workspace_ids):
        raise ValueError("candidate workspace_id does not match active_workspace_id")
    scope = resolve_relationship_scope(event_kind, payload.get("scope") if isinstance(payload.get("scope"), str) else None)
    importance = normalize_relationship_importance(
        event_kind,
        payload.get("importance") if isinstance(payload.get("importance"), (int, float)) else float(cast(float, EVENT_WRITE_RULES.get(event_kind, {}).get("default_importance", 0.8))),
    )
    source_name = str(metadata_payload.get("source") or cast(str, EVENT_WRITE_RULES.get(event_kind, {}).get("source", "relationship")))

    routing = route_memory_write(
        text=str(payload.get("text") or ""),
        memory_type=str(payload.get("type") or "event"),
        importance=importance,
        session_id=payload.get("session_id") if isinstance(payload.get("session_id"), str) else None,
        workspace_id=authoritative_workspace_id,
        metadata={
            **metadata_payload,
            "source": source_name,
        },
        explicit_layer=payload.get("layer") if isinstance(payload.get("layer"), str) else None,
    )

    text = str(payload.get("text") or "").strip()
    if not text:
        tool_name = str(payload.get("tool_name") or "")
        text = f"結崎关系事件：kind={event_kind}" + (f", tool={tool_name}" if tool_name else "")

    existing_relationship_event = metadata_payload.get("relationship_event")
    relationship_event = (
        dict(existing_relationship_event)
        if isinstance(existing_relationship_event, dict)
        else {}
    )
    relationship_event.update({
        "kind": event_kind,
        **{k: v for k, v in payload.items() if k not in {"text", "type", "layer", "importance", "session_id", "workspace_id", "metadata"}},
    })
    metadata = normalize_memory_expiry({
        **routing["metadata"],
        "scope": scope,
        "importance": importance,
        "source": source_name,
        "timestamp": datetime.now().isoformat(),
        "workspace_id": authoritative_workspace_id,
        "companion_id": companion_id,
        "event_type": "relationship_state",
        "relationship_event": relationship_event,
    }, reject_expired=True)
    provenance_source_id = str(
        payload.get("source_id") or payload.get("task_id") or payload.get("tool_name")
        or metadata.get("source_id") or metadata.get("task_id") or metadata.get("tool_name") or ""
    ) or None
    provenance_turn_id = payload.get("turn_id") if isinstance(payload.get("turn_id"), str) else metadata.get("turn_id")
    sensitivity = _resolve_sensitivity(
        metadata_payload.get("sensitive_category"),
        metadata_payload.get("sensitivity"),
        payload.get("sensitive_category"),
        payload.get("sensitivity"),
    )
    source_kind = _authoritative_source_kind(
        event_kind=event_kind,
        payload=payload,
        metadata=metadata_payload,
    )
    metadata.update(_candidate_provenance(
        kind=event_kind,
        source_kind=source_kind,
        source_id=provenance_source_id,
        turn_id=provenance_turn_id,
        evidence=payload.get("evidence") if payload.get("evidence") is not None else metadata_payload.get("evidence"),
        sensitive_category=sensitivity,
        trust_level=_default_trust_level(source_kind),
        allow_low_risk_admission=allow_low_risk_admission,
    ))
    stable_id = candidate_id(
        kind=event_kind,
        source_id=provenance_source_id,
        turn_id=provenance_turn_id,
        text=text,
        workspace_id=metadata.get("workspace_id"),
    )
    metadata["candidate_id"] = stable_id
    audit = list(metadata.get("audit") or []) if isinstance(metadata.get("audit"), list) else []
    audit.append({
        "at": datetime.now().isoformat(),
        "action": "create_candidate",
        "actor": "memory-write-pipeline",
    })
    metadata["audit"] = audit[-100:]
    return {
        "doc_id": stable_id,
        "text": text,
        "layer": routing["layer"],
        "scope": scope,
        "importance": importance,
        "metadata": metadata,
    }


def persist_relationship_memory(payload: dict[str, Any], *, memory_store) -> dict[str, Any]:
    metadata = normalize_memory_expiry(payload["metadata"], reject_expired=True)
    doc_id = str(payload.get("doc_id") or candidate_id(
        kind=str(metadata.get("source_kind") or metadata.get("event_type") or "event"),
        source_id=metadata.get("source_id"),
        turn_id=metadata.get("turn_id"),
        text=str(payload.get("text") or ""),
        workspace_id=metadata.get("workspace_id"),
    ))
    if metadata.get("candidate") is not True:
        raise ValueError("automatic relationship memory must be a candidate")
    if str(metadata.get("candidate_id") or "") != doc_id:
        raise ValueError("candidate_id must match the persisted document id")
    required_provenance = ("event_kind", "source_kind", "trust_level", "sensitive_category")
    if any(metadata.get(key) in (None, "") for key in required_provenance):
        raise ValueError("automatic relationship memory requires complete provenance")
    expected_admission = _candidate_admission(
        source_kind=str(metadata["source_kind"]),
        sensitivity=_sensitive_category(metadata.get("sensitive_category")),
        trust_level=_trust_level(metadata.get("trust_level"), default="untrusted"),
        allow_low_risk_admission=metadata.get("low_risk_admission_requested") is True,
    )
    for key in ("review_status", "review_required", "admission_policy", "admission_reason"):
        if metadata.get(key) != expected_admission[key]:
            raise ValueError(f"candidate admission metadata is inconsistent: {key}")
    existing = next((item for item in memory_store.list_documents() if item.id == doc_id), None)
    if existing is not None:
        return {**payload, "doc_id": doc_id, "idempotent": True}
    doc = Document(id=doc_id, text=str(payload["text"]), metadata=metadata)
    add_metadata_document = getattr(memory_store, "add_metadata_document", None)
    if callable(add_metadata_document):
        add_metadata_document(doc)
    else:
        memory_store.add_document(doc)
    return {**payload, "doc_id": doc_id, "idempotent": False}
