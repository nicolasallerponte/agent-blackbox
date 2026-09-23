"""Recording sessions: snapshots, journals and crash recovery (design §4, §6).

Every public method takes the project lock, repairs any state left by a
crashed process, snapshots the workspace and appends a journal record. The
write order is: git objects → commit → compare-and-swap ref update → journal
line. The commit message carries the same record, so a crash between the ref
update and the journal append is repaired by replaying commit messages.
"""

from __future__ import annotations

import dataclasses
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_blackbox.core import journal
from agent_blackbox.core.errors import LockTimeoutError, StorageError
from agent_blackbox.core.fsutil import write_atomic
from agent_blackbox.core.ids import validate_session_id
from agent_blackbox.core.layout import Store, open_store, refresh_excludes, refresh_workspace
from agent_blackbox.core.lock import ProjectLock
from agent_blackbox.core.records import (
    AgentRef,
    StepKind,
    StepRecord,
    TurnRecord,
    truncate_payload,
)
from agent_blackbox.core.snapshot import (
    CommitInfo,
    Limits,
    SnapshotTooLargeError,
    commit_tree,
    commits_between,
    resolve_ref,
    update_ref,
    write_tree,
)

if TYPE_CHECKING:
    from agent_blackbox.core.events import SessionEvent, StepEvent, TurnEvent

#: Testing aid: when set to a stage name, the process is killed at that stage
#: (``after-add``, ``after-commit``, ``after-update-ref``, ``mid-journal``).
CRASH_ENV = "AGENT_BLACKBOX_TESTING_CRASH_AT"

#: Prompts longer than this are truncated before being stored.
MAX_PROMPT_CHARS = 16 * 1024

_RECOVERED = "recovered"


@dataclass(frozen=True)
class RecorderConfig:
    """Tunables for a :class:`Recorder`."""

    limits: Limits = dataclasses.field(default_factory=Limits)
    lock_timeout_s: float = 2.0


@dataclass(frozen=True)
class _Cause:
    """What a snapshot is attributed to (fields copied into the record)."""

    kind: StepKind
    ended_ns: int
    turn: str | None = None
    agent: AgentRef | None = None
    tool: str | None = None
    input: dict[str, Any] | None = None
    ok: bool | None = None
    started_ns: int | None = None
    flags: tuple[str, ...] = ()


class Recorder:
    """Records one project's sessions. Safe to use from many processes at once."""

    def __init__(self, root: Path, config: RecorderConfig | None = None) -> None:
        self._root = root
        self._config = config or RecorderConfig()

    def start_session(self, event: SessionEvent) -> StepRecord | None:
        """Handle a session start or resume.

        A new session gets a baseline snapshot. A known session gets an
        ``external`` snapshot only if the workspace changed in between.
        """
        sid = validate_session_id(event.session_id)
        cause = _Cause(kind=StepKind.EXTERNAL, ended_ns=event.at_ns)
        return self._locked(sid, cause, lambda store: self._start(store, sid, event))

    def record_turn(self, event: TurnEvent) -> StepRecord | None:
        """Store the prompt and snapshot changes made since the last step (by the user)."""
        sid = validate_session_id(event.session_id)
        cause = _Cause(kind=StepKind.EXTERNAL, ended_ns=event.at_ns, turn=event.turn_id)
        turn = TurnRecord(
            session=sid,
            turn=event.turn_id,
            prompt=_truncate_prompt(event.prompt),
            synthetic=event.synthetic,
            at_ns=event.at_ns,
        )

        def run(store: Store) -> StepRecord | None:
            journal.append(self._session_dir(store, sid) / "turns.jsonl", turn.to_dict())
            return self._snapshot(store, sid, cause, only_if_changed=True)

        return self._locked(sid, cause, run, dropped_extra={"turn_record": turn.to_dict()})

    def record_step(self, event: StepEvent) -> StepRecord | None:
        """Snapshot the workspace after a tool call. Always journals a record."""
        sid = validate_session_id(event.session_id)
        cause = _Cause(
            kind=StepKind.TOOL,
            ended_ns=event.ended_ns,
            turn=event.turn_id,
            agent=event.agent,
            tool=event.tool,
            input=_as_dict(truncate_payload(dict(event.tool_input))),
            ok=event.ok,
            started_ns=event.started_ns,
            flags=event.flags,
        )
        return self._locked(
            sid, cause, lambda store: self._snapshot(store, sid, cause, only_if_changed=False)
        )

    def end_session(self, event: SessionEvent) -> StepRecord | None:
        """Snapshot trailing changes and mark the session as ended."""
        sid = validate_session_id(event.session_id)
        cause = _Cause(kind=StepKind.EXTERNAL, ended_ns=event.at_ns)

        def run(store: Store) -> StepRecord | None:
            record = self._snapshot(store, sid, cause, only_if_changed=True)
            self._write_meta(store, sid, adapter=event.adapter, at_ns=None, ended_ns=event.at_ns)
            return record

        return self._locked(sid, cause, run)

    # --- internals -----------------------------------------------------------

    def _start(self, store: Store, sid: str, event: SessionEvent) -> StepRecord | None:
        store = refresh_workspace(store)
        refresh_excludes(store)
        self._write_meta(store, sid, adapter=event.adapter, at_ns=event.at_ns, ended_ns=None)
        cause = _Cause(kind=StepKind.EXTERNAL, ended_ns=event.at_ns)
        return self._snapshot(store, sid, cause, only_if_changed=True)

    def _locked(
        self,
        sid: str,
        cause: _Cause,
        action: Callable[[Store], StepRecord | None],
        dropped_extra: dict[str, Any] | None = None,
    ) -> StepRecord | None:
        timeout = self._config.lock_timeout_s
        store = open_store(self._root, create=True, lock_timeout_s=timeout)
        try:
            with ProjectLock(store.lock_path, timeout_s=timeout):
                return action(store)
        except LockTimeoutError:
            return self._drop(store, sid, cause, dropped_extra or {})

    def _snapshot(
        self, store: Store, sid: str, cause: _Cause, *, only_if_changed: bool
    ) -> StepRecord | None:
        session_dir = self._session_dir(store, sid)
        if (session_dir / "disabled").exists():
            return None
        steps = session_dir / "steps.jsonl"
        self._recover(store, sid, steps)
        last_raw = journal.last_record(steps)
        last = StepRecord.from_dict(last_raw) if last_raw else None
        if last is None:
            # First snapshot of the session is always a baseline, even when a
            # tool event arrives before the session start (late install).
            baseline_cause = _Cause(kind=StepKind.BASELINE, ended_ns=cause.ended_ns)
            baseline = self._take(
                store, sid, steps, baseline_cause, seq=0, parent=None, prev_tree=None
            )
            if baseline is None or cause.kind is not StepKind.TOOL:
                return baseline
            last = baseline
        return self._take(
            store,
            sid,
            steps,
            cause,
            seq=last.seq + 1,
            parent=last.commit,
            prev_tree=last.tree,
            only_if_changed=only_if_changed,
        )

    def _take(
        self,
        store: Store,
        sid: str,
        steps: Path,
        cause: _Cause,
        *,
        seq: int,
        parent: str | None,
        prev_tree: str | None,
        only_if_changed: bool = False,
    ) -> StepRecord | None:
        try:
            snap = write_tree(store, sid, self._config.limits)
        except SnapshotTooLargeError as exc:
            write_atomic(self._session_dir(store, sid) / "disabled", f"{exc}\n")
            return None
        _crash_point("after-add")
        changed = snap.tree != prev_tree
        if not changed and only_if_changed:
            return None
        record = StepRecord(
            seq=seq,
            kind=cause.kind,
            session=sid,
            ended_ns=cause.ended_ns,
            changed=changed,
            commit=parent,
            tree=snap.tree,
            parent=parent,
            turn=cause.turn,
            agent=cause.agent,
            tool=cause.tool,
            input=cause.input,
            ok=cause.ok,
            started_ns=cause.started_ns,
            skipped_large=snap.skipped_large,
            flags=cause.flags,
        )
        if changed:
            message = dataclasses.replace(record, commit=None).to_json()
            commit = commit_tree(store, snap.tree, parent, message, cause.ended_ns)
            _crash_point("after-commit")
            if not update_ref(store, store.ref(sid), commit, parent):
                msg = f"session ref {store.ref(sid)} moved while holding the project lock"
                raise StorageError(msg)
            _crash_point("after-update-ref")
            record = dataclasses.replace(record, commit=commit)
        _crash_point("mid-journal", steps, record.to_json())
        journal.append(steps, record.to_dict())
        return record

    def _recover(self, store: Store, sid: str, steps: Path) -> None:
        """Bring the journal back in line with the session ref after a crash."""
        journal.repair(steps)
        last_raw = journal.last_record(steps)
        last = StepRecord.from_dict(last_raw) if last_raw else None
        journal_head = last.commit if last else None
        ref = store.ref(sid)
        ref_head = resolve_ref(store, ref)
        if ref_head == journal_head:
            return
        if ref_head is None:
            # Ref lost (e.g. deleted by hand): point it back at the journal head.
            update_ref(store, ref, journal_head or "", None)
            return
        missing = commits_between(store, journal_head, ref_head)
        if not missing:
            # Journal is ahead of the ref: trust the journal.
            update_ref(store, ref, journal_head or "", ref_head)
            return
        next_seq = last.seq + 1 if last else 0
        for info in missing:
            record = _record_from_commit(sid, info, next_seq)
            journal.append(steps, record.to_dict())
            next_seq = record.seq + 1

    def _drop(self, store: Store, sid: str, cause: _Cause, extra: dict[str, Any]) -> StepRecord:
        record = StepRecord(
            seq=-1,
            kind=StepKind.DROPPED,
            session=sid,
            ended_ns=cause.ended_ns,
            changed=False,
            turn=cause.turn,
            agent=cause.agent,
            tool=cause.tool,
            input=cause.input,
            ok=cause.ok,
            started_ns=cause.started_ns,
            flags=(*cause.flags, "lock_timeout"),
        )
        # Written without the lock: one small O_APPEND write per record.
        journal.append(
            self._session_dir(store, sid) / "dropped.jsonl", {**record.to_dict(), **extra}
        )
        return record

    def _session_dir(self, store: Store, sid: str) -> Path:
        path = store.session_dir(sid)
        if not path.is_dir():
            store.sessions_dir.mkdir(mode=0o700, exist_ok=True)
            path.mkdir(mode=0o700, exist_ok=True)
        return path

    def _write_meta(
        self, store: Store, sid: str, *, adapter: str, at_ns: int | None, ended_ns: int | None
    ) -> None:
        path = self._session_dir(store, sid) / "meta.json"
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            meta = {"v": 1, "session": sid, "root": str(store.workspace.root), "started_ns": at_ns}
        meta["adapter"] = adapter
        meta["ended_ns"] = ended_ns
        write_atomic(path, json.dumps(meta, indent=2) + "\n")


def _record_from_commit(sid: str, info: CommitInfo, next_seq: int) -> StepRecord:
    """Rebuild a journal record from a commit; tree and parent come from git itself."""
    try:
        record = StepRecord.from_dict(json.loads(info.message))
    except (ValueError, KeyError, TypeError):
        record = StepRecord(
            seq=next_seq,
            kind=StepKind.EXTERNAL,
            session=sid,
            ended_ns=time.time_ns(),
            changed=True,
            flags=("unparsable_commit_message",),
        )
    return dataclasses.replace(
        record,
        seq=next_seq,
        commit=info.sha,
        tree=info.tree,
        parent=info.parent,
        changed=True,
        flags=(*record.flags, _RECOVERED),
    )


def _truncate_prompt(prompt: str) -> str:
    if len(prompt) <= MAX_PROMPT_CHARS:
        return prompt
    return f"{prompt[:MAX_PROMPT_CHARS]}… [truncated {len(prompt) - MAX_PROMPT_CHARS} chars]"


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {"value": value}


def _crash_point(stage: str, path: Path | None = None, line: str | None = None) -> None:
    if os.environ.get(CRASH_ENV) != stage:
        return
    if path is not None and line is not None:
        with path.open("ab") as fh:
            fh.write(line.encode("utf-8")[: max(1, len(line) // 2)])
    os._exit(137)
