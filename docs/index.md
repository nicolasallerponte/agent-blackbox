# agent-blackbox

**A flight recorder for AI coding agents.** agent-blackbox records every step
of a Claude Code session and, when your tests are broken at the end, finds the
exact tool call that broke them — like `git bisect`, but over the agent's
steps instead of commits.

!!! warning "Pre-alpha"
    The design is settled; the implementation is in progress. Nothing is
    published on PyPI yet.

## Principles

- **Deterministic.** No LLM takes part in any decision.
- **Local-first.** No network calls in any code path.
- **Never in the way.** Recording is best-effort; the hook never breaks or
  blocks the agent.
- **Agent-agnostic core.** Claude Code is the first adapter; others can be
  added without touching the core.

## Read next

- [Design](design.md) — what is recorded, how, and how bisect works.
- [Architecture decisions](adr/README.md) — the trade-offs behind the design.
