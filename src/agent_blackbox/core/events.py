"""Agent-agnostic events that adapters translate agent activity into (design §3.1)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from agent_blackbox.core.records import AgentRef


@dataclass(frozen=True)
class SessionEvent:
    """A session started, resumed or ended."""

    session_id: str
    kind: Literal["start", "resume", "end"]
    at_ns: int
    adapter: str


@dataclass(frozen=True)
class TurnEvent:
    """The user submitted a prompt (``synthetic`` for agent-generated prompts)."""

    session_id: str
    turn_id: str
    prompt: str
    synthetic: bool
    at_ns: int


@dataclass(frozen=True)
class StepEvent:
    """A tool call finished and may have changed the workspace."""

    session_id: str
    tool: str
    tool_input: Mapping[str, Any]
    ok: bool
    ended_ns: int
    started_ns: int | None = None
    turn_id: str | None = None
    agent: AgentRef | None = None
    flags: tuple[str, ...] = ()
