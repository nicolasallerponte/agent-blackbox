---
status: accepted
date: 2026-09-23
decision-makers: [nicolasallerponte]
---

# Bisect as a pure search over distinct trees with git-compatible exit codes

## Context and Problem Statement

Given recorded snapshots and a user test command, find the first snapshot
that fails. The algorithm must be deterministic, provably efficient, robust
to untestable states and flaky tests, and testable without git.

## Decision Drivers

* Determinism; no LLM in any decision.
* At most `⌈log₂ n⌉ + 2` test runs without skips/retries.
* Familiar semantics for `git bisect run` users.
* Never report a false culprit for a flaky test.

## Considered Options

* Pure binary search over distinct trees, oracle injected, git exit-code convention
* Delegate to `git bisect run` on the shadow repository
* Linear scan from the end

## Decision Outcome

Chosen option: "Pure binary search over distinct trees", because it is
testable with Hypothesis in microseconds, lets us dedupe identical trees
(many steps don't change anything), and gives us full control over skip,
retry and flaky semantics and the report. Exit codes follow `git bisect run`
exactly (0 good, 125 skip, 1–127 bad, ≥ 128 abort).

Flaky handling: with `--retries N`, any disagreement between runs of the
same tree yields a `flaky` verdict and stops the search; results are cached
per tree so a tree is never re-run outside of retries.

### Consequences

* Good, because the search is a ~100-line pure function with exhaustive property tests.
* Good, because identical trees are evaluated once.
* Bad, because we re-implement skip handling rather than reuse git's; mitigated by property tests (termination, culprit inside reported range).

### Confirmation

Hypothesis properties: for all `n ≤ 512` and culprit `c`, verdict = `c` and
runs ≤ `⌈log₂ n⌉ + 2`; with arbitrary skip sets, termination and the
culprit lies in the reported range; with a flaky oracle and retries ≥ 1,
the verdict is never a culprit that contradicts an observed outcome.

## Pros and Cons of the Options

### `git bisect run` on the shadow repo

* Good, because battle-tested.
* Bad, because it needs a linear commit history per session and checks out into a work tree (we'd need to point it at a worktree), gives us little control over retries/flaky detection and reporting, and its output is not a stable API.

### Linear scan

* Good, because trivial.
* Bad, because O(n) test runs; unacceptable for 100-step sessions with slow test suites.

## More Information

Design §9.
