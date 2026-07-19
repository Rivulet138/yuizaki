from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .companion_policy import apply_behavior_modifiers, build_base_behavior_event, build_behavior_profile, evaluate_proactive_policy

logger = logging.getLogger(__name__)


@dataclass
class HeartbeatState:
    running: bool = False
    interval_seconds: int = 30
    tick_count: int = 0
    last_tick_at: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    behavior_events: list[dict[str, Any]] = field(default_factory=list)
    persona: dict[str, Any] = field(default_factory=lambda: {
        'mood': 'neutral',
        'energy': 1.0,
        'affinity': 0.5,
    })
    last_relationship_snapshot: dict[str, Any] | None = None


class HeartbeatScheduler:
    def __init__(self, interval_seconds: int = 30, trace_provider=None, companion_provider=None, companion_persist=None, relationship_memory_writer=None, relationship_history_provider=None, relationship_summary_provider=None):
        self.state = HeartbeatState(interval_seconds=interval_seconds)
        self._task: asyncio.Task[Any] | None = None
        self._trace_provider = trace_provider
        self._companion_provider = companion_provider
        self._companion_persist = companion_persist
        self._relationship_memory_writer = relationship_memory_writer
        self._relationship_history_provider = relationship_history_provider
        self._relationship_summary_provider = relationship_summary_provider

    async def start(self):
        if self._task and not self._task.done():
            return
        self.state.running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        self.state.running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _run(self):
        while self.state.running:
            await asyncio.sleep(self.state.interval_seconds)
            self.state.tick_count += 1
            self.state.last_tick_at = datetime.now().isoformat()
            self._sync_companion_defaults()
            self._update_persona_state()
            self._emit_behavior_events()
            self._persist_companion_state()
            await self._persist_relationship_memory_nonblocking()
            self.state.events.append({
                'tick': self.state.tick_count,
                'at': self.state.last_tick_at,
                'persona': dict(self.state.persona),
            })
            self.state.events = self.state.events[-50:]

    def _sync_companion_defaults(self):
        companion = self._companion_provider() if self._companion_provider else None
        if not isinstance(companion, dict):
            return
        emotion_state = companion.get('emotion_state')
        affinity_state = companion.get('affinity_state')
        energy_state = companion.get('energy_state')
        if emotion_state:
            self.state.persona['mood'] = str(emotion_state)
        if affinity_state is not None:
            self.state.persona['affinity'] = float(affinity_state)
        if energy_state is not None:
            self.state.persona['energy'] = float(energy_state)

    def _update_persona_state(self):
        energy = max(0.2, round(float(self.state.persona['energy']) - 0.01, 3))
        affinity = min(1.0, round(float(self.state.persona['affinity']) + 0.002, 3))

        if energy < 0.35:
            mood = 'tired'
        elif energy < 0.5 and affinity > 0.7:
            mood = 'gentle'
        elif affinity > 0.75:
            mood = 'warm'
        elif self.state.tick_count % 5 == 0:
            mood = 'curious'
        else:
            mood = 'neutral'

        self.state.persona.update({
            'energy': energy,
            'affinity': affinity,
            'mood': mood,
        })

    def _emit_behavior_events(self):
        mood = self.state.persona['mood']
        companion = self._companion_provider() if self._companion_provider else None
        companion_name = companion.get('name') if isinstance(companion, dict) else None
        temperament = companion.get('temperament') if isinstance(companion, dict) else None
        attachment_style = companion.get('attachment_style') if isinstance(companion, dict) else None
        support_style = companion.get('support_style') if isinstance(companion, dict) else None
        event: dict[str, Any] | None = None
        recent_same_type = self.state.behavior_events[-1]['type'] if self.state.behavior_events else None
        latest_trace = self._trace_provider() if self._trace_provider else None
        trace_layers = latest_trace.get('layers', []) if isinstance(latest_trace, dict) else []
        recall_count = int(latest_trace.get('recall_count', 0)) if isinstance(latest_trace, dict) else 0
        relationship_history = self._relationship_history_provider() if self._relationship_history_provider else []
        recent_kinds = [
            str(kind)
            for item in relationship_history
            if isinstance(item, dict)
            for kind in [item.get('kind')]
            if kind
        ]
        relationship_summary = self._relationship_summary_provider() if self._relationship_summary_provider else {}

        proactive_state = evaluate_proactive_policy(
            mood=str(mood),
            tick_count=int(self.state.tick_count),
            relationship_summary=relationship_summary,
            recent_kinds=recent_kinds,
            attachment_style=attachment_style,
            support_style=support_style,
            energy=float(self.state.persona['energy']),
        )
        behavior_profile = build_behavior_profile(
            support_style=support_style if isinstance(support_style, str) else None,
            attachment_style=attachment_style if isinstance(attachment_style, str) else None,
            temperament=temperament if isinstance(temperament, str) else None,
            readiness_band=str(proactive_state.get('readiness_band') or 'medium'),
        )

        warm_interval = 4
        gentle_interval = 3
        if attachment_style == 'attached':
            warm_interval = 3
            gentle_interval = 2
        elif attachment_style == 'independent':
            warm_interval = 6
            gentle_interval = 4

        if relationship_summary.get('recent_gratitude_count', 0) >= 2:
            warm_interval = max(2, warm_interval - 1)
        if relationship_summary.get('milestone_count', 0) >= 3:
            gentle_interval = max(2, gentle_interval - 1)
        if relationship_summary.get('milestone_salience') == 'high':
            warm_interval = max(2, warm_interval - 1)
            gentle_interval = max(2, gentle_interval - 1)
        if relationship_summary.get('relationship_stage') == 'close':
            warm_interval = max(2, warm_interval - 1)
            gentle_interval = max(2, gentle_interval - 1)
        elif relationship_summary.get('relationship_stage') == 'stable':
            warm_interval = max(3, warm_interval - 1)
        if relationship_summary.get('proactive_budget', 1.0) >= 1.2:
            warm_interval = max(2, warm_interval - 1)

        warm_interval = int(proactive_state.get('warm_interval') or warm_interval)
        gentle_interval = int(proactive_state.get('gentle_interval') or gentle_interval)

        if not proactive_state.get('can_proactively_reach_out', True):
            self.state.last_relationship_snapshot = {
                **(self.state.last_relationship_snapshot or {}),
                'proactive_state': proactive_state,
                'behavior_profile': behavior_profile,
            }
            return

        event = build_base_behavior_event(
            mood=str(mood),
            tick_count=int(self.state.tick_count),
            warm_interval=warm_interval,
            gentle_interval=gentle_interval,
        )

        event = apply_behavior_modifiers(
            event,
            trace_layers=[str(item) for item in trace_layers if item],
            recall_count=recall_count,
            recent_kinds=[str(item) for item in recent_kinds if item],
            relationship_summary=relationship_summary if isinstance(relationship_summary, dict) else {},
            temperament=temperament if isinstance(temperament, str) else None,
            attachment_style=attachment_style if isinstance(attachment_style, str) else None,
            support_style=support_style if isinstance(support_style, str) else None,
        )

        if event:
            event['trigger_reason'] = proactive_state.get('trigger_reason')
            event['proactive_state'] = proactive_state
            event['behavior_profile'] = behavior_profile
        if event and companion_name:
            event['companion'] = companion_name

        if event and event['type'] != recent_same_type:
            event['tick'] = self.state.tick_count
            event['at'] = self.state.last_tick_at
            self.state.behavior_events.append(event)
            self.state.behavior_events = self.state.behavior_events[-20:]
            self.state.last_relationship_snapshot = {
                **(self.state.last_relationship_snapshot or {}),
                'proactive_state': proactive_state,
                'behavior_profile': behavior_profile,
            }

    def _persist_companion_state(self):
        companion = self._companion_provider() if self._companion_provider else None
        if not self._companion_persist or not isinstance(companion, dict) or not companion.get('id'):
            return
        self._companion_persist(str(companion['id']), {
            'emotion_state': self.state.persona['mood'],
            'affinity_state': float(self.state.persona['affinity']),
            'energy_state': float(self.state.persona['energy']),
        })

    async def _persist_relationship_memory_nonblocking(self):
        if not self._relationship_memory_writer or self.state.tick_count % 5 != 0:
            return
        try:
            await asyncio.to_thread(self._persist_relationship_memory)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to persist heartbeat relationship memory")

    def _persist_relationship_memory(self):
        companion = self._companion_provider() if self._companion_provider else None
        if not self._relationship_memory_writer or not isinstance(companion, dict) or not companion.get('id'):
            return
        if self.state.tick_count % 5 != 0:
            return
        previous = self.state.last_relationship_snapshot or {}
        current = {
            'mood': self.state.persona['mood'],
            'affinity': float(self.state.persona['affinity']),
            'energy': float(self.state.persona['energy']),
        }
        event_kind = 'state_snapshot'
        if previous:
            if previous.get('mood') != current['mood']:
                event_kind = 'mood_shift'
            elif current['affinity'] - float(previous.get('affinity', current['affinity'])) >= 0.05:
                event_kind = 'trust_shift'
            elif current['energy'] <= 0.35:
                event_kind = 'care_signal'
        self._relationship_memory_writer({
            'text': f"結崎 {companion.get('name', companion.get('id'))} 产生了一次关系事件：kind={event_kind}, mood={current['mood']}, affinity={current['affinity']:.3f}, energy={current['energy']:.3f}",
            'type': 'event',
            'layer': 'profile',
            'importance': 0.85,
            'metadata': {
                'source': 'profile',
                'companion_id': companion.get('id'),
                'event_type': 'relationship_state',
                'relationship_event': {
                    'kind': event_kind,
                    'mood': current['mood'],
                    'affinity': current['affinity'],
                    'energy': current['energy'],
                },
            },
        })
        self.state.last_relationship_snapshot = current
