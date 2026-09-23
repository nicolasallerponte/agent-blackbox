# Architecture Decision Records

Format: [MADR 4](https://adr.github.io/madr/). Copy [`template.md`](template.md),
use the next free number, and add a row below. Status values: `proposed`,
`accepted`, `rejected`, `deprecated`, `superseded by ADR-NNNN`.

| # | Title | Status |
|---|-------|--------|
| [0001](0001-shadow-git-repository.md) | Store workspace snapshots in a per-project shadow git repository | accepted |
| [0002](0002-session-log-format.md) | Session log as versioned, append-only JSON Lines, mirrored in commit messages | accepted |
| [0003](0003-concurrency-and-crash-safety.md) | Serialize recording with a per-project flock; detect, don't prevent, concurrent attribution | accepted |
| [0004](0004-language-and-cli-framework.md) | Python ≥ 3.10 with uv, Typer + Rich for the CLI, stdlib-only hook path | accepted |
| [0005](0005-claude-code-hook-integration.md) | Claude Code integration: synchronous exec-form command hooks on post-tool events | accepted |
| [0006](0006-windows-support.md) | Defer native Windows support; run Windows CI as allowed-to-fail | accepted |
| [0007](0007-bisect-algorithm.md) | Bisect as a pure search over distinct trees with git-compatible exit codes | accepted |
