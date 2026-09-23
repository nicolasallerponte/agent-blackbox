---
status: accepted
date: 2026-09-23
decision-makers: [nicolasallerponte]
---

# Serialize recording with a per-project flock; detect, don't prevent, concurrent attribution

## Context and Problem Statement

Hooks run as independent processes. Claude Code documents that
`PostToolUse` fires concurrently for parallel tool calls, background
subagents run concurrently with the main thread (verified, research F5), and
several sessions can run in the same project. Hooks can also be killed at any
point. How do we keep the shadow repository and journals consistent and
attribution honest?

## Decision Drivers

* No corrupted snapshots or journals, ever.
* A killed process must never wedge future recording.
* Must not block or slow the agent beyond the latency budget.
* Honest reporting when a step's diff may contain another agent's work.

## Considered Options

* `fcntl.flock` on `.agent-blackbox/lock` with a deadline, total order of snapshots, attribution flags computed from tool intervals
* Lock files created with `O_EXCL` (PID files)
* No global lock; rely on git's own `index.lock` / ref CAS and per-session indexes
* A long-running recorder daemon receiving events over a socket
* Blocking the agent (`PreToolUse`) until concurrent tools finish

## Decision Outcome

Chosen option: "`flock` with deadline + interval-based attribution flags",
because kernel-managed advisory locks disappear with the process that holds
them (no stale-lock recovery needed), they serialize every write so `seq` is
a total order, and attribution ambiguity is surfaced to the user instead of
being hidden or "fixed" by slowing the agent.

Details:

* Lock acquisition polls with a deadline (`snapshot_budget_ms`); on timeout the step is journaled as `dropped` in a best-effort side file and the hook exits 0.
* Write order: objects → commit → `update-ref` with expected old value → journal line. Repairs are listed in design §6.3.
* A step is flagged `concurrent` when its `[end − duration_ms, end]` interval overlaps a step from a different agent, or when an earlier background Bash of the same turn may still be running.

### Consequences

* Good, because no stale locks after `SIGKILL`.
* Good, because simple to reason about and to test by hammering with N processes.
* Bad, because `flock` is unreliable on some network filesystems (NFS); `doctor` warns when `.agent-blackbox/` is on one.
* Bad, because `flock` is POSIX-only; Windows needs `msvcrt.locking` (ADR-0006).
* Bad, because attribution under concurrency stays ambiguous by nature; we report it.

### Confirmation

Integration tests: 16 processes snapshotting concurrently yield a gap-free
`seq`, a consistent ref chain and `git fsck` clean; fault injection kills the
recorder at every write stage and asserts the next run repairs the state.

## Pros and Cons of the Options

### `O_EXCL` lock files

* Good, because portable.
* Bad, because a killed holder leaves a stale lock; PID checks are racy and wrong across PID namespaces/containers.

### Git's own locks only

* Good, because no extra mechanism.
* Bad, because `seq` assignment and journal append are not covered; lock contention surfaces as git errors that we would need to retry.

### Recorder daemon

* Good, because single writer and warm state (faster).
* Bad, because lifecycle management, orphaned daemons and sockets, and much larger attack and failure surface. Revisit only if latency requires it.

### Block the agent in `PreToolUse`

* Good, because exact attribution.
* Bad, because it serializes the agent's work and violates "never slow the agent".

## More Information

Design §6. Research F3–F5.
