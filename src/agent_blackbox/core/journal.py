"""Append-only JSON Lines journals (docs/adr/0002-session-log-format.md).

Writers must hold the project lock. Each record is written with a single
``write(2)`` on a file opened with ``O_APPEND``. A crash can leave at most one
torn line at the end, without a trailing newline; readers ignore it and
:func:`repair` removes it.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

_TAIL_CHUNK = 64 * 1024
_FILE_MODE = 0o600

# json.dumps(ensure_ascii=False) leaves these raw, so escape them explicitly:
# - C1 controls (including NEL, U+0085) and U+2028/U+2029, which some readers
#   (str.splitlines, JavaScript) treat as line breaks;
# - lone surrogates (json.loads accepts "\\ud800"), which cannot be UTF-8 encoded.
_ESCAPES = {c: f"\\u{c:04x}" for c in [*range(0x80, 0xA0), 0x2028, 0x2029, *range(0xD800, 0xE000)]}


def dumps_line(record: Mapping[str, Any]) -> str:
    """Serialize ``record`` as compact JSON that is guaranteed to be a single line."""
    text = json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return text.translate(_ESCAPES)


def append(path: Path, record: Mapping[str, Any]) -> None:
    """Append ``record`` as one line, repairing a torn tail first.

    Raises:
        TypeError: If ``record`` is not a mapping.
    """
    if not isinstance(cast("object", record), Mapping):
        msg = f"journal records must be mappings, got {type(record).__name__}"
        raise TypeError(msg)
    data = (dumps_line(record) + "\n").encode("utf-8")
    repair(path)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | _O_NOFOLLOW, _FILE_MODE)
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
    finally:
        os.close(fd)


def read_records(path: Path) -> list[dict[str, Any]]:
    """Return every complete, well-formed JSON object line, in order.

    Missing files read as empty. Torn tails, blank lines, invalid UTF-8,
    invalid JSON and non-object values are skipped.
    """
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return []
    complete, _, _ = data.rpartition(b"\n")
    return [r for r in (_parse(raw) for raw in complete.split(b"\n")) if r is not None]


def last_record(path: Path) -> dict[str, Any] | None:
    """Return the last complete, well-formed record, reading only the file's tail."""
    try:
        fd = os.open(path, os.O_RDONLY | _O_NOFOLLOW)
    except FileNotFoundError:
        return None
    try:
        end = os.fstat(fd).st_size
        buffer = b""
        pos = end
        while pos > 0:
            start = max(0, pos - _TAIL_CHUNK)
            buffer = os.pread(fd, pos - start, start) + buffer
            pos = start
            complete, sep, _ = buffer.rpartition(b"\n")
            if not sep:
                continue
            lines = complete.split(b"\n")
            # The first line may be cut by the chunk boundary unless we reached offset 0.
            candidates = lines if pos == 0 else lines[1:]
            for raw in reversed(candidates):
                record = _parse(raw)
                if record is not None:
                    return record
        return None
    finally:
        os.close(fd)


def repair(path: Path) -> bool:
    """Truncate a torn last line (bytes after the final newline).

    Returns:
        True if the file was modified.
    """
    try:
        fd = os.open(path, os.O_RDWR | _O_NOFOLLOW)
    except FileNotFoundError:
        return False
    try:
        size = os.fstat(fd).st_size
        if size == 0:
            return False
        pos = size
        while pos > 0:
            start = max(0, pos - _TAIL_CHUNK)
            chunk = os.pread(fd, pos - start, start)
            index = chunk.rfind(b"\n")
            if index != -1:
                keep = start + index + 1
                break
            pos = start
        else:
            keep = 0
        if keep == size:
            return False
        os.ftruncate(fd, keep)
        return True
    finally:
        os.close(fd)


def _parse(raw: bytes) -> dict[str, Any] | None:
    if not raw.strip():
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
