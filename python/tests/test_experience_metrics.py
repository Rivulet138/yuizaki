import pytest

from modules.agent.tool_executor import ToolExecutor
from modules.agent.tool_registry import ToolDefinition, ToolRegistry
from modules.agent.tool_result import ToolResultEnvelope
from modules.system.experience_metrics import ExperienceMetricsStore


def test_generation_snapshots_are_deduplicated_and_summarized() -> None:
    store = ExperienceMetricsStore(max_entries=20)
    store.record_latency({
        "kind": "generation",
        "session_id": "session-1",
        "generation_id": "generation-1",
        "stages": {"llm_request": 20, "llm_first_token": 100, "llm_first_sentence": 300, "tts_ready_wait": 80},
    })
    store.record_latency({
        "kind": "generation",
        "session_id": "session-1",
        "generation_id": "generation-1",
        "stages": {"llm_request": 20, "llm_first_token": 100, "llm_first_sentence": 300, "tts_ready_wait": 80, "tts_first_chunk": 600},
    })
    store.record_latency({
        "kind": "generation",
        "session_id": "session-2",
        "generation_id": "generation-2",
        "stages": {"llm_request": 30, "llm_first_token": 300, "llm_first_sentence": 500, "tts_ready_wait": 120, "tts_first_chunk": 900},
    })

    snapshot = store.snapshot()

    assert snapshot["window"]["generation_samples"] == 2
    assert snapshot["latency"]["llm_first_token"] == {
        "samples": 2,
        "latest_ms": 300.0,
        "p50_ms": 200.0,
        "p95_ms": 290.0,
    }
    assert snapshot["latency"]["llm_request"]["p50_ms"] == 25.0
    assert snapshot["latency"]["tts_ready_wait"] == {
        "samples": 2,
        "latest_ms": 120.0,
        "p50_ms": 100.0,
        "p95_ms": 118.0,
    }
    assert snapshot["latency"]["tts_first_chunk"]["p95_ms"] == 885.0


def test_voice_journey_pairs_asr_and_first_audio_for_same_session() -> None:
    clock_values = iter([10.0, 10.8, 11.1])
    store = ExperienceMetricsStore(clock=lambda: next(clock_values))
    store.record_latency({
        "kind": "asr",
        "session_id": "voice-session",
        "stages": {
            "vad_start_confirmed": 96,
            "speech_start_confirmed": 192,
            "speech_end": 132,
            "endpoint_detected": 420,
            "asr_final": 700,
        },
    })
    store.record_latency({
        "kind": "generation",
        "session_id": "other-session",
        "generation_id": "other-generation",
        "stages": {"tts_first_audio_ready": 500},
    })
    store.record_latency({
        "kind": "generation",
        "session_id": "voice-session",
        "generation_id": "voice-generation",
        "stages": {"llm_first_token": 100, "tts_first_chunk": 800},
    })
    store.record_latency({
        "kind": "generation",
        "session_id": "voice-session",
        "generation_id": "voice-generation",
        "stages": {"tts_first_chunk": 800, "playback_start": 1050},
    })

    snapshot = store.snapshot()

    assert snapshot["window"]["voice_journey_samples"] == 1
    assert snapshot["window"]["voice_playback_journey_samples"] == 1
    assert snapshot["latency"]["voice_to_first_audio"]["p50_ms"] == 1500.0
    assert snapshot["latency"]["voice_to_playback"]["p50_ms"] == 1800.0
    assert snapshot["latency"]["playback_start"]["p50_ms"] == 1050.0
    assert snapshot["latency"]["vad_start_confirmed"]["latest_ms"] == 96.0
    assert snapshot["latency"]["speech_start_confirmed"]["latest_ms"] == 192.0
    assert snapshot["latency"]["endpoint_detected"]["latest_ms"] == 420.0
    assert snapshot["latency"]["speech_end"]["latest_ms"] == 132.0


def test_interrupt_and_tool_rates_do_not_invent_zero_sample_percentages() -> None:
    store = ExperienceMetricsStore()
    empty = store.snapshot()
    assert empty["interrupts"]["hit_rate"] is None
    assert empty["tools"]["success_rate"] is None

    store.record_interrupt(True)
    store.record_interrupt(False, "voice")
    store.record_interrupt(True, "voice")
    store.record_interrupt(False, "untrusted-source")
    store.record_tool_outcome(True)
    store.record_tool_outcome(True)
    store.record_tool_outcome(False)

    snapshot = store.snapshot()
    assert snapshot["interrupts"] == {
        "requests": 4,
        "hits": 2,
        "hit_rate": 0.5,
        "by_source": {
            "manual": {"requests": 1, "hits": 1, "hit_rate": 1.0},
            "voice": {"requests": 2, "hits": 1, "hit_rate": 0.5},
            "other": {"requests": 1, "hits": 0, "hit_rate": 0.0},
        },
    }
    assert snapshot["tools"] == {"calls": 3, "successes": 2, "failures": 1, "success_rate": 0.6667}


def test_renderer_interrupt_ack_timings_are_allowlisted_and_summarized() -> None:
    store = ExperienceMetricsStore()

    assert store.record_client_timing("interrupt_ack", 42.5) is True
    assert store.record_client_timing("interrupt_ack", 57.5) is True
    assert store.record_client_timing("prompt", 1) is False
    assert store.record_client_timing("interrupt_ack", -1) is False

    assert store.snapshot()["latency"]["interrupt_ack"] == {
        "samples": 2,
        "latest_ms": 57.5,
        "p50_ms": 50.0,
        "p95_ms": 56.8,
    }


def test_visual_metrics_track_routing_and_latency_without_content() -> None:
    store = ExperienceMetricsStore()
    store.record_visual_frame(
        analysis_status="pending",
        analysis_reason="initial_frame",
        capture_reason="initial",
        change_score=1.0,
    )
    store.record_visual_frame(
        analysis_status="cached",
        analysis_reason="minor_change_cached",
        capture_reason="change",
        change_score=0.04,
    )
    assert store.record_visual_analysis("ready", 120.0) is True
    assert store.record_visual_analysis("error", 280.0) is True
    assert store.record_visual_analysis("caption text", 1.0) is False

    snapshot = store.snapshot()

    assert snapshot["window"]["visual_analysis_samples"] == 2
    assert snapshot["latency"]["visual_analysis"] == {
        "samples": 2,
        "latest_ms": 280.0,
        "p50_ms": 200.0,
        "p95_ms": 272.0,
    }
    assert snapshot["visual"] == {
        "frames": 2,
        "analysis_requests": 1,
        "analysis_skipped": 1,
        "analysis_rate": 0.5,
        "completed": 2,
        "usable": 1,
        "usable_rate": 0.5,
        "outcomes": {"ready": 1, "empty": 0, "error": 1, "stale": 0},
        "decision_reasons": {"initial_frame": 1, "minor_change_cached": 1},
        "capture_reasons": {"initial": 1, "change": 1},
        "latest_change_score": 0.04,
    }
    assert "caption text" not in str(snapshot)


def test_invalid_or_content_fields_are_not_retained() -> None:
    store = ExperienceMetricsStore()
    store.record_latency({
        "kind": "generation",
        "generation_id": "bad",
        "prompt": "private prompt",
        "stages": {"llm_first_token": -1, "llm_completed": "not-a-number"},
    })

    snapshot = store.snapshot()
    assert snapshot["window"]["generation_samples"] == 0
    assert "prompt" not in str(snapshot)


@pytest.mark.asyncio
async def test_tool_executor_reports_success_failure_and_unknown_tools() -> None:
    outcomes: list[bool] = []
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="ok",
        description="ok",
        source="builtin",
        parameters={},
        handler=lambda _args: ToolResultEnvelope(success=True, content="done", source="builtin", tool_name="ok"),
    ))
    registry.register(ToolDefinition(
        name="fail",
        description="fail",
        source="builtin",
        parameters={},
        handler=lambda _args: ToolResultEnvelope(success=False, content="", source="builtin", tool_name="fail", error="failed"),
    ))
    executor = ToolExecutor(registry, outcome_observer=outcomes.append)

    await executor.execute("ok", {})
    await executor.execute("fail", {})
    await executor.execute("missing", {})

    assert outcomes == [True, False, False]
