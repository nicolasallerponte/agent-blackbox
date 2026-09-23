# agent-blackbox

[![CI](https://github.com/nicolasallerponte/agent-blackbox/actions/workflows/ci.yml/badge.svg)](https://github.com/nicolasallerponte/agent-blackbox/actions/workflows/ci.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/nicolasallerponte/agent-blackbox/badge)](https://scorecard.dev/viewer/?uri=github.com/nicolasallerponte/agent-blackbox)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

**A flight recorder for AI coding agents.** agent-blackbox records every step
of a Claude Code session and, when your tests are broken at the end, finds the
exact tool call that broke them — like `git bisect`, but over the agent's
steps instead of commits.

> **Status: pre-alpha.** The design is settled
> ([`docs/design.md`](docs/design.md)); the implementation is in progress.
> Nothing is published on PyPI yet.

## Why

An agent can make 50–100 changes in one session without a single commit. If
the tests fail at the end, you review everything by hand. Claude Code's
checkpoints let you rewind per prompt, but they don't tell you *which step*
introduced the failure, and they don't capture changes made through Bash.

## How it works

1. **Record.** Claude Code hooks snapshot the workspace after every
   file-changing tool call into a *shadow* git repository inside
   `.agent-blackbox/`. Your own git history is never touched.
2. **Inspect.** List sessions, view the timeline, diff any step, restore any
   step into a separate directory.
3. **Bisect.** `agent-blackbox bisect -- pytest` binary-searches from the
   session's initial state to its last step and reports the culprit: tool,
   input, diff and the user prompt that led to it.

Principles: deterministic (no LLM decides anything), local-first (no network
calls, ever), and the hook never breaks or blocks the agent.

## Documentation

- [Design](docs/design.md)
- [Architecture decision records](docs/adr/README.md)
- [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)

## License

[Apache-2.0](LICENSE)
