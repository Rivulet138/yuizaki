"""Settings persistence - JSON-based configuration storage."""

import json
import logging
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict
from datetime import datetime

from .dynamic_config import redact_sensitive_config_value
from ..core.paths import DEFAULT_SETTINGS_PATH, settings_path_from_env

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS_PATH_STR = str(DEFAULT_SETTINGS_PATH)
PROVIDER_CREDENTIALS_ENV = "YUIZAKI_PROVIDER_CREDENTIALS_JSON"
SETTINGS_SECRET_MASK = "********"
_SECRET_FIELD_NAMES = {"api_key", "vision_api_key", "qdrant_api_key"}


def _set_path(target: Dict[str, Any], field_path: str, value: str) -> None:
    parts = [part for part in field_path.split(".") if part]
    if not parts:
        return
    current = target
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value


def _credential_environment() -> Dict[str, str]:
    raw = os.getenv(PROVIDER_CREDENTIALS_ENV, "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Ignoring invalid provider credential environment payload")
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in payload.items()
        if isinstance(key, str) and isinstance(value, str) and value
    }


def _scrub_sensitive_settings(value: Any) -> Any:
    if isinstance(value, list):
        return [_scrub_sensitive_settings(item) for item in value]
    if not isinstance(value, dict):
        return deepcopy(value)
    result: Dict[str, Any] = {}
    for key, child in value.items():
        if key in _SECRET_FIELD_NAMES:
            result[key] = ""
        else:
            result[key] = _scrub_sensitive_settings(child)
    return result


class SettingsStore:
    """Persistent settings storage using JSON."""

    def __init__(self, storage_path: str | Path | None = None):
        """Initialize settings store.

        Args:
            storage_path: Path to JSON settings file.
        """
        self.storage_path = Path(storage_path) if storage_path is not None else settings_path_from_env()
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.transfer_dir = self.storage_path.parent / "transfers"
        self.transfer_dir.mkdir(parents=True, exist_ok=True)
        self.settings: Dict[str, Any] = self._load_settings()

    def resolve_transfer_path(self, relative_path: str) -> Path:
        target = (self.transfer_dir / relative_path).resolve()
        root = self.transfer_dir.resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError("Path escapes managed transfer directory") from exc
        return target

    def _load_settings(self) -> Dict[str, Any]:
        """Load settings from file."""
        settings: Dict[str, Any] = {}
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                logger.info(f"Loaded settings from {self.storage_path}")
            except Exception as e:
                logger.warning(f"Failed to load settings: {e}. Using defaults.")
                settings = {}
        for field_path, secret in _credential_environment().items():
            _set_path(settings, field_path, secret)
        return settings

    def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value.

        Args:
            key: Setting key (supports dot notation: "section.key").
            default: Default value if key not found.

        Returns:
            Setting value or default.
        """
        keys = key.split(".")
        value = self.settings
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        return value

    def set(self, key: str, value: Any) -> None:
        """Set a setting value.

        Args:
            key: Setting key (supports dot notation: "section.key").
            value: Value to set.
        """
        keys = key.split(".")
        current = self.settings

        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]

        current[keys[-1]] = value
        logger.debug("Set setting %s = %s", key, redact_sensitive_config_value(value, key))

    def delete(self, key: str) -> bool:
        """Delete a setting.

        Args:
            key: Setting key.

        Returns:
            True if deleted, False if not found.
        """
        keys = key.split(".")
        current = self.settings

        for k in keys[:-1]:
            if k not in current:
                return False
            current = current[k]

        if keys[-1] in current:
            del current[keys[-1]]
            logger.debug(f"Deleted setting {key}")
            return True
        return False

    def save(self) -> None:
        """Save settings to file."""
        try:
            persisted = _scrub_sensitive_settings(self.settings)
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(persisted, f, indent=2, ensure_ascii=True)
            logger.info(f"Saved settings to {self.storage_path}")
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")
            raise

    def load(self) -> None:
        """Reload settings from file."""
        self.settings = self._load_settings()

    def clear(self) -> None:
        """Clear all settings."""
        self.settings = {}
        logger.info("Cleared all settings")

    def get_all(self) -> Dict[str, Any]:
        """Get all settings."""
        return deepcopy(self.settings)

    def replace(self, settings: Dict[str, Any]) -> None:
        self.settings = deepcopy(settings)

    def update(self, updates: Dict[str, Any]) -> None:
        """Update multiple settings.

        Args:
            updates: Dictionary of settings to update.
        """
        for key, value in updates.items():
            self.set(key, value)
        logger.info(f"Updated {len(updates)} settings")

    def export(self, filepath: str) -> None:
        """Export settings to file.

        Args:
            filepath: Path to export to.
        """
        try:
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(_scrub_sensitive_settings(self.settings), f, indent=2, ensure_ascii=True)
            logger.info(f"Exported settings to {filepath}")
        except Exception as e:
            logger.error(f"Failed to export settings: {e}")

    def export_managed(self, relative_path: str) -> Path:
        target = self.resolve_transfer_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(_scrub_sensitive_settings(self.settings), f, indent=2, ensure_ascii=True)
        logger.info(f"Exported settings to managed path {target}")
        return target

    def import_settings(self, filepath: str) -> None:
        """Import settings from file.

        Args:
            filepath: Path to import from.
        """
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                imported = json.load(f)
            self.settings.update(imported)
            logger.info(f"Imported settings from {filepath}")
        except Exception as e:
            logger.error(f"Failed to import settings: {e}")

    def import_managed(self, relative_path: str) -> Path:
        source = self.resolve_transfer_path(relative_path)
        logger.info(f"Validated settings source at managed path {source}")
        return source

    def get_metadata(self) -> Dict[str, Any]:
        """Get settings metadata.

        Returns:
            Metadata including file path, size, and last modified time.
        """
        if self.storage_path.exists():
            stat = self.storage_path.stat()
            return {
                "path": str(self.storage_path),
                "size_bytes": stat.st_size,
                "last_modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "settings_count": len(self.settings),
            }
        return {
            "path": str(self.storage_path),
            "exists": False,
        }
