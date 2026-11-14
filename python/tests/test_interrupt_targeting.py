from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from modules.core.state import GenerationManager
from socket_handlers.interrupt import register_interrupt_handler
from socket_server import DesktopPetSocketServer


async def _park() -> None:
    await asyncio.Event().wait()


def _setup():
    server = DesktopPetSocketServer.__new__(DesktopPetSocketServer)
    server._interruption_epoch = 7
    manager = server.generation_mgr = GenerationManager()
    old = manager.start("session", request_id="old")
    current = manager.start("session", request_id="new")
    other = manager.start("other-session", request_id="other")
    signals = {key: asyncio.Event() for key in ("old", "new", "other")}
    server._tool_cancellation_signals = {
        "old": ("sid", "old", signals["old"]),
        "new": ("sid", "new", signals["new"]),
        "other": ("other-sid", "other", signals["other"]),
    }
    tasks = {sid: asyncio.create_task(_park()) for sid in ("sid", "other-sid")}
    server._visual_analysis_tasks = dict(tasks)
    server._visual_analysis_request_ids = {"sid": "new", "other-sid": "other"}
    server._latest_visual_frames = {"sid": {"request_id": "new"}, "other-sid": {"request_id": "other"}}
    server._latest_visual_observations = {"sid": {"request_id": "new"}, "other-sid": {"request_id": "other"}}
    server._visual_capture_requests = {
        key: {"sid": "other-sid" if key == "other" else "sid", "request_id": key}
        for key in signals
    }
    visual_cancelled = []
    server._complete_visual_job = lambda frame, **_kwargs: visual_cancelled.append(frame["request_id"])
    server._resolve_visual_capture_request = lambda *_args: None
    acks, records = [], []

    async def emit(_event, payload, **_kwargs):
        acks.append(payload)

    handler = register_interrupt_handler(
        sio=SimpleNamespace(on=lambda *_args, **_kwargs: None, emit=emit),
        generation_manager_provider=lambda: manager,
        advance_interruption_epoch=server._advance_interruption_epoch,
        cancel_visual_turn=server._cancel_visual_turn_for_interrupt,
        cancel_direct_tool_calls=server._cancel_direct_tool_calls,
        record_interrupt=lambda *args: records.append(args),
    )
    return server, handler, old, current, other, signals, tasks, acks, records, visual_cancelled


@pytest.mark.asyncio
async def test_request_interrupt_matches_generation_and_preserves_other_work() -> None:
    server, handler, old, current, other, signals, tasks, acks, records, visual = _setup()
    try:
        assert old.invalidated  # start() already replaced the old request.
        await handler("sid", {"session_id": "session", "request_id": "missing"})
        assert not any(signal.is_set() for signal in signals.values())
        assert acks[-1]["hit_active_generation"] is False
        assert acks[-1]["hit_active_tool"] is False
        assert records[-1] == (False, "manual")
        assert not visual

        await handler("sid", {"session_id": "session", "request_id": "old"})
        assert signals["old"].is_set() and not signals["new"].is_set()
        assert not current.invalidated and not other.invalidated
        assert not tasks["sid"].cancelling() and not tasks["other-sid"].cancelling()
        assert server._latest_visual_frames["sid"]["request_id"] == "new"
        assert server._latest_visual_observations["sid"]["request_id"] == "new"
        assert visual == ["old"]
        assert acks[-1]["generation_id"] == ""
        assert acks[-1]["hit_active_generation"] is False
        assert acks[-1]["hit_active_tool"] is True
        assert server._active_interruption_epoch() == 7

        # Even a matching request in the wrong session must not find a target.
        assert server.generation_mgr.interrupt("other-session", request_id="new") is None
        assert not other.invalidated
        await handler("sid", {"session_id": "session", "request_id": "new"})
        assert current.invalidated and current.cancel.is_set()
        assert not other.invalidated and not signals["other"].is_set()
        assert tasks["sid"].cancelling() and not tasks["other-sid"].cancelling()
        assert "sid" not in server._latest_visual_frames
        assert "sid" not in server._latest_visual_observations
        assert "other-sid" in server._latest_visual_frames
        assert server._active_interruption_epoch() == 7
        assert acks[-1]["generation_id"] == current.generation_id
        assert acks[-1]["hit_active_generation"] is True
    finally:
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)


@pytest.mark.asyncio
async def test_general_interrupt_keeps_epoch_and_session_cancellation_contract() -> None:
    server, handler, _old, current, other, signals, tasks, acks, records, _visual = _setup()
    try:
        await handler("sid", {"session_id": "session", "source": "voice"})
        assert server._active_interruption_epoch() == 8
        assert current.invalidated and current.cancel.is_set()
        assert not other.invalidated
        assert signals["old"].is_set() and signals["new"].is_set()
        assert not signals["other"].is_set()
        assert tasks["sid"].cancelling() and not tasks["other-sid"].cancelling()
        assert "sid" not in server._latest_visual_frames
        assert "sid" not in server._latest_visual_observations
        assert "other-sid" in server._latest_visual_frames
        assert acks[-1]["request_id"] == ""
        assert acks[-1]["generation_id"] == current.generation_id
        assert acks[-1]["hit_active_generation"] is True
        assert acks[-1]["hit_active_tool"] is True
        assert records == [(True, "voice")]
    finally:
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
