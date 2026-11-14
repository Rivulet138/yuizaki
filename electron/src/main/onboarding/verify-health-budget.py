"""Isolated health regression evidence; no running service, model, or user data access.
Run with: python/.venv/Scripts/python.exe electron/src/main/onboarding/verify-health-budget.py
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import subprocess
import sys
import time
import threading
import types

ROOT = Path(__file__).resolve().parents[4]


def load(name: str, relative: str, baseline: bool = False):
    source = subprocess.check_output(["git", "show", f"HEAD:{relative}"], cwd=ROOT, text=True, encoding="utf-8") if baseline else (ROOT / relative).read_text(encoding="utf-8")
    module = types.ModuleType(name)
    sys.modules[name] = module
    exec(compile(source, relative, "exec"), module.__dict__)
    return module


async def exercise():
    current = load("health_budget_current", "python/modules/system/health_check.py")
    providers = load("health_providers_current", "python/modules/system/health_providers.py")
    baseline = load("health_budget_baseline", "python/modules/system/health_check.py", True)
    old_providers = load("health_providers_baseline", "python/modules/system/health_providers.py", True)
    metrics = {}

    class SlowTts:
        calls = 0
        def status_snapshot(self):
            self.calls += 1
            time.sleep(0.3)
            return {"available": True}

    def build(factory, tts):
        return factory.build_app_runtime_health_providers(
            llm_client_provider=lambda: None, tts_client_provider=lambda: tts,
            asr_manager_provider=lambda: None, ocr_client_provider=lambda: None,
            database_repository_provider=lambda: None, memory_state_provider=lambda: None,
        )

    async def timed(checker):
        started = time.monotonic()
        result = await checker.check_all()
        return (time.monotonic() - started) * 1000, result

    old = baseline.HealthChecker(check_timeout_seconds=0.04)
    old.register_check("tts", build(old_providers, SlowTts()).tts)
    elapsed, result = await timed(old)
    assert elapsed >= 280 and result["status"] == "healthy", (elapsed, result)
    metrics["baseline_sync_tts_40ms_budget"] = {"duration_ms": round(elapsed, 1), "status": result["status"]}

    tts = SlowTts()
    new = current.HealthChecker(check_timeout_seconds=0.04)
    new.register_check("tts", build(providers, tts).tts)
    async def heartbeat():
        started = time.monotonic()
        await asyncio.sleep(0.01)
        return (time.monotonic() - started) * 1000
    (elapsed, result), ping_ms = await asyncio.gather(timed(new), heartbeat())
    assert elapsed < 200 and ping_ms < 150, (elapsed, ping_ms)
    assert result["status"] == "unhealthy" and result["components"][0]["budget_ms"] == 40
    assert result["components"][0]["checked_at"] and result["components"][0]["source"] == "python.health:tts"
    await new.check_all()
    assert tts.calls == 1, "A timed-out worker must be reused rather than duplicated"
    metrics["current_sync_tts_40ms_budget"] = {"duration_ms": round(elapsed, 1), "heartbeat_ms": round(ping_ms, 1), "status": result["status"], "snapshot_calls_after_two_scans": tts.calls}
    await asyncio.sleep(0.32)
    assert new.get_status()["status"] == "unhealthy", "Late snapshot must not rewrite timed-out results"

    async def cancellation_case(checker_type):
        calls = 0
        async def slow_cleanup():
            nonlocal calls
            calls += 1
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                await asyncio.sleep(0.18)
                return True, "late completion"
        checker = checker_type(check_timeout_seconds=0.04)
        checker.register_check("slow_cleanup", slow_cleanup)
        elapsed, result = await timed(checker)
        return checker, elapsed, result, lambda: calls

    _, old_ms, _, _ = await cancellation_case(baseline.HealthChecker)
    checker, new_ms, result, calls = await cancellation_case(current.HealthChecker)
    assert old_ms >= 200 and new_ms < 180, (old_ms, new_ms)
    assert result["status"] == "unhealthy"
    still_pending = await checker.check_all()
    assert calls() == 1 and "fresh probe not run" in still_pending["components"][0]["message"]
    await asyncio.sleep(0.22)
    assert checker.get_status()["status"] == "unhealthy"
    metrics["slow_cancel_cleanup"] = {"baseline_ms": round(old_ms, 1), "current_ms": round(new_ms, 1), "late_completion_ignored": True}

    count = 0
    async def failure():
        nonlocal count
        count += 1
        await asyncio.sleep(0.01)
        raise ValueError("fixture failure detail")
    checker = current.HealthChecker(check_timeout_seconds=0.1)
    checker.register_check("failure", failure)
    left, right = await asyncio.gather(checker.check_all(), checker.check_all())
    assert count == 1 and left == right
    assert left["components"][0]["message"] == "ValueError: fixture failure detail"
    metrics["concurrent_callers"] = {"provider_calls": count, "detailed_error": left["components"][0]["message"]}
    # A synchronous provider can prevent asyncio's timeout callback from running.
    # Its eventual successful return is still a late result, never a pass.
    checker = current.HealthChecker(check_timeout_seconds=0.02)
    called_after_deadline = False
    async def blocking_fixture():
        time.sleep(0.08)
        return True, "blocking function returned success"
    async def queued_fixture():
        nonlocal called_after_deadline
        called_after_deadline = True
        return True, "queued function ran"
    checker.register_check("blocking_fixture", blocking_fixture)
    checker.register_check("queued_fixture", queued_fixture)
    elapsed, result = await timed(checker)
    assert result["status"] == "unhealthy" and all(item["status"] == "unhealthy" for item in result["components"])
    assert "completed after" in result["components"][0]["message"]
    assert not called_after_deadline and "did not start" in result["components"][1]["message"]
    metrics["late_success_and_expired_queue"] = {"duration_ms": round(elapsed, 1), "budget_ms": 20, "status": result["status"], "expired_check_executed": called_after_deadline}

    # Snapshot reuse must remain scoped to the actual provider instance.
    release = threading.Event()
    entered = threading.Event()
    class OldTts:
        def status_snapshot(self):
            entered.set()
            release.wait(1)
            return {"available": True}
    class NewTts:
        def status_snapshot(self):
            return {"available": False, "last_error": "replacement is unavailable"}
    active_tts = [OldTts()]
    changing = providers.build_app_runtime_health_providers(
        llm_client_provider=lambda: None, tts_client_provider=lambda: active_tts[0],
        asr_manager_provider=lambda: None, ocr_client_provider=lambda: None,
        database_repository_provider=lambda: None, memory_state_provider=lambda: None,
    )
    old_probe = asyncio.create_task(changing.tts())
    while not entered.is_set():
        await asyncio.sleep(0.001)
    try:
        active_tts[0] = NewTts()
        replacement = await asyncio.wait_for(changing.tts(), timeout=0.5)
        assert replacement == (False, "TTS unavailable: replacement is unavailable"), replacement
    finally:
        release.set()
        await old_probe
    metrics["provider_replacement"] = {"ready": replacement[0], "message": replacement[1]}

    print(json.dumps({"verification": "passed", "interpreter": sys.executable, "prefix": sys.prefix, "base_prefix": sys.base_prefix, "metrics": metrics}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(exercise())
