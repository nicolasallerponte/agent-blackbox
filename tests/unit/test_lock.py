import multiprocessing
import os
import signal
import sys
import time
from pathlib import Path

import pytest

from agent_blackbox.core.errors import LockTimeoutError
from agent_blackbox.core.lock import ProjectLock

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX flock (ADR-0006)")


def _hold(path: str, ready: "multiprocessing.synchronize.Event", seconds: float) -> None:
    with ProjectLock(Path(path), timeout_s=5):
        ready.set()
        time.sleep(seconds)


def test_lock_is_reentrant_across_sequential_uses(tmp_path: Path) -> None:
    lock_path = tmp_path / "lock"
    for _ in range(3):
        with ProjectLock(lock_path, timeout_s=1):
            assert lock_path.exists()
    assert lock_path.stat().st_mode & 0o777 == 0o600


def test_lock_times_out_while_another_process_holds_it(tmp_path: Path) -> None:
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Event()
    holder = ctx.Process(target=_hold, args=(str(tmp_path / "lock"), ready, 5.0))
    holder.start()
    try:
        assert ready.wait(10)
        start = time.monotonic()
        with pytest.raises(LockTimeoutError), ProjectLock(tmp_path / "lock", timeout_s=0.2):
            pass
        assert time.monotonic() - start < 2
    finally:
        holder.kill()
        holder.join()


def test_lock_is_released_when_holder_is_killed(tmp_path: Path) -> None:
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Event()
    holder = ctx.Process(target=_hold, args=(str(tmp_path / "lock"), ready, 60.0))
    holder.start()
    assert ready.wait(10)
    assert holder.pid is not None
    os.kill(holder.pid, signal.SIGKILL)
    holder.join()
    with ProjectLock(tmp_path / "lock", timeout_s=2):
        pass


def test_lock_does_not_follow_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere"
    target.write_text("do not touch")
    (tmp_path / "lock").symlink_to(target)
    with (
        pytest.raises(OSError, match="symbolic link"),
        ProjectLock(tmp_path / "lock", timeout_s=0.1),
    ):
        pass
    assert target.read_text() == "do not touch"
