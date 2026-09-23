"""Small filesystem helpers shared by the core."""

from __future__ import annotations

import os
from pathlib import Path


def write_atomic(path: Path, text: str) -> None:
    """Replace ``path`` with ``text`` atomically (mode 0600, never following symlinks)."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        data = memoryview(text.encode("utf-8"))
        while data:
            data = data[os.write(fd, data) :]
    finally:
        os.close(fd)
    tmp.replace(path)
