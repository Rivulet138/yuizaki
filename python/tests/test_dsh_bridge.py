from __future__ import annotations

import asyncio
import inspect
import itertools
import json
import logging
from collections.abc import Iterable

import pytest

from modules.agent import dsh_bridge
from modules.agent.companion_events import CompanionJobEventLog
from modules.agent.context import AgentRequestContext
from modules.agent.dsh_bridge import DshBridge
from modules.agent.policy_engine import PolicyEngine
from modules.agent.tool_executor import ToolExecutor
from modules.agent.tool_registry import ToolRegistry
from modules.agent_plugins.dsh_delegate_plugin import PLUGIN, DshDelegatePlugin
from modules.agent_plugins.manager import PluginManager
from modules.system.companion_runtime import build_companion_runtime_snapshot


class FakeStream:
    def __init__(self, chunks: Iterable[bytes] = ()) -> None:
        self.chunks = iter(chunks)
        self.reads = 0

    async def read(self, size: int) -> bytes:
        assert 0 < size <= 4096, "Streams must be read in bounded chunks"
        self.reads += 1
        return next(self.chunks, b"")


class FakeProcess:
    def __init__(self, stdout=(), stderr=(), *, code: int = 0, blocked: bool = False) -> None:
        self.stdout = FakeStream(stdout)
        self.stderr = FakeStream(stderr)
        self.code = code
        self.returncode = None
        self.exited = asyncio.Event()
        if not blocked:
            self.exited.set()
        self.wait_started = asyncio.Event()
        self.kill_calls = 0
        self.wait_calls = 0
        self.reaped_after_kill = False

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9
        self.exited.set()

    async def wait(self) -> int:
        self.wait_calls += 1
        self.wait_started.set()
        await self.exited.wait()
        if self.returncode is None:
            self.returncode = self.code
        if self.kill_calls:
            self.reaped_after_kill = True
        return self.returncode


@pytest.fixture(autouse=True)
def isolate_bridge(monkeypatch):
    monkeypatch.setattr(dsh_bridge, "_DSH_SEMAPHORE", asyncio.Semaphore(1))
    for key in ("YUIZAKI_DSH_COMMAND", "YUIZAKI_DSH_TIMEOUT_S", "YUIZAKI_DSH_MAX_OUTPUT_CHARS"):
        monkeypatch.delenv(key, raising=False)

    async def no_real_process(*args, **kwargs):
        raise AssertionError("Tests must never execute a real DSH process")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_real_process)


def fake_spawn(monkeypatch, *processes):
    remaining = iter(processes)
    calls = []

    async def spawn(*argv, **kwargs):
        calls.append((argv, kwargs))
        return next(remaining)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    return calls


@pytest.mark.asyncio
async def test_safe_argv_env_and_success(monkeypatch):
    process = FakeProcess(["处理完成".encode()])
    calls = fake_spawn(monkeypatch, process)
    for name in ("YUIZAKI_BACKEND_API_TOKEN", "YUIZAKI_PROVIDER_CREDENTIALS_JSON",
                 "YUIZAKI_QQ_BRIDGE_TOKEN", "YUIZAKI_FUTURE_SECRET", "UNRELATED_SECRET"):
        monkeypatch.setenv(name, "do-not-inherit")
    monkeypatch.setenv("OP_API_KEY", "dsh-provider-key")
    monkeypatch.setenv("HOME", "safe-home")
    task = '分析 E:/repo；路径含空格 & echo "quoted" $(touch nope)\n不要改文件'
    command = [r"C:\Program Files\nodejs\node.exe", r"C:\Users\编码 用户\npm\dsh\bin.js"]
    bridge = DshBridge(command=command)
    command.append("must-not-mutate-the-copy")

    result = await bridge.run(task, cwd="E:/repo with spaces")

    assert result.ok and result.output == "处理完成"
    assert result.exit_code == 0 and result.duration_ms >= 0 and result.error is None
    argv, kwargs = calls[0]
    assert argv == (*command[:-1], "--profile", "headless", task)
    assert "shell" not in kwargs
    assert kwargs["cwd"] == "E:/repo with spaces"
    assert kwargs["stdin"] == asyncio.subprocess.DEVNULL
    env = kwargs["env"]
    assert env["HOME"] == "safe-home" and env["OP_API_KEY"] == "dsh-provider-key"
    assert not any(key.upper().startswith("YUIZAKI_") for key in env)
    assert "UNRELATED_SECRET" not in env
    assert {key.upper() for key in env} <= (
        dsh_bridge.MCP_STDIO_INHERITED_ENV_KEYS | dsh_bridge._DSH_PROVIDER_ENV_KEYS
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("task", ["", " \n", "--profile evil", " \n--profile evil", "x" * 4001, "a\0b", None, 42])
async def test_invalid_task_does_not_spawn(task):
    result = await DshBridge(command=["node", "bin.js"]).run(task)
    assert result.error == "dsh_invalid_task" and not result.ok


@pytest.mark.asyncio
async def test_task_at_length_limit_is_valid(monkeypatch):
    fake_spawn(monkeypatch, FakeProcess([b"ok"]))
    assert (await DshBridge(command=["node", "bin.js"]).run("x" * 4000)).ok


@pytest.mark.asyncio
async def test_windows_default_is_node_entry_not_cmd(monkeypatch):
    monkeypatch.setattr(dsh_bridge.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\用户 Name\AppData\Roaming")
    monkeypatch.setattr(dsh_bridge.shutil, "which", lambda _: r"C:\Program Files\nodejs\node.exe")
    calls = fake_spawn(monkeypatch, FakeProcess([b"answer"]))
    assert (await DshBridge().run("分析仓库")).ok
    assert calls[0][0] == (
        r"C:\Program Files\nodejs\node.exe",
        r"C:\Users\用户 Name\AppData\Roaming\npm\node_modules\@deepseek-ai\dsh\lib\bin.js",
        "--profile", "headless", "分析仓库",
    )


@pytest.mark.asyncio
async def test_json_command_and_numeric_environment_config(monkeypatch):
    command = [r"C:\Program Files\node.exe", r"D:\DSH Agent\bin.js"]
    monkeypatch.setenv("YUIZAKI_DSH_COMMAND", json.dumps(command))
    monkeypatch.setenv("YUIZAKI_DSH_TIMEOUT_S", "1.25")
    monkeypatch.setenv("YUIZAKI_DSH_MAX_OUTPUT_CHARS", "64")
    calls = fake_spawn(monkeypatch, FakeProcess())
    bridge = DshBridge()
    assert bridge.timeout_s == 1.25 and bridge.max_output_chars == 64
    await bridge.run("检查代码")
    assert calls[0][0] == (*command, "--profile", "headless", "检查代码")
    explicit = DshBridge(command=["node", "custom.js"], timeout_s=2, max_output_chars=32)
    assert explicit.command == ["node", "custom.js"]
    assert explicit.timeout_s == 2 and explicit.max_output_chars == 32


@pytest.mark.parametrize("command", ['"dsh"', '[]', '{}', '["dsh", 1]', '[""]', '["dsh.cmd"]', 'broken'])
def test_invalid_command_config_is_rejected(monkeypatch, command):
    monkeypatch.setenv("YUIZAKI_DSH_COMMAND", command)
    with pytest.raises(ValueError, match="dsh_invalid_command"):
        DshBridge()


@pytest.mark.parametrize("key,value", [
    ("YUIZAKI_DSH_TIMEOUT_S", "0"), ("YUIZAKI_DSH_TIMEOUT_S", "nan"),
    ("YUIZAKI_DSH_TIMEOUT_S", "inf"), ("YUIZAKI_DSH_TIMEOUT_S", "invalid"),
    ("YUIZAKI_DSH_MAX_OUTPUT_CHARS", "0"), ("YUIZAKI_DSH_MAX_OUTPUT_CHARS", "-1"),
])
def test_invalid_numeric_config_is_rejected(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match="dsh_invalid_config"):
        DshBridge(command=["node", "bin.js"])


@pytest.mark.asyncio
async def test_not_found_releases_slot(monkeypatch):
    async def missing(*args, **kwargs):
        raise FileNotFoundError("token=do-not-log-this")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", missing)
    result = await DshBridge(command=["missing"]).run("分析仓库")
    assert result.error == "dsh_not_found" and not result.output
    assert dsh_bridge._DSH_SEMAPHORE._value == 1


@pytest.mark.asyncio
async def test_nonzero_redaction_and_only_last_twenty_stderr_lines(monkeypatch, caplog):
    stderr = "\n".join(f"line-{i:02}" for i in range(30)) + "\ntoken=stderr-secret\n"
    process = FakeProcess([b"api_key=stdout-secret\nresult"], [stderr.encode()], code=7)
    calls = fake_spawn(monkeypatch, process)
    with caplog.at_level(logging.WARNING, logger=dsh_bridge.__name__):
        result = await DshBridge(command=["node", "bin.js"]).run("分析仓库")
    assert result.error == "dsh_nonzero_exit" and result.exit_code == 7
    assert result.output.endswith("token=<redacted>\n")
    assert "stdout-secret" not in result.output and "stderr-secret" not in caplog.text
    assert "line-10" not in caplog.text and "line-11" in caplog.text
    assert len(caplog.records) == 1
    assert len(caplog.records[0].getMessage().splitlines()[1:]) == 20
    assert len(calls) == 1  # No retry after a possibly state-changing failure.


@pytest.mark.asyncio
async def test_timeout_kills_waits_and_releases_slot(monkeypatch):
    process = FakeProcess([b"partial output"], blocked=True)
    calls = fake_spawn(monkeypatch, process, FakeProcess([b"next run"]))
    bridge = DshBridge(command=["node", "bin.js"], timeout_s=0.02)
    result = await bridge.run("修改代码")
    assert result.error == "dsh_timeout" and result.output == "partial output"
    assert process.kill_calls == 1 and process.reaped_after_kill
    assert len(calls) == 1
    assert (await bridge.run("检查状态")).ok


@pytest.mark.asyncio
async def test_cancellation_kills_waits_and_releases_slot(monkeypatch):
    process = FakeProcess(blocked=True)
    fake_spawn(monkeypatch, process)
    pending = asyncio.create_task(DshBridge(command=["node", "bin.js"]).run("修改代码"))
    await process.wait_started.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert process.kill_calls == 1 and process.reaped_after_kill
    assert dsh_bridge._DSH_SEMAPHORE._value == 1


@pytest.mark.asyncio
async def test_cancellation_during_spawn_cleans_up_new_process(monkeypatch):
    process = FakeProcess(blocked=True)
    spawning = asyncio.Event()
    finish_spawn = asyncio.Event()

    async def spawn(*args, **kwargs):
        spawning.set()
        await finish_spawn.wait()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    pending = asyncio.create_task(DshBridge(command=["node", "bin.js"]).run("修改代码"))
    await spawning.wait()
    pending.cancel()
    finish_spawn.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert process.kill_calls == 1 and process.reaped_after_kill


@pytest.mark.asyncio
async def test_module_slot_serializes_separate_bridge_instances(monkeypatch):
    first = FakeProcess([b"first"], blocked=True)
    calls = fake_spawn(monkeypatch, first, FakeProcess([b"second"]))
    one = asyncio.create_task(DshBridge(command=["node", "bin.js"]).run("第一个任务"))
    await first.wait_started.wait()
    two = asyncio.create_task(DshBridge(command=["node", "bin.js"]).run("第二个任务"))
    await asyncio.sleep(0.01)
    assert len(calls) == 1
    first.exited.set()
    assert all(item.ok for item in await asyncio.gather(one, two))
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_queue_timeout_and_queue_cancellation_do_not_release_owner(monkeypatch):
    assert dsh_bridge._QUEUE_TIMEOUT_S == 30.0
    monkeypatch.setattr(dsh_bridge, "_QUEUE_TIMEOUT_S", 0.02)
    first = FakeProcess([b"answer"], blocked=True)
    calls = fake_spawn(monkeypatch, first)
    bridge = DshBridge(command=["node", "bin.js"])
    owner = asyncio.create_task(bridge.run("第一个任务"))
    await first.wait_started.wait()
    assert (await bridge.run("排队超时")).error == "dsh_busy"
    waiting = asyncio.create_task(bridge.run("取消排队"))
    await asyncio.sleep(0)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert len(calls) == 1 and dsh_bridge._DSH_SEMAPHORE._value == 0
    first.exited.set()
    assert (await owner).ok
    assert dsh_bridge._DSH_SEMAPHORE._value == 1


@pytest.mark.asyncio
async def test_silent_exit_zero_is_not_a_success(monkeypatch):
    """DSH reports setup failures on stderr and still exits 0.

    A delegation with no answer must never be reported as success.
    """
    process = FakeProcess([], [b"dsh: MISSING_CREDENTIAL: llm-deepseek\n"], code=0)
    fake_spawn(monkeypatch, process)
    result = await DshBridge(command=["node", "bin.js"]).run("分析仓库")
    assert result.ok is False
    assert result.error == "dsh_empty_output"
    assert "MISSING_CREDENTIAL" in result.output

    # With no diagnostic at all the caller still gets an actionable hint.
    process = FakeProcess([], [], code=0)
    fake_spawn(monkeypatch, process)
    silent = await DshBridge(command=["node", "bin.js"]).run("分析仓库")
    assert silent.error == "dsh_empty_output"
    assert "headless profile" in silent.output and "DEEPSEEK_API_KEY" in silent.output


@pytest.mark.asyncio
async def test_huge_stream_is_bounded_and_preserves_head_tail(monkeypatch):
    peak = 0
    append = dsh_bridge._BoundedOutput.append

    def measure(self, text):
        nonlocal peak
        append(self, text)
        peak = max(peak, len(self.head) + len(self.tail))

    monkeypatch.setattr(dsh_bridge._BoundedOutput, "append", measure)
    chunks = itertools.chain([b"HEAD\n"], itertools.repeat(b"x" * 4096, 4096), [b"\nTAIL"])
    process = FakeProcess(chunks)
    fake_spawn(monkeypatch, process)
    result = await DshBridge(command=["node", "bin.js"], max_output_chars=80).run("分析仓库")
    assert result.error == "dsh_output_too_large" and not result.ok
    assert len(result.output) <= 80 and peak <= 80
    assert result.output.startswith("HEAD\n") and result.output.endswith("\nTAIL")
    assert "truncated" in result.output and process.stdout.reads > 4000


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [1, 2, 19, 20])
async def test_tiny_output_limits_remain_bounded(monkeypatch, limit):
    fake_spawn(monkeypatch, FakeProcess([b"x" * 4096, b"last"]))
    result = await DshBridge(command=["node", "bin.js"], max_output_chars=limit).run("检查代码")
    assert result.error == "dsh_output_too_large" and len(result.output) <= limit


@pytest.mark.asyncio
async def test_utf8_split_between_stream_chunks(monkeypatch):
    text = "分析完成🙂"
    chunks = (bytes([byte]) for byte in text.encode())
    fake_spawn(monkeypatch, FakeProcess(chunks))
    result = await DshBridge(command=["node", "bin.js"]).run("分析仓库")
    assert result.ok and result.output == text


@pytest.mark.asyncio
async def test_plugin_discovery_abi_and_prompt_hook(tmp_path):
    registry = ToolRegistry()
    manager = PluginManager(store_file=tmp_path / "plugins.json")
    await manager.discover_and_load(registry)
    tool = registry.get("ask_dsh")
    assert PLUGIN is DshDelegatePlugin
    assert isinstance(manager.plugins["dsh-delegate"], DshDelegatePlugin)
    assert tool.source == "plugin" and tool.risk_level == "high" and tool.effect_kind == "write"
    assert tool.require_confirm and tool.scopes == ["dsh:delegate"]
    assert len(inspect.signature(tool.context_handler).parameters) == 4
    result = await tool.handler({"task": "修改代码"})
    assert result.error == "dsh_execution_context_required"
    ctx = AgentRequestContext(sid="s", session_id="chat", messages=[{"role": "user", "content": "你好"}])
    assert await manager.before_llm(ctx) is ctx
    await manager.before_llm(ctx)
    prompts = [m["content"] for m in ctx.messages if "ask_dsh" in m.get("content", "")]
    assert len(prompts) == 1 and "明确要求" in prompts[0] and "闲聊" in prompts[0]
    assert "不得自动重试" in prompts[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [False, True])
async def test_confirmation_gates_execution_and_ui_sees_one_job(monkeypatch, tmp_path, allowed):
    calls = fake_spawn(monkeypatch, FakeProcess([b"delegated result"]))
    registry = ToolRegistry()
    manager = PluginManager(store_file=tmp_path / "plugins.json")
    await manager.discover_and_load(registry)
    policy = PolicyEngine(store_file=tmp_path / "permissions.json")
    log = CompanionJobEventLog()
    ctx = AgentRequestContext(
        sid="sid", session_id="chat", workspace_id="workspace", request_id="request",
        messages=[], permission_scope="workspace", extra={"job_event_log": log},
    )
    executor = ToolExecutor(registry, policy)
    confirmed = []

    async def permission(**request):
        assert not calls  # Approval must precede any external process.
        assert request["tool_name"] == "ask_dsh" and request["risk_level"] == "high"
        confirmed.append(request)
        policy.resolve_pending(request["request_id"], allowed, False, "ask_dsh", ctx.permission_scope)

    result = await executor.execute(
        "ask_dsh", {"task": "分析仓库", "context": "E:/yuizaki"},
        ctx=ctx, plugin_manager=manager, permission_request_cb=permission,
    )
    snapshot = build_companion_runtime_snapshot(
        active_workspace_id="workspace", db_repo=None, heartbeat_scheduler=None, memory_state=None,
        summarize_relationship_events=lambda _: {}, is_relationship_milestone=lambda *_: False,
        job_event_log=log,
    )
    events = snapshot["jobs"]["events"]
    assert len(confirmed) == 1
    assert len({event["jobId"] for event in events}) == 1
    assert all(event["source"] == "plugin" and event["data"]["toolName"] == "ask_dsh" for event in events)
    assert snapshot["jobs"]["active_job_ids"] == []
    if allowed:
        assert result.success and result.content == "delegated result"
        assert len(calls) == 1 and calls[0][0][-1] == "分析仓库\n\n必要背景：\nE:/yuizaki"
        assert [event["status"] for event in events] == ["created", "running", "completed"]
        assert events[-1]["data"]["resultSummary"] == "delegated result"
    else:
        assert not result.success and not calls
        assert [event["status"] for event in events] == ["created", "cancelled"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["nonzero", "timeout", "too_large"])
async def test_state_changing_failures_are_terminal_and_not_retryable(monkeypatch, tmp_path, failure):
    process = FakeProcess(
        [b"partial changes" * (100 if failure == "too_large" else 1)],
        code=1 if failure == "nonzero" else 0, blocked=failure == "timeout",
    )
    calls = fake_spawn(monkeypatch, process)
    monkeypatch.setenv("YUIZAKI_DSH_TIMEOUT_S", "0.02")
    monkeypatch.setenv("YUIZAKI_DSH_MAX_OUTPUT_CHARS", "80")
    registry = ToolRegistry()
    registry.register(DshDelegatePlugin().register_tools()[0])
    policy = PolicyEngine(store_file=tmp_path / "permissions.json")
    log = CompanionJobEventLog()

    async def allow(**request):
        policy.resolve_pending(request["request_id"], True, False, "ask_dsh")

    result = await ToolExecutor(registry, policy, job_event_log=log).execute(
        "ask_dsh", {"task": "修改代码"}, permission_request_cb=allow,
    )
    expected = {"nonzero": "dsh_nonzero_exit", "timeout": "dsh_timeout", "too_large": "dsh_output_too_large"}
    assert not result.success and result.error == expected[failure]
    assert result.outcome == "unknown_effect" and result.retryable is False
    assert len(calls) == 1
    terminal = log.snapshot()[-1]
    assert terminal["status"] == "failed"
    assert terminal["data"]["effectOutcome"] == "unknown_effect"
    assert terminal["data"]["retryable"] is False


@pytest.mark.asyncio
async def test_combined_context_cannot_bypass_task_limit():
    plugin = DshDelegatePlugin()
    result = await plugin._handle({"task": "x" * 3990, "context": "y" * 30}, None, None, None)
    assert result.error == "dsh_invalid_task" and result.retryable is False
