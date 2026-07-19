"""High-level settings schema for Yuizaki.

This module defines a typed SettingsSchema and a thin SettingsManager
wrapper around the existing JSON-based SettingsStore so that other
parts of the backend can consume a structured view of configuration
while still persisting to ``config/settings.json``.

The concrete fields are aligned with NEXT_STEPS.md and
modules.core.config so that:

* UI can expose LLM/TTS/ASR/SVC options
* Environment-variable based defaults still work
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from ..system.settings_store import SettingsStore
from ..system.settings_schema import PersistedSettingsSchema, merge_settings

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS_PATH = BACKEND_ROOT / "config" / "settings.json"

SettingsSchema = PersistedSettingsSchema


class SettingsManager:
    """Typed façade over SettingsStore.

    Settings are persisted to ``config/settings.json`` using
    SettingsStore, but exposed to callers as a strongly typed
    SettingsSchema instance.
    """

    def __init__(self, storage_path: Path | str = DEFAULT_SETTINGS_PATH) -> None:
        self._store = SettingsStore(str(storage_path))
        self.settings = self._load_from_store()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _load_from_store(self) -> SettingsSchema:
        raw: Dict[str, Any] = self._store.get_all()
        if not raw:
            return SettingsSchema()
        known = set(SettingsSchema.model_fields)
        filtered = {k: v for k, v in raw.items() if k in known}
        return SettingsSchema.model_validate(filtered)

    def _save_to_store(self) -> None:
        self._store.replace(self.settings.model_dump())
        self._store.save()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def reload(self) -> None:
        """Reload settings from disk into the typed schema."""

        self.settings = self._load_from_store()

    def update(self, **kwargs: Any) -> None:
        """Update top-level fields and persist.

        The front-end typically sends a flattened object where nested
        structures (llm/tts/...) are encoded as nested dictionaries.
        We simply delegate to Pydantic's ``update`` via ``dict`` merge.
        """

        data = self.settings.dict()
        self.settings = SettingsSchema.model_validate(merge_settings(data, kwargs))
        self._save_to_store()
