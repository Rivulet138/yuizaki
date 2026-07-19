"""Health check - system diagnostics and monitoring."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Dict, Any, Optional
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)

HealthCheckFunc = Callable[[], Awaitable[tuple[bool, str]]]
DEFAULT_HEALTH_CHECK_TIMEOUT_SECONDS = 5.0


class HealthStatus(Enum):
    """Health status enumeration."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ComponentHealth:
    """Health status of a component."""

    def __init__(self, name: str, status: HealthStatus = HealthStatus.HEALTHY):
        """Initialize component health.

        Args:
            name: Component name
            status: Initial health status
        """
        self.name = name
        self.status = status
        self.message = ""
        self.checked_at: Optional[datetime] = None
        self.response_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
            "response_time_ms": self.response_time_ms,
        }


class HealthChecker:
    """System health checker."""

    def __init__(self, check_timeout_seconds: float = DEFAULT_HEALTH_CHECK_TIMEOUT_SECONDS):
        """Initialize health checker."""
        self.checks: Dict[str, HealthCheckFunc] = {}
        self.components: Dict[str, ComponentHealth] = {}
        self.last_check_time: Optional[datetime] = None
        self.check_timeout_seconds = check_timeout_seconds

    def register_check(self, name: str, check_func: HealthCheckFunc) -> None:
        """Register a health check function.

        Args:
            name: Check name
            check_func: Async function that returns (is_healthy: bool, message: str)
        """
        self.checks[name] = check_func
        self.components[name] = ComponentHealth(name)
        logger.info(f"Registered health check: {name}")

    async def check_all(self) -> Dict[str, Any]:
        """Run all health checks.

        Returns:
            Health check results.
        """
        logger.debug("Running health checks...")
        self.last_check_time = datetime.now()

        tasks = []
        for name, check_func in self.checks.items():
            tasks.append(self._run_check(name, check_func))

        await asyncio.gather(*tasks, return_exceptions=True)

        return self.get_status()

    async def _run_check(self, name: str, check_func: HealthCheckFunc) -> None:
        """Run a single health check."""
        component = self.components[name]
        start_time = datetime.now()

        try:
            is_healthy, message = await asyncio.wait_for(
                check_func(),
                timeout=self.check_timeout_seconds,
            )
            component.status = (
                HealthStatus.HEALTHY if is_healthy else HealthStatus.DEGRADED
            )
            component.message = message
        except asyncio.TimeoutError:
            component.status = HealthStatus.UNHEALTHY
            component.message = f"Health check timed out after {self.check_timeout_seconds:.1f}s"
            logger.error(f"Health check timed out for {name}")
        except Exception as e:
            component.status = HealthStatus.UNHEALTHY
            component.message = str(e)
            logger.error(f"Health check failed for {name}: {e}")

        component.checked_at = datetime.now()
        component.response_time_ms = (
            component.checked_at - start_time
        ).total_seconds() * 1000

    def get_status(self) -> Dict[str, Any]:
        """Get current health status.

        Returns:
            Health status information.
        """
        components = [comp.to_dict() for comp in self.components.values()]

        # Determine overall status
        statuses = [comp.status for comp in self.components.values()]
        if all(s == HealthStatus.HEALTHY for s in statuses):
            overall_status = HealthStatus.HEALTHY
        elif any(s == HealthStatus.UNHEALTHY for s in statuses):
            overall_status = HealthStatus.UNHEALTHY
        else:
            overall_status = HealthStatus.DEGRADED

        return {
            "status": overall_status.value,
            "checked_at": self.last_check_time.isoformat() if self.last_check_time else None,
            "components": components,
        }

    def is_healthy(self) -> bool:
        """Check if system is healthy.

        Returns:
            True if all components are healthy, False otherwise.
        """
        return all(
            comp.status == HealthStatus.HEALTHY
            for comp in self.components.values()
        )

    def is_degraded(self) -> bool:
        """Check if system is degraded.

        Returns:
            True if any component is degraded or unhealthy, False otherwise.
        """
        return any(
            comp.status != HealthStatus.HEALTHY
            for comp in self.components.values()
        )
