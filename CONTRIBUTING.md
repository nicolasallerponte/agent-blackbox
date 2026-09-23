# Contributing to agent-blackbox

Thanks for your interest! This project aims to be maintained for years, so
contributions are held to a consistent standard. This guide is for humans;
AI coding agents should read [`AGENTS.md`](AGENTS.md), which is the
authoritative, concise version of the same rules.

## Before you start

- For anything beyond a small fix, open an issue first so we can agree on the
  approach. New agent adapters have their own issue template.
- Read [`docs/design.md`](docs/design.md) and the
  [architecture decision records](docs/adr/README.md). Changes that
  contradict an accepted ADR need a new ADR that supersedes it.

## Development setup

Requirements: [uv](https://docs.astral.sh/uv/), git ≥ 2.25, Linux or macOS.

```sh
git clone https://github.com/nicolasallerponte/agent-blackbox
cd agent-blackbox
uv sync                       # creates .venv with all dev tools
uv run pre-commit install     # same checks as CI, on every commit
uv run pytest                 # full test suite
```

Useful commands:

| Task | Command |
|---|---|
| All checks (as CI) | `uv run pre-commit run --all-files` |
| Tests | `uv run pytest` |
| One file / one test | `uv run pytest tests/unit/test_outcome.py` / `uv run pytest -k name` |
| Coverage | `uv run pytest --cov=agent_blackbox` |
| Types | `uv run mypy` |
| Architecture contracts | `uv run lint-imports` |
| Docs site | `uv run --group docs mkdocs serve` |

## Rules that are not negotiable

1. **The core never depends on adapters or the CLI.** Enforced by
   import-linter.
2. **The hook never breaks the agent.** It catches everything, prints
   nothing on stdout and exits 0.
3. **No network calls**, anywhere. Enforced by lint rules and by running the
   tests with sockets disabled.
4. **No `shell=True`** with anything that could come from the agent.
5. **Every bug fix comes with a regression test** that fails without the fix.
   Say in the PR how you verified that.
6. **Tests first** for core logic.

## Commits and pull requests

- [Conventional Commits](https://www.conventionalcommits.org/):
  `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `perf:`, `ci:`, `chore:`.
  Breaking changes use `!` and a `BREAKING CHANGE:` footer.
- One logical change per PR. Never push to `main`.
- Update `CHANGELOG.md` under `[Unreleased]` for user-visible changes
  ([Keep a Changelog](https://keepachangelog.com/en/1.1.0/)).
- Fill in the PR template, including how you tested the change.
- CI must be green: lint, types, tests on Linux and macOS for Python
  3.10–3.13, core coverage ≥ 90 %, and the build.

## Architecture decisions

Significant decisions are recorded as ADRs in `docs/adr/` using
[MADR](https://adr.github.io/madr/). Copy `docs/adr/template.md` to the next
free number, fill it in, add it to `docs/adr/README.md` and to `mkdocs.yml`,
and open it as `proposed` in your PR.

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).
