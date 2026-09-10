# Slice-Scoped Coverage - Implementation Plan

**Status:** Accepted 2026-09-08 by Martin Urban (instructed in session;
transcribed by Claude Opus 5, who does not hold acceptance authority)
**Owner:** urban233
**Reviewer:** independent reviewer, to be named before the pull request is marked ready
**Risk:** high for its size. It changes what the outer-loop coverage gate lets through. Too loose and the gate stops gating; too strict and every slice re-verifies dimensions a human already ruled on.
**Containment:** N/A -- pure evidence accounting; no runtime behaviour, no data migration beyond reinterpreting existing records.
**Work style:** `pair` (recorded)
**Slices:** 1 -- one pull request
**Slice:** `slice-scoped-coverage`
**Base commit:** `b299819` (head of slice 1's branch; stacked between #50 and slice 2)
**Issue/work item:** none (kept local)
**Brief/design/API:** Not needed -- defect fix against observed behaviour, reproduction below

## Focus card

- **Change:** scope coverage waivers and reviewer verdicts to the slice that
  earned them, so a later slice starts with an empty manifest rather than
  inheriting the previous slice's.
- **Success:** a waiver granted on slice A does not appear in slice B's
  coverage manifest or rendered pull-request body; `codev task check` reports
  `stop_incomplete_coverage` for slice B until slice B's own dimensions are
  covered.
- **Non-goals:** withdrawing a waiver (noted below, deliberately separate);
  changing what any dimension means; the adapter plan's slices.
- **Allowed scope:** `src/codev_workflow/task.py`, `tests/`, `CHANGELOG.md`.
- **Validation:** `just ci`; a regression test that grants a waiver on one
  slice, advances, and asserts the next slice does not carry it.
- **Stop if:** scoping turns out to break `codev task reopen`'s surviving
  prior rounds, which deliberately carry forward *within* a slice.

## Repository evidence

Reproduced 2026-09-08 on task `claude-code-adapter-verification-first`:

1. Seven waivers granted while slice `work-style-and-plan-tiering` was in the
   outer phase.
2. `codev slice land` advanced to slice `permission-surface`.
3. `codev slice publish` rendered all seven into PR #51's body verbatim,
   attributed to the granting human.

The reasons are false for that slice: "zero Python changed" (it adds
`tests/test_permission_surface.py`), "No tests added or modified" (it adds
one), "no credential, network, data or serialization surface" (it changes
`.claude/settings.json`'s `permissions.allow`/`deny`, which is exactly a
permission surface). PR #51 was closed rather than reviewed on that evidence.

Mechanism, confirmed by reading the code:

- `task.py:908-928` (`_effective_coverage`) merges `state["rounds"]` and
  `state["coverage_waivers"]` by round number across the **whole task**.
  `state["rounds"]` spans every slice, so both waivers *and reviewer verdicts*
  carry across slice boundaries.
- Waiver entries carry `by`, `dimension`, `reason`, `round`, `timestamp` --
  verified: no `slice_id` on any of the seven.
- `codev task waive` (`cli.py:689`) has no withdrawal option, so a waiver
  granted once cannot be taken back.

This contradicts ADR-0035, which makes the slice the unit of execution, and it
undermines the guarantee the waiver mechanism exists to provide: a pull request
body saying "waived (by <human>)" reads as a decision about *that* pull
request.

## Proposed change

1. **Record the slice on a waiver.** `waive()` writes `slice_id` alongside
   `round`.
2. **Scope the merge.** `_effective_coverage` filters to the current slice:
   a round counts when its `slice_id` matches; a waiver counts when its
   `slice_id` matches, or -- for the pre-existing entries that have none --
   when the round it was recorded at belongs to the current slice. That
   derivation is the migration, and it retro-scopes the seven existing
   waivers to slice 1 correctly, because they were granted at round 5.
3. **Leave carry-forward inside a slice untouched.** The round-ordered
   most-recent-wins merge, and `reopen`'s surviving prior rounds, are correct
   and stay exactly as they are. Only the slice boundary becomes a wall.

## Validation

- New regression test: grant a waiver on slice A, advance to slice B, assert
  B's effective coverage does not contain it and that `task check` reports
  `stop_incomplete_coverage`.
- New test pinning the migration: a waiver with no `slice_id`, recorded at a
  round belonging to slice A, does not leak into slice B.
- New test pinning what must NOT change: within one slice, a later round still
  carries forward an earlier round's verdict, and a `reopen`'s surviving prior
  rounds still count.
- `just ci`, and `PYTHONPATH=src python3 -m unittest discover -s tests` --
  CI's other legs run the raw runner, and Bazel's sandbox has already masked
  one bug in this stack.

## Risks and rollout

- **Existing multi-slice tasks change verdict.** Any task whose later slice
  was relying, knowingly or not, on an earlier slice's coverage will start
  reporting `stop_incomplete_coverage`. That is the fix working, but it will
  look like a new gate failure and belongs in the CHANGELOG.
- **Withdrawal is still impossible.** Scoping stops a waiver leaking forward;
  it does not let a human take back one granted in error on the current slice.
  Deliberately out of scope -- it is a new CLI surface with its own design.
- **Rollback** is a revert; the `slice_id` field is additive and older records
  remain readable.

## Decisions needed

None. The migration rule is the only judgement call and it is recorded above.

## Completion evidence

- [ ] Regression test: waiver does not cross a slice boundary
- [ ] Migration test: an entry with no `slice_id` scopes by its round
- [ ] Carry-forward within a slice, and `reopen` recovery, still pass
- [ ] `just ci` green and the raw unittest runner shows no new failures
- [ ] CHANGELOG entry naming the behaviour change
- [ ] Slice 2 republished with a coverage block describing its own diff
