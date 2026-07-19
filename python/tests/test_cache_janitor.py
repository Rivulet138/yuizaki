from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from modules.system.cache_janitor import run_audio_cache_janitor, sweep_stale_audio_files


@dataclass
class _Policy:
    max_age: int = 1800
    janitor_interval: int = 3600


@dataclass
class _Location:
    audio_cache_dir: Path


def _age(path: Path, timestamp: float) -> None:
    os.utime(path, (timestamp, timestamp))


def test_audio_sweep_only_removes_stale_yuizaki_audio(tmp_path: Path) -> None:
    cache_dir = tmp_path / "audio-cache"
    temp_dir = tmp_path / "temp"
    cache_dir.mkdir()
    temp_dir.mkdir()
    stale_cache = cache_dir / "generation.wav"
    fresh_cache = cache_dir / "fresh.wav"
    stale_warmup = temp_dir / "yuizaki_tts_warmup_1.wav"
    stale_svc = temp_dir / "yuizaki_svc_in_1.wav"
    unrelated = temp_dir / "recording.wav"
    for path in (stale_cache, fresh_cache, stale_warmup, stale_svc, unrelated):
        path.write_bytes(b"audio")
    now = 10_000.0
    for path in (stale_cache, stale_warmup, stale_svc, unrelated):
        _age(path, now - 2_000)
    _age(fresh_cache, now - 10)

    result = sweep_stale_audio_files(
        _Policy(max_age=1_000),
        _Location(cache_dir),
        now=now,
        temp_dir=temp_dir,
    )

    assert result == {"scanned": 4, "removed": 3, "removed_bytes": 15, "failed": 0}
    assert not stale_cache.exists()
    assert not stale_warmup.exists()
    assert not stale_svc.exists()
    assert fresh_cache.exists()
    assert unrelated.exists()


def test_audio_janitor_sweeps_before_first_sleep(tmp_path: Path, monkeypatch) -> None:
    cache_dir = tmp_path / "audio-cache"
    cache_dir.mkdir()
    stale_cache = cache_dir / "generation.wav"
    stale_cache.write_bytes(b"audio")
    _age(stale_cache, 1.0)

    async def stop_after_sweep(_seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr("modules.system.cache_janitor.time.time", lambda: 10_000.0)
    monkeypatch.setattr("modules.system.cache_janitor.asyncio.sleep", stop_after_sweep)

    try:
        asyncio.run(run_audio_cache_janitor(
            _Policy(max_age=100),
            _Location(cache_dir),
            logging.getLogger("test.cache-janitor"),
        ))
    except asyncio.CancelledError:
        pass

    assert not stale_cache.exists()
