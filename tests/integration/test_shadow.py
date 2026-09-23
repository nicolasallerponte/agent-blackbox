"""Shadow repository layout and tree snapshots against real git."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from agent_blackbox.core.errors import StorageError
from agent_blackbox.core.layout import STORAGE_DIRNAME, detect_workspace, open_store
from agent_blackbox.core.snapshot import (
    Limits,
    SnapshotTooLargeError,
    read_index_entry_count,
    write_tree,
)
from tests.integration.conftest import git


def _shadow_ls(store_dir: Path, tree: str) -> list[str]:
    out = subprocess.run(
        ["git", "--git-dir", str(store_dir / "shadow.git"), "ls-tree", "-r", "--name-only", tree],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(out.splitlines())


def _shadow_cat(store_dir: Path, tree: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "--git-dir", str(store_dir / "shadow.git"), "cat-file", "blob", f"{tree}:{path}"],
        capture_output=True,
        check=True,
    ).stdout


def _hash_tree(directory: Path) -> dict[str, str]:
    return {
        str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.rglob("*"))
        if p.is_file() and not p.is_symlink()
    }


# --- workspace detection -----------------------------------------------------


def test_workspace_of_repo_root(project: Path) -> None:
    ws = detect_workspace(project)
    assert ws.root == project.resolve()
    assert ws.toplevel == project.resolve()
    assert ws.prefix == ""
    assert ws.in_git_repo


def test_workspace_of_subdirectory_uses_repo_toplevel(project: Path) -> None:
    sub = project / "pkg" / "inner"
    sub.mkdir(parents=True)
    ws = detect_workspace(sub)
    assert ws.toplevel == project.resolve()
    assert ws.prefix == "pkg/inner/"


def test_workspace_outside_git(tmp_path: Path) -> None:
    ws = detect_workspace(tmp_path)
    assert ws.toplevel == tmp_path.resolve()
    assert ws.prefix == ""
    assert not ws.in_git_repo


def test_inherited_git_environment_is_ignored(project: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q")
    (other / "other.txt").write_text("not ours\n")
    other_git = _hash_tree(other / ".git")
    os.environ["GIT_DIR"] = str(other / ".git")
    os.environ["GIT_WORK_TREE"] = str(other)
    os.environ["GIT_INDEX_FILE"] = str(tmp_path / "hijacked-index")
    os.environ["GIT_LITERAL_PATHSPECS"] = "1"

    (project / "big.bin").write_bytes(b"x" * 100)

    ws = detect_workspace(project)
    store = open_store(project, create=True)
    snap = write_tree(store, "s1", Limits(max_file_size=50))

    assert ws.toplevel == project.resolve()
    assert _shadow_ls(store.dir, snap.tree) == [".gitignore", "app.py"]
    assert snap.skipped_large == ("big.bin",)
    assert _hash_tree(other / ".git") == other_git
    assert not (tmp_path / "hijacked-index").exists()


# --- storage layout ----------------------------------------------------------


def test_open_store_creates_private_layout(project: Path) -> None:
    store = open_store(project, create=True)
    base = project / STORAGE_DIRNAME
    assert store.dir == base
    assert base.stat().st_mode & 0o777 == 0o700
    assert (base / "VERSION").read_text() == "1\n"
    assert (base / "shadow.git" / "HEAD").is_file()
    assert not (base / "shadow.git" / "hooks").exists()
    attributes = (base / "shadow.git" / "info" / "attributes").read_text()
    assert "* -text -filter -ident -working-tree-encoding" in attributes


def test_open_store_is_idempotent(project: Path) -> None:
    open_store(project, create=True)
    exclude = project / ".git" / "info" / "exclude"
    before = exclude.read_text()
    open_store(project, create=True)
    assert exclude.read_text() == before
    assert before.count("/.agent-blackbox/") == 1


def test_open_store_without_create_requires_existing(project: Path) -> None:
    with pytest.raises(StorageError, match="not initialized"):
        open_store(project, create=False)


def test_open_store_rejects_symlinked_storage_dir(project: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (project / STORAGE_DIRNAME).symlink_to(elsewhere)
    with pytest.raises(StorageError, match="symlink"):
        open_store(project, create=True)
    assert list(elsewhere.iterdir()) == []


def test_open_store_rejects_unknown_storage_version(project: Path) -> None:
    open_store(project, create=True)
    (project / STORAGE_DIRNAME / "VERSION").write_text("99\n")
    with pytest.raises(StorageError, match="version"):
        open_store(project, create=True)


def test_user_exclude_is_anchored_at_subdirectory(project: Path) -> None:
    sub = project / "pkg"
    sub.mkdir()
    open_store(sub, create=True)
    exclude = (project / ".git" / "info" / "exclude").read_text()
    assert "/pkg/.agent-blackbox/" in exclude.splitlines()
    assert ".agent-blackbox" not in git(project, "status", "--porcelain", "--untracked-files=all")


def test_user_gitignore_and_tracked_files_are_untouched(project: Path) -> None:
    git_before = _hash_tree(project / ".git")
    gitignore_before = (project / ".gitignore").read_text()
    store = open_store(project, create=True)
    write_tree(store, "s1", Limits())
    git_after = _hash_tree(project / ".git")
    changed = {
        k for k in git_before.keys() | git_after.keys() if git_before.get(k) != git_after.get(k)
    }
    assert changed == {"info/exclude"}
    assert (project / ".gitignore").read_text() == gitignore_before


# --- tree snapshots ----------------------------------------------------------


def test_snapshot_captures_uncommitted_and_untracked_but_not_ignored(project: Path) -> None:
    (project / "new.txt").write_text("untracked\n")
    (project / "debug.log").write_text("ignored\n")
    (project / "node_modules").mkdir()
    (project / "node_modules" / "dep.js").write_text("ignored\n")
    store = open_store(project, create=True)

    snap = write_tree(store, "s1", Limits())

    assert _shadow_ls(store.dir, snap.tree) == [".gitignore", "app.py", "new.txt"]
    assert _shadow_cat(store.dir, snap.tree, "app.py") == b"print('hello')\n"


def test_snapshot_is_deterministic_and_deduplicated(project: Path) -> None:
    store = open_store(project, create=True)
    first = write_tree(store, "s1", Limits())
    second = write_tree(store, "s1", Limits())
    other_session = write_tree(store, "s2", Limits())
    assert first.tree == second.tree == other_session.tree


def test_snapshot_tracks_deletions_and_renames(project: Path) -> None:
    store = open_store(project, create=True)
    write_tree(store, "s1", Limits())
    (project / "app.py").rename(project / "main.py")
    snap = write_tree(store, "s1", Limits())
    assert _shadow_ls(store.dir, snap.tree) == [".gitignore", "main.py"]


def test_snapshot_keeps_bytes_verbatim_despite_attributes(project: Path) -> None:
    (project / ".gitattributes").write_text("*.txt text eol=crlf\n*.dat filter=boom\n")
    (project / "t.txt").write_bytes(b"l1\nl2\r\n")
    (project / "f.dat").write_bytes(b"\x00\x01binary")
    # The shadow repository reads global config, so a failing required filter
    # there would break snapshots unless attributes are neutralized.
    home_config = Path(os.environ["HOME"]) / ".gitconfig"
    home_config.write_text(
        home_config.read_text() + '[filter "boom"]\n\tclean = false\n\trequired = true\n'
    )
    store = open_store(project, create=True)
    snap = write_tree(store, "s1", Limits())
    assert _shadow_cat(store.dir, snap.tree, "t.txt") == b"l1\nl2\r\n"
    assert _shadow_cat(store.dir, snap.tree, "f.dat") == b"\x00\x01binary"


def test_snapshot_ignores_global_autocrlf(project: Path) -> None:
    home_config = Path(os.environ["HOME"]) / ".gitconfig"
    home_config.write_text(home_config.read_text() + "[core]\n\tautocrlf = true\n")
    (project / "w.txt").write_bytes(b"a\r\nb\r\n")
    store = open_store(project, create=True)
    snap = write_tree(store, "s1", Limits())
    assert _shadow_cat(store.dir, snap.tree, "w.txt") == b"a\r\nb\r\n"


def test_snapshot_handles_hostile_file_names(project: Path) -> None:
    names = [
        "-rf",
        "--all",
        "sp ace.txt",
        "ünïcödé.txt",
        "we*ird[1]?.txt",
        ":(exclude)x",
        "new\nline",
    ]
    for name in names:
        (project / name).write_text(name)
    store = open_store(project, create=True)
    snap = write_tree(store, "s1", Limits())
    listed = (
        subprocess.run(
            [
                "git",
                "--git-dir",
                str(store.dir / "shadow.git"),
                "ls-tree",
                "-r",
                "-z",
                "--name-only",
                snap.tree,
            ],
            capture_output=True,
            check=True,
        )
        .stdout.decode("utf-8")
        .split("\0")
    )
    for name in names:
        assert name in listed


def test_snapshot_records_symlinks_without_following(project: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside-secret"
    outside.write_text("secret")
    (project / "link").symlink_to(outside)
    store = open_store(project, create=True)
    snap = write_tree(store, "s1", Limits())
    assert _shadow_cat(store.dir, snap.tree, "link") == str(outside).encode()


def test_snapshot_of_subdirectory_is_scoped_but_honours_parent_ignores(project: Path) -> None:
    sub = project / "pkg"
    sub.mkdir()
    (sub / "mod.py").write_text("x = 1\n")
    (sub / "trace.log").write_text("ignored by the parent .gitignore\n")
    store = open_store(sub, create=True)
    snap = write_tree(store, "s1", Limits())
    assert _shadow_ls(store.dir, snap.tree) == ["pkg/mod.py"]


def test_snapshot_outside_git_uses_default_excludes(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    root.mkdir()
    (root / "main.py").write_text("x\n")
    (root / ".env").write_text("TOKEN=secret\n")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "a.js").write_text("x\n")
    (root / ".venv").mkdir()
    (root / ".venv" / "pyvenv.cfg").write_text("x\n")
    store = open_store(root, create=True)
    snap = write_tree(store, "s1", Limits())
    assert _shadow_ls(store.dir, snap.tree) == ["main.py"]


def test_snapshot_outside_git_with_gitignore_uses_it_instead_of_defaults(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    root.mkdir()
    (root / ".gitignore").write_text("build/\n")
    (root / "build").mkdir()
    (root / "build" / "out").write_text("x\n")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "a.js").write_text("x\n")
    store = open_store(root, create=True)
    snap = write_tree(store, "s1", Limits())
    assert _shadow_ls(store.dir, snap.tree) == [".gitignore", "node_modules/a.js"]


def test_snapshot_copies_user_info_exclude(project: Path) -> None:
    exclude = project / ".git" / "info" / "exclude"
    exclude.write_text(exclude.read_text() + "local-notes.md\n")
    (project / "local-notes.md").write_text("private\n")
    store = open_store(project, create=True)
    snap = write_tree(store, "s1", Limits())
    assert "local-notes.md" not in _shadow_ls(store.dir, snap.tree)


def test_large_untracked_files_are_skipped_and_reported(project: Path) -> None:
    (project / "big.bin").write_bytes(b"x" * 2048)
    (project / "small.bin").write_bytes(b"x" * 10)
    store = open_store(project, create=True)
    snap = write_tree(store, "s1", Limits(max_file_size=1024))
    assert snap.skipped_large == ("big.bin",)
    assert "big.bin" not in _shadow_ls(store.dir, snap.tree)
    assert "small.bin" in _shadow_ls(store.dir, snap.tree)


def test_file_captured_while_small_stays_captured_when_it_grows(project: Path) -> None:
    # Documented limitation: only files new to the snapshot are size-checked.
    store = open_store(project, create=True)
    (project / "grows.txt").write_bytes(b"small")
    write_tree(store, "s1", Limits(max_file_size=1024))
    (project / "grows.txt").write_bytes(b"x" * 4096)
    snap = write_tree(store, "s1", Limits(max_file_size=1024))
    assert snap.skipped_large == ()
    assert _shadow_cat(store.dir, snap.tree, "grows.txt") == b"x" * 4096


def test_too_many_files_raises(project: Path) -> None:
    for i in range(5):
        (project / f"f{i}.txt").write_text(str(i))
    store = open_store(project, create=True)
    with pytest.raises(SnapshotTooLargeError):
        write_tree(store, "s1", Limits(max_files=3))


def test_index_entry_count_reads_header(project: Path) -> None:
    store = open_store(project, create=True)
    write_tree(store, "s1", Limits())
    assert read_index_entry_count(store.index_path("s1")) == 2


def test_stale_index_lock_is_removed(project: Path) -> None:
    store = open_store(project, create=True)
    write_tree(store, "s1", Limits())
    stale = store.index_path("s1").with_name(store.index_path("s1").name + ".lock")
    stale.write_text("")
    (project / "after.txt").write_text("x\n")
    snap = write_tree(store, "s1", Limits())
    assert "after.txt" in _shadow_ls(store.dir, snap.tree)
    assert not stale.exists()


def test_corrupt_index_is_rebuilt(project: Path) -> None:
    store = open_store(project, create=True)
    write_tree(store, "s1", Limits())
    store.index_path("s1").write_bytes(b"garbage")
    snap = write_tree(store, "s1", Limits())
    assert _shadow_ls(store.dir, snap.tree) == [".gitignore", "app.py"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read files with mode 000")
def test_unreadable_files_do_not_fail_the_snapshot(project: Path) -> None:
    secret = project / "unreadable.txt"
    secret.write_text("x\n")
    secret.chmod(0)
    try:
        store = open_store(project, create=True)
        snap = write_tree(store, "s1", Limits())
        assert "app.py" in _shadow_ls(store.dir, snap.tree)
    finally:
        secret.chmod(0o600)


def test_read_index_entry_count_rejects_non_index(tmp_path: Path) -> None:
    bogus = tmp_path / "index"
    bogus.write_bytes(b"NOPE" + b"\0" * 8)
    with pytest.raises(ValueError, match="not a git index"):
        read_index_entry_count(bogus)


def test_git_failure_other_than_corruption_keeps_the_index(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_blackbox.core.errors import GitError  # noqa: PLC0415
    from agent_blackbox.core.git import ShadowGit  # noqa: PLC0415

    store = open_store(project, create=True)
    write_tree(store, "s1", Limits())
    index = store.index_path("s1")
    original_run = ShadowGit.run

    def slow_add(self: ShadowGit, *args: str, **kwargs: object) -> bytes:
        if "add" in args:
            raise GitError(args, -1, "timed out after 30.0s")
        return original_run(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ShadowGit, "run", slow_add)
    with pytest.raises(GitError, match="timed out"):
        write_tree(store, "s1", Limits())
    assert index.exists()
