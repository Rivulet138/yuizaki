"""Settings persistence - JSON-based configuration storage."""

import json
import logging
import os
import tempfile
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from ..core.paths import DEFAULT_SETTINGS_PATH, settings_path_from_env
from .dynamic_config import redact_sensitive_config_value

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS_PATH_STR = str(DEFAULT_SETTINGS_PATH)
PROVIDER_CREDENTIALS_ENV = "YUIZAKI_PROVIDER_CREDENTIALS_JSON"
SETTINGS_SECRET_MASK = "********"
_SECRET_FIELD_NAMES = {"api_key", "vision_api_key", "qdrant_api_key"}
_PROVIDER_CREDENTIAL_SECTIONS = {"llm", "tts", "asr", "svc", "memory"}


def _is_provider_credential_path(field_path: str) -> bool:
    parts = field_path.split(".")
    return len(parts) == 2 and parts[0] in _PROVIDER_CREDENTIAL_SECTIONS and parts[1] in _SECRET_FIELD_NAMES


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
        if isinstance(key, str)
        and _is_provider_credential_path(key)
        and isinstance(value, str)
        and value
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


def scrub_sensitive_settings(value: Any) -> Any:
    """Return a copy with provider credential values replaced by an empty string.

    Snapshots that survive a restart must never carry vault-sourced secrets;
    rollback restores the current secrets afterwards.
    """
    return _scrub_sensitive_settings(value)


def _fsync_directory(directory: Path) -> None:
    """Best-effort durability for the rename itself (POSIX only)."""
    if os.name == "nt":
        return
    try:
        descriptor = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _atomic_write_text(target: Path, payload: str) -> None:
    """Replace ``target`` with ``payload`` without exposing a partial file.

    Settings used to be truncated in place, so a crash or a full disk mid-write
    left an unparsable file that silently reset every preference on next start.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=str(target.parent),
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(5):
            try:
                os.replace(temporary_name, target)
                break
            except PermissionError:
                # Windows denies the replace while another handle briefly holds
                # the target; retry instead of losing the write.
                if attempt == 4:
                    raise
                time.sleep(0.02)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
    _fsync_directory(target.parent)


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
        """Load settings from file, quarantining an unparsable payload."""
        settings: Dict[str, Any] = {}
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if not isinstance(loaded, dict):
                    raise ValueError("settings payload must be a JSON object")
                settings = loaded
                logger.info(f"Loaded settings from {self.storage_path}")
            except OSError as e:
                logger.warning(f"Failed to read settings: {e}. Using defaults.")
                settings = {}
            except (ValueError, RecursionError) as e:
                # Keep the damaged file instead of letting the next save erase
                # whatever the user had configured.
                self._quarantine_corrupt_settings(e)
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

    def reload_provider_credentials(self, credentials: Dict[str, str]) -> int:
        """Replace in-memory provider secrets from an authenticated local sync.

        Credentials are deliberately never written to the settings JSON file. The
        caller must provide the complete allowlisted set, so removed vault values
        are cleared from this process as well.
        """
        if not isinstance(credentials, dict):
            raise ValueError("credentials must be an object")
        normalized: Dict[str, str] = {}
        for field_path, value in credentials.items():
            if not isinstance(field_path, str) or not _is_provider_credential_path(field_path):
                raise ValueError("unsupported provider credential field")
            if not isinstance(value, str):
                raise ValueError("provider credential values must be strings")
            clean = value.strip()
            if clean:
                normalized[field_path] = clean
        changed = 0
        for section in _PROVIDER_CREDENTIAL_SECTIONS:
            for field in _SECRET_FIELD_NAMES:
                field_path = f"{section}.{field}"
                current = self.get(field_path)
                next_value = normalized.get(field_path)
                if current != next_value:
                    self.set(field_path, next_value or "")
                    changed += 1
        return changed

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

    def _quarantine_corrupt_settings(self, error: Exception) -> None:
        """Move an unreadable settings file aside so it is not overwritten."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = self.storage_path.with_name(f"{self.storage_path.name}.corrupt-{timestamp}")
        try:
            os.replace(self.storage_path, backup)
            logger.warning("Quarantined unreadable settings file at %s: %s", backup, error)
        except OSError as exc:
            logger.warning(
                "Could not quarantine unreadable settings file at %s: %s",
                self.storage_path,
                exc,
            )

    def save(self) -> None:
        """Save settings to file atomically."""
        try:
            persisted = _scrub_sensitive_settings(self.settings)
            _atomic_write_text(self.storage_path, json.dumps(persisted, indent=2, ensure_ascii=True))
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
