---
status: accepted
date: 2026-09-23
decision-makers: [nicolasallerponte]
---

# Python ≥ 3.10 with uv, Typer + Rich for the CLI, stdlib-only hook path

## Context and Problem Statement

The tool is installed on developer machines, is invoked by the agent on
every mutating tool call (latency-critical), and has a richer interactive
CLI (latency-tolerant). Which language and CLI framework?

## Decision Drivers

* Hook p95 < 150 ms including interpreter start-up.
* Easy install (`uv tool install`, `uvx`), easy contributions.
* Good testing story (property-based testing, fixtures with real git).
* Readable terminal output and machine-readable `--json`.

## Considered Options

* Python + Typer + Rich
* Python + Click + Rich
* Python + argparse
* Go or Rust single binary

## Decision Outcome

Chosen option: "Python + Typer + Rich", with the rule that **the hook entry
point imports only the standard library** and never imports Typer or Rich.

Measured: bare interpreter start-up 17 ms; full snapshot including start-up
46 ms p95 on 5,000 files. The latency budget is dominated by git, not Python.

Typer over Click: type-annotated commands match our strict typing policy,
Typer is built on Click (so we can drop to Click APIs when needed), and it
integrates with Rich for help output. Its import cost only affects the
interactive CLI.

### Consequences

* Good, because Hypothesis, pytest and mypy give a strong verification story for the core algorithm.
* Good, because contributors can read and extend it easily.
* Good, because distribution via PyPI/uv is simple and supports Trusted Publishing.
* Bad, because the hook pays interpreter start-up (~17–25 ms) on every mutating tool call.
* Bad, because Python ≥ 3.10 must be available; `uv tool install` handles this.

### Confirmation

CI check that importing the hook module does not load any third-party
module; hook latency benchmark gate (design §10).

## Pros and Cons of the Options

### Click + Rich

* Good, because mature and slightly faster import.
* Neutral, because Typer uses Click internally.
* Bad, because more boilerplate and weaker typing of options.

### argparse

* Good, because zero dependencies, fastest import.
* Bad, because poor UX for subcommands and help, more code to maintain.

### Go / Rust binary

* Good, because ~2 ms start-up, single static binary.
* Bad, because the start-up gain (~15 ms) is small relative to git's cost, the requested stack is Python, and the contributor pool for a Python dev-tool is larger.

## More Information

Revisit if hook latency measurements show interpreter start-up dominating
(e.g. a Rust shim that forwards to a warm Python process).
