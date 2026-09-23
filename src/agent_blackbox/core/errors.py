"""Exception hierarchy for the core."""

from __future__ import annotations


class AgentBlackboxError(Exception):
    """Base class for every error raised by agent-blackbox."""


class LockTimeoutError(AgentBlackboxError):
    """The project lock could not be acquired before the deadline."""


class GitError(AgentBlackboxError):
    """A git command failed.

    Attributes:
        args_: The git arguments (without the executable).
        returncode: The process exit status.
        stderr: Decoded standard error, for diagnostics.
    """

    def __init__(self, args_: tuple[str, ...], returncode: int, stderr: str) -> None:
        self.args_ = args_
        self.returncode = returncode
        self.stderr = stderr
        command = " ".join(args_[:3])
        super().__init__(f"git {command} ... exited {returncode}: {stderr.strip()[:500]}")


class StorageError(AgentBlackboxError):
    """The ``.agent-blackbox`` directory is missing, unsafe or inconsistent."""
