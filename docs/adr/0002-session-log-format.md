---
status: accepted
date: 2026-09-23
decision-makers: [nicolasallerponte]
---

# Session log as versioned, append-only JSON Lines, mirrored in commit messages

## Context and Problem Statement

Each snapshot needs metadata: step number, tool, input, agent, turn, time,
status, flags. The log is written by short-lived hook processes, possibly
concurrently, may be interrupted by `SIGKILL`, and is read by the CLI and by
other programs through `--json`. Which format and where?

## Decision Drivers

* Append must be cheap and safe for concurrent writers.
* A crash mid-write must lose at most the record being written, detectably.
* Human-debuggable; no extra dependencies.
* Forward-compatible schema evolution.
* The log must be recoverable if its file is lost or inconsistent.

## Considered Options

* JSON Lines per session (`steps.jsonl`, `turns.jsonl`) + record duplicated as the commit message
* SQLite database
* Git notes / commit messages only
* One JSON file per step

## Decision Outcome

Chosen option: "JSON Lines per session, mirrored in commit messages",
because appends are a single `write(2)` under the project lock, torn writes
are detectable (missing trailing newline) and repairable, and the commit
message copy makes the journal reconstructible from the shadow repository
alone.

Schema rules:

* Every record carries `"v": <int>`; `.agent-blackbox/VERSION` carries the storage version.
* Readers ignore unknown fields and accept every released version.
* Adding optional fields is a minor change; renaming/removing fields or changing semantics is a breaking change requiring a migration, a new `v`, an ADR and a CHANGELOG entry.
* The `--json` CLI output schema is versioned separately (`"schema": "agent-blackbox/<command>/1"`).

### Consequences

* Good, because append is O(1) and needs no dependency or daemon.
* Good, because files can be inspected with `jq`.
* Good, because redundancy (journal + commits) enables automatic repair.
* Bad, because queries (e.g. "all Bash steps across sessions") require a scan; acceptable at expected sizes (≤ 10⁴ steps per session).
* Bad, because two copies must be kept consistent; the repair procedure in design §6.3 defines which one wins (the ref chain).

### Confirmation

Unit tests for parsing with truncated/garbage tail lines; integration tests
that delete or truncate `steps.jsonl` and verify reconstruction; a golden
file test pins the v1 record layout.

## Pros and Cons of the Options

### SQLite

* Good, because transactional and queryable.
* Bad, because `sqlite3` import plus connection and WAL handling costs start-up time in the hook, and concurrent writers from many short processes need careful busy handling.
* Bad, because opaque to casual inspection.

### Commit messages / git notes only

* Good, because single source of truth.
* Bad, because every read requires spawning git and parsing; `log` over long sessions becomes slow.

### One JSON file per step

* Good, because atomic via rename.
* Bad, because thousands of small files, slower listing, more inodes.

## More Information

Design §4.2–4.3.
