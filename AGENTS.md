# AGENTS.md

Source of truth for any coding agent working on this repository. Keep it
short: it is loaded into every session. User documentation lives in `docs/`.

## Project in five lines

agent-blackbox is a flight recorder for AI coding agents. Hooks snapshot the
workspace after every file-changing tool call into a shadow git repository
(`.agent-blackbox/`), never touching the user's git. The CLI inspects sessions
and `agent-blackbox bisect -- <test cmd>` binary-searches the steps to find the
one that broke the tests. Deterministic, local-first, and never in the agent's
way. Design: `docs/design.md`; decisions: `docs/adr/`.

## Architecture map

| Path | Contents | May import |
|---|---|---|
| `src/agent_blackbox/core/` | Snapshots, journal, lock, redaction, bisect. Agent-agnostic. | stdlib only |
| `src/agent_blackbox/adapters/<agent>/` | Hook entry, install/uninstall/doctor for one agent. | `core`, stdlib |
| `src/agent_blackbox/cli/` | Typer + Rich commands. | `core`, `adapters`, typer, rich |
| `tests/unit/` | Pure logic, Hypothesis properties. | anything |
| `tests/integration/` | Real git repositories in `tmp_path`. | anything |
| `tests/e2e/` | Replayed real hook payloads, full CLI runs. | anything |
| `docs/research/` | Captured Claude Code payloads (future fixtures). Do not edit by hand. | — |
| `scripts/` | Repository tooling (release notes). | stdlib |

Import rules are enforced by import-linter (`uv run lint-imports`).

## Commands

```sh
uv sync                                        # setup (Python >= 3.10, git >= 2.25)
uv run pre-commit install                      # once per clone
uv run pre-commit run --all-files              # everything CI's lint job runs
uv run pytest                                  # all tests
uv run pytest tests/unit/test_outcome.py       # one file
uv run pytest tests/unit/test_outcome.py::test_git_bisect_run_convention  # one test
uv run pytest --cov=agent_blackbox             # coverage
uv run coverage report --include='src/agent_blackbox/core/*' --fail-under=90  # core gate
uv run ruff check --fix . && uv run ruff format .
uv run mypy                                    # strict
uv run lint-imports                            # architecture contracts
uv run --group docs mkdocs build --strict      # docs
uv build                                       # sdist + wheel
```

Benchmarks (`benchmarks/`) arrive with the hook in Phase 3.

## Invariants (do not break; each has a reason)

1. **`core` never imports `adapters` or `cli`**, nor typer/rich. Reason: new
   agents must be addable without touching the core, and the hook path must
   stay fast.
2. **The hook never breaks or blocks the agent.** Catch everything, write
   nothing to stdout, always exit 0, respect the time budget. Reason: exit ≠ 0
   shows an error to the user; stdout is injected into Claude's context.
3. **No network calls** in any code path. Reason: local-first is a product
   promise. Enforced by ruff `banned-api` and `pytest --disable-socket`.
4. **No `shell=True`** and no shell interpolation of agent-controlled
   content; subprocesses take argument vectors. Reason: tool inputs are
   attacker-influenced (prompt injection).
5. **Every bug fix has a regression test that fails without the fix.**
   Verify it by reverting the fix locally, and say so in the PR.
6. **Tests first** for `core/` logic. Core coverage must stay ≥ 90 %.
7. **Never push to `main`.** Work on a branch, open a PR, merge only with
   green CI.
8. **No AI attribution anywhere on GitHub**: no `Co-Authored-By` trailers,
   session links or "Generated with" footers in commits, PRs, issues or
   comments. Commits are authored by the maintainer's git identity.
9. **English only** in code, comments, docs, commits, issues and PRs.

## Ask before touching

- The session log / storage format (`steps.jsonl`, `turns.jsonl`, shadow
  refs, `VERSION`) once released: changes need a migration and an ADR.
- The `--json` output schemas of CLI commands (public API).
- Accepted ADRs: supersede them with a new ADR instead of editing them.
- `docs/research/` captures: regenerate with the `capture-hook-fixture` skill.
- CI workflows' permissions and pinned action SHAs.

## Conventions

- Python ≥ 3.10, `from __future__ import annotations`, full type hints,
  `mypy --strict` clean, Google-style docstrings on public API.
- Names: modules `snake_case`, classes `PascalCase`, no abbreviations in
  public names. Absolute imports only.
- Commits: Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`,
  `refactor:`, `perf:`, `ci:`, `chore:`). One logical change per PR.
- `CHANGELOG.md`: Keep a Changelog, update `[Unreleased]` for user-visible
  changes. Versioning: SemVer; the version lives in `pyproject.toml`.
- New ADR: copy `docs/adr/template.md` to the next number, add it to
  `docs/adr/README.md` and `mkdocs.yml`, status `proposed`.
- New adapter: a package under `adapters/`, implementing the adapter
  protocol from `docs/design.md` §3.1, with e2e tests on captured payloads.
  Never modify `core` to accommodate one agent.

## Definition of done (PR)

- CI green: lint (pre-commit), tests on Linux + macOS × Python 3.10–3.13,
  core coverage ≥ 90 %, build.
- Tests cover the change; regression test verified for fixes.
- Docs, ADRs and `CHANGELOG.md` updated where relevant.
- PR description: summary, linked issue, list of changes, how it was tested.
