# ADR-0040: The lead agent is the only human-facing agent

**Status:** Accepted
**Date:** 2026-09-03
**Owner:** Martin Urban
**Related design:** [docs/plans/developer-experience-implementation.md](../plans/developer-experience-implementation.md)
**Supersedes:** [ADR-0024](0024-planner-primary-agent.md)

## Context

CoDev shipped three human-started agents: `planner` for Specify, Understand,
Design and Plan; `orchestrator` for Build and Review; `outer-loop-runner` for
the specialist pass on an open pull request. Each was a separate session the
developer had to know to start, and the instructions said so explicitly --
"they are separate, human-started entry points by design; do not chain from
one into the other yourself."

The unified-workflow brief had already named this as the defect, in the clause
that did not ship with the rest of item 8: *"the three sessions collapse into
one run ... because a session boundary the developer has to notice is a
command by another name."* CoDev's position (ADR-0036) is that developers do
not run commands. A session switch is a command wearing different clothes.

The split existed for a real reason -- `planner` must not implement, `builder`
must not review -- but that is an argument for separate *subagents* with
separate permissions, not for making the developer the dispatcher between
them.

## Decision

**`lead` is the only agent a developer talks to.** It plans, dispatches the
build, and drives review to a merged pull request.

`orchestrator` is renamed to `lead` and rewritten against the composite verbs
and the navigator. `planner` is removed: roughly forty of its fifty-six lines
routed to skills `lead` now invokes directly, `codev next` computes the
routing its "Scope" section described in prose, and its one unique behavior,
the issue-only short circuit, is `codev git issue-create --body-file`.

`outer-loop-runner` keeps its file and loses its trigger. It holds
irreducible protocol -- CI gating, five-specialist dispatch, a second entry
for acting on existing review comments, coverage-recording rules -- and
folding that into `lead` would reproduce the long role file this decision
exists to remove. `lead` dispatches it, permission-gated like the specialists
(ADR-0021).

Role count falls from thirteen to eleven. Human-facing role count falls from
three to one, which is the number that matters.

`lead` runs on `opus`: it inherits the planning judgment that justified
`planner`'s model, while the volume work stays in `builder`, `reviewer`, and
the five specialists, which are unchanged.

**`lead`'s role file is budgeted at 80 lines**, against `orchestrator`'s 167.
The budget is a validation criterion, not a style note: it is the only thing
standing between this decision and a `lead.md` that reproduces
`orchestrator.md` under a new name. Overflow becomes a skill, loaded on
demand, never a longer resident role file.

## Alternatives considered

- **Fold `outer-loop-runner` into `lead` as well.** Rejected: it would produce
  a role file well past 200 lines, which is the problem, not the fix.
- **Keep `planner` as a second entry point for planning-only sessions.**
  Rejected: a developer who wants planning-only work says so, and `lead`
  stops there. Preserving the session boundary to preserve the option trades
  one rigidity for another.
- **Rename nothing and only change the instructions.** Rejected: the role
  files are the instructions. Prose that says "do not switch sessions" beside
  three primary agents is contradicted by the file listing.

## Consequences

- Every document, adapter, and installer path that named `orchestrator` or
  `planner` names `lead`. `ADAPTER_ROLE_PATHS` loses two entries and gains
  one.
- **Existing installations must have the retired role files removed, not
  retained.** A file in an adapter's agents directory is an invocable agent,
  so leaving `orchestrator.md` beside `lead.md` gives a developer both. The
  installer now deletes an untouched retired role file rather than retiring
  it in place; a locally edited one stays a conflict the developer resolves.
- OpenCode's `default_agent` migrates from `orchestrator` to `lead` on update
  rather than being preserved as a local change, because the old value names
  an agent that no longer ships.
- ADR-0001's "every platform has an `orchestrator`" and ADR-0024's `planner`
  entry point now read as history. This ADR is their forward pointer.

## Revisit when

Eleven roles is still a lot, and this decision fixes the number a developer
sees rather than the number that exists. If specialist selection becomes
diff-driven rather than dispatched as a set, revisit whether five specialist
roles remain the right shape.
