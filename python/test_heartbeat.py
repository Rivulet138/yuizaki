import asyncio
import pytest

from modules.agent.companion_events import CompanionJobEventLog
from modules.system.companion_policy import build_base_behavior_event, build_behavior_profile, evaluate_proactive_policy
from modules.system.heartbeat import MAX_HEARTBEAT_GOALS, HeartbeatScheduler
from modules.system.heartbeat_goal_store import HeartbeatGoalStore


async def _wait_for(predicate, timeout: float = 0.25):
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        if predicate():
            return True
        if asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(0.005)


def test_heartbeat_defaults_to_low_frequency_desktop_pet_interval():
    scheduler = HeartbeatScheduler()

    assert scheduler.state.interval_seconds == 60


def test_heartbeat_goal_queue_is_bounded_and_orders_priority():
    scheduler = HeartbeatScheduler()
    low = scheduler.register_goal(kind='idle_prompt', priority=0)
    high = scheduler.register_goal(kind='reminder', priority=2)

    goals = scheduler.goal_snapshot()
    assert [goal['goal_id'] for goal in goals[:2]] == [high, low]
    assert all(goal['state'] == 'pending' for goal in goals)


def test_heartbeat_goal_store_restores_bounded_goal_history(tmp_path):
    store = HeartbeatGoalStore(tmp_path / 'heartbeat-goals.json')
    writer = HeartbeatScheduler(goal_store=store)
    goal_id = writer.register_goal(kind='reminder', priority=2)
    writer._finish_goal(goal_id, 'delivered', 'test')

    restored = HeartbeatScheduler(goal_store=HeartbeatGoalStore(tmp_path / 'heartbeat-goals.json'))
    goal = next(goal for goal in restored.goal_snapshot() if goal['goal_id'] == goal_id)
    assert goal['state'] == 'completed'
    assert goal['reason'] == 'test'


def test_heartbeat_goal_store_rejects_non_finite_numbers(tmp_path):
    store = HeartbeatGoalStore(tmp_path / 'heartbeat-goals.json')
    base = {
        'goal_id': 'goal-1', 'kind': 'reminder', 'due_at': 1.0,
        'created_at': 1.0, 'updated_at': 1.0, 'cooldown_seconds': 1.0, 'priority': 0,
    }
    for key in ('due_at', 'created_at', 'updated_at', 'cooldown_seconds', 'priority', 'expires_at'):
        value = {**base, key: float('nan')}
        assert not store._valid_goal(value)
        value = {**base, key: float('inf')}
        assert not store._valid_goal(value)


def test_heartbeat_register_goal_rejects_non_finite_runtime_values():
    scheduler = HeartbeatScheduler()
    assert scheduler.register_goal(kind='reminder', due_at=float('nan')) == ''
    assert scheduler.register_goal(kind='reminder', expires_at=float('inf')) == ''
    assert scheduler.register_goal(kind='reminder', cooldown_seconds=float('nan')) == ''


def test_heartbeat_goal_store_interrupts_unrecoverable_pending_goals_on_restart(tmp_path):
    path = tmp_path / 'heartbeat-goals.json'
    writer = HeartbeatScheduler(goal_store=HeartbeatGoalStore(path))
    goal_id = writer.register_goal(kind='reminder', priority=2)

    restored = HeartbeatScheduler(goal_store=HeartbeatGoalStore(path))

    goal = next(goal for goal in restored.goal_snapshot() if goal['goal_id'] == goal_id)
    assert goal['state'] == 'interrupted'
    assert goal['reason'] == 'runtime_restart'
    persisted = HeartbeatGoalStore(path).load()
    persisted_goal = next(goal for goal in persisted if goal['goal_id'] == goal_id)
    assert persisted_goal['state'] == 'interrupted'


def test_heartbeat_opportunity_tracks_goal_lifecycle():
    job_events = CompanionJobEventLog()
    scheduler = HeartbeatScheduler(job_event_log=job_events)
    scheduler.state.tick_count = 1
    scheduler._emit_opportunity_job({'type': 'reminder', 'trigger_reason': 'test'})

    created = job_events.snapshot()[0]
    goal_id = created['data']['goalId']
    assert goal_id
    assert scheduler.goal_snapshot()[0]['state'] == 'pending'

    assert scheduler.resolve_opportunity(
        job_id=created['jobId'], request_id=created['requestId'], outcome='delivered',
    ) is True
    goal = next(goal for goal in scheduler.goal_snapshot() if goal['goal_id'] == goal_id)
    assert goal['state'] == 'completed'


def test_heartbeat_cancel_goal_is_idempotent_and_cancels_linked_job():
    job_events = CompanionJobEventLog()
    scheduler = HeartbeatScheduler(job_event_log=job_events)
    scheduler.state.tick_count = 1
    scheduler._emit_opportunity_job({'type': 'reminder', 'trigger_reason': 'test'})
    created = job_events.snapshot()[0]
    goal_id = created['data']['goalId']

    assert scheduler.cancel_goal(goal_id, reason='user_request') is True
    assert scheduler.cancel_goal(goal_id, reason='duplicate_request') is True
    goal = next(goal for goal in scheduler.goal_snapshot() if goal['goal_id'] == goal_id)
    assert goal['state'] == 'cancelled'
    assert goal['reason'] == 'user_request'
    terminal = job_events.snapshot()[-1]
    assert terminal['status'] == 'cancelled'
    assert terminal['data']['reason'] == 'user_request'


@pytest.mark.asyncio
async def test_heartbeat_scheduler_ticks():
    scheduler = HeartbeatScheduler(interval_seconds=0)
    await scheduler.start()
    assert await _wait_for(lambda: scheduler.state.tick_count >= 1)
    await scheduler.stop()

    assert scheduler.state.tick_count >= 1
    assert scheduler.state.last_tick_at is not None
    assert 'mood' in scheduler.state.persona


@pytest.mark.asyncio
async def test_heartbeat_uses_recent_trace_for_behavior_text():
    trace = {
        'layers': ['profile'],
        'recall_count': 2,
    }
    scheduler = HeartbeatScheduler(interval_seconds=0, trace_provider=lambda: trace)
    scheduler.state.persona['affinity'] = 0.9
    await scheduler.start()
    await asyncio.sleep(0.01)
    await scheduler.stop()

    if scheduler.state.behavior_events:
        assert '偏好' in scheduler.state.behavior_events[-1]['message'] or '记得' in scheduler.state.behavior_events[-1]['message']


@pytest.mark.asyncio
async def test_heartbeat_persists_relationship_event_with_kind():
    captured = []
    companion = {
        'id': 'default',
        'name': '默认結崎',
        'emotion_state': 'neutral',
        'affinity_state': 0.5,
        'energy_state': 1.0,
    }

    scheduler = HeartbeatScheduler(
        interval_seconds=0,
        companion_provider=lambda: companion,
        relationship_memory_writer=lambda payload: captured.append(payload),
    )
    scheduler.state.tick_count = 4
    await scheduler.start()
    await asyncio.sleep(0.01)
    await scheduler.stop()

    assert captured
    event = captured[-1]['metadata']['relationship_event']
    assert event['kind'] in {'state_snapshot', 'mood_shift', 'trust_shift', 'care_signal'}


@pytest.mark.asyncio
async def test_heartbeat_relationship_writer_does_not_block_event_loop():
    import threading

    captured = []
    writer_finished = threading.Event()
    companion = {
        'id': 'default',
        'name': 'default',
        'emotion_state': 'neutral',
        'affinity_state': 0.5,
        'energy_state': 1.0,
    }

    def slow_writer(payload):
        import time

        time.sleep(0.05)
        captured.append(payload)
        writer_finished.set()

    scheduler = HeartbeatScheduler(
        interval_seconds=0,
        companion_provider=lambda: companion,
        relationship_memory_writer=slow_writer,
    )
    scheduler.state.tick_count = 4
    await scheduler.start()
    await asyncio.sleep(0.01)
    await scheduler.stop()

    assert scheduler.state.tick_count >= 5
    await asyncio.wait_for(asyncio.to_thread(writer_finished.wait), timeout=0.5)
    assert captured


@pytest.mark.asyncio
async def test_heartbeat_behavior_uses_relationship_history_to_adjust_prompt():
    trace = {'layers': ['session'], 'recall_count': 1}
    scheduler = HeartbeatScheduler(
        interval_seconds=0,
        trace_provider=lambda: trace,
        relationship_history_provider=lambda: [{'kind': 'trust_shift'}],
    )
    scheduler.state.persona['affinity'] = 0.9
    await scheduler.start()
    await asyncio.sleep(0.01)
    await scheduler.stop()

    if scheduler.state.behavior_events:
        latest = scheduler.state.behavior_events[-1]
        assert latest['prompt'] in {'relationship-warmth', 'memory-recall', 'focus-current-session'}


@pytest.mark.asyncio
async def test_heartbeat_behavior_uses_support_request_history():
    scheduler = HeartbeatScheduler(
        interval_seconds=0,
        relationship_history_provider=lambda: [{'kind': 'support_request'}],
    )
    scheduler.state.persona['mood'] = 'gentle'
    scheduler.state.tick_count = 2
    await scheduler.start()
    await asyncio.sleep(0.01)
    await scheduler.stop()

    if scheduler.state.behavior_events:
        latest = scheduler.state.behavior_events[-1]
        assert latest['prompt'] in {'supportive-response', 'gentle-support'}


@pytest.mark.asyncio
async def test_heartbeat_behavior_uses_relationship_stage_for_budget_and_tone():
    scheduler = HeartbeatScheduler(
        interval_seconds=0,
        relationship_summary_provider=lambda: {'relationship_stage': 'close', 'recent_gratitude_count': 2, 'milestone_count': 3},
    )
    scheduler.state.persona['mood'] = 'warm'
    scheduler.state.tick_count = 2
    await scheduler.start()
    await asyncio.sleep(0.01)
    await scheduler.stop()

    if scheduler.state.behavior_events:
        latest = scheduler.state.behavior_events[-1]
        assert '很熟悉' in latest['message'] or latest['prompt'] in {'memory-recall', 'relationship-warmth'}


def test_evaluate_proactive_policy_suppresses_when_energy_low():
    state = evaluate_proactive_policy(
        mood='tired',
        tick_count=3,
        relationship_summary={'relationship_stage': 'stable', 'milestone_salience': 'low', 'proactive_budget': 1.0},
        recent_kinds=[],
        attachment_style='secure',
        support_style='gentle',
        energy=0.2,
    )
    assert state['can_proactively_reach_out'] is False
    assert 'low-energy' in state['suppression_reasons']
    assert state['readiness_band'] == 'low'


def test_build_base_behavior_event_returns_warm_idle_prompt():
    event = build_base_behavior_event(mood='warm', tick_count=4, warm_interval=4, gentle_interval=3)
    assert event is not None
    assert event['type'] == 'idle_prompt'
    assert event['emotion_id'] == 'happy'


def test_build_behavior_profile_reflects_style_attachment_and_readiness():
    profile = build_behavior_profile(
        support_style='analytical',
        attachment_style='attached',
        temperament='playful',
        readiness_band='high',
    )
    assert profile['tone_bucket'] == 'structured'
    assert profile['closeness_bucket'] == 'close'
    assert profile['expression_bucket'] == 'expressive'
    assert profile['initiative_bucket'] == 'proactive'


@pytest.mark.asyncio
async def test_heartbeat_behavior_event_carries_trigger_reason_and_proactive_state():
    scheduler = HeartbeatScheduler(
        interval_seconds=0,
        relationship_history_provider=lambda: [{'kind': 'support_request'}],
        relationship_summary_provider=lambda: {'relationship_stage': 'stable', 'milestone_salience': 'low', 'proactive_budget': 1.1},
    )
    scheduler.state.persona['mood'] = 'gentle'
    scheduler.state.tick_count = 1
    await scheduler.start()
    assert await _wait_for(lambda: scheduler.state.last_relationship_snapshot is not None)
    await scheduler.stop()

    proactive_state = (scheduler.state.last_relationship_snapshot or {}).get('proactive_state')
    assert isinstance(proactive_state, dict)
    assert proactive_state.get('trigger_reason') in {'recent-support-request', 'gentle-support'}

    if scheduler.state.behavior_events:
        latest = scheduler.state.behavior_events[-1]
        assert latest.get('trigger_reason') in {'recent-support-request', 'gentle-support'}
        assert isinstance(latest.get('proactive_state'), dict)


def test_heartbeat_emits_job_lifecycle_only_for_an_eligible_proactive_opportunity():
    job_events = CompanionJobEventLog()
    scheduler = HeartbeatScheduler(
        workspace_id_provider=lambda: 'workspace-heartbeat',
        job_event_log=job_events,
        relationship_summary_provider=lambda: {
            'relationship_stage': 'stable',
            'milestone_salience': 'low',
            'proactive_budget': 1.1,
        },
    )
    scheduler.state.persona['mood'] = 'gentle'
    scheduler.state.tick_count = 3
    scheduler.state.last_tick_at = '2026-08-09T10:00:00'

    scheduler._emit_behavior_events()

    events = job_events.snapshot()
    assert [event['type'] for event in events] == ['AgentJobCreated']
    assert [event['data']['phase'] for event in events] == ['opportunity_requested']
    assert all(event['source'] == 'heartbeat' for event in events)
    assert all(event['workspaceId'] == 'workspace-heartbeat' for event in events)
    assert job_events.active_job_ids() == [events[0]['jobId']]
    behavior = scheduler.state.behavior_events[-1]
    assert behavior['job_id'] == events[0]['jobId']
    assert behavior['request_id'] == events[0]['requestId']

    assert scheduler.resolve_opportunity(
        job_id=behavior['job_id'],
        request_id=behavior['request_id'],
        outcome='suppressed',
        reason='dnd',
    ) is True
    terminal = job_events.snapshot()[-1]
    assert terminal['type'] == 'AgentJobCompleted'
    assert terminal['data']['outcome'] == 'suppressed'
    assert terminal['data']['reason'] == 'dnd'
    assert job_events.active_job_ids() == []


def test_heartbeat_does_not_publish_behavior_when_job_capacity_is_exhausted():
    job_events = CompanionJobEventLog(max_jobs=1)
    job_events.append(
        workspace_id='default',
        session_id='existing',
        turn_id='turn:existing',
        job_id='existing-job',
        request_id='existing-request',
        interruption_epoch=0,
        source='scheduler',
        timestamp=1.0,
        status='created',
    )
    scheduler = HeartbeatScheduler(job_event_log=job_events)
    scheduler.state.persona['mood'] = 'gentle'
    scheduler.state.tick_count = 3
    scheduler.state.last_tick_at = '2026-08-09T10:00:00'

    scheduler._emit_behavior_events()

    assert scheduler.state.behavior_events == []
    assert job_events.active_job_ids() == ['existing-job']
    heartbeat_goals = scheduler.goal_snapshot()
    assert len(heartbeat_goals) == 1
    assert heartbeat_goals[0]['state'] == 'failed'
    assert heartbeat_goals[0]['reason'] == 'job_event_capacity'


def test_heartbeat_does_not_publish_behavior_when_goal_capacity_is_exhausted():
    job_events = CompanionJobEventLog()
    scheduler = HeartbeatScheduler(job_event_log=job_events)
    for index in range(MAX_HEARTBEAT_GOALS):
        assert scheduler.register_goal(kind=f'existing-{index}')
    scheduler.state.persona['mood'] = 'gentle'
    scheduler.state.tick_count = 3
    scheduler.state.last_tick_at = '2026-08-09T10:00:00'

    scheduler._emit_behavior_events()

    assert scheduler.state.behavior_events == []
    assert job_events.snapshot() == []
    assert len(scheduler.goal_snapshot()) == MAX_HEARTBEAT_GOALS


def test_heartbeat_opportunity_rejects_wrong_identity_and_expires_once():
    job_events = CompanionJobEventLog()
    scheduler = HeartbeatScheduler(job_event_log=job_events)
    scheduler.state.tick_count = 3
    scheduler.state.last_tick_at = '2026-08-09T10:00:00'
    scheduler._emit_opportunity_job({'type': 'suggestion'})
    behavior = {'job_id': job_events.snapshot()[0]['jobId'], 'request_id': job_events.snapshot()[0]['requestId']}

    assert scheduler.resolve_opportunity(job_id=behavior['job_id'], request_id='wrong', outcome='delivered') is False
    assert scheduler.expire_opportunities(now=float('inf')) == 1
    assert scheduler.expire_opportunities(now=float('inf')) == 0
    terminal = job_events.snapshot()[-1]
    assert terminal['data']['outcome'] == 'expired'


def test_heartbeat_failed_delivery_emits_failed_terminal_event():
    job_events = CompanionJobEventLog()
    scheduler = HeartbeatScheduler(job_event_log=job_events)
    scheduler.state.tick_count = 1
    behavior = {'type': 'notification', 'trigger_reason': 'test'}
    scheduler._emit_opportunity_job(behavior)

    assert scheduler.resolve_opportunity(
        job_id=behavior['job_id'],
        request_id=behavior['request_id'],
        outcome='failed',
        reason='all_sinks_failed',
    ) is True
    terminal = job_events.snapshot()[-1]
    assert terminal['type'] == 'AgentJobFailed'
    assert terminal['data']['outcome'] == 'failed'


@pytest.mark.asyncio
async def test_heartbeat_opportunity_expires_without_renderer_snapshot_polling():
    job_events = CompanionJobEventLog()
    scheduler = HeartbeatScheduler(
        interval_seconds=3600,
        opportunity_ttl_seconds=0.03,
        job_event_log=job_events,
    )
    await scheduler.start()
    try:
        scheduler.state.tick_count = 1
        scheduler._emit_opportunity_job({'type': 'suggestion'})
        assert await _wait_for(lambda: len(job_events.snapshot()) == 2, timeout=0.25)
        terminal = job_events.snapshot()[-1]
        assert terminal['data']['outcome'] == 'expired'
        assert job_events.active_job_ids() == []
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_heartbeat_new_opportunity_wakes_an_idle_expiry_loop():
    job_events = CompanionJobEventLog()
    scheduler = HeartbeatScheduler(
        interval_seconds=3600,
        opportunity_ttl_seconds=0.03,
        job_event_log=job_events,
    )
    await scheduler.start()
    try:
        await asyncio.sleep(0)
        assert scheduler._expiry_task is not None
        assert not scheduler._expiry_task.done()
        assert scheduler._opportunities == {}

        scheduler.state.tick_count = 1
        scheduler._emit_opportunity_job({'type': 'suggestion'})

        assert await _wait_for(
            lambda: len(job_events.snapshot()) == 2
            and job_events.snapshot()[-1]['data']['outcome'] == 'expired',
            timeout=0.25,
        )
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_heartbeat_stop_cancels_all_outstanding_opportunities():
    job_events = CompanionJobEventLog()
    scheduler = HeartbeatScheduler(
        interval_seconds=3600,
        opportunity_ttl_seconds=60,
        job_event_log=job_events,
    )
    await scheduler.start()
    scheduler._emit_opportunity_job({'type': 'suggestion'})
    scheduler._emit_opportunity_job({'type': 'reminder'})

    await scheduler.stop()

    terminal = [event for event in job_events.snapshot() if event['status'] == 'cancelled']
    assert len(terminal) == 2
    assert all(event['data']['reason'] == 'heartbeat_stopped' for event in terminal)
    assert job_events.active_job_ids() == []


def test_heartbeat_resolution_keeps_pending_when_event_is_missing_or_inactive():
    job_events = CompanionJobEventLog()
    scheduler = HeartbeatScheduler(job_event_log=job_events)
    scheduler.state.tick_count = 1
    scheduler._emit_opportunity_job({'type': 'suggestion'})
    created = job_events.snapshot()[0]
    pending = scheduler._opportunities[created['jobId']]

    job_events._events.pop(created['jobId'])
    assert scheduler.resolve_opportunity(
        job_id=created['jobId'], request_id=created['requestId'], outcome='delivered',
    ) is False
    assert scheduler._opportunities[created['jobId']] is pending

    job_events._events[created['jobId']] = [created]
    job_events._terminal_jobs.add(created['jobId'])
    assert scheduler.resolve_opportunity(
        job_id=created['jobId'], request_id=created['requestId'], outcome='delivered',
    ) is False
    assert scheduler._opportunities[created['jobId']] is pending


def test_heartbeat_policy_suppression_does_not_create_a_job():
    job_events = CompanionJobEventLog()
    scheduler = HeartbeatScheduler(job_event_log=job_events)
    scheduler.state.persona.update({'mood': 'tired', 'energy': 0.2})
    scheduler.state.tick_count = 3
    scheduler.state.last_tick_at = '2026-08-09T10:00:00'

    scheduler._emit_behavior_events()

    assert job_events.snapshot() == []
    assert job_events.active_job_ids() == []
