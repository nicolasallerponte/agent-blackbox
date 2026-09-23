"""Unit-test configuration."""

from __future__ import annotations

import sys

if sys.platform == "win32":  # pragma: no cover - POSIX flock (ADR-0006)
    collect_ignore = ["test_lock.py"]
