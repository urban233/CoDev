# ADR-0035: The slice is the unit of execution; a task is the collection its slices belong to

**Status:** Accepted
**Date:** 2026-09-02
**Owner:** Martin Urban
**Related design:** [docs/features/unified-workflow/brief.md](../features/unified-workflow/brief.md)

## Context

CoDev's execution model currently makes the task the only first-class
object. `git_ops.branch_name_for` derives exactly one branch name,
`codev/<task-id>`, from a task id. `create_branch` refuses once
`git-state.json` exists for that task. `open_pr` refuses when the branch
already has an open pull request. `task.check`
(`src/codev_workflow/task.py:732`) drives one round-state machine to one
`ok_ready_for_pr`. One task means one branch, one round state, and one
pull request.

`docs/features/small-prs/design.md` and ADR-0034 established that a real
piece of work often needs several dependent pull requests, and gave
`codev git branch` a `--stack-on <parent-task-id>` flag so a task's branch
may target a recorded sibling's branch. That solved the mechanics and left
the model wrong. A three-slice piece of work is expressed today as three
independent tasks that a `parent_task` field relates after the fact. The
three share an issue, an owner, an independent reviewer, and a set of
acceptance criteria, and nothing in the model says so: `_closes_issue_number`
had to be taught to write `Part of #N` for every task with a recorded child
precisely because the collection those tasks form has no representation.

The same mismatch appears upstream. `plan-wave` and the task issue template
(`.github/ISSUE_TEMPLATE/task.md`) both ask for an ordered list of two to
four slices, each naming its decomposition strategy. That list is prose. It
is the plan's central output and the state machine cannot read it, so a
human translates it into task ids by hand and the translation is where the
size discipline is lost.

The accepted brief records the consequence: the slice list in a plan and
the tasks in the state machine are different objects, and the developer
performs the join.

## Decision

The **slice** is CoDev's unit of execution. The **task** is the higher-level
collection its slices belong to, and owns nothing that executes.

A slice owns:

- its branch, and the `git-state.json` recording that branch and its
  `base_snapshot`;
- its builder-and-reviewer round state, and therefore `task.check`'s
  convergence machinery, round caps, drift guard, coverage manifest, and
  every `stop_*`/`ok_*` outcome;
- its non-generated size measurement against `review.max_lines` and
  `review.max_files`;
- its work style, per [ADR-0038](0038-work-style-is-a-slice-property.md);
- its position in the stack — its predecessor slice, replacing ADR-0034's
  `parent_task` link between sibling tasks; and
- exactly one pull request.

A task owns:

- the GitHub issue and its linkage;
- the acceptance criteria, containment note, and stop-if condition;
- the owner and the independent reviewer, per
  [ADR-0037](0037-human-review-and-ownership-gate.md);
- the ordered list of slices; and
- the decision of when it is complete, which is when its last slice merges.

A change that genuinely fits in one pull request is a task holding exactly
one slice. That is the degenerate case, not the normal shape, and it is the
compatibility path: every task recorded before this decision reads as a
one-slice task, and its existing round state is that slice's round state,
with the slice's identity defaulted from the task id. No previously recorded
round is rewritten.

Auto-close behavior follows from the model rather than from a derived rule:
the task owns the issue, so only the task's final slice carries `Closes #N`
and every earlier slice carries `Part of #N`. ADR-0034 derived this from
"has a recorded child"; it is now read directly from the task's ordered
slice list.

## Alternatives considered

- **Keep the task as the unit and generate N sibling tasks from a plan's
  slice list, related by `parent_task`:** rejected. This is the shape the
  accepted brief proposed in an earlier draft and it reproduces the current
  defect at greater scale — the collection still has no representation, the
  issue, owner, reviewer, and acceptance criteria are still duplicated
  across siblings or held only by the first, and "is this the last slice?"
  stays a question answered by walking parent links instead of reading an
  ordered list.
- **Introduce the slice as a purely planning-time concept, leaving
  execution task-scoped:** rejected. The slice list is already a
  planning-time concept and that is exactly why the size discipline is lost
  at the hand-off. A concept the state machine cannot read cannot be
  enforced, which is the general principle the accepted brief draws from
  every part of CoDev that works well.
- **Rename the existing task to "slice" and add a new parent object above
  it:** rejected as a terminology change masquerading as a model change.
  ADR-0023 already renamed this object once (work item to task), and the
  cost of a second rename lands on every ADR, skill, agent file, and
  transcript that says "task" correctly. The word "task" keeps its current
  meaning as the thing a GitHub issue tracks, which is also how adopters
  already use it.
- **Allow a slice to belong to more than one task:** rejected as
  unmotivated. No observed case needs it, and it would make "the task is
  complete when its last slice merges" ambiguous.

## Consequences

- `codev task check` becomes slice-scoped. Its thirteen outcomes, round
  caps, `stop_drift` guard, and coverage manifest are unchanged in meaning;
  what changes is the object they are recorded against. The command surface
  for this is a design question, not decided here.
- ADR-0034's `parent_task` field is superseded in intent but not in
  mechanism: the stacking machinery, the `--force-with-lease`-only restack,
  the ownership check, and the post-merge refusal all stand exactly as
  accepted there. What changes is that a slice's predecessor is read from
  its task's ordered list rather than from a flat pointer between siblings.
  ADR-0034 is not superseded and must not be edited; this ADR narrows how
  its field is populated.
- ADR-0002's guarantee that the guarded CLI "operates only on the one
  branch created for the work item" now reads as one branch per *slice*.
  ADR-0034 already opened the single exception this needs; nothing further
  is authorized here.
- ADR-0001's decision to track state as local JSON files stands. The change
  is where a round-state file lives and what it is keyed by, not what it is.
- The round-state schema change is additive, and the migration is a defaulted
  field rather than a rewrite. `ROUND_SCHEMA_VERSION` must nonetheless
  increment, and the reader must accept both shapes.
- The task issue template's `Slices:` field stops being advisory prose and
  becomes the input a task's slice list is generated from. Its accepted
  decomposition strategies — preparatory refactor, contract-first,
  behavior-vertical, wiring-behind-a-guard — become recorded slice metadata.
- `codev status`'s per-task size reporting becomes per-slice, which is the
  level at which the budget was always meant to apply. A task's total size
  stays available and stays uncapped: the budget exists to bound a reviewer's
  reading, and a reviewer reads a pull request.
- Stacking remains coherent only under trunk-based development, so every
  affordance here reads `git.workflow` and disables itself under
  `feature-branch`, exactly as ADR-0033 and ADR-0034 already require.

## Revisit when

Real usage shows a task whose slices are not totally ordered — genuinely
parallel slices that could open pull requests simultaneously against the
same base — since an ordered list cannot represent that and the auto-close
rule would need a different definition of "last." Also revisit if adopters
routinely produce one-slice tasks and never use a second, which would mean
the collection is carrying no weight and the earlier, simpler model was
right.
