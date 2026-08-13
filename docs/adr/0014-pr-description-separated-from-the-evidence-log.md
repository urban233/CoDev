# ADR-0014: PR description separated from the evidence log

**Status:** Accepted
**Date:** 2026-08-13

## Context

`git_ops.mark_ready()` unconditionally overwrote the pull request's body
with `work.log_text()` -- the mechanical, round-by-round audit-trail
formatter -- discarding whatever prose `open-pr` originally set. `mark_ready`
runs once the outer loop converges, on essentially every PR that reaches
human review, so the PR a human actually sees was, in practice, always the
raw log: work item id, round numbers, builder/reviewer head hashes,
findings by category and location. A real session's feedback called this
"utter ugly" and "nowhere near professional," and asked that a reviewer be
able to understand the change without opening any of the repository's own
docs.

Separately, the richest available prose already exists and is already
discarded: `orchestrator` step 3 renders the full
`implementation-plan.template.md` in conversation -- summary, approach,
risks, validation plan -- gets it approved by the human, and then never
persists any of it. Only a one-line `summary` (ADR-0004) survives into
`round-state.json`.

Decided directly with the maintainer: the evidence trail stays linked, not
embedded. `codev work log`'s exact current format is untouched and stays
the only place round-by-round detail lives; the PR body becomes a separate,
self-contained narrative document instead of trying to be both.

## Decision

`work.start()` gains an optional `description`, alongside the existing
`summary`, same `_validate_optional_text` pattern, same write-once timing
(set at `start()`, which already runs after the plan is discussed and
approved in `orchestrator` steps 3-4 -- no update path needed, the content
is already known by the time it's needed). Sized proportionally, per the
maintainer's direction: set only when `orchestrator` already rendered the
full implementation-plan template for this item (that step's own existing
size/risk gate decides this, nothing new to invent); a small bounded item
keeps just `summary`.

New `work.pr_description(work_item_id, *, target) -> str`, entirely
separate from `log_text()`:
- `description`, falling back to `summary` when unset, so a small item
  degrades gracefully instead of rendering an empty section.
- A "Validation" section built from `_effective_coverage(rounds)`: a
  one-line "All 8 review dimensions pass" when nothing is missing, or a
  per-dimension breakdown (passed / not passed / not yet reviewed, and --
  forward-compatible with the coverage-waiver work already scheduled next
  -- waived, with its reason) otherwise. Human-readable dimension labels,
  not the raw `REQUIRED_COVERAGE_DIMENSIONS` keys.
- A tracking line naming the work item id and `link_ref`, and a pointer to
  `codev work log --id <id>` for the full trail -- linked, never embedded.
- Never includes finding text, round numbers, or head hashes.

`cli.py`'s `git open-pr`: when neither `--body` nor `--body-file` is given
(previously a hard `GitOpsError`), falls back to `pr_description()` instead
of requiring the caller to supply body text by hand. `git_ops.mark_ready()`:
replaced `work.log_text(...)` with `work.pr_description(...)` -- the one
line that was actually causing the complaint.

## Consequences

- No `ROUND_SCHEMA_VERSION` bump: `description` is additive, same
  precedent as ADR-0004's `link_ref`/`summary`/`owner`.
- `codev work log`'s output and every existing consumer of it (terminal
  use, `triage_note`, the `reopens` rendering) is completely unchanged.
- A PR opened with an explicit `--body`/`--body-file` still works exactly
  as before at `open-pr` time -- but `mark-ready` now always regenerates
  from `pr_description()` regardless, so a hand-written body only survives
  until the outer loop concludes. This is intentional: `mark-ready`'s job
  is to reflect the item's *final* state, and a hand-written body has no
  way to track ongoing coverage the way the formatter does.
- Testing needs (added): `tests/test_work.py::PrDescriptionTests` --
  summary fallback, description preferred over summary, "review in
  progress" before any reviewer round, full-coverage one-liner,
  per-dimension breakdown when incomplete, no finding text or round
  numbers ever present, work item id and link included.
  `tests/test_git_ops.py::MarkReadyTests` gains a regression test that the
  regenerated body matches `pr_description()` and not `log_text()`.
