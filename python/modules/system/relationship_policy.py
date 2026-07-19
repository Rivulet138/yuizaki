from __future__ import annotations

from typing import Any, Dict, Iterable


GLOBAL_EVENT_KINDS = {"gratitude", "preference_confirmed", "trust_shift"}
WORKSPACE_EVENT_KINDS = {"tool_success", "support_request", "comfort_event", "care_signal"}
MILESTONE_EVENT_KINDS = {"trust_shift", "preference_confirmed", "gratitude"}


def resolve_relationship_scope(event_kind: str, explicit_scope: str | None = None) -> str:
    if explicit_scope:
        return str(explicit_scope)
    if event_kind in GLOBAL_EVENT_KINDS:
        return "global"
    if event_kind in WORKSPACE_EVENT_KINDS:
        return "workspace"
    return "workspace"


def normalize_relationship_importance(event_kind: str, importance: float | int | None) -> float:
    resolved = float(importance if importance is not None else 0.8)
    if event_kind in GLOBAL_EVENT_KINDS:
        return max(resolved, 0.92)
    if event_kind in WORKSPACE_EVENT_KINDS:
        return max(resolved, 0.88)
    return resolved


def is_relationship_milestone(kind: str, importance: float | int | None) -> bool:
    resolved_importance = float(importance if importance is not None else 0.0)
    return bool(resolved_importance >= 0.92 or kind in MILESTONE_EVENT_KINDS)


def derive_relationship_stage(summary: Dict[str, Any]) -> str:
    milestone_count = int(summary.get("milestone_count", 0) or 0)
    trust_shift_count = int(summary.get("recent_trust_shift_count", 0) or 0)
    event_count = int(summary.get("event_count", 0) or 0)
    if milestone_count >= 4 or trust_shift_count >= 2:
        return "close"
    if event_count >= 3:
        return "stable"
    return "warming"


def derive_proactive_budget(summary: Dict[str, Any]) -> float:
    stage = str(summary.get("relationship_stage") or derive_relationship_stage(summary))
    milestone_count = int(summary.get("milestone_count", 0) or 0)
    gratitude_count = int(summary.get("recent_gratitude_count", 0) or 0)
    budget = 0.9
    if stage == "close":
        budget = 1.3
    elif stage == "stable":
        budget = 1.1
    if milestone_count >= 5:
        budget += 0.1
    elif milestone_count >= 3:
        budget += 0.05
    if gratitude_count >= 3:
        budget += 0.05
    return round(min(budget, 1.5), 2)


def derive_relationship_trend(summary: Dict[str, Any]) -> str:
    trust_shift_count = int(summary.get("recent_trust_shift_count", 0) or 0)
    gratitude_count = int(summary.get("recent_gratitude_count", 0) or 0)
    event_count = int(summary.get("event_count", 0) or 0)
    milestone_count = int(summary.get("milestone_count", 0) or 0)
    if trust_shift_count >= 2 or gratitude_count >= 3:
        return "rising"
    if event_count >= 5 and milestone_count == 0:
        return "flat"
    return "steady"


def derive_milestone_salience(summary: Dict[str, Any]) -> str:
    milestone_count = int(summary.get("milestone_count", 0) or 0)
    trust_shift_count = int(summary.get("recent_trust_shift_count", 0) or 0)
    gratitude_count = int(summary.get("recent_gratitude_count", 0) or 0)
    if milestone_count >= 5 or trust_shift_count >= 2:
        return "high"
    if milestone_count >= 2 or gratitude_count >= 2:
        return "medium"
    return "low"


def derive_milestone_reasoning(summary: Dict[str, Any]) -> str:
    salience = str(summary.get("milestone_salience") or derive_milestone_salience(summary))
    milestone_count = int(summary.get("milestone_count", 0) or 0)
    trust_shift_count = int(summary.get("recent_trust_shift_count", 0) or 0)
    gratitude_count = int(summary.get("recent_gratitude_count", 0) or 0)
    if salience == "high":
        return f"当前共有 {milestone_count} 个关键里程碑，且 trust_shift={trust_shift_count}，说明关系中的关键节点已经足以显著影响主动预算与记忆优先级。"
    if salience == "medium":
        return f"当前里程碑已具备稳定延续意义（milestone={milestone_count}, gratitude={gratitude_count}），应在回答和回忆中被持续保留。"
    return "当前里程碑显著度较低，仍会被保留，但不会过度主导关系节奏或检索策略。"


def summarize_relationship_events(events: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "event_count": 0,
        "high_importance_count": 0,
        "global_count": 0,
        "workspace_count": 0,
        "milestone_count": 0,
        "recent_trust_shift_count": 0,
        "recent_gratitude_count": 0,
        "relationship_stage": "warming",
        "proactive_budget": 1.0,
        "relationship_trend": "steady",
        "milestone_salience": "low",
        "milestone_reasoning": "当前里程碑显著度较低，仍会被保留，但不会过度主导关系节奏或检索策略。",
    }

    for item in events:
        scope = str(item.get("scope") or "workspace")
        kind = str(item.get("kind") or "event")
        importance = float(item.get("importance") or 0.0)

        summary["event_count"] += 1
        if importance >= 0.9:
            summary["high_importance_count"] += 1
        if scope == "global":
            summary["global_count"] += 1
        if scope == "workspace":
            summary["workspace_count"] += 1
        if kind == "trust_shift":
            summary["recent_trust_shift_count"] += 1
        if kind == "gratitude":
            summary["recent_gratitude_count"] += 1
        if is_relationship_milestone(kind, importance):
            summary["milestone_count"] += 1

    summary["relationship_stage"] = derive_relationship_stage(summary)
    summary["proactive_budget"] = derive_proactive_budget(summary)
    summary["relationship_trend"] = derive_relationship_trend(summary)
    summary["milestone_salience"] = derive_milestone_salience(summary)
    summary["milestone_reasoning"] = derive_milestone_reasoning(summary)
    return summary
