from __future__ import annotations

import asyncio
import ctypes
import os
import signal
import sys
import time
from pathlib import Path

import pytest

from modules.agent import dsh_process


class FakeProcess:
    def __init__(self, *, exited: bool = False, stuck: bool = False) -> None:
        self.returncode = 0 if exited else None
        self.stuck = stuck
        self.kill_calls = 0
        self.wait_calls = 0

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9

    async def wait(self) -> int:
        self.wait_calls += 1
        if self.stuck:
            await asyncio.Event().wait()
        return self.returncode or 0


def test_spawn_options_isolate_posix_sessions() -> None:
    options = dsh_process.spawn_options()
    if os.name == "nt":
        assert options == {}
    else:
        assert options == {"start_new_session": True}


def test_fake_process_needs_no_guard() -> None:
    assert dsh_process.attach_process(FakeProcess()) is None
    dsh_process.close_guard(None)


@pytest.mark.asyncio
async def test_fake_process_killed_and_waited() -> None:
    process = FakeProcess()
    await dsh_process.terminate_process(process, None)
    assert process.kill_calls == 1
    assert process.wait_calls == 1


@pytest.mark.asyncio
async def test_exited_fake_is_waited_without_kill() -> None:
    process = FakeProcess(exited=True)
    await dsh_process.terminate_process(process, None)
    assert process.kill_calls == 0
    assert process.wait_calls == 1


@pytest.mark.asyncio
async def test_wait_is_bounded(monkeypatch, caplog) -> None:
    monkeypatch.setattr(dsh_process, "_TERMINATE_TIMEOUT_S", 0.05)
    process = FakeProcess(stuck=True)
    started = time.monotonic()
    await dsh_process.terminate_process(process, None)
    assert time.monotonic() - started < 0.5
    assert "timed out" in caplog.text


@pytest.mark.asyncio
async def test_cleanup_propagates_cancellation() -> None:
    waiting = asyncio.Event()

    class WaitingProcess(FakeProcess):
        async def wait(self) -> int:
            self.wait_calls += 1
            waiting.set()
            await asyncio.Event().wait()
            return 0

    process = WaitingProcess()
    cleanup = asyncio.create_task(dsh_process.terminate_process(process, None))
    try:
        await asyncio.wait_for(waiting.wait(), 1)
        cleanup.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cleanup
        assert process.kill_calls == 1
        assert process.wait_calls == 1
    finally:
        cleanup.cancel()
        await asyncio.gather(cleanup, return_exceptions=True)


@pytest.mark.asyncio
async def test_process_already_gone_during_kill() -> None:
    class GoneProcess(FakeProcess):
        def kill(self) -> None:
            raise ProcessLookupError

    process = GoneProcess()
    await dsh_process.terminate_process(process, None)
    assert process.wait_calls == 1


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")
@pytest.mark.asyncio
async def test_group_is_killed_even_after_root_exits(monkeypatch) -> None:
    process = FakeProcess(exited=True)
    process.pid = 123456
    calls = []
    monkeypatch.setattr(dsh_process.os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    guard = dsh_process.attach_process(process)
    await dsh_process.terminate_process(process, guard)
    assert calls == [(process.pid, signal.SIGKILL)]
    assert process.kill_calls == 0


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")
@pytest.mark.asyncio
async def test_missing_group_still_reaps_root(monkeypatch) -> None:
    process = FakeProcess()
    process.pid = 123456

    def gone(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr(dsh_process.os, "killpg", gone)
    await dsh_process.terminate_process(process, dsh_process.attach_process(process))
    assert process.kill_calls == 1
    assert process.wait_calls == 1


class ProcessIdListFixture(ctypes.Structure):
    _fields_ = [
        ("NumberOfAssignedProcesses", ctypes.c_uint32),
        ("NumberOfProcessIdsInList", ctypes.c_uint32),
        ("ProcessIdList", ctypes.c_uint64 * 1),
    ]


class PendingJobApi:
    """Model a root that exits before the rest of its Job finishes."""

    def __init__(self, counts: list[int], *, failing: str | None = None) -> None:
        self.counts = counts.copy()
        self.failing = failing
        self.events: list[str | int] = []
        self.queried = asyncio.Event()
        self.signals = [0]
        self.signal_checks = 0

    def TerminateJobObject(self, handle, exit_code):
        self.events.append("terminate")
        if self.failing == "terminate":
            raise OSError("injected terminate failure")
        return True

    def QueryInformationJobObject(self, handle, info_class, info, size, returned):
        if info_class == 3:
            pids = ctypes.cast(info, ctypes.POINTER(ProcessIdListFixture)).contents
            pids.NumberOfAssignedProcesses = 1
            pids.NumberOfProcessIdsInList = 1
            pids.ProcessIdList[0] = 222
            return True
        if self.failing == "query":
            raise OSError("injected query failure")
        assert info_class == 1
        assert size == ctypes.sizeof(dsh_process._BasicAccountingInformation)
        count = self.counts[0]
        if len(self.counts) > 1:
            self.counts.pop(0)
        accounting = ctypes.cast(info, ctypes.POINTER(dsh_process._BasicAccountingInformation))
        accounting.contents.ActiveProcesses = count
        self.events.append(count)
        self.queried.set()
        return True

    def OpenProcess(self, access, inherit, pid):
        assert access == 0x100000 and inherit is False
        assert pid == 222
        return 222

    def WaitForSingleObject(self, handle, timeout):
        assert handle == 222 and timeout == 0
        self.signal_checks += 1
        if self.failing == "wait":
            raise OSError("injected wait failure")
        result = self.signals[0]
        if len(self.signals) > 1:
            self.signals.pop(0)
        return result

    def CloseHandle(self, handle):
        self.events.append("close" if handle == 111 else "process-close")
        return True


@pytest.mark.asyncio
@pytest.mark.parametrize("root_exits", [False, True], ids=["live-root", "exited-root"])
async def test_windows_job_waits_for_all_descendants_before_closing(root_exits) -> None:
    api = PendingJobApi([2, 1, 0])
    guard = dsh_process._WindowsJob(111, api)
    process = FakeProcess(exited=root_exits)
    await dsh_process.terminate_process(process, guard)
    assert api.events == ["terminate", 2, 1, 0, "process-close", "close"]
    assert guard.handle is None
    assert process.wait_calls == 1
    assert process.kill_calls == (0 if root_exits else 1)
    dsh_process.close_guard(guard)
    assert api.events[-3:] == [0, "process-close", "close"]


@pytest.mark.asyncio
async def test_windows_job_waits_for_process_handles_to_be_signaled() -> None:
    api = PendingJobApi([0])
    api.signals = [258, 258, 0]
    guard = dsh_process._WindowsJob(111, api)
    await dsh_process.terminate_process(FakeProcess(exited=True), guard)
    assert api.signal_checks == 3
    assert api.events == ["terminate", 0, 0, 0, "process-close", "close"]


@pytest.mark.asyncio
async def test_windows_job_wait_is_bounded(monkeypatch, caplog) -> None:
    monkeypatch.setattr(dsh_process, "_TERMINATE_TIMEOUT_S", 0.05)
    api = PendingJobApi([1])
    guard = dsh_process._WindowsJob(111, api)
    process = FakeProcess()
    started = time.monotonic()
    await dsh_process.terminate_process(process, guard)
    assert time.monotonic() - started < 0.5
    assert "job cleanup timed out" in caplog.text
    assert 1 in api.events and api.events[-1] == "close"
    assert guard.handle is None
    assert process.kill_calls == process.wait_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failing", ["terminate", "query", "wait"])
async def test_windows_job_api_failure_still_closes_and_reaps_root(failing, caplog) -> None:
    api = PendingJobApi([1], failing=failing)
    guard = dsh_process._WindowsJob(111, api)
    process = FakeProcess()
    await dsh_process.terminate_process(process, guard)
    assert "Could not terminate DSH process tree" in caplog.text
    assert api.events[-1] == "close"
    assert guard.handle is None
    assert process.kill_calls == process.wait_calls == 1


@pytest.mark.asyncio
async def test_windows_job_wait_cancellation_closes_guard() -> None:
    api = PendingJobApi([1])
    guard = dsh_process._WindowsJob(111, api)
    cleanup = asyncio.create_task(dsh_process.terminate_process(FakeProcess(), guard))
    try:
        await asyncio.wait_for(api.queried.wait(), 1)
        assert not cleanup.done()
        cleanup.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cleanup
        assert api.events[-1] == "close"
        assert guard.handle is None
    finally:
        cleanup.cancel()
        await asyncio.gather(cleanup, return_exceptions=True)
        dsh_process.close_guard(guard)


_CHILD = """
import subprocess, sys, time
child = subprocess.Popen([sys.executable, '-u', '-c',
    'import sys,time; print("child-ready",file=sys.stderr,flush=True); time.sleep(30)'])
print(child.pid, flush=True)
print("child-ready", file=sys.stderr, flush=True)
time.sleep(30)
"""
_PARENT = f"""
import subprocess, sys, time
sys.stdin.readline()
child = subprocess.Popen([sys.executable, '-u', '-c', {_CHILD!r}])
print(child.pid, flush=True)
if sys.argv[1] == 'exit':
    sys.exit(0)
time.sleep(30)
"""


class ChildProbe:
    """Keep a Windows handle so PID reuse cannot falsify the liveness check."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.handle = None
        if os.name == "nt":
            from ctypes import wintypes
            self.api = ctypes.WinDLL("kernel32", use_last_error=True)
            self.api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            self.api.OpenProcess.restype = wintypes.HANDLE
            self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            self.api.WaitForSingleObject.restype = wintypes.DWORD
            self.api.CloseHandle.argtypes = [wintypes.HANDLE]
            self.api.CloseHandle.restype = wintypes.BOOL
            self.api.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
            self.api.TerminateProcess.restype = wintypes.BOOL
            self.handle = self.api.OpenProcess(0x100001, False, pid)
            assert self.handle, "The child must be alive before cleanup"

    def alive(self) -> bool:
        if self.handle is not None:
            return self.api.WaitForSingleObject(self.handle, 0) == 258
        stat = Path(f"/proc/{self.pid}/stat")
        if stat.exists() and stat.read_text().split(") ", 1)[1].startswith("Z"):
            return False
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            return False
        return True

    def force_cleanup(self) -> None:
        if self.handle is not None:
            try:
                if self.alive():
                    self.api.TerminateProcess(self.handle, 1)
                    self.api.WaitForSingleObject(self.handle, 1000)
            finally:
                self.api.CloseHandle(self.handle)
                self.handle = None
        elif self.alive():
            os.kill(self.pid, signal.SIGKILL)


@pytest.mark.asyncio
@pytest.mark.parametrize("root_exits", [False, True], ids=["live-parent", "exited-parent"])
async def test_real_python_tree_cleanup_closes_inherited_pipes(root_exits) -> None:
    process, guard = await dsh_process.spawn_process(
        [sys.executable, "-u", "-c", _PARENT, "exit" if root_exits else "sleep"],
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **dsh_process.spawn_options(),
    )
    probes = []
    try:
        assert guard is not None
        process.stdin.write(b"go\n")
        await process.stdin.drain()
        process.stdin.close()
        for _ in range(2):
            child_pid = int(await asyncio.wait_for(process.stdout.readline(), 3))
            probes.append(ChildProbe(child_pid))
        for _ in range(2):
            assert (await asyncio.wait_for(process.stderr.readline(), 3)).rstrip() == b"child-ready"
        if root_exits:
            deadline = asyncio.get_running_loop().time() + 3
            while process.returncode is None:
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.01)
        started = time.monotonic()
        await dsh_process.terminate_process(process, guard)
        assert all(not probe.alive() for probe in probes), "No descendant may survive cleanup"
        await asyncio.wait_for(asyncio.gather(process.stdout.read(), process.stderr.read()), 1)
        assert time.monotonic() - started < 1.5
        assert process.returncode is not None
        dsh_process.close_guard(guard)
        dsh_process.close_guard(guard)
    finally:
        for probe in probes:
            probe.force_cleanup()
        await dsh_process.terminate_process(process, guard)
        dsh_process.close_guard(guard)


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Objects")
@pytest.mark.asyncio
async def test_close_guard_alone_kills_owned_process() -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "import time; time.sleep(30)",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        **dsh_process.spawn_options(),
    )
    guard = None
    try:
        guard = dsh_process.attach_process(process)
        assert guard is not None
        dsh_process.close_guard(guard)
        dsh_process.close_guard(guard)
        await asyncio.wait_for(process.communicate(), 2)
        assert process.returncode is not None
    finally:
        await dsh_process.terminate_process(process, guard)


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Objects")
def test_windows_assignment_failure_closes_both_handles(monkeypatch) -> None:
    class Api:
        closed = []
        def CreateJobObjectW(self, *args):
            return 111
        def SetInformationJobObject(self, *args):
            return True
        def OpenProcess(self, *args):
            return 222
        def AssignProcessToJobObject(self, *args):
            ctypes.set_last_error(5)
            return False
        def CloseHandle(self, handle):
            self.closed.append(handle)
            return True

    api = Api()
    monkeypatch.setattr(dsh_process, "_windows_api", lambda: api)
    process = FakeProcess()
    process.pid = 123456
    with pytest.raises(OSError):
        dsh_process.attach_process(process)
    assert api.closed == [222, 111]


@pytest.mark.asyncio
@pytest.mark.parametrize("command", [[], "python -c pass"])
async def test_spawn_rejects_non_argv_command(command) -> None:
    with pytest.raises(ValueError):
        await dsh_process.spawn_process(command)


@pytest.mark.asyncio
async def test_spawn_rejects_shell() -> None:
    with pytest.raises(ValueError, match="shell"):
        await dsh_process.spawn_process([sys.executable, "-c", "pass"], shell=True)


@pytest.mark.asyncio
async def test_spawn_options_and_fake_process_compatibility(monkeypatch) -> None:
    calls = []
    process = FakeProcess()

    async def spawn(*args, **kwargs):
        calls.append((args, kwargs))
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    result, guard = await dsh_process.spawn_process(
        ["node", "bin.js", "literal & argv"], env={"SAFE": "value"}, cwd="cwd", shell=False,
    )
    assert result is process
    assert guard is None
    argv, options = calls[0]
    assert argv == ("node", "bin.js", "literal & argv")
    assert options["env"] == {"SAFE": "value"}
    assert options["cwd"] == "cwd" and "shell" not in options
    if os.name == "nt":
        assert options["creationflags"] & 4
    else:
        assert options["start_new_session"] is True


@pytest.mark.skipif(os.name != "nt", reason="Windows suspended startup")
@pytest.mark.asyncio
async def test_target_cannot_run_before_job_assignment(monkeypatch, tmp_path) -> None:
    marker = tmp_path / "executed.txt"
    original_attach = dsh_process.attach_process
    original_resume = dsh_process._resume_windows_root
    calls = []

    def attach(process):
        assert not marker.exists()
        guard = original_attach(process)
        calls.append("assigned")
        return guard

    def resume(pid):
        assert not marker.exists()
        assert calls == ["assigned"]
        original_resume(pid)
        calls.append("resumed")

    monkeypatch.setattr(dsh_process, "attach_process", attach)
    monkeypatch.setattr(dsh_process, "_resume_windows_root", resume)
    code = f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')"
    process, guard = await dsh_process.spawn_process([sys.executable, "-c", code])
    try:
        await asyncio.wait_for(process.wait(), 3)
        assert marker.read_text() == "ran"
        assert calls == ["assigned", "resumed"]
    finally:
        await dsh_process.terminate_process(process, guard)


@pytest.mark.skipif(os.name != "nt", reason="Windows suspended startup")
@pytest.mark.asyncio
@pytest.mark.parametrize("fail_step", ["attach", "resume"])
async def test_failed_suspended_launch_never_executes_target(monkeypatch, tmp_path, fail_step) -> None:
    marker = tmp_path / "executed.txt"
    captured = []
    original_attach = dsh_process.attach_process

    def attach(process):
        captured.append(process)
        if fail_step == "attach":
            raise OSError("injected attach failure")
        return original_attach(process)

    def resume(pid):
        raise OSError("injected resume failure")

    monkeypatch.setattr(dsh_process, "attach_process", attach)
    monkeypatch.setattr(dsh_process, "_resume_windows_root", resume)
    code = f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')"
    with pytest.raises(OSError, match=f"injected {fail_step} failure"):
        await dsh_process.spawn_process([sys.executable, "-c", code])
    assert len(captured) == 1 and captured[0].returncode is not None
    assert not marker.exists()
