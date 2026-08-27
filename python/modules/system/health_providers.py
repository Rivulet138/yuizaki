from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass
from typing import Protocol, cast, runtime_checkable

HealthResult = tuple[bool, str]
HealthProvider = Callable[[], Coroutine[object, object, HealthResult]]

__all__ = [
    "RuntimeHealthProviders",
    "build_app_runtime_health_providers",
    "register_app_runtime_health_checks",
]


class HealthCheckRegistrar(Protocol):
    def register_check(self, name: str, check_func: HealthProvider, /) -> None: ...


class DatabaseHealthRepository(Protocol):
    def get_database_stats(self) -> Mapping[str, object]: ...


@runtime_checkable
class OcrHealthClient(Protocol):
    @property
    def is_available(self) -> bool: ...


@runtime_checkable
class MemoryHealthStatus(Protocol):
    healthy: bool
    message: str


@runtime_checkable
class MemoryHealthStore(Protocol):
    def get_status(self) -> MemoryHealthStatus: ...


@runtime_checkable
class MemoryHealthState(Protocol):
    @property
    def store(self) -> MemoryHealthStore: ...


@dataclass(frozen=True)
class RuntimeHealthProviders:
    llm: HealthProvider
    tts: HealthProvider
    asr: HealthProvider
    ocr: HealthProvider
    database: HealthProvider
    memory: HealthProvider


def build_app_runtime_health_providers(
    *,
    llm_client_provider: Callable[[], object | None],
    tts_client_provider: Callable[[], object | None],
    asr_manager_provider: Callable[[], object | None],
    ocr_client_provider: Callable[[], object | None],
    database_repository_provider: Callable[[], DatabaseHealthRepository | None],
    memory_state_provider: Callable[[], object | None],
) -> RuntimeHealthProviders:
    async def _check_llm_health() -> HealthResult:
        client = llm_client_provider()
        if client is None:
            return False, "LLM client not initialized"
        # A constructed client only proves local wiring.  Probe the upstream
        # when the client exposes the existing bounded preconnect contract.
        preconnect = getattr(client, "preconnect", None)
        if callable(preconnect):
            try:
                preconnect_call = cast(Callable[..., Awaitable[bool]], preconnect)
                reached = await asyncio.wait_for(preconnect_call(force=True), timeout=2.5)
            except asyncio.TimeoutError:
                return False, "LLM provider health probe timed out"
            except Exception as exc:  # noqa: BLE001 - provider-specific transport failures
                return False, f"LLM provider unavailable: {exc}"
            snapshot_provider = getattr(client, "status_snapshot", None)
            snapshot = snapshot_provider() if callable(snapshot_provider) else {}
            if isinstance(snapshot, Mapping) and snapshot.get("last_preconnect_ok") is False:
                return False, "LLM provider unavailable"
            if not reached:
                return False, "LLM provider unavailable"
            return True, "LLM service healthy"
        snapshot_provider = getattr(client, "status_snapshot", None)
        if callable(snapshot_provider):
            snapshot = snapshot_provider()
            if isinstance(snapshot, Mapping) and snapshot.get("last_preconnect_ok") is False:
                return False, "LLM provider unavailable"
        return True, "LLM service healthy"

    async def _check_tts_health() -> HealthResult:
        tts_client = tts_client_provider()
        if tts_client is None:
            return False, "TTS client not initialized"
        snapshot_provider = getattr(tts_client, "status_snapshot", None)
        if callable(snapshot_provider):
            try:
                snapshot = snapshot_provider()
            except Exception as exc:  # noqa: BLE001 - status adapters are provider-defined
                return False, f"TTS status error: {exc}"
            if not isinstance(snapshot, Mapping):
                return True, "TTS service healthy"
            if snapshot.get("warming_up"):
                return True, "TTS service warming up"
            if snapshot.get("available"):
                if snapshot.get("warmup_done"):
                    return True, "TTS service healthy (warmed)"
                return True, "TTS service healthy"
            last_error = snapshot.get("last_error")
            if last_error:
                return False, f"TTS unavailable: {last_error}"
            return False, "TTS client not ready"
        return True, "TTS service healthy"

    async def _check_asr_health() -> HealthResult:
        asr_manager = asr_manager_provider()
        if asr_manager is None:
            return True, "ASR not available (optional)"
        if getattr(asr_manager, "is_available", True):
            return True, "ASR service healthy"
        return False, "ASR configured but not available"

    async def _check_ocr_health() -> HealthResult:
        ocr_client = ocr_client_provider()
        if ocr_client is None:
            return False, "OCR client not initialized"
        if not isinstance(ocr_client, OcrHealthClient):
            return False, "OCR client does not expose availability"
        if ocr_client.is_available:
            return True, "OCR service healthy"
        if getattr(ocr_client, "initialization_state", "") == "idle":
            return True, "OCR ready on demand"
        return False, "OCR not available"

    async def _check_database_health() -> HealthResult:
        repository = database_repository_provider()
        if repository is None:
            return False, "Database not initialized"
        try:
            stats = await asyncio.to_thread(repository.get_database_stats)
        except Exception as exc:  # noqa: BLE001 - repository adapter boundary
            return False, f"Database error: {exc}"
        return True, f"Database healthy ({stats.get('total_messages', 0)} messages)"

    async def _check_memory_health() -> HealthResult:
        memory_state = memory_state_provider()
        if memory_state is None:
            return False, "Memory backend not initialized"
        if not isinstance(memory_state, MemoryHealthState):
            return False, "Memory store not initialized"
        status = await asyncio.to_thread(memory_state.store.get_status)
        return status.healthy, status.message

    return RuntimeHealthProviders(
        llm=_check_llm_health,
        tts=_check_tts_health,
        asr=_check_asr_health,
        ocr=_check_ocr_health,
        database=_check_database_health,
        memory=_check_memory_health,
    )


def register_app_runtime_health_checks(
    health_checker: HealthCheckRegistrar,
    providers: RuntimeHealthProviders,
) -> None:
    health_checker.register_check("llm", providers.llm)
    health_checker.register_check("tts", providers.tts)
    health_checker.register_check("asr", providers.asr)
    health_checker.register_check("ocr", providers.ocr)
    health_checker.register_check("database", providers.database)
    health_checker.register_check("memory", providers.memory)
