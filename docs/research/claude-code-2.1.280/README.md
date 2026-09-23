# Claude Code hook research (Claude Code 2.1.280, 2026-09-23)

Empirical verification backing `docs/design.md`. Everything here was produced
by running a real, nested `claude -p` session (model: Haiku 4.5, Linux,
`--permission-mode acceptEdits`) in a throwaway git repository with a
command hook registered on every relevant event. The hook
(`scripts/dump_hook_payload.py`) writes each stdin payload plus a wall-clock
timestamp to disk.

Payloads were anonymized: absolute paths were rewritten to
`/home/user/project`, `/tmp/claude-0/-home-user-project` and `/opt/probe`.
Session, prompt, tool-use and agent IDs are real random identifiers and carry
no personal data. `_observed_offset_s` is the time the hook process started,
relative to the first event of the run.

These files will be promoted to test fixtures in Phase 3
(`tests/e2e/fixtures/`), via the `capture-hook-fixture` skill.

## Run 1 — sequential tools (`run-1-sequential/`)

Prompt asked for: two parallel `Write` calls in one message, an `Edit`, a
mutating `Bash`, a failing `Bash` (`false`), and a foreground subagent that
writes a file.

## Run 2 — concurrency (`run-2-concurrent/`)

Prompt asked for: three `Bash` calls in one message (two mutating with
`sleep 3`, one read-only `ls`), a *background* subagent running
`sleep 4; echo bg > bg.txt`, and a main-thread `Write` issued right after.

## Findings

| # | Finding | Evidence |
|---|---------|----------|
| F1 | Every tool event carries `session_id`, `prompt_id`, `tool_use_id`, `cwd`, `transcript_path`. `prompt_id` is also on `UserPromptSubmit`, so a step links to the user's message without parsing the transcript. | run-1 `01`, `03` |
| F2 | Tool events fired inside a subagent carry `agent_id` and `agent_type`; the parent's `prompt_id` is inherited. | run-1 `20`, `21` |
| F3 | Mutating tools in one parallel batch are **executed sequentially** (Pre/Post pairs do not overlap): two `Write`s, two mutating `Bash`es. | run-1 `02`–`05`; run-2 `02`–`05` (3 s apart) |
| F4 | Read-only tools may run concurrently with others (`ls` overlapped the `Agent` launch). | run-2 `06`–`10` |
| F5 | A **background subagent runs concurrently with the main thread**: its `Bash` spans 14.9 s → 18.9 s while main-thread tools run. Main-thread snapshots can therefore see a subagent's partial work. | run-2 `17`, `24` vs `18`–`22` |
| F6 | When a background task finishes, Claude Code fires `UserPromptSubmit` again with the **same `prompt_id`** and a synthetic `prompt` starting with `<task-notification>`. The first prompt per `prompt_id` must be kept. | run-2 `33` |
| F7 | A failed `Bash` fires `PostToolUseFailure` (not `PostToolUse`) with `error` starting `Exit code N`. A failing command can still modify files, so this event must snapshot too. | run-1 `16` |
| F8 | `PostToolUse` for `Agent` fires *after* the subagent's own tool events (foreground) or immediately with `status: "async_launched"` (background). | run-1 `24`; run-2 `08` |
| F9 | `CLAUDE_PROJECT_DIR` is exported to hooks and equals the session start directory. | all (`env` captured by the probe, not stored) |
| F10 | `PostToolBatch` fires once per model turn batch, also inside subagents (with `agent_id`). | run-1 `08`, `22` |
| F11 | Transcript JSONL `user` entries carry `promptId`; the first `user` entry with string `content` per `promptId` is the typed prompt (fallback source). | inspected, not stored |
| F12 | A `PostToolUse` matcher `^(?!(Read\|Glob\|Grep\|WebFetch\|WebSearch\|TodoWrite\|ReadNotifications)$)` (JavaScript negative lookahead) spawned the hook for `Write` and `Bash` only; `Read` and `Glob` spawned nothing. | run 3 (not stored; two files observed) |

## Latency prototype (`scripts/snapshot_prototype.py`)

5,000-file repository (50 × 7 directories, 5–200 lines each), 4 vCPU, git
2.43, Python 3.11. One new file per iteration, 40 iterations, each measured
as a fresh `python3` process doing: `flock`, `git add -A` into a private
index, `write-tree`, `rev-parse`, `commit-tree`, `update-ref`.

| Metric | Value |
|--------|-------|
| p50 | 41.7 ms |
| p95 | 45.8 ms |
| max | 46.2 ms |
| bare `python3 -c "import json,sys"` | 17.1 ms |

Conclusion: Python plus plumbing-level git calls fits the 150 ms p95 budget
with roughly 3× headroom on a medium repo.
