from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.system.onboarding_readiness import OnboardingReadiness
from routes.system_api import create_system_router


def _manager(**overrides):
    llm = overrides.get(
        "llm",
        SimpleNamespace(provider="openai", model="configured-chat", test_connection=AsyncMock(return_value={"ok": True, "message": "ok"})),
    )
    return OnboardingReadiness(
        llm_client_provider=lambda: llm,
        tts_client_provider=lambda: overrides.get("tts"),
        asr_manager_provider=lambda: overrides.get("asr"),
        database_repository_provider=lambda: overrides.get("database"),
        memory_state_provider=lambda: overrides.get("memory"),
        mcp_manager_provider=lambda: overrides.get("mcp"),
        default_timeout_ms=overrides.get("timeout_ms", 8_000),
    )


@pytest.mark.asyncio
async def test_required_model_probe_uses_non_persistent_connection_test() -> None:
    test_connection = AsyncMock(return_value={"ok": True, "message": "configured model replied"})
    llm = SimpleNamespace(provider="openai", model="configured-chat", test_connection=test_connection)
    manager = _manager(llm=llm)

    snapshot = await manager.run(["backend.service", "llm.provider", "llm.model_chat"])

    assert snapshot["readyForText"] is True
    test_connection.assert_awaited_once_with()
    assert next(item for item in snapshot["probes"] if item["id"] == "llm.model_chat")["durationMs"] is not None
    assert not hasattr(llm, "generation_manager")
    assert not hasattr(llm, "history")


@pytest.mark.asyncio
async def test_optional_failures_do_not_block_text_readiness() -> None:
    manager = _manager()

    snapshot = await manager.run()

    assert snapshot["readyForText"] is True
    probes = {probe["id"]: probe for probe in snapshot["probes"]}
    assert probes["tts.status"]["status"] == "degraded"
    assert probes["database.status"]["status"] == "degraded"
    assert probes["memory.status"]["requiredForText"] is False


@pytest.mark.asyncio
async def test_timeout_is_bounded_and_reported() -> None:
    async def _slow():
        await asyncio.sleep(1)
        return {"ok": True, "message": "late"}

    manager = _manager(llm=SimpleNamespace(provider="openai", model="slow", test_connection=_slow), timeout_ms=100)
    snapshot = await manager.run(["llm.model_chat"])
    probe = next(item for item in snapshot["probes"] if item["id"] == "llm.model_chat")

    assert probe["status"] == "unavailable"
    assert probe["evidence"] == {"category": "timeout"}
    assert probe["durationMs"] is not None
    assert probe["durationMs"] >= 0


@pytest.mark.asyncio
async def test_failed_dependencies_block_downstream_probes() -> None:
    test_connection = AsyncMock(return_value={"ok": True, "message": "must not run"})
    memory_status = Mock(return_value=SimpleNamespace(healthy=True, message="must not run"))
    manager = _manager(
        llm=SimpleNamespace(provider="", model="", test_connection=test_connection),
        database=None,
        memory=SimpleNamespace(store=SimpleNamespace(get_status=memory_status)),
    )

    snapshot = await manager.run(["llm.model_chat", "memory.status"])
    probes = {probe["id"]: probe for probe in snapshot["probes"]}

    assert probes["llm.model_chat"]["evidence"]["category"] == "blocked_by_dependency"
    assert probes["memory.status"]["evidence"] == {
        "category": "blocked_by_dependency",
        "dependencies": ["database.status"],
    }
    test_connection.assert_not_awaited()
    memory_status.assert_not_called()


@pytest.mark.asyncio
async def test_cancelled_run_rejects_stale_late_result() -> None:
    entered = asyncio.Event()

    async def _ignores_cancel_once():
        entered.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            return {"ok": True, "message": "late secret result"}
        return {"ok": True, "message": "unexpected"}

    manager = _manager(llm=SimpleNamespace(provider="openai", model="slow", test_connection=_ignores_cancel_once))
    running = asyncio.create_task(manager.run(["llm.model_chat"]))
    await entered.wait()
    run_id = manager.snapshot()["runId"]

    cancelled = await manager.cancel(run_id)
    await running

    final = manager.snapshot()
    probe = next(item for item in final["probes"] if item["id"] == "llm.model_chat")
    assert cancelled["state"] == "cancelled"
    assert final["state"] == "cancelled"
    assert probe["status"] == "cancelled"
    assert "late secret" not in probe["message"]


@pytest.mark.asyncio
async def test_external_cancel_awaits_probe_cleanup_before_returning() -> None:
    entered = asyncio.Event()
    cleaned = asyncio.Event()

    async def _cleanup_on_cancel():
        entered.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            await asyncio.sleep(0)
            cleaned.set()
            raise

    manager = _manager(llm=SimpleNamespace(provider="openai", model="slow", test_connection=_cleanup_on_cancel))
    running = asyncio.create_task(manager.run(["llm.model_chat"]))
    await entered.wait()

    cancelled = await manager.cancel(manager.snapshot()["runId"])

    assert cleaned.is_set()
    assert cancelled["state"] == "cancelled"
    await running


@pytest.mark.asyncio
async def test_superseding_run_awaits_prior_cleanup_before_new_probe() -> None:
    first_entered = asyncio.Event()
    first_cleaned = asyncio.Event()
    calls = 0

    async def _probe():
        nonlocal calls
        calls += 1
        if calls == 1:
            first_entered.set()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                await asyncio.sleep(0)
                first_cleaned.set()
                raise
        assert first_cleaned.is_set()
        return {"ok": True, "message": "new run"}

    manager = _manager(llm=SimpleNamespace(provider="openai", model="chat", test_connection=_probe))
    first = asyncio.create_task(manager.run(["llm.model_chat"]))
    await first_entered.wait()

    second_snapshot = await manager.run(["llm.model_chat"])
    await first

    assert first_cleaned.is_set()
    assert second_snapshot["readyForText"] is True
    assert calls == 2


@pytest.mark.asyncio
async def test_superseding_middle_probe_prevents_old_later_probe() -> None:
    middle_entered = asyncio.Event()
    database_stats = Mock(return_value={"total_messages": 0})

    async def _slow_tts_status():
        middle_entered.set()
        await asyncio.sleep(10)
        return {"available": True}

    manager = _manager(
        tts=SimpleNamespace(status_snapshot=_slow_tts_status),
        database=SimpleNamespace(get_database_stats=database_stats),
    )
    first = asyncio.create_task(manager.run(["tts.status", "database.status"]))
    await middle_entered.wait()

    second = await manager.run(["backend.service"])
    await first

    assert second["state"] == "completed"
    database_stats.assert_not_called()


@pytest.mark.asyncio
async def test_mcp_probe_is_snapshot_only_and_redacts_bounded_evidence() -> None:
    mcp = SimpleNamespace(
        snapshot=Mock(return_value={"servers": {"existing": {}}, "status": {"existing": {"ok": True}}}),
        refresh_status=AsyncMock(),
        refresh_one=AsyncMock(),
    )
    llm = SimpleNamespace(
        provider="openai",
        model="configured-chat",
        test_connection=AsyncMock(return_value={"ok": False, "message": "Bearer super-secret-token api_key=abc123 token:xyz"}),
    )
    manager = _manager(llm=llm, mcp=mcp)

    snapshot = await manager.run(["llm.model_chat", "mcp.snapshot"])

    mcp.snapshot.assert_called_once_with()
    mcp.refresh_status.assert_not_awaited()
    mcp.refresh_one.assert_not_awaited()
    probe = next(item for item in snapshot["probes"] if item["id"] == "llm.model_chat")
    assert probe["message"] == "Bearer [redacted] api_key=[redacted] token:[redacted]"


def test_action_route_rejects_malicious_or_unknown_payloads() -> None:
    action = AsyncMock(return_value={"ok": True})
    app = FastAPI()
    app.include_router(
        create_system_router(
            health_handler=lambda: {},
            readiness_handler=lambda: {},
            system_status_handler=lambda: {},
            onboarding_readiness_action_handler=action,
        )
    )
    client = TestClient(app)

    malicious = client.post(
        "/api/system/onboarding/readiness/action",
        json={"actionId": "mcp.refresh_existing", "command": "powershell", "args": ["evil"], "env": {"TOKEN": "x"}},
    )
    unknown = client.post("/api/system/onboarding/readiness/action", json={"actionId": "shell.run"})

    assert malicious.status_code == 422
    assert unknown.status_code == 422
    action.assert_not_awaited()


def test_readiness_routes_start_early_observe_and_cancel_after_cleanup() -> None:
    entered = threading.Event()
    cleaned = threading.Event()

    async def _slow_model():
        entered.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            await asyncio.sleep(0)
            cleaned.set()
            raise

    manager = _manager(llm=SimpleNamespace(provider="openai", model="slow", test_connection=_slow_model))
    app = FastAPI()
    app.include_router(
        create_system_router(
            health_handler=lambda: {},
            readiness_handler=lambda: {},
            system_status_handler=lambda: {},
            onboarding_readiness_state_handler=manager.snapshot,
            onboarding_readiness_run_handler=manager.start,
            onboarding_readiness_cancel_handler=manager.cancel,
        )
    )

    with TestClient(app) as client:
        started = client.post(
            "/api/system/onboarding/readiness/run",
            json={"probeIds": ["llm.model_chat"]},
        )
        assert started.status_code == 200
        assert started.json()["state"] == "running"
        run_id = started.json()["runId"]
        assert run_id
        assert entered.wait(timeout=1)

        observed = client.get("/api/system/onboarding/readiness")
        assert observed.status_code == 200
        assert observed.json()["runId"] == run_id
        assert observed.json()["state"] == "running"

        cancelled = client.post(
            "/api/system/onboarding/readiness/cancel",
            json={"runId": run_id},
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["state"] == "cancelled"
        assert cleaned.is_set()
