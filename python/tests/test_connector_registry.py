from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient
from modules.system.connector_registry import build_connector_registry_snapshot
from modules.system.message_connectors import MessageConnectorRegistry
from modules.system.runtime_endpoints import build_disable_connector_endpoint
from routes.system_api import create_system_router


def test_connector_registry_projects_runtime_and_planned_states() -> None:
    snapshot = build_connector_registry_snapshot(
        mcp_snapshot={
            "servers": {
                "calendar": {"transport": "http", "enabled": True},
                "offline": {"transport": "stdio", "enabled": False},
            },
            "status": {
                "calendar": {"enabled": True, "connected": True, "ok": True, "tools_count": 2},
                "offline": {"enabled": False, "connected": False, "ok": False},
            },
        },
        plugin_snapshot={
            "plugins": [
                {"id": "clock", "name": "Clock", "enabled": True, "loaded": False, "error": "load failed"},
                {"id": "notes", "name": "Notes", "enabled": False, "loaded": True},
            ],
        },
    )

    by_id = {item["id"]: item for item in snapshot["connectors"]}
    assert snapshot["schemaVersion"] == 1
    assert by_id["mcp:calendar"]["state"] == "running"
    assert by_id["mcp:offline"]["state"] == "disabled"
    assert by_id["plugin:clock"]["state"] == "failure"
    assert by_id["plugin:notes"]["state"] == "disabled"
    assert by_id["telegram"]["state"] == "uninstalled"
    assert by_id["discord"]["canDisable"] is False
    assert by_id["qq"]["state"] == "uninstalled"
    assert by_id["wechat"]["state"] == "uninstalled"
    assert snapshot["summary"]["running"] == 1
    assert snapshot["summary"]["failures"] == 1
    assert snapshot["summary"]["uninstalled"] == 5


def test_connector_registry_routes_are_read_only_until_disable_is_requested() -> None:
    app = FastAPI()
    app.include_router(create_system_router(
        health_handler=lambda: {"status": "healthy"},
        readiness_handler=lambda: {"ready": True},
        system_status_handler=lambda: {"status": "ok"},
        connector_registry_handler=lambda: {
            "schemaVersion": 1,
            "connectors": [{"id": "telegram", "state": "uninstalled"}],
            "summary": {"total": 1},
        },
        disable_connector_handler=lambda connector_id: {"ok": True, "connector": {"id": connector_id, "state": "disabled"}},
    ))

    client = TestClient(app)
    response = client.get("/api/system/connectors")
    assert response.status_code == 200
    assert response.json()["connectors"][0]["state"] == "uninstalled"
    response = client.post("/api/system/connectors/plugin%3Anotes/disable")
    assert response.status_code == 200
    assert response.json()["connector"]["state"] == "disabled"


def test_connector_registry_replaces_planned_rows_with_configured_adapters(tmp_path) -> None:
    adapters = MessageConnectorRegistry(
        state_path=tmp_path / "connectors.json",
        env={
            "YUIZAKI_TELEGRAM_BOT_TOKEN": "token",
            "YUIZAKI_TELEGRAM_ENABLED": "1",
            "YUIZAKI_TELEGRAM_WEBHOOK_SECRET": "webhook-secret",
        },
    )
    snapshot = build_connector_registry_snapshot(
        mcp_snapshot={"servers": {}, "status": {}},
        plugin_snapshot={"plugins": []},
        adapter_registry=adapters,
    )
    by_id = {item["id"]: item for item in snapshot["connectors"]}
    assert by_id["telegram"]["state"] == "running"
    assert by_id["telegram"]["source"] == "adapter"
    assert by_id["telegram"]["canDisable"] is True
    assert by_id["discord"]["state"] == "uninstalled"


def test_disable_connector_endpoint_stops_an_agent_plugin_without_starting_external_services() -> None:
    class FakeMCP:
        def snapshot(self):
            return {"servers": {}, "status": {}}

        def set_enabled(self, _name: str, _enabled: bool):
            return None

    class FakePlugins:
        def __init__(self):
            self.enabled = True

        def set_enabled(self, name: str, enabled: bool):
            if name != "notes":
                return None
            self.enabled = enabled
            return {"id": name, "enabled": enabled}

        def snapshot(self):
            return {"plugins": [{"id": "notes", "name": "Notes", "enabled": self.enabled, "loaded": True}]}

    handler = build_disable_connector_endpoint(mcp_manager=FakeMCP(), plugin_manager=FakePlugins())
    result = asyncio.run(handler("plugin:notes"))
    assert result["ok"] is True
    assert result["connector"]["state"] == "disabled"

    planned = asyncio.run(handler("telegram"))
    assert planned["ok"] is False
    assert planned["connector"] is None


def test_disable_connector_endpoint_stops_configured_message_adapter(tmp_path) -> None:
    adapters = MessageConnectorRegistry(
        state_path=tmp_path / "connectors.json",
        env={
            "YUIZAKI_TELEGRAM_BOT_TOKEN": "token",
            "YUIZAKI_TELEGRAM_ENABLED": "1",
            "YUIZAKI_TELEGRAM_WEBHOOK_SECRET": "webhook-secret",
        },
    )
    handler = build_disable_connector_endpoint(mcp_manager=type("MCP", (), {})(), plugin_manager=type("Plugins", (), {})(), adapter_registry=adapters)
    result = asyncio.run(handler("telegram"))
    assert result["ok"] is True
    assert result["connector"]["state"] == "disabled"
