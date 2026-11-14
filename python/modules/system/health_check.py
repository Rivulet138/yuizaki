"""Health check - system diagnostics and monitoring."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from enum import Enum
from time import monotonic
from typing import Any

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
        self.checked_at: datetime | None = None
        self.response_time_ms: float = 0.0
        self.started_at: datetime | None = None
        self.budget_ms = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
            "response_time_ms": self.response_time_ms,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "budget_ms": self.budget_ms,
            "source": f"python.health:{self.name}",
        }


class HealthChecker:
    """System health checker."""

    def __init__(self, check_timeout_seconds: float = DEFAULT_HEALTH_CHECK_TIMEOUT_SECONDS):
        """Initialize health checker."""
        self.checks: dict[str, HealthCheckFunc] = {}
        self.components: dict[str, ComponentHealth] = {}
        self.last_check_time: datetime | None = None
        self.check_timeout_seconds = max(0.001, check_timeout_seconds)
        self._scan: asyncio.Task[dict[str, Any]] | None = None
        self._pending: dict[str, asyncio.Task[ComponentHealth]] = {}
        self.duration_ms = 0.0
        self.loop_lag_ms = 0.0

    def register_check(self, name: str, check_func: HealthCheckFunc) -> None:
        """Register a health check function.

        Args:
            name: Check name
            check_func: Async function that returns (is_healthy: bool, message: str)
        """
        self.checks[name] = check_func
        self.components[name] = ComponentHealth(name)
        logger.info(f"Registered health check: {name}")

    async def check_all(self) -> dict[str, Any]:
        """Run all health checks.

        Returns:
            Health check results.
        """
        # Concurrent callers share a scan; a disconnected caller cannot cancel it.
        if self._scan is None or self._scan.done():
            self._scan = asyncio.create_task(self._check_all())
        return await asyncio.shield(self._scan)

    async def _check_all(self) -> dict[str, Any]:
        self.last_check_time = datetime.now(timezone.utc)
        started = monotonic()
        self.loop_lag_ms = 0.0
        loop = asyncio.get_running_loop()
        interval = 0.05
        expected_tick = loop.time() + interval

        def sample_lag() -> None:
            nonlocal expected_tick, lag_timer
            now = loop.time()
            self.loop_lag_ms = max(self.loop_lag_ms, (now - expected_tick) * 1000)
            expected_tick = now + interval
            lag_timer = loop.call_later(interval, sample_lag)

        lag_timer = loop.call_later(interval, sample_lag)
        tasks: dict[str, asyncio.Task[ComponentHealth]] = {}
        for name, check_func in self.checks.items():
            previous = self._pending.get(name)
            if previous is not None and not previous.done():
                component = ComponentHealth(name, HealthStatus.UNHEALTHY)
                component.message = "Previous health probe is still finishing; fresh probe not run"
                component.budget_ms = self.check_timeout_seconds * 1000
                self.components[name] = component
                continue
            task = asyncio.create_task(self._run_check(name, check_func, started + self.check_timeout_seconds))
            tasks[name] = task
            self._pending[name] = task

        try:
            if tasks:
                await asyncio.wait(tasks.values(), timeout=self.check_timeout_seconds)
            for name, task in tasks.items():
                if task.done() and not task.cancelled():
                    self.components[name] = task.result()
                else:
                    component = ComponentHealth(name, HealthStatus.UNHEALTHY)
                    component.started_at = self.last_check_time
                    component.checked_at = datetime.now(timezone.utc)
                    component.budget_ms = self.check_timeout_seconds * 1000
                    component.response_time_ms = (monotonic() - started) * 1000
                    component.message = f"Health check timed out after {self.check_timeout_seconds:.1f}s total budget"
                    self.components[name] = component
                    logger.warning("Health total budget exceeded component=%s budget_ms=%.1f elapsed_ms=%.1f loop_lag_ms=%.1f", name, component.budget_ms, component.response_time_ms, self.loop_lag_ms)
                    # Do not wait for provider cancellation cleanup beyond the total budget.
                    # Results are task-local, so late completion cannot overwrite this scan.
                    task.cancel()
                    task.add_done_callback(self._consume_result)
        finally:
            lag_timer.cancel()
            self.duration_ms = (monotonic() - started) * 1000
        return self.get_status()

    @staticmethod
    def _consume_result(task: asyncio.Task[ComponentHealth]) -> None:
        if not task.cancelled():
            task.exception()

    async def _run_check(self, name: str, check_func: HealthCheckFunc, deadline: float) -> ComponentHealth:
        component = ComponentHealth(name)
        component.started_at = datetime.now(timezone.utc)
        component.budget_ms = self.check_timeout_seconds * 1000
        started = monotonic()
        if started >= deadline:
            component.status = HealthStatus.UNHEALTHY
            component.message = "Health check did not start before the total budget expired"
            component.checked_at = component.started_at
            return component
        try:
            is_healthy, message = await check_func()
            component.status = HealthStatus.HEALTHY if is_healthy else HealthStatus.DEGRADED
            component.message = message
        except Exception as exc:
            component.status = HealthStatus.UNHEALTHY
            component.message = f"{type(exc).__name__}: {exc}"
            logger.error("Health check failed for %s: %s", name, exc)
        component.checked_at = datetime.now(timezone.utc)
        finished = monotonic()
        component.response_time_ms = (finished - started) * 1000
        if finished > deadline:
            component.status = HealthStatus.UNHEALTHY
            component.message = f"Health check completed after {self.check_timeout_seconds:.1f}s total budget: {component.message}"
            logger.warning("Health late result component=%s budget_ms=%.1f duration_ms=%.1f", name, component.budget_ms, component.response_time_ms)
        return component

    def get_status(self) -> dict[str, Any]:
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
            "source": "python.health",
            "budget_ms": self.check_timeout_seconds * 1000,
            "duration_ms": self.duration_ms,
            "loop_lag_ms": round(self.loop_lag_ms, 2),
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
