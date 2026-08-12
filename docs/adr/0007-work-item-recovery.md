# ADR-0007: Work items gain a human-authorized recovery path

**Status:** Accepted
**Date:** 2026-08-12

## Context

A work item could become permanently stuck with no supported way forward,
even though nothing about the underlying code was wrong. Three converging
causes, found by tracing a real session transcript against the actual
`work.py`/`cli.py` implementation rather than assuming the bundle's
documented protocol matched its own state machine:

1. **`builder.md`'s evidence-recording instruction ran before the fact it
   recorded existed.** Every platform's `builder` agent was told to call
   `codev work record --role builder --head <head-sha>` before returning,
   but `builder`'s permission block denies `git commit*` — only
   `orchestrator` commits, and only after the builder returns
   (`orchestrator.md` step 6). The only head that exists at the moment
   `builder` records is therefore the pre-existing base commit, not the head
   its own uncommitted changes will produce. The instant `orchestrator`
   commits afterward, `codev work check` compares the real HEAD against that
   now-stale recorded snapshot and returns `stop_drift` — not on some
   misuse, but on the first round of every ordinary work item that followed
   the documented sequence literally.
2. **The pre-PR `code-audit` gate's correction round was undocumented past
   the point it actually lands.** `code-audit.md.template` and
   `orchestrator.md` both described a `code-audit` finding routing back to
   `builder` "under the inner loop's existing round cap." That is
   mechanically false: `_round_slot` (`work.py`) unconditionally transitions
   to the outer phase after a `READY_FOR_OUTER_LOOP` decision, regardless of
   what opens the next round — and an outer-phase `CHANGES_REQUIRED` round
   requires `codev work triage` before a further round may open (ADR-0003).
   Neither file mentioned the triage step, so an orchestrator following the
   documented path hit an undocumented `WorkError` with no prescribed
   recovery.
3. **Nothing could recover once stuck.** `work.start()` refuses to reuse a
   work-item id whenever its state file exists at all — `close()` only ever
   sets `status` to `"closed"`, it never removes the file — so a closed
   item's id is unusable forever. `_round_slot` mechanically refuses to open
   a round beyond `max_rounds`. Combined with (1) and (2), a work item could
   reach a state where it was simultaneously closed (or round-capped) and
   drifted, with every documented path forward blocked and no
   `reset`/`reopen`/`delete` command anywhere in `work.py` or `cli.py`. The
   only way out was manually deleting or hand-editing
   `.codev/work/<id>/round-state.json` outside the CLI entirely — silently
   discarding the evidence trail ADR-0001 exists to keep honest.

None of this is a case for loosening the guards themselves. `start`'s
id-uniqueness, `_round_slot`'s round cap, and `check`'s drift detection are
each individually correct — they are what makes the evidence trail
trustworthy. The gap is that nothing in the tool acknowledged a human can
look at a stuck item and legitimately decide "yes, continue this one
anyway," the same authority a human already has to accept a delivery-plan
change or override a triaged finding elsewhere in this system.

## Decision

### 1. Fix the two wording defects at the source

`builder.md` (all four platforms) no longer instructs the builder to call
`codev work record` itself, and no longer asks it to report a head snapshot
it cannot know. `orchestrator.md` (all four platforms) and the canonical
`.codev/for-ai/ai-agent-guidelines.md` now commit first (`codev git
commit`) and record the builder's round immediately after, against the
commit's actual resulting head. `code-audit.md.template` (all four
platforms) no longer claims a specific round cap or phase for its own
correction round — that claim duplicated `orchestrator.md`'s protocol in a
second place and had already drifted from it once; `code-audit` now defers
entirely to the orchestrator for what happens after it reports findings.
`orchestrator.md` and `ai-agent-guidelines.md` instead state the real
mechanics: a post-`ok_ready_for_pr` finding opens the outer phase's round 1
and needs a `codev work triage` call before the correction reaches
`builder`.

### 2. `codev work reopen`: a human-authorized escape hatch

A new `work.reopen(work_item_id, head, reason, *, target, max_rounds=None,
by=None)`, exposed as `codev work reopen --id <id> --head <head> --reason
<text> [--max-rounds N] [--by <identity>]`:

- Works regardless of `status` — `in_progress` or `closed` — unlike `start`.
- Requires `head` and `reason` as non-empty text; there is no default
  reason, the same way `triage`'s `override_reason` for a deferred blocking
  finding cannot be empty (ADR-0003) — a recovery with no stated reason is
  exactly the silent state-rewriting this command exists to replace.
- Re-baselines `base_snapshot` to `head` and appends exactly one new, empty
  round (`builder` and `reviewer` both `None`) — it never touches a
  previously recorded round. `check()`'s existing fallback (expected head is
  `base_snapshot` when the latest round has neither builder nor reviewer
  set) then makes the item immediately consistent again with no new special
  case in `check()` itself.
- Infers the new round's phase the same way `_round_slot` already would from
  the last round's reviewer decision, when there is one —
  `READY_FOR_OUTER_LOOP` from an inner-phase round continues into the outer
  phase, everything else continues in the same phase — so a reopen after
  normal convergence lands exactly where the interrupted flow would have.
- May raise `max_rounds` (either phase) but never lower it below the rounds
  already recorded for that phase, so a widen-only cap change cannot
  retroactively contradict recorded history.
- Sets `status` back to `in_progress` and clears any `outcome`.
- Appends a record (`timestamp`, `previous_status`, `from_round`/`to_round`,
  `head`, `reason`, `by`, resulting `max_rounds`) to a new, additive
  `reopens` list on the round-state, printed by `codev work log` the same
  way `triage` already is. No `ROUND_SCHEMA_VERSION` bump — additive only,
  the same precedent ADR-0004 and ADR-0006 established for optional
  metadata.

`start`'s duplicate-id error and `_round_slot`'s round-cap error now name
`codev work reopen` directly, and `.codev/for-ai/ai-agent-guidelines.md`
documents it as a "Stop conditions"-style human decision: an agent may
propose it, never invoke it on its own initiative.

## Consequences

- A work item can no longer become permanently unrecoverable through the
  normal protocol. The worst case is now "a human must explicitly authorize
  continuing," never "the id is dead and its history must be discarded."
- `reopen` intentionally does not attempt to diagnose *why* an item is
  stuck (drift, round cap, a close, or some combination) — it does not need
  to, since it bypasses the same small set of preconditions regardless of
  which one fired. This keeps the function simple and avoids re-deriving
  `check()`'s diagnostic logic a second time.
- All four platform adapters needed the same two wording fixes; `codev
  adapter verify`'s required-marker check for `builder`/`orchestrator` is
  unaffected (the edited files still contain `codev work record`, now
  attributed correctly).
- `code-audit.md.template` is intentionally no longer the place that
  documents the outer-phase/triage transition — `orchestrator.md` and
  `ai-agent-guidelines.md` are, matching the single-source-of-truth
  reasoning ADR-0005 already applied to who owns which coverage dimension.
  This ADR's own Context section is a case study in why: the duplicated
  claim had already drifted once.
- Testing needs: round-trip coverage for `reopen` on both a closed and a
  round-capped-but-still-`in_progress` item, phase inference in both the
  `READY_FOR_OUTER_LOOP` and non-`READY_FOR_OUTER_LOOP` cases, `max_rounds`
  widen-only validation, required-text validation for `head`/`reason`, and
  `log_text` output for the `reopens` trail.
