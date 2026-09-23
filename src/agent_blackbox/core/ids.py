"""Validation of identifiers that become file names and git ref components."""

from __future__ import annotations

import re

from agent_blackbox.core.errors import AgentBlackboxError

_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class InvalidSessionIdError(AgentBlackboxError, ValueError):
    """A session identifier is not safe to use as a path or ref component."""


def validate_session_id(value: str) -> str:
    """Return ``value`` if it is safe as a directory name and a git ref component.

    Session identifiers come from the agent (untrusted). They are used in
    ``.agent-blackbox/sessions/<id>/`` and ``refs/agent-blackbox/sessions/<id>``,
    so they must not allow path traversal, option injection or invalid refs.

    Args:
        value: The candidate identifier.

    Returns:
        The same value, unchanged.

    Raises:
        InvalidSessionIdError: If the value is empty, longer than 128
            characters, not ASCII alphanumerics plus ``._-``, starts with ``.``
            or ``-``, contains ``..``, or ends with ``.`` or ``.lock``.
    """
    if not _SESSION_ID.fullmatch(value) or ".." in value or value.endswith((".", ".lock")):
        msg = f"unsafe session id: {value[:64]!r}"
        raise InvalidSessionIdError(msg)
    return value
