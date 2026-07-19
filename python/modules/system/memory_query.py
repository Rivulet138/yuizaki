from __future__ import annotations

from typing import Any, Dict

from ..memory.schema import RetrievalRequest


def build_style_aware_retrieval_strategy(
    *,
    support_style: str | None = None,
    relationship_stage: str | None = None,
    milestone_salience: str | None = None,
    recent_signal_kinds: list[str] | None = None,
    layers: str | None = None,
) -> Dict[str, Any]:
    if layers:
        resolved_layers = [item.strip() for item in layers.split(",") if item.strip()]
        return {
            "label": "manual-override",
            "layers": resolved_layers,
            "reasoning": "layers were explicitly provided by the caller; style-aware defaults were skipped.",
        }

    if support_style == "analytical":
        resolved_layers = ["semantic", "profile", "working", "relationship"]
        reasoning = "analytical support prefers structured semantic recall first, then profile/working/relationship context."
    elif support_style == "gentle":
        resolved_layers = ["profile", "relationship", "episodic", "working", "semantic"]
        reasoning = "gentle support prefers profile, relationship, and episodic context first to preserve reassurance and affective continuity."
    elif support_style == "cheerful":
        resolved_layers = ["episodic", "working", "profile", "relationship", "semantic"]
        reasoning = "cheerful support prefers episodic and working context first to surface momentum and emotionally vivid recall."
    else:
        resolved_layers = ["profile", "working", "episodic", "relationship", "reflective", "semantic"]
        reasoning = "default style-aware retrieval uses balanced profile/working/episodic/relationship/reflective/semantic ordering."

    if relationship_stage == "close" and milestone_salience == "high":
        boosted_layers = [layer for layer in ["episodic", *resolved_layers] if layer in resolved_layers or layer == "episodic"]
        milestone_layers: list[str] = []
        for layer in boosted_layers:
            if layer not in milestone_layers:
                milestone_layers.append(layer)
        resolved_layers = milestone_layers
        reasoning += " High milestone salience in a close relationship boosts episodic recall priority."
        label = "style+milestone-boosted"
    else:
        label = "style-aware-default"

    signals = [str(item) for item in (recent_signal_kinds or []) if item]
    if any(kind in signals for kind in ["support_request", "comfort_event"]):
        boosted_layers = ["relationship", "working", *resolved_layers]
        support_layers: list[str] = []
        for layer in boosted_layers:
            if layer not in support_layers:
                support_layers.append(layer)
        resolved_layers = support_layers
        reasoning += " Recent support/comfort signals boost relationship and working recall priority."
        label = "style+support-signal-boosted"
    elif any(kind in signals for kind in ["tool_success", "task_completed"]):
        boosted_layers = ["reflective", *resolved_layers]
        reflective_layers: list[str] = []
        for layer in boosted_layers:
            if layer not in reflective_layers:
                reflective_layers.append(layer)
        resolved_layers = reflective_layers
        reasoning += " Recent tool/task completion signals boost reflective recall priority."
        label = "style+reflective-boosted"

    return {
        "label": label,
        "layers": resolved_layers,
        "reasoning": reasoning,
    }


def build_memory_query_request(
    *,
    query: str,
    session_id: str | None,
    workspace_id: str | None,
    scope: str | None,
    layers: str | None,
    top_k: int,
    support_style: str | None = None,
    relationship_stage: str | None = None,
    milestone_salience: str | None = None,
    recent_signal_kinds: list[str] | None = None,
) -> RetrievalRequest:
    strategy = build_style_aware_retrieval_strategy(
        support_style=support_style,
        relationship_stage=relationship_stage,
        milestone_salience=milestone_salience,
        recent_signal_kinds=recent_signal_kinds,
        layers=layers,
    )
    resolved_layers = strategy["layers"]
    return RetrievalRequest(
        query=query,
        scope=scope,
        session_id=session_id,
        workspace_id=workspace_id,
        top_k=top_k,
        layers=resolved_layers,
    )
