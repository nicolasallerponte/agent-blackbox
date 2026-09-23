"""Per-project inter-process lock (docs/adr/0003-concurrency-and-crash-safety.md).

Uses ``flock(2)``: the kernel releases the lock when the holding process dies,
so a killed hook can never leave a stale lock behind.
"""

from __future__ import annotations

import fcntl
import os
import time
from pathlib import Path
from types import TracebackType

from agent_blackbox.core.errors import LockTimeoutError

_POLL_S = 0.005


class ProjectLock:
    """Exclusive advisory lock on a file, acquired with a deadline.

    Use as a context manager::

        with ProjectLock(path, timeout_s=2.0):
            ...  # critical section
    """

    def __init__(self, path: Path, *, timeout_s: float) -> None:
        self._path = path
        self._timeout_s = timeout_s
        self._fd: int | None = None

    def __enter__(self) -> ProjectLock:
        fd = os.open(self._path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            acquired = _wait_for_lock(fd, self._timeout_s)
        except BaseException:
            os.close(fd)
            raise
        if not acquired:
            os.close(fd)
            msg = f"could not lock {self._path} within {self._timeout_s:.2f}s"
            raise LockTimeoutError(msg)
        self._fd = fd
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None


def _wait_for_lock(fd: int, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while not _try_lock(fd):
        if time.monotonic() >= deadline:
            return False
        time.sleep(_POLL_S)
    return True


def _try_lock(fd: int) -> bool:
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True
