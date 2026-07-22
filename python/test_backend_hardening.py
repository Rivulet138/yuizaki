from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest

from modules.agent.mcp_manager import MCPManager, MCPServerConfig
from modules.agent.scheduler import AgentScheduler
from modules.agent.schedule_store import ScheduledTask
from modules.core.config import AppConfig
from modules.llm.client import LLMClient, redact_error_text
from modules.svc.converter import SVCClient
from modules.system.settings_store import SettingsStore
from modules.tools.local_tools import LocalToolError, read_file, write_file


def test_local_file_tools_restrict_paths_to_allowed_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    allowed_root = tmp_path / "allowed"
    outside_root = tmp_path / "outside"
    allowed_root.mkdir()
    outside_root.mkdir()
    outside_file = outside_root / "secret.txt"
    outside_file.write_text("secret", encoding="utf-8")
    monkeypatch.setenv("YUIZAKI_LOCAL_TOOL_ROOTS", str(allowed_root))

    allowed_file = allowed_root / "notes.txt"
    assert "Wrote 2 characters" in write_file(str(allowed_file), "ok")
    assert read_file(str(allowed_file)) == "ok"

    with pytest.raises(LocalToolError, match="outside allowed local tool roots"):
        read_file(str(outside_file))
    with pytest.raises(LocalToolError, match="outside allowed local tool roots"):
        write_file(str(outside_root / "blocked.txt"), "no")
    with pytest.raises(LocalToolError, match="outside allowed local tool roots"):
        read_file(str(Path(__file__).resolve().parent.parent / "README.md"))


def test_settings_store_redacts_secret_values_in_debug_logs(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    store = SettingsStore(str(tmp_path / "settings.json"))

    with caplog.at_level(logging.DEBUG, logger="modules.system.settings_store"):
        store.set("llm.api_key", "super-secret-token")

    assert "super-secret-token" not in caplog.text
    assert "<redacted>" in caplog.text


def test_mcp_stdio_environment_does_not_inherit_application_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "C:/runtime/bin")
    monkeypatch.setenv("OPENAI_API_KEY", "host-secret")
    monkeypatch.setenv("YUIZAKI_BACKEND_API_TOKEN", "backend-secret")
    manager = MCPManager()
    server = MCPServerConfig(
        name="isolated",
        base_url="",
        transport="stdio",
        env={"PLUGIN_TOKEN": "explicit-plugin-token"},
    )

    process_env = manager._stdio_process_env(server)

    assert process_env["PATH"] == "C:/runtime/bin"
    assert process_env["PLUGIN_TOKEN"] == "explicit-plugin-token"
    assert "OPENAI_API_KEY" not in process_env
    assert "YUIZAKI_BACKEND_API_TOKEN" not in process_env


class _FakeStdin:
    def write(self, _payload: bytes) -> None:
        return None

    async def drain(self) -> None:
        return None


class _HangingStdout:
    async def readline(self) -> bytes:
        await asyncio.sleep(60)
        return b""


class _FakeLegacyProcess:
    def __init__(self) -> None:
        self.stdin = _FakeStdin()
        self.stdout = _HangingStdout()
        self.stderr = None
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        self.returncode = 0
        return 0


@pytest.mark.asyncio
async def test_legacy_mcp_stdio_call_times_out_and_closes_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("modules.agent.mcp_manager.SSE_TOOL_TIMEOUT_SECONDS", 0.01)
    manager = MCPManager()
    server = MCPServerConfig(name="legacy", base_url="", transport="stdio", enabled=True, command="fake")
    process = _FakeLegacyProcess()
    manager.servers = {"legacy": server}
    manager._stdio_sessions["legacy"] = {
        "server_name": "legacy",
        "session_id": "stdio-test",
        "process": process,
        "lock": asyncio.Lock(),
        "protocol": "legacy",
    }

    with pytest.raises(Exception, match="stdio MCP response timed out"):
        await manager.call_tool("legacy", "never_returns", {})

    assert process.terminated is True
    assert "legacy" not in manager._stdio_sessions


def test_svc_rejects_service_returned_local_file_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeResponse:
        headers = {"content-type": "application/json"}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"status": "done", "output_path": str(tmp_path / "host-secret.wav")}

    class _FakeHttpClient:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def __enter__(self) -> "_FakeHttpClient":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def post(self, *_args: Any, **_kwargs: Any) -> _FakeResponse:
            return _FakeResponse()

    monkeypatch.setattr("modules.svc.converter.httpx.Client", _FakeHttpClient)
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    input_path.write_bytes(base64.b64decode(base64.b64encode(b"audio")))
    client = SVCClient(base_url="http://svc.example")

    result = client._convert_with_service(input_path, output_path, "gen-1", 0, 0)

    assert result == {"status": "error", "error": "SVC service returned unsupported local file path"}
    assert not output_path.exists()


def test_llm_error_text_redacts_common_secret_shapes() -> None:
    text = 'Authorization: Bearer sk-testsecret123456 api_key=plain-secret-token "token":"qk-secret123456"'

    redacted = redact_error_text(text)

    assert "sk-testsecret123456" not in redacted
    assert "plain-secret-token" not in redacted
    assert "qk-secret123456" not in redacted
    assert "<redacted>" in redacted


@pytest.mark.asyncio
async def test_llm_http_error_response_is_redacted() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Authorization: Bearer sk-testsecret123456")

    client = LLMClient("https://llm.example/v1", "sk-client-secret123", "model-test")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(RuntimeError) as exc_info:
            await client.complete_chat([{"role": "user", "content": "hello"}])
    finally:
        await client.disconnect()

    message = str(exc_info.value)
    assert "sk-testsecret123456" not in message
    assert "Bearer <redacted>" in message


@pytest.mark.asyncio
async def test_scheduler_stop_cancels_background_run_now_task() -> None:
    class _Store:
        def __init__(self) -> None:
            self.tasks: dict[str, ScheduledTask] = {}

        def upsert(self, task: ScheduledTask) -> ScheduledTask:
            self.tasks[task.id] = task
            return task

        def remove(self, task_id: str) -> None:
            self.tasks.pop(task_id, None)

        def list(self) -> list[ScheduledTask]:
            return list(self.tasks.values())

    class _SlowPipeline:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def run(self, _ctx: Any) -> Any:
            self.started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                self.cancelled.set()
                raise

    store = _Store()
    task = ScheduledTask(
        id="sched-test",
        name="test",
        source="test",
        prompt="run",
        enabled=True,
        mode="once",
        created_at=0.0,
    )
    store.upsert(task)
    pipeline = _SlowPipeline()
    scheduler = AgentScheduler(
        store=store,  # type: ignore[arg-type]
        pipeline=pipeline,  # type: ignore[arg-type]
        context_factory=lambda _task: AppConfig(),  # type: ignore[arg-type]
    )

    await scheduler.run_now("sched-test")
    await asyncio.wait_for(pipeline.started.wait(), timeout=1.0)
    await scheduler.stop()

    assert pipeline.cancelled.is_set()
    assert not scheduler._background_runs
