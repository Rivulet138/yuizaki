"""Cross-process advisory file lock shared by the JSON-backed stores.

Every store that performs a read-modify-write cycle on a file next to the
database (workspace context, settings history, the MCP config pointer) needs
the same primitive: an exclusive lock that works on Windows and POSIX without
writing to the lock file itself.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def exclusive_file_lock(lock_path: Path) -> Iterator[None]:
    """Serialize read-modify-write across processes on Windows and POSIX."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")  # noqa: SIM115 - closed in the finally block
    try:
        if os.name == "nt":
            import msvcrt

            # Locking a byte range beyond EOF is supported, so the lock file
            # never needs to be written. Writing here would race with another
            # process that already holds the same byte locked.
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


__all__ = ["exclusive_file_lock"]
