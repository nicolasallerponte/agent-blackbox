# agent-blackbox — Design

- **Status:** Accepted (Phase 0 review, 2026-09-23)
- **Date:** 2026-09-23
- **Verified against:** Claude Code 2.1.280, git 2.43, Python 3.11

This document describes what agent-blackbox records, how it stores it, how the
bisect works and which guarantees hold. Decisions with real alternatives are
recorded as ADRs in [`docs/adr/`](adr/README.md); this document links to them
rather than repeating the trade-offs.

**Naming.** The project was first drafted as `agent-bisect`. That name is
already used by an unrelated project (counterfactual replay for LLM agents,
<https://github.com/kidus-der/agent-bisect>), so it is `agent-blackbox`:
PyPI distribution `agent-blackbox`, import package `agent_blackbox`, command
`agent-blackbox`, storage directory `.agent-blackbox/`, environment variables
`AGENT_BLACKBOX_*`. Bisecting is one subcommand: `agent-blackbox bisect -- CMD`.

## 1. Goals and non-goals

**Goals**

1. Record every workspace-changing step of a coding-agent session with
   enough metadata to explain it: tool, input, agent, user prompt, time.
2. Given a test command, find the first step whose workspace state fails it,
   with `git bisect run` semantics.
3. Never slow down or break the agent. Recording is best-effort; the user's
   work comes first.
4. Deterministic and local: no network, no LLM, same inputs → same verdict.
5. Agent-agnostic core; Claude Code is the first adapter.

**Non-goals (v0.1)**

- Capturing side effects outside the project directory (databases, other
  directories, network services, running processes).
- Replaying the agent or its model calls. We bisect *workspace states*, not
  conversations.
- Automatically fixing the culprit step. The product skill helps the agent
  do that; the core only reports.
- Windows as a supported platform (see [ADR-0006](adr/0006-windows-support.md)).

## 2. Research: Claude Code hooks

Sources read (2026-09-23):

- Hooks reference — <https://code.claude.com/docs/en/hooks>
- Hooks guide — <https://code.claude.com/docs/en/hooks-guide>
- Settings — <https://code.claude.com/docs/en/settings>
- Memory / `CLAUDE.md` imports / `AGENTS.md` — <https://code.claude.com/docs/en/memory>
- Skills — <https://code.claude.com/docs/en/skills>
- Subagents — <https://code.claude.com/docs/en/sub-agents>
- Checkpointing — <https://code.claude.com/docs/en/checkpointing>

Empirical verification: [`docs/research/claude-code-2.1.280/`](research/claude-code-2.1.280/README.md)
holds real payloads captured from a nested Claude Code session and the
latency prototype. Findings are referenced below as F1…F12.

### 2.1 What the documentation guarantees

| Topic | Documented behaviour | Consequence for us |
|---|---|---|
| Configuration | `hooks.<Event>[].matcher` + `hooks[]` handlers in `~/.claude/settings.json`, `.claude/settings.json`, `.claude/settings.local.json`. Entries from all levels **merge**; identical handlers in several files run once. | `install` edits exactly one file and can identify its own entries. |
| Handler form | `type: "command"`; with `args` it is **exec form** (no shell), otherwise `sh -c`. | We use exec form: no quoting bugs, no shell. |
| Matcher | Letters, digits, `_`, `-`, `,`, `\|` and spaces → exact list; anything else → unanchored JavaScript regex. | A negative-lookahead regex excludes read-only tools without spawning a process (verified, F12); in-process filtering duplicates it as a safety net. |
| Input | JSON on stdin. Common fields: `session_id`, `prompt_id` (≥ 2.1.196), `transcript_path`, `cwd`, `permission_mode`, `hook_event_name`, plus `agent_id`/`agent_type` inside subagents. | F1, F2 confirm. |
| Exit codes | 0 = success. 2 = blocking error on blocking events. Any other code = **non-blocking error, shown to the user as a "hook error" notice**. stdout on exit 0 is parsed as JSON if it looks like JSON, and for `SessionStart`/`UserPromptSubmit` plain stdout is **injected into Claude's context**. | Hook must always exit 0 and print nothing on stdout. |
| Timeouts | Default 600 s for command hooks, 30 s on `UserPromptSubmit`, 1.5 s shared budget on `SessionEnd`. A timed-out hook is cancelled, not blocking. | We set our own `timeout` and keep an internal budget far below it. |
| Sync vs async | Hooks block until done unless `async: true`. Async hooks are killed at teardown in `-p` mode. | Snapshots must be **synchronous**: an async snapshot would race the next tool call and misattribute changes. |
| Parallel tool calls | `PostToolUse` "fires concurrently when Claude makes parallel tool calls"; `PostToolBatch` fires once per batch. | Snapshots need a lock. In practice mutating tools ran serially (F3), but background subagents are truly concurrent (F5). |
| Subagents | Tool events inside subagents fire the same hooks and carry `agent_id`/`agent_type`. Subagents run in the background by default since 2.1.198. | Per-step agent attribution is free; concurrency with the main thread is the norm, not an edge case. |
| `CLAUDE_PROJECT_DIR` | Project root where the session started; stays put when Claude `cd`s or enters a worktree (`cwd` follows Claude). | The recorded work tree is `CLAUDE_PROJECT_DIR`, never `cwd`. |
| Bash diffs | `tool_response.bashEditDiff` exists (≥ 2.1.269) but is best-effort, beta, capped, and only in some modes. | Not used for correctness; our snapshot is the source of truth. |
| Checkpointing | Captures state per user prompt; does **not** track Bash changes; usually not subagent edits; not external edits. | Our differentiator; see the README comparison. |

### 2.2 What we verified empirically

See the findings table in the research README. The ones that shape the
design:

- **F1** `prompt_id` on every tool event → step-to-prompt linking without
  parsing the transcript. The transcript (`promptId` on `user` entries, F11)
  remains a fallback for sessions recorded before a `UserPromptSubmit` hook
  was installed.
- **F5** background subagents overlap main-thread tools → concurrency must be
  modelled and reported, not assumed away.
- **F6** synthetic `UserPromptSubmit` events (`<task-notification>`) reuse
  the `prompt_id` → keep the *first* prompt per `prompt_id`; mark later ones
  as synthetic.
- **F7** failed tools fire `PostToolUseFailure` → snapshot there too.

## 3. Architecture

```
┌──────────────────────────── adapters/claude_code ─────────────────────────────┐
│ hook entry (stdlib only)  install/uninstall/doctor   transcript reader        │
│   parse payload → core.Event                                                  │
└───────────────┬───────────────────────────────────────────────────────────────┘
                │ core API (no knowledge of Claude Code)
┌───────────────▼──────────────────────── core ─────────────────────────────────┐
│ recorder      : Event → snapshot + log record, crash recovery                 │
│ shadow        : shadow git repo (plumbing via subprocess, no shell)           │
│ journal       : per-session append-only JSONL, schema-versioned               │
│ lock          : inter-process lock with timeout                               │
│ redact        : secret redaction for anything persisted as metadata           │
│ bisect        : pure search algorithm (no I/O) + runner (worktrees, setup)    │
│ store         : read model: sessions, steps, diffs, restore                   │
└───────────────▲───────────────────────────────────────────────────────────────┘
                │
┌───────────────┴──────────── cli (typer + rich, lazily imported) ──────────────┐
│ install uninstall doctor sessions log show restore bisect gc (--json on all) │
└───────────────────────────────────────────────────────────────────────────────┘
```

Import rules (enforced by an import-linter contract in CI):

- `core` imports nothing from `adapters` or `cli`.
- `adapters.*` import `core`, never `cli` and never each other.
- `cli` imports `core` and `adapters` through a registry.
- The hook entry module imports only the standard library and
  `core.recorder`'s dependency closure, which is itself stdlib-only.

### 3.1 The adapter contract

An adapter translates agent-specific events into core events and owns the
agent's configuration files. The core sees only:

```python
@dataclass(frozen=True)
class StepEvent:            # something may have changed the workspace
    session_id: str
    agent: AgentRef         # id + type; None for the main agent
    turn_id: str | None     # adapter's notion of a user turn (prompt_id)
    tool: str
    tool_input: Mapping[str, object]
    ok: bool                # tool succeeded
    started_at_ns: int | None
    ended_at_ns: int

@dataclass(frozen=True)
class TurnEvent:            # user submitted a prompt
    session_id: str
    turn_id: str
    prompt: str
    synthetic: bool         # e.g. <task-notification>

@dataclass(frozen=True)
class SessionEvent:         # start / resume / end
    session_id: str
    kind: Literal["start", "resume", "end"]
```

plus a `WorkspaceRef` (project root). Adapters implement a small `Adapter`
protocol (`name`, `install`, `uninstall`, `diagnose`, `parse_hook(argv,
stdin) -> Event | None`). A second adapter (OpenCode, Aider, Codex CLI) adds a
package under `adapters/` and a registry entry; nothing in `core` changes.

## 4. Storage layout

Everything lives in `<project>/.agent-blackbox/` ([ADR-0001](adr/0001-shadow-git-repository.md),
[ADR-0002](adr/0002-session-log-format.md)):

```
.agent-blackbox/
├── VERSION                       # storage format version ("1")
├── config.toml                   # optional user config (limits, excludes)
├── shadow.git/                   # bare git repo, GIT_WORK_TREE = project root
│   ├── info/exclude              # our excludes + a copy of the user's
│   ├── index-<session>           # one private index per session
│   └── refs/agent-blackbox/sessions/<session>   # chain of step commits
├── sessions/<session>/
│   ├── steps.jsonl               # append-only step records
│   ├── turns.jsonl               # append-only prompt records (redacted)
│   └── meta.json                 # adapter, project root, started/ended
├── lock                          # inter-process lock file
└── logs/hook-errors.log          # rotating, capped
```

When the project is a git repository, `install` and the first recording add
`/.agent-blackbox/` to the file returned by
`git rev-parse --git-path info/exclude` (works for worktrees). The user's
`.gitignore` is never touched.

### 4.1 Snapshots (shadow repo)

A snapshot is the tree of the project root as git would see it, taken with
plumbing only, under the lock:

```
GIT_DIR=.agent-blackbox/shadow.git GIT_WORK_TREE=<root> GIT_INDEX_FILE=…/index-<session>
git add -A --ignore-errors -- .
git write-tree                         → T
if T == tree(previous step): record step with changed=false, no commit
git commit-tree T -p <prev> -F <msg>   → C      (msg = step record JSON)
git update-ref refs/agent-blackbox/sessions/<s> C <prev>   (compare-and-swap)
```

- The user's `.git` is never read or written; the user's `.gitignore` files
  apply naturally because they live in the work tree. The user's
  `info/exclude` is copied into ours at session start.
- Non-git projects work the same way. A built-in default exclude list
  (`node_modules/`, `.venv/`, `__pycache__/`, `.env*`, …) applies only when
  the project has no `.gitignore`.
- Objects are shared by all sessions of the project, so unchanged files cost
  nothing (git deduplication). `doctor` reports `count-objects -vH`.
- Git configuration used by the shadow repo is pinned per invocation
  (`-c core.autocrlf=false -c core.safecrlf=false -c core.untrackedCache=true
  -c gc.auto=0 -c commit.gpgSign=false`), so the user's global config cannot
  change snapshot content or trigger signing prompts.

**Limits** (all configurable in `config.toml`):

| Limit | Default | Behaviour when exceeded |
|---|---|---|
| `max_file_size` | 10 MiB | Untracked-in-shadow files above it are added to a session-local exclude and listed in the step record (`skipped_large`). |
| `max_files` | 100 000 | Recording is disabled for the session with one warning in `doctor`; the agent is unaffected. |
| `snapshot_budget_ms` | 2 000 | If lock wait + snapshot exceeds it, the step is recorded as `dropped` (no tree). Bisect treats dropped steps as merged into the next one. |
| Ignored files | not captured | Documented; `include_ignored` globs opt specific paths back in. |

Nested git repositories and submodules inside the project are recorded as
gitlinks only (their content is not captured) — known limitation.

### 4.2 Step records

`steps.jsonl`, one JSON object per line, UTF-8, `\n`-terminated
([ADR-0002](adr/0002-session-log-format.md)):

```json
{"v":1,"seq":23,"kind":"tool","session":"e083…","turn":"1bc0…",
 "agent":{"id":"a2884005c5630a9a9","type":"general-purpose"},
 "tool":"Edit","input":{"file_path":"src/app.py","old_string":"…","new_string":"…"},
 "ok":true,"started_ns":…,"ended_ns":…,"commit":"9f1c…","tree":"4b2e…",
 "parent":"77aa…","changed":true,"skipped_large":[],"flags":[]}
```

- `seq` is a per-session monotonically increasing step number assigned under
  the lock. Step 0 is the baseline (`kind: "baseline"`).
- `kind` ∈ `baseline | tool | external | dropped | recovered`.
  `external` snapshots are taken at `UserPromptSubmit` and session resume, so
  edits the *user* made between turns are not blamed on the agent's next step.
- `input` is redacted (§7) and large string fields (`content`,
  `new_string`, …) are truncated to 4 KiB with a SHA-256 of the original;
  the full content is in the snapshot anyway.
- File paths inside the project are stored relative to the root; paths
  outside it are kept absolute and the step gets flag `outside_project`.
- `flags` may include `concurrent` (computed at read time, §6),
  `background_bash` (`run_in_background: true`), `outside_project`.
- The same record is written as the commit message, so the log can be
  rebuilt from the shadow repo alone.

`turns.jsonl` stores `{v, turn, prompt, synthetic, at_ns}`; only the first
non-synthetic prompt per `turn` is authoritative (F6).

### 4.3 Compatibility

`VERSION` and the per-record `v` field version the format. Readers accept
all known versions; writers write the current one. Changing the format after
v0.1.0 requires a migration and an ADR (listed under "do not touch without
asking" in `AGENTS.md`).

## 5. Claude Code adapter

### 5.1 Registered hooks

| Event | Matcher | Action | Budget |
|---|---|---|---|
| `SessionStart` | all | Init storage if needed, repair (§6.3), refresh excludes; `startup`/`clear`/`fork` → baseline snapshot; `resume`/`compact` → `external` snapshot if tree changed. | 5 s |
| `UserPromptSubmit` | — | Store prompt (redacted, first per `prompt_id`); `external` snapshot if tree changed. | 5 s |
| `PostToolUse` | not read-only | `tool` snapshot. | 10 s |
| `PostToolUseFailure` | not read-only | `tool` snapshot (`ok: false`) — failing commands still change files (F7). | 10 s |
| `SessionEnd` | — | Final `external` snapshot, mark session ended. | ≤ 1.5 s |

The read-only set (`Read`, `Glob`, `Grep`, `WebFetch`, `WebSearch`,
`TodoWrite`, `AskUserQuestion`, `ExitPlanMode`, `ReadNotifications`, task
tools, …) is excluded by a regex matcher so no process is spawned for them.
Unknown tools, including all MCP tools, **are** snapshotted: missing a
change is worse than a no-op snapshot, and unchanged trees cost only the
`add`/`write-tree` time. The in-process filter duplicates the list so a
matcher regression cannot make things wrong, only slower.

We deliberately do **not** hook `PreToolUse`: `duration_ms` on
`PostToolUse*` gives the execution interval (it excludes permission prompts
and PreToolUse hooks), which is all the concurrency analysis needs, and it
saves one process spawn per tool call.

### 5.2 Invocation

Exec form, absolute interpreter path, no shell
([ADR-0005](adr/0005-claude-code-hook-integration.md)):

```json
{"type": "command",
 "command": "/home/u/.local/share/uv/tools/agent-blackbox/bin/python",
 "args": ["-I", "-m", "agent_blackbox.adapters.claude_code.hook", "post-tool-use"],
 "timeout": 10}
```

- `-I` isolates from `PYTHONPATH`, user site and the project's own modules.
- `install` refuses to write hooks pointing into an ephemeral `uvx` cache and
  tells the user to `uv tool install agent-blackbox` first.
- Every hook entry carries a marker (`"statusMessage"` is user-visible, so
  the marker is the argument `--managed-by=agent-blackbox/1`) that lets
  `uninstall` remove exactly our entries.

### 5.3 Install scopes

| Scope | File | Default |
|---|---|---|
| `local` | `<project>/.claude/settings.local.json` | **yes** |
| `project` | `<project>/.claude/settings.json` | no — warns that a machine-specific absolute path would be committed; uses bare `agent-blackbox` from `PATH` instead |
| `user` | `~/.claude/settings.json` | no |

Install algorithm: read JSON (tolerating a missing file), back up to
`<file>.agent-blackbox.bak.<timestamp>`, remove any previous entries carrying
our marker, append ours, write atomically (temp file + `os.replace`),
preserve key order and 2-space indentation. `uninstall` removes marked
entries, and removes containers (`hooks.<Event>` arrays, `hooks`) only if we
created them and they are now empty. Round-trip property test: for any
settings document `S`, `uninstall(install(S)) == S` as JSON values. JSON
with comments (JSONC) is not accepted by Claude Code either, so it is
rejected with a clear error.

`install --with-skill` copies `product-skill/agent-blackbox/` to the matching
skills directory (`.claude/skills/` or `~/.claude/skills/`); `uninstall`
removes it only if unmodified (hash check).

### 5.4 The "never break the agent" contract

The hook entry point:

1. Wraps everything in `try/except BaseException`.
2. Never writes to stdout (stdout would become Claude context on
   `SessionStart`/`UserPromptSubmit`) and never exits non-zero (non-zero
   shows a "hook error" notice). `sys.stdout` is closed on entry.
3. Logs internal errors to `.agent-blackbox/logs/hook-errors.log` (capped at
   1 MiB, one rotation); if even that fails, it gives up silently.
4. Enforces its own budget with lock-acquire timeouts and subprocess
   timeouts well below the configured hook `timeout`.
5. Honors `AGENT_BLACKBOX_DISABLE=1` and a `.agent-blackbox/disabled` file.

## 6. Concurrency and crash safety

([ADR-0003](adr/0003-concurrency-and-crash-safety.md))

### 6.1 Lock

One lock per project, `.agent-blackbox/lock`, taken with `fcntl.flock`
(exclusive, polled with a deadline). `flock` is released by the kernel when
the process dies, so a killed hook cannot leave a stale lock. Everything
that mutates the shadow repo or a journal happens under it: tree snapshot,
commit, ref update, journal append, `seq` assignment.

This gives a **total order** of snapshots per project even with parallel
tool calls, concurrent subagents and several simultaneous sessions. Sessions
use separate indexes and refs, so they never corrupt each other; they only
queue behind the same lock (tens of ms).

### 6.2 Attribution under concurrency

A snapshot records the full tree at the moment the step's `PostToolUse`
fires. If another tool was executing at that moment (a background subagent,
F5, or a `run_in_background` Bash), part of its effect may land in this
step's diff. We cannot prevent that without blocking the agent, so we
**detect and report** it:

- Each step has an interval `[ended − duration_ms, ended]`.
- At read time, step *k* is flagged `concurrent` if its interval overlaps
  the interval of a step from a different `agent.id`, or if a
  `background_bash` step of the same session precedes it within the same
  turn.
- The bisect report shows concurrent co-suspects next to the culprit and
  says the attribution is ambiguous. The *tree* verdict remains exact: the
  first failing snapshot is still the first failing snapshot.

### 6.3 Crash recovery

Write order per step: objects → commit → `update-ref` (CAS on the old
value) → journal append (single `write` of one line). Invariants and repairs,
run at `SessionStart` and lazily when the lock is taken:

| Crash point | State found | Repair |
|---|---|---|
| During `git add` / `write-tree` | Stale `index-<s>.lock`; loose unreferenced objects | Remove the index lock (we hold `flock`, so nobody else owns it); objects are garbage for `gc`. |
| After `commit-tree`, before `update-ref` | Unreferenced commit | Nothing to do. |
| After `update-ref`, before journal append | Ref head not in journal | Append a `recovered` record parsed from the commit message. |
| During journal append | Last line truncated (no `\n`) | Truncate to the last complete line; the ref-vs-journal check re-adds it. |
| Corrupt index file | `git` error reading index | Delete the session index; next `add -A` rebuilds it (slower once). |

Readers tolerate a trailing partial line. `doctor` runs `git fsck
--connectivity-only` on the shadow repo and reports sessions whose journal
and ref disagree.

## 7. Security and privacy

Full threat model in `SECURITY.md` (Phase 1). Design constraints:

- **No network** in any code path. CI runs the test suite with a socket
  guard (`pytest-socket`) and a static check that no module imports
  `urllib.request`, `http.client`, `socket`, `requests`, … outside tests.
- **No shell with agent content.** Every subprocess is an argument vector.
  The only shell execution in the product is the user's own `--setup` and
  test command, which the user typed; `bisect -- CMD…` executes the vector
  directly, and `--setup` is split with `shlex` unless `--shell` is given.
- **Redaction** of everything persisted as metadata (`input`, prompts),
  before it touches disk. Patterns: provider tokens (Anthropic, OpenAI,
  GitHub, GitLab, Slack, Stripe, AWS access key IDs, Google API keys, npm,
  PyPI), `Authorization:`/`Bearer` headers, JWTs, PEM private-key blocks,
  credentials in URLs (`scheme://user:pass@host`), `KEY=value` assignments
  where the key matches `(?i)(secret|token|password|passwd|api[_-]?key|private[_-]?key)`.
  All regexes are linear-time by construction (no nested quantifiers, no
  overlapping alternations under `*`, bounded repetition), inputs are capped
  at 64 KiB per string before matching, and a test asserts that each
  pattern processes adversarial 64 KiB inputs in < 50 ms.
- **Snapshots contain file contents.** If a secret sits in a non-ignored
  file, it is in the shadow repo, exactly as it is in the work tree. This is
  an accepted risk, documented: `.agent-blackbox/` is local, excluded from
  git, and created with mode `0700`.
- **Restore never overwrites** the work tree without `--in-place --yes`.
- **Hook input is untrusted**: schema-validated, size-capped (stdin read is
  limited to 16 MiB), unknown fields ignored.

## 8. Inspection CLI

| Command | Behaviour |
|---|---|
| `sessions` | Sessions in this project: id, start/end, steps, changed steps, agents, disk use. |
| `log [SESSION]` | Timeline: `seq`, time, agent, tool, one-line input summary, `+/-` stats, flags. Default session = most recent. |
| `show STEP` | Record, full (redacted) input, user prompt of its turn, diff vs previous snapshot (`--stat`, `--name-only`). |
| `restore STEP [--to PATH]` | Materialises the step's tree into a new directory (default `.agent-blackbox/restore/<s>-<seq>/`) via `git worktree add --detach`. `--in-place` requires `--yes` and refuses if the work tree changed since the last snapshot. |
| `gc [--older-than 30d]` | Deletes session journals and refs, then `git gc --prune=now` on the shadow repo. |

`STEP` accepts `seq` (session defaults to latest), `SESSION:seq`, or a
commit prefix. Every command supports `--json` with a documented,
versioned schema; human output goes through `rich` to stderr-safe consoles.

## 9. Bisect

### 9.1 Candidates

Take the session's snapshots in `seq` order, drop `changed: false` and
`dropped` records (their tree equals — or is subsumed by — a neighbour) and
collapse runs of identical trees. The result is a list of distinct trees
`T0 … Tn`, each with its originating step(s). Defaults: `good = T0` (the
baseline), `bad = Tn`. `--good`/`--bad` accept step references.
`external` steps are candidates too: if the user's own edit broke the tests,
the report says so.

### 9.2 Algorithm

A pure function over an oracle, no I/O ([ADR-0007](adr/0007-bisect-algorithm.md)):

1. Evaluate `good`; if not GOOD → stop: "good step is not good".
2. Evaluate `bad`; if not BAD → stop: "bad step is not bad".
3. Binary search on the open interval: `lo` = last known good, `hi` = first
   known bad. Probe `mid = (lo + hi) // 2`.
4. SKIP (exit 125): mark untestable and probe the nearest untested index to
   `mid`, alternating sides (same strategy as git's skip handling).
5. Terminate when `hi = lo + 1` (culprit = `hi`) or when every index in
   `(lo, hi)` is skipped (report the ambiguous range).

Without skips and retries, the number of test runs is at most
`⌈log₂ n⌉ + 2` (two endpoint verifications plus the search). A Hypothesis
property test checks that bound and correctness for every `n` ≤ 512 and
every culprit position, and checks termination and "culprit is always inside
the reported range" with arbitrary skip sets.

Exit-code mapping (identical to `git bisect run`): `0` good; `125` skip;
`1–127` except 125 bad; `≥ 128` (including death by signal) aborts the whole
run with the step and code reported.

### 9.3 Flaky tests

`--retries N` evaluates each probe up to `N+1` times and stops early once
results disagree. Any disagreement makes the verdict `FLAKY` for that step
and aborts the search with a "flaky" report listing the observed outcomes.
With `N = 0` (default) the search additionally re-checks the final pair
(`culprit−1` good, `culprit` bad) once more only if `--confirm` is given.
The oracle cache guarantees that the same tree is never re-evaluated outside
of retries.

### 9.4 Execution environment

- Each probe materialises its tree with `git worktree add --detach` into
  `.agent-blackbox/bisect/<run-id>/wt-<seq>/`, runs optional `--setup`, then
  the test command with `cwd` = worktree, `env` + `AGENT_BLACKBOX_STEP`,
  `AGENT_BLACKBOX_TREE`. Worktrees are reused across probes by checking out
  the next tree in place (`git read-tree -u --reset`), which touches only
  changed files and keeps build caches warm.
- Process hygiene: each command runs in its own process group with a
  `--timeout` (default none); on timeout or Ctrl-C the whole group is
  killed (`SIGTERM`, then `SIGKILL` after 5 s). A timeout counts as SKIP
  unless `--timeout-is-bad`.
- **Dependencies** (ignored directories such as `node_modules`, `.venv`)
  are not in snapshots. Options, documented with trade-offs:
  1. `--setup "npm ci"` — correct, slow (runs per probe; with worktree reuse
     only when the lockfile changed: `--setup-if-changed package-lock.json`).
  2. `--link node_modules --link .venv` — symlink the live project's
     directories into the worktree. Fast; wrong if the agent changed
     dependencies during the session. The report warns when a linked
     path's manifest/lockfile differs between probe tree and live tree.
  Default: neither; the test command is run as is.
- Cleanup: worktrees are removed and pruned at the end; stale run
  directories from killed runs are removed by the next `bisect` or `gc`.

### 9.5 Report

Human and `--json`:

- verdict: `culprit | range | flaky | good-not-good | bad-not-bad | aborted`
- culprit step: `seq`, agent, tool, redacted input, diff (`--stat` plus
  patch, truncated in human output), timestamps, flags
- user prompt that started its turn (from `turns.jsonl`, falling back to the
  transcript by `promptId`)
- co-suspects when `concurrent`
- skipped steps, every probe with exit code and duration, total time.

## 10. Performance

- Budget: hook p95 < 150 ms on ~5,000 files. Prototype: 46 ms p95
  (research README).
- The hook path imports only stdlib; a CI test fails if importing the hook
  module pulls in `typer`, `rich` or any third-party module
  (`python -X importtime` check).
- `benchmarks/hook_latency.py` builds a reproducible 5,000-file repository
  (seeded), replays 200 captured payloads through the real entry point and
  prints p50/p95/p99; CI fails above 150 ms p95 on Linux runners (macOS
  reported, threshold 250 ms because runner I/O is slower).
- Large repositories: `core.untrackedCache` is enabled; `fsmonitor` is
  opt-in via config because it spawns a daemon.

## 11. Test plan

| Layer | What | Where |
|---|---|---|
| Unit | Bisect search (Hypothesis), redaction patterns + ReDoS timing, journal parsing/repair, settings merge round-trip (Hypothesis over JSON documents), payload parsing | `tests/unit/` |
| Integration | Real git in `tmp_path`: snapshot/dedup, ignored & large files, non-git projects, nested repos, concurrent writers (N processes hammering the recorder), crash injection by `SIGKILL` at each stage via a fault-injection env var, restore, gc | `tests/integration/` |
| End-to-end | Replay captured Claude Code payload sequences (from `docs/research`) through the real hook executable against a scripted workspace; full `bisect` on `examples/demo-session/` (bug at step 23 of 40) | `tests/e2e/` |
| Benchmarks | Hook latency, snapshot size on long sessions | `benchmarks/` |
| Live (manual, pre-release) | Real Claude Code session with `install --with-skill`, via the `dev-setup` skill | documented checklist |

Every bug fix lands with a regression test shown to fail without the fix.
Coverage gate: ≥ 90 % lines+branches on `core/`.

## 12. Known limitations (to be mirrored in README)

- Side effects outside the project root (other directories, databases,
  services, global installs) are not captured.
- Ignored files (dependencies, build output) are not captured; bisect may
  need `--setup`/`--link`.
- Concurrent agents can blur per-step attribution; this is flagged, not
  hidden.
- Subagents using `isolation: worktree` edit a different directory; their
  steps are recorded but flagged `outside_project`, and their changes only
  appear once merged back into the project root.
- Files changed by a background process after its Bash call returned are
  attributed to the next snapshot.
- Nested git repositories/submodules are captured as pointers only.
- Linux and macOS only for v0.1.

## 13. Open questions for the maintainer

Tracked in the Phase 0 summary; answers will be folded into this document.
