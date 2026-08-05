from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, cast
from uuid import uuid4

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
}


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


def build_user_signal_event(text: str) -> dict[str, Any] | None:
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
        "metadata": {
            "source": source,
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
        },
    }


def build_tool_success_event(*, tool_name: str, args: dict[str, Any], text: str, importance: float, owner_agent_id: str | None, owner_agent_role: str | None) -> dict[str, Any]:
    return {
        "text": text,
        "kind": "tool_success",
        "tool_name": tool_name,
        "args": args,
        "importance": importance,
        "metadata": {
            "source": cast(str, EVENT_WRITE_RULES["tool_success"]["source"]),
            "owner_agent_id": owner_agent_id,
            "owner_agent_role": owner_agent_role,
        },
    }


def normalize_relationship_memory_payload(
    payload: dict[str, Any],
    *,
    active_workspace_id: str,
    companion_id: str | None,
    resolve_relationship_scope: Callable[[str, str | None], str],
    normalize_relationship_importance: Callable[[str, float | int | None], float],
) -> dict[str, Any]:
    event_kind = str(payload.get("kind") or "state_snapshot")
    scope = resolve_relationship_scope(event_kind, payload.get("scope") if isinstance(payload.get("scope"), str) else None)
    importance = normalize_relationship_importance(
        event_kind,
        payload.get("importance") if isinstance(payload.get("importance"), (int, float)) else float(cast(float, EVENT_WRITE_RULES.get(event_kind, {}).get("default_importance", 0.8))),
    )
    metadata_payload = cast(dict[str, Any], payload.get("metadata")) if isinstance(payload.get("metadata"), dict) else {}
    source_name = str(metadata_payload.get("source") or cast(str, EVENT_WRITE_RULES.get(event_kind, {}).get("source", "relationship")))

    routing = route_memory_write(
        text=str(payload.get("text") or ""),
        memory_type=str(payload.get("type") or "event"),
        importance=importance,
        session_id=payload.get("session_id") if isinstance(payload.get("session_id"), str) else None,
        workspace_id=payload.get("workspace_id") if isinstance(payload.get("workspace_id"), str) else active_workspace_id,
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

    metadata = normalize_memory_expiry({
        **routing["metadata"],
        "scope": scope,
        "importance": importance,
        "source": source_name,
        "timestamp": datetime.now().isoformat(),
        "workspace_id": payload.get("workspace_id") or active_workspace_id,
        "companion_id": companion_id,
        "event_type": "relationship_state",
        "relationship_event": {
            "kind": event_kind,
            **{k: v for k, v in payload.items() if k not in {"text", "type", "layer", "importance", "session_id", "workspace_id", "metadata"}},
        },
    }, reject_expired=True)
    return {
        "doc_id": str(uuid4()),
        "text": text,
        "layer": routing["layer"],
        "scope": scope,
        "importance": importance,
        "metadata": metadata,
    }


def persist_relationship_memory(payload: dict[str, Any], *, memory_store) -> dict[str, Any]:
    metadata = normalize_memory_expiry(payload["metadata"], reject_expired=True)
    doc = Document(id=str(payload["doc_id"]), text=str(payload["text"]), metadata=metadata)
    add_metadata_document = getattr(memory_store, "add_metadata_document", None)
    if callable(add_metadata_document):
        add_metadata_document(doc)
    else:
        memory_store.add_document(doc)
    return payload
