"""Bounded, shell-free access to the locally installed DSH coding agent."""

from __future__ import annotations

import asyncio
import codecs
import json
import logging
import math
import ntpath
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass

from ..llm.client import redact_error_text
from .dsh_process import close_guard, spawn_process, terminate_process
from .mcp_manager import MCP_STDIO_INHERITED_ENV_KEYS

logger = logging.getLogger(__name__)
_DSH_SEMAPHORE = asyncio.Semaphore(1)
_QUEUE_TIMEOUT_S = 30.0
_READ_SIZE = 4096
_DRAIN_TIMEOUT_S = 1.0
_TRUNCATION = "\n...[truncated]...\n"
# These are DSH's provider credentials, not Yuizaki's backend/vault credentials.
_DSH_PROVIDER_ENV_KEYS = frozenset({
    "DEEPSEEK_API_KEY", "OP_API_KEY", "ROAI_API_KEY", "OPENLUX_API_KEY",
})


@dataclass(frozen=True)
class DshResult:
    ok: bool
    output: str
    exit_code: int | None
    duration_ms: int
    error: str | None = None


def _process_env() -> dict[str, str]:
    allowed = MCP_STDIO_INHERITED_ENV_KEYS | _DSH_PROVIDER_ENV_KEYS
    return {
        key: value for key, value in os.environ.items()
        if key.upper() in allowed and not key.upper().startswith("YUIZAKI_")
    }


def _default_command() -> list[str]:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA") or ntpath.join(
            os.environ.get("USERPROFILE") or os.path.expanduser("~"), "AppData", "Roaming",
        )
        return [
            shutil.which("node") or "node",
            ntpath.join(appdata, "npm", "node_modules", "@deepseek-ai", "dsh", "lib", "bin.js"),
        ]
    return [shutil.which("dsh") or "dsh"]


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    marker = _TRUNCATION if limit > len(_TRUNCATION) + 1 else "…"
    remaining = limit - len(marker)
    head = (remaining + 1) // 2
    tail = remaining // 2
    return text[:head] + marker + (text[-tail:] if tail else "")


class _StreamRedactor:
    """Remove credentials before output retention, including split stream tokens."""

    _PREFIX = re.compile(
        r"(?i)(?:\bBearer\s+|(?P<assignment>[\"']?(?:api[_-]?key|token|secret|password|authorization)"
        r"[\"']?\s*[:=]\s*[\"']?)|\b(?:sk-proj|sk|sess|qk)-)"
    )
    _DELIMITER = re.compile(r"[\s,;}\]\"']")

    def __init__(self, emit) -> None:
        self.emit = emit
        self.pending = ""
        self.suppress = False
        self.value_started = False
        self.scheme_pending = False
        self.secrets = tuple(sorted({
            value for key, value in os.environ.items()
            if key.upper() in _DSH_PROVIDER_ENV_KEYS and value
        }, key=len, reverse=True))
        self.window = max([256, *(len(secret) for secret in self.secrets)])

    def _emit(self, text: str) -> None:
        for secret in self.secrets:
            text = text.replace(secret, "<redacted>")
        self.emit(redact_error_text(text))

    def append(self, text: str, *, final: bool = False) -> None:
        self.pending += text
        while self.pending:
            if self.suppress:
                if not self.value_started:
                    self.pending = self.pending.lstrip(" \t\r\n\"'")
                    if not self.pending:
                        break
                    self.value_started = True
                if self.scheme_pending:
                    # The optional scheme can arrive after the field or quote.
                    if not final and "bearer".startswith(self.pending.lower()):
                        break
                    scheme = re.match(r"(?i)Bearer\s+", self.pending)
                    self.scheme_pending = False
                    if scheme:
                        self.pending = self.pending[scheme.end():]
                        self.value_started = False
                        continue
                delimiter = self._DELIMITER.search(self.pending)
                if delimiter is None:
                    self.pending = ""
                    break
                self.pending = self.pending[delimiter.start():]
                self.suppress = False
            match = self._PREFIX.search(self.pending)
            if match:
                self._emit(self.pending[:match.end()])
                self.emit("<redacted>")
                self.pending = self.pending[match.end():]
                self.suppress = True
                self.value_started = False
                self.scheme_pending = match.group("assignment") is not None
                continue
            cut = len(self.pending) if final else max(0, len(self.pending) - self.window)
            # A complete literal credential may straddle the retention cut.
            # Keep that occurrence intact so replacement precedes truncation.
            for secret in self.secrets:
                offset = self.pending.find(secret)
                while 0 <= offset < cut:
                    if offset + len(secret) > cut:
                        cut = offset
                        break
                    offset = self.pending.find(secret, offset + 1)
            self._emit(self.pending[:cut])
            self.pending = self.pending[cut:]
            break


class _BoundedOutput:
    """Bound retained output; raw size accounting remains independent of redaction."""

    def __init__(self, limit: int, *, tail_only: bool = False) -> None:
        self.limit = limit
        self.head_limit = 0 if tail_only else (limit + 1) // 2
        self.head = ""
        self.tail = ""
        self.total = 0
        self.retained_total = 0
        self.tail_only = tail_only
        self.redactor = _StreamRedactor(self._retain)

    def _retain(self, text: str) -> None:
        self.retained_total += len(text)
        take = min(len(text), self.head_limit - len(self.head))
        self.head += text[:take]
        tail_limit = self.limit - self.head_limit
        self.tail = (self.tail + text[take:])[-tail_limit:] if tail_limit else ""
        if self.tail_only:
            self.tail = "".join(self.tail.splitlines(keepends=True)[-20:])

    def append(self, text: str) -> None:
        self.total += len(text)
        self.redactor.append(text)

    def text(self) -> str:
        self.redactor.append("", final=True)
        if self.tail_only or self.retained_total <= self.limit:
            return self.head + self.tail
        return _truncate(self.head + _TRUNCATION + self.tail, self.limit)


async def _read_stream(stream: asyncio.StreamReader, output: _BoundedOutput) -> None:
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    while chunk := await stream.read(_READ_SIZE):
        output.append(decoder.decode(chunk))
    output.append(decoder.decode(b"", final=True))


async def _finish_cleanup(awaitable, *, propagate_cancel: bool = False):
    """Do not release the shared slot until cleanup survives repeated cancels."""
    pending = asyncio.ensure_future(awaitable)
    cancelled = False
    while not pending.done():
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError:
            cancelled = True
    result = pending.result()
    if cancelled and propagate_cancel:
        raise asyncio.CancelledError
    return result


class DshBridge:
    def __init__(
        self, *, command: list[str] | None = None, timeout_s: float | None = None,
        max_output_chars: int | None = None,
    ) -> None:
        if command is None:
            configured = os.environ.get("YUIZAKI_DSH_COMMAND")
            try:
                command = json.loads(configured) if configured is not None else _default_command()
            except (TypeError, ValueError) as exc:
                raise ValueError("dsh_invalid_command") from exc
        if (
            not isinstance(command, list) or not command
            or any(not isinstance(arg, str) or not arg.strip() or "\0" in arg for arg in command)
            or ntpath.splitext(command[0])[1].lower() in {".cmd", ".bat"}
        ):
            raise ValueError("dsh_invalid_command")
        self.command = list(command)
        try:
            self.timeout_s = float(
                timeout_s if timeout_s is not None else os.environ.get("YUIZAKI_DSH_TIMEOUT_S", "180"),
            )
            self.max_output_chars = int(
                max_output_chars if max_output_chars is not None
                else os.environ.get("YUIZAKI_DSH_MAX_OUTPUT_CHARS", "8000"),
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("dsh_invalid_config") from exc
        if not math.isfinite(self.timeout_s) or self.timeout_s <= 0 or self.max_output_chars <= 0:
            raise ValueError("dsh_invalid_config")

    async def run(self, task: str, *, cwd: str | None = None) -> DshResult:
        started = time.perf_counter()

        def result(error: str | None, output: str = "", code: int | None = None) -> DshResult:
            return DshResult(
                ok=error is None, output=_truncate(redact_error_text(output), self.max_output_chars),
                exit_code=code, duration_ms=round((time.perf_counter() - started) * 1000), error=error,
            )

        if (
            not isinstance(task, str) or not task.strip() or len(task) > 4000
            or task.lstrip().startswith("-") or "\0" in task
        ):
            return result("dsh_invalid_task")
        try:
            await asyncio.wait_for(_DSH_SEMAPHORE.acquire(), timeout=_QUEUE_TIMEOUT_S)
        except TimeoutError:
            return result("dsh_busy")

        guard = None
        try:
            spawn = asyncio.create_task(spawn_process(
                [*self.command, "--profile", "headless", task], cwd=cwd, env=_process_env(),
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ))
            try:
                process, guard = await asyncio.shield(spawn)
            except asyncio.CancelledError:
                # Cancellation may race CreateProcess: recover its handle first.
                try:
                    process, guard = await _finish_cleanup(spawn)
                except OSError:
                    raise asyncio.CancelledError from None
                await _finish_cleanup(terminate_process(process, guard))
                raise
            except FileNotFoundError:
                return result("dsh_not_found")
            except OSError:
                return result("dsh_spawn_error")

            stdout = _BoundedOutput(self.max_output_chars)
            stderr = _BoundedOutput(self.max_output_chars, tail_only=True)
            assert process.stdout is not None and process.stderr is not None
            readers = [
                asyncio.create_task(_read_stream(process.stdout, stdout)),
                asyncio.create_task(_read_stream(process.stderr, stderr)),
            ]
            waiter = asyncio.create_task(process.wait())
            completion = asyncio.gather(waiter, *readers)

            async def cleanup() -> None:
                # Keep both readers alive while killing/reaping to avoid pipe
                # backpressure deadlocking Process.wait().
                await terminate_process(process, guard)
                # A descendant may retain pipes after the root exits. Bound
                # draining as well as root wait before releasing the shared slot.
                # A failed gather leaves its other children running.
                settled = asyncio.gather(waiter, *readers, return_exceptions=True)
                done, _ = await asyncio.wait({settled}, timeout=_DRAIN_TIMEOUT_S)
                if not done:
                    settled.cancel()
                    await asyncio.gather(settled, return_exceptions=True)
                await asyncio.gather(completion, return_exceptions=True)

            error = None
            try:
                await asyncio.wait_for(asyncio.shield(completion), timeout=self.timeout_s)
            except TimeoutError:
                error = "dsh_timeout"
                await _finish_cleanup(cleanup(), propagate_cancel=True)
            except asyncio.CancelledError:
                await _finish_cleanup(cleanup())
                raise
            except (OSError, ValueError):
                error = "dsh_io_error"
                await _finish_cleanup(cleanup(), propagate_cancel=True)
            finally:
                diagnostic = stderr.text()
                if diagnostic:
                    logger.warning("DSH stderr (last 20 lines):\n%s", diagnostic)

            if error is None:
                await _finish_cleanup(terminate_process(process, guard), propagate_cancel=True)
                if process.returncode != 0:
                    error = "dsh_nonzero_exit"
                elif stdout.total + stderr.total > self.max_output_chars:
                    error = "dsh_output_too_large"
                elif stdout.total == 0:
                    # DSH can exit 0 while only reporting a credential/setup
                    # problem on stderr (for example MISSING_CREDENTIAL). An
                    # empty answer is not a successful delegation.
                    error = "dsh_empty_output"
            output = stdout.text()
            if error and diagnostic:
                output += "\n[stderr]\n" + diagnostic
            elif error == "dsh_empty_output":
                output = (
                    "DSH produced no output. Check that its headless profile is initialised and that it "
                    "holds model credentials (for example DEEPSEEK_API_KEY); run "
                    "`dsh --profile headless \"...\"` once by hand to confirm."
                )
            return result(error, output, process.returncode)
        finally:
            try:
                close_guard(guard)
            finally:
                _DSH_SEMAPHORE.release()
