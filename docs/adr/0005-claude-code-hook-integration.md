---
status: accepted
date: 2026-09-23
decision-makers: [nicolasallerponte]
---

# Claude Code integration: synchronous exec-form command hooks on post-tool events

## Context and Problem Statement

We need to observe every workspace-changing step of a Claude Code session,
link it to its user prompt and agent, and never disturb the session. Which
hook events, which handler form and which settings file?

## Decision Drivers

* Correct attribution (snapshot must be taken before the next tool starts).
* Minimal process spawns per tool call.
* Zero visible side effects: no stdout, no non-zero exit, no context injection.
* Reversible, idempotent installation.
* No machine-specific paths committed to shared repositories.

## Considered Options

* Events: `PostToolUse` + `PostToolUseFailure` (+ `SessionStart`, `UserPromptSubmit`, `SessionEnd`) vs. adding `PreToolUse` vs. `PostToolBatch` only vs. `FileChanged`
* Execution: synchronous vs. `async: true`
* Handler: exec form with absolute interpreter vs. shell form vs. `agent-blackbox` on `PATH`
* Default scope: `settings.local.json` vs. `settings.json` vs. user settings
* Distribution: settings entries vs. a Claude Code plugin

## Decision Outcome

* **Events:** `SessionStart`, `UserPromptSubmit`, `PostToolUse`, `PostToolUseFailure`, `SessionEnd`. No `PreToolUse`: `duration_ms` already yields the execution interval. Not `PostToolBatch` alone: it would merge several steps into one. Not `FileChanged`: it only watches configured filenames.
* **Synchronous.** Async hooks would snapshot after Claude may already be running the next tool, and are killed at teardown in `-p` mode (documented).
* **Exec form**, absolute path of the interpreter from the `uv tool` environment, `-I -m agent_blackbox.adapters.claude_code.hook <event>`, plus a marker argument used by `uninstall`.
* **Default scope `local`** (`.claude/settings.local.json`); `project` scope writes the bare `agent-blackbox` command instead of an absolute path.
* **Settings entries now; a plugin later.** A Claude Code plugin (with `hooks/hooks.json` and the product skill) is a better long-term distribution channel and is tracked for v0.2; settings entries are what the requested `install`/`uninstall` UX needs and are easier to reason about for v0.1.
* Read-only tools are excluded by matcher regex; unknown tools (including MCP) are recorded.

### Consequences

* Good, because each mutating tool call costs one process spawn and one snapshot.
* Good, because `prompt_id` and `agent_id` on the payload give attribution without transcript parsing (research F1, F2).
* Bad, because the absolute interpreter path breaks if the tool environment moves; `doctor` detects it and `install` is idempotent to fix it.
* Bad, because the negative-lookahead matcher relies on documented-but-subtle regex semantics; the in-process filter duplicates it as a safety net.

### Confirmation

E2E tests replay captured payload sequences through the real entry point;
a property test asserts `uninstall(install(S)) == S` for arbitrary settings
documents; a test asserts the hook writes nothing to stdout and exits 0 on
malformed input, missing storage, full disk (simulated) and lock timeout.

## More Information

Hooks reference: <https://code.claude.com/docs/en/hooks>. Research payloads:
`docs/research/claude-code-2.1.280/`. Re-verify on every Claude Code minor
upgrade with the `capture-hook-fixture` skill.
