"""Runtime dependency container used by the application composition root.

The existing backend still exposes compatibility globals while it is being
migrated.  This container gives new code one typed place to obtain mutable
runtime services and makes lifecycle ownership explicit without changing the
underlying providers or database schemas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from logging import Logger, getLogger
from threading import RLock
from typing import Any


@dataclass
class RuntimeContainer:
    """Mutable service registry shared by HTTP and realtime composition."""

    config: Any
    logger: Logger = field(default_factory=lambda: getLogger("yuizaki"))
    _services: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
    started: bool = field(default=False, init=False)

    def set(self, name: str, value: Any) -> None:
        key = str(name).strip()
        if not key:
            raise ValueError("runtime_service_name_required")
        with self._lock:
            self._services[key] = value

    def get(self, name: str, default: Any = None) -> Any:
        with self._lock:
            return self._services.get(str(name).strip(), default)

    def require(self, name: str) -> Any:
        value = self.get(name)
        if value is None:
            raise RuntimeError(f"runtime_service_not_initialized:{name}")
        return value

    def remove(self, name: str) -> Any:
        with self._lock:
            return self._services.pop(str(name).strip(), None)

    def mark_started(self) -> None:
        with self._lock:
            self.started = True

    def mark_stopped(self) -> None:
        with self._lock:
            self.started = False

    def reload_config(self, config: Any | None = None) -> Any:
        """Replace the config object while keeping service identities stable."""

        if config is not None:
            self.config = config
        return self.config

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "started": self.started,
                "services": sorted(self._services),
            }


__all__ = ["RuntimeContainer"]
