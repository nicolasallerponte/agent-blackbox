"""Recorder: sessions, steps, turns, limits, crash recovery and concurrency."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from agent_blackbox.core import journal
from agent_blackbox.core.events import SessionEvent, StepEvent, TurnEvent
from agent_blackbox.core.ids import InvalidSessionIdError
from agent_blackbox.core.layout import open_store
from agent_blackbox.core.lock import ProjectLock
from agent_blackbox.core.recorder import CRASH_ENV, MAX_PROMPT_CHARS, Recorder, RecorderConfig
from agent_blackbox.core.records import AgentRef, StepKind, StepRecord
from agent_blackbox.core.snapshot import Limits, resolve_ref

REPO_ROOT = Path(__file__).parents[2]
SESSION = "sess-1"


def _steps(root: Path, session: str = SESSION) -> list[StepRecord]:
    path = root / ".agent-blackbox" / "sessions" / session / "steps.jsonl"
    return [StepRecord.from_dict(r) for r in journal.read_records(path)]


def _step_event(tool: str = "Edit", session: str = SESSION, **kw: object) -> StepEvent:
    now = time.time_ns()
    fields: dict[str, object] = {
        "session_id": session,
        "tool": tool,
        "tool_input": {"file_path": "app.py"},
        "ok": True,
        "started_ns": now - 1_000_000,
        "ended_ns": now,
    }
    fields.update(kw)
    return StepEvent(**fields)  # type: ignore[arg-type]


def _start(recorder: Recorder, session: str = SESSION, kind: str = "start") -> StepRecord | None:
    return recorder.start_session(
        SessionEvent(session_id=session, kind=kind, at_ns=time.time_ns(), adapter="test")  # type: ignore[arg-type]
    )


def _drive(
    root: Path, label: str, count: int, *, session: str = SESSION, crash_at: str | None = None
) -> int:
    env = dict(os.environ)
    if crash_at:
        env[CRASH_ENV] = crash_at
    proc = subprocess.run(
        [sys.executable, "-m", "tests.integration._driver", str(root), session, label, str(count)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 137):
        raise AssertionError(proc.stderr)
    return proc.returncode


def _assert_chain_consistent(root: Path, session: str = SESSION) -> None:
    records = _steps(root, session)
    assert [r.seq for r in records] == list(range(len(records)))
    head = None
    for record in records:
        assert record.parent == head or (not record.changed and record.commit == head)
        head = record.commit
    store = open_store(root, create=False)
    assert resolve_ref(store, store.ref(session)) == head
    subprocess.run(
        ["git", "--git-dir", str(store.shadow_dir), "fsck", "--connectivity-only", "--no-dangling"],
        check=True,
        capture_output=True,
    )


# --- sessions and steps -------------------------------------------------------


def test_start_records_baseline(project: Path) -> None:
    baseline = _start(Recorder(project))
    assert baseline is not None
    assert baseline.seq == 0
    assert baseline.kind is StepKind.BASELINE
    assert baseline.changed
    assert baseline.parent is None
    assert _steps(project) == [baseline]
    meta = json.loads((project / ".agent-blackbox/sessions" / SESSION / "meta.json").read_text())
    assert meta["session"] == SESSION
    assert meta["adapter"] == "test"
    assert meta["ended_ns"] is None
    _assert_chain_consistent(project)


def test_step_after_edit_is_recorded_with_metadata(project: Path) -> None:
    recorder = Recorder(project)
    baseline = _start(recorder)
    assert baseline is not None
    (project / "app.py").write_text("print('changed')\n")
    step = recorder.record_step(
        _step_event(turn_id="turn-1", agent=AgentRef(id="a1", type="Explore"), flags=("x",))
    )
    assert step is not None
    assert (step.seq, step.kind, step.changed) == (1, StepKind.TOOL, True)
    assert step.parent == baseline.commit
    assert step.turn == "turn-1"
    assert step.agent == AgentRef(id="a1", type="Explore")
    assert step.tool == "Edit"
    assert step.flags == ("x",)
    _assert_chain_consistent(project)


def test_commit_message_is_the_record(project: Path) -> None:
    recorder = Recorder(project)
    _start(recorder)
    (project / "new.txt").write_text("x\n")
    step = recorder.record_step(_step_event())
    assert step is not None
    store = open_store(project, create=False)
    message = store.git().run("log", "-1", "--format=%B", step.commit or "").decode()
    from_commit = StepRecord.from_dict(json.loads(message))
    assert from_commit.seq == step.seq
    assert from_commit.tree == step.tree
    assert from_commit.commit is None


def test_step_without_change_is_recorded_but_not_committed(project: Path) -> None:
    recorder = Recorder(project)
    baseline = _start(recorder)
    assert baseline is not None
    step = recorder.record_step(_step_event(tool="mcp__db__query"))
    assert step is not None
    assert not step.changed
    assert step.commit == baseline.commit
    assert step.tree == baseline.tree
    _assert_chain_consistent(project)


def test_failed_tool_is_recorded(project: Path) -> None:
    recorder = Recorder(project)
    _start(recorder)
    (project / "partial.txt").write_text("half\n")
    step = recorder.record_step(_step_event(tool="Bash", ok=False))
    assert step is not None
    assert step.ok is False
    assert step.changed


def test_large_tool_input_is_truncated(project: Path) -> None:
    recorder = Recorder(project)
    _start(recorder)
    step = recorder.record_step(_step_event(tool_input={"content": "x" * 100_000}))
    assert step is not None
    assert step.input is not None
    assert "$truncated" in step.input["content"]


def test_step_before_start_creates_baseline_implicitly(project: Path) -> None:
    recorder = Recorder(project)
    (project / "early.txt").write_text("x\n")
    step = recorder.record_step(_step_event())
    assert step is not None
    records = _steps(project)
    assert [r.kind for r in records] == [StepKind.BASELINE, StepKind.TOOL]
    assert not records[1].changed


def test_resume_records_external_changes_only(project: Path) -> None:
    recorder = Recorder(project)
    _start(recorder)
    assert _start(recorder, kind="resume") is None
    (project / "user-edit.txt").write_text("by hand\n")
    external = _start(recorder, kind="resume")
    assert external is not None
    assert external.kind is StepKind.EXTERNAL
    assert len(_steps(project)) == 2


def test_turn_is_stored_and_user_edits_become_external_step(project: Path) -> None:
    recorder = Recorder(project)
    _start(recorder)
    first = recorder.record_turn(
        TurnEvent(session_id=SESSION, turn_id="t1", prompt="fix it", synthetic=False, at_ns=1)
    )
    assert first is None  # nothing changed since the baseline
    (project / "app.py").write_text("edited by the user between turns\n")
    external = recorder.record_turn(
        TurnEvent(session_id=SESSION, turn_id="t2", prompt="now test", synthetic=False, at_ns=2)
    )
    assert external is not None
    assert external.kind is StepKind.EXTERNAL
    assert external.turn == "t2"
    turns = journal.read_records(project / ".agent-blackbox/sessions" / SESSION / "turns.jsonl")
    assert [(t["turn"], t["prompt"]) for t in turns] == [("t1", "fix it"), ("t2", "now test")]


def test_long_prompts_are_truncated(project: Path) -> None:
    recorder = Recorder(project)
    recorder.record_turn(
        TurnEvent(
            session_id=SESSION,
            turn_id="t1",
            prompt="p" * (MAX_PROMPT_CHARS + 50),
            synthetic=False,
            at_ns=1,
        )
    )
    (turn,) = journal.read_records(project / ".agent-blackbox/sessions" / SESSION / "turns.jsonl")
    assert len(turn["prompt"]) < MAX_PROMPT_CHARS + 100
    assert turn["prompt"].endswith("[truncated 50 chars]")


def test_end_session_marks_meta_and_captures_trailing_changes(project: Path) -> None:
    recorder = Recorder(project)
    _start(recorder)
    (project / "last.txt").write_text("x\n")
    final = recorder.end_session(
        SessionEvent(session_id=SESSION, kind="end", at_ns=123, adapter="test")
    )
    assert final is not None
    assert final.kind is StepKind.EXTERNAL
    meta = json.loads((project / ".agent-blackbox/sessions" / SESSION / "meta.json").read_text())
    assert meta["ended_ns"] == 123


def test_sessions_are_independent(project: Path) -> None:
    recorder = Recorder(project)
    _start(recorder, "a")
    _start(recorder, "b")
    (project / "x.txt").write_text("x\n")
    recorder.record_step(_step_event(session="a"))
    assert [r.seq for r in _steps(project, "a")] == [0, 1]
    assert [r.seq for r in _steps(project, "b")] == [0]


def test_invalid_session_id_is_rejected(project: Path) -> None:
    with pytest.raises(InvalidSessionIdError):
        Recorder(project).record_step(_step_event(session="../../etc"))


def test_non_git_project_is_recorded(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    root.mkdir()
    (root / "a.txt").write_text("a\n")
    recorder = Recorder(root)
    _start(recorder)
    (root / "b.txt").write_text("b\n")
    step = recorder.record_step(_step_event())
    assert step is not None
    assert step.changed
    _assert_chain_consistent(root)


# --- limits and lock contention -----------------------------------------------


def test_too_many_files_disables_the_session(project: Path) -> None:
    recorder = Recorder(project, RecorderConfig(limits=Limits(max_files=2)))
    assert _start(recorder) is not None  # 2 files: at the limit
    (project / "third.txt").write_text("x\n")
    assert recorder.record_step(_step_event()) is None
    (project / "third.txt").unlink()
    assert recorder.record_step(_step_event()) is None  # stays disabled
    assert (project / ".agent-blackbox/sessions" / SESSION / "disabled").is_file()
    assert len(_steps(project)) == 1


def test_lock_timeout_drops_the_step_without_raising(project: Path) -> None:
    recorder = Recorder(project, RecorderConfig(lock_timeout_s=0.05))
    _start(recorder)
    store = open_store(project, create=False)
    with ProjectLock(store.lock_path, timeout_s=1):
        # A different open file description, so flock conflicts even in-process.
        dropped = recorder.record_step(_step_event())
    assert dropped is not None
    assert dropped.kind is StepKind.DROPPED
    assert len(_steps(project)) == 1
    side = journal.read_records(project / ".agent-blackbox/sessions" / SESSION / "dropped.jsonl")
    assert [r["kind"] for r in side] == ["dropped"]
    assert side[0]["tool"] == "Edit"


# --- crash recovery -----------------------------------------------------------


@pytest.mark.parametrize(
    "crash_at", ["after-add", "after-commit", "after-update-ref", "mid-journal"]
)
def test_recovers_from_crash_at_each_stage(project: Path, crash_at: str) -> None:
    recorder = Recorder(project)
    _start(recorder)
    assert _drive(project, "crash", 1, crash_at=crash_at) == 137
    _drive(project, "after", 1)
    records = _steps(project)
    _assert_chain_consistent(project)
    tools = [r for r in records if r.kind is StepKind.TOOL]
    if crash_at in ("after-update-ref", "mid-journal"):
        # The crashed step reached the ref, so it is recovered from the commit.
        assert [("recovered" in r.flags) for r in tools] == [True, False]
    else:
        assert len(tools) == 1
    last = tools[-1]
    store = open_store(project, create=False)
    files = store.git().run("ls-tree", "-r", "--name-only", last.tree or "").decode().split()
    assert "crash-0.txt" in files
    assert "after-0.txt" in files


def test_torn_journal_line_is_repaired(project: Path) -> None:
    recorder = Recorder(project)
    _start(recorder)
    steps = project / ".agent-blackbox/sessions" / SESSION / "steps.jsonl"
    with steps.open("ab") as fh:
        fh.write(b'{"v":1,"seq":')
    (project / "x.txt").write_text("x\n")
    recorder.record_step(_step_event())
    assert steps.read_bytes().count(b"\n") == 2
    _assert_chain_consistent(project)


# --- concurrency --------------------------------------------------------------


def test_concurrent_writers_in_one_session_keep_a_consistent_chain(project: Path) -> None:
    _start(Recorder(project))
    procs = [
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tests.integration._driver",
                str(project),
                SESSION,
                f"w{n}",
                "5",
            ],
            cwd=REPO_ROOT,
        )
        for n in range(8)
    ]
    assert [p.wait(timeout=120) for p in procs] == [0] * 8
    records = _steps(project)
    assert len(records) == 1 + 8 * 5
    _assert_chain_consistent(project)
    store = open_store(project, create=False)
    final = store.git().run("ls-tree", "-r", "--name-only", records[-1].tree or "").decode().split()
    assert {f"w{n}-{i}.txt" for n in range(8) for i in range(5)} <= set(final)


def test_concurrent_sessions_do_not_interfere(project: Path) -> None:
    procs = [
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tests.integration._driver",
                str(project),
                f"s{n}",
                f"s{n}",
                "4",
            ],
            cwd=REPO_ROOT,
        )
        for n in range(4)
    ]
    assert [p.wait(timeout=120) for p in procs] == [0] * 4
    for n in range(4):
        records = _steps(project, f"s{n}")
        assert [r.kind for r in records] == [StepKind.BASELINE] + [StepKind.TOOL] * 4
        _assert_chain_consistent(project, f"s{n}")


# --- recovery branches (in-process, so they count for coverage) ---------------


def _shadow(root: Path, *args: str) -> str:
    store = open_store(root, create=False)
    return store.git().run(*args).decode().strip()


def test_deleted_ref_is_restored_from_the_journal(project: Path) -> None:
    recorder = Recorder(project)
    _start(recorder)
    ref = open_store(project, create=False).ref(SESSION)
    _shadow(project, "update-ref", "-d", ref)
    (project / "x.txt").write_text("x\n")
    assert recorder.record_step(_step_event()) is not None
    _assert_chain_consistent(project)


def test_ref_behind_the_journal_is_moved_forward(project: Path) -> None:
    recorder = Recorder(project)
    baseline = _start(recorder)
    assert baseline is not None
    (project / "x.txt").write_text("x\n")
    recorder.record_step(_step_event())
    ref = open_store(project, create=False).ref(SESSION)
    _shadow(project, "update-ref", ref, baseline.commit or "")
    (project / "y.txt").write_text("y\n")
    assert recorder.record_step(_step_event()) is not None
    _assert_chain_consistent(project)


def test_commit_with_unparsable_message_is_recovered_as_external(project: Path) -> None:
    recorder = Recorder(project)
    baseline = _start(recorder)
    assert baseline is not None
    store = open_store(project, create=False)
    foreign = _shadow(
        project, "commit-tree", baseline.tree or "", "-p", baseline.commit or "", "-m", "not json"
    )
    _shadow(project, "update-ref", store.ref(SESSION), foreign)
    (project / "z.txt").write_text("z\n")
    recorder.record_step(_step_event())
    records = _steps(project)
    assert records[1].commit == foreign
    assert records[1].kind is StepKind.EXTERNAL
    assert "unparsable_commit_message" in records[1].flags
    _assert_chain_consistent(project)


def test_update_ref_compare_and_swap(project: Path) -> None:
    from agent_blackbox.core.snapshot import update_ref  # noqa: PLC0415

    recorder = Recorder(project)
    baseline = _start(recorder)
    assert baseline is not None
    store = open_store(project, create=False)
    ref = store.ref(SESSION)
    assert update_ref(store, ref, baseline.commit or "", "0" * 40) is False
    assert update_ref(store, "refs/agent-blackbox/other", baseline.commit or "", None) is True
    assert update_ref(store, "refs/agent-blackbox/other", baseline.commit or "", None) is False


def test_open_store_without_shadow_repository_fails(project: Path) -> None:
    import shutil  # noqa: PLC0415

    from agent_blackbox.core.errors import StorageError  # noqa: PLC0415

    open_store(project, create=True)
    shutil.rmtree(project / ".agent-blackbox" / "shadow.git")
    with pytest.raises(StorageError, match="shadow repository"):
        open_store(project, create=False)


def test_session_start_refreshes_cached_workspace_after_git_init(tmp_path: Path) -> None:
    from tests.integration.conftest import git  # noqa: PLC0415

    root = tmp_path / "later-repo"
    root.mkdir()
    (root / ".env").write_text("SECRET=1\n")
    recorder = Recorder(root)
    _start(recorder, "before")
    assert not open_store(root, create=False).workspace.in_git_repo
    git(root, "init", "-q")
    _start(recorder, "after")
    store = open_store(root, create=False)
    assert store.workspace.in_git_repo
    # No .gitignore and now a git repo: .env is no longer excluded by defaults.
    files = store.git().run("ls-tree", "-r", "--name-only", _steps(root, "after")[0].tree or "")
    assert b".env" in files.split()


def test_packed_refs_are_resolved(project: Path) -> None:
    recorder = Recorder(project)
    baseline = _start(recorder)
    assert baseline is not None
    _shadow(project, "pack-refs", "--all")
    store = open_store(project, create=False)
    assert not (store.shadow_dir / store.ref(SESSION)).exists()
    assert resolve_ref(store, store.ref(SESSION)) == baseline.commit
    (project / "x.txt").write_text("x\n")
    assert recorder.record_step(_step_event()) is not None
    _assert_chain_consistent(project)
