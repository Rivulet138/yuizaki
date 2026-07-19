from __future__ import annotations

import os
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = BACKEND_ROOT / "data"
DEFAULT_AUDIO_CACHE_DIR = BACKEND_ROOT / "audio_cache"
DEFAULT_RUNTIME_TEMP_DIR = BACKEND_ROOT / "tmp"


def resolve_backend_path(value: str | Path | None, default: Path) -> Path:
    raw = str(value or "").strip()
    path = Path(raw).expanduser() if raw else default
    if not path.is_absolute():
        path = BACKEND_ROOT / path
    return path.resolve()


def data_dir_from_env() -> Path:
    return resolve_backend_path(os.getenv("YUIZAKI_DATA_DIR"), DEFAULT_DATA_DIR)


def audio_cache_dir_from_env() -> Path:
    value = os.getenv("AUDIO_CACHE_DIR")
    return resolve_backend_path(value, DEFAULT_AUDIO_CACHE_DIR)
