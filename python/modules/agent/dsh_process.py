"""Own and terminate the process tree of one DSH invocation, using only stdlib.

Prefer ``process, guard = await spawn_process(command, **kwargs)``. On Windows
it creates the root suspended, attaches its Job, then resumes its first thread.
Keep the returned guard through process exit: descendants can hold stdout/stderr.
Call ``terminate_process`` on timeout/cancellation and ``close_guard`` in a
finally block, including successful exits. The caller owns cancellation
shielding and output-reader deadlines; this module does not swallow cancels.

Windows uses a non-inheritable Job Object with KILL_ON_JOB_CLOSE. Termination
keeps the Job open until its active process count reaches zero (bounded wait).
Assignment
errors raise OSError rather than pretending tree ownership was established.
The low-level attach_process interface alone has a spawn/assignment race;
spawn_process closes that gap by suspending the root before it can run.
POSIX uses a new session and kills the group even after its leader exits.
Descendants deliberately escaping the group/job are outside this contract.

References:
https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject
https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject
https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-queryinformationjobobject
https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_accounting_information
https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags
https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-resumethread
https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/nf-tlhelp32-thread32first
https://docs.python.org/3/library/asyncio-subprocess.html
https://docs.python.org/3/library/subprocess.html
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
import ctypes
import logging
import os
import signal
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

logger = logging.getLogger(__name__)
_TERMINATE_TIMEOUT_S = 1.0
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
_JOB_OBJECT_BASIC_PROCESS_ID_LIST = 3
_PROCESS_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_CREATE_SUSPENDED = 0x00000004
_THREAD_SUSPEND_RESUME = 0x0002
_TH32CS_SNAPTHREAD = 0x00000004


class ProcessLike(Protocol):
    """Minimal process surface; PID-less test doubles are supported."""

    @property
    def returncode(self) -> int | None: ...

    def kill(self) -> None: ...

    async def wait(self) -> int: ...


class _BasicAccountingInformation(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_int64),
        ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64),
        ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", ctypes.c_uint32),
        ("TotalProcesses", ctypes.c_uint32),
        ("ActiveProcesses", ctypes.c_uint32),
        ("TotalTerminatedProcesses", ctypes.c_uint32),
    ]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ThreadID", ctypes.c_uint32),
        ("th32OwnerProcessID", ctypes.c_uint32),
        ("tpBasePri", ctypes.c_int32),
        ("tpDeltaPri", ctypes.c_int32),
        ("dwFlags", ctypes.c_uint32),
    ]


@lru_cache(maxsize=1)
def _windows_api() -> Any:
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = ctypes.c_void_p
    signatures = {
        "CreateJobObjectW": ([ctypes.c_void_p, ctypes.c_wchar_p], handle),
        "SetInformationJobObject": (
            [handle, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32], ctypes.c_int,
        ),
        "OpenProcess": ([ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32], handle),
        "AssignProcessToJobObject": ([handle, handle], ctypes.c_int),
        "TerminateJobObject": ([handle, ctypes.c_uint32], ctypes.c_int),
        "QueryInformationJobObject": (
            [handle, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32,
             ctypes.POINTER(ctypes.c_uint32)], ctypes.c_int,
        ),
        "WaitForSingleObject": ([handle, ctypes.c_uint32], ctypes.c_uint32),
        "CloseHandle": ([handle], ctypes.c_int),
        "CreateToolhelp32Snapshot": ([ctypes.c_uint32, ctypes.c_uint32], handle),
        "Thread32First": ([handle, ctypes.POINTER(_ThreadEntry)], ctypes.c_int),
        "Thread32Next": ([handle, ctypes.POINTER(_ThreadEntry)], ctypes.c_int),
        "OpenThread": ([ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32], handle),
        "ResumeThread": ([handle], ctypes.c_uint32),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(api, name)
        function.argtypes = arguments
        function.restype = result
    return api


@dataclass(frozen=True)
class _ProcessGroup:
    pgid: int


@dataclass
class _WindowsJob:
    handle: int | None
    api: Any


ProcessGuard = _ProcessGroup | _WindowsJob


def spawn_options() -> dict[str, Any]:
    """Keyword arguments for asyncio.create_subprocess_exec (never a shell)."""
    if os.name == "nt":
        return {}
    return {"start_new_session": True}


def _resume_windows_root(pid: int) -> None:
    """Resume the sole initial thread of a CREATE_SUSPENDED root process."""
    api = _windows_api()
    snapshot = api.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = _ThreadEntry()
        entry.dwSize = ctypes.sizeof(entry)
        found = api.Thread32First(snapshot, ctypes.byref(entry))
        while found:
            if entry.th32OwnerProcessID == pid:
                thread = api.OpenThread(_THREAD_SUSPEND_RESUME, False, entry.th32ThreadID)
                if not thread:
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    previous_count = api.ResumeThread(thread)
                    if previous_count == 0xFFFFFFFF:
                        raise ctypes.WinError(ctypes.get_last_error())
                    if previous_count != 1:
                        raise OSError("DSH initial thread had an unexpected suspend count")
                finally:
                    api.CloseHandle(thread)
                return
            found = api.Thread32Next(snapshot, ctypes.byref(entry))
        raise ProcessLookupError(f"No initial thread for suspended DSH process {pid}")
    finally:
        api.CloseHandle(snapshot)


async def spawn_process(
    command: Sequence[str], **kwargs: Any,
) -> tuple[asyncio.subprocess.Process, ProcessGuard | None]:
    """Create and own a shell-free tree before its target code can execute.

    Windows starts suspended, assigns the Job, then resumes the initial thread.
    POSIX starts a new session. Use the bridge's existing shield around this
    entire coroutine so cancellation cannot discard the returned process/guard.
    On attach/resume failure the suspended root is killed and reaped here.
    All normal asyncio PIPE/DEVNULL/env/cwd options are passed through.
    """
    if isinstance(command, (str, bytes)) or not command:
        raise ValueError("command must be a nonempty argv sequence")
    options = dict(kwargs)
    if options.pop("shell", False):
        raise ValueError("DSH must be launched without a shell")
    if os.name == "nt":
        options["creationflags"] = options.get("creationflags", 0) | _CREATE_SUSPENDED
    else:
        options["start_new_session"] = True
    process = await asyncio.create_subprocess_exec(*command, **options)
    guard = None
    try:
        guard = attach_process(process)
        if os.name == "nt" and guard is not None:
            _resume_windows_root(process.pid)
    except BaseException:
        await terminate_process(process, guard)
        raise
    return process, guard


def attach_process(process: ProcessLike) -> ProcessGuard | None:
    """Attach immediately after spawn; return an owned, idempotently closable guard.

    On Windows, OSError means no tree guard was established. The caller must
    terminate/reap the already-spawned root on that error path. PID-less fakes
    return None and use direct kill/wait. POSIX callers must use spawn_options.
    """
    pid = getattr(process, "pid", None)
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    if os.name != "nt":
        return _ProcessGroup(pid)

    api = _windows_api()
    job_handle = api.CreateJobObjectW(None, None)
    if not job_handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not api.SetInformationJobObject(
            job_handle, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits), ctypes.sizeof(limits),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        process_handle = api.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
        if not process_handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not api.AssignProcessToJobObject(job_handle, process_handle):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            api.CloseHandle(process_handle)
    except BaseException:
        api.CloseHandle(job_handle)
        raise
    return _WindowsJob(job_handle, api)


def close_guard(guard: ProcessGuard | None) -> None:
    """Release ownership; closing a Windows job also kills remaining descendants.

    This initiates Windows termination without waiting; use terminate_process
    to confirm completion. Safe to call again on an already closed guard.
    POSIX guards own no handles;
    terminate_process must be called to kill a remaining POSIX group.
    """
    if isinstance(guard, _WindowsJob) and guard.handle is not None:
        if not guard.api.CloseHandle(guard.handle):
            raise ctypes.WinError(ctypes.get_last_error())
        guard.handle = None


async def _terminate_windows_job(guard: _WindowsJob) -> None:
    """Terminate a Job and wait for all captured member handles to signal."""
    if guard.handle is None:
        return
    opened_handles: list[Any] = []
    try:
        # Capture synchronization handles before terminating: the Job PID list
        # may be empty by the time ActiveProcesses reaches zero.
        capacity = 8
        while True:
            pid_list_type = type(
                "_ProcessIdList",
                (ctypes.Structure,),
                {"_fields_": [
                    ("NumberOfAssignedProcesses", ctypes.c_uint32),
                    ("NumberOfProcessIdsInList", ctypes.c_uint32),
                    ("ProcessIdList", ctypes.c_uint64 * capacity),
                ]},
            )
            pid_list = pid_list_type()
            returned = ctypes.c_uint32()
            if not guard.api.QueryInformationJobObject(
                guard.handle, _JOB_OBJECT_BASIC_PROCESS_ID_LIST,
                ctypes.byref(pid_list), ctypes.sizeof(pid_list),
                ctypes.byref(returned),
            ):
                error = ctypes.get_last_error()
                if error == 234:
                    capacity = max(capacity * 2, returned.value // ctypes.sizeof(ctypes.c_uint64) + 1)
                    continue
                raise ctypes.WinError(error)
            count = int(pid_list.NumberOfProcessIdsInList)
            assigned = int(pid_list.NumberOfAssignedProcesses)
            if count > capacity or assigned > capacity:
                capacity = max(capacity * 2, count, assigned)
                continue
            for index in range(count):
                handle = guard.api.OpenProcess(
                    _PROCESS_SYNCHRONIZE, False, int(pid_list.ProcessIdList[index]),
                )
                if handle:
                    opened_handles.append(handle)
            break

        if not guard.api.TerminateJobObject(guard.handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _TERMINATE_TIMEOUT_S
        accounting = _BasicAccountingInformation()
        pending = opened_handles.copy()
        while True:
            if not guard.api.QueryInformationJobObject(
                guard.handle, _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
                ctypes.byref(accounting), ctypes.sizeof(accounting), None,
            ):
                raise ctypes.WinError(ctypes.get_last_error())

            still_pending = []
            for handle in pending:
                state = guard.api.WaitForSingleObject(handle, 0)
                if state == _WAIT_TIMEOUT:
                    still_pending.append(handle)
                elif state != _WAIT_OBJECT_0:
                    raise ctypes.WinError(ctypes.get_last_error())
            pending = still_pending

            if accounting.ActiveProcesses == 0 and not pending:
                break
            remaining = deadline - loop.time()
            if remaining <= 0:
                if accounting.ActiveProcesses:
                    logger.warning(
                        "DSH job cleanup timed out after %.2fs (%d active processes)",
                        _TERMINATE_TIMEOUT_S, accounting.ActiveProcesses,
                    )
                else:
                    logger.warning(
                        "DSH process handles did not signal within %.2fs",
                        _TERMINATE_TIMEOUT_S,
                    )
                return
            await asyncio.sleep(min(0.01, remaining))
    except asyncio.CancelledError:
        raise
    except OSError:
        logger.warning("Could not terminate DSH process tree", exc_info=True)
    finally:
        for handle in opened_handles:
            try:
                guard.api.CloseHandle(handle)
            except OSError:
                logger.warning("Could not close DSH process handle", exc_info=True)
        close_guard(guard)

async def terminate_process(process: ProcessLike, guard: ProcessGuard | None) -> None:
    """Kill the owned tree and await completion with bounded waits.

    Windows waits at most one second for Job ActiveProcesses to reach zero
    before closing it; root/pipe cleanup has a separate one-second bound.
    Always acts on the group/job even when root.returncode is already set.
    Uncooperative waiters and OS errors are logged; cancellation propagates so
    the bridge can apply its existing repeated-cancellation shielding policy.
    The caller must separately bound outstanding stream-reader tasks.
    """
    try:
        if isinstance(guard, _ProcessGroup):
            os.killpg(guard.pgid, signal.SIGKILL)
        elif isinstance(guard, _WindowsJob):
            await _terminate_windows_job(guard)
    except ProcessLookupError:
        pass
    except OSError:
        logger.warning("Could not terminate DSH process tree", exc_info=True)

    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        except OSError:
            logger.warning("Could not kill DSH root process", exc_info=True)
    try:
        await asyncio.wait_for(process.wait(), timeout=_TERMINATE_TIMEOUT_S)
    except TimeoutError:
        logger.warning("DSH process cleanup timed out after %.2fs", _TERMINATE_TIMEOUT_S)
