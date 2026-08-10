# ADR-0001: `codev work` may run during a build

**Status:** Accepted
**Date:** 2026-08-10

## Context

CoDev's builder/reviewer protocol relied entirely on prose ("stop after two
correction attempts with the same root cause") to bound the number of
correction rounds between the `builder` and `reviewer` subagents. That rule
lives only in `.opencode/agents/orchestrator.md` and its Codex, Junie, and
Antigravity equivalents, and the `reviewer` is deliberately invoked in a
fresh context each round for independence. Nothing tracked how many rounds
had happened or whether a new finding was actually a repeat of an earlier
one, so correction loops could drift instead of converge. Review
"completeness" was similarly unverified: a reviewer could silently skip one
of the seven dimensions in `.agents/skills/review-change/SKILL.md` and
nothing caught the omission.

`docs/architecture.md` stated "No CoDev process runs while product code is
being built" as a purpose-level invariant. That was accurate while CoDev's
only runtime behavior was installing and updating the bundle. It is not
compatible with fixing the convergence and completeness problems above,
which require tracking round state as a build happens rather than
reconstructing it afterward from a transcript.

## Decision

`codev work` becomes a lifecycle command family that may run during a live
build session:

- `codev work start|record|check|close|status|log` read and write only
  `.codev/work/<work-item-id>/round-state.json`.
- They never read or write product source, and never run formatters,
  linters, or tests themselves — those remain the builder's and reviewer's
  responsibility, reported into `work record` as evidence.
- `codev init`, `update`, `remove`, and `diff` retain the original invariant
  unchanged: they never run during a build.

The orchestrator, builder, and reviewer agent definitions (all four
platforms) call `codev work check` before starting a new correction round or
accepting a review as ready for human approval, and treat a nonzero exit
code as a hard stop, not a suggestion.

## Consequences

- "Stop after two attempts with the same root cause" becomes an exit-code
  check instead of a sentence a model has to remember and interpret
  consistently across a fresh-context reviewer invocation.
- Review completeness becomes a structural property of `round-state.json`'s
  coverage manifest rather than an assumption about prompt compliance.
- `docs/architecture.md`'s purpose statement is narrowed, not removed:
  install/update/remove machinery keeps the original guarantee; `work`
  commands carry an explicit, narrower one — state-only, read-only with
  respect to product code.
