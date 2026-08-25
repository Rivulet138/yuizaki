"""
State management for Yuizaki backend.
Handles Generation lifecycle, session history, and ASR pipeline.
"""

import asyncio
import uuid
import logging
import math
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
import numpy as np

logger = logging.getLogger("yuizaki.state")


@dataclass
class Generation:
    """One LLM → TTS cycle, tied to a session_id."""

    generation_id: str
    session_id: str
    turn_id: str = ""
    request_id: str = ""
    conversation_id: str = ""
    operation_id: str = ""
    run_id: str = ""
    step_index: int = 0
    interruption_epoch: int = 0
    envelope_version: int = 1
    sequence: int = 0
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    invalidated: bool = False
    tokens: list[str] = field(default_factory=list)
    llm_task: Optional[asyncio.Task[None]] = None
    tts_task: Optional[asyncio.Task[None]] = None
    started_monotonic: float = field(default_factory=time.perf_counter, repr=False)
    timings_ms: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.timings_ms.setdefault("generation_started", 0.0)

    @property
    def full_text(self) -> str:
        return "".join(self.tokens)

    def mark(self, stage: str, *, overwrite: bool = False) -> float:
        """Record a stage once using a monotonic clock."""
        elapsed_ms = max(0.0, (time.perf_counter() - self.started_monotonic) * 1000)
        if overwrite or stage not in self.timings_ms:
            self.timings_ms[stage] = elapsed_ms
        return self.timings_ms[stage]

    def record_duration(self, stage: str, elapsed_ms: float, *, overwrite: bool = False) -> float:
        """Record a measured duration without treating it as a lifecycle timestamp."""
        value = float(elapsed_ms)
        if not math.isfinite(value):
            raise ValueError(f"{stage} duration must be finite")
        value = max(0.0, value)
        if overwrite or stage not in self.timings_ms:
            self.timings_ms[stage] = value
        return self.timings_ms[stage]

    def latency_snapshot(self) -> dict[str, Any]:
        stages = {key: round(value, 1) for key, value in self.timings_ms.items()}
        return {
            "kind": "generation",
            "session_id": self.session_id,
            "generation_id": self.generation_id,
            "turn_id": self.turn_id,
            "request_id": self.request_id,
            "interruption_epoch": self.interruption_epoch,
            "version": self.envelope_version,
            "stages": stages,
            "total_ms": round(max(stages.values(), default=0.0), 1),
        }

    def invalidate(self) -> None:
        """Hard-kill: cancel everything, block all future WS sends,
        and delete any cached wav file."""
        self.mark("interrupted")
        self.invalidated = True
        self.cancel.set()
        for task in (self.llm_task, self.tts_task):
            if task is not None and not task.done():
                task.cancel()


class GenerationManager:
    """Per-WS-connection manager. One active Generation per session_id,
    plus per-session conversation history."""

    def __init__(self) -> None:
        self._active: dict[str, Generation] = {}
        self._history: dict[str, list[dict[str, str]]] = {}
        self._summary: dict[str, str] = {}
        self._summary_meta: dict[str, dict[str, Any]] = {}
        self._summary_quality_profile: dict[str, dict[str, Any]] = {}
        self._summary_audit: list[dict[str, Any]] = []
        self._summary_audit_max_entries = 500
        self._session_locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()
        from .config import config

        self._summary_trigger_messages = int(config.summary.trigger_messages)
        self._summary_keep_recent = int(config.summary.keep_recent_messages)
        self._summary_item_max_chars = int(config.summary.item_max_chars)
        self._summary_rewrite_interval = int(config.summary.rewrite_interval_messages)
        self._summary_quality_mode = str(config.summary.quality_scorer_mode or "rule").lower()
        self._quality_score_cooldown_seconds = max(1, int(config.summary.quality_score_cooldown_seconds))
        self._quality_score_budget_per_hour = max(1, int(config.summary.quality_score_budget_per_hour))
        self._quality_score_events: dict[str, list[float]] = {}

    # ── history ──────────────────────────────────────────────

    def _lock_for(self, session_id: str) -> threading.RLock:
        with self._locks_guard:
            lock = self._session_locks.get(session_id)
            if lock is None:
                lock = threading.RLock()
                self._session_locks[session_id] = lock
            return lock

    def append_history(
        self,
        session_id: str,
        role: str,
        content: str,
    ) -> None:
        with self._lock_for(session_id):
            self._history.setdefault(session_id, []).append(
                {"role": role, "content": content}
            )
            self._maybe_compress_history(session_id)

    def get_messages_for_new_turn(
        self,
        session_id: str,
        user_text: str,
    ) -> list[dict[str, str]]:
        """Append user_text to history and return the full conversation."""
        with self._lock_for(session_id):
            self.append_history(session_id, "user", user_text)
            return list(self._history[session_id])

    def replace_history(
        self,
        session_id: str,
        messages: list[dict[str, str]],
    ) -> None:
        """Overwrite history with an externally-provided list."""
        with self._lock_for(session_id):
            self._history[session_id] = list(messages)
            self._maybe_compress_history(session_id)

    def get_summary(self, session_id: str) -> str:
        with self._lock_for(session_id):
            return self._summary.get(session_id, "")

    def update_summary_policy(
        self,
        trigger_messages: int,
        keep_recent_messages: int,
        item_max_chars: int,
        rewrite_interval_messages: int,
        quality_scorer_mode: str | None = None,
        quality_score_cooldown_seconds: int | None = None,
        quality_score_budget_per_hour: int | None = None,
    ) -> None:
        """Hot-update summary governance thresholds at runtime."""
        self._summary_trigger_messages = max(1, int(trigger_messages))
        self._summary_keep_recent = max(1, int(keep_recent_messages))
        self._summary_item_max_chars = max(20, int(item_max_chars))
        self._summary_rewrite_interval = max(1, int(rewrite_interval_messages))
        if quality_scorer_mode is not None:
            mode = str(quality_scorer_mode).strip().lower()
            self._summary_quality_mode = mode if mode in {"rule", "llm"} else "rule"
        if quality_score_cooldown_seconds is not None:
            self._quality_score_cooldown_seconds = max(1, int(quality_score_cooldown_seconds))
        if quality_score_budget_per_hour is not None:
            self._quality_score_budget_per_hour = max(1, int(quality_score_budget_per_hour))

    def get_history_snapshot(self, session_id: str) -> list[dict[str, str]]:
        with self._lock_for(session_id):
            return list(self._history.get(session_id, []))

    def get_summary_stats(self, session_id: str) -> dict[str, Any]:
        with self._lock_for(session_id):
            meta = self._summary_meta.get(session_id, {})
            summary = self._summary.get(session_id, "")
            cached_profile = self._summary_quality_profile.get(session_id)
        quality_profile = cached_profile or self._score_summary_quality_profile(summary, scorer="rule")
        quality = quality_profile["scores"]
        effective_interval = self._effective_rewrite_interval(quality)
        quality_band = self._quality_band(quality["overall"])
        return {
            "session_id": session_id,
            "summary_length": len(summary),
            "updated_at": meta.get("updated_at"),
            "compression_count": int(meta.get("compression_count", 0)),
            "rewrite_count": int(meta.get("rewrite_count", 0)),
            "messages_since_rewrite": int(meta.get("messages_since_rewrite", 0)),
            "has_summary": bool(summary),
            "quality": quality,
            "quality_scorer": quality_profile.get("scorer", "rule"),
            "quality_basis": quality_profile.get("basis", "rule-keywords"),
            "effective_rewrite_interval": effective_interval,
            "quality_band": quality_band,
            "quality_score_cooldown_seconds": self._quality_score_cooldown_seconds,
            "quality_score_budget_per_hour": self._quality_score_budget_per_hour,
        }

    def get_quality_scorer_mode(self) -> str:
        return self._summary_quality_mode

    def update_quality_profile(
        self,
        session_id: str,
        scores: dict[str, int],
        scorer: str,
        basis: str,
    ) -> None:
        profile = {
            "scores": {
                "overall": int(scores.get("overall", 0)),
                "facts": int(scores.get("facts", 0)),
                "preferences": int(scores.get("preferences", 0)),
                "goals_open_tasks": int(scores.get("goals_open_tasks", 0)),
            },
            "scorer": scorer,
            "basis": basis,
            "updated_at": datetime.now().isoformat(),
        }
        with self._lock_for(session_id):
            self._summary_quality_profile[session_id] = profile

    def allow_llm_quality_scoring(self, session_id: str) -> tuple[bool, str]:
        """Cost guard for LLM quality scoring.

        Returns (allowed, reason). reason='ok' when allowed.
        """
        now = time.time()
        with self._lock_for(session_id):
            events = self._quality_score_events.setdefault(session_id, [])
            # Keep only last hour events.
            cutoff = now - 3600
            events[:] = [ts for ts in events if ts >= cutoff]

            if events:
                since_last = now - events[-1]
                if since_last < self._quality_score_cooldown_seconds:
                    return False, "cooldown"

            if len(events) >= self._quality_score_budget_per_hour:
                return False, "hourly_budget"

            events.append(now)
            return True, "ok"

    def record_summary_audit(
        self,
        session_id: str,
        source: str,
        outcome: str,
        detail: str = "",
    ) -> None:
        entry = {
            "timestamp": datetime.now().isoformat(),
            "session_id": session_id,
            "source": source,
            "outcome": outcome,
            "detail": detail,
        }
        self._summary_audit.append(entry)
        if len(self._summary_audit) > self._summary_audit_max_entries:
            self._summary_audit = self._summary_audit[-self._summary_audit_max_entries :]

    def get_summary_audit(
        self,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        logs = self._summary_audit
        if session_id:
            logs = [item for item in logs if item.get("session_id") == session_id]
        take = max(1, min(int(limit), 500))
        return list(reversed(logs[-take:]))

    def _effective_rewrite_interval(self, quality: dict[str, int]) -> int:
        base = max(1, int(self._summary_rewrite_interval))
        overall = int(quality.get("overall", 0))
        if overall < 35:
            return max(1, base // 2)
        if overall >= 75:
            return max(1, int(base * 1.5))
        return base

    def _quality_band(self, overall: int) -> str:
        if overall < 35:
            return "low"
        if overall >= 75:
            return "high"
        return "medium"

    def _score_summary_quality(self, summary: str) -> dict[str, int]:
        text = (summary or "").lower()
        if not text:
            return {
                "overall": 0,
                "facts": 0,
                "preferences": 0,
                "goals_open_tasks": 0,
            }

        fact_hits = sum(
            1 for kw in ["事实", "fact", "住在", "职业", "身份", "背景", "关系"] if kw in text
        )
        pref_hits = sum(
            1 for kw in ["喜欢", "偏好", "讨厌", "不喜欢", "preference", "倾向"] if kw in text
        )
        goal_hits = sum(
            1 for kw in ["目标", "计划", "待办", "未完成", "todo", "next", "下一步"] if kw in text
        )

        facts = min(100, 25 * fact_hits)
        preferences = min(100, 25 * pref_hits)
        goals = min(100, 25 * goal_hits)
        overall = int((facts + preferences + goals) / 3)

        return {
            "overall": overall,
            "facts": facts,
            "preferences": preferences,
            "goals_open_tasks": goals,
        }

    def _score_summary_quality_profile(self, summary: str, scorer: str = "rule") -> dict[str, Any]:
        return {
            "scores": self._score_summary_quality(summary),
            "scorer": scorer,
            "basis": "rule-keywords",
            "updated_at": datetime.now().isoformat(),
        }

    def list_summary_session_ids(self) -> list[str]:
        ids = set(self._history.keys()) | set(self._summary.keys())
        return sorted(ids)

    def should_rewrite_summary(self, session_id: str) -> bool:
        with self._lock_for(session_id):
            summary = self._summary.get(session_id, "")
            messages_since_rewrite = int(
                self._summary_meta.get(session_id, {}).get("messages_since_rewrite", 0)
            )
            profile = self._summary_quality_profile.get(session_id)
        if not summary:
            return False
        quality = profile["scores"] if profile else self._score_summary_quality(summary)
        effective_interval = self._effective_rewrite_interval(quality)
        return messages_since_rewrite >= effective_interval

    def build_summary_rewrite_source(self, session_id: str) -> str:
        with self._lock_for(session_id):
            summary = self._summary.get(session_id, "")
            recent = self._history.get(session_id, [])[-12:]
        lines: list[str] = []
        if summary:
            lines.append("[CURRENT_SUMMARY]")
            lines.append(summary)
            lines.append("")
        lines.append("[RECENT_MESSAGES]")
        for item in recent:
            role = item.get("role", "user")
            content = (item.get("content", "") or "").strip().replace("\n", " ")
            if len(content) > 300:
                content = content[:299] + "…"
            lines.append(f"- {role}: {content}")
        return "\n".join(lines)

    def apply_llm_summary(self, session_id: str, summary_text: str) -> None:
        summary_text = (summary_text or "").strip()
        if not summary_text:
            return
        with self._lock_for(session_id):
            self._summary[session_id] = summary_text
            meta = self._summary_meta.setdefault(session_id, {})
            meta["rewrite_count"] = int(meta.get("rewrite_count", 0)) + 1
            meta["messages_since_rewrite"] = 0
            meta["updated_at"] = datetime.now().isoformat()
            self._summary_quality_profile[session_id] = self._score_summary_quality_profile(summary_text, scorer="rule")

    def _maybe_compress_history(self, session_id: str) -> None:
        history = self._history.get(session_id, [])
        meta = self._summary_meta.setdefault(session_id, {})
        meta["messages_since_rewrite"] = int(meta.get("messages_since_rewrite", 0)) + 1
        has_summary = session_id in self._summary
        should_compress = (
            len(history) > self._summary_trigger_messages
            or (has_summary and len(history) > self._summary_keep_recent)
        )
        if not should_compress:
            return

        keep_recent = self._summary_keep_recent
        old_part = history[:-keep_recent]
        recent_part = history[-keep_recent:]

        summary_lines: list[str] = []
        for item in old_part[-16:]:
            role = item.get("role", "user")
            content = (item.get("content", "") or "").strip().replace("\n", " ")
            if len(content) > self._summary_item_max_chars:
                content = content[: self._summary_item_max_chars - 1] + "…"
            if content:
                summary_lines.append(f"- {role}: {content}")

        if summary_lines:
            self._summary[session_id] = "\n".join(summary_lines)
            meta["compression_count"] = int(meta.get("compression_count", 0)) + 1
            meta["updated_at"] = datetime.now().isoformat()
            self._summary_quality_profile[session_id] = self._score_summary_quality_profile(
                self._summary[session_id],
                scorer="rule",
            )

        self._history[session_id] = recent_part

    # ── generation lifecycle ─────────────────────────────────

    def start(
        self,
        session_id: str,
        *,
        generation_id: str | None = None,
        turn_id: str | None = None,
        request_id: str | None = None,
        interruption_epoch: int = 0,
        envelope_version: int = 1,
        conversation_id: str | None = None,
        operation_id: str | None = None,
        run_id: str | None = None,
        step_index: int = 0,
    ) -> Generation:
        """Create a new Generation, invalidating any prior one."""
        prev = self._active.get(session_id)
        if prev is not None:
            prev.invalidate()
            logger.info(
                "[%s] previous generation %s invalidated",
                session_id,
                prev.generation_id,
            )

        gen = Generation(
            generation_id=str(generation_id or uuid.uuid4().hex[:12]),
            session_id=session_id,
            turn_id=str(turn_id or uuid.uuid4().hex[:12]),
            request_id=str(request_id or uuid.uuid4().hex),
            interruption_epoch=max(0, int(interruption_epoch)),
            envelope_version=max(1, int(envelope_version)),
            conversation_id=str(conversation_id or session_id),
            operation_id=str(operation_id or ""),
            run_id=str(run_id or ""),
            step_index=max(0, int(step_index)),
        )
        self._active[session_id] = gen
        return gen

    def get(self, session_id: str) -> Optional[Generation]:
        return self._active.get(session_id)

    def active_session_ids(self) -> tuple[str, ...]:
        """Return an identity-only snapshot for host cancellation."""
        return tuple(self._active)

    def interrupt(self, session_id: str) -> Optional[Generation]:
        """Interrupt the active generation. Returns it or None."""
        gen = self._active.get(session_id)
        if gen is not None:
            gen.invalidate()
            logger.info(
                "[%s] generation %s interrupted",
                session_id,
                gen.generation_id,
            )
        return gen

    def cancel_all(self) -> None:
        """Invalidate everything (WS disconnect)."""
        for gen in self._active.values():
            gen.invalidate()
        self._active.clear()


class ASRPipeline:
    """Per-session VAD segmentation + SenseVoice transcription.

    Audio contract
    ──────────────
    • Sample rate : 16 000 Hz
    • Format      : mono PCM-16 (signed int16, little-endian)
    • Chunk size  : exactly 512 samples = 1 024 bytes  (32 ms)
    """

    SAMPLE_RATE = 16_000
    CHUNK_SAMPLES = 512  # 32 ms at 16 kHz
    _BASE_ENERGY_THRESHOLD = 0.005
    _CHUNK_DURATION_MS = 32
    _START_CONFIRM_FRAMES = 3
    _REAL_START_CONFIRM_FRAMES = 6

    def __init__(
        self,
        sensevoice_model: Any,
        vad_threshold: float = 0.5,
        vad_min_silence_ms: int = 300,
        asr_partial_every: int = 15,
    ) -> None:
        self._sv = sensevoice_model
        self._vad_threshold = vad_threshold
        self._vad_min_silence_ms = vad_min_silence_ms
        self._buffer: list[np.ndarray] = []
        self.is_speaking: bool = False
        self._chunk_count: int = 0
        self.transcribe_task: Optional[asyncio.Task[None]] = None
        self._asr_partial_every = max(1, int(asr_partial_every))
        self._next_partial_chunk = self._asr_partial_every
        self._silence_frames: int = 0
        self._noise_floor: float = self._BASE_ENERGY_THRESHOLD / 5
        self._pre_roll: list[np.ndarray] = []
        self._speech_candidate: list[np.ndarray] = []
        self._speech_candidate_started_monotonic: float | None = None
        self._speech_started_monotonic: float | None = None
        self._timings_ms: dict[str, float] = {}
        self._last_energy_threshold = self._BASE_ENERGY_THRESHOLD
        self._pause_ema_ms: float = 0.0
        self._speech_frames: int = 0
        self._real_start_emitted: bool = False

    def _mark(self, stage: str) -> float | None:
        if self._speech_started_monotonic is None:
            return None
        elapsed_ms = max(0.0, (time.perf_counter() - self._speech_started_monotonic) * 1000)
        self._timings_ms.setdefault(stage, elapsed_ms)
        return self._timings_ms[stage]

    def mark(self, stage: str) -> float | None:
        return self._mark(stage)

    def latency_snapshot(self) -> dict[str, Any]:
        stages = {key: round(value, 1) for key, value in self._timings_ms.items()}
        endpoint_ms = stages.get("endpoint_detected")
        if endpoint_ms is not None and "speech_end" not in stages:
            stages["speech_end"] = round(
                max(0.0, endpoint_ms - self._adaptive_endpoint_silence_ms()),
                1,
            )
        return {
            "kind": "asr",
            "stages": stages,
            "total_ms": round(max(stages.values(), default=0.0), 1),
            "energy_threshold": round(self._last_energy_threshold, 6),
            "noise_floor": round(self._noise_floor, 6),
            "endpoint_silence_ms": self._adaptive_endpoint_silence_ms(),
            "observed_pause_ms": round(self._pause_ema_ms, 1),
        }

    @property
    def start_confirmation_ms(self) -> int:
        return self._START_CONFIRM_FRAMES * self._CHUNK_DURATION_MS

    @property
    def real_start_confirmation_ms(self) -> int:
        return self._REAL_START_CONFIRM_FRAMES * self._CHUNK_DURATION_MS

    def _energy_threshold(self) -> float:
        configured = self._BASE_ENERGY_THRESHOLD * max(0.2, self._vad_threshold / 0.5)
        adaptive = self._noise_floor * 2.8
        self._last_energy_threshold = max(configured, adaptive)
        return self._last_energy_threshold

    def _adaptive_endpoint_silence_ms(self) -> int:
        configured = max(160, min(1200, int(self._vad_min_silence_ms)))
        utterance_ms = len(self._buffer) * self._CHUNK_DURATION_MS
        if utterance_ms >= 2500:
            baseline = 224
        elif utterance_ms >= 900:
            baseline = 288
        else:
            baseline = 352
        if self._pause_ema_ms <= 0:
            return min(configured, baseline)
        learned = int(np.ceil((self._pause_ema_ms + 96) / self._CHUNK_DURATION_MS)) * self._CHUNK_DURATION_MS
        return min(configured, max(baseline, learned))

    def _record_recovered_pause(self) -> None:
        if self._silence_frames <= 0:
            return
        pause_ms = self._silence_frames * self._CHUNK_DURATION_MS
        if self._pause_ema_ms <= 0:
            self._pause_ema_ms = float(pause_ms)
        else:
            self._pause_ema_ms = (self._pause_ema_ms * 0.7) + (pause_ms * 0.3)

    def _partial_interval_chunks(self) -> int:
        utterance_ms = len(self._buffer) * self._CHUNK_DURATION_MS
        if utterance_ms >= 4000:
            return self._asr_partial_every * 3
        if utterance_ms >= 1200:
            return self._asr_partial_every * 2
        return self._asr_partial_every

    def feed_chunk(self, pcm16_bytes: bytes) -> Optional[str]:
        if not pcm16_bytes:
            return None

        audio_i16 = np.frombuffer(pcm16_bytes, dtype=np.int16).copy()
        audio_f32 = audio_i16.astype(np.float32) / 32768.0
        energy = float(np.sqrt(np.mean(audio_f32 ** 2)))
        energy_threshold = self._energy_threshold()

        if energy > energy_threshold:
            if self.is_speaking:
                self._record_recovered_pause()
            self._silence_frames = 0
            if not self.is_speaking:
                if not self._speech_candidate:
                    self._speech_candidate_started_monotonic = time.perf_counter()
                self._speech_candidate.append(audio_f32)
                if len(self._speech_candidate) < self._START_CONFIRM_FRAMES:
                    return None
                self.is_speaking = True
                self._speech_started_monotonic = self._speech_candidate_started_monotonic or time.perf_counter()
                self._timings_ms = {"speech_started": 0.0}
                self._mark("vad_start_confirmed")
                self._speech_frames = len(self._speech_candidate)
                self._real_start_emitted = False
                self._buffer = [*self._pre_roll, *self._speech_candidate]
                self._pre_roll.clear()
                self._speech_candidate.clear()
                self._speech_candidate_started_monotonic = None
                self._chunk_count = self._START_CONFIRM_FRAMES - 1
                self._next_partial_chunk = self._asr_partial_every
                return "vad_start"
            self._buffer.append(audio_f32)
            self._chunk_count += 1
            self._speech_frames += 1
            if not self._real_start_emitted and self._speech_frames >= self._REAL_START_CONFIRM_FRAMES:
                self._real_start_emitted = True
                self._mark("speech_start_confirmed")
                return "speech_start"
            if self._chunk_count >= self._next_partial_chunk:
                self._next_partial_chunk += self._partial_interval_chunks()
                return "partial"
        else:
            if self.is_speaking:
                self._buffer.append(audio_f32)
                self._silence_frames += 1
                silence_ms = self._silence_frames * self._CHUNK_DURATION_MS
                if silence_ms >= self._adaptive_endpoint_silence_ms():
                    self.is_speaking = False
                    self._mark("endpoint_detected")
                    return "vad_end"
            else:
                if self._speech_candidate:
                    self._pre_roll.extend(self._speech_candidate)
                    self._speech_candidate.clear()
                    self._speech_candidate_started_monotonic = None
                self._noise_floor = (self._noise_floor * 0.94) + (energy * 0.06)
                self._pre_roll.append(audio_f32)
                self._pre_roll = self._pre_roll[-3:]
        return None

    def snapshot_audio(self) -> Optional[np.ndarray]:
        if not self._buffer:
            return None
        return np.concatenate(self._buffer)

    def transcribe_sync(
        self,
        audio: np.ndarray,
        beam_size: int = 5,
        language: str = "auto",
    ) -> str:
        if audio.size < 1600:
            return ""
        try:
            result = self._sv.generate(
                input=audio,
                language=language,
                use_itn=True,
                batch_size_s=60,
            )
            if not result:
                return ""
            texts = [str(item.get("text", "")) for item in result]
            return " ".join(t for t in texts if t).strip()
        except Exception:
            logger.exception("SenseVoice transcribe_sync failed")
            return ""

    def cancel_transcription(self) -> None:
        if self.transcribe_task and not self.transcribe_task.done():
            self.transcribe_task.cancel()
            self.transcribe_task = None

    def reset(self) -> None:
        self._buffer.clear()
        self.is_speaking = False
        self._chunk_count = 0
        self._next_partial_chunk = self._asr_partial_every
        self._silence_frames = 0
        self._pre_roll.clear()
        self._speech_candidate.clear()
        self._speech_candidate_started_monotonic = None
        self._speech_started_monotonic = None
        self._timings_ms = {}
        self._speech_frames = 0
        self._real_start_emitted = False
        self.cancel_transcription()
