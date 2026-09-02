---
title: Roles
description: Every agent CoDev installs, what it may do, and what it may never do.
---

CoDev installs a set of agents with deliberately unequal powers. The
constraints are the design: an agent that can both write code and approve it
is not a review system.

You start two of them. The rest are invoked for you.

## The ones you start

| Agent | Phase | What it does |
|---|---|---|
| `planner` | Specify, Understand, Design, Plan | Everything upstream of a ready task. Never implements product code, never invokes the build agents |
| `orchestrator` | Build, Review, Ship | Frames the change, delegates it, records evidence, opens the pull request. **Never edits product code itself** |
| `outer-loop-runner` | Review → Ship | Takes a task with an open pull request through specialist review to a human-ready state |

`planner` and `orchestrator` are separate entry points on purpose. Handing a
ready task from one to the other is your decision, not an automatic
continuation.

## The inner loop

| Agent | What it does | What it may not do |
|---|---|---|
| `builder` | Executes one accepted plan. Edits and tests | Invoke other agents, commit, push, merge, deploy, or alter accepted authority |
| `lightweight-reviewer` | A fast, narrow check: correctness, intent-match, and independent re-verification that the builder's validation actually passes | Edit code, talk to the builder, or authorize merge |
| `code-audit-gate` | An automatic pre-pull-request pass over style and documentation only | Touch logic or behavior |

`code-audit-gate` is autonomous by design — nothing in its scope needs
approval — and it finishes *before* the reviewer round is recorded, so
mechanical cleanup never spends any of the outer loop's round budget.

## The outer loop

Five specialists review the exact diff in parallel once the pull request is
open. You choose which to dispatch; skipping one is offered as a recorded
waiver with a reason, never assumed.

| Specialist | Dimensions it owns |
|---|---|
| `correctness-tests-specialist` | Correctness, error handling, test quality |
| `security-data-specialist` | Security, privacy, data, compatibility |
| `concurrency-specialist` | Concurrency and race conditions |
| `architecture-maintainability-specialist` | Architecture, scope, maintainability |
| `rollout-specialist` | Rollout, monitoring, migration, rollback |

**None of them is a reviewer in the sense that matters for merge.** They are a
presubmit. They produce machine evidence, and it is labelled as such in the
pull-request body. The approval that lets a change land comes from a human who
is neither the task's owner nor a bot.

## The invariant

> An agent may write code, or it may review code. Never both, for the same
> change.

`builder` cannot review. Reviewers cannot edit. `orchestrator` never writes
product code. An agent may check its own work; it may never approve it.

## Next

- [The Workflow](/CoDev/concepts/) — the phases and the two loops
- [Slices and Stacks](/CoDev/slices/) — what one agent works on at a time
