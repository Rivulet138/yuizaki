from __future__ import annotations

import os
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = BACKEND_ROOT / "data"
DEFAULT_AUDIO_CACHE_DIR = BACKEND_ROOT / "audio_cache"
DEFAULT_RUNTIME_TEMP_DIR = BACKEND_ROOT / "tmp"
DEFAULT_SETTINGS_PATH = BACKEND_ROOT / "config" / "settings.json"


def resolve_backend_path(value: str | Path | None, default: Path) -> Path:
    raw = str(value or "").strip()
    path = Path(raw).expanduser() if raw else default
    if not path.is_absolute():
        path = BACKEND_ROOT / path
    return path.resolve()


def data_dir_from_env() -> Path:
    return resolve_backend_path(os.getenv("YUIZAKI_DATA_DIR"), DEFAULT_DATA_DIR)


def database_url_from_env() -> str:
    """Resolve the chat database URL, with an explicit URL taking precedence."""
    explicit_url = os.getenv("DATABASE_URL", "").strip()
    if explicit_url:
        return explicit_url
    return f"sqlite:///{(data_dir_from_env() / 'chat.db').as_posix()}"


def audio_cache_dir_from_env() -> Path:
    value = os.getenv("AUDIO_CACHE_DIR")
    return resolve_backend_path(value, DEFAULT_AUDIO_CACHE_DIR)


def settings_path_from_env() -> Path:
    explicit_path = os.getenv("YUIZAKI_SETTINGS_PATH")
    if explicit_path and explicit_path.strip():
        return resolve_backend_path(explicit_path, DEFAULT_SETTINGS_PATH)
    if os.getenv("YUIZAKI_DATA_DIR", "").strip():
        return data_dir_from_env() / "settings.json"
    return DEFAULT_SETTINGS_PATH
