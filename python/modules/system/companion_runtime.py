from __future__ import annotations

from typing import Any, Dict

from .relationship_runtime import collect_relationship_events
from .memory_query import build_style_aware_retrieval_strategy


def _unit_state(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return min(1.0, max(0.0, number))


def build_companion_runtime_snapshot(
    *,
    active_workspace_id: str,
    db_repo: Any,
    heartbeat_scheduler: Any,
    memory_state: Any,
    summarize_relationship_events,
    is_relationship_milestone,
    limit: int = 8,
) -> Dict[str, Any]:
    companion = db_repo.get_workspace_companion(active_workspace_id) if db_repo else None
    companion_id = companion.get("id") if isinstance(companion, dict) else None
    heartbeat = {
        "running": heartbeat_scheduler.state.running if heartbeat_scheduler else False,
        "interval_seconds": heartbeat_scheduler.state.interval_seconds if heartbeat_scheduler else 0,
        "tick_count": heartbeat_scheduler.state.tick_count if heartbeat_scheduler else 0,
        "last_tick_at": heartbeat_scheduler.state.last_tick_at if heartbeat_scheduler else None,
        "persona": heartbeat_scheduler.state.persona if heartbeat_scheduler else {"mood": "neutral", "energy": 1.0, "affinity": 0.5},
        "events": heartbeat_scheduler.state.events if heartbeat_scheduler else [],
        "behavior_events": heartbeat_scheduler.state.behavior_events if heartbeat_scheduler else [],
        "proactive_state": (heartbeat_scheduler.state.last_relationship_snapshot or {}).get("proactive_state") if heartbeat_scheduler else None,
        "behavior_profile": (heartbeat_scheduler.state.last_relationship_snapshot or {}).get("behavior_profile") if heartbeat_scheduler else None,
    }
    if not companion_id:
        return {
            "active_workspace_id": active_workspace_id,
            "active_companion": None,
            "heartbeat": heartbeat,
            "companion_state": {
                "mood": "neutral",
                "energy": 1.0,
                "trust": 0.5,
                "intimacy": 0.5,
                "interruptibility": 0.75,
                "fatigue": 0.0,
                "stage": "warming",
                "proactive_state": None,
                "behavior_profile": None,
            },
            "memory_state": {
                "profile_count": 0,
                "semantic_count": 0,
                "episodic_count": 0,
                "relationship_count": 0,
                "working_count": 0,
                "reflective_count": 0,
                "recent_signals": [],
                "signal_summary": {},
            },
            "relationship": {
                "events": [],
                "grouped": {},
                "milestones": [],
                "summary": summarize_relationship_events([]),
            },
        }

    events = collect_relationship_events(
        memory_store=memory_state.store,
        companion_id=companion_id,
        limit=limit,
        workspace_id=active_workspace_id,
    )

    grouped: Dict[str, Dict[str, list[Dict[str, Any]]]] = {}
    milestones: list[Dict[str, Any]] = []
    summary = summarize_relationship_events(events)
    for item in events:
        scope = str(item.get("scope") or "workspace")
        kind = str(item.get("kind") or "event")
        item["milestone"] = is_relationship_milestone(kind, item.get("importance"))
        grouped.setdefault(scope, {}).setdefault(kind, []).append(item)
        if item["milestone"]:
            milestones.append(item)

    all_docs = memory_state.store.list_documents() if memory_state and getattr(memory_state, "store", None) else []
    docs = [
        doc
        for doc in all_docs
        if (doc.metadata or {}).get("scope") == "global"
        or (doc.metadata or {}).get("workspace_id") == active_workspace_id
    ]
    profile_count = sum(1 for doc in docs if (doc.metadata or {}).get("layer") == "profile")
    semantic_count = sum(1 for doc in docs if (doc.metadata or {}).get("layer") == "semantic")
    episodic_count = sum(1 for doc in docs if (doc.metadata or {}).get("layer") == "episodic")
    relationship_count = sum(1 for doc in docs if (doc.metadata or {}).get("layer") == "relationship")
    working_count = sum(1 for doc in docs if (doc.metadata or {}).get("layer") in {"working", "session"})
    reflective_count = sum(1 for doc in docs if (doc.metadata or {}).get("layer") == "reflective")
    current_energy = _unit_state(companion.get("energy_state") if isinstance(companion, dict) else None, 1.0)
    trust = _unit_state(companion.get("trust_state") if isinstance(companion, dict) else None, 0.5)
    intimacy = _unit_state(companion.get("intimacy_state") if isinstance(companion, dict) else None, 0.5)
    interruptibility = _unit_state(companion.get("interruptibility_state") if isinstance(companion, dict) else None, 0.75)
    fatigue = _unit_state(companion.get("fatigue_state") if isinstance(companion, dict) else None, 0.0)

    support_style = companion.get("support_style") if isinstance(companion, dict) else None

    recent_signal_docs = []
    for doc in reversed(docs):
        meta = doc.metadata or {}
        layer = meta.get("layer")
        signal_kind = None
        if meta.get("event_type") == "relationship_state":
            rel = meta.get("relationship_event")
            if isinstance(rel, dict):
                signal_kind = rel.get("kind")
        if signal_kind is None and layer in {"profile", "working", "episodic", "relationship", "reflective"}:
            signal_kind = meta.get("type")
        if not signal_kind:
            continue
        recent_signal_docs.append({
            "kind": str(signal_kind),
            "layer": str(layer or "semantic"),
            "source": str(meta.get("source") or "unknown"),
            "importance": float(meta.get("importance") or 0),
            "text": doc.text,
            "timestamp": str(meta.get("timestamp") or ""),
        })
        if len(recent_signal_docs) >= 6:
            break

    signal_summary: dict[str, int] = {}
    for item in recent_signal_docs:
        key = item["kind"]
        signal_summary[key] = signal_summary.get(key, 0) + 1

    retrieval_strategy = build_style_aware_retrieval_strategy(
        support_style=support_style,
        relationship_stage=summary.get("relationship_stage"),
        milestone_salience=summary.get("milestone_salience"),
        layers=None,
    )
    heartbeat_persona = heartbeat.get("persona")
    heartbeat_mood = heartbeat_persona.get("mood") if isinstance(heartbeat_persona, dict) else None

    return {
        "active_workspace_id": active_workspace_id,
        "active_companion": companion,
        "heartbeat": heartbeat,
        "companion_state": {
            "mood": str(companion.get("emotion_state") or heartbeat_mood or "neutral") if isinstance(companion, dict) else "neutral",
            "energy": current_energy,
            "trust": round(trust, 3),
            "intimacy": round(intimacy, 3),
            "interruptibility": round(interruptibility, 3),
            "fatigue": round(fatigue, 3),
            "stage": str(summary.get("relationship_stage") or "warming"),
            "proactive_state": heartbeat.get("proactive_state"),
            "behavior_profile": heartbeat.get("behavior_profile"),
        },
        "memory_state": {
            "profile_count": profile_count,
            "semantic_count": semantic_count,
            "episodic_count": episodic_count,
            "relationship_count": relationship_count,
            "working_count": working_count,
            "reflective_count": reflective_count,
            "recent_signals": recent_signal_docs,
            "signal_summary": signal_summary,
        },
        "retrieval_strategy": retrieval_strategy,
        "relationship": {
            "events": events,
            "grouped": grouped,
            "milestones": milestones,
            "summary": summary,
        },
    }
