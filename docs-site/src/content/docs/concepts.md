---
title: The Workflow
description: The mental model behind CoDev — the phases, the two loops, and who decides what.
---

You talk to an agent. The agent runs CoDev. This page is the model behind
that conversation — not the commands, which live in the
[CLI reference](/CoDev/cli-reference/) and which you will not have to type.

## The phase spine

```text
Specify → Understand → Design → Plan → Build → Review → Ship → Launch
```

**Build, Review, and Ship are the only universal phases.** Everything else is
an on-ramp your change may skip. A one-line bug fix enters at Build. A new
product enters at Specify. Most work enters at Understand.

| Phase | You are here when | Skipped when |
|---|---|---|
| Specify | A whole product is new, or being redesigned | Almost always |
| Understand | An idea or request needs its outcome settled | The change is trivial and obvious |
| Design | Architecture, a contract, or a cross-component trade-off is at stake | The implementation is obvious and local |
| Plan | Several developers or several waves must be coordinated | One bounded change, one developer |
| Build | Always | Never |
| Review | Always | Never |
| Ship | Always | Never |
| Launch | Flags, migration, or staged exposure carry real risk | Internal or low-risk work |

## The unit of work: task and slice

A **task** is what a GitHub issue tracks. It owns the acceptance criteria, the
owner, the independent reviewer, and an ordered list of slices.

A **slice** is what actually gets built. It owns a branch, a round of
builder-and-reviewer work, a size budget, and **one pull request**.

A change that genuinely fits in one pull request is a task holding exactly one
slice. That is the small case, not the normal shape — see
[Slices and Stacks](/CoDev/slices/).

## Two loops

Review is layered, and the layers do different jobs.

**The inner loop** runs per slice, before any pull request exists. A bounded
builder makes the change; a fast reviewer checks it for correctness and
intent-match and independently re-runs the validation. They iterate under a
round cap. Immediately before the pull request opens, an automatic gate fixes
style and documentation drift.

**The outer loop** runs once the pull request is open. Up to five specialist
reviewers — correctness and tests, security and data, concurrency,
architecture and maintainability, rollout — examine the exact diff in
parallel. A human triages what they find.

**Neither loop approves anything.** Both produce evidence.

## Who decides what

| Decision | Who |
|---|---|
| Whether the plan is right | You |
| Whether the code is correct | The loops produce evidence; a human reads it |
| Whether the change may land | An independent human reviewer — not the person who directed it |
| Merge, deploy, migrate, release | You, always |

The last row is the point of the whole system. When an AI writes the code, the
developer who directed it is its **author**, not its reviewer — so their
signature says *"I own this"*, and a different human supplies the approval.

## Where you are, without asking

At every boundary the agent tells you where the work stands and what it
recommends next, because CoDev computes it rather than leaving the agent to
remember a sequence:

```text
Position: inner phase, round 1
Next: correct the findings
Why: the reviewer asked for changes and the round cap allows another pass
```

You never have to know that a draft pull request means specialist review is
next, or that a blocking finding must be triaged first.

## When it stops

CoDev stops and hands back to you when the round cap is spent, when the same
finding recurs, when scope quietly expands, when the code changed outside the
tracked flow, or when a decision is not the agent's to make. Each one is a
named stop with a reason — not a silent retry.

## Next

- [How CoDev Works](/CoDev/onboarding-guide/) — the longer walk through the same model
- [Roles](/CoDev/roles/) — every agent, and what it may and may not do
- [Talking to Your Agent](/CoDev/working-with-your-agent/) — what you actually say
