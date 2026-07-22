"""Service manager - manages service lifecycle and dependencies."""

import logging
import time
from collections.abc import Callable
from typing import Any, Optional
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class ServiceStatus(Enum):
    """Service status enumeration."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


class ServiceInfo:
    """Information about a service."""

    def __init__(self, name: str, init_func: Callable[[], Any], cleanup_func: Optional[Callable[[], Any]] = None):
        """Initialize service info.

        Args:
            name: Service name
            init_func: Async function to initialize service
            cleanup_func: Async function to cleanup service
        """
        self.name = name
        self.init_func = init_func
        self.cleanup_func = cleanup_func
        self.status = ServiceStatus.STOPPED
        self.started_at: Optional[datetime] = None
        self.error: Optional[str] = None
        self.startup_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "error": self.error,
            "startup_ms": round(self.startup_ms, 1) if self.startup_ms is not None else None,
        }


class ServiceManager:
    """Manages service lifecycle."""

    def __init__(self):
        """Initialize service manager."""
        self.services: dict[str, ServiceInfo] = {}
        self.startup_order: list[str] = []
        self.shutdown_order: list[str] = []

    def register(
        self,
        name: str,
        init_func: Callable[[], Any],
        cleanup_func: Optional[Callable[[], Any]] = None,
        depends_on: Optional[list[str]] = None,
    ) -> None:
        """Register a service.

        Args:
            name: Service name
            init_func: Async initialization function
            cleanup_func: Async cleanup function
            depends_on: List of service names this service depends on
        """
        if name in self.services:
            logger.warning(f"Service {name} already registered, overwriting")
            self.startup_order = [service_name for service_name in self.startup_order if service_name != name]

        service = ServiceInfo(name, init_func, cleanup_func)
        self.services[name] = service

        # Add to startup order (simple topological sort)
        if depends_on:
            for dep in depends_on:
                if dep not in self.startup_order:
                    self.startup_order.append(dep)
        if name not in self.startup_order:
            self.startup_order.append(name)

        # Reverse for shutdown
        self.shutdown_order = list(reversed(self.startup_order))

        logger.info(f"Registered service: {name}")

    async def start_all(self) -> bool:
        """Start all registered services.

        Returns:
            True if all services started successfully, False otherwise.
        """
        logger.info("Starting all services...")
        started_services: list[ServiceInfo] = []
        for service_name in self.startup_order:
            if service_name not in self.services:
                continue

            service = self.services[service_name]
            try:
                service.status = ServiceStatus.STARTING
                started = time.perf_counter()
                await service.init_func()
                service.startup_ms = (time.perf_counter() - started) * 1000
                service.status = ServiceStatus.RUNNING
                service.started_at = datetime.now()
                started_services.append(service)
                logger.info("Service started: %s (%.1f ms)", service_name, service.startup_ms)
                logger.info(f"✓ Service started: {service_name}")
            except Exception as e:
                service.status = ServiceStatus.ERROR
                service.error = str(e)
                logger.error("Failed to start service %s: %s", service_name, e)
                for started_service in reversed(started_services):
                    if not started_service.cleanup_func:
                        continue
                    try:
                        await started_service.cleanup_func()
                        started_service.status = ServiceStatus.STOPPED
                    except Exception as cleanup_error:
                        logger.warning("Startup rollback failed for %s: %s", started_service.name, cleanup_error)
                return False

        total_ms = sum(service.startup_ms or 0.0 for service in started_services)
        logger.info("All services started successfully (service_time_ms=%.1f)", total_ms)
        return True

    async def stop_all(self) -> None:
        """Stop all running services."""
        logger.info("Stopping all services...")
        for service_name in self.shutdown_order:
            if service_name not in self.services:
                continue

            service = self.services[service_name]
            if service.status != ServiceStatus.RUNNING:
                continue

            try:
                service.status = ServiceStatus.STOPPING
                if service.cleanup_func:
                    await service.cleanup_func()
                service.status = ServiceStatus.STOPPED
                logger.info(f"✓ Service stopped: {service_name}")
            except Exception as e:
                service.status = ServiceStatus.ERROR
                service.error = str(e)
                logger.error(f"✗ Failed to stop service {service_name}: {e}")

        logger.info("All services stopped")

    def get_status(self, service_name: Optional[str] = None) -> dict[str, Any]:
        """Get service status.

        Args:
            service_name: Specific service name, or None for all services.

        Returns:
            Service status information.
        """
        if service_name:
            if service_name in self.services:
                return self.services[service_name].to_dict()
            return {"error": f"Service {service_name} not found"}

        return {
            name: service.to_dict() for name, service in self.services.items()
        }

    def is_healthy(self) -> bool:
        """Check if all services are healthy.

        Returns:
            True if all services are running, False otherwise.
        """
        return all(
            service.status == ServiceStatus.RUNNING
            for service in self.services.values()
        )
