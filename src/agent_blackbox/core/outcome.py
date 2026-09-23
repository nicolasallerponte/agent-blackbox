"""Classification of test-command results, following ``git bisect run``."""

from __future__ import annotations

import enum

#: Exit code that marks a state as untestable (same as ``git bisect run``).
SKIP_EXIT_CODE = 125

#: Exit codes at or above this value abort the whole bisect.
ABORT_THRESHOLD = 128


class Outcome(enum.Enum):
    """Verdict for one evaluation of the test command on one workspace state."""

    GOOD = "good"
    BAD = "bad"
    SKIP = "skip"
    ABORT = "abort"


def classify_exit_code(code: int) -> Outcome:
    """Map a process exit code to an :class:`Outcome`.

    The convention is identical to ``git bisect run``: ``0`` is good, ``125``
    is skip, ``1``-``127`` (except ``125``) is bad, and ``128`` or above aborts.
    Negative codes, which :mod:`subprocess` uses for death by signal, abort too.

    Args:
        code: Exit status as reported by :attr:`subprocess.CompletedProcess.returncode`.

    Returns:
        The outcome for that exit status.
    """
    if code == 0:
        return Outcome.GOOD
    if code == SKIP_EXIT_CODE:
        return Outcome.SKIP
    if 0 < code < ABORT_THRESHOLD:
        return Outcome.BAD
    return Outcome.ABORT
