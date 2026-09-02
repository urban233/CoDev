**Status:** Draft
**Owner:** Martin Urban
**Last reviewed:** 2026-09-02

## Problem and users

CoDev's users are its adopters: a developer, or a small team of up to roughly
eight to ten engineers, building a product with AI-agent-driven development in
a repository that has CoDev installed.

CoDev tells those adopters to keep changes small and then makes a large pull
request the path of least resistance. Google's published engineering practices
put a change list at roughly 300 to 400 lines, and Google's own guidance for
AI-generated code raises that from a preference to a requirement: a coding
agent produces a 3,000-line diff in thirty seconds, and the reviewer who must
own every line of it is the bottleneck. Reviewers facing multi-screen
agent-authored diffs approve reflexively rather than read, which is exactly the
failure CoDev's independent-review architecture exists to prevent.

Four specific mechanisms in CoDev produce oversized pull requests today:

- **The size budget is prose that nothing measures.** The roughly 400-line,
  eight-file figure appears in `.codev/for-ai/ai-agent-guidelines.md` and in
  `build-change/SKILL.md` step 3 as advice, and nowhere as a computed value. No
  command reports how large a task's diff has grown, so an agent has no signal
  telling it when it crossed the line.
- **The advice arrives after the decision it should inform.** Both statements
  sit in implementation guidance. By the time an agent reads them, the task
  exists, the branch exists, and the issue is filed. The size of the eventual
  pull request was determined upstream, when the task was written.
- **The single-developer path has no decomposition step.**
  `ai-agent-guidelines.md`'s routing table sends a bounded feature through
  `plan-wave` only when more than one developer is involved, and `plan-wave` is
  the only skill that owns slicing work into a sequence of pull requests. A
  solo developer goes brief to `build-change` to one task to one pull request,
  whatever size that turns out to be.
- **One task, one branch, one pull request is mechanically enforced.**
  `git_ops.branch_name_for` derives a single branch name from the task id,
  `create_branch` refuses a second branch once `git-state.json` exists,
  `open_pr` refuses a second pull request for the branch, and `task.check`
  drives one round-state machine to one `ok_ready_for_pr`. Nothing in the task
  model represents a stack.

Stacking is therefore possible but unsupported. A developer can create two task
ids and pass `--base codev/<parent>` to both `codev git branch` and `codev git
open-pr`, but nothing records the relationship, nothing rebases the children
when the parent changes, `task.check` reports `stop_drift` once the parent
moves, and `git_ops._with_closes_line` writes `Closes #N` into every pull
request body, so the first slice of a three-slice stack closes the issue two
slices early.

Separately, `codev git branch` is the least guarded verb in the guarded git
surface. `commit`, `push`, and `open-pr` each check real preconditions:
`_ensure_on_own_branch`, a refusal to push the default branch, a mixed-path
commit guard, and a `task.check` gate. `create_branch` checks only that this
task has no branch recorded, then runs `git checkout -b <branch> <base>`. It
accepts a dirty worktree, silently carrying uncommitted work onto the new
branch. It accepts any `--base` a caller invents, including a stale local
`main` or, by accident, another task's branch. It does not notice that the
session is already on a task branch with unmerged work. `--base` is a required
argument with no default, which invites an agent to guess a value rather than
resolve one.

## Desired outcome

CoDev makes the small, stacked pull request the default outcome of its own
workflow rather than a discipline an agent is asked to remember. Four changes
carry that:

- **Size becomes a measured, reported property of a task**, computed against
  the task's own base snapshot, excluding generated files, and surfaced while
  splitting is still cheap rather than after the work is finished.
- **The slice decision moves upstream to where it is cheap**, into the
  implementation plan and the task issue, on the single-developer path as well
  as the team path, using one named set of decomposition strategies shared by
  `build-change` and `plan-wave`.
- **Stacking becomes a first-class capability of `codev git`**: a task records
  its parent, a child pull request targets the parent's branch and links its
  issue without closing it, and one command restacks a child onto a revised
  parent without tripping the drift guard.
- **`codev git branch` becomes as guarded as the verbs around it**, refusing
  the branch-point mistakes an agent makes silently today and resolving a
  default base rather than requiring a guessed one.

## Success measures

- `codev status` reports a non-generated changed-line and changed-file count
  for every open task, and a task that exceeds the configured budget cannot
  reach a pull request without one recorded human confirmation.
- CoDev's own next multi-part feature ships as a stack of pull requests, each
  under 400 non-generated changed lines, created and restacked through `codev
  git` rather than by hand.
- No pull request in a stack closes its tracking issue before the final slice
  merges.
- `codev git branch` refuses, with an actionable message, when run on a dirty
  worktree or from another task's branch carrying unmerged commits.

## Essential scenarios

- A developer starts a task that grows past the budget mid-implementation. The
  running size appears at each `codev git commit`, so the orchestrator proposes
  a split at 380 lines rather than discovering 900 at the pull-request
  checkpoint.
- An agent finishes a task whose diff exceeds the budget. `codev git open-pr`
  reports the measurement, and the Claude Code guardrail asks the human to
  confirm before the pull request opens, rather than opening it silently or
  refusing outright.
- A developer plans a schema change, the logic that consumes it, and the wiring
  that exposes it. They create three tasks, stack the second on the first and
  the third on the second, and open three pull requests while the first is
  still in review. The first two say `Part of #N`; the third says `Closes #N`.
- A reviewer requests changes on the first slice. The developer amends it,
  runs `codev git restack` on each child, and CoDev rebases, force-pushes with
  `--force-with-lease`, and re-baselines each child's base snapshot so
  `task.check` does not report `stop_drift`.
- An agent already on its own task branch is asked to start related work and
  reaches for `codev git branch` again. The command refuses and names the two
  correct paths: stack on the current task, or return to the default branch
  first.

## First release

### Now

- Add `codev task size`, and the same measurement inside `codev status
  --verbose`, reporting non-generated changed lines and changed files against
  the task's recorded base snapshot. Honor `.gitattributes`
  `linguist-generated` so vendored and generated files do not inflate the
  count.
- Add `review.max_lines` (default 400) and `review.max_files` (default 8)
  through `config.py`'s existing layered resolution, following the precedent
  `git.pr_base` (ADR-0013) and `git.workflow` (ADR-0033) already set. No config
  schema version change.
- Report the running size at every `codev git commit` and at `codev git
  open-pr`.
- Add `require_small_change.py`, a third `.claude/hooks/` sibling that asks for
  confirmation at `codev git open-pr` when a task exceeds its budget. It asks,
  never denies, and fails open on any internal error, matching
  `require_plan.py` and `require_wave_shape.py`.
- Add a `Slices:` field to `implementation-plan.template.md` and
  `.github/ISSUE_TEMPLATE/task.md`, beside the existing `Containment:` field:
  either one pull request with an estimated size, or an ordered list of two to
  four slices, each naming its boundary type.
- Name the four decomposition strategies once and use the same vocabulary in
  `build-change` step 3 and `plan-wave` step 3: preparatory refactor,
  contract-first, behavior-vertical, and wiring-behind-a-guard.
- Harden `codev git branch`: refuse a dirty worktree unless `--allow-dirty`,
  refuse when HEAD is on another task's branch carrying commits beyond its own
  base, default `--base` to `git.pr_base` and then the repository's default
  branch instead of requiring it, and warn when the resolved base is behind its
  remote counterpart.
- Add `codev git` mutation subcommands to `require_plan.py`'s gated Bash
  prefixes. The guarded path currently bypasses the plan-first guardrail while
  raw `git checkout` triggers it.
- Add `codev git branch --stack-on <task-id>`, recording `parent_task` in the
  child's `git-state.json` and resolving the parent's branch as the base.
- Make `codev git open-pr` stack-aware: default `--base` to the parent's branch
  while the parent's pull request is open, and write `Part of #N` rather than
  `Closes #N` for every slice that is not the last in its stack.
- Add `codev git restack --id <id>`: rebase the child onto its updated parent,
  push with `--force-with-lease`, and re-baseline `base_snapshot` through the
  same path `codev task reopen` already uses, so `task.check` does not report
  `stop_drift`.
- Render the stack in `codev status`, and ask for confirmation past a depth of
  three.

### Next

- `codev task start --slice-of <parent-id>`, so a second slice inherits the
  parent's GitHub issue link without filing a new issue.
- A branch-age signal in `codev status`, already named as a Next item in
  `docs/features/plan-wave/brief.md`.
- Automatic cascading restack across a whole stack from one command, rather
  than one `codev git restack` call per child.

### Not planned

- Integration with Graphite, `gh stack`, or any external stacking tool. CoDev
  drives plain Git and the `gh` CLI it already depends on.
- Any change to how `task.check` decides convergence, beyond the base-snapshot
  re-baselining that `restack` reuses.
- A machine-checked containment mechanism, or CoDev shipping feature-flag
  infrastructure. ADR-0033 already rejected that, and the `Slices:` field is
  advisory prose for the same reason the `Containment:` field is.
- Enforcing a size budget on human-authored pull requests that never passed
  through a CoDev task.

## Constraints

- Every new gate asks and pauses; none refuses outright. This matches ADR-0030's
  established posture and `require_wave_shape.py`'s precedent.
- Stacking is coherent only under trunk-based development. Every stacking
  affordance reads `git.workflow` and disables itself cleanly under
  `feature-branch`, as ADR-0033 requires of every prompt it introduced.
- A target repository never imports CoDev as a runtime dependency. Size
  measurement uses Git and `.gitattributes`, not an installed library.
- `codev git restack` force-pushes. It is the first CoDev command that rewrites
  already-pushed history, so it must refuse on a branch it does not own, refuse
  once the parent's pull request has merged, and never use a bare `--force`.
- One task, one branch, one pull request is not an accepted decision anywhere
  in `docs/adr/`; `git_ops.create_branch` and `git_ops.open_pr` simply
  implement it. Making stacking first-class changes the task-to-pull-request
  relationship across the workflow contract, the skills, and the CLI, so it
  needs its own ADR under ADR-0025's practice, not a design-document footnote.

## Assumptions and discovery

| Assumption | Evidence needed | Owner | Decision point |
|---|---|---|---|
| `.gitattributes` `linguist-generated` is a sufficient generated-file signal for the size measurement, without a second CoDev-specific exclude list | Measure CoDev's own recent merged pull requests both ways and compare | Implementer | Before `design.md` is accepted |
| Re-baselining `base_snapshot` through `task reopen`'s existing path is safe for a restack, which is a rebase rather than a new round | Read `task.reopen`'s round-state handling and prototype one restack against a two-task stack | Implementer | Before `design.md` is accepted |
| Determining "last slice in the stack" for the `Part of` versus `Closes` decision can be resolved from recorded parent links alone, without a new explicit flag | Prototype against a three-task stack | Implementer | During implementation |
| One measurement threshold pair serves both the commit-time nudge and the open-pr gate, without separate budgets | Real usage on CoDev's own next feature | Martin Urban | After first release |

## Acceptance

- [ ] Outcome, scope, non-goals, and success measures accepted by the accountable human.
