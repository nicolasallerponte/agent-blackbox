"""Running git safely: argument vectors, scrubbed environment, pinned config.

Every git invocation in agent-blackbox goes through :func:`run_git`. It never
uses a shell, removes inherited ``GIT_*`` variables that could redirect or
reconfigure git (``GIT_DIR``, ``GIT_CONFIG_PARAMETERS``, pathspec modes, ...),
and pins configuration that would otherwise change snapshot content or run
external programs.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from agent_blackbox.core.errors import GitError

#: Inherited GIT_* variables that are safe to keep (user-level config selection).
_KEPT_GIT_VARS = frozenset(
    {"GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_EXEC_PATH"}
)

#: Configuration forced on every shadow-repository command.
PINNED_CONFIG: tuple[str, ...] = (
    "core.autocrlf=false",
    "core.safecrlf=false",
    "core.fsmonitor=false",
    "core.untrackedCache=true",
    "core.hooksPath=/dev/null",
    "core.quotePath=false",
    "core.splitIndex=false",
    "core.sparseCheckout=false",
    "commit.gpgSign=false",
    "gc.auto=0",
    "maintenance.auto=false",
    "advice.detachedHead=false",
)

#: Deterministic identity for shadow commits.
SHADOW_IDENTITY = ("agent-blackbox", "agent-blackbox@localhost")

DEFAULT_TIMEOUT_S = 30.0


def scrubbed_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return the current environment minus unsafe ``GIT_*`` variables, plus ``extra``."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") or k in _KEPT_GIT_VARS}
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["LC_ALL"] = "C"
    if extra:
        env.update(extra)
    return env


def run_git(
    args: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    stdin: bytes | None = None,
    ok_codes: tuple[int, ...] = (0,),
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> subprocess.CompletedProcess[bytes]:
    """Run ``git <args>`` without a shell.

    Args:
        args: Arguments after ``git``. Callers must put ``--`` before paths.
        cwd: Working directory.
        env: Extra environment variables on top of :func:`scrubbed_env`.
        stdin: Bytes sent to standard input.
        ok_codes: Exit codes that are not errors.
        timeout_s: Kill git after this many seconds.

    Returns:
        The completed process (stdout and stderr as bytes).

    Raises:
        GitError: On a disallowed exit code, a timeout, or if git is missing.
    """
    argv = ("git", *args)
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            env=scrubbed_env(env),
            input=stdin,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError(tuple(args), -1, f"timed out after {timeout_s}s") from exc
    except OSError as exc:
        raise GitError(tuple(args), -1, str(exc)) from exc
    if proc.returncode not in ok_codes:
        raise GitError(tuple(args), proc.returncode, proc.stderr.decode("utf-8", "replace"))
    return proc


@dataclass(frozen=True)
class ShadowGit:
    """Git bound to a shadow repository, a work tree and a private index."""

    git_dir: Path
    work_tree: Path
    index_file: Path | None = None
    timeout_s: float = DEFAULT_TIMEOUT_S

    def run(
        self,
        *args: str,
        cwd: Path | None = None,
        stdin: bytes | None = None,
        env: Mapping[str, str] | None = None,
        ok_codes: tuple[int, ...] = (0,),
    ) -> bytes:
        """Run a git command against the shadow repository and return stdout."""
        return self.run_process(*args, cwd=cwd, stdin=stdin, env=env, ok_codes=ok_codes).stdout

    def run_process(
        self,
        *args: str,
        cwd: Path | None = None,
        stdin: bytes | None = None,
        env: Mapping[str, str] | None = None,
        ok_codes: tuple[int, ...] = (0,),
    ) -> subprocess.CompletedProcess[bytes]:
        """Like :meth:`run`, but return the completed process (exit code, stderr)."""
        extra = {"GIT_DIR": str(self.git_dir), "GIT_WORK_TREE": str(self.work_tree)}
        if self.index_file is not None:
            extra["GIT_INDEX_FILE"] = str(self.index_file)
        if env:
            extra.update(env)
        pinned = [part for item in PINNED_CONFIG for part in ("-c", item)]
        return run_git(
            [*pinned, *args],
            cwd=cwd or self.work_tree,
            env=extra,
            stdin=stdin,
            ok_codes=ok_codes,
            timeout_s=self.timeout_s,
        )
