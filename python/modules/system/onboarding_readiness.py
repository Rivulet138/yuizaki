"""Bounded, non-persistent probes for first-run text readiness."""

from __future__ import annotations

import asyncio
import inspect
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

ProbeStatus = Literal["pending", "running", "ready", "degraded", "unavailable", "cancelled"]
RunState = Literal["idle", "running", "completed", "cancelled"]
ProbeFunction = Callable[[], Awaitable[tuple[bool, str, Mapping[str, Any]]]]

SCHEMA_VERSION = 1
REQUIRED_TEXT_PROBES = ("backend.service", "llm.provider", "llm.model_chat")
_SENSITIVE_KEY = re.compile(r"(api[_-]?key|authorization|cookie|secret|token|password)", re.IGNORECASE)
_BEARER = re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]+")
_INLINE_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|authorization|cookie|secret|token|password)\b(\s*[:=]\s*)([^\s,;&]+)"
)
_MAX_TEXT = 240


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _redact(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if depth > 3:
        return "[truncated]"
    if _SENSITIVE_KEY.search(key):
        return "[redacted]"
    if isinstance(value, str):
        redacted = _BEARER.sub("Bearer [redacted]", value)
        redacted = _INLINE_SECRET.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", redacted)
        return redacted[:_MAX_TEXT]
    if isinstance(value, Mapping):
        return {str(k)[:64]: _redact(v, key=str(k), depth=depth + 1) for k, v in list(value.items())[:16]}
    if isinstance(value, (list, tuple)):
        return [_redact(item, depth=depth + 1) for item in value[:16]]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)[:_MAX_TEXT]


@dataclass(frozen=True)
class ProbeDefinition:
    probe_id: str
    label: str
    required_for_text: bool
    dependencies: tuple[str, ...]
    timeout_ms: int
    function: ProbeFunction
    repair_action_id: str | None = None


class OnboardingReadiness:
    """Runs a closed set of leaf probes and rejects results from stale runs."""

    def __init__(
        self,
        *,
        llm_client_provider: Callable[[], Any],
        tts_client_provider: Callable[[], Any],
        asr_manager_provider: Callable[[], Any],
        database_repository_provider: Callable[[], Any],
        memory_state_provider: Callable[[], Any],
        mcp_manager_provider: Callable[[], Any],
        default_timeout_ms: int = 8_000,
    ) -> None:
        self._llm_client_provider = llm_client_provider
        self._tts_client_provider = tts_client_provider
        self._asr_manager_provider = asr_manager_provider
        self._database_repository_provider = database_repository_provider
        self._memory_state_provider = memory_state_provider
        self._mcp_manager_provider = mcp_manager_provider
        self._run_id: str | None = None
        self._revision = 0
        self._state: RunState = "idle"
        self._started_at: str | None = None
        self._completed_at: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()
        timeout = max(100, min(int(default_timeout_ms), 30_000))
        self._definitions = self._build_definitions(timeout)
        self._results = {probe_id: self._initial_result(definition) for probe_id, definition in self._definitions.items()}

    def _build_definitions(self, timeout_ms: int) -> dict[str, ProbeDefinition]:
        definitions = (
            ProbeDefinition("backend.service", "Backend service", True, (), 1_000, self._probe_backend),
            ProbeDefinition("llm.provider", "LLM provider", True, ("backend.service",), 1_000, self._probe_llm_provider),
            ProbeDefinition("llm.model_chat", "Configured chat model", True, ("llm.provider",), timeout_ms, self._probe_llm_model),
            ProbeDefinition("tts.status", "Text-to-speech", False, ("backend.service",), 2_000, self._probe_tts),
            ProbeDefinition("asr.runtime", "Speech recognition", False, ("backend.service",), 2_000, self._probe_asr),
            ProbeDefinition("database.status", "Database", False, ("backend.service",), 2_000, self._probe_database),
            ProbeDefinition("memory.status", "Memory", False, ("database.status",), 2_000, self._probe_memory),
            ProbeDefinition("mcp.snapshot", "MCP servers", False, ("backend.service",), 2_000, self._probe_mcp, "mcp.refresh_existing"),
        )
        return {item.probe_id: item for item in definitions}

    @staticmethod
    def _initial_result(definition: ProbeDefinition) -> dict[str, Any]:
        return {
            "id": definition.probe_id,
            "label": definition.label,
            "status": "pending",
            "requiredForText": definition.required_for_text,
            "dependencies": list(definition.dependencies),
            "timeoutMs": definition.timeout_ms,
            "message": "Not checked",
            "evidence": {},
            "repairActionId": definition.repair_action_id,
        }

    def snapshot(self) -> dict[str, Any]:
        probes = [dict(self._results[probe_id]) for probe_id in self._definitions]
        required = [probe for probe in probes if probe["requiredForText"]]
        return {
            "schemaVersion": SCHEMA_VERSION,
            "runId": self._run_id,
            "revision": self._revision,
            "state": self._state,
            "readyForText": bool(required) and all(probe["status"] == "ready" for probe in required),
            "startedAt": self._started_at,
            "completedAt": self._completed_at,
            "probes": probes,
        }

    def _validate_probe_ids(self, probe_ids: Sequence[str] | None) -> tuple[str, ...]:
        if probe_ids is None:
            return tuple(self._definitions)
        normalized = tuple(dict.fromkeys(str(item).strip() for item in probe_ids))
        if not normalized or any(not item or item not in self._definitions for item in normalized):
            raise ValueError("probeIds must contain only known readiness probe IDs")
        included = set(normalized)
        pending = list(normalized)
        while pending:
            probe_id = pending.pop()
            for dependency in self._definitions[probe_id].dependencies:
                if dependency not in included:
                    included.add(dependency)
                    pending.append(dependency)
        return tuple(probe_id for probe_id in self._definitions if probe_id in included)

    async def _start_task(self, probe_ids: Sequence[str] | None = None) -> asyncio.Task[None]:
        selected = self._validate_probe_ids(probe_ids)
        async with self._start_lock:
            async with self._lock:
                prior_task = self._task if self._task is not None and not self._task.done() else None
                if prior_task is not None:
                    prior_task.cancel()
            if prior_task is not None:
                await asyncio.gather(prior_task, return_exceptions=True)
            async with self._lock:
                run_id = uuid.uuid4().hex
                self._run_id = run_id
                self._revision += 1
                self._state = "running"
                self._started_at = _now()
                self._completed_at = None
                for probe_id in selected:
                    self._results[probe_id] = self._initial_result(self._definitions[probe_id])
                    self._results[probe_id]["status"] = "running"
                    self._results[probe_id]["message"] = "Checking"
                self._task = asyncio.create_task(self._execute(run_id, selected))
                task = self._task
        return task

    async def start(self, probe_ids: Sequence[str] | None = None) -> dict[str, Any]:
        await self._start_task(probe_ids)
        return self.snapshot()

    async def run(self, probe_ids: Sequence[str] | None = None) -> dict[str, Any]:
        task = await self._start_task(probe_ids)
        try:
            await task
        except asyncio.CancelledError:
            pass
        return self.snapshot()

    async def retry(self, run_id: str, probe_ids: Sequence[str] | None = None) -> dict[str, Any]:
        if not run_id or run_id != self._run_id:
            raise LookupError("runId does not match the current readiness run")
        if probe_ids is None:
            probe_ids = [item["id"] for item in self._results.values() if item["status"] != "ready"]
            if not probe_ids:
                probe_ids = REQUIRED_TEXT_PROBES
        return await self.run(probe_ids)

    async def cancel(self, run_id: str) -> dict[str, Any]:
        async with self._lock:
            if not run_id or run_id != self._run_id:
                raise LookupError("runId does not match the current readiness run")
            task = self._task
            if task is None or task.done():
                raise RuntimeError("readiness run is not active")
            self._state = "cancelled"
            self._completed_at = _now()
            self._revision += 1
            for result in self._results.values():
                if result["status"] == "running":
                    result["status"] = "cancelled"
                    result["message"] = "Cancelled"
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return self.snapshot()

    async def execute_action(self, action_id: str) -> dict[str, Any]:
        if action_id != "mcp.refresh_existing":
            raise ValueError("unknown readiness actionId")
        manager = self._mcp_manager_provider()
        if manager is None:
            raise RuntimeError("MCP manager not initialized")
        servers = getattr(manager, "servers", {})
        refreshed: list[str] = []
        # Never launch stdio from onboarding. Explicit refresh is limited to
        # already configured network transports.
        for name, server in list(servers.items())[:32]:
            if not getattr(server, "enabled", False) or getattr(server, "transport", "http") == "stdio":
                continue
            result = manager.refresh_one(str(name), timeout_seconds=2.0)
            if inspect.isawaitable(result):
                await result
            refreshed.append(str(name)[:80])
        return {"ok": True, "actionId": action_id, "refreshed": refreshed}

    async def _execute(self, run_id: str, selected: tuple[str, ...]) -> None:
        try:
            for probe_id in selected:
                definition = self._definitions[probe_id]
                async with self._lock:
                    if self._run_id != run_id or self._state != "running":
                        return
                    blocked_by = [
                        dependency
                        for dependency in definition.dependencies
                        if self._results[dependency]["status"] != "ready"
                    ]
                    if blocked_by:
                        result = self._results[probe_id]
                        result.update(
                            status="unavailable" if definition.required_for_text else "degraded",
                            message="Blocked by unavailable dependency",
                            evidence={"category": "blocked_by_dependency", "dependencies": blocked_by},
                        )
                        self._revision += 1
                        continue
                await self._run_probe(run_id, definition)
        except asyncio.CancelledError:
            raise
        async with self._lock:
            if self._run_id != run_id or self._state != "running":
                return
            self._state = "completed"
            self._completed_at = _now()
            self._revision += 1

    async def _run_probe(self, run_id: str, definition: ProbeDefinition) -> None:
        try:
            ok, message, evidence = await asyncio.wait_for(
                definition.function(), timeout=definition.timeout_ms / 1000
            )
            status: ProbeStatus = "ready" if ok else ("unavailable" if definition.required_for_text else "degraded")
        except TimeoutError:
            status = "unavailable" if definition.required_for_text else "degraded"
            message, evidence = "Probe timed out", {"category": "timeout"}
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            status = "unavailable" if definition.required_for_text else "degraded"
            message, evidence = "Probe failed", {"category": type(exc).__name__, "detail": str(exc)}
        async with self._lock:
            if self._run_id != run_id or self._state != "running":
                return
            result = self._results[definition.probe_id]
            result.update(status=status, message=_redact(str(message)), evidence=_redact(evidence))
            self._revision += 1

    async def _probe_backend(self) -> tuple[bool, str, Mapping[str, Any]]:
        return True, "Backend service is responding", {"transport": "local-http"}

    async def _probe_llm_provider(self) -> tuple[bool, str, Mapping[str, Any]]:
        client = self._llm_client_provider()
        provider = str(getattr(client, "provider", "") or "").strip() if client is not None else ""
        model = str(getattr(client, "model", "") or "").strip() if client is not None else ""
        ok = bool(client is not None and provider and model)
        return ok, "LLM provider configured" if ok else "Configure an LLM provider and chat model", {
            "provider": provider or None,
            "model": model or None,
        }

    async def _probe_llm_model(self) -> tuple[bool, str, Mapping[str, Any]]:
        client = self._llm_client_provider()
        if client is None or not callable(getattr(client, "test_connection", None)):
            return False, "LLM client is not initialized", {}
        result = await client.test_connection()
        if not isinstance(result, Mapping):
            return False, "LLM model probe returned an invalid response", {}
        return bool(result.get("ok")), str(result.get("message") or "LLM model probe completed"), {
            "provider": getattr(client, "provider", None),
            "model": getattr(client, "model", None),
        }

    async def _probe_tts(self) -> tuple[bool, str, Mapping[str, Any]]:
        client = self._tts_client_provider()
        if client is None:
            return False, "TTS is not configured (optional)", {}
        status_provider = getattr(client, "status_snapshot", None)
        snapshot = status_provider() if callable(status_provider) else {"available": True}
        if inspect.isawaitable(snapshot):
            snapshot = await snapshot
        available = bool(snapshot.get("available", True)) if isinstance(snapshot, Mapping) else True
        return available, "TTS runtime available" if available else "TTS runtime unavailable (optional)", snapshot if isinstance(snapshot, Mapping) else {}

    async def _probe_asr(self) -> tuple[bool, str, Mapping[str, Any]]:
        manager = self._asr_manager_provider()
        available = bool(manager is not None and getattr(manager, "is_available", True))
        return available, "ASR runtime available" if available else "ASR is not available (optional)", {}

    async def _probe_database(self) -> tuple[bool, str, Mapping[str, Any]]:
        repository = self._database_repository_provider()
        if repository is None:
            return False, "Database is not initialized", {}
        stats = await asyncio.to_thread(repository.get_database_stats)
        total = stats.get("total_messages", 0) if isinstance(stats, Mapping) else 0
        return True, "Database available", {"totalMessages": total}

    async def _probe_memory(self) -> tuple[bool, str, Mapping[str, Any]]:
        state = self._memory_state_provider()
        store = getattr(state, "store", None)
        if store is None or not callable(getattr(store, "get_status", None)):
            return False, "Memory backend is not initialized", {}
        status = await asyncio.to_thread(store.get_status)
        ok = bool(getattr(status, "healthy", False))
        return ok, str(getattr(status, "message", "Memory status unavailable")), {"healthy": ok}

    async def _probe_mcp(self) -> tuple[bool, str, Mapping[str, Any]]:
        manager = self._mcp_manager_provider()
        if manager is None or not callable(getattr(manager, "snapshot", None)):
            return False, "MCP manager is not initialized (optional)", {}
        snapshot = manager.snapshot()
        servers = snapshot.get("servers", {}) if isinstance(snapshot, Mapping) else {}
        status = snapshot.get("status", {}) if isinstance(snapshot, Mapping) else {}
        configured = len(servers) if isinstance(servers, Mapping) else 0
        healthy = sum(1 for item in status.values() if isinstance(item, Mapping) and item.get("ok")) if isinstance(status, Mapping) else 0
        return True, "MCP configuration snapshot captured", {"configured": configured, "healthy": healthy}


__all__ = ["OnboardingReadiness", "REQUIRED_TEXT_PROBES", "SCHEMA_VERSION"]
