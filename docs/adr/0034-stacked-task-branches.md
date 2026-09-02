# ADR-0034: A task's branch may target a recorded sibling task's branch

**Status:** Accepted
**Date:** 2026-09-02
**Owner:** Martin Urban
**Related design:** [docs/features/small-prs/design.md](../features/small-prs/design.md)

## Context

ADR-0002 accepted, as part of its guarded-CLI decision, that the `codev
git` wrapper "operates only on the one branch created for the work item
(name derived from the work item id), never the branch checked out at run
start." Every task branches directly from a base snapshot, and every
task's pull request is independent of every other task's. That is correct
and unchanged for the overwhelming majority of work, and this ADR does not
touch it.

`docs/features/small-prs/design.md` documents a real cost of that
guarantee having no exception: a piece of work with a genuine sequential
dependency -- a schema change, then the logic that consumes it, then the
wiring that exposes it -- has no way to become three small, independently
reviewable pull requests without either waiting for each one to merge
before starting the next (destroying the parallelism CoDev's own
`plan-wave` skill already values), or manually branching one task off
another's branch by hand outside `codev git` entirely, which the guarded
surface can neither see nor protect: no restack after review feedback, no
correct issue-closing behavior, and `task.check`'s `stop_drift` guard
firing the moment the parent branch is rebased.

Google's published engineering practice for exactly this shape of problem
is stacked change lists: an author does not wait for review before
starting dependent work, branching the next piece directly off the
still-unreviewed previous one, and restacking each child when an earlier
one changes. That case does not exist in `codev git` today at all.

## Decision

`codev git branch` gains an optional `--stack-on <parent-task-id>`. When
given, the parent task must already have a recorded branch, and the new
task's `git-state.json` records `parent_task: <parent-task-id>` alongside
its own `branch`/`base_snapshot`. This is the one narrow, explicit,
opt-in exception to ADR-0002's "never the branch checked out at run
start" guarantee: a task may target another *recorded* task's branch,
never an arbitrary checked-out branch, and only when the caller asks for
it by name. A task created without `--stack-on` keeps ADR-0002's original
guarantee exactly as written.

Three further, additive changes follow from that one field, all detailed
in design.md rather than repeated here:

- `codev git open-pr` resolves its base to the parent's branch, ahead of
  `--base`/`git.pr_base`/the default branch, while the parent's pull
  request is still open, and writes `Part of #N` instead of `Closes #N`
  for every task that has a recorded child -- only the last slice in a
  stack carries the auto-close link.
- A new command, `codev git restack --id <id>`, rebases a child onto its
  parent's current head and re-baselines `base_snapshot`, so `task.check`
  does not report `stop_drift` after a parent is amended. This is CoDev's
  first command that force-pushes already-pushed history, which ADR-0002
  never authorized for anything. It is authorized here, narrowly: only
  with `--force-with-lease`, never a bare `--force`; only when the caller
  is actually on the child's own branch; and refused outright once the
  parent's pull request has merged. A rebase conflict is reported to the
  human, never resolved automatically.
- `codev git branch` also gains the preconditions design.md's "Now" slice
  already shipped independently of stacking (a dirty-worktree refusal, a
  refusal to branch from another recorded task's branch that carries
  unmerged commits, and an optional, resolved `--base`) -- those apply
  regardless of `--stack-on` and are not part of this decision.

## Alternatives considered

- **Document plain-`git` branch stacking in the skills, with no `codev
  git` change:** rejected -- this is the status quo the Context section
  describes, and it is exactly what leaves stacking unprotected by every
  guarantee ADR-0002 already provides for a non-stacked task.
- **`--stack-on` only, with restacking left to a manual `git rebase`:**
  rejected as insufficient on its own -- the cascade after review feedback
  is the step that actually makes stacking painful, and leaving it manual
  means the guarded surface still can't prevent the exact drift and
  force-push mistakes it exists to prevent everywhere else.
- **Give `codev git branch` a generic `--base <any-ref>` and let a
  developer point it at another task's branch name directly, with no
  dedicated flag or recorded relationship:** rejected -- `base_snapshot`
  must stay a value `changed_files`/`task_size` can safely diff against
  (task.size's design already pins it to a commit for exactly this
  reason), and a bare `--base` given a moving branch name provides no
  place to record the sibling relationship `open_pr` and `restack` both
  need to look up.

## Consequences

- Purely additive and opt-in: `parent_task` is absent from every task
  created before this change and from every task that never passes
  `--stack-on`, and both `codev git branch` and `codev git open-pr` keep
  working exactly as before for such a task. No existing round-state or
  git-state schema field changes shape.
- `codev git restack` is the first command in this project authorized to
  force-push. Every future guarded-CLI addition that touches already-
  pushed history must be held to the same three-part standard set here
  (`--force-with-lease` only, ownership-checked, refused post-merge) or
  else amend this ADR to explain why not.
- Testing: `restack`'s force-push path needs a local bare-remote fixture,
  mirroring `PushTests`'s existing pattern in `tests/test_git_ops.py`,
  never a real GitHub repository.
- Stacking is coherent only under trunk-based development; every stacking
  affordance reads `git.workflow` (ADR-0033) and disables itself under
  `feature-branch`, the same posture ADR-0033 already required of every
  prompt it introduced.

## Revisit when

Design.md names two implementation-level questions that this ADR
deliberately leaves open, to be resolved empirically during the slices
that actually build `restack` and the `Part of`/`Closes` logic, not
guessed at here: whether "the last slice in a stack" can be derived from
recorded parent links alone or needs an explicit flag on the final task,
and whether `restack`'s re-baselining can reuse `task.reopen`'s existing
in-place update or needs its own code path. Neither answer changes the
decision recorded above; both are free to resolve either way without
reopening this ADR. Revisit this ADR itself only if real usage shows a
task needs more than one parent, or a stack deeper than a handful of
tasks turns out to be common enough that a flat `parent_task` field can no
longer represent it.
