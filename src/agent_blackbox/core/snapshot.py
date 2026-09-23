"""Workspace snapshots in the shadow repository (design §4.1).

Callers must hold the project lock (:class:`agent_blackbox.core.lock.ProjectLock`)
around every function that writes: they assume no other process uses the same
session index or ref concurrently.
"""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from agent_blackbox.core.errors import AgentBlackboxError, GitError
from agent_blackbox.core.git import SHADOW_IDENTITY, ShadowGit

if TYPE_CHECKING:
    from agent_blackbox.core.layout import Store

_INDEX_SIGNATURE = b"DIRC"
_COMMIT_SEPARATOR = "\x1e"


@dataclass(frozen=True)
class Limits:
    """Resource limits for recording (configurable per project)."""

    max_file_size: int = 10 * 1024 * 1024
    max_files: int = 100_000
    git_timeout_s: float = 30.0


class SnapshotTooLargeError(AgentBlackboxError):
    """The workspace has more files than :attr:`Limits.max_files`."""


@dataclass(frozen=True)
class TreeSnapshot:
    """Result of snapshotting the work tree.

    Attributes:
        tree: The git tree id.
        skipped_large: Paths (relative to the project root) left out because
            they exceed :attr:`Limits.max_file_size`.
        entries: Number of files in the snapshot.
        unreadable: Paths git could not read (e.g. permission denied); the rest
            of the snapshot is still taken.
    """

    tree: str
    skipped_large: tuple[str, ...]
    entries: int
    unreadable: tuple[str, ...] = ()


def write_tree(store: Store, session_id: str, limits: Limits) -> TreeSnapshot:
    """Snapshot the project into the session's index and return its tree.

    Stale index locks left by a killed process are removed first, and a
    corrupt index is rebuilt once from scratch.

    Raises:
        SnapshotTooLargeError: If the snapshot exceeds ``limits.max_files``.
        GitError: If git fails even with a fresh index.
    """
    git = store.git(session_id, timeout_s=limits.git_timeout_s)
    index = store.index_path(session_id)
    index.with_name(index.name + ".lock").unlink(missing_ok=True)
    try:
        return _write_tree(git, store.workspace.root, index, limits)
    except GitError as exc:
        # Only a corrupt index is worth discarding: rebuilding it rehashes every
        # file, which would make a slow repository (timeout) even slower.
        if not index.exists() or "index file" not in exc.stderr:
            raise
        index.unlink()
        return _write_tree(git, store.workspace.root, index, limits)


def read_index_entry_count(index: Path) -> int:
    """Return the number of entries recorded in a git index file header.

    Raises:
        ValueError: If the file is not a git index.
    """
    with index.open("rb") as fh:
        header = fh.read(12)
    if len(header) != 12 or header[:4] != _INDEX_SIGNATURE:  # noqa: PLR2004 - header size
        msg = f"{index} is not a git index"
        raise ValueError(msg)
    return int.from_bytes(header[8:12], "big")


def commit_tree(store: Store, tree: str, parent: str | None, message: str, when_ns: int) -> str:
    """Create a commit for ``tree`` with a deterministic identity and date."""
    date = f"@{when_ns // 1_000_000_000} +0000"
    name, email = SHADOW_IDENTITY
    env = {
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_AUTHOR_DATE": date,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
        "GIT_COMMITTER_DATE": date,
    }
    args = ["commit-tree", tree]
    if parent is not None:
        args += ["-p", parent]
    out = store.git().run(*args, stdin=message.encode("utf-8"), env=env)
    return out.decode("ascii").strip()


def resolve_ref(store: Store, ref: str) -> str | None:
    """Return the commit a ref points to, or ``None`` if it does not exist.

    Reads the loose ref or ``packed-refs`` directly (saves a git process per
    hook call) and falls back to ``git rev-parse`` for anything unexpected.
    """
    try:
        value: str | None = (store.shadow_dir / ref).read_text(encoding="ascii").strip()
    except FileNotFoundError:
        value = _packed_ref(store, ref)
    except (OSError, UnicodeDecodeError):
        value = "?"
    if value is None or _is_object_id(value):
        return value
    out = store.git().run("rev-parse", "--quiet", "--verify", f"{ref}^{{commit}}", ok_codes=(0, 1))
    return out.decode("ascii").strip() or None


def _packed_ref(store: Store, ref: str) -> str | None:
    try:
        lines = (store.shadow_dir / "packed-refs").read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    suffix = f" {ref}"
    for line in lines:
        if line.endswith(suffix) and not line.startswith(("#", "^")):
            return line[: -len(suffix)]
    return None


def _is_object_id(value: str) -> bool:
    return len(value) in (40, 64) and all(c in "0123456789abcdef" for c in value)


def update_ref(store: Store, ref: str, new: str, expected_old: str | None) -> bool:
    """Point ``ref`` at ``new`` only if it currently points at ``expected_old``.

    ``expected_old=None`` requires the ref not to exist.

    Returns:
        False if the ref had moved (compare-and-swap failed), True on success.

    Raises:
        GitError: If the update fails for another reason.
    """
    try:
        store.git().run("update-ref", "-m", "agent-blackbox step", ref, new, expected_old or "")
    except GitError:
        if resolve_ref(store, ref) != expected_old:
            return False
        raise
    return True


@dataclass(frozen=True)
class CommitInfo:
    """A shadow commit as stored by git (the source of truth during recovery)."""

    sha: str
    tree: str
    parent: str | None
    message: str


def commits_between(store: Store, old: str | None, new: str) -> list[CommitInfo]:
    """Return commits reachable from ``new`` but not ``old``, oldest first."""
    spec = new if old is None else f"{old}..{new}"
    fmt = f"--format=%H %T %P%n%B{_COMMIT_SEPARATOR}"
    out = store.git().run("log", "--reverse", fmt, spec, "--")
    result = []
    for chunk in out.decode("utf-8", "replace").split(_COMMIT_SEPARATOR):
        text = chunk.strip("\n")
        if not text:
            continue
        header, _, message = text.partition("\n")
        sha, tree, *parents = header.split()
        parent = parents[0] if parents else None
        result.append(CommitInfo(sha=sha, tree=tree, parent=parent, message=message.strip()))
    return result


def _write_tree(git: ShadowGit, root: Path, index: Path, limits: Limits) -> TreeSnapshot:
    oversized = _oversized_candidates(git, root, limits.max_file_size)
    excludes = [f":(exclude,literal){path}" for path in oversized]
    # --ignore-errors adds every readable file but exits 1 if any file could
    # not be read. That is expected (e.g. a mode-000 file); anything else fails.
    proc = git.run_process(
        "add", "--all", "--ignore-errors", "--", ".", *excludes, cwd=root, ok_codes=(0, 1)
    )
    unreadable = _unreadable_paths(proc.stderr) if proc.returncode else ()
    entries = read_index_entry_count(index) if index.exists() else 0
    if entries > limits.max_files:
        msg = f"{entries} files exceed the limit of {limits.max_files}"
        raise SnapshotTooLargeError(msg)
    tree = git.run("write-tree").decode("ascii").strip()
    return TreeSnapshot(
        tree=tree, skipped_large=tuple(oversized), entries=entries, unreadable=unreadable
    )


_UNINDEXABLE = re.compile(r"error: unable to index file '(.*)'")


def _unreadable_paths(stderr: bytes) -> tuple[str, ...]:
    """Parse ``git add --ignore-errors`` stderr; raise unless only unreadable files failed."""
    text = stderr.decode("utf-8", "replace")
    paths = []
    for line in text.splitlines():
        match = _UNINDEXABLE.fullmatch(line)
        if match:
            paths.append(match.group(1))
        elif line and not line.startswith(("error: open(", "warning: ")):
            raise GitError(("add",), 1, text)
    if not paths:
        raise GitError(("add",), 1, text)
    return tuple(paths)


def _oversized_candidates(git: ShadowGit, root: Path, max_size: int) -> list[str]:
    """Files new to the snapshot (relative to ``root``) larger than ``max_size``.

    Only untracked files are checked: ``--modified`` would double the scan cost
    of every snapshot. A file captured while small stays captured if it grows.
    """
    out = git.run("ls-files", "-z", "--others", "--exclude-standard", "--", ".", cwd=root)
    oversized = []
    for raw in sorted(set(out.split(b"\0"))):
        if not raw:
            continue
        path = os.fsdecode(raw)
        try:
            info = (root / path).lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISREG(info.st_mode) and info.st_size > max_size:
            oversized.append(path)
    return oversized
