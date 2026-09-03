# ADR-0044: Lead is not an agent

**Status:** Accepted
**Date:** 2026-09-03
**Owner:** Martin Urban
**Related design:** [docs/plans/lead-as-skill-not-agent.md](../plans/lead-as-skill-not-agent.md)
**Supersedes in part:** [ADR-0040](0040-the-lead-agent-is-the-only-human-facing-agent.md)

## Context

ADR-0040 made `lead` the only agent a developer talks to and had it dispatch
`outer-loop-runner`, permission-gated the same way as the five specialists.
That decision assumed a dispatched Claude Code subagent can dispatch a
further subagent by default. It cannot: a subagent gets no dispatch tool
unless its own frontmatter grants `Agent(name1, name2, ...)` explicitly, and
no role in this bundle -- `lead` included -- has ever granted it. This was
found live: `outer-loop-runner`, dispatched in a real outer-loop review,
reported it had no way to invoke the five specialists it is described as
coordinating, and did the analysis itself instead.

Two further platform facts, verified rather than assumed, made the fix
larger than one missing grant:

- **Claude Code has no mechanism for a session to boot as a named agent.**
  Unlike OpenCode's `mode: primary` + `default_agent`, nothing designates
  `lead` as what a fresh Claude Code session becomes. A session that has
  never explicitly dispatched `lead` is not lead -- it is generic Claude,
  following `AGENTS.md`.
- **OpenCode does not need a project-defined primary agent at all.** It
  ships its own built-in `Build` and `Plan` primary agents as a
  platform-level fallback.

Granting `Agent(...)` to `lead.md` and `outer-loop-runner.md` would repair
dispatch without repairing the session boundary ADR-0040 exists to remove,
and would not repair a second, unrelated problem: `outer-loop-runner`'s 217
lines of real, irreducible protocol cannot fit ADR-0040's 80-line ceiling by
any rewrite, and keeping it as a *dispatched agent body* means it is fully
resident for the whole of every outer-loop session regardless of whether
that turn needs the CI-gating clause.

## Decision

**`lead` is not an agent, on either platform.** No file, on Claude Code or
OpenCode, designates a coordination-role identity a developer selects or is
dispatched into as their whole session.

`lead.md` is deleted from `.claude/agents/` and `.opencode/agents/`. Its
coordination framing -- run the navigator every turn, dispatch the
inner-loop roles, request review, never edit product code, never claim
approval -- folds into `.codev/for-ai/ai-agent-guidelines.md`, which every
platform already loads at the start of every session. There is no separate
file left to forget to read, and no boot-time selection needed: an ordinary
session already has it.

`outer-loop-runner.md` is deleted as an agent file on both platforms. Its
protocol becomes `outer-loop-review`, a skill -- not an extension of
`pr-review`, because `pr-review`'s own scope explicitly excludes general
review orchestration, and no skill in this collection dispatches another
agent today. A skill loads only when invoked, so the protocol's real length
stops being a cost paid on every turn.

`builder`, `reviewer`, `lightweight-reviewer`, `code-audit-gate`, and the
five specialists are unchanged. Their isolation is ADR-0002's git-mutation
posture and ADR-0021's independent-review posture, neither of which the
primary-agent model ever provided -- removing that model changes nothing
about why they stay subagents.

**ADR-0021's specialist-dispatch guarantee does not move to a new
mechanism; it was never resting on the one being removed.**
`outer-loop-runner.md`'s own protocol already asks the human, in prose,
which specialists to run before dispatching any of them -- independent of
whatever platform permission config also existed. That prose carries into
`outer-loop-review` unchanged and is the guarantee. OpenCode's
`permission.task` gate, wherever it still applies to whatever OpenCode
falls back to, is additional defense-in-depth worth keeping if it turns out
to be configurable on a built-in primary agent -- confirming that is
validation work, not a blocking dependency of this decision.

`.opencode/agents/outer-loop-runner.md` also carried a stray `mode: primary`
that ADR-0040 never removed, letting a developer select it directly and
bypass `lead` entirely. Deleting the file closes that as a side effect.

`code-audit`'s `mode: primary` status is explicitly untouched. It is a
standalone, occasionally invoked style-audit tool, not part of the everyday
coordination loop this decision is about.

## Consequences

- Role count falls from eleven to nine. Human-facing *agent* count falls to
  zero -- coordination is no longer an identity a developer or a harness
  selects.
- `.claude/settings.json` and `.opencode/opencode.json` no longer need to
  designate any coordination-role default; OpenCode's own built-in primary
  agents are the fallback CoDev never had to replace.
- The installer's role-retirement mechanism, built for ADR-0040's own
  migration, removes `lead.md` and `outer-loop-runner.md` cleanly from an
  existing installation without new logic: an untouched retired role file is
  deleted, a locally edited one becomes a conflict the developer resolves.
- Neither the outer-loop-protocol-as-skill design nor the permission-guarantee
  reasoning above has been validated against a real OpenCode installation --
  both are reasoned from OpenCode's public documentation and this
  repository's own files. That is named as a real risk in the plan, not
  glossed over here.
- This is a second bundle-breaking release inside one development arc:
  0.6.0 removed `orchestrator`/`planner`; this removes `lead` and
  `outer-loop-runner` as agents roughly one day later. Both are true and
  both are stated plainly in their respective ADRs -- CoDev's own claim to
  small, reviewable, honestly-recorded change applies to changing CoDev
  itself.

## Alternatives considered

- **Grant `Agent(...)` to `lead.md` and `outer-loop-runner.md`, keep the
  rest of ADR-0040's shape.** Rejected: repairs dispatch, not the session
  boundary the whole redesign exists to remove, and does not resolve the
  80-line-ceiling-versus-217-lines-of-real-protocol tension for
  `outer-loop-runner` by any means other than relocating where the tension
  lives.
- **Fold `outer-loop-runner`'s protocol into `pr-review`.** Rejected:
  `pr-review` is scoped, by its own description, to being one independent
  reviewer of one pull request; the outer loop's job is coordinating five
  reviewers and a correction loop, a different shape of work every other
  skill in the collection keeps separate from what it reviews.
- **Keep `lead` as OpenCode's `mode: primary` agent, make Claude Code's
  `lead` a skill.** Rejected: it would make ADR-0021's guarantee depend on
  two different mechanisms on two different platforms for the same
  guarantee, and it does nothing to close the stray `mode: primary` on
  OpenCode's `outer-loop-runner.md`. One model, everywhere, is the more
  honest claim to CoDev's own stated goal of a single, unified mental model.
