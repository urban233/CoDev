# ADR-0039: Slice stacking replaces sibling-task stacking

**Status:** Accepted
**Date:** 2026-09-02
**Owner:** Martin Urban
**Related design:** [docs/features/slice-per-branch/brief.md](../features/slice-per-branch/brief.md)
**Supersedes:** [ADR-0034](0034-stacked-task-branches.md)

## Context

ADR-0034 gave `codev git branch` an opt-in `--stack-on <parent-task-id>`, so
one task's branch could target a recorded sibling task's branch. At the time
that was the only way to express a piece of work as an ordered chain of small
pull requests, because a task was the only unit CoDev had.

ADR-0035 then made the slice the unit of execution and the task the collection
its slices belong to, and `docs/features/slice-per-branch/brief.md` carried
that through to the git surface: a slice now owns its own branch, cut from the
previous slice's head, and its own pull request.

The two mechanisms now answer the same question twice. A developer with three
dependent changes can express them as one task holding three slices, or as
three sibling tasks related by `--stack-on`, and nothing in the product says
which is right. Both paths maintain their own notion of a parent, their own
base resolution in `open_pr`, and their own answer to "is this the last piece,
so may it close the issue?" -- `_has_recorded_child` globbing sibling state
files on one side, an ordered slice list on the other.

Keeping both is worse than a redundancy. The sibling form spreads one piece of
work across several tasks, which means several GitHub issues, several owners,
and several independent reviewers for what is a single reviewable outcome --
exactly the coupling ADR-0035 introduced the task/slice split to remove.

## Decision

Sibling-task stacking is removed. `codev git branch` loses `--stack-on`,
`git-state.json` stops recording `parent_task`, and the accessors and
pull-request base resolution that existed only to serve that relationship are
removed with it.

A stack is now expressed one way: **one task, an ordered list of slices, one
branch and one pull request per slice.**

Three parts of ADR-0034 are **carried forward unchanged**, because they were
never about the sibling relationship:

- `codev git restack` remains, and now cascades across a task's own slices
  rather than a chain of sibling tasks.
- Its force-push standard stands exactly as ADR-0034 set it, and remains the
  standard every future guarded command touching already-pushed history is
  held to: `--force-with-lease` only and never a bare `--force`; only when the
  caller is on the branch being rewritten; refused once the parent's pull
  request has merged; and a rebase conflict reported to the human, never
  resolved automatically.
- `codev git branch`'s preconditions -- the dirty-worktree refusal and the
  resolved default base -- stand, since ADR-0034 already recorded them as
  independent of stacking.

Stacking remains coherent only under trunk-based development, so every
affordance continues to read `git.workflow` and disable itself under
`feature-branch` (ADR-0033).

## Alternatives considered

- **Keep both and document when to use each:** rejected. Two mechanisms for
  one job is a question every adopter has to answer once and CoDev cannot
  answer for them, and the two disagree on the thing that matters most --
  whether one issue or several track the work.
- **Keep `--stack-on` as a deprecated alias that creates a slice:** rejected.
  A task id and a slice id are not interchangeable: the sibling form gives
  each piece its own issue, owner, and reviewer, and silently collapsing that
  into one task's slice list would change what a task means without saying so.
- **Deprecate with a warning for one release rather than removing:** rejected
  for this case, though it is the pattern ADR-0037's rename used. A returned
  reason string is read by scripts that cannot be found; `--stack-on` is an
  interactive flag whose only recorded use is in this repository's own
  history, which the discovery below confirmed.

## Consequences

- This is a breaking change for any adopter with an open sibling stack.
  Existing branches and pull requests are untouched -- git does not care why a
  branch was created -- but `codev git restack` will no longer walk a
  `parent_task` link, and such a stack must be finished by hand or re-expressed
  as one task's slices.
- `_has_recorded_child` and the sibling half of `_closing_line` go away. The
  `Part of #N` / `Closes #N` decision now comes only from the task's ordered
  slice list, which ADR-0035 already made authoritative.
- `codev status`'s stack reporting becomes per-task-slices rather than a walk
  of sibling links, and reports the same shape it did before.
- ADR-0034 is marked superseded rather than edited. Its Context and Decision
  stay exactly as written; they record what was true when it was accepted.

## Revisit when

A piece of work genuinely needs its pieces owned by different people with
different reviewers, reviewed as one chain. That is the case the sibling form
served, and nothing here replaces it -- slices of one task share the task's
owner and reviewer by construction. If that case turns out to be common,
this decision is the one to reopen, not ADR-0035.
