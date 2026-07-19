from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from pathlib import Path
from typing import Protocol


class AudioCachePolicy(Protocol):
    max_age: int
    janitor_interval: int


class AudioCacheLocation(Protocol):
    audio_cache_dir: Path


_TEMP_AUDIO_PATTERNS = (
    "yuizaki_tts_warmup_*.wav",
    "yuizaki_svc_in_*.wav",
)


def sweep_stale_audio_files(
    cache_policy: AudioCachePolicy,
    cache_location: AudioCacheLocation,
    *,
    now: float | None = None,
    temp_dir: Path | None = None,
) -> dict[str, int]:
    """Remove only Yuizaki-generated WAV files older than the cache policy."""
    cutoff_now = time.time() if now is None else now
    max_age = max(1, int(cache_policy.max_age))
    cache_dir = Path(cache_location.audio_cache_dir).expanduser().resolve()
    system_temp_dir = (temp_dir or Path(tempfile.gettempdir())).expanduser().resolve()
    candidates = list(cache_dir.glob("*.wav")) if cache_dir.is_dir() else []
    if system_temp_dir.is_dir():
        for pattern in _TEMP_AUDIO_PATTERNS:
            candidates.extend(system_temp_dir.glob(pattern))

    removed = 0
    removed_bytes = 0
    failed = 0
    for file_path in candidates:
        try:
            if file_path.is_symlink() or not file_path.is_file():
                continue
            stat = file_path.stat()
            if cutoff_now - stat.st_mtime <= max_age:
                continue
            file_path.unlink()
            removed += 1
            removed_bytes += stat.st_size
        except OSError:
            failed += 1
    return {
        "scanned": len(candidates),
        "removed": removed,
        "removed_bytes": removed_bytes,
        "failed": failed,
    }


async def run_audio_cache_janitor(
    cache_policy: AudioCachePolicy,
    cache_location: AudioCacheLocation,
    logger: logging.Logger,
) -> None:
    while True:
        result = await asyncio.to_thread(sweep_stale_audio_files, cache_policy, cache_location)
        if result["removed"] or result["failed"]:
            logger.info(
                "audio cache janitor: removed=%d bytes=%d failed=%d scanned=%d",
                result["removed"],
                result["removed_bytes"],
                result["failed"],
                result["scanned"],
            )
        await asyncio.sleep(max(1, int(cache_policy.janitor_interval)))
