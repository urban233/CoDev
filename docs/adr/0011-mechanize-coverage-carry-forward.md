# ADR-0011: Mechanize coverage carry-forward in `codev work check`

**Status:** Accepted
**Date:** 2026-08-13

## Context

ADR-0008 and ADR-0010 both describe "coverage carries forward": a round
that only re-verifies some dimensions (a narrow correction, or ADR-0010's
comment-sourced entry) does not need to re-derive the dimensions it didn't
touch — those carry forward from whichever earlier round most recently
established them. Both ADRs stated this as prose guidance to the recording
agent: assemble a `--coverage` JSON manifest that merges this round's own
verdicts with the carried-forward ones from history, then pass the merged
manifest to `codev work record`.

`record_reviewer` stores exactly the coverage dict it is given — nothing in
`work.py` ever read a work item's round history to fill gaps. `_incomplete_
coverage` checked only `reviewer["coverage"]` from the latest round,
verbatim. The entire mechanism lived in prose the recording agent had to
correctly execute every time: remember the earlier round, remember which
dimensions it established, transcribe them into the new call.

A transcript from a real session surfaced the failure mode directly. A PR
had already reached `READY_FOR_HUMAN_APPROVAL`/`ok_approve` with full
eight-dimension coverage. The human then asked for two PR review comments
to be addressed. The agent fixed them, reopened the item, and ran a fresh
narrow review — "the fresh review passed with no actionable findings and
all checks green" — but recorded coverage only for the dimension(s) that
round actually touched. `codev work check` then reported
`stop_incomplete_coverage`, listing four dimensions as missing, "despite
the reviewer's prose claiming they passed." The reviewer's prose was
correct — those dimensions genuinely were still valid, established two
rounds earlier — but nothing carried that forward into the recorded
manifest, because carrying it forward was never the tool's job in the
first place.

This is the same class of problem `lightweight-reviewer` and `open_pr`'s
GitHub-truth check already exist to prevent elsewhere in this project:
prose asking an agent to correctly reconstruct state by hand is exactly
the kind of bookkeeping that degrades under load, longer sessions, or a
less careful model — and the cost of getting it wrong here is a spurious
hard stop on an otherwise-converged, human-approved item.

## Decision

Coverage carry-forward moves from agent-executed prose into `work.py`
itself. `check()` computes an *effective* coverage manifest at read time —
`_effective_coverage(rounds)` walks the item's full round history in
order and keeps, per dimension, whichever round's entry is most recent;
a later round's entry for a dimension always overrides an earlier one,
so a regression a fresh round flags as failing is never resurrected by an
older passing entry. `_incomplete_coverage` is checked against this merged
view in both places it runs (the `ok_approve`/`READY_FOR_HUMAN_APPROVAL`
gate and the `ok_approve_with_deferrals` gate), instead of against the
latest round's own coverage dict directly.

What each round *records* is unchanged and deliberately not merged at
write time: `record_reviewer` still stores exactly the coverage it is
given, preserving an honest per-round audit trail of what that round
itself actually verified. Only the *completeness check* looks across
history. This also means a `reopen` recovery's surviving prior rounds
(ADR-0007 — `reopen` never touches earlier rounds' builder/reviewer
entries) participate in the merge automatically, with no special-casing.

The recording instructions across all four platforms' `outer-loop-runner`
and `ai-agent-guidelines.md` drop the "assemble the merged/carried-forward
manifest" step entirely. An agent now records only the dimension(s) it
actually re-verified this round; `codev work check` fills in the rest and
names exactly what's still missing when it isn't complete. This is a
narrower, more honest instruction to follow, and it can no longer be
gotten wrong the way the transcript's round did — there is nothing left
for the agent to reconstruct from memory.

## Consequences

- `stop_incomplete_coverage` now reflects the item's actual established
  coverage across its full history, not just what the triggering round
  happened to restate. A narrow correction or a comment-sourced fix that
  only touches one or two dimensions on a PR the five specialists already
  fully reviewed converges correctly, without the agent needing to know
  or reconstruct that history at all.
- A dimension that has never been established in any round still blocks,
  by design — `_effective_coverage` only ever returns what some round
  actually recorded; there is no default-pass.
- A later round's failing verdict for a dimension always wins over an
  earlier passing one for that same dimension — carry-forward never
  resurrects a stale pass once something re-verifies and fails it.
- `tests/test_work.py::CoverageCarryForwardTests` covers: carry-forward
  producing `ok_approve` after a narrow post-approval fix (the transcript's
  exact failure, now passing); a dimension never recorded anywhere still
  blocking; a later failing verdict overriding an earlier pass; and the
  same mechanism applying to the `ok_approve_with_deferrals` gate.
- No schema or CLI change: `--coverage` still accepts the same partial or
  full JSON manifest it always did. This is purely a `check()`-time
  read-side change plus a documentation simplification, so it's fully
  backward compatible with every round ever recorded.
