---
name: dev-setup
description: Takes a fresh clone of agent-blackbox to a verified development environment (uv, git, dependencies, pre-commit, full test suite, docs build) and, once the hook exists, confirms recording works with a real Claude Code session. Use on a new machine, in a new container, or when the dev environment seems broken.
allowed-tools: Bash(uv --version) Bash(git --version) Bash(uv sync *) Bash(uv run *) Bash(uv build *)
---

# Development environment setup

Work from the repository root. Stop at the first failing step, fix it, and
re-run that step before continuing. Report a table of steps with ✅/❌ at
the end.

## 1. Prerequisites

```sh
uv --version        # any recent uv; install: https://docs.astral.sh/uv/
git --version       # >= 2.25, the minimum `doctor` will check (ADR-0001)
uname -s            # Linux or Darwin; Windows is unsupported (ADR-0006)
```

If `uv` is missing, ask the user before installing anything system-wide.

## 2. Dependencies and hooks

```sh
uv sync                        # creates .venv from uv.lock (dev group included)
uv run pre-commit install      # git hook with the same checks as CI
```

`uv sync` must not modify `uv.lock`. If it does, the lock is stale: report it
instead of committing the change silently.

## 3. Verify

Run exactly what CI runs:

```sh
uv run pre-commit run --all-files
uv run pytest --cov=agent_blackbox
uv run coverage report --include='src/agent_blackbox/core/*' --fail-under=90
uv run --group docs mkdocs build --strict
uv build
```

All must pass on a clean checkout of `main`. A failure on `main` is a bug:
report it with the command and output.

## 4. Recording smoke test (from Phase 3 on)

Skip this step while `agent-blackbox install` does not exist
(`uv run agent-blackbox --help` does not list it).

1. Create a throwaway project: `mkdir -p "$TMPDIR/ab-smoke" && cd` into it,
   `git init`, add a file, commit.
2. `uv run --project <repo> agent-blackbox install` inside it.
3. Run a short headless session that edits a file and runs a Bash command,
   for example
   `claude -p "Create hello.txt with Hello, then run: echo bye > bye.txt" --allowedTools "Write,Bash"`.
4. `uv run --project <repo> agent-blackbox log --json` must list both steps
   with their tool names; `agent-blackbox doctor` must report no problems.
5. `agent-blackbox uninstall` and confirm `.claude/settings.local.json` is back
   to its original content.

## Troubleshooting

- `pytest` fails with socket errors: a test is trying to use the network,
  which the suite forbids on purpose (`--disable-socket`). Fix the test.
- `lint-imports` fails: a module broke the layering in `AGENTS.md`; move the
  code, never relax the contract.
- mypy differs locally vs CI: make sure you run `uv run mypy` (the locked
  version), not a global mypy.
