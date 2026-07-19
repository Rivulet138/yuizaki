"""Dynamic reconfiguration - runtime configuration updates."""

import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

SENSITIVE_KEY_PARTS = ("api_key", "apikey", "token", "secret", "password")


def redact_sensitive_config_value(value: Any, key_hint: str = "") -> Any:
    normalized_key = key_hint.replace("-", "_").lower()
    if any(part in normalized_key for part in SENSITIVE_KEY_PARTS):
        return value if value is None or value == "" else "<redacted>"
    if isinstance(value, dict):
        return {str(key): redact_sensitive_config_value(item, str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_sensitive_config_value(item, key_hint) for item in value]
    return value


class ConfigChangeListener:
    """Listener for configuration changes."""

    def __init__(self, callback: Callable[[str, Any, Any], Awaitable[None]], keys: Optional[List[str]] = None):
        """Initialize listener.

        Args:
            callback: Async function to call on config change.
            keys: Specific keys to listen for. If None, listens to all changes.
        """
        self.callback = callback
        self.keys = keys or []

    async def on_change(self, key: str, old_value: Any, new_value: Any) -> None:
        """Handle configuration change."""
        if not self.keys or key in self.keys:
            await self.callback(key, old_value, new_value)


class ConfigChangeEvent:
    """Configuration change event."""

    def __init__(self, key: str, old_value: Any, new_value: Any):
        """Initialize change event.

        Args:
            key: Configuration key that changed.
            old_value: Previous value.
            new_value: New value.
        """
        self.key = key
        self.old_value = old_value
        self.new_value = new_value
        self.timestamp = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "key": self.key,
            "old_value": redact_sensitive_config_value(self.old_value, self.key),
            "new_value": redact_sensitive_config_value(self.new_value, self.key),
            "timestamp": self.timestamp.isoformat(),
        }


class DynamicConfigManager:
    """Manages dynamic configuration updates at runtime."""

    def __init__(self):
        """Initialize dynamic config manager."""
        self.config: Dict[str, Any] = {}
        self.listeners: List[ConfigChangeListener] = []
        self.change_history: List[ConfigChangeEvent] = []
        self.max_history = 100

    def register_listener(self, listener: ConfigChangeListener) -> None:
        """Register a configuration change listener.

        Args:
            listener: Listener to register.
        """
        self.listeners.append(listener)
        logger.info(f"Registered config listener: {listener}")

    def unregister_listener(self, listener: ConfigChangeListener) -> None:
        """Unregister a configuration change listener.

        Args:
            listener: Listener to unregister.
        """
        if listener in self.listeners:
            self.listeners.remove(listener)
            logger.info(f"Unregistered config listener: {listener}")

    async def update(self, key: str, value: Any) -> bool:
        """Update configuration and notify listeners.

        Args:
            key: Configuration key.
            value: New value.

        Returns:
            True if update was successful, False otherwise.
        """
        old_value = self.config.get(key)

        if old_value == value:
            logger.debug(f"Config {key} unchanged, skipping update")
            return True

        self.config[key] = value
        event = ConfigChangeEvent(key, old_value, value)
        self.change_history.append(event)

        # Keep history size bounded
        if len(self.change_history) > self.max_history:
            self.change_history.pop(0)

        logger.info(
            "Updated config %s: %s -> %s",
            key,
            redact_sensitive_config_value(old_value, key),
            redact_sensitive_config_value(value, key),
        )

        # Notify listeners
        for listener in self.listeners:
            try:
                await listener.on_change(key, old_value, value)
            except Exception as e:
                logger.error(f"Error notifying listener: {e}")

        return True

    async def update_batch(self, updates: Dict[str, Any]) -> bool:
        """Update multiple configuration values.

        Args:
            updates: Dictionary of key-value pairs to update.

        Returns:
            True if all updates were successful, False otherwise.
        """
        success = True
        for key, value in updates.items():
            if not await self.update(key, value):
                success = False
        return success

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value.

        Args:
            key: Configuration key.
            default: Default value if key not found.

        Returns:
            Configuration value or default.
        """
        return self.config.get(key, default)

    def get_all(self) -> Dict[str, Any]:
        """Get all configuration values.

        Returns:
            Dictionary of all configuration values.
        """
        return self.config.copy()

    def get_history(self, key: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """Get configuration change history.

        Args:
            key: Specific key to filter by. If None, returns all changes.
            limit: Maximum number of entries to return.

        Returns:
            List of change events.
        """
        history = self.change_history
        if key:
            history = [e for e in history if e.key == key]
        return [e.to_dict() for e in history[-limit:]]

    def validate_update(self, key: str, value: Any) -> tuple[bool, str]:
        """Validate a configuration update.

        Args:
            key: Configuration key.
            value: Value to validate.

        Returns:
            Tuple of (is_valid, error_message).
        """
        # Add custom validation logic here
        if value is None:
            return False, f"Value for {key} cannot be None"
        return True, ""

    def rollback(self, steps: int = 1) -> bool:
        """Rollback configuration changes.

        Args:
            steps: Number of changes to rollback.

        Returns:
            True if rollback was successful, False otherwise.
        """
        if steps > len(self.change_history):
            logger.warning(f"Cannot rollback {steps} steps, only {len(self.change_history)} changes available")
            return False

        for _ in range(steps):
            if self.change_history:
                event = self.change_history.pop()
                if event.old_value is None:
                    self.config.pop(event.key, None)
                else:
                    self.config[event.key] = event.old_value
                logger.info(
                    "Rolled back %s to %s",
                    event.key,
                    redact_sensitive_config_value(event.old_value, event.key),
                )

        return True

    def clear_history(self) -> None:
        """Clear change history."""
        self.change_history.clear()
        logger.info("Cleared configuration change history")
