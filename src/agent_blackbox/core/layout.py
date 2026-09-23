"""On-disk layout of ``.agent-blackbox/`` and workspace detection (design §4)."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from agent_blackbox.core.errors import GitError, StorageError
from agent_blackbox.core.fsutil import write_atomic
from agent_blackbox.core.git import ShadowGit, run_git
from agent_blackbox.core.ids import validate_session_id
from agent_blackbox.core.lock import ProjectLock

STORAGE_DIRNAME = ".agent-blackbox"
STORAGE_VERSION = "1"
_SHADOW_DIRNAME = "shadow.git"
_WORKSPACE_FILE = "workspace.json"

#: Neutralize in-tree .gitattributes so snapshots store bytes verbatim and no
#: clean filter (e.g. git-lfs) ever runs. info/attributes has top precedence.
_SHADOW_ATTRIBUTES = "* -text -filter -ident -working-tree-encoding\n"

#: Applied only when the project is not a git repository and has no .gitignore.
DEFAULT_EXCLUDES = (
    ".env",
    ".env.*",
    ".envrc",
    "node_modules/",
    ".venv/",
    "venv/",
    "__pycache__/",
    ".tox/",
    ".mypy_cache/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".DS_Store",
)


@dataclass(frozen=True)
class Workspace:
    """Where the project lives and how it relates to a user git repository.

    Attributes:
        root: The project root (resolved), where ``.agent-blackbox/`` lives.
        toplevel: The shadow work tree: the user repository's top level when
            ``root`` is inside one (so its ignore rules apply), else ``root``.
        prefix: ``root`` relative to ``toplevel``, POSIX, ``""`` or ending in ``/``.
        in_git_repo: Whether ``root`` is inside a user git repository.
    """

    root: Path
    toplevel: Path
    prefix: str
    in_git_repo: bool


def detect_workspace(root: Path) -> Workspace:
    """Describe the project at ``root``, ignoring any inherited ``GIT_*`` settings."""
    resolved = root.resolve(strict=True)
    try:
        out = run_git(
            ["rev-parse", "--show-toplevel", "--show-prefix"], cwd=resolved, timeout_s=10
        ).stdout.decode("utf-8")
    except GitError:
        return Workspace(root=resolved, toplevel=resolved, prefix="", in_git_repo=False)
    lines = out.split("\n")
    toplevel = Path(lines[0]).resolve()
    prefix = lines[1] if len(lines) > 1 else ""
    return Workspace(root=resolved, toplevel=toplevel, prefix=prefix, in_git_repo=True)


@dataclass(frozen=True)
class Store:
    """Paths inside ``.agent-blackbox/`` for one project."""

    workspace: Workspace
    dir: Path

    @property
    def shadow_dir(self) -> Path:
        """The bare shadow repository."""
        return self.dir / _SHADOW_DIRNAME

    @property
    def lock_path(self) -> Path:
        """The project lock file."""
        return self.dir / "lock"

    @property
    def sessions_dir(self) -> Path:
        """Directory holding one sub-directory per session."""
        return self.dir / "sessions"

    def session_dir(self, session_id: str) -> Path:
        """Directory for one session's journals."""
        return self.sessions_dir / validate_session_id(session_id)

    def index_path(self, session_id: str) -> Path:
        """Private index used for one session's snapshots."""
        return self.shadow_dir / f"index-{validate_session_id(session_id)}"

    def ref(self, session_id: str) -> str:
        """Ref holding the head of one session's step chain."""
        return f"refs/agent-blackbox/sessions/{validate_session_id(session_id)}"

    def git(self, session_id: str | None = None, *, timeout_s: float = 30.0) -> ShadowGit:
        """Git bound to the shadow repository (and a session index, if given)."""
        index = None if session_id is None else self.index_path(session_id)
        return ShadowGit(
            git_dir=self.shadow_dir,
            work_tree=self.workspace.toplevel,
            index_file=index,
            timeout_s=timeout_s,
        )


def open_store(root: Path, *, create: bool, lock_timeout_s: float = 5.0) -> Store:
    """Open (and optionally create) the storage of the project at ``root``.

    Creation is idempotent and runs under the project lock, so concurrent
    sessions can call it safely.

    Raises:
        StorageError: If the storage is missing (and ``create`` is false),
            is a symlink or not a directory, is owned by another user, or has
            an unsupported version.
        LockTimeoutError: If ``create`` and the lock is not acquired in time.
    """
    resolved = root.resolve(strict=True)
    base = resolved / STORAGE_DIRNAME
    if base.exists() or base.is_symlink():
        _check_private_dir(base)
        cached = _load_workspace(base, resolved)
        if create and cached is not None:
            store = Store(workspace=cached, dir=base)
            if _is_initialized(store):
                _check_version(base)
                return store
    if create:
        _mkdir_private(base)
        _check_private_dir(base)
        with ProjectLock(base / "lock", timeout_s=lock_timeout_s):
            if not (base / "VERSION").exists():
                write_atomic(base / "VERSION", STORAGE_VERSION + "\n")
            _check_version(base)
            store = _refresh_workspace(base, resolved)
            _init_shadow(store)
            _exclude_from_user_repo(store.workspace)
        return store
    _check_private_dir(base)
    _check_version(base)
    store = Store(workspace=_load_workspace(base, resolved) or detect_workspace(resolved), dir=base)
    if not (store.shadow_dir / "HEAD").is_file():
        msg = f"{base} is not initialized (missing shadow repository)"
        raise StorageError(msg)
    return store


def refresh_workspace(store: Store) -> Store:
    """Re-detect the workspace (e.g. after ``git init``) and update the cache.

    The caller must hold the project lock.
    """
    return _refresh_workspace(store.dir, store.workspace.root)


def _refresh_workspace(base: Path, root: Path) -> Store:
    ws = detect_workspace(root)
    data = {
        "v": 1,
        "root": str(ws.root),
        "toplevel": str(ws.toplevel),
        "prefix": ws.prefix,
        "in_git_repo": ws.in_git_repo,
    }
    write_atomic(base / _WORKSPACE_FILE, json.dumps(data, indent=2) + "\n")
    return Store(workspace=ws, dir=base)


def _load_workspace(base: Path, root: Path) -> Workspace | None:
    """Read the cached workspace (saves a git process per hook call)."""
    try:
        data = json.loads((base / _WORKSPACE_FILE).read_text(encoding="utf-8"))
        if data["root"] != str(root):
            return None
        return Workspace(
            root=root,
            toplevel=Path(data["toplevel"]),
            prefix=str(data["prefix"]),
            in_git_repo=bool(data["in_git_repo"]),
        )
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
        return None


def _is_initialized(store: Store) -> bool:
    """Fast path for the hook: everything :func:`open_store` creates already exists."""
    return (
        (store.dir / "VERSION").is_file()
        and (store.shadow_dir / "HEAD").is_file()
        and (store.shadow_dir / "info" / "attributes").is_file()
        and (store.shadow_dir / "info" / "exclude").is_file()
    )


def _check_version(base: Path) -> None:
    try:
        version = (base / "VERSION").read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        msg = f"{base} is not initialized (missing VERSION)"
        raise StorageError(msg) from None
    if version != STORAGE_VERSION:
        msg = f"unsupported storage version {version!r} in {base} (expected {STORAGE_VERSION})"
        raise StorageError(msg)


def refresh_excludes(store: Store) -> None:
    """Regenerate the shadow repository's ``info/exclude``.

    Contains our own storage directory, the user's ``info/exclude`` (so local
    ignores apply to snapshots too), and :data:`DEFAULT_EXCLUDES` for projects
    that are not git repositories and have no ``.gitignore``.
    """
    ws = store.workspace
    lines = [
        "# Managed by agent-blackbox; regenerated at session start. Do not edit.",
        f"/{ws.prefix}{STORAGE_DIRNAME}/",
    ]
    if not ws.in_git_repo and not (ws.root / ".gitignore").exists():
        lines.append("# Defaults for projects without git ignore rules:")
        lines.extend(DEFAULT_EXCLUDES)
    user_exclude = _user_exclude_path(ws)
    if user_exclude is not None and user_exclude.is_file():
        lines.append("# Copied from the project's git info/exclude:")
        lines.extend(user_exclude.read_text(encoding="utf-8", errors="replace").splitlines())
    write_atomic(store.shadow_dir / "info" / "exclude", "\n".join(lines) + "\n")


def _init_shadow(store: Store) -> None:
    shadow = store.shadow_dir
    if not (shadow / "HEAD").is_file():
        run_git(
            ["init", "--quiet", "--bare", "--template=", "--", str(shadow)],
            cwd=store.dir,
        )
    info = shadow / "info"
    info.mkdir(mode=0o700, exist_ok=True)
    attributes = info / "attributes"
    if not attributes.is_file() or attributes.read_text(encoding="utf-8") != _SHADOW_ATTRIBUTES:
        write_atomic(attributes, _SHADOW_ATTRIBUTES)
    if not (info / "exclude").is_file():
        refresh_excludes(store)


def _user_exclude_path(ws: Workspace) -> Path | None:
    if not ws.in_git_repo:
        return None
    try:
        out = run_git(
            ["rev-parse", "--git-path", "info/exclude"], cwd=ws.root, timeout_s=10
        ).stdout.decode("utf-8")
    except GitError:
        return None
    return (ws.root / out.rstrip("\n")).resolve()


def _exclude_from_user_repo(ws: Workspace) -> None:
    """Add ``/<prefix>.agent-blackbox/`` to the user's ``info/exclude`` once."""
    path = _user_exclude_path(ws)
    if path is None:
        return
    line = f"/{ws.prefix}{STORAGE_DIRNAME}/"
    existing = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    if line in existing.splitlines():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    separator = "" if not existing or existing.endswith("\n") else "\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"{separator}# agent-blackbox recordings (local only)\n{line}\n")


def _mkdir_private(path: Path) -> None:
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        return
    path.chmod(0o700)  # mkdir's mode is filtered by the umask


def _check_private_dir(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        msg = f"{path} is not initialized (run `agent-blackbox install`)"
        raise StorageError(msg) from None
    if stat.S_ISLNK(info.st_mode):
        msg = f"refusing to use {path}: it is a symlink"
        raise StorageError(msg)
    if not stat.S_ISDIR(info.st_mode):
        msg = f"refusing to use {path}: not a directory"
        raise StorageError(msg)
    if info.st_uid != os.getuid():
        msg = f"refusing to use {path}: owned by another user"
        raise StorageError(msg)
