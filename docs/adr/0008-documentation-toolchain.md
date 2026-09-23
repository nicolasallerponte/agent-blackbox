---
status: accepted
date: 2026-09-23
decision-makers: [nicolasallerponte]
---

# Documentation toolchain: MkDocs 1.x + Material pinned below 2.0, re-evaluate before v0.1.0

## Context and Problem Statement

The documentation site is built with MkDocs + Material for MkDocs and must
generate `llms.txt` at build time (a plugin). MkDocs 2.0 (pre-release since
2026-08-30) removes the plugin system and is incompatible with Material; the
Material team is building Zensical as a MkDocs 1.x-compatible successor, and
the ProperDocs community fork continues MkDocs 1.x. Which toolchain do we
build on?

## Decision Drivers

* Plugins are required (`llms.txt` generation).
* Stable today; low migration cost later.
* Minimal maintenance for a small project.

## Considered Options

* MkDocs 1.x + Material, pinned `mkdocs<2`, re-evaluated before v0.1.0
* Zensical now
* ProperDocs now
* MkDocs 2.0

## Decision Outcome

Chosen option: "MkDocs 1.x + Material pinned `<2`", because it works today
with every plugin we need, and both successors aim to read the same
`mkdocs.yml`, so switching later is cheap. Zensical is 0.0.x and its plugin
coverage is unverified; MkDocs 2.0 cannot run Material at all.

### Consequences

* Good, because the site builds with a mature, well-known stack.
* Bad, because MkDocs 1.x is unmaintained; a security issue would force an early migration.

### Confirmation

`mkdocs build --strict` runs in CI (`docs.yml`). Before tagging v0.1.0, the
`release` skill checklist asks to re-run this evaluation and supersede this
ADR if a successor is ready.

## More Information

* <https://squidfunk.github.io/mkdocs-material/blog/2026/02/18/mkdocs-2.0/>
* <https://github.com/orgs/ProperDocs/discussions/33>
