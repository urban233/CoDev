# ADR-0017: Outer-loop round-recording integrity

**Status:** Accepted
**Date:** 2026-08-13

## Context

Two incidents from the same real outer-loop session, traced against the
actual `work.py` implementation rather than assumed from the documented
protocol, turned out to be one bug wearing two costumes.

**Incident one.** A pre-PR mechanical finding (a stale implementation-plan
`Status:` line) was corrected and re-reviewed. The correction landed at a new
head, but the attempt to record a fresh reviewer verdict targeted the same
round number that already had one recorded. `record_reviewer`'s write-once
guard rejected it -- correctly -- but the round-state's escalation log shows
this reached the human only as a raw `WorkError`, requiring a manually
authorized `codev work reopen` to recover:

> "round 2 already had a reviewer snapshot at f051635...; the fresh reviewer
> found the implementation plan still records the stale f051635 head, and
> codev work record rejected a second reviewer entry. Human-authorized
> reopen is required..."

**Incident two, same session, same work item.** A later, genuine five-
specialist outer-loop pass found six blocking findings, including an SSRF
hole. Recording that round hit `_round_slot`'s
`"READY_FOR_OUTER_LOOP is only a valid transition from the inner phase"`
raise -- because the item's most recently recorded round already carried
that exact decision while its phase was already `"outer"` (a state produced,
legitimately, by the `reopen` that recovered incident one). Rather than
calling `codev work reopen` again -- which *would* have opened a legal new
round, since `reopen()` has no such phase restriction -- the outer-loop
session folded a one-line prose summary of the six findings into a
`reopen`'s free-text `reason` field and moved straight to a correction. The
six structured findings, categories, locations, and blocking status exist
today only in a side-channel `pr-review` cache file, never in
`round-state.json`'s round history. Had the transcript not been saved by
hand, the SSRF finding would be unrecoverable.

Both incidents are the same behavioral bug: an agent needing to record a
reviewer verdict after the outer phase already has one recorded tries to
write onto the already-recorded round instead of opening a new one first.
`reopen()` (ADR-0007) already mechanically solves this -- the gap is that
nothing told the agent to use it, in the right order, both times.

A second, deeper bug enabled incident two specifically: `record_reviewer`
validates `decision in VALID_DECISIONS` but never checks that
`READY_FOR_OUTER_LOOP` is only semantically valid coming from an inner-phase
round. Nothing stopped the reopened round from being recorded with that
decision while already `"outer"` -- silently producing the exact corrupted
shape `_round_slot` then refuses to build on.

ADR-0007 is directly on point here and is not being revisited: "None of this
is a case for loosening the guards themselves... they are what makes the
evidence trail trustworthy." This ADR does not relax `_round_slot`'s
inner-only restriction on that transition -- doing so would legitimize the
exact corrupted state this ADR closes, and would remove the one guardrail
that currently forces a human decision via `reopen` when this state is
reached.

## Decision

### 1. `record_reviewer` rejects the corrupted combination at the write site

`decision == "READY_FOR_OUTER_LOOP"` is now rejected outright when
`round_entry["phase"] != "inner"`, with a `WorkError` naming the three
decisions that are actually legal on an outer-phase round instead. This is
the primary fix: it prevents the corrupted shape from being written again,
at the source, rather than only reacting to it after the fact. Going
forward, an outer-phase round genuinely cannot carry this decision.

### 2. `check()` gains `ok_outer_loop_needs_reopen`, for defense in depth

For any round-state already in the corrupted shape (produced before this ADR,
or reached some other way not yet foreseen), `check()` now recognizes
`decision == "READY_FOR_OUTER_LOOP"` with `latest["phase"] == "outer"` as its
own outcome rather than silently reusing the same `ok_ready_for_pr` string
the normal inner-to-outer hand-off produces. Reusing that string was
misleading: `check()` said "ok" while the very next `record_reviewer` call
would hard-fail. The new outcome's message tells the caller plainly what to
do -- confirm with the human that re-entering is actually intended, not
unexamined drift, then run `codev work reopen` before dispatching anything
further.

Confirmed low blast radius: exactly one caller anywhere in this codebase
pattern-matches a specific `check()` reason string --
`git_ops.py::open_pr`'s eligibility check, `result.reason == "ok_ready_for_pr"
or description["current_phase"] == "outer"`. That check's own phase-based
fallback already covers this exact case (`current_phase` is `"outer"`
whenever the new outcome fires), so `open_pr` eligibility is unaffected by
which of the two reason strings actually returns. No other caller in
`cli.py` or elsewhere branches on anything but `result.ok`.

### 3. Write-once guard messages name the fix

The existing `WorkError` messages on `record_builder`'s and
`record_reviewer`'s write-once guards ("round N already has a recorded
.../reviewer entry") now continue: "...to re-review after a correction,
record a new round instead -- the next sequential round, or `codev work
reopen` if this item is in a terminal state." This is the same information
`ok_outer_loop_needs_reopen` carries, surfaced at the other point an agent
is likely to hit this mistake -- mid-write, not just at the preceding
`check()` call.

### 4. Not resolved by this ADR

A structured `--trigger` vocabulary for `reopen`'s `reason` field (mirroring
`escalate --trigger`), to distinguish "intentional re-entry after a
completed hand-off" from "investigated drift, continuing anyway" in the
audit trail -- both look identical in `round-state.json` today, same fields,
free-text `reason`. Worth doing, flagged directly by this ADR's own design
review, but left out here to keep this change to the one incident class it
actually closes.

## Consequences

- No `ROUND_SCHEMA_VERSION` bump: nothing here changes stored shape, only
  what `record_reviewer` accepts and what `check()` reports for an existing
  shape.
- The outer-loop-runner protocol (all four platforms) needs to actually call
  `codev work check` *before* dispatching specialists, not only after
  attempting to record -- otherwise `ok_outer_loop_needs_reopen` is only ever
  seen after the specialist-dispatch cost incident two was trying to avoid
  losing has already been spent. Landed together with ADR-0018 and ADR-0019's
  own step-1/step-2 prompt changes in one combined edit, not as part of this
  ADR's own change.
- Testing needs: `record_reviewer` rejecting `READY_FOR_OUTER_LOOP` on a
  non-inner-phase round; `check()` returning `ok_outer_loop_needs_reopen` for
  a round-state constructed directly in the corrupted shape (this exact
  combination -- phase `"outer"`, decision `READY_FOR_OUTER_LOOP` -- had no
  existing test coverage before this ADR); `git_ops::open_pr` eligibility
  confirmed unaffected by the new reason string.
