"""Out-of-process driver for recorder tests (concurrency and crash injection).

Usage: python -m tests.integration._driver <root> <session> <label> <count>

Writes ``<label>-<i>.txt`` and records one tool step per file, ``count`` times.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from agent_blackbox.core.events import StepEvent
from agent_blackbox.core.recorder import Recorder, RecorderConfig


def main(argv: list[str]) -> int:
    """Entry point."""
    root, session, label, count = Path(argv[1]), argv[2], argv[3], int(argv[4])
    recorder = Recorder(root, RecorderConfig(lock_timeout_s=60))
    for i in range(count):
        path = root / f"{label}-{i}.txt"
        start = time.time_ns()
        path.write_text(f"{label} {i}\n", encoding="utf-8")
        recorder.record_step(
            StepEvent(
                session_id=session,
                tool="Write",
                tool_input={"file_path": str(path), "content": f"{label} {i}\n"},
                ok=True,
                started_ns=start,
                ended_ns=time.time_ns(),
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
