import importlib
import asyncio
import json

pytest = importlib.import_module("pytest")

mcp_manager_module = importlib.import_module("modules.agent.mcp_manager")

MCPManager = mcp_manager_module.MCPManager
MCPServerConfig = mcp_manager_module.MCPServerConfig


class FakeManifestResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300

    def json(self) -> dict[str, object]:
        return self._payload

    def raise_for_status(self) -> None:
        if not self.is_success:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.mark.asyncio
async def test_http_mcp_status_includes_manifest_inventory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    manager = MCPManager()
    manager.servers = {
        "playwright": MCPServerConfig(name="playwright", base_url="http://127.0.0.1:7777", transport="http"),
    }

    class FakeAsyncClient:
        def __init__(self, timeout=None):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url: str):
            if url == "http://127.0.0.1:7777/health":
                return FakeManifestResponse({"ok": True})
            if url == "http://127.0.0.1:7777/manifest":
                return FakeManifestResponse({
                    "tools": [
                        {
                            "name": "browser.open_page",
                            "description": "Open a URL",
                            "inputSchema": {"type": "object"},
                        },
                        "browser.click",
                    ],
                    "resources": [{"name": "browser.page"}],
                    "prompts": [{"id": "browser.default", "desc": "Default browser prompt"}],
                })
            raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(mcp_manager_module.httpx, "AsyncClient", FakeAsyncClient)

    await manager.refresh_one("playwright")
    snapshot = manager.snapshot()
    status = snapshot["status"]["playwright"]
    capability_summary = next(item for item in snapshot["contributionSummary"] if item["category"] == "capability")

    assert status["ok"] is True
    assert status["connected"] is True
    assert status["tools_count"] == 2
    assert status["resources_count"] == 1
    assert status["prompts_count"] == 1
    assert status["tools"][0]["name"] == "browser.open_page"
    assert status["tools"][0]["description"] == "Open a URL"
    assert status["tools"][0]["input_schema"] == {"type": "object"}
    assert status["tools"][1]["name"] == "browser.click"
    assert status["resources"][0]["name"] == "browser.page"
    assert status["prompts"][0]["name"] == "browser.default"
    assert capability_summary["count"] == 2
    assert capability_summary["items"] == ["playwright:browser.click", "playwright:browser.open_page"]


@pytest.mark.asyncio
async def test_http_mcp_inventory_failure_does_not_break_health(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    manager = MCPManager()
    manager.servers = {
        "playwright": MCPServerConfig(name="playwright", base_url="http://127.0.0.1:7777", transport="http"),
    }

    class FakeAsyncClient:
        def __init__(self, timeout=None):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url: str):
            if url == "http://127.0.0.1:7777/health":
                return FakeManifestResponse({"ok": True})
            if url == "http://127.0.0.1:7777/manifest":
                return FakeManifestResponse({"error": "missing"}, status_code=404)
            raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(mcp_manager_module.httpx, "AsyncClient", FakeAsyncClient)

    await manager.refresh_one("playwright")
    status = manager.snapshot()["status"]["playwright"]

    assert status["ok"] is True
    assert status["connected"] is True
    assert status["tools_count"] == 0
    assert status["resources_count"] == 0
    assert status["prompts_count"] == 0
    assert status["tools"] == []
    assert status["inventory_error"] == "HTTP 404"


@pytest.mark.asyncio
async def test_refresh_status_timeout_marks_server_offline(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    manager = MCPManager()
    manager.servers = {
        "slow": MCPServerConfig(name="slow", base_url="http://127.0.0.1:7777", transport="http"),
    }

    async def slow_status(server):
        await asyncio.sleep(1)
        return {"enabled": True, "ok": True, "transport": server.transport, "connected": True}

    monkeypatch.setattr(manager, "_check_server_status", slow_status)

    await manager.refresh_status(timeout_seconds=0.01)
    status = manager.snapshot()["status"]["slow"]

    assert status["ok"] is False
    assert status["connected"] is False
    assert "timed out" in status["message"]
    assert status["inventory_error"] == status["message"]


@pytest.mark.asyncio
async def test_snapshot_endpoint_does_not_refresh_mcp_status(tmp_path):
    runtime_endpoints = importlib.import_module("modules.system.runtime_endpoints")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.chdir(tmp_path)
    try:
        manager = MCPManager()
        manager.servers = {
            "playwright": MCPServerConfig(name="playwright", base_url="http://127.0.0.1:7777", transport="http"),
        }

        async def fail_refresh(*_args, **_kwargs):
            raise AssertionError("MCP panel snapshot should not refresh external servers")

        manager.refresh_status = fail_refresh
        endpoint = runtime_endpoints.build_mcp_state_endpoint(manager)
        snapshot = await endpoint()

        assert "playwright" in snapshot["servers"]
        assert snapshot["status"] == {}
    finally:
        monkeypatch.undo()


def test_mcp_headers_are_resolved_for_requests_but_redacted_from_snapshot(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REMOTE_MCP_TOKEN", "secret-token")
    manager = MCPManager()
    manager.servers = {
        "remote": MCPServerConfig(
            name="remote",
            base_url="https://mcp.example.test/mcp",
            transport="streamable_http",
            headers={
                "Authorization": "Bearer {env:REMOTE_MCP_TOKEN}",
                "X-Missing": "{env:DOES_NOT_EXIST}",
            },
        ),
    }

    headers = manager._request_headers(manager.servers["remote"], {"Accept": "application/json"})
    snapshot = manager.snapshot()
    server = snapshot["servers"]["remote"]

    assert headers == {"Accept": "application/json", "Authorization": "Bearer secret-token"}
    assert server["header_keys"] == ["Authorization", "X-Missing"]
    assert "headers" not in server
    assert "secret-token" not in str(snapshot)


def test_curated_mcp_presets_are_connected_without_secret_values(monkeypatch, tmp_path):
    manager = MCPManager(tmp_path / "mcp_servers.json")
    presets = {item["id"]: item for item in manager.presets_snapshot()}

    for preset_id in [
        "chrome_devtools",
        "context7",
        "deepwiki",
        "edge_devtools",
        "firecrawl",
        "github",
        "grep_app",
        "playwright_mcp",
        "websearch",
    ]:
        assert preset_id in presets
        assert presets[preset_id]["installed"] is True
        assert manager.servers[preset_id].enabled is False

    assert presets["context7"]["header_keys"] == ["Authorization"]
    assert presets["github"]["header_keys"] == ["Authorization"]
    assert presets["firecrawl"]["env_keys"] == ["FIRECRAWL_API_KEY"]
    assert "headers" not in presets["context7"]
    assert "GITHUB_PERSONAL_ACCESS_TOKEN" not in str(manager.snapshot()["servers"]["github"])


def test_default_browser_mcp_is_disabled_until_url_is_configured(monkeypatch, tmp_path):
    monkeypatch.delenv("YUIZAKI_BROWSER_MCP_URL", raising=False)
    monkeypatch.delenv("YUIZAKI_MCP_PLAYWRIGHT_URL", raising=False)

    manager = MCPManager(tmp_path / "empty-mcp-servers.json")

    assert manager.servers["playwright"].base_url == ""
    assert manager.servers["playwright"].enabled is False

    monkeypatch.setenv("YUIZAKI_BROWSER_MCP_URL", "http://browser-mcp.local")
    configured = MCPManager(tmp_path / "configured-mcp-servers.json")

    assert configured.servers["playwright"].base_url == "http://browser-mcp.local"
    assert configured.servers["playwright"].enabled is True


def test_legacy_browser_mcp_default_store_is_migrated(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("YUIZAKI_BROWSER_MCP_URL", raising=False)
    monkeypatch.delenv("YUIZAKI_MCP_PLAYWRIGHT_URL", raising=False)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    store_file = data_dir / "mcp_servers.json"
    store_file.write_text(
        json.dumps(
            {
                "servers": {
                    "playwright": {
                        "name": "playwright",
                        "base_url": "http://127.0.0.1:7777",
                        "transport": "http",
                        "enabled": True,
                        "command": "node",
                        "args": ["server.mjs", "--stdio"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    manager = MCPManager(store_file)
    persisted = json.loads(store_file.read_text(encoding="utf-8"))

    assert manager.servers["playwright"].base_url == ""
    assert manager.servers["playwright"].enabled is False
    assert persisted["servers"]["playwright"]["base_url"] == ""
    assert persisted["servers"]["playwright"]["enabled"] is False


def test_mcp_store_merges_builtin_presets_without_overwriting_existing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    store_file = data_dir / "mcp_servers.json"
    store_file.write_text(
        json.dumps(
            {
                "servers": {
                    "playwright": {
                        "name": "playwright",
                        "base_url": "http://127.0.0.1:7777",
                        "transport": "http",
                        "enabled": False,
                    },
                    "custom_http": {
                        "name": "custom_http",
                        "base_url": "https://mcp.example.test",
                        "transport": "streamable_http",
                        "enabled": True,
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    manager = MCPManager(store_file)
    persisted = json.loads(store_file.read_text(encoding="utf-8"))

    assert manager.servers["playwright"].enabled is False
    assert manager.servers["custom_http"].enabled is True
    assert "context7" in manager.servers
    assert "github" in manager.servers
    assert persisted["builtin_preset_version"] == 1
    assert "context7" in persisted["servers"]
