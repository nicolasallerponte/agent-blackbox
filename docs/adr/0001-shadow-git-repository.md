---
status: accepted
date: 2026-09-23
decision-makers: [nicolasallerponte]
---

# Store workspace snapshots in a per-project shadow git repository

## Context and Problem Statement

agent-blackbox must capture the full workspace state after every agent step
(including changes made through shell commands), keep dozens to hundreds of
states per session cheaply, materialise any of them for testing, and do all
of that without touching the user's own git history. How should snapshots be
stored?

## Decision Drivers

* Never modify the user's repository, index, refs, stash or hooks.
* Hook latency: p95 < 150 ms on ~5,000 files.
* Disk usage: consecutive states differ by a few files.
* Must work in directories that are not git repositories.
* Fast materialisation of an arbitrary state for bisect.
* Crash safety and concurrent writers.
* No new runtime dependency beyond `git`.

## Considered Options

* Shadow git repository (`GIT_DIR` separate, `GIT_WORK_TREE` = project)
* Commits/refs in the user's own repository (`refs/agent-blackbox/*`, like `git stash create`)
* Per-step file copies of changed files (own content-addressed store)
* Filesystem snapshots (btrfs/ZFS/APFS clones, `cp --reflink`)
* Record tool inputs and replay them

## Decision Outcome

Chosen option: "Shadow git repository", because it reuses git's
content-addressed storage, ignore rules, stat-cache and worktree
materialisation, works with or without a user repository, and keeps the
user's `.git` completely untouched. The prototype measured 46 ms p95 per
snapshot, including Python start-up, on 5,000 files.

### Consequences

* Good, because unchanged files cost nothing (object deduplication across all steps and sessions).
* Good, because `git add -A` with a private per-session index only re-hashes files whose stat data changed.
* Good, because `.gitignore` files in the work tree are honoured for free.
* Good, because `git worktree add --detach` / `read-tree -u` give cheap, incremental materialisation for bisect.
* Good, because the shadow repo is inspectable with plain git for debugging.
* Bad, because ignored files (dependencies, build output) are not captured; bisect needs `--setup` or `--link`.
* Bad, because user git config could leak into shadow operations; mitigated by pinning `-c` options on every call.
* Bad, because nested repositories/submodules are recorded only as gitlinks.
* Bad, because a hard dependency on a `git` binary (≥ 2.25, checked by `doctor`).

### Confirmation

Integration tests assert that the user's `.git` directory is byte-identical
before and after a recorded session (hash of every file under `.git`), and
that snapshots work in a non-git directory.

## Pros and Cons of the Options

### Refs in the user's repository

* Good, because no second object store.
* Bad, because it writes into the user's `.git` (objects, refs, reflogs), which surfaces in `git gc`, backups, GUIs and `git for-each-ref`, and risks interfering with the user's own operations and locks.
* Bad, because it does not work for non-git projects.

### Own content-addressed store of changed files

* Good, because full control of format.
* Bad, because we would re-implement change detection, ignore handling, hashing and materialisation that git already does well and fast.

### Filesystem snapshots / reflinks

* Good, because near-zero cost on supporting filesystems.
* Bad, because not portable (ext4, most macOS setups via tooling, CI), often requires privileges, and still needs a diff mechanism.

### Record and replay tool inputs

* Good, because tiny storage.
* Bad, because shell commands are not replayable deterministically, and replay would execute agent content — a security non-starter.

## More Information

Design §4.1. Revisit if hook latency on large repositories exceeds budget
(fsmonitor integration) or if a second adapter needs non-git capture.
