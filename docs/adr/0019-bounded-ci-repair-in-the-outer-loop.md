# ADR-0019: Bounded CI-repair attempt in the outer loop

**Status:** Accepted
**Date:** 2026-08-13

## Context

ADR-0003 designed the outer loop's CI check as a pure pre-dispatch gate, on
purpose: "Checks CI status *before* dispatching any specialist: red or
pending checks stop the run and report, rather than spending five specialist
invocations on a PR that doesn't even build." `outer-loop-runner.md` step 1
implements exactly that today, on every platform, and nothing more.

This was always a scope decision, not an oversight — but it leaves a real gap
against the "self-healing" instinct already established elsewhere in this
system (ADR-0002's inner loop, ADR-0015's pre-PR cleanup gate): the outer
loop already has everything it would need to *attempt* a fix. `builder` is
already in `outer-loop-runner`'s permitted dispatch list. The
`github-actions-ci-results` skill it already calls for fetching CI status
produces exactly the structured diagnostic a correction needs — a labeled
`Assessment` and `Next action` per failed job/step, not just a pass/fail
flag. Nobody had decided the outer loop should *own* getting CI green,
distinct from deciding it should merely notice CI is red.

## Decision

`outer-loop-runner` step 1 (all four platforms), on red — not pending —
checks: fetch the failing job's diagnostic via `github-actions-ci-results`
(its existing `Assessment`/`Next action` structure is exactly the scoped
input a correction needs), dispatch `builder` **once**, scoped to only that
failure, push the result, and re-fetch CI status. If checks are now green,
continue to step 2 as normal. If not, fall through to today's behavior —
stop and report plainly to the human — exactly as if no repair had been
attempted.

Capped at exactly one attempt, matching every other bound already in this
system: the inner and outer round caps, the outer loop's own single
correction round (ADR-0003). This is not a general-purpose CI-fixing loop —
it is one bounded, reversible attempt before falling back to the existing,
already-correct stop-and-report behavior. A human may still explicitly
override the CI gate itself for a specific reason, unchanged from ADR-0003;
this ADR does not touch that path, only what happens automatically before it
would be reached.

No `work.py` change: this reuses `builder` dispatch and the existing
`github-actions-ci-results` skill entirely at the prompt level, the same way
ADR-0010's comment-sourced entry needed no schema or CLI change. The repair
attempt itself is not recorded as a round — it either succeeds, in which
case the outer loop proceeds normally with real checks now green, or it
doesn't, in which case nothing about round-state has changed and the
existing stop-and-report path applies unmodified.

## Consequences

- `outer-loop-runner.md`'s step 1 prompt update lands together with
  ADR-0017's pre-dispatch `codev work check` call and ADR-0018's
  `--selection` requirement, in one combined edit across all four platforms
  rather than three separate passes over the same section.
- This is a real increase in autonomy — the outer loop can now push a commit
  without a human turn in between, the same category of change ADR-0002 and
  ADR-0015 each got their own ADR for. Scoped tightly (one attempt, one
  failure, falls back to the existing human checkpoint) to keep that
  increase bounded and reversible, consistent with this project's target
  audience: a human-triggered local run, never unattended CI-triggered
  inference.
- Not resolved by this ADR: what happens if the repair attempt's own commit
  introduces a *different* CI failure than the one it was scoped to fix.
  Falls through to the existing stop-and-report path either way (checks are
  still not green), so no new failure mode is introduced, but the report to
  the human does not yet distinguish "still the original failure" from "a
  new one caused by the repair attempt" — worth a follow-up once this is in
  use, not designed here.
- Testing needs: none beyond the existing adapter-conformance checks, the
  same as ADR-0010 — this is workflow-instruction surface only, with no new
  executable surface in `work.py`/`git_ops.py`/`cli.py` for a unit test to
  exercise.
