**Status:** Draft
**Owner:** Martin Urban
**Reviewers:** Martin Urban (accountable owner)
**Brief:** [brief.md](./brief.md)
**Last reviewed:** 2026-09-02

## Summary

Make the small, stacked pull request the default outcome of CoDev's workflow
by turning its existing 400-line advice into a measured property, moving the
slice decision upstream into the implementation plan, giving `codev git`
native stacking, and hardening `codev git branch` to the same standard as the
verbs around it. The size budget resolves through `config.py` as
`review.max_lines` and `review.max_files`, following the mechanism `git.pr_base`
(ADR-0013) and `git.workflow` (ADR-0033) already established. Stacking changes
the task-to-pull-request relationship that `git_ops` currently hardcodes, so it
carries its own ADR. Every new gate asks and pauses rather than refusing,
matching ADR-0030's posture.

## Goals and non-goals

### Goals

- A task's size is a computed number that CoDev reports before the pull request
  opens, not prose an agent is asked to estimate.
- Every path to implementation, including the single-developer path that skips
  `plan-wave`, records an explicit slice decision before editing.
- A stack of dependent pull requests is a supported CoDev workflow: created,
  linked, described, and restacked through `codev git`.
- `codev git branch` refuses the branch-point mistakes an agent currently makes
  silently, and resolves a default base rather than requiring a guessed one.

### Non-goals

- Integration with Graphite, `gh stack`, or any external stacking tool.
- Any change to how `task.check` decides convergence, beyond reusing
  `task.reopen`'s base-snapshot re-baselining inside `restack`.
- A machine-checked containment or slice field. Both stay advisory prose, for
  the reason ADR-0033 already recorded.
- Enforcing a size budget on human-authored pull requests that never passed
  through a CoDev task.

## Current system and evidence

Confirmed by direct repository inspection on 2026-09-02.

**The size budget exists only as prose.** `.codev/for-ai/ai-agent-guidelines.md`
says to treat "roughly 400 non-generated changed lines or eight files as a
prompt to reconsider slicing the work -- not a hard limit," and
`build-change/SKILL.md` step 3 repeats it as a soft warning. No module computes
either number. `git_ops.changed_files` (`git_ops.py:466`) already runs `git diff
--name-only <base_snapshot> <branch>` and returns an empty list rather than
raising when a task has no branch recorded, because it backs `codev status
--verbose`'s informational overlap check. It reports names, never counts.

**The task-to-pull-request relationship is accepted, not merely
implemented.** `git_ops.branch_name_for` derives exactly one branch name,
`codev/<task-id>`, from a task id. `create_branch` refuses once
`git-state.json` exists for that task, and records only `{"branch",
"base_snapshot"}`. `open_pr` refuses when the branch already has an open
pull request. ADR-0002 already accepts this as durable, not just as an
implementation choice: its guarded-CLI decision states the wrapper
"operates only on the one branch created for the work item... never the
branch checked out at run start." Stacking narrows that guarantee -- a
task with no `--stack-on` keeps the exact original behavior -- but it is
still a real amendment to an accepted decision, scoped to that one clause,
which is why it needs its own ADR rather than a design-document footnote.

**A stack would break issue linkage today.** Both pull-request body paths write
an auto-close line. `_with_closes_line` (`git_ops.py:361`) appends `Closes #N`
to the standalone body, and `_render_pr_template` (`git_ops.py:373`) fills the
template's `<!-- codev:closes -->` marker with the same string. Both derive `N`
from `_closes_issue_number`, which confirms the recorded `link_ref` names this
repository's own issue before returning a number. A three-slice stack would
therefore close its tracking issue when the first slice merged.

**A stack would also trip the drift guard.** `task.check` compares the supplied
head against `state["base_snapshot"]` and reports `stop_drift` on a mismatch
(`task.py:754`). Rebasing a child onto a revised parent changes exactly that.
`task.reopen` already re-baselines the field in place (`task.py:958`) and
appends to the item's `reopens` history, which is the mechanism a restack can
reuse rather than reinvent.

**`codev git branch` is the least guarded verb in the guarded surface.** Its
siblings each check real preconditions: `_ensure_on_own_branch`
(`git_ops.py:491`) gates `commit`, `push`, `open_pr`, and `mark_ready`; `push`
(`git_ops.py:585`) refuses the repository's default branch;
`_refuse_if_mixed_dirty_paths` blocks a path-less `git add -A` that mixes
CoDev-managed and product changes; `open_pr` gates on a `task.check` result.
`create_branch` checks only for a recorded branch, then runs `git checkout -b`.
It inspects neither the worktree's cleanliness, nor which branch HEAD is
currently on, nor whether `--base` resolves to something current. `--base` is
`required=True` in the CLI (`cli.py:648`), so an agent must supply a value it
has no guidance for.

**The guarded path is less gated than the raw path.**
`.claude/hooks/require_plan.py` matches Bash commands against
`_DESTRUCTIVE_BASH_PREFIXES`, which lists `git commit`, `git push`, `git
checkout`, and six others. It contains no `codev git` entry, so `codev git
branch` bypasses the plan-first guardrail entirely while raw `git checkout`
triggers it. The hook allows every `docs/` path unconditionally, fails open on
any internal error, and is registered alongside `require_wave_shape.py` in
`.claude/settings.json` under `PreToolUse`.

**The config mechanism is ready.** `config.DEFAULTS` (`config.py:46`) currently
holds one entry, `"git.workflow": "trunk"`, and `resolve(key, *, target,
override)` layers flag, environment variable, project config, global config,
then default. `set_value` quotes dotted keys correctly, a bug class ADR-0013
already fixed. Two new keys need no new resolution logic and no schema version
change.

**Decomposition guidance already exists but is unreachable on the solo path.**
`plan-wave/SKILL.md` step 3 says a task "should normally produce one small pull
request or a short stack of independently valid pull requests, split by
behavior rather than by technical layer," and ADR-0033 extended that under
`git.workflow=trunk` to allow an engineering-dependency split with a stated
containment. `ai-agent-guidelines.md`'s routing table reaches `plan-wave` only
when more than one developer is involved.

## Proposed design

### Components and ownership

| Component | Responsibility | Owner | Existing or new |
|---|---|---|---|
| `task.size` | Count non-generated changed lines and files against a task's base snapshot | `src/codev_workflow/task.py` | New |
| `review.max_lines` / `review.max_files` keys | Configurable size budget, default 400 and 8 | `config.py` `DEFAULTS` | New |
| `codev task size` | Report one task's measurement; also surfaced by `codev status --verbose` | `cli.py` | New |
| `require_small_change.py` | Ask at `codev git open-pr` when a task is over budget | `.claude/hooks/` | New |
| `Slices:` template field | Record the intended pull-request sequence before editing | `implementation-plan.template.md`, `.github/ISSUE_TEMPLATE/task.md` | Extended |
| Decomposition vocabulary | One named set of four split strategies | `build-change/SKILL.md`, `plan-wave/SKILL.md` | Updated prose |
| `create_branch` preconditions | Refuse a dirty worktree, a foreign task branch, and a stale base | `git_ops.py` | Extended |
| `--stack-on` and `parent_task` | Record and resolve a child task's parent | `git_ops.py`, `cli.py` | New |
| Stack-aware pull-request body | `Part of #N` for a non-final slice, `Closes #N` for the last | `git_ops.py` | Extended |
| `codev git restack` | Rebase a child onto its revised parent and re-baseline it | `git_ops.py`, `cli.py` | New |
| `codev git` prefix gating | Bring the guarded path under the plan-first guardrail | `.claude/hooks/require_plan.py` | Extended |

### Data and control flow

`git-state.json` gains one optional field, `parent_task`, written by
`create_branch` when `--stack-on` is supplied. Its absence means the task sits
directly on the base branch, which is every task that exists today, so the file
stays backward-compatible without a version marker.

Size measurement runs `git diff --numstat <base_snapshot> <branch>`, drops every
path that `git check-attr linguist-generated` marks as generated, and sums the
remainder. `task.size` returns the line total, the file total, and the resolved
budget, so the CLI, `codev status --verbose`, and the hook all read one
implementation rather than three approximations. `codev git commit` prints the
resulting counts after committing, which is the point at which an agent can
still split cheaply.

At the pull-request checkpoint, `codev git open-pr` prints the measurement and
proceeds. On Claude Code, `require_small_change.py` intercepts the same command
in `PreToolUse`, runs `codev task size --json`, and asks for confirmation when
either count exceeds its budget. As with both existing hooks, it asks rather
than denies, and any internal error allows the call.

For a stacked task, `open_pr` resolves its base in a new first position: the
parent's branch when `parent_task` is recorded and that parent's pull request
is still open, then the explicit `--base`, then `git.pr_base`, then the
repository's default branch. It writes `Part of #N` instead of `Closes #N`
whenever the task has a child recorded against it, so only the last slice in a
stack carries the auto-close link.

`codev git restack --id <child>` verifies it is on the child's own branch,
refuses when the parent's pull request has already merged, rebases the child
onto the parent's current head, force-pushes with `--force-with-lease`, and
re-baselines `git-state.json`'s `base_snapshot`. On the `task.py` side, a new
`record_restack` (not `reopen` -- see the resolved open question below)
updates `base_snapshot` and, if the current round already recorded a
builder or reviewer verdict, that verdict's own `head_snapshot` too, so
`task.check`'s drift comparison keeps matching the rebase's new commit
identity. It records the restack in the item's own history rather than
opening a new round, because a rebase produces no new review evidence.

### APIs and contracts

| Contract | Guarantees and errors | Compatibility |
|---|---|---|
| `task.size(task_id, *, target) -> SizeReport` | Returns line count, file count, and resolved budget. Returns zeros rather than raising when the task has no branch recorded, matching `changed_files`'s established posture | New function; no existing caller changes |
| `config.resolve("review.max_lines" \| "review.max_files")` | Flag, environment variable, project, global, then `DEFAULTS` of `400` and `8`. A non-integer configured value falls back to the default and warns | New keys; no config schema version change |
| `git-state.json` `parent_task` | Optional string task id. Absent for every task created before this change | Additive; readers must tolerate its absence |
| `create_branch(..., stack_on=None, allow_dirty=False)` | Raises `GitOpsError` on a dirty worktree, on a HEAD that is another task's branch with commits beyond its base, or on an unresolvable base. Warns when the resolved base is behind its remote counterpart | `--base` becomes optional; existing callers passing it keep working |
| `restack(task_id, *, target)` | Rebases, force-pushes with `--force-with-lease`, re-baselines `base_snapshot`. Raises rather than force-pushing when the parent's pull request has merged, when HEAD is not the child's branch, or when the rebase reports a conflict | New command; leaves conflicts for the human, never resolves them |
| `require_small_change.py` `PreToolUse` hook | Asks on an over-budget `codev git open-pr`; allows on an unparseable payload or any internal error | New file; Claude Code only in this release |

## Alternatives and trade-offs

| Decision | Option | Benefits | Costs and risks | Recommendation |
|---|---|---|---|---|
| Where the budget bites | Measure and report only | Zero friction | Close to today's prose; an agent reads past a warning as easily as past a sentence | Rejected |
| Where the budget bites | Ask at `open-pr` through a hook, plus report at every commit (this design) | One human decision at the one irreversible-looking moment; matches `require_wave_shape.py` | Claude Code only; other platforms get the printed number and nothing more | **Recommended** |
| Where the budget bites | Refuse `open-pr` over budget without `--oversize <reason>` | Strongest guarantee, and the reason enters the evidence trail | The first hard block in the workflow, against ADR-0030's stated posture | Rejected for this release |
| Stacking mechanism | Document plain-git stacking in the skills only | No CLI change | Stacking stays manual; CoDev keeps mechanically enforcing one pull request per task | Rejected |
| Stacking mechanism | `--stack-on` only, manual rebase for cascades | Smaller change | Leaves the step that actually hurts, the cascade after review feedback, unautomated | Rejected |
| Stacking mechanism | Native `--stack-on`, stack-aware base and issue linkage, and `restack` (this design) | Full support for the workflow the brief targets | Introduces CoDev's first history-rewriting command; needs its own ADR | **Recommended** |
| Generated-file exclusion | `.gitattributes` `linguist-generated` via `git check-attr` | Reuses a signal review tooling already honors; no CoDev-specific list to maintain | A repository without the attribute set gets inflated counts | **Recommended**, listed as an assumption to verify |
| Generated-file exclusion | A CoDev-owned exclude list in config | Works without repository setup | A second source of truth that drifts from what GitHub actually collapses | Deferred |
| Slice field enforcement | Machine-checked slice plan | Would catch an unfilled field | Same objection ADR-0033 recorded against machine-checking containment: free text describing intent cannot be validated usefully | Rejected |

## Quality and risk

- **The force-push is the sharpest edge here.** `codev git restack` is the
  first CoDev command that rewrites already-pushed history. It uses
  `--force-with-lease` and never a bare `--force`, refuses when HEAD is not the
  child's own branch, refuses once the parent's pull request has merged, and
  stops on a rebase conflict rather than resolving one. A human resolves
  conflicts; CoDev reports them.
- **Reliability.** `require_small_change.py` fails open on any internal error,
  exactly like both existing hooks. A bug in it degrades to no extra check,
  never to no pull request possible.
- **Security and privacy.** Size measurement reads local Git state only. The
  hook reads repository state and resolved config. Neither adds a network
  dependency; `restack` uses the `gh` and `git` access CoDev already has.
- **False positives, named explicitly.** A repository that does not mark
  generated files with `linguist-generated` will see inflated counts and one
  extra confirmation prompt. That costs a click, never a block.
- **Compatibility.** `parent_task` is additive and optional. `--base` becoming
  optional keeps every existing invocation valid. The size keys are new. No
  state file changes shape for a task that never stacks.
- **Interaction with `git.workflow`.** Stacking affordances read
  `git.workflow` and disable themselves under `feature-branch`, as ADR-0033
  requires. The size measurement and the branch hardening apply under both
  workflows, because neither depends on trunk-based development.

## Test strategy

Unit tests for `task.size` cover a task with no branch recorded, a diff with
generated files present, and a repository with no `.gitattributes`. Config
round-trip tests for both new keys mirror `PersistenceTests`'s existing
dotted-key regression test. `git_ops` tests cover each new `create_branch`
refusal, base resolution order for a stacked task, the `Part of` versus `Closes`
decision across a three-task stack, and `restack`'s refusals, using the
temporary-repository fixtures `tests/test_git_ops.py` already establishes.
Fixture-stdin tests for `require_small_change.py` follow
`tests/test_wave_shape_hook.py`, the nearest existing sibling, and
`tests/test_claude_hook.py` before it, so they need no Claude Code install. One new behavioral scenario in
`scripts/validate-development-workflow.py` covers a task planned as a stack.

`restack`'s force-push path is tested against a local bare remote in a
temporary directory, never against a real GitHub repository.

## Delivery slices

This feature is the argument for its own shape, so it ships as a stack rather
than one change. Each slice stays under the budget it introduces and is safe to
merge alone.

| Slice | Contents | Depends on |
|---|---|---|
| 1 | `task.size`, the two config keys, `codev task size`, and the `status --verbose` line | None |
| 2 | `Slices:` template field and the shared decomposition vocabulary in `build-change` and `plan-wave` | None |
| 3 | `create_branch` preconditions, optional `--base`, and `codev git` in `require_plan.py`'s gated prefixes | None |
| 4 | `require_small_change.py` and its registration in `.claude/settings.json` | Slice 1 |
| 5 | The stacking ADR | None |
| 6 | `--stack-on`, `parent_task`, and stack-aware base resolution | Slices 3 and 5 |
| 7 | `Part of` versus `Closes`, and stack rendering in `codev status` | Slice 6 |
| 8 | `codev git restack` | Slice 6 |

Slices 1, 2, 3, and 5 have no dependency on each other and can proceed in
parallel or in any order.

## Migration, rollout, rollback, and cleanup

Purely additive. No existing state file changes shape, no command loses an
argument, and every task created before this ships keeps working with
`parent_task` absent.

Like `git.workflow` before them, `review.max_lines` and `review.max_files`
take effect for every adopter on update without an opt-in, so the changelog
calls out the new commit-time reporting and the new confirmation prompt
explicitly. Rollback for one project is raising the budget with `codev config
set review.max_lines <n>`; because the gate only ever asks, declining a prompt
costs nothing further. A project that does not want stacking simply never
passes `--stack-on`, and one on `git.workflow=feature-branch` never sees the
affordance at all.

## Open questions

| Question | Owner | Evidence needed | Blocking? |
|---|---|---|---|
| ~~Is `.gitattributes` `linguist-generated` a sufficient generated-file signal on its own?~~ | Martin Urban | Resolved 2026-09-02: yes, `linguist-generated` only, no CoDev-owned fallback list. CoDev's own repository has no `.gitattributes` today, so the exclusion is inert here until one is added -- an accepted, named limitation, not a gap to patch with a second exclude list | Resolved |
| ~~Can `restack` reuse `task.reopen`'s re-baselining directly, or does a rebase need a distinct code path?~~ | Implementer | Resolved 2026-09-02: no, a distinct code path (`task.record_restack`) was needed. `reopen` unconditionally appends a new round and consumes round-cap budget; `task.check`'s drift comparison reads the *latest round's own* `head_snapshot`, not just `base_snapshot`, so re-baselining only `base_snapshot` (as originally described) would not have cleared drift for a task with any recorded builder/reviewer evidence -- confirmed with a real prototype in `RecordRestackTests` | Resolved |
| Can "last slice in the stack" be derived from recorded parent links alone, or does it need an explicit flag on the final task? | Implementer | Prototype against a three-task stack | No; the fallback is an explicit flag |
| Do the commit-time nudge and the open-pr gate need separate thresholds? | Martin Urban | Real usage on CoDev's own next feature | No; ship one pair, split later if it proves too coarse |

## Acceptance

- [x] Both blocking open questions resolved.
- [x] Stacking ADR written and accepted: [ADR-0034](../../adr/0034-stacked-task-branches.md).
- [ ] Accountable human accepts planning against this design.
