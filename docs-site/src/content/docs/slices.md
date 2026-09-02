---
title: Slices and Stacks
description: Why CoDev splits work into slices, and how a stack of small pull requests gets built and kept current.
---

A coding agent produces a thousand-line diff in under a minute. The reviewer
who has to own every line of it is the bottleneck — and a reviewer facing a
multi-screen agent-authored diff approves reflexively rather than reads.

That is the failure CoDev's whole review architecture exists to prevent, so
CoDev makes the small pull request the default outcome rather than a
discipline an agent is asked to remember.

## Task and slice

A **task** is the collection. It owns the GitHub issue, the acceptance
criteria, the owner, the independent reviewer, and an ordered list of slices.
It owns nothing that executes.

A **slice** is the unit that executes. It owns a branch, a round of
builder-and-reviewer work, a size budget, a work style, and one pull request.

A change that genuinely fits in one pull request is a task with exactly one
slice — the small case, not the normal shape.

## Choosing slices

The slice decision belongs in the implementation plan, before the branch
exists, because that is when splitting is still cheap. Four named strategies:

| Strategy | Use it when |
|---|---|
| Preparatory refactor | The change is easy once the ground is moved; move the ground first, changing no behavior |
| Contract-first | A shared interface can land before anything consumes it |
| Behavior-vertical | A thin end-to-end path can work before the next one starts |
| Wiring behind a guard | The code can land complete but unreachable, behind a flag |

## The size budget

The budget is roughly 400 non-generated changed lines and eight files, and it
applies **per slice**, because a reviewer reads one pull request.

A task's total is reported and never capped. A task deliberately split into
four slices is *supposed* to total more than one slice's budget.

Going over is a prompt to reconsider, not a refusal: CoDev pauses and asks
before the pull request opens, with the measurement in front of you.

## Stacks

Dependent slices do not wait for each other to merge. A later slice branches
from the previous one, and the stack keeps moving while the first is still in
review.

Two things follow automatically:

- **Only the last slice closes the issue.** Earlier ones say `Part of #N`, so
  a three-slice task does not close its issue when the first third lands.
- **Restacking is supported.** When review changes an earlier slice, the
  children are rebased onto it and their recorded snapshots re-baselined, so
  the drift guard does not fire on a rebase you asked for.

Stacking is coherent only under trunk-based development, and every stacking
affordance disables itself when the project is configured for feature
branches.

## Next

- [The Workflow](/CoDev/concepts/) — where slices sit in the phases
- [Roles](/CoDev/roles/) — who builds and who reviews a slice
