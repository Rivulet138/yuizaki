from __future__ import annotations

import asyncio
import inspect
import logging
import math
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from ..agent.companion_events import CompanionJobCapacityError, CompanionJobEventLog
from ..agent.turn_service import SemanticTurnRequest, TurnCommit, TurnService
from .companion_policy import (
    apply_behavior_modifiers,
    build_base_behavior_event,
    build_behavior_profile,
    evaluate_proactive_policy,
)
from .heartbeat_goal_store import HeartbeatGoalStore

logger = logging.getLogger(__name__)
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 60
MAX_HEARTBEAT_GOALS = 32
OPPORTUNITY_EXPIRY_RETRY_BASE_SECONDS = 0.05
OPPORTUNITY_EXPIRY_RETRY_MAX_SECONDS = 5.0


class HeartbeatOpportunityAcceptanceError(RuntimeError):
    """Base error for a rejected explicit heartbeat acceptance."""


class HeartbeatOpportunityAuthorizationError(HeartbeatOpportunityAcceptanceError):
    """Raised when policy does not authorize an explicit acceptance."""


class HeartbeatOpportunityConflictError(HeartbeatOpportunityAcceptanceError):
    """Raised when the opportunity identity is stale, cancelled, or mismatched."""


class HeartbeatOpportunityUnavailableError(HeartbeatOpportunityAcceptanceError):
    """Raised when the acceptance bridge is missing a required authority."""


@dataclass(frozen=True)
class HeartbeatOpportunityAcceptance:
    """Complete caller identity required to accept one heartbeat opportunity."""

    job_id: str
    request_id: str
    workspace_id: str
    session_id: str

    @classmethod
    def from_mapping(
        cls,
        job_id: str,
        value: Mapping[str, Any],
    ) -> HeartbeatOpportunityAcceptance:
        acceptance = cls(
            job_id=str(job_id or "").strip(),
            request_id=str(value.get("request_id") or value.get("requestId") or "").strip(),
            workspace_id=str(value.get("workspace_id") or value.get("workspaceId") or "").strip(),
            session_id=str(value.get("session_id") or value.get("sessionId") or "").strip(),
        )
        if not all((
            acceptance.job_id,
            acceptance.request_id,
            acceptance.workspace_id,
            acceptance.session_id,
        )):
            raise ValueError(
                "job_id, request_id, workspace_id, and session_id are required"
            )
        return acceptance

    @property
    def identity(self) -> tuple[str, str, str, str]:
        return (self.job_id, self.request_id, self.workspace_id, self.session_id)


HeartbeatOpportunityAuthorizer = Callable[
    [HeartbeatOpportunityAcceptance, Mapping[str, Any]],
    bool | Awaitable[bool],
]


@dataclass(frozen=True)
class HeartbeatAcceptedTurn:
    acceptance: HeartbeatOpportunityAcceptance
    commit: TurnCommit
    replayed_delivery: bool = False

    def response(self) -> dict[str, Any]:
        commit = self.commit
        return {
            "ok": True,
            "accepted": True,
            "job_id": self.acceptance.job_id,
            "request_id": self.acceptance.request_id,
            "workspace_id": self.acceptance.workspace_id,
            "session_id": self.acceptance.session_id,
            "commit_id": commit.idempotency_key,
            "semantic_fingerprint": commit.semantic_fingerprint,
            "turn_stage": "committed",
            "trigger": commit.trigger,
            "outcome": commit.outcome,
            "retryable": commit.retryable,
            "replayed": self.replayed_delivery or commit.replayed,
            "configured_budget": dict(commit.configured_budget),
            "consumed_usage": dict(commit.consumed_usage),
        }


@dataclass
class _HeartbeatAcceptanceClaim:
    identity: tuple[str, str, str, str]
    cancellation_event: asyncio.Event = field(default_factory=asyncio.Event)
    event_loop: asyncio.AbstractEventLoop | None = None
    phase: str = "claimed"
    cancellation_outcome: str | None = None
    cancellation_reason: str | None = None

    def request_cancellation(self, outcome: str, reason: str | None) -> None:
        self.cancellation_outcome = outcome
        self.cancellation_reason = reason
        if self.event_loop is not None:
            self.event_loop.call_soon_threadsafe(self.cancellation_event.set)
        else:
            self.cancellation_event.set()


@dataclass
class HeartbeatState:
    running: bool = False
    interval_seconds: int = DEFAULT_HEARTBEAT_INTERVAL_SECONDS
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
    goals: list[dict[str, Any]] = field(default_factory=list)


class HeartbeatScheduler:
    def __init__(self, interval_seconds: int = DEFAULT_HEARTBEAT_INTERVAL_SECONDS, trace_provider=None, companion_provider=None, companion_persist=None, relationship_memory_writer=None, relationship_history_provider=None, relationship_summary_provider=None, workspace_id_provider=None, job_event_log: CompanionJobEventLog | None = None, opportunity_ttl_seconds: float | None = None, goal_store: HeartbeatGoalStore | None = None):
        self.state = HeartbeatState(interval_seconds=interval_seconds)
        self._task: asyncio.Task[Any] | None = None
        self._expiry_task: asyncio.Task[Any] | None = None
        self._expiry_wakeup = asyncio.Event()
        self._trace_provider = trace_provider
        self._companion_provider = companion_provider
        self._companion_persist = companion_persist
        self._relationship_memory_writer = relationship_memory_writer
        self._relationship_history_provider = relationship_history_provider
        self._relationship_summary_provider = relationship_summary_provider
        self._workspace_id_provider = workspace_id_provider
        self._job_events = job_event_log
        self._opportunities: dict[str, dict[str, Any]] = {}
        self._resolved_opportunities: dict[str, tuple[str, str]] = {}
        self._opportunity_acceptance_claims: dict[str, _HeartbeatAcceptanceClaim] = {}
        self._resolved_acceptances: dict[str, dict[str, Any]] = {}
        self._opportunity_lock = Lock()
        self._goals: dict[str, dict[str, Any]] = {}
        self._goal_lock = Lock()
        self._goal_store = goal_store
        self._opportunity_ttl_seconds = opportunity_ttl_seconds
        self._proactive_policy_authority = False
        self._proactive_outcome_observer = None
        self._load_goals()
        self.state.goals = self.goal_snapshot()

    def set_proactive_outcome_observer(self, observer) -> None:
        """Bind the backend policy authority for proactive opportunity outcomes."""
        self._proactive_policy_authority = observer is not None
        self._proactive_outcome_observer = observer

    async def start(self):
        if self._task and not self._task.done():
            return
        self.state.running = True
        self._task = asyncio.create_task(self._run())
        self._expiry_task = asyncio.create_task(self._run_opportunity_expiry())

    async def stop(self):
        self.state.running = False
        if self._task and not self._task.done():
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        if self._expiry_task and not self._expiry_task.done():
            self._expiry_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._expiry_task
        self._expiry_task = None
        self.cancel_opportunities(reason='heartbeat_stopped')
        self._persist_goals()

    async def _run(self):
        while self.state.running:
            await asyncio.sleep(self.state.interval_seconds)
            self.state.tick_count += 1
            self.state.last_tick_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
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

    async def _run_opportunity_expiry(self) -> None:
        while self.state.running:
            with self._opportunity_lock:
                self._expiry_wakeup.clear()
                next_expiry = min(
                    (
                        max(
                            float(item['expires_at']),
                            float(item.get('expiry_retry_at') or 0.0),
                        )
                        for item in self._opportunities.values()
                    ),
                    default=None,
                )
            if next_expiry is None:
                await self._expiry_wakeup.wait()
                continue
            timeout = max(0.0, next_expiry - time.time())
            try:
                await asyncio.wait_for(self._expiry_wakeup.wait(), timeout=timeout)
            except TimeoutError:
                self.expire_opportunities()

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
            # Once the durable proactive policy service is bound, legacy
            # relationship behavior remains presentation-only and cannot emit
            # a second, ungoverned proactive opportunity source.
            if not self._proactive_policy_authority and self._emit_opportunity_job(event):
                self.state.behavior_events.append(event)
                self.state.behavior_events = self.state.behavior_events[-20:]
            self.state.last_relationship_snapshot = {
                **(self.state.last_relationship_snapshot or {}),
                'proactive_state': proactive_state,
                'behavior_profile': behavior_profile,
            }

    def emit_proactive_opportunity(
        self,
        event: dict[str, Any],
        *,
        workspace_id: str,
    ) -> bool:
        if not self._proactive_policy_authority:
            return False
        if str(event.get('source_kind') or '') != 'completed_turn_followup':
            return False
        return self._emit_opportunity_job(event, workspace_id=workspace_id)

    def proactive_opportunity_ttl_seconds(self) -> float:
        if self._opportunity_ttl_seconds is not None:
            return max(0.01, float(self._opportunity_ttl_seconds))
        return max(60.0, float(self.state.interval_seconds) * 2.0)

    def proactive_interruptible(self) -> bool:
        if self._job_events is None:
            return True
        active = self._job_events.active_job_ids()
        return not any(job_id not in self._opportunities for job_id in active)

    def _emit_opportunity_job(
        self,
        event: dict[str, Any],
        *,
        workspace_id: str | None = None,
    ) -> bool:
        if self._job_events is None:
            return True
        resolved_workspace_id = str(workspace_id or '').strip() or 'default'
        if workspace_id is None and self._workspace_id_provider is not None:
            try:
                resolved_workspace_id = str(self._workspace_id_provider() or 'default').strip() or 'default'
            except Exception:
                logger.exception('Failed to resolve heartbeat workspace id')
        job_id = str(event.get('job_id') or f"heartbeatjob_{uuid.uuid4().hex[:12]}")
        request_id = str(event.get('request_id') or f"heartbeatreq_{uuid.uuid4().hex[:12]}")
        with self._opportunity_lock:
            existing = self._opportunities.get(job_id)
            if existing is not None:
                matches = existing.get('request_id') == request_id
                if matches:
                    self._publish_proactive_behavior(existing)
                return matches
        goal_id = self.register_goal(
            kind=str(event.get('type') or 'proactive'),
            due_at=time.time(),
            priority=self._goal_priority(event),
            expires_at=None,
            payload={'trigger_reason': event.get('trigger_reason')},
        )
        if not goal_id:
            logger.warning('Heartbeat opportunity skipped because the goal queue is at capacity')
            return False
        turn_id = f"heartbeat:{job_id}"
        run_id = f"heartbeat-accept:{job_id}:{request_id}"
        common = {
            'workspace_id': resolved_workspace_id,
            'session_id': str(event.get('session_id') or 'heartbeat'),
            'turn_id': turn_id,
            'job_id': job_id,
            'request_id': request_id,
            'interruption_epoch': 0,
            'source': 'heartbeat',
            'timestamp': time.time(),
            'run_id': run_id,
        }
        data = {
            'behaviorType': event.get('type'),
            'tick': self.state.tick_count,
            'triggerReason': event.get('trigger_reason'),
            'reasonCode': event.get('reason_code') or event.get('trigger_reason'),
            'sceneConfidence': event.get('scene_confidence', 0.0),
            'userWorkState': event.get('user_work_state', 'unknown'),
            'expectedBenefit': event.get('expected_benefit', 'unspecified'),
            'interruptCost': event.get('interrupt_cost', 'unknown'),
            'goalId': goal_id,
        }
        for source_key, output_key in (
            ('frame_id', 'frameId'),
            ('source_kind', 'sourceKind'),
            ('source_id', 'sourceId'),
        ):
            if event.get(source_key):
                data[output_key] = event[source_key]
        requested_expiry = event.get('expires_at')
        expires_at = (
            float(requested_expiry)
            if requested_expiry is not None
            else time.time() + self.proactive_opportunity_ttl_seconds()
        )
        if not math.isfinite(expires_at) or expires_at <= time.time():
            self._finish_goal(goal_id, 'expired', 'delivery_window_elapsed')
            return False
        try:
            self._job_events.append(status='created', data={**data, 'phase': 'opportunity_requested'}, **common)
        except CompanionJobCapacityError:
            logger.warning('Heartbeat opportunity skipped because the job event log is at active capacity')
            self._finish_goal(goal_id, 'failed', 'job_event_capacity')
            return False
        event['job_id'] = job_id
        event['request_id'] = request_id
        event['goal_id'] = goal_id
        event['expires_at'] = expires_at
        with self._opportunity_lock:
            self._opportunities[job_id] = {
                **common,
                'job_id': job_id,
                'expires_at': expires_at,
                'goal_id': goal_id,
                'frame_id': event.get('frame_id'),
                'source_kind': event.get('source_kind'),
                'source_id': event.get('source_id'),
                'content_code': 'completed_turn_followup',
                'tick': event.get('tick', self.state.tick_count),
                'at': event.get('at') or datetime.fromtimestamp(
                    common['timestamp'],
                    tz=timezone.utc,
                ).isoformat().replace('+00:00', 'Z'),
                'data': data,
                'lifecycle_phase': 'created',
            }
            pending = dict(self._opportunities[job_id])
        self._publish_proactive_behavior(pending)
        self._expiry_wakeup.set()
        return True

    def _publish_proactive_behavior(self, pending: dict[str, Any]) -> None:
        if pending.get('source_kind') != 'completed_turn_followup':
            return
        job_id = str(pending.get('job_id') or '')
        if not job_id or any(item.get('job_id') == job_id for item in self.state.behavior_events):
            return
        behavior = {
            'type': 'completed_turn_followup',
            'tick': pending.get('tick', 0),
            'at': str(pending.get('at') or ''),
            'job_id': job_id,
            'request_id': str(pending.get('request_id') or ''),
            'source_kind': 'completed_turn_followup',
            'source_id': str(pending.get('source_id') or ''),
            'trigger_reason': 'completed_turn_followup',
            'reason_code': str((pending.get('data') or {}).get('reasonCode') or 'completed_turn_followup'),
            'scene_confidence': float((pending.get('data') or {}).get('sceneConfidence', 0.0) or 0.0),
            'user_work_state': str((pending.get('data') or {}).get('userWorkState') or 'unknown'),
            'expected_benefit': str((pending.get('data') or {}).get('expectedBenefit') or 'unspecified'),
            'interrupt_cost': str((pending.get('data') or {}).get('interruptCost') or 'unknown'),
            'frame_id': str(pending.get('frame_id') or ''),
            'expires_at': float(pending.get('expires_at') or 0.0),
            'content_code': 'completed_turn_followup',
            'content_params': {},
            # Legacy sinks may still require text. This fixed compatibility
            # fallback is never derived from a turn, model reply, or tool data;
            # current renderers localize the closed content_code instead.
            'message': 'Would you like to continue where we left off?',
            'proactive_state': {
                'can_proactively_reach_out': True,
                'trigger_reason': 'completed_turn_followup',
            },
        }
        self.state.behavior_events.append(behavior)
        self.state.behavior_events = self.state.behavior_events[-20:]

    def _remove_proactive_behavior(self, job_id: str) -> None:
        self.state.behavior_events = [
            item for item in self.state.behavior_events if item.get('job_id') != job_id
        ]

    def _append_opportunity_phase(
        self,
        pending: Mapping[str, Any],
        *,
        status: str,
        phase: str,
    ) -> None:
        if self._job_events is None:
            return
        common = {
            key: pending[key]
            for key in (
                'workspace_id', 'session_id', 'turn_id', 'job_id', 'request_id',
                'interruption_epoch', 'source', 'run_id',
            )
        }
        self._job_events.append(
            status=status,
            timestamp=time.time(),
            data={**dict(pending['data']), 'phase': phase},
            **common,
        )

    def claim_opportunity_acceptance(
        self,
        acceptance: HeartbeatOpportunityAcceptance,
        *,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        """Atomically fence one accepted opportunity before semantic execution."""
        current = time.time() if now is None else float(now)
        with self._opportunity_lock:
            pending = self._opportunities.get(acceptance.job_id)
            if pending is None:
                return None
            if (
                str(pending.get('request_id') or '') != acceptance.request_id
                or str(pending.get('workspace_id') or '') != acceptance.workspace_id
                or str(pending.get('session_id') or '') != acceptance.session_id
                or current >= float(pending.get('expires_at') or 0.0)
                or self._job_events is None
            ):
                return None
            claimed = self._opportunity_acceptance_claims.get(acceptance.job_id)
            if (
                not self._job_events.is_active(acceptance.job_id, acceptance.workspace_id)
                and (claimed is None or claimed.identity != acceptance.identity)
            ):
                return None
            if claimed is not None and claimed.identity != acceptance.identity:
                return None
            if claimed is None:
                self._opportunity_acceptance_claims[acceptance.job_id] = (
                    _HeartbeatAcceptanceClaim(acceptance.identity)
                )
            return dict(pending)

    def begin_opportunity_acceptance_execution(
        self,
        acceptance: HeartbeatOpportunityAcceptance,
        event_loop: asyncio.AbstractEventLoop,
    ) -> asyncio.Event | None:
        with self._opportunity_lock:
            claim = self._opportunity_acceptance_claims.get(acceptance.job_id)
            if claim is None or claim.identity != acceptance.identity:
                return None
            claim.event_loop = event_loop
            if claim.cancellation_outcome is not None:
                return None
            claim.phase = "executing"
            pending = self._opportunities.get(acceptance.job_id)
            if (
                pending is not None
                and self._job_events is not None
                and self._job_events.is_active(acceptance.job_id, acceptance.workspace_id)
                and pending.get('lifecycle_phase') != 'running'
            ):
                self._append_opportunity_phase(pending, status='progress', phase='offered')
                self._append_opportunity_phase(pending, status='running', phase='accepted')
                self._append_opportunity_phase(pending, status='progress', phase='running')
                pending['lifecycle_phase'] = 'running'
            return claim.cancellation_event

    def replayable_opportunity_acceptance(
        self,
        acceptance: HeartbeatOpportunityAcceptance,
    ) -> dict[str, Any] | None:
        with self._opportunity_lock:
            resolved = self._resolved_acceptances.get(acceptance.job_id)
            if resolved is None:
                return None
            identity = resolved.get("acceptance_identity")
            if identity != acceptance.identity:
                return None
            return dict(resolved)

    def release_opportunity_acceptance(
        self,
        acceptance: HeartbeatOpportunityAcceptance,
    ) -> bool:
        with self._opportunity_lock:
            claim = self._opportunity_acceptance_claims.get(acceptance.job_id)
            if claim is None or claim.identity != acceptance.identity:
                return False
            self._opportunity_acceptance_claims.pop(acceptance.job_id, None)
            return True

    def resolve_opportunity(
        self,
        *,
        job_id: str,
        request_id: str,
        outcome: str,
        reason: str | None = None,
        _acceptance_terminal: bool = False,
    ) -> bool:
        normalized = str(outcome or '').strip().lower()
        if normalized not in {'delivered', 'suppressed', 'expired', 'cancelled', 'failed'}:
            return False
        with self._opportunity_lock:
            resolved = self._resolved_opportunities.get(job_id)
            if resolved is not None:
                return resolved == (request_id, normalized)
            pending = self._opportunities.get(job_id)
            if pending is None or pending.get('request_id') != request_id:
                return False
            acceptance_claim = self._opportunity_acceptance_claims.get(job_id)
            if acceptance_claim is not None and not _acceptance_terminal:
                if acceptance_claim.phase == "sealed":
                    return False
                if normalized in {'cancelled', 'expired'}:
                    acceptance_claim.request_cancellation(normalized, reason)
                    return True
                return False
            if self._job_events is None or not self._job_events.is_active(job_id):
                return False
            if normalized == 'cancelled':
                status = 'cancelled'
            elif normalized == 'failed':
                status = 'failed'
            else:
                status = 'completed'
            common = {key: pending[key] for key in (
                'workspace_id', 'session_id', 'turn_id', 'job_id', 'request_id',
                'interruption_epoch', 'source',
            )}
            for key in ('conversation_id', 'operation_id', 'run_id', 'step_index'):
                if key in pending:
                    common[key] = pending[key]
            observer = self._proactive_outcome_observer
            if observer is not None and pending.get('source_kind'):
                try:
                    if observer(dict(pending), normalized) is False:
                        return False
                except Exception:
                    logger.exception('Failed to persist proactive opportunity outcome')
                    return False
            try:
                self._job_events.append(
                    status=status,
                    timestamp=time.time(),
                    data={
                        **pending['data'],
                        'phase': 'opportunity_resolved',
                        'outcome': normalized,
                        **({'reason': reason} if reason else {}),
                    },
                    **common,
                )
            except (CompanionJobCapacityError, KeyError, ValueError):
                logger.exception('Failed to append heartbeat opportunity terminal event')
                return False
            self._opportunities.pop(job_id, None)
            self._opportunity_acceptance_claims.pop(job_id, None)
            if _acceptance_terminal:
                self._resolved_acceptances[job_id] = {
                    **pending,
                    "acceptance_identity": (
                        job_id,
                        request_id,
                        str(pending.get("workspace_id") or ""),
                        str(pending.get("session_id") or ""),
                    ),
                }
                if len(self._resolved_acceptances) > MAX_HEARTBEAT_GOALS * 4:
                    self._resolved_acceptances.pop(next(iter(self._resolved_acceptances)))
            self._remove_proactive_behavior(job_id)
            self._resolved_opportunities[job_id] = (request_id, normalized)
            if len(self._resolved_opportunities) > MAX_HEARTBEAT_GOALS * 4:
                self._resolved_opportunities.pop(next(iter(self._resolved_opportunities)))
            self._finish_goal(str(pending.get('goal_id') or ''), normalized, reason)
        return True

    def finalize_opportunity_acceptance(
        self,
        acceptance: HeartbeatOpportunityAcceptance,
        *,
        outcome: str,
        reason: str,
    ) -> bool:
        with self._opportunity_lock:
            claim = self._opportunity_acceptance_claims.get(acceptance.job_id)
            if claim is None or claim.identity != acceptance.identity:
                return False
            claim.phase = "sealed"
        return self.resolve_opportunity(
            job_id=acceptance.job_id,
            request_id=acceptance.request_id,
            outcome=outcome,
            reason=reason,
            _acceptance_terminal=True,
        )

    def acknowledge_committed_acceptance(
        self,
        acceptance: HeartbeatOpportunityAcceptance,
        *,
        outcome: str,
        reason: str,
    ) -> bool:
        """Clean accepted opportunity state after the TurnService terminal projection."""
        normalized = str(outcome or "").strip().lower()
        if normalized not in {"delivered", "cancelled", "failed"}:
            return False
        with self._opportunity_lock:
            resolved = self._resolved_acceptances.get(acceptance.job_id)
            if resolved is not None:
                return resolved.get("acceptance_identity") == acceptance.identity
            claim = self._opportunity_acceptance_claims.get(acceptance.job_id)
            pending = self._opportunities.get(acceptance.job_id)
            if (
                claim is None
                or claim.identity != acceptance.identity
                or pending is None
                or str(pending.get("request_id") or "") != acceptance.request_id
            ):
                return False
            claim.phase = "sealed"
            observer = self._proactive_outcome_observer
            if observer is not None and pending.get("source_kind"):
                try:
                    if observer(dict(pending), normalized) is False:
                        return False
                except Exception:
                    logger.exception("Failed to persist proactive opportunity outcome")
                    return False
            self._opportunities.pop(acceptance.job_id, None)
            self._opportunity_acceptance_claims.pop(acceptance.job_id, None)
            self._resolved_acceptances[acceptance.job_id] = {
                **pending,
                "acceptance_identity": acceptance.identity,
            }
            if len(self._resolved_acceptances) > MAX_HEARTBEAT_GOALS * 4:
                self._resolved_acceptances.pop(next(iter(self._resolved_acceptances)))
            self._remove_proactive_behavior(acceptance.job_id)
            self._resolved_opportunities[acceptance.job_id] = (
                acceptance.request_id,
                normalized,
            )
            if len(self._resolved_opportunities) > MAX_HEARTBEAT_GOALS * 4:
                self._resolved_opportunities.pop(next(iter(self._resolved_opportunities)))
            self._finish_goal(str(pending.get("goal_id") or ""), normalized, reason)
        return True

    def finalize_deferred_acceptance_cancellation(
        self,
        acceptance: HeartbeatOpportunityAcceptance,
    ) -> bool:
        with self._opportunity_lock:
            claim = self._opportunity_acceptance_claims.get(acceptance.job_id)
            if (
                claim is None
                or claim.identity != acceptance.identity
                or claim.cancellation_outcome is None
            ):
                return False
            outcome = claim.cancellation_outcome
            reason = claim.cancellation_reason or "acceptance_cancelled"
        return self.finalize_opportunity_acceptance(
            acceptance,
            outcome=outcome,
            reason=reason,
        )

    def cancel_proactive_opportunities(
        self,
        *,
        workspace_id: str,
        source_kind: str,
        reason: str,
        frame_id: str | None = None,
    ) -> int:
        with self._opportunity_lock:
            pending = [
                (job_id, str(item.get('request_id') or ''))
                for job_id, item in self._opportunities.items()
                if item.get('workspace_id') == workspace_id
                and item.get('source_kind') == source_kind
                and (frame_id is None or item.get('frame_id') == frame_id)
            ]
        resolved = 0
        for job_id, request_id in pending:
            if self.resolve_opportunity(
                job_id=job_id,
                request_id=request_id,
                outcome='cancelled',
                reason=reason,
            ):
                resolved += 1
        return resolved

    @staticmethod
    def _goal_priority(event: dict[str, Any]) -> int:
        kind = str(event.get('type') or '').lower()
        if kind in {'reminder', 'care_signal'}:
            return 2
        if kind in {'suggestion', 'idle_prompt'}:
            return 1
        return 0

    def register_goal(
        self,
        *,
        kind: str,
        due_at: float | None = None,
        priority: int = 0,
        cooldown_seconds: float = 0.0,
        expires_at: float | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        now = time.time()
        goal_id = f"heartbeatgoal_{uuid.uuid4().hex[:12]}"
        raw_due = now if due_at is None else float(due_at)
        raw_expiry = None if expires_at is None else float(expires_at)
        raw_cooldown = float(cooldown_seconds)
        if not math.isfinite(raw_due) or (raw_expiry is not None and not math.isfinite(raw_expiry)) or not math.isfinite(raw_cooldown):
            return ''
        due = max(0.0, raw_due)
        expiry = None if raw_expiry is None else max(due, raw_expiry)
        cooldown = max(0.0, raw_cooldown)
        goal = {
            'goal_id': goal_id,
            'kind': str(kind or 'proactive'),
            'due_at': due,
            'priority': max(-10, min(10, int(priority))),
            'cooldown_seconds': cooldown,
            'expires_at': expiry,
            'state': 'pending',
            'created_at': now,
            'updated_at': now,
            'payload': dict(payload or {}),
        }
        snapshot: list[dict[str, Any]] = []
        with self._goal_lock:
            if len(self._goals) >= MAX_HEARTBEAT_GOALS:
                terminal_id = next((key for key, value in self._goals.items() if value['state'] in {'completed', 'cancelled', 'expired', 'failed'}), None)
                if terminal_id is None:
                    return ''
                self._goals.pop(terminal_id, None)
            self._goals[goal_id] = goal
            snapshot = self._goal_snapshot_unlocked()
            self.state.goals = snapshot
        self._persist_goal_snapshot(snapshot)
        return goal_id

    def _finish_goal(self, goal_id: str, outcome: str, reason: str | None = None) -> None:
        if not goal_id:
            return
        snapshot: list[dict[str, Any]] = []
        with self._goal_lock:
            goal = self._goals.get(goal_id)
            if goal is None:
                return
            if str(goal.get('state') or '') in {'completed', 'cancelled', 'expired', 'failed', 'interrupted'}:
                return
            state = 'completed' if outcome in {'delivered', 'suppressed'} else outcome
            goal['state'] = state
            goal['updated_at'] = time.time()
            if reason:
                goal['reason'] = reason
            snapshot = self._goal_snapshot_unlocked()
            self.state.goals = snapshot
        self._persist_goal_snapshot(snapshot)

    def cancel_goal(self, goal_id: str, reason: str = 'cancelled') -> bool:
        """Cancel a goal exactly once and resolve any linked opportunity job.

        The operation is idempotent: cancelling an already-cancelled goal succeeds,
        while terminal goals with another outcome are left unchanged.
        """
        normalized_id = str(goal_id or '').strip()
        if not normalized_id:
            return False
        with self._goal_lock:
            goal = self._goals.get(normalized_id)
            if goal is None:
                return False
            current_state = str(goal.get('state') or 'pending')
            if current_state == 'cancelled':
                return True
            if current_state in {'completed', 'failed', 'expired', 'interrupted'}:
                return False
        with self._opportunity_lock:
            linked = next(
                (
                    (job_id, str(item.get('request_id') or ''))
                    for job_id, item in self._opportunities.items()
                    if str(item.get('goal_id') or '') == normalized_id
                ),
                None,
            )
        if linked is not None and linked[1]:
            resolved = self.resolve_opportunity(
                job_id=linked[0],
                request_id=linked[1],
                outcome='cancelled',
                reason=reason,
            )
            if resolved:
                return True
            with self._goal_lock:
                return str(self._goals.get(normalized_id, {}).get('state') or '') == 'cancelled'
        self._finish_goal(normalized_id, 'cancelled', reason)
        return True

    def _load_goals(self) -> None:
        if self._goal_store is None:
            return
        try:
            loaded = self._goal_store.load()
        except Exception:
            logger.exception('Failed to load heartbeat goals')
            return
        changed = False
        now = time.time()
        with self._goal_lock:
            for goal in loaded[-MAX_HEARTBEAT_GOALS:]:
                goal_id = str(goal.get('goal_id') or '').strip()
                if goal_id:
                    restored = dict(goal)
                    if str(restored.get('state') or 'pending') not in {
                        'completed', 'cancelled', 'expired', 'failed', 'interrupted',
                    }:
                        restored['state'] = 'interrupted'
                        restored['reason'] = 'runtime_restart'
                        restored['updated_at'] = now
                        changed = True
                    self._goals[goal_id] = restored
            snapshot = self._goal_snapshot_unlocked()
        if changed:
            self._persist_goal_snapshot(snapshot)

    def _persist_goal_snapshot(self, goals: list[dict[str, Any]]) -> None:
        if self._goal_store is None:
            return
        try:
            self._goal_store.save(goals)
        except Exception:
            logger.exception('Failed to persist heartbeat goals')

    def _persist_goals(self) -> None:
        self._persist_goal_snapshot(self.goal_snapshot())

    def _goal_snapshot_unlocked(self) -> list[dict[str, Any]]:
        goals = []
        for goal in self._goals.values():
            try:
                priority = max(-10, min(10, int(goal.get('priority', 0))))
                due_at = max(0.0, float(goal.get('due_at', 0.0)))
            except (TypeError, ValueError, OverflowError):
                continue
            goals.append({**goal, 'priority': priority, 'due_at': due_at, 'payload': dict(goal.get('payload') or {})})
        goals.sort(key=lambda goal: (-int(goal.get('priority', 0)), float(goal.get('due_at', 0.0)), str(goal.get('goal_id'))))
        return goals[:MAX_HEARTBEAT_GOALS]

    def goal_snapshot(self) -> list[dict[str, Any]]:
        with self._goal_lock:
            return self._goal_snapshot_unlocked()

    def expire_opportunities(self, now: float | None = None) -> int:
        current = time.time() if now is None else float(now)
        retry_clock = time.time()
        with self._opportunity_lock:
            expired = [
                (job_id, str(item['request_id']))
                for job_id, item in self._opportunities.items()
                if current >= float(item['expires_at'])
                and retry_clock >= float(item.get('expiry_retry_at') or 0.0)
            ]
        resolved = 0
        for job_id, request_id in expired:
            if self.resolve_opportunity(
                job_id=job_id,
                request_id=request_id,
                outcome='expired',
                reason='delivery_window_elapsed',
            ):
                resolved += 1
                continue
            with self._opportunity_lock:
                pending = self._opportunities.get(job_id)
                if pending is None or pending.get('request_id') != request_id:
                    continue
                attempts = int(pending.get('expiry_retry_attempts') or 0) + 1
                backoff = min(
                    OPPORTUNITY_EXPIRY_RETRY_MAX_SECONDS,
                    OPPORTUNITY_EXPIRY_RETRY_BASE_SECONDS * (2 ** min(attempts, 7)),
                )
                pending['expiry_retry_attempts'] = attempts
                pending['expiry_retry_at'] = retry_clock + backoff
        return resolved

    def cancel_opportunities(self, *, reason: str) -> int:
        with self._opportunity_lock:
            pending = [(job_id, str(item['request_id'])) for job_id, item in self._opportunities.items()]
        resolved = 0
        for job_id, request_id in pending:
            if self.resolve_opportunity(job_id=job_id, request_id=request_id, outcome='cancelled', reason=reason):
                resolved += 1
        return resolved

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
            'text': f"結崎 {companion.get('name', companion.get('id'))} 产生了一次关系事件: kind={event_kind}, mood={current['mood']}, affinity={current['affinity']:.3f}, energy={current['energy']:.3f}",
            'kind': event_kind,
            'source_id': str(companion['id']),
            'evidence': current,
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


class HeartbeatOpportunityTurnBridge:
    """Execute only explicitly accepted opportunities through TurnService."""

    def __init__(
        self,
        *,
        scheduler: HeartbeatScheduler | None,
        turn_service: TurnService | None,
        authorizer: HeartbeatOpportunityAuthorizer | None,
    ) -> None:
        self._scheduler = scheduler
        self._turn_service = turn_service
        self._authorizer = authorizer
        self._lock = asyncio.Lock()
        self._completed: dict[tuple[str, str, str, str], TurnCommit] = {}

    async def accept(
        self,
        acceptance: HeartbeatOpportunityAcceptance,
    ) -> HeartbeatAcceptedTurn:
        if self._scheduler is None or self._turn_service is None:
            raise HeartbeatOpportunityUnavailableError(
                "heartbeat scheduler and TurnService are required"
            )
        if self._authorizer is None:
            raise HeartbeatOpportunityUnavailableError(
                "heartbeat opportunity authorization is required"
            )

        async with self._lock:
            cached = self._completed.get(acceptance.identity)
            if cached is not None:
                self._finalize_commit(acceptance, cached)
                return HeartbeatAcceptedTurn(
                    acceptance=acceptance,
                    commit=cached,
                    replayed_delivery=True,
                )

            pending = self._scheduler.claim_opportunity_acceptance(acceptance)
            if pending is None:
                replayable = self._scheduler.replayable_opportunity_acceptance(acceptance)
                if replayable is None:
                    raise HeartbeatOpportunityConflictError(
                        "heartbeat opportunity is not active for this identity"
                    )
                await self._authorize(acceptance, replayable)
                commit = await self._turn_service.execute_heartbeat(
                    self._turn_request(acceptance, replayable)
                )
                self._completed[acceptance.identity] = commit
                return HeartbeatAcceptedTurn(
                    acceptance=acceptance,
                    commit=commit,
                    replayed_delivery=True,
                )

            try:
                await self._authorize(acceptance, pending)
            except HeartbeatOpportunityAuthorizationError:
                self._scheduler.release_opportunity_acceptance(acceptance)
                raise

            cancellation_event = self._scheduler.begin_opportunity_acceptance_execution(
                acceptance,
                asyncio.get_running_loop(),
            )
            if cancellation_event is None:
                self._scheduler.finalize_deferred_acceptance_cancellation(acceptance)
                raise HeartbeatOpportunityConflictError(
                    "heartbeat opportunity expired or was cancelled"
                )

            semantic_request = self._turn_request(acceptance, pending)
            execute_task = asyncio.create_task(
                self._turn_service.execute_heartbeat(semantic_request)
            )
            cancellation_task = asyncio.create_task(cancellation_event.wait())
            try:
                done, _pending_tasks = await asyncio.wait(
                    {execute_task, cancellation_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancellation_task in done and execute_task not in done:
                    execute_task.cancel()
                try:
                    commit = await execute_task
                except asyncio.CancelledError:
                    # A cancellation can land after the durable commit while
                    # its required projections are still acknowledging. The
                    # same identity reloads that commit and resumes ACKs; it
                    # must never rerun the semantic pipeline.
                    commit = await self._turn_service.execute_heartbeat(
                        semantic_request
                    )
            except BaseException:
                self._scheduler.release_opportunity_acceptance(acceptance)
                raise
            finally:
                cancellation_task.cancel()
                await asyncio.gather(cancellation_task, return_exceptions=True)

            self._completed[acceptance.identity] = commit
            if len(self._completed) > MAX_HEARTBEAT_GOALS * 4:
                self._completed.pop(next(iter(self._completed)))
            self._finalize_commit(acceptance, commit)
            return HeartbeatAcceptedTurn(acceptance=acceptance, commit=commit)

    def _finalize_commit(
        self,
        acceptance: HeartbeatOpportunityAcceptance,
        commit: TurnCommit,
    ) -> None:
        terminal_outcome = {
            "completed": "delivered",
            "cancelled": "cancelled",
            "failed": "failed",
            "unknown_effect": "failed",
        }[commit.outcome]
        if self._scheduler is None:
            return
        finalized = self._scheduler.acknowledge_committed_acceptance(
            acceptance,
            outcome=terminal_outcome,
            reason=f"accepted_turn_{commit.outcome}",
        )
        if (
            not finalized
            and self._scheduler.replayable_opportunity_acceptance(acceptance) is None
        ):
            logger.warning(
                "Heartbeat turn commit could not finalize its acceptance: %s",
                acceptance.job_id,
            )

    async def _authorize(
        self,
        acceptance: HeartbeatOpportunityAcceptance,
        pending: Mapping[str, Any],
    ) -> None:
        if self._authorizer is None:
            raise HeartbeatOpportunityUnavailableError(
                "heartbeat opportunity authorization is required"
            )
        try:
            authorized = self._authorizer(acceptance, pending)
            if inspect.isawaitable(authorized):
                authorized = await authorized
        except Exception as exc:
            raise HeartbeatOpportunityAuthorizationError(
                "heartbeat opportunity authorization failed"
            ) from exc
        if authorized is not True:
            raise HeartbeatOpportunityAuthorizationError(
                "heartbeat opportunity was denied by policy"
            )

    @staticmethod
    def _turn_request(
        acceptance: HeartbeatOpportunityAcceptance,
        pending: Mapping[str, Any],
    ) -> SemanticTurnRequest:
        turn_id = f"heartbeat:{acceptance.job_id}"
        run_id = f"heartbeat-accept:{acceptance.job_id}:{acceptance.request_id}"
        permission_scope = f"heartbeat:{acceptance.workspace_id}"
        return SemanticTurnRequest(
            session_id=acceptance.session_id,
            workspace_id=acceptance.workspace_id,
            request_id=acceptance.request_id,
            turn_id=turn_id,
            generation_id=f"generation:{turn_id}",
            messages=({
                "role": "user",
                "content": "Continue from the explicitly accepted heartbeat opportunity.",
            },),
            context_options={
                "max_tokens": 512,
                "permission_scope": permission_scope,
            },
            extra={
                "job_id": acceptance.job_id,
                "run_id": run_id,
                "acceptance_id": run_id,
                "permission_scope": permission_scope,
                "heartbeat_opportunity": {
                    "job_id": acceptance.job_id,
                    "request_id": acceptance.request_id,
                    "workspace_id": acceptance.workspace_id,
                    "session_id": acceptance.session_id,
                    "goal_id": str(pending.get("goal_id") or ""),
                    "source_kind": str(pending.get("source_kind") or "heartbeat"),
                    "source_id": str(pending.get("source_id") or ""),
                },
                "configured_budget": {"output_tokens": 512},
            },
        )
