---
name: write-adr
description: Creates a new Architecture Decision Record in MADR format under docs/adr/ with the next free number, fills it from the discussion, and links it from the ADR index and the docs navigation. Use when a decision with real alternatives is made or changed (storage format, concurrency, dependencies, CLI contract, platform support, tooling), or to supersede an accepted ADR.
argument-hint: "[short title]"
---

# Write an ADR

ADRs record *why*. Write one when there were at least two reasonable options.

## Steps

1. **Number.** List `docs/adr/[0-9][0-9][0-9][0-9]-*.md`; the new number is
   the highest plus one, zero-padded to four digits.
2. **File name.** `docs/adr/NNNN-<kebab-case-title>.md`, title in the
   imperative or as the chosen solution ("Serialize recording with flock").
3. **Content.** Copy `docs/adr/template.md` and fill every section:
   - Front matter: `status: proposed`, today's date (`YYYY-MM-DD`),
     `decision-makers: [nicolasallerponte]`.
   - Context and problem statement: two or three sentences, ending with the
     question being decided.
   - Decision drivers: the forces, including invariants from `AGENTS.md`.
   - Considered options: at least two, including the status quo.
   - Decision outcome: the choice and the *because*; consequences as
     "Good, because" / "Bad, because"; a **Confirmation** section saying how
     compliance is checked (test, CI job, lint rule, review rule).
   - Pros and cons per rejected option; links in "More information".
   Use only facts you verified; cite sources (docs URLs, benchmarks, files).
4. **Index.** Add a row to the table in `docs/adr/README.md`.
5. **Navigation.** Add the file under `Decisions` in `mkdocs.yml`.
6. **Supersede, don't edit.** If this replaces an accepted ADR, set the old
   one's status to `superseded by ADR-NNNN` (the only edit allowed on an
   accepted ADR) and link both ways.
7. **Design doc.** If the decision changes behaviour described in
   `docs/design.md`, update the design and link the ADR from it.
8. **Verify.** `uv run --group docs mkdocs build --strict` passes.

The maintainer moves the status to `accepted` when approving the PR.
