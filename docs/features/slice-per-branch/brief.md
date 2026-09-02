**Status:** Draft
**Owner:** Martin Urban
**Last reviewed:** 2026-09-02

## Problem and users

CoDev's users are its adopters: a developer, or a small team, building a
product in a repository that has CoDev installed, with a strict review and
ownership policy over AI-generated code.

[ADR-0035](../../adr/0035-slice-is-the-unit-of-execution.md) made the slice the
unit of execution and the task the collection its slices belong to. A slice, it
says, owns "its branch ... and exactly one pull request."

**It does not.** The model landed in the state layer and stopped there. The
guarded git surface still works one branch per *task*, so a task holding three
slices has one branch and can open one pull request. Direct inspection on
2026-09-02 confirms the gap:

- `git_ops.branch_name_for` derives exactly one branch name, `codev/<task-id>`,
  from a task id. Nothing derives a branch from a slice id.
- `create_branch` refuses once `git-state.json` exists for that task, so a
  second slice cannot get a branch through the guarded surface at all.
- `git-state.json` records one `{branch, base_snapshot, parent_task}` per task.
  There is no per-slice equivalent.
- `open_pr` refuses when the branch already has an open pull request, so slice
  two cannot open one while slice one is in review.
- `task.advance_slice` moves `current_slice`, opens a round, and re-baselines
  `base_snapshot` — and touches no branch and no pull request.

The result is a model that describes the right thing and a surface that cannot
perform it. A developer who declares three slices gets three recorded round
groups on one branch, and must either land them as one pull request — losing
the entire point — or create the branches by hand outside `codev git`, which
the guarded surface can then neither see nor protect.

Three specific consequences make this worse than "a feature not built yet":

- **The stacking machinery is stranded.** ADR-0034 built `--stack-on`,
  `codev git restack`, and the `Part of #N` / `Closes #N` logic for stacks of
  *sibling tasks*. ADR-0035 then made slices the thing that should stack.
  Neither mechanism now describes a whole workflow on its own.
- **The size budget measures something that cannot ship separately.**
  `slice_size` correctly measures from the current slice's base, and a
  developer can be told a slice is within budget while having no way to open a
  pull request for that slice alone.
- **The gap is invisible from the code.** Every function involved behaves
  correctly in isolation. Nothing fails, nothing warns; the workflow simply
  cannot be completed as the accepted model describes it.

## Desired outcome

A slice is a pull request in mechanism, not only in the model. Declaring three
slices and working them produces three branches and three pull requests through
`codev git`, each independently reviewable, each restackable when an earlier
one changes, with only the last closing the task's issue.

The `--stack-on` sibling-task form and the slice form stop being two answers to
the same question. One of them becomes the workflow; the other is either
expressed in terms of it or explicitly retired.

## Success measures

- A task declared with three slices produces three branches and three pull
  requests without a developer creating a branch by hand or leaving
  `codev git`.
- `codev task advance-slice` creates and checks out the next slice's branch,
  based on the previous slice's head, without a separate command.
- Amending an earlier slice after review and restacking updates its children
  without any of them reporting `stop_drift`.
- Only the final slice's pull request closes the task's issue; the others say
  `Part of #N`.
- `codev next` recommends opening a pull request for the current slice, and
  after it merges recommends advancing — with both actions available.

## Essential scenarios

- A developer accepts a plan with a schema change, the logic consuming it, and
  the wiring exposing it. Three branches and three pull requests exist while
  the first is still in review.
- A reviewer requests changes on the first slice. The developer amends it, and
  the two children are rebased and re-baselined so no drift is reported.
- A task with exactly one slice behaves precisely as it does today: one branch,
  one pull request, no stack.
- A developer runs `codev task advance-slice` on a slice whose pull request has
  not merged. CoDev says what state the previous slice is in, rather than
  branching from unlanded work by accident.
- An existing task created before this change continues on its single branch
  without migration.

## Open questions carried into design

**How is a slice's branch named?** `codev/<task-id>` is taken. `codev/<task-id>/<slice-id>` reads well and nests, but a slash in a branch name forbids a
sibling ref of the same prefix — `codev/auth` and `codev/auth/schema` cannot
both exist, which breaks exactly the one-slice-then-many case. This must be
settled before anything else.

**Does `git-state.json` gain slices, or does each slice get its own record?**
The file is currently one object per task. ADR-0035's shape argues for per-slice
records; ADR-0002's guarantees are written in terms of "the one branch created
for the work item" and would need restating either way.

**What happens to `--stack-on`?** Sibling-task stacking and slice stacking now
solve the same problem twice. Superseding ADR-0034 is the honest option, but it
would strand any adopter who already has a sibling stack open.

**Should `advance-slice` require the previous slice to have merged?** Requiring
it makes stacking pointless — the parallelism is the point. Not requiring it
means branching from unreviewed work, which is what stacking is, but the
command should say so rather than doing it silently.

## First release

Ordered so the branch-naming decision lands before anything that depends on
it, since every other piece of the git surface reads a branch name.

### Now

- Settle the branch-naming question, since every other decision depends on it.
- Per-slice branch records, with a one-slice task keeping today's exact shape.
- `codev git branch` creates the current slice's branch; `advance-slice`
  creates and checks out the next one from the previous slice's head.
- `open_pr` opens one pull request per slice, based on the previous slice's
  branch, and `Part of #N` / `Closes #N` reads the slice list as it already
  does.
- `codev git restack` cascades across a task's own slices.

### Next

- Retire or re-express `--stack-on` once slice stacking is proven in use.
- Teach `codev next` the slice-boundary positions this makes reachable.

### Not planned

- Migrating existing single-branch tasks. They continue as they are.
- Integration with an external stacking tool, per
  `docs/features/small-prs/design.md`.
- Automatic merging of any slice. Merge stays a human decision.

## Constraints

- Additive to the round-state schema; ADR-0001's local-JSON storage stands.
- A task with one slice keeps today's behavior exactly, including its branch
  name.
- Stacking stays coherent only under trunk-based development, and every
  affordance disables itself under `feature-branch` (ADR-0033, ADR-0034).
- Every new gate asks and pauses rather than refusing (ADR-0030).
- Force-pushing stays bound by ADR-0034's standard: `--force-with-lease` only,
  ownership-checked, refused once the parent's pull request has merged.

## Assumptions and discovery

Martin Urban owns every assumption below as the accountable human.

| Assumption | Evidence needed | Decision point |
|---|---|---|
| A branch-naming scheme exists that nests slices without forbidding a sibling ref | Try the candidate schemes against real `git` on a one-slice and a three-slice task | Before design |
| Per-slice branch records need no round-state change | Prototype the record and check whether `check`'s drift guard reads anything that moves | Before design |
| No adopter depends on `--stack-on`'s sibling form | Confirm against this repository's own history and any known adopter | Before deciding ADR-0034's fate |
| Restacking a task's own slices reuses `restack` rather than needing a second path | Walk the existing implementation against a three-slice cascade | During the restack slice |

## Acceptance

- [ ] Outcome, scope, non-goals, and success measures accepted by the
      accountable human.
- [ ] The branch-naming question settled, and recorded wherever it binds later
      design.
- [ ] `--stack-on`'s future decided: superseded, re-expressed, or retained
      alongside, with an ADR if ADR-0034 changes meaning.
