# ADR-0016: Human-selectable specialist dispatch with authorized coverage waivers

**Status:** Accepted
**Date:** 2026-08-13

## Context

`outer-loop-runner` always dispatched all five specialists on every run,
with no way to run a faster, narrower first pass. Discussed directly with
the maintainer: `outer-loop-runner` should present the five as a numbered
list and let a human pick a subset, with the agent free to push back — with
reasoning tied to the actual diff — on a skipped specialist it judges
necessary, but always deferring to human override.

Skipping a specialist leaves its owned coverage dimension(s) permanently
uncovered under the existing gate: `_incomplete_coverage`/
`_effective_coverage` require every dimension to have been established by
*some* round, with no default-pass (ADR-0011, deliberate — "there is no
default-pass" is a direct quote from that ADR's own consequences). Two
resolutions were considered: leave the dimension for a later round (no
schema change), or let a human explicitly waive it. The maintainer chose
the latter, and specified it should be asked **immediately after
specialist selection**, not deferred to whenever `stop_incomplete_coverage`
would otherwise first surface it.

## Decision

### 1. `work.waive()` — modeled on `reopen`, not `record_triage`

Two existing precedents in this codebase have different shapes:
`record_triage` writes into a single per-round slot, guarded against being
set twice; `reopen` appends to a top-level, cross-round list with no such
guard, callable repeatedly across an item's life. A waiver needs the
second shape — callable multiple times, across different dimensions and
different rounds — so `waive(work_item_id, dimension, reason, *, target,
by=None)` appends to a new additive `coverage_waivers` list, each entry
`{timestamp, round, dimension, reason, by}`. `reason` is required non-empty
(`_validate_required_text`, the same rule `reopen`'s `head`/`reason`
already use); `dimension` must be one of `REQUIRED_COVERAGE_DIMENSIONS`.
Exposed as `codev git work waive --id --dimension --reason [--by]`,
`--by` defaulting through `detect_identity` exactly as `reopen`/`triage`
already do.

### 2. Waivers are never recorded as `passed`

A waived entry is `{"waived": True, "reason": ..., "by": ...}` — no
`passed` key. This is deliberate, matching the project's existing "never
silently claim something was verified" discipline (ADR-0008's own phrase):
a dimension nobody ran is not the same claim as a dimension that was
checked and found clean, and every surface that renders coverage —
`codev work log`, `pr_description()`'s Validation section — keeps them
visibly distinct.

### 3. `_effective_coverage` takes the full `state`, not just `rounds`

Signature changed from `_effective_coverage(rounds)` to
`_effective_coverage(state)` (all three call sites in `check()`/
`pr_description()` updated) so it can also read `coverage_waivers`.
Waivers are grouped by the `round` they were recorded at and interleaved
into the same round-ordered merge `_effective_coverage` already performs
(ADR-0011): for each round number in order, that round's waivers are
applied first, then that round's own recorded `reviewer.coverage` is
merged on top — so a real verdict recorded in the *same* round as a waiver
for the same dimension wins (real verification is more authoritative than
a waiver noted in passing), and, across rounds, whichever is more recent
wins, symmetric with how a later real pass already overrides an earlier
one. This means a human can waive something that later turns out to
matter (a subsequent real run overrides it), or waive something that
failed earlier and is later judged not to matter (a subsequent waiver
overrides a stale failure) — both directions work through the one merge
rule. `_incomplete_coverage` treats a waived entry as resolved without
ever treating it as `passed`.

### 4. `outer-loop-runner` step 2 becomes selection, push-back, then waiver — in that order

All four platforms (Codex rewritten in its own condensed style, confirmed
independently paraphrased from the other three before editing — see
ADR-0015's note on the same point): present the five specialists numbered
1–5 with the dimension(s) each owns; accept numbers or `all`. Before
accepting a selection that skips one, weigh it against the actual diff and
say so with reasoning if a skipped dimension looks relevant — the human's
answer wins regardless, including a flat override. **Immediately** once
selection is final — per the maintainer, not deferred — for each dimension
whose specialist wasn't selected, ask once: waive now with a reason, or
leave for later with no schema effect. Only dispatch the selected
specialists; `codev work check`'s existing carry-forward fills in
everything else from history or a waiver.

Section 3 ("Merge and record") no longer assumes all eight dimensions are
covered by the current round's dispatch — the wording now says "whichever
were actually selected this round, not necessarily all eight," matching
the narrow-correction carry-forward language ADR-0010/0011 already
established elsewhere in the same file.

`adapter.py`'s `_REQUIRED_MARKERS["outer-loop-runner"]` gains `"codev work
waive"` alongside its existing three markers.

## Consequences

- No `ROUND_SCHEMA_VERSION` bump: `coverage_waivers` is additive, same
  precedent as `reopens`/`escalations`.
- `pr_description()` (ADR-0014) needed one fix caught by its own test
  suite: its "All N dimensions pass" shortcut originally fired whenever
  `_incomplete_coverage` returned nothing, which is also true when
  everything is waived rather than passed. Now requires every dimension to
  actually be `passed` before using the compact line; anything else
  (including an all-waived manifest) renders the per-dimension breakdown so
  a waiver is never presented as if it had been verified.
- Testing needs (added): `tests/test_work.py::WaiverTests` — empty-reason
  and unknown-dimension rejection, rejection when not `in_progress`,
  `ok_approve` reached with a waived dimension no specialist ever ran,
  a later real verdict overriding an earlier waiver, a later waiver
  overriding an earlier failing verdict, `log_text` rendering. One new
  test in `PrDescriptionTests` for the waived-vs-passed rendering fix
  above. `codev adapter verify` re-run clean for all four platforms
  against the raw bundle after the marker addition. Full release gate
  (`scripts/verify_release.py`) passes.
