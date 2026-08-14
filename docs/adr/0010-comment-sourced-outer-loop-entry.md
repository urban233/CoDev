# ADR-0010: `outer-loop-runner` gains a comment-sourced entry

**Status:** Accepted
**Date:** 2026-08-13

## Context

A human reviewer leaving comments directly on an open GitHub PR had no
tracked path into the inner/outer loop. `publish_review.py --fetch` already
retrieves a PR's existing `comments`/`reviews` (alongside `metadata`, `diff`,
`files`, `commits`, `checks`), and `critique-review`'s accepted inputs
already listed "a developer-supplied review comment tied to an exact file
and line" — but neither closes the loop: `pr-review` reads existing comments
only as context for producing its *own* new review, and `critique-review`
requires a human to manually transcribe the comment in, drafts a suggested
diff only, and stops — "Suggested only — not applied... a developer must
accept, reject, or revise" — fully decoupled from `codev work`'s round-state.
Nothing recorded a PR comment as a finding, nothing dispatched `builder` to
fix it, and nothing tracked the fix as evidence.

Two questions shaped the design, resolved by direct instruction rather than
inference from precedent:

1. **Where does a comment-sourced round belong, mechanically?** A PR can
   only exist once an item reaches `ok_ready_for_pr` or the outer phase
   (`git_ops.open_pr`'s eligibility, ADR-0007's follow-up); every legitimate
   path to an open PR — normal `ok_ready_for_pr`, `reopen` into the outer
   phase, or a `direct-review` entry starting there directly — leaves the
   item's current phase as `"outer"` or one round away from it. `_round_slot`
   never transitions backward from outer to inner. So "using the inner loop
   strategy" cannot mean literally reopening a `phase: "inner"` round; it
   means reusing the inner loop's fast, narrow *verification standard*
   (`lightweight-reviewer`'s intent-match-plus-revalidate, not a full
   specialist pass) inside what is still mechanically an outer-phase round.
   No `work.py` schema change was needed either way: `_round_slot` does not
   care who or what produced a round's findings, and `record_triage` and
   the coverage gate already operate generically on whatever is recorded.
2. **Does a comment become a finding directly, or does the owning specialist
   independently re-verify it first?** The project's established pattern
   elsewhere is "never trust a self-report" (`lightweight-reviewer`
   re-running the builder's own validation, `open_pr` checking GitHub
   directly rather than trusting round-state). Asked directly: comments
   should be trusted as findings as-is, with specialist involvement reserved
   for a comment that itself names or asks for one. A human reviewer's PR
   comment is not a self-report in the sense that guidance addresses — it is
   independent, external, human-authored judgment already; the guidance was
   protecting against unverified *agent* claims, which does not apply here.

## Decision

`outer-loop-runner` (all four platforms) gains an "Entry mode" section,
preceding its numbered steps the same way `orchestrator.md`'s `takeover`/
`direct-review` preamble does:

- **Fetch** (step 1, unchanged) explicitly includes `comments` and `reviews`
  in `publish_review.py --fetch`'s `--include` list.
- **Drafting** replaces specialist dispatch (step 2) for this entry only:
  read every fetched comment; for each actionable one (a concrete ask, not a
  question or side discussion), draft a finding directly from its content —
  exact `location` from the comment's anchor, best-fit `category` among the
  eight coverage dimensions, `blocking: true`. Trust the comment as the
  finding. Dispatch the specific specialist a comment itself names or asks
  for, narrowly, for that one finding only, before finalizing it — the one
  case specialist involvement remains warranted.
- **Record and auto-triage.** `codev work record --role reviewer --decision
  CHANGES_REQUIRED` with the drafted findings, then immediately
  `codev work triage` disposing every one of them `address` — the human's
  own instruction to act on their PR comments is the authorization; waiting
  for a second, separate triage confirmation would be ceremony over the
  decision already given. The interpreted findings are still reported in the
  same turn, so a misread comment is visible before `builder` starts, even
  though nothing blocks on that visibility.
- **Correction** continues at the existing step 5's `ok_continue` path,
  scoped to exactly the comment-derived findings.
- **Verification** uses `lightweight-reviewer`'s standard (intent-match plus
  independent re-run of validation) instead of a fresh full specialist pass,
  reflecting that these are typically narrow, human-pinpointed fixes. The
  round's recorded decision still uses the outer vocabulary
  (`CHANGES_REQUIRED` / `READY_FOR_HUMAN_APPROVAL` /
  `BLOCKED_BY_MISSING_EVIDENCE`) — the round's phase is mechanically outer
  regardless of entry mode, so `READY_FOR_OUTER_LOOP` never applies here.
- **Coverage carries forward.** Both the new entry and the existing step 5
  narrow-correction path (which had the same unstated assumption already)
  now say explicitly: coverage for a dimension this round did not itself
  touch carries forward from whichever round most recently established it,
  rather than being re-derived or left blank. `ok_approve` still requires
  complete eight-dimension coverage; a PR the five specialists have never
  reviewed cannot reach it through comment-fixing alone, and the workflow
  now says so plainly instead of leaving the gap implicit.

`critique-review`'s accepted inputs drop "a developer-supplied review
comment tied to an exact file and line" — for a work item with an open PR,
this entry mode fixes the finding directly through the tracked inner-loop
correction cycle instead of stopping at a suggested, unapplied diff, making
`critique-review` strictly worse for that exact case. `critique-review`'s
remaining inputs (`review-change`/outer-loop/`code-audit` findings,
presubmit/lint/test failures) are unaffected — none of those have a work
item's round-state to attach a tracked fix to, which remains
`critique-review`'s actual niche, the same zero-ceremony territory ADR-0005
already scoped `review-change` to.

## Consequences

- No `work.py` or `git_ops.py` change: `_round_slot`, `record_triage`, and
  `_incomplete_coverage` already operate generically on whatever produced a
  round's findings and coverage. This entire ADR is workflow-instruction
  surface only, across the four platform `outer-loop-runner` files,
  `ai-agent-guidelines.md`, and `critique-review`.
- A comment-sourced round can converge and land findings without ever
  satisfying full outer-loop coverage — by design, not an oversight: fixing
  what a human flagged and reaching full review-completeness are separate
  claims, and this entry only makes the first one. A team wanting both runs
  the full specialist pass at some point too, before or after.
- The coverage-carry-forward clarification applies to the *existing*
  step 5 narrow-correction path as well, not only the new entry — it was an
  unstated assumption there already; this ADR is the first place it is
  written down.
- Testing needs: none beyond the existing adapter-conformance and
  bundle-validator checks, which already passed against the new prose
  unchanged (`codev adapter verify` required-marker checks, `scripts/
  validate-development-workflow.py`'s guide/skill reference checks) — there
  is no new executable surface for a unit test to exercise.
