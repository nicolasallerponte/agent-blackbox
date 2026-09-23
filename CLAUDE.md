@AGENTS.md

## Claude Code specifics

Skills in `.claude/skills/` (invoke with `/name` or let Claude pick them):

| Skill | Use when |
|---|---|
| `dev-setup` | Setting up a fresh clone or diagnosing a broken dev environment. |
| `write-adr` | Recording an architecture or product decision. |
| `capture-hook-fixture` | Claude Code changed version, or a test needs real hook payloads. |

Subagents in `.claude/agents/`:

| Subagent | Use when |
|---|---|
| `reviewer` | Before opening or merging a PR: checks a diff against `AGENTS.md`. Read-only. |
| `security-auditor` | Changes touch the hook, subprocess calls, redaction or file handling. Read-only. |
| `test-writer` | A bug is described: writes the regression test and proves it fails first. |

Read-only subagents cannot run git. Save the diff to a file first, e.g.
`git diff origin/main...HEAD > "$(mktemp -t pr-XXXXXX.diff)"`, and pass that
path in the prompt.
