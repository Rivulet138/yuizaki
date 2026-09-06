from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from routes.connector_api import ConnectorRecoveryController


class _Store:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.recovered: list[str] = []

    def list_connector_deliveries(self, *, status: str, limit: int) -> list[dict[str, object]]:
        assert status == "processing" and limit == 100
        return list(self.rows)

    def recover_stale_connector_turn(self, key: str) -> bool:
        if key in self.recovered:
            return False
        self.recovered.append(key)
        return True


@pytest.mark.asyncio
async def test_recovery_skips_active_task_and_recovers_each_stale_row_once() -> None:
    store = _Store([
        {"connector_id": "telegram", "event_id": "active", "delivery_key": "k-active"},
        {"connector_id": "telegram", "event_id": "stale", "delivery_key": "k-stale"},
    ])
    active = asyncio.create_task(asyncio.sleep(1))
    calls: list[tuple[str, str]] = []

    async def retry(connector_id: str, key: str) -> SimpleNamespace:
        calls.append((connector_id, key))
        return SimpleNamespace(status_code=200)

    controller = ConnectorRecoveryController(
        store_provider=lambda: store,
        active_tasks={"telegram:active": active},
        retry_callback=retry,
        interval_seconds=1,
    )
    assert await controller.run_once() == {"inspected": 2, "recovered": 1, "failed": 0}
    assert calls == [("telegram", "k-stale")]
    assert store.recovered == ["k-stale"]
    active.cancel()
    await asyncio.gather(active, return_exceptions=True)


@pytest.mark.asyncio
async def test_recovery_counts_retry_http_and_exception_failures(tmp_path: Path) -> None:
    store = _Store([
        {"connector_id": "telegram", "event_id": "bad", "delivery_key": "k-bad"},
        {"connector_id": "discord", "event_id": "boom", "delivery_key": "k-boom"},
    ])

    async def retry(_connector_id: str, key: str) -> SimpleNamespace:
        if key == "k-boom":
            raise RuntimeError("provider unavailable")
        return SimpleNamespace(status_code=502)

    metrics = tmp_path / "recovery.json"
    controller = ConnectorRecoveryController(
        store_provider=lambda: store,
        active_tasks={},
        retry_callback=retry,
        interval_seconds=1,
        metrics_path=metrics,
    )
    result = await controller.run_once()
    assert result == {"inspected": 2, "recovered": 2, "failed": 2}
    snapshot = controller.snapshot()
    assert snapshot["lastError"] == "retry_exception_RuntimeError"
    persisted = json.loads(metrics.read_text(encoding="utf-8"))
    assert "message" not in json.dumps(persisted)
