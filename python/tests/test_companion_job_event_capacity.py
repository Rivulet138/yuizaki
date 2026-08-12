from __future__ import annotations

import pytest

from modules.agent.companion_events import CompanionJobCapacityError, CompanionJobEventLog


def _append_created(log: CompanionJobEventLog, job_id: str) -> None:
    log.append(
        workspace_id='default',
        session_id='test',
        turn_id=f'turn:{job_id}',
        job_id=job_id,
        request_id=f'request:{job_id}',
        interruption_epoch=0,
        source='scheduler',
        timestamp=1.0,
        status='created',
    )


def test_capacity_never_evicts_an_active_job():
    log = CompanionJobEventLog(max_jobs=2)
    _append_created(log, 'job-1')
    _append_created(log, 'job-2')

    with pytest.raises(CompanionJobCapacityError):
        _append_created(log, 'job-3')

    assert log.active_job_ids() == ['job-1', 'job-2']
    assert [event['jobId'] for event in log.snapshot()] == ['job-1', 'job-2']


def test_capacity_evicts_a_terminal_job_before_accepting_a_new_job():
    log = CompanionJobEventLog(max_jobs=2)
    _append_created(log, 'job-1')
    log.append(
        workspace_id='default', session_id='test', turn_id='turn:job-1',
        job_id='job-1', request_id='request:job-1', interruption_epoch=0,
        source='scheduler', timestamp=2.0, status='completed',
    )
    _append_created(log, 'job-2')
    _append_created(log, 'job-3')

    assert not log.contains('job-1')
    assert log.active_job_ids() == ['job-2', 'job-3']


def test_event_log_rejects_terminal_reopen_and_copies_payload():
    log = CompanionJobEventLog()
    payload = {"nested": {"value": 1}}
    log.append(workspace_id='default', session_id='test', turn_id='turn:j', job_id='j', request_id='r', interruption_epoch=0, source='builtin', timestamp=1, status='created', data=payload)
    payload["nested"]["value"] = 2
    log.append(workspace_id='default', session_id='test', turn_id='turn:j', job_id='j', request_id='r', interruption_epoch=0, source='builtin', timestamp=2, status='completed')
    assert log.snapshot()[0]["data"]["nested"]["value"] == 1
    with pytest.raises(ValueError, match='terminal companion job'):
        log.append(workspace_id='default', session_id='test', turn_id='turn:j', job_id='j', request_id='r', interruption_epoch=0, source='builtin', timestamp=3, status='running')


def test_progress_events_are_coalesced_within_a_short_window():
    log = CompanionJobEventLog()
    _append_created(log, 'job-progress')
    log.append(workspace_id='default', session_id='test', turn_id='turn:job-progress', job_id='job-progress', request_id='request:job-progress', interruption_epoch=0, source='scheduler', timestamp=1.0, status='running')
    first = log.append(workspace_id='default', session_id='test', turn_id='turn:job-progress', job_id='job-progress', request_id='request:job-progress', interruption_epoch=0, source='scheduler', timestamp=2.0, status='progress', data={'progress': 0.1})
    second = log.append(workspace_id='default', session_id='test', turn_id='turn:job-progress', job_id='job-progress', request_id='request:job-progress', interruption_epoch=0, source='scheduler', timestamp=2.05, status='progress', data={'progress': 0.2})
    third = log.append(workspace_id='default', session_id='test', turn_id='turn:job-progress', job_id='job-progress', request_id='request:job-progress', interruption_epoch=0, source='scheduler', timestamp=2.11, status='progress', data={'progress': 0.3})

    assert first['revision'] == 3
    assert second['revision'] == first['revision']
    assert second['data']['progress'] == 0.2
    assert third['revision'] == 4
    assert [event['status'] for event in log.snapshot()] == ['created', 'running', 'progress', 'progress']
