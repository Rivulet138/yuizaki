"""Replay the local external-connector chain without network access.

The check drives the same FastAPI webhook routes used by the renderer.  It
uses deterministic in-memory provider callbacks and a temporary SQLite
``TurnCommitStore`` so that signature verification, durable enqueue, Agent
turn creation, duplicate delivery handling, and provider failures remain
visible in CI.  It is contract/staging evidence only; it does not prove that
an internet-facing webhook, bot account, or platform credential is valid.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any

import httpx
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from modules.agent.turn_store import TurnCommitStore
from modules.system.message_connectors import MessageConnectorRegistry
from routes.connector_api import create_message_connector_router

SCHEMA_VERSION = "yuizaki.connector-staging-evaluation.v1"


class StagingTurnService:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, _trigger: str, request: object) -> SimpleNamespace:
        self.calls += 1
        return SimpleNamespace(
            replayed=False,
            context=SimpleNamespace(turn_id=getattr(request, "turn_id", "turn:staging")),
            result=SimpleNamespace(outcome="completed", reply="已收到，我在这里。"),
        )


async def _wait_for_status(store: TurnCommitStore, key: str, expected: str) -> dict[str, Any]:
    for _ in range(100):
        row = store.connector_delivery(key)
        if row is not None and row.get("status") == expected:
            return row
        await asyncio.sleep(0.01)
    raise AssertionError(f"delivery {key} did not reach {expected}")


def _app(
    registry: MessageConnectorRegistry,
    store: TurnCommitStore,
    turn_service: StagingTurnService,
) -> FastAPI:
    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=lambda: turn_service,
        active_workspace_id_provider=lambda: "default",
        delivery_store_provider=lambda: store,
        fast_ack_connectors={"telegram"},
    ))
    return app


async def _case(name: str, callback: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
    try:
        details = await callback()
        return {"name": name, "passed": True, "details": details}
    except Exception as exc:  # noqa: BLE001 - report every bounded scenario.
        return {"name": name, "passed": False, "error": f"{type(exc).__name__}: {str(exc)[:240]}"}


async def run_staging_checks() -> dict[str, Any]:
    async def telegram_success_and_duplicate() -> dict[str, Any]:
        provider_calls: list[dict[str, Any]] = []

        def http_post(url: str, headers: object, payload: object) -> dict[str, Any]:
            provider_calls.append({"url": url, "headers": headers, "payload": payload})
            return {"ok": True, "sent": True, "status_code": 200}

        with TemporaryDirectory(prefix="yuizaki-connector-staging-") as directory:
            registry = MessageConnectorRegistry(http_post=http_post)
            registry.update_config("telegram", {
                "botToken": "staging-bot-token",
                "webhookSecret": "staging-webhook-secret",
                "enabled": True,
            })
            store = TurnCommitStore(Path(directory) / "turns.sqlite3")
            turn_service = StagingTurnService()
            app = _app(registry, store, turn_service)
            payload = {
                "update_id": 42,
                "message": {"chat": {"id": 123}, "from": {"id": 456}, "text": "你好"},
            }
            headers = {"X-Telegram-Bot-Api-Secret-Token": "staging-webhook-secret"}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://staging") as client:
                first = await client.post("/api/system/connectors/telegram/webhook", json=payload, headers=headers)
                assert first.status_code == 200 and first.json().get("queued") is True
                row = await _wait_for_status(store, "connector:telegram:42", "delivered")
                duplicate = await client.post("/api/system/connectors/telegram/webhook", json=payload, headers=headers)
                assert duplicate.status_code == 200 and duplicate.json().get("already_sent") is True
            assert turn_service.calls == 1
            assert len(provider_calls) == 1
            assert row["reply_text"] == "已收到，我在这里。"
            return {"turnCalls": turn_service.calls, "providerCalls": len(provider_calls), "duplicate": True}

    async def telegram_bad_secret_is_rejected() -> dict[str, Any]:
        with TemporaryDirectory(prefix="yuizaki-connector-staging-") as directory:
            registry = MessageConnectorRegistry()
            registry.update_config("telegram", {
                "botToken": "staging-bot-token",
                "webhookSecret": "staging-webhook-secret",
                "enabled": True,
            })
            store = TurnCommitStore(Path(directory) / "turns.sqlite3")
            turn_service = StagingTurnService()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(registry, store, turn_service)), base_url="http://staging") as client:
                response = await client.post(
                    "/api/system/connectors/telegram/webhook",
                    json={"update_id": 43, "message": {"chat": {"id": 123}, "text": "blocked"}},
                    headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
                )
            assert response.status_code == 401
            assert turn_service.calls == 0
            return {"statusCode": response.status_code, "agentCalls": 0}

    async def telegram_provider_failure_requires_manual_retry() -> dict[str, Any]:
        provider_calls = 0

        def http_post(_url: str, _headers: object, _payload: object) -> dict[str, Any]:
            nonlocal provider_calls
            provider_calls += 1
            if provider_calls == 1:
                return {"ok": False, "sent": False, "status_code": 502, "reason": "staging_provider_down"}
            return {"ok": True, "sent": True, "status_code": 200}

        with TemporaryDirectory(prefix="yuizaki-connector-staging-") as directory:
            registry = MessageConnectorRegistry(http_post=http_post)
            registry.update_config("telegram", {
                "botToken": "staging-bot-token",
                "webhookSecret": "staging-webhook-secret",
                "enabled": True,
            })
            store = TurnCommitStore(Path(directory) / "turns.sqlite3")
            turn_service = StagingTurnService()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(registry, store, turn_service)), base_url="http://staging") as client:
                response = await client.post(
                    "/api/system/connectors/telegram/webhook",
                    json={"update_id": 44, "message": {"chat": {"id": 123}, "text": "retry me"}},
                    headers={"X-Telegram-Bot-Api-Secret-Token": "staging-webhook-secret"},
                )
                assert response.status_code == 200
                failed = await _wait_for_status(store, "connector:telegram:44", "failed")
                assert failed["reply_text"] == "已收到，我在这里。"
                retry = await client.post("/api/system/connectors/telegram/events/44/retry")
                assert retry.status_code == 200 and retry.json().get("retried") is True
            delivered = store.connector_delivery("connector:telegram:44")
            assert delivered is not None and delivered["status"] == "delivered"
            assert turn_service.calls == 1
            assert provider_calls == 2
            return {"initialStatus": "failed", "finalStatus": delivered["status"], "agentCalls": 1, "providerCalls": provider_calls}

    async def discord_signature_and_duplicate() -> dict[str, Any]:
        public_key = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
        body = (
            b'{"type":2,"id":"interaction-42","application_id":"app-1",'
            b'"token":"interaction-token","channel_id":"channel-1",'
            b'"data":{"name":"hello","options":[{"name":"text","value":"\xe4\xbd\xa0\xe5\xa5\xbd"}]},'
            b'"member":{"user":{"id":"user-1"}}}'
        )
        timestamp = "1710000000"
        signature = (
            "84fff18844caa92084c4ae7ecc83c4103ce7bca67d9ff88a802fdee9a9a34c315"
            "382f0e188992093ef87d4fa4cc073bbfe56d502f4dc61f48c1f415bdd4f820d"
        )
        provider_calls: list[dict[str, Any]] = []

        def http_patch(url: str, headers: object, payload: object) -> dict[str, Any]:
            provider_calls.append({"url": url, "headers": headers, "payload": payload})
            return {"ok": True, "sent": True, "status_code": 200}

        with TemporaryDirectory(prefix="yuizaki-connector-staging-") as directory:
            registry = MessageConnectorRegistry(http_patch=http_patch, clock=lambda: 1710000000)
            registry.update_config("discord", {"publicKey": public_key, "enabled": True})
            store = TurnCommitStore(Path(directory) / "turns.sqlite3")
            turn_service = StagingTurnService()
            headers = {
                "Content-Type": "application/json",
                "X-Signature-Timestamp": timestamp,
                "X-Signature-Ed25519": signature,
            }
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(registry, store, turn_service)), base_url="http://staging") as client:
                first = await client.post("/api/system/connectors/discord/webhook", content=body, headers=headers)
                assert first.status_code == 200 and first.json().get("type") == 5
                await _wait_for_status(store, "connector:discord:interaction-42", "delivered")
                duplicate = await client.post("/api/system/connectors/discord/webhook", content=body, headers=headers)
                assert duplicate.status_code == 200 and duplicate.json().get("already_sent") is True
            assert turn_service.calls == 1
            assert len(provider_calls) == 1
            return {"turnCalls": turn_service.calls, "providerCalls": len(provider_calls), "duplicate": True}

    scenarios = [
        await _case("telegram_success_and_duplicate", telegram_success_and_duplicate),
        await _case("telegram_bad_secret_is_rejected", telegram_bad_secret_is_rejected),
        await _case("telegram_provider_failure_requires_manual_retry", telegram_provider_failure_requires_manual_retry),
        await _case("discord_signature_and_duplicate", discord_signature_and_duplicate),
    ]
    passed = sum(item["passed"] is True for item in scenarios)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "networkAccess": False,
        "realProviders": False,
        "claim": "local_connector_contract_replay_only",
        "summary": {"passed": passed, "total": len(scenarios)},
        "scenarios": scenarios,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = asyncio.run(run_staging_checks())
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(f"{args.output.suffix}.tmp")
        try:
            temporary.write_text(payload + "\n", encoding="utf-8")
            temporary.replace(args.output)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    print(payload)
    return 0 if report["summary"]["passed"] == report["summary"]["total"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
