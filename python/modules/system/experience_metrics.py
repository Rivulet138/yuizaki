from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime, timezone
from typing import Any, Callable, Mapping


TRACKED_GENERATION_STAGES = (
    "llm_request",
    "llm_first_token",
    "llm_first_sentence",
    "llm_completed",
    "tts_ready_wait",
    "tts_first_chunk",
    "tts_first_audio_ready",
    "playback_start",
    "tts_completed",
)
TRACKED_ASR_STAGES = (
    "vad_start_confirmed",
    "speech_start_confirmed",
    "speech_end",
    "endpoint_detected",
    "asr_final",
)
TRACKED_CLIENT_STAGES = (
    "interrupt_ack",
    "realtime_connect",
    "realtime_transcript_stable",
    "realtime_speech_to_response",
    "realtime_speech_to_playback",
    "realtime_interrupt_ack",
)
INTERRUPT_SOURCES = ("manual", "voice", "other")
VISUAL_ANALYSIS_OUTCOMES = ("ready", "empty", "error", "stale")


def _finite_milliseconds(value: object) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return number


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 1)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 1)
    weight = position - lower
    return round((ordered[lower] * (1 - weight)) + (ordered[upper] * weight), 1)


class ExperienceMetricsStore:
    """Bounded, content-free runtime metrics for companion responsiveness."""

    def __init__(self, max_entries: int = 200, clock: Callable[[], float] = time.perf_counter) -> None:
        self.max_entries = max(10, int(max_entries))
        self._clock = clock
        self._lock = threading.RLock()
        self._generations: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._asr_samples: deque[dict[str, Any]] = deque(maxlen=self.max_entries)
        self._voice_journeys: OrderedDict[str, float] = OrderedDict()
        self._voice_playback_journeys: OrderedDict[str, float] = OrderedDict()
        self._pending_asr_by_session: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._client_stage_samples: dict[str, deque[float]] = {
            stage: deque(maxlen=self.max_entries) for stage in TRACKED_CLIENT_STAGES
        }
        self._interrupt_requests = 0
        self._interrupt_hits = 0
        self._interrupts_by_source = {
            source: {"requests": 0, "hits": 0}
            for source in INTERRUPT_SOURCES
        }
        self._tool_calls = 0
        self._tool_successes = 0
        self._visual_frames = 0
        self._visual_analysis_requests = 0
        self._visual_analysis_skipped = 0
        self._visual_analysis_outcomes = {outcome: 0 for outcome in VISUAL_ANALYSIS_OUTCOMES}
        self._visual_analysis_latency: deque[float] = deque(maxlen=self.max_entries)
        self._visual_decision_reasons: dict[str, int] = {}
        self._visual_capture_reasons: dict[str, int] = {}
        self._visual_latest_change_score: float | None = None

    def record_latency(self, snapshot: Mapping[str, object]) -> None:
        kind = str(snapshot.get("kind") or "").strip().lower()
        stages_raw = snapshot.get("stages")
        if not isinstance(stages_raw, Mapping):
            return
        stages = {
            str(key): value
            for key, raw_value in stages_raw.items()
            if (value := _finite_milliseconds(raw_value)) is not None
        }
        if not stages:
            return

        session_id = str(snapshot.get("session_id") or "").strip()
        with self._lock:
            if kind == "asr":
                sample = {"session_id": session_id, "stages": stages, "recorded_monotonic": self._clock()}
                self._asr_samples.append(sample)
                if session_id and "asr_final" in stages:
                    self._pending_asr_by_session[session_id] = sample
                    self._pending_asr_by_session.move_to_end(session_id)
                    while len(self._pending_asr_by_session) > self.max_entries:
                        self._pending_asr_by_session.popitem(last=False)
                return
            if kind != "generation":
                return

            generation_id = str(snapshot.get("generation_id") or "").strip()
            if not generation_id:
                return
            sample = {"session_id": session_id, "stages": stages}
            self._generations[generation_id] = sample
            self._generations.move_to_end(generation_id)
            while len(self._generations) > self.max_entries:
                self._generations.popitem(last=False)

            pending_asr = self._pending_asr_by_session.get(session_id)
            if pending_asr is None:
                return
            assigned_generation = pending_asr.get("generation_id")
            if assigned_generation and assigned_generation != generation_id:
                return
            asr_final_ms = pending_asr["stages"].get("asr_final")
            if asr_final_ms is None:
                return

            first_audio_ms = stages.get("tts_first_chunk", stages.get("tts_first_audio_ready"))
            if first_audio_ms is not None and generation_id not in self._voice_journeys:
                pending_asr["generation_id"] = generation_id
                self._record_voice_journey(
                    self._voice_journeys,
                    generation_id,
                    asr_final_ms,
                    pending_asr["recorded_monotonic"],
                )
            if "playback_start" in stages and generation_id not in self._voice_playback_journeys:
                self._record_voice_journey(
                    self._voice_playback_journeys,
                    generation_id,
                    asr_final_ms,
                    pending_asr["recorded_monotonic"],
                )
                self._pending_asr_by_session.pop(session_id, None)

    def _record_voice_journey(
        self,
        target: OrderedDict[str, float],
        generation_id: str,
        asr_final_ms: float,
        asr_recorded_monotonic: float,
    ) -> None:
        handoff_ms = max(0.0, (self._clock() - asr_recorded_monotonic) * 1000)
        target[generation_id] = asr_final_ms + handoff_ms
        target.move_to_end(generation_id)
        while len(target) > self.max_entries:
            target.popitem(last=False)

    def record_interrupt(self, hit_active_generation: bool, source: str = "manual") -> None:
        normalized_source = source if source in {"manual", "voice"} else "other"
        with self._lock:
            self._interrupt_requests += 1
            source_metrics = self._interrupts_by_source[normalized_source]
            source_metrics["requests"] += 1
            if hit_active_generation:
                self._interrupt_hits += 1
                source_metrics["hits"] += 1

    def record_client_timing(self, stage: str, elapsed_ms: object) -> bool:
        """Record an allowlisted, content-free timing measured by the renderer."""
        value = _finite_milliseconds(elapsed_ms)
        if stage not in self._client_stage_samples or value is None:
            return False
        with self._lock:
            self._client_stage_samples[stage].append(value)
        return True

    def record_tool_outcome(self, success: bool) -> None:
        with self._lock:
            self._tool_calls += 1
            if success:
                self._tool_successes += 1

    def record_visual_frame(
        self,
        *,
        analysis_status: str,
        analysis_reason: str,
        capture_reason: str,
        change_score: object,
    ) -> None:
        """Record bounded visual-routing metadata without retaining image or caption content."""
        normalized_status = analysis_status.strip().lower()
        normalized_reason = analysis_reason.strip().lower() or "unknown"
        normalized_capture = capture_reason.strip().lower() or "unknown"
        score = _finite_milliseconds(change_score)
        with self._lock:
            self._visual_frames += 1
            if normalized_status == "pending":
                self._visual_analysis_requests += 1
            elif normalized_status == "cached":
                self._visual_analysis_skipped += 1
            self._visual_decision_reasons[normalized_reason] = self._visual_decision_reasons.get(normalized_reason, 0) + 1
            self._visual_capture_reasons[normalized_capture] = self._visual_capture_reasons.get(normalized_capture, 0) + 1
            if score is not None:
                self._visual_latest_change_score = min(1.0, score)

    def record_visual_analysis(self, outcome: str, elapsed_ms: object) -> bool:
        normalized_outcome = outcome.strip().lower()
        latency = _finite_milliseconds(elapsed_ms)
        if normalized_outcome not in VISUAL_ANALYSIS_OUTCOMES or latency is None:
            return False
        with self._lock:
            self._visual_analysis_outcomes[normalized_outcome] += 1
            self._visual_analysis_latency.append(latency)
        return True

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            generations = list(self._generations.values())
            asr_samples = list(self._asr_samples)
            voice_journeys = list(self._voice_journeys.values())
            voice_playback_journeys = list(self._voice_playback_journeys.values())
            interrupt_requests = self._interrupt_requests
            interrupt_hits = self._interrupt_hits
            interrupts_by_source = {
                source: dict(values)
                for source, values in self._interrupts_by_source.items()
            }
            tool_calls = self._tool_calls
            tool_successes = self._tool_successes
            client_stage_samples = {
                stage: list(values) for stage, values in self._client_stage_samples.items()
            }
            visual_frames = self._visual_frames
            visual_analysis_requests = self._visual_analysis_requests
            visual_analysis_skipped = self._visual_analysis_skipped
            visual_analysis_outcomes = dict(self._visual_analysis_outcomes)
            visual_analysis_latency = list(self._visual_analysis_latency)
            visual_decision_reasons = dict(self._visual_decision_reasons)
            visual_capture_reasons = dict(self._visual_capture_reasons)
            visual_latest_change_score = self._visual_latest_change_score

        latency: dict[str, dict[str, float | int | None]] = {}
        for stage in TRACKED_GENERATION_STAGES:
            values = [sample["stages"][stage] for sample in generations if stage in sample["stages"]]
            latency[stage] = self._summary(values)
        for stage in TRACKED_ASR_STAGES:
            values = [sample["stages"][stage] for sample in asr_samples if stage in sample["stages"]]
            latency[stage] = self._summary(values)
        for stage in TRACKED_CLIENT_STAGES:
            latency[stage] = self._summary(client_stage_samples[stage])
        latency["voice_to_first_audio"] = self._summary(voice_journeys)
        latency["voice_to_playback"] = self._summary(voice_playback_journeys)
        latency["visual_analysis"] = self._summary(visual_analysis_latency)

        tool_failures = tool_calls - tool_successes
        visual_completed = sum(visual_analysis_outcomes.values())
        visual_usable = visual_analysis_outcomes["ready"]
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "window": {
                "max_entries": self.max_entries,
                "generation_samples": len(generations),
                "asr_samples": len(asr_samples),
                "voice_journey_samples": len(voice_journeys),
                "voice_playback_journey_samples": len(voice_playback_journeys),
                "visual_analysis_samples": len(visual_analysis_latency),
            },
            "latency": latency,
            "interrupts": {
                "requests": interrupt_requests,
                "hits": interrupt_hits,
                "hit_rate": self._rate(interrupt_hits, interrupt_requests),
                "by_source": {
                    source: {
                        **values,
                        "hit_rate": self._rate(values["hits"], values["requests"]),
                    }
                    for source, values in interrupts_by_source.items()
                },
            },
            "tools": {
                "calls": tool_calls,
                "successes": tool_successes,
                "failures": tool_failures,
                "success_rate": self._rate(tool_successes, tool_calls),
            },
            "visual": {
                "frames": visual_frames,
                "analysis_requests": visual_analysis_requests,
                "analysis_skipped": visual_analysis_skipped,
                "analysis_rate": self._rate(visual_analysis_requests, visual_frames),
                "completed": visual_completed,
                "usable": visual_usable,
                "usable_rate": self._rate(visual_usable, visual_completed),
                "outcomes": visual_analysis_outcomes,
                "decision_reasons": visual_decision_reasons,
                "capture_reasons": visual_capture_reasons,
                "latest_change_score": visual_latest_change_score,
            },
        }

    @staticmethod
    def _summary(values: list[float]) -> dict[str, float | int | None]:
        return {
            "samples": len(values),
            "latest_ms": round(values[-1], 1) if values else None,
            "p50_ms": percentile(values, 0.5),
            "p95_ms": percentile(values, 0.95),
        }

    @staticmethod
    def _rate(numerator: int, denominator: int) -> float | None:
        if denominator <= 0:
            return None
        return round(numerator / denominator, 4)
