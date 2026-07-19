from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from typing import Any, Callable, cast

from modules.agent.skill_store import SkillCatalogStore
from routes.system_api import create_system_router


_create_system_router = cast(Callable[..., Any], create_system_router)


def _build_test_client() -> TestClient:
    app = FastAPI()
    app.include_router(
        _create_system_router(
            health_handler=lambda: None,
            readiness_handler=lambda: None,
            system_status_handler=lambda: None,
            heartbeat_status_handler=lambda: {"running": True},
            companion_runtime_handler=lambda limit: {"limit": limit, "companion": "demo"},
            capabilities_state_handler=lambda: {"capabilities": [], "summary": {"total": 0}},
            orchestration_state_handler=lambda: {"skills": [], "commands": [], "hooks": []},
            active_workspace_handler=lambda payload: {"ok": True, "workspace_id": payload.get("workspace_id")},
            experience_metrics_handler=lambda: {"window": {"generation_samples": 4}},
        )
    )
    return TestClient(app)


def test_system_router_exposes_heartbeat_wrapper_route():
    client = _build_test_client()

    response = client.get("/api/system/heartbeat")

    assert response.status_code == 200
    assert response.json() == {"running": True}


def test_system_router_exposes_companion_runtime_wrapper_route_with_limit_param():
    client = _build_test_client()

    response = client.get("/api/system/companion-runtime", params={"limit": 11})

    assert response.status_code == 200
    assert response.json() == {"limit": 11, "companion": "demo"}


def test_system_router_exposes_capabilities_and_orchestration_routes():
    client = _build_test_client()

    capabilities = client.get("/api/system/capabilities")
    orchestration = client.get("/api/system/orchestration")

    assert capabilities.status_code == 200
    assert capabilities.json() == {"capabilities": [], "summary": {"total": 0}}
    assert orchestration.status_code == 200
    assert orchestration.json() == {"skills": [], "commands": [], "hooks": []}


def test_system_router_exposes_active_workspace_post_route():
    client = _build_test_client()

    response = client.post("/api/system/active-workspace", json={"workspace_id": "ws-focus"})

    assert response.status_code == 200
    assert response.json() == {"ok": True, "workspace_id": "ws-focus"}


def test_system_router_exposes_experience_metrics_route():
    client = _build_test_client()

    response = client.get("/api/system/experience-metrics")

    assert response.status_code == 200
    assert response.json() == {"window": {"generation_samples": 4}}


def _build_skill_test_client(tmp_path: Path) -> TestClient:
    store = SkillCatalogStore(str(tmp_path / "imported_skills.json"))
    app = FastAPI()
    app.include_router(
        _create_system_router(
            health_handler=lambda: None,
            readiness_handler=lambda: None,
            system_status_handler=lambda: None,
            imported_skills_state_handler=store.snapshot,
            save_imported_skills_handler=store.replace,
            remove_imported_skills_handler=store.remove_many,
        )
    )
    return TestClient(app)


def test_imported_skill_routes_persist_and_normalize_items(tmp_path: Path):
    client = _build_skill_test_client(tmp_path)

    response = client.put(
        "/api/system/skills/imported",
        json={
            "items": [
                {
                    "id": "voice-dialogue",
                    "name": "Voice Dialogue",
                    "description": "ASR 到 LLM 再到 TTS 的对话链路。",
                    "category": "companion",
                    "fit": "high",
                    "tags": ["asr", "tts"],
                }
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["id"] == "voice-dialogue"
    assert payload["items"][0]["source"] == "imported"
    assert payload["items"][0]["status"] == "built-in"
    assert payload["items"][0]["enabled_codex"] is True

    reloaded = client.get("/api/system/skills/imported")
    assert reloaded.status_code == 200
    assert reloaded.json()["summary"]["total"] == 1


def test_imported_skill_delete_removes_only_selected_ids(tmp_path: Path):
    client = _build_skill_test_client(tmp_path)
    client.put(
        "/api/system/skills/imported",
        json={
            "items": [
                {"id": "skill-a", "name": "Skill A", "description": "keep"},
                {"id": "skill-b", "name": "Skill B", "description": "delete"},
                {"id": "skill-c", "name": "Skill C", "description": "keep"},
            ]
        },
    )

    response = client.request("DELETE", "/api/system/skills/imported", json={"ids": ["skill-b"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["removed"] == 1
    assert {item["id"] for item in payload["items"]} == {"skill-a", "skill-c"}


def test_imported_skill_delete_requires_explicit_ids(tmp_path: Path):
    client = _build_skill_test_client(tmp_path)

    response = client.request("DELETE", "/api/system/skills/imported", json={"ids": []})

    assert response.status_code == 422


def _build_mcp_test_client() -> TestClient:
    added: list[dict[str, Any]] = []

    async def _add_mcp(name: str, base_url: str, transport: str, enabled: bool, command: str | None, args: list[str] | None, env: dict[str, str] | None) -> dict[str, Any]:
        added.append({"name": name, "base_url": base_url, "transport": transport})
        return {"ok": True, "server": {"name": name}}

    async def _install_preset(preset_id: str) -> dict[str, Any]:
        return {"ok": True, "server": {"name": preset_id}}

    async def _toggle_mcp(server_name: str, enabled: bool) -> dict[str, Any]:
        return {"ok": True, "server": {"name": server_name, "enabled": enabled}}

    async def _remove_mcp(server_name: str) -> dict[str, Any]:
        return {"ok": True, "server_name": server_name}

    async def _refresh_mcp(server_name: str) -> dict[str, Any]:
        return {"ok": True, "server": {"name": server_name}, "tools": []}

    app = FastAPI()
    app.include_router(
        _create_system_router(
            health_handler=lambda: None,
            readiness_handler=lambda: None,
            system_status_handler=lambda: None,
            add_mcp_handler=_add_mcp,
            install_mcp_preset_handler=_install_preset,
            toggle_mcp_handler=_toggle_mcp,
            remove_mcp_handler=_remove_mcp,
            refresh_mcp_handler=_refresh_mcp,
        )
    )
    return TestClient(app)


def test_mcp_registration_rejects_empty_name():
    client = _build_mcp_test_client()
    response = client.post("/api/system/mcp", json={"name": "", "base_url": "http://x", "transport": "http"})
    assert response.status_code == 422


def test_mcp_registration_rejects_invalid_transport():
    client = _build_mcp_test_client()
    response = client.post("/api/system/mcp", json={"name": "test", "base_url": "http://x", "transport": "grpc"})
    assert response.status_code == 422


def test_mcp_registration_rejects_http_without_base_url():
    client = _build_mcp_test_client()
    response = client.post("/api/system/mcp", json={"name": "test", "transport": "http"})
    assert response.status_code == 422


def test_mcp_registration_rejects_non_http_base_url():
    client = _build_mcp_test_client()
    response = client.post("/api/system/mcp", json={"name": "test", "transport": "http", "base_url": "file:///tmp/mcp"})
    assert response.status_code == 422


def test_mcp_registration_rejects_stdio_without_command():
    client = _build_mcp_test_client()
    response = client.post("/api/system/mcp", json={"name": "test", "transport": "stdio"})
    assert response.status_code == 422


def test_mcp_registration_accepts_valid_http_payload():
    client = _build_mcp_test_client()
    response = client.post("/api/system/mcp", json={"name": "fetch", "base_url": "http://127.0.0.1:7777", "transport": "http"})
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_mcp_registration_accepts_valid_streamable_http_payload():
    client = _build_mcp_test_client()
    response = client.post("/api/system/mcp", json={"name": "notion", "base_url": "https://mcp.notion.com/mcp", "transport": "streamable_http"})
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_mcp_registration_rejects_custom_stdio_by_default(monkeypatch):
    monkeypatch.delenv("YUIZAKI_ALLOW_CUSTOM_MCP_STDIO", raising=False)
    client = _build_mcp_test_client()
    response = client.post("/api/system/mcp", json={"name": "local", "transport": "stdio", "command": "python", "args": ["-m", "server"]})
    assert response.status_code == 403


def test_mcp_registration_accepts_valid_stdio_payload_when_enabled(monkeypatch):
    monkeypatch.setenv("YUIZAKI_ALLOW_CUSTOM_MCP_STDIO", "true")
    client = _build_mcp_test_client()
    response = client.post("/api/system/mcp", json={"name": "local", "transport": "stdio", "command": "python", "args": ["-m", "server"]})
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_mcp_preset_install_route_delegates_to_handler():
    client = _build_mcp_test_client()
    response = client.post("/api/system/mcp/presets/memory_graph/install")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "server": {"name": "memory_graph"}}


def test_mcp_mutation_routes_accept_encoded_slash_names():
    client = _build_mcp_test_client()

    toggled = client.post("/api/system/mcp/local%2Ftools/toggle", json={"enabled": False})
    refreshed = client.post("/api/system/mcp/local%2Ftools/refresh")
    removed = client.delete("/api/system/mcp/local%2Ftools")

    assert toggled.status_code == 200
    assert toggled.json()["server"] == {"name": "local/tools", "enabled": False}
    assert refreshed.status_code == 200
    assert refreshed.json()["server"]["name"] == "local/tools"
    assert removed.status_code == 200
    assert removed.json()["server_name"] == "local/tools"


def _build_agent_plugin_test_client() -> TestClient:
    app = FastAPI()
    app.include_router(
        _create_system_router(
            health_handler=lambda: None,
            readiness_handler=lambda: None,
            system_status_handler=lambda: None,
            toggle_agent_plugin_handler=lambda plugin_id, enabled: {"ok": True, "plugin": {"id": plugin_id, "enabled": enabled}},
            update_agent_plugin_config_handler=lambda plugin_id, config: {"ok": True, "plugin": {"id": plugin_id, "config": config}},
        )
    )
    return TestClient(app)


def test_agent_plugin_routes_accept_encoded_slash_ids():
    client = _build_agent_plugin_test_client()

    toggled = client.post("/api/system/agent-plugins/voice%2Frouter/toggle", json={"enabled": True})
    configured = client.post("/api/system/agent-plugins/voice%2Frouter/config", json={"mode": "tts"})

    assert toggled.status_code == 200
    assert toggled.json()["plugin"] == {"id": "voice/router", "enabled": True}
    assert configured.status_code == 200
    assert configured.json()["plugin"] == {"id": "voice/router", "config": {"mode": "tts"}}


def _build_schedule_test_client() -> TestClient:
    created: list[dict[str, Any]] = []

    async def _create_once(name: str, prompt: str, run_after_seconds: int) -> dict[str, Any]:
        created.append({"mode": "once", "name": name, "prompt": prompt, "seconds": run_after_seconds})
        return {"ok": True, "task": {"id": "task-once", "name": name, "prompt": prompt, "run_after_seconds": run_after_seconds}}

    async def _create_interval(name: str, prompt: str, interval_seconds: int) -> dict[str, Any]:
        created.append({"mode": "interval", "name": name, "prompt": prompt, "seconds": interval_seconds})
        return {"ok": True, "task": {"id": "task-interval", "name": name, "prompt": prompt, "interval_seconds": interval_seconds}}

    async def _remove_schedule(task_id: str) -> dict[str, Any]:
        return {"ok": True, "task_id": task_id}

    async def _toggle_schedule(task_id: str, enabled: bool) -> dict[str, Any]:
        return {"ok": True, "task": {"id": task_id, "enabled": enabled}}

    async def _run_schedule(task_id: str) -> dict[str, Any]:
        return {"ok": True, "task": {"id": task_id, "ran": True}}

    app = FastAPI()
    app.include_router(
        _create_system_router(
            health_handler=lambda: None,
            readiness_handler=lambda: None,
            system_status_handler=lambda: None,
            create_once_schedule_handler=_create_once,
            create_interval_schedule_handler=_create_interval,
            remove_schedule_handler=_remove_schedule,
            toggle_schedule_handler=_toggle_schedule,
            run_schedule_now_handler=_run_schedule,
        )
    )
    return TestClient(app)


def test_schedule_creation_rejects_empty_prompt():
    client = _build_schedule_test_client()
    response = client.post("/api/system/schedules/once", json={"name": "Empty", "prompt": "  ", "run_after_seconds": 30})
    assert response.status_code == 422


def test_once_schedule_rejects_too_short_delay():
    client = _build_schedule_test_client()
    response = client.post("/api/system/schedules/once", json={"name": "Soon", "prompt": "hello", "run_after_seconds": 0})
    assert response.status_code == 422


def test_interval_schedule_rejects_too_fast_loop():
    client = _build_schedule_test_client()
    response = client.post("/api/system/schedules/interval", json={"name": "Loop", "prompt": "hello", "interval_seconds": 5})
    assert response.status_code == 422


def test_schedule_creation_trims_payload_and_accepts_valid_values():
    client = _build_schedule_test_client()
    response = client.post("/api/system/schedules/once", json={"name": "  Review  ", "prompt": "  summarize  ", "run_after_seconds": 30})
    assert response.status_code == 200
    assert response.json()["task"]["name"] == "Review"
    assert response.json()["task"]["prompt"] == "summarize"


def test_schedule_mutation_routes_accept_encoded_slash_ids():
    client = _build_schedule_test_client()

    toggled = client.post("/api/system/schedules/daily%2Freview/toggle", json={"enabled": False})
    ran = client.post("/api/system/schedules/daily%2Freview/run")
    removed = client.delete("/api/system/schedules/daily%2Freview")

    assert toggled.status_code == 200
    assert toggled.json()["task"] == {"id": "daily/review", "enabled": False}
    assert ran.status_code == 200
    assert ran.json()["task"] == {"id": "daily/review", "ran": True}
    assert removed.status_code == 200
    assert removed.json()["task_id"] == "daily/review"
