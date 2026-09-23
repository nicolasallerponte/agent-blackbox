"""Versioned records stored in session journals (docs/adr/0002-session-log-format.md)."""

from __future__ import annotations

import enum
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from agent_blackbox.core.journal import dumps_line

#: Version of the record layout written by this release.
SCHEMA_VERSION = 1

#: Strings longer than this (in characters) are truncated in stored inputs.
MAX_STRING_CHARS = 4096

#: Lists longer than this are cut in stored inputs.
MAX_LIST_ITEMS = 256

#: Nesting deeper than this is cut in stored inputs.
MAX_DEPTH = 16


class StepKind(str, enum.Enum):
    """Why a step record exists."""

    BASELINE = "baseline"
    TOOL = "tool"
    EXTERNAL = "external"
    DROPPED = "dropped"


@dataclass(frozen=True)
class AgentRef:
    """The agent that performed a step; ``None`` on a record means the main agent."""

    id: str
    type: str | None = None


@dataclass(frozen=True)
class StepRecord:
    """One recorded step: a workspace snapshot plus what caused it."""

    seq: int
    kind: StepKind
    session: str
    ended_ns: int
    changed: bool
    commit: str | None = None
    tree: str | None = None
    parent: str | None = None
    turn: str | None = None
    agent: AgentRef | None = None
    tool: str | None = None
    input: Mapping[str, Any] | None = None
    ok: bool | None = None
    started_ns: int | None = None
    skipped_large: tuple[str, ...] = ()
    flags: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-ready mapping, with ``v`` as the first key."""
        return {
            "v": SCHEMA_VERSION,
            "seq": self.seq,
            "kind": self.kind.value,
            "session": self.session,
            "turn": self.turn,
            "agent": None if self.agent is None else {"id": self.agent.id, "type": self.agent.type},
            "tool": self.tool,
            "input": None if self.input is None else dict(self.input),
            "ok": self.ok,
            "started_ns": self.started_ns,
            "ended_ns": self.ended_ns,
            "commit": self.commit,
            "tree": self.tree,
            "parent": self.parent,
            "changed": self.changed,
            "skipped_large": list(self.skipped_large),
            "flags": list(self.flags),
        }

    def to_json(self) -> str:
        """Serialize to one compact JSON line (no newline)."""
        return _dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> StepRecord:
        """Parse a record, ignoring unknown fields.

        Raises:
            ValueError: If the record was written by a newer, unknown schema.
            KeyError: If a required field is missing.
        """
        _check_version(data)
        agent = data.get("agent")
        return cls(
            seq=int(data["seq"]),
            kind=StepKind(data["kind"]),
            session=str(data["session"]),
            ended_ns=int(data["ended_ns"]),
            changed=bool(data["changed"]),
            commit=data.get("commit"),
            tree=data.get("tree"),
            parent=data.get("parent"),
            turn=data.get("turn"),
            agent=None if agent is None else AgentRef(id=str(agent["id"]), type=agent.get("type")),
            tool=data.get("tool"),
            input=data.get("input"),
            ok=data.get("ok"),
            started_ns=data.get("started_ns"),
            skipped_large=tuple(data.get("skipped_large", ())),
            flags=tuple(data.get("flags", ())),
        )


@dataclass(frozen=True)
class TurnRecord:
    """A user prompt that started (or, if synthetic, continued) a turn."""

    session: str
    turn: str
    prompt: str
    synthetic: bool
    at_ns: int

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-ready mapping, with ``v`` as the first key."""
        return {
            "v": SCHEMA_VERSION,
            "session": self.session,
            "turn": self.turn,
            "prompt": self.prompt,
            "synthetic": self.synthetic,
            "at_ns": self.at_ns,
        }

    def to_json(self) -> str:
        """Serialize to one compact JSON line (no newline)."""
        return _dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TurnRecord:
        """Parse a record, ignoring unknown fields."""
        _check_version(data)
        return cls(
            session=str(data["session"]),
            turn=str(data["turn"]),
            prompt=str(data["prompt"]),
            synthetic=bool(data["synthetic"]),
            at_ns=int(data["at_ns"]),
        )


def truncate_payload(value: object, *, _depth: int = 0) -> object:
    """Return a JSON-safe copy of ``value`` with bounded size.

    Strings longer than :data:`MAX_STRING_CHARS` become
    ``{"$truncated": {"head", "chars", "sha256"}}``; lists are cut to
    :data:`MAX_LIST_ITEMS` plus a ``{"$truncated_items": n}`` marker; nesting
    beyond :data:`MAX_DEPTH` becomes ``{"$truncated_depth": true}``; mapping keys
    become strings and non-JSON values their ``repr``/``str``.
    """
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _truncate_string(value)
    if _depth >= MAX_DEPTH:
        return {"$truncated_depth": True}
    if isinstance(value, Mapping):
        return {str(k): truncate_payload(v, _depth=_depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return _truncate_sequence(value, _depth)
    return str(value)


def _truncate_string(value: str) -> object:
    if len(value) <= MAX_STRING_CHARS:
        return value
    digest = hashlib.sha256(value.encode("utf-8", "surrogatepass")).hexdigest()
    head = value[:MAX_STRING_CHARS]
    return {"$truncated": {"head": head, "chars": len(value), "sha256": digest}}


def _truncate_sequence(value: list[object] | tuple[object, ...], depth: int) -> list[object]:
    items = [truncate_payload(v, _depth=depth + 1) for v in value[:MAX_LIST_ITEMS]]
    if len(value) > MAX_LIST_ITEMS:
        items.append({"$truncated_items": len(value) - MAX_LIST_ITEMS})
    return items


def _dumps(data: Mapping[str, Any]) -> str:
    return dumps_line(data)


def _check_version(data: Mapping[str, Any]) -> None:
    version = data.get("v", SCHEMA_VERSION)
    if not isinstance(version, int) or version > SCHEMA_VERSION:
        msg = f"unsupported record schema version {version!r} (reads <= {SCHEMA_VERSION})"
        raise ValueError(msg)
