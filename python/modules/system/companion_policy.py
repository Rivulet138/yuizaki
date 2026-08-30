from __future__ import annotations

import math
from typing import Any


def _finite_number(value: Any, *, default: float, minimum: float | None = None, maximum: float | None = None) -> tuple[float, bool]:
    """Normalize untrusted relationship/persona numbers without enabling action."""
    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError):
        return default, False
    if not math.isfinite(normalized):
        return default, False
    if minimum is not None and normalized < minimum:
        return default, False
    if maximum is not None and normalized > maximum:
        return default, False
    return normalized, True


def evaluate_proactive_policy(
    *,
    mood: str,
    tick_count: int,
    relationship_summary: dict[str, Any] | None,
    recent_kinds: list[str] | None,
    attachment_style: str | None,
    support_style: str | None,
    energy: float,
) -> dict[str, Any]:
    summary = relationship_summary or {}
    kinds = [str(item) for item in (recent_kinds or []) if item]
    relationship_stage = str(summary.get("relationship_stage") or "warming")
    milestone_salience = str(summary.get("milestone_salience") or "low")
    raw_budget = summary.get("proactive_budget", 1.0)
    if raw_budget is None:
        raw_budget = 1.0
    proactive_budget, budget_valid = _finite_number(
        raw_budget,
        default=0.0,
        minimum=0.0,
        maximum=10.0,
    )
    normalized_energy, energy_valid = _finite_number(
        energy,
        default=0.0,
        minimum=0.0,
        maximum=1.0,
    )

    suppression_reasons: list[str] = []
    trigger_reason = "routine-idle"

    if not budget_valid:
        suppression_reasons.append("invalid-proactive-budget")
    if not energy_valid:
        suppression_reasons.append("invalid-energy")
    if normalized_energy <= 0.3 or mood == "tired":
        suppression_reasons.append("low-energy")
    if proactive_budget < 0.85:
        suppression_reasons.append("low-proactive-budget")
    if tick_count < 2:
        suppression_reasons.append("warmup-window")

    warm_interval = 4
    gentle_interval = 3
    if attachment_style == "attached":
        warm_interval = 3
        gentle_interval = 2
    elif attachment_style == "independent":
        warm_interval = 6
        gentle_interval = 4

    if relationship_stage == "close":
        warm_interval = max(2, warm_interval - 1)
        gentle_interval = max(2, gentle_interval - 1)
    elif relationship_stage == "stable":
        warm_interval = max(3, warm_interval - 1)
    if milestone_salience == "high":
        warm_interval = max(2, warm_interval - 1)
        gentle_interval = max(2, gentle_interval - 1)

    if "support_request" in kinds:
        trigger_reason = "recent-support-request"
    elif "comfort_event" in kinds:
        trigger_reason = "recent-comfort-event"
    elif "trust_shift" in kinds:
        trigger_reason = "recent-trust-shift"
    elif mood == "warm":
        trigger_reason = "warm-idle-prompt"
    elif mood == "gentle":
        trigger_reason = "gentle-idle-prompt"
    elif mood == "curious":
        trigger_reason = "curious-reminder"

    can_proactively_reach_out = not suppression_reasons
    if support_style == "analytical" and trigger_reason == "curious-reminder":
        trigger_reason = "analytical-reminder"
    elif support_style == "gentle" and mood == "gentle":
        trigger_reason = "gentle-support"
    elif support_style == "cheerful" and mood in {"warm", "curious"}:
        trigger_reason = "cheerful-nudge"

    readiness_band = "high" if can_proactively_reach_out and proactive_budget >= 1.2 else "medium" if can_proactively_reach_out else "low"

    return {
        "can_proactively_reach_out": can_proactively_reach_out,
        "suppression_reasons": suppression_reasons,
        "trigger_reason": trigger_reason,
        "readiness_band": readiness_band,
        "warm_interval": warm_interval,
        "gentle_interval": gentle_interval,
        "relationship_stage": relationship_stage,
        "milestone_salience": milestone_salience,
        "proactive_budget": proactive_budget,
    }


def build_behavior_profile(*, support_style: str | None, attachment_style: str | None, temperament: str | None, readiness_band: str) -> dict[str, str]:
    tone_bucket = "balanced"
    if support_style == "gentle":
        tone_bucket = "soft"
    elif support_style == "analytical":
        tone_bucket = "structured"
    elif support_style == "cheerful":
        tone_bucket = "bright"

    closeness_bucket = "steady"
    if attachment_style == "attached":
        closeness_bucket = "close"
    elif attachment_style == "independent":
        closeness_bucket = "spacious"

    expression_bucket = "calm"
    if temperament == "playful":
        expression_bucket = "expressive"
    elif temperament == "reserved":
        expression_bucket = "subtle"

    initiative_bucket = "quiet"
    if readiness_band == "high":
        initiative_bucket = "proactive"
    elif readiness_band == "medium":
        initiative_bucket = "available"

    return {
        "tone_bucket": tone_bucket,
        "closeness_bucket": closeness_bucket,
        "expression_bucket": expression_bucket,
        "initiative_bucket": initiative_bucket,
    }


def build_base_behavior_event(*, mood: str, tick_count: int, warm_interval: int, gentle_interval: int) -> dict[str, object] | None:
    if mood == "tired":
        return {
            "type": "suggestion",
            "message": "我有点累了，想安静陪你一会。",
            "emotion": "calm",
            "emotion_id": "calm",
            "motion_group": "Idle",
            "prompt": "rest-mode",
        }
    if mood == "warm" and tick_count % warm_interval == 0:
        return {
            "type": "idle_prompt",
            "message": "要不要让我帮你回顾一下最近的重要记忆？",
            "emotion": "happy",
            "emotion_id": "happy",
            "motion_group": "Tap",
            "prompt": "memory-recall",
        }
    if mood == "curious":
        return {
            "type": "reminder",
            "message": "你最近好像有些事情在推进，我可以帮你整理。",
            "emotion": "curious",
            "emotion_id": "curious",
            "motion_group": "Flick",
            "prompt": "organize-work",
        }
    if mood == "gentle" and tick_count % gentle_interval == 0:
        return {
            "type": "idle_prompt",
            "message": "别太勉强自己，我可以陪你慢慢整理。",
            "emotion": "calm",
            "emotion_id": "calm",
            "motion_group": "Tap",
            "prompt": "gentle-support",
        }
    return None


def apply_behavior_modifiers(
    event: dict[str, object] | None,
    *,
    trace_layers: list[str],
    recall_count: int,
    recent_kinds: list[str],
    relationship_summary: dict[str, object],
    temperament: str | None,
    attachment_style: str | None,
    support_style: str | None,
) -> dict[str, object] | None:
    if event is None:
        return None

    # Keep proactive copy warm but bounded: relationship, milestone and style
    # signals may all be present at once, yet stacking them makes a short
    # desktop prompt feel performative. Apply at most one social prefix.
    prefix_applied = False

    def prepend_prefix(prefix: str) -> None:
        nonlocal prefix_applied
        if prefix_applied:
            return
        event['message'] = f"{prefix}{event['message']}"
        prefix_applied = True

    if recall_count > 0:
        if 'profile' in trace_layers:
            prepend_prefix('我记得你的偏好，')
            event['emotion_id'] = 'happy'
        elif 'session' in trace_layers:
            prepend_prefix('结合你当前会话的内容，')
            event['motion_group'] = 'Tap'
            if recall_count >= 3:
                event['prompt'] = 'focus-current-session'
        elif 'episodic' in trace_layers:
            prepend_prefix('想到你最近经历的事情，')
            event['motion_group'] = 'Flick'
        event['trace_layers'] = trace_layers
        event['trace_recall_count'] = recall_count

    if 'trust_shift' in recent_kinds:
        prepend_prefix('最近我们之间更有默契了，')
        event['prompt'] = 'relationship-warmth'
        event['motion_group'] = 'Tap'
        event['emotion_id'] = 'happy'
    elif 'care_signal' in recent_kinds:
        prepend_prefix('我留意到你最近状态需要照顾，')
        event['emotion_id'] = 'calm'
        event['motion_group'] = 'Idle'
    elif 'support_request' in recent_kinds:
        prepend_prefix('我在这里支持你，')
        event['emotion_id'] = 'calm'
        event['motion_group'] = 'Tap'
        event['prompt'] = 'supportive-response'
    elif 'comfort_event' in recent_kinds:
        prepend_prefix('我会好好陪着你，')
        event['emotion_id'] = 'calm'
        event['motion_group'] = 'Idle'
        event['prompt'] = 'comfort-mode'

    if relationship_summary.get('relationship_stage') == 'close':
        prepend_prefix('我们已经很熟悉了，')
        if event.get('type') in {'idle_prompt', 'suggestion'}:
            prepend_prefix('如果你愿意，我现在就可以顺手帮你处理。')
    elif relationship_summary.get('relationship_stage') == 'stable':
        prepend_prefix('我会稳定地陪着你，')

    if relationship_summary.get('milestone_salience') == 'high':
        prepend_prefix('我记得我们之间那些重要时刻，')
        if event.get('type') in {'idle_prompt', 'suggestion'}:
            event['prompt'] = 'milestone-aware-support'

    if temperament == 'playful':
        event['motion_group'] = 'Flick' if event.get('motion_group') == 'Tap' else event.get('motion_group', 'Flick')
        if event.get('emotion_id') == 'calm':
            event['emotion_id'] = 'curious'
    elif temperament == 'reserved':
        event['motion_group'] = 'Idle'

    if attachment_style == 'attached':
        prepend_prefix('我会更贴近地陪着你，')
        if event.get('type') == 'idle_prompt':
            event['prompt'] = 'closer-bonding'
        event['motion_group'] = 'Tap'
    elif attachment_style == 'independent':
        prepend_prefix('我会在旁边稳稳支持你，')
        event['motion_group'] = 'Idle'

    if support_style == 'analytical' and event.get('type') == 'reminder':
        prepend_prefix('我帮你把问题拆清楚，')
        event['prompt'] = 'analytical-support'
    elif support_style == 'gentle' and event.get('type') in {'idle_prompt', 'suggestion'}:
        prepend_prefix('我会温柔地陪着你，')
    elif support_style == 'cheerful' and event.get('type') in {'idle_prompt', 'suggestion', 'reminder'}:
        prepend_prefix('我会更积极一点帮你推进，')
        if event.get('emotion_id') == 'calm':
            event['emotion_id'] = 'happy'
        event['motion_group'] = 'Flick'

    return event
