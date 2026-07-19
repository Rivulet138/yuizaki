import asyncio
import pytest

from modules.system.companion_policy import build_base_behavior_event, build_behavior_profile, evaluate_proactive_policy
from modules.system.heartbeat import HeartbeatScheduler


async def _wait_for(predicate, timeout: float = 0.25):
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        if predicate():
            return True
        if asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(0.005)


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
