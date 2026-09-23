"""Claude Code command hook that saves each stdin payload to a directory.

Register it for every event you want to capture (see ../SKILL.md). It always
exits 0 and prints nothing, so it never disturbs the session.

Usage (exec form): python3 dump_payload.py <output-dir>
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def main(argv: list[str]) -> int:
    """Write ``{"observed_ns": ..., "payload": ...}`` to a new file in ``argv[1]``."""
    try:
        out_dir = Path(argv[1])
        raw = sys.stdin.read()
        payload = json.loads(raw)
        now = time.time_ns()
        event = payload.get("hook_event_name", "Unknown")
        tool = payload.get("tool_name", "")
        name = f"{now}-{os.getpid()}-{event}" + (f"-{tool}" if tool else "") + ".json"
        record = {"observed_ns": now, "payload": payload}
        (out_dir / name).write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - a capture hook must never break the session
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
