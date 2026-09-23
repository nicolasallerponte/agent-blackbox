---
status: accepted
date: 2026-09-23
decision-makers: [nicolasallerponte]
---

# Defer native Windows support; run Windows CI as allowed-to-fail

## Context and Problem Statement

Claude Code runs on Windows (with Git Bash or PowerShell). Should v0.1
support Windows?

## Decision Drivers

* Locking relies on `fcntl.flock` (POSIX).
* Process-group management for bisect (`killpg`) is POSIX.
* Windows paths arrive with backslashes in hook payloads (documented).
* Limited maintainer capacity for v0.1.

## Considered Options

* Support Windows in v0.1
* Linux + macOS in v0.1; Windows CI job allowed to fail; decide for v0.2
* Never support Windows

## Decision Outcome

Chosen option: "Linux + macOS in v0.1, Windows CI allowed to fail", because
the three POSIX dependencies above each need a separate, tested
implementation (`msvcrt.locking`, Job Objects, path normalisation), and
shipping them untested would violate "never break the agent". Code keeps
platform-specific parts behind small interfaces (`lock`, `proc`) so Windows
can be added without touching the rest. WSL is supported as Linux.

### Consequences

* Good, because v0.1 scope stays tractable.
* Bad, because native Windows users cannot use v0.1; `install` refuses with a clear message.

### Confirmation

The `windows-latest` CI job runs with `continue-on-error: true` and its
status is reviewed before v0.2 planning.

## More Information

Revisit at the start of milestone v0.2.0.
