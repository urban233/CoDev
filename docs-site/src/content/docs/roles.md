---
title: Roles
description: Every agent CoDev installs, what it may do, and what it may never do.
---

CoDev installs a set of agents with deliberately unequal powers. The
constraints are the design: an agent that can both write code and approve it
is not a review system.

You start none of them. All are invoked for you.

## Who you actually talk to

There is no agent to start or select
([ADR-0044](https://github.com/urban233/CoDev/blob/main/docs/adr/0044-lead-is-not-an-agent.md)).
Earlier versions asked you to start a `planner` session for upstream work,
then an `orchestrator` (later `lead`) session for the build, then an
`outer-loop-runner` session for review, and to know when to switch. A session
boundary you have to notice is a command by another name, and CoDev's
position is that you do not run commands -- whether that boundary is a
separate session or a separate agent identity you have to dispatch first.

Coordination is what `AGENTS.md` and `.codev/for-ai/ai-agent-guidelines.md`
already tell an ordinary session to do: run the navigator every turn, dispatch
the roles below, request review, never touch product code directly outside a
`pair` slice. Every session already reads them. There is nothing else to
start.

Every turn opens with where the work stands, what it recommends, and why --
computed by the navigator, not remembered. When it is blocked it says so and
offers the choices, rather than stopping at a wall.

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

Once a pull request is open, the `outer-loop-review` skill takes over -- not
a separate agent, a set of instructions the same conversation loads on
demand. It fetches the pull request, gates on CI, dispatches the specialists,
and drives human-triaged correction to a landed change. It used to be a
session you started yourself, then a subagent that session dispatched; now
it is guidance loaded into the conversation you are already having.

Five specialists review the exact diff in parallel. You choose which to
dispatch — each spends a real model call, and the skill asks you explicitly
before dispatching any of them, which is the guarantee
([ADR-0021](https://github.com/urban233/CoDev/blob/main/docs/adr/0021-opencode-specialist-dispatch-permission-gate.md)) —
and skipping one is offered as a recorded waiver with a reason, never
assumed.

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

`builder` cannot review. Reviewers cannot edit. Coordination never writes
product code outside an explicitly recorded `pair` slice. An agent may check
its own work; it may never approve it.

## Next

- [The Workflow](/CoDev/concepts/) — the phases and the two loops
- [Slices and Stacks](/CoDev/slices/) — what one agent works on at a time
