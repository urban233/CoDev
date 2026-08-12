# ADR-0006: Work-item entry modes for human-authored work

**Status:** Proposed
**Date:** 2026-08-12

## Context

`codev work start` and the three-agent Build protocol (ADR-0001, ADR-0002)
assume every work item begins the same way: `orchestrator` opens it against
a bare base snapshot and invokes `builder` from a blank slate. Real usage
does not always look like that — a developer picks a work item off an
existing delivery plan or backlog and starts writing code by hand before
CoDev is involved at all. Today that work has no first-class entry point
into either loop; the only tool that reaches it is `review-change`, and
ADR-0005 just repositioned that skill explicitly around the zero-ceremony,
no-work-item case, not a real work item's lifecycle.

Two genuinely different human-authored situations need two different
answers, not one:

- the work is **unfinished** and the developer wants AI to continue it —
  this belongs in the inner loop, exactly like AI-only work, because there
  is real building left for `builder` to do;
- the work is **finished** and only needs review — forcing it through the
  inner loop would waste a round having `builder` rediscover that the diff
  is already correct; it belongs directly in the outer loop.

A third option — an AI-guided "give me the next work item" CLI flow, to
reduce the mental load of remembering `work start`'s flags — was considered
and dropped. GitHub's own Issues list already serves that need for any work
item pushed there via `codev git issue-create` (ADR-0004); a second,
CoDev-specific mechanism for the same job would be exactly the kind of
redundant surface this round of ADRs exists to remove, not add.

This ADR does not revisit ADR-0004's `owner`/`link`/`summary` fields; it
adds a way to record how a work item's code came to exist, alongside them.

## Decision

### 1. `--entry takeover` — hand unfinished human work to the inner loop

`codev work start` gains an optional `--entry` argument (`takeover` or
`direct-review`; omitted means today's implicit cold start, unchanged). For
`takeover`, the branch already carries human commits beyond the base
snapshot recorded by `--base`. `orchestrator`'s three-agent protocol gains
an explicit branch for this case: `builder`'s first round must read the
current head-to-base diff — the human's own work — before changing
anything, and continue it rather than silently discarding or replacing it.
`lightweight-reviewer`'s per-round check is unchanged; it already reviews
whatever diff exists at the recorded head regardless of who authored which
round.

### 2. `--entry direct-review` — hand finished human work directly to the outer loop

For `direct-review`, `codev work check` must recognize the item as
immediately eligible for `ok_ready_for_pr` without waiting for any
builder/reviewer round to be recorded — there is no inner-loop evidence to
wait for. The developer pushes their own branch and opens the PR through the
same guarded `codev git` commands as any other item (or already has). From
there, `outer-loop-runner` is unchanged: it already only requires "one work
item that already has an open pull request," and does not care how that PR
came to exist.

### 3. Quick-look stays outside the work-item lifecycle

Cross-reference, not a new decision: per ADR-0005, a diff with no work item
and no intention of becoming one is `review-change`'s territory, not this
ADR's.

## Consequences

- `work.py` gains one new optional field (`entry`) on `start`, additive
  only — no `ROUND_SCHEMA_VERSION` bump, matching ADR-0004's precedent for
  optional metadata.
- `codev work check` gains exactly one new case: a `direct-review` item's
  readiness no longer depends on a recorded round. This is the only real
  state-machine change in this ADR; everything else is metadata plus prose
  guidance to `orchestrator`.
- `orchestrator.md` (all four platforms) gains explicit `takeover` and
  `direct-review` branches alongside its existing cold-start protocol.
- `outer-loop-runner` and `lightweight-reviewer` require no changes at all —
  both are already entry-mode-agnostic by how they were written.
- Non-goal: no `codev work next` or guided-selection command — considered
  and dropped in favor of GitHub's own Issues list.
- `docs/product-map.md` should be updated once this lands, same as ADR-0005.
