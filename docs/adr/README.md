# Architecture Decision Records

One durable, cross-cutting decision per file — a choice later designs and
changes need to find and respect, not a detail local to one change. This is
the same convention `design-solution`'s `assets/adr.template.md` distributes
to every repository that installs CoDev (ADR-0025); this repository practices
it on itself.

## Convention

- **Filename:** `NNNN-slug.md`, `NNNN` a four-digit, zero-padded sequence
  number, one higher than the highest number already present. The first ADR
  is `0001`.
- **Header:** `# ADR-NNNN: <title>`, followed by `**Status:**` and
  `**Date:**`. `**Related design:**` when one exists.
- **Status** is one of `Proposed`, `Accepted`, or `Superseded by ADR-NNNN`
  (linking to the ADR that replaced it).
- **Append-only once `Accepted`.** Never edit a past ADR's `Context` or
  `Decision` to reflect new information — write a new ADR and mark the old
  one superseded instead. This directory is a record of what was decided and
  when, not a living document.
- **Sections:** `Context`, `Decision`, `Alternatives considered` (when
  genuine ones existed), `Consequences`. `Revisit when` is optional — name
  the condition that should reopen the decision if one is known.

Numbers are not reused, including for a proposal later abandoned before
acceptance — the number still records that the question was raised and when.
