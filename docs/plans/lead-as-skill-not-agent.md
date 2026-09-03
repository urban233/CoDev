# Lead Is a Skill, Not an Agent - Implementation Plan

**Status:** Accepted 2026-09-03 by Martin Urban
**Owner:** Martin Urban
**Author:** Claude Sonnet 5 (drafted; not an approval)
**Supersedes in part:** [ADR-0040](../adr/0040-the-lead-agent-is-the-only-human-facing-agent.md)
**Base commit:** `f5df9c7`
**Risk:** high. It reopens a merged architectural decision and touches
ADR-0021's specialist-dispatch permission guarantee.

## Context

ADR-0040 made `lead` the only agent a developer talks to, and had it dispatch
`outer-loop-runner`, permission-gated the same way as the five specialists.
That decision assumed dispatching one subagent from another would simply
work. It does not, and the gap is not one role's oversight -- it is
structural, and it predates this session's work.

**Every role in `.claude/agents/` is missing the grant a Claude Code subagent
needs to dispatch further subagents.** A Claude Code subagent gets no
dispatch tool by default; it needs an explicit `Agent(name1, name2, ...)`
entry in its own `tools:` frontmatter line. `lead.md`'s tools are `Read,
Grep, Glob, Bash, Write, Edit, AskUserQuestion` -- no `Agent`. Neither does
`outer-loop-runner.md`, `builder.md`, `code-audit.md`, or `reviewer.md`. This
was found live: `outer-loop-runner`, dispatched in this session's own outer
loop, reported it had no way to invoke the five specialists it is described
as coordinating, and did the analysis itself instead.

**Claude Code has no mechanism for a session to boot as a named agent.**
Unlike OpenCode's `mode: primary` + `default_agent`, nothing in
`.claude/settings.json` designates `lead` as what a fresh session becomes.
This repository's own settings file sets only `permissions.defaultMode` and
three hooks. A Claude Code session that has never explicitly dispatched
`lead` is not lead -- it is generic Claude, following `AGENTS.md`, which is
exactly what every session in this conversation has actually been, informal
narration of "acting as lead" notwithstanding.

**OpenCode does not need a project-defined primary agent at all.** It ships
its own built-in `Build` and `Plan` primary agents as a platform-level
fallback. A project that defines no custom primary agent still has a session
to start in.

Three facts, taken together, argue for the same conclusion: `lead` should
not be modeled as an agent identity a developer selects or is dispatched
into, on either platform. It should be what every ordinary session already
does, because it already reads the instructions that would otherwise live in
`lead.md`.

## What changes, in one paragraph

`lead.md` is deleted from both `.claude/agents/` and `.opencode/agents/`.
Its coordination framing -- run the navigator every turn, dispatch the
inner-loop roles, request review, never edit product code, never claim
approval -- folds into `.codev/for-ai/ai-agent-guidelines.md`, which every
platform already loads at the start of every session; there is no separate
file left to forget to read. `outer-loop-runner.md` is deleted as an agent
file; its 217-line protocol becomes a skill, loaded only when a session is
actually doing outer-loop review, not resident in every turn's context the
way an agent's system prompt is. `builder`, `reviewer`,
`lightweight-reviewer`, `code-audit-gate`, and the five specialists are
unchanged -- they stay subagents, because their isolation is the point
(ADR-0002: a builder that cannot commit, a reviewer that cannot edit), not an
artifact of the primary-agent model this plan removes.

## Why this is better than granting `Agent(...)` and calling it done

The narrower fix -- add `Agent(builder, reviewer, ...)` to `lead.md`,
`Agent(correctness-tests-specialist, ...)` to `outer-loop-runner.md`, leave
the rest of ADR-0040's shape alone -- would work. It is not what this plan
proposes, for two reasons found while investigating the narrower fix:

- **It does not fix the boot problem.** `lead` would still be a thing a
  developer has to dispatch or select before a session is actually following
  it, on Claude Code. The narrower fix repairs dispatch; it does not repair
  the session boundary ADR-0040 was written to remove.
- **It does not fix the length problem, only relocates it.** ADR-0040's own
  80-line budget for `lead.md` exists because a resident agent body is a
  cost paid every turn. `outer-loop-runner`'s 217 lines of real,
  irreducible protocol cannot shrink to fit that budget by any rewrite --
  the content is what CI gating, five-way specialist selection, merge and
  triage rules actually require. Keeping it as a *dispatched* agent body
  means it is still fully resident for the whole of every outer-loop
  session, whether or not that turn needs the CI-gating clause. A skill
  loads only when invoked; the same content costs nothing on every other
  turn.

## What moves where

| Content | From | To |
|---|---|---|
| Coordination framing (navigator every turn, dispatch inner loop, stop conditions) | `lead.md` body, ~58 lines | `.codev/for-ai/ai-agent-guidelines.md`, already universally loaded |
| Outer-loop protocol (fetch/gate, select/dispatch, merge/record, triage, correction, comment-driven entry) | `outer-loop-runner.md` body, ~207 lines | New skill `outer-loop-review`, decided below |
| `builder`, `reviewer`, `lightweight-reviewer`, `code-audit-gate`, five specialists | unchanged | unchanged, still subagents |

No content is deleted outright. The outer-loop protocol's word count barely
changes -- it moves from a place that is always loaded to a place that is
loaded on demand, which is the entire point.

## Decisions

Both were open questions when this document was first drafted. Both are
resolved below, using evidence already in this repository rather than an
unconfirmed platform capability.

### 1. Where does the outer-loop protocol live as a skill? Resolved: a new skill.

**Not `pr-review`.** Reading `pr-review/SKILL.md` and
`github-actions-ci-results/SKILL.md` directly shows every skill in this
collection is single-voice: one reviewer producing findings, one read-only
investigator. `pr-review`'s own description is explicit -- "do not use for
general code review, commit review, branch review, or working-tree review"
-- and its body frames the work as "Act as an independent, read-only
reviewer of one GitHub Pull Request," singular. No skill in the collection
dispatches another agent; `github-actions-ci-results` goes out of its way to
say it does not even trigger a workflow rerun on its own.

`outer-loop-runner`'s actual job -- dispatch five specialists, merge their
findings into one coverage manifest, gate on CI, drive a human-triaged
correction loop -- is not a review. It is review *orchestration*. Folding it
into `pr-review` would make that skill the first in the collection to blend
"I review" with "I coordinate five other reviewers," working directly
against the scoping discipline every other skill here follows.

**Decision: a new skill, `outer-loop-review`.** Named to match the sibling
`pr-review`'s noun-noun shape and the vocabulary this whole session already
uses for the concept, so it is discoverable by analogy. It keeps
`pr-review` and `github-actions-ci-results` as dependencies -- reusing their
fetch scripts exactly as `outer-loop-runner.md` does today -- rather than
duplicating what they already do.

### 2. How does ADR-0021's specialist-dispatch permission guarantee survive? Resolved: it already does not depend on the platform gate alone.

`outer-loop-runner.md`'s own current protocol, step 2, already reads:
*"present the five specialists as a numbered list, each with the
dimension(s) it owns, and ask which to run this pass"* -- and, immediately
after selection, asks again before waiving any skipped dimension. This is a
human-in-the-loop step written in prose, independent of whatever platform
permission config also exists. It is not new; it is what the protocol
already requires today, on every platform, on top of OpenCode's
`permission.task` backstop.

This session's own practice corroborates it directly: mid-session, the
correction that mattered was not "should the outer loop run" but "how many
model calls does this cost, authorize the spend" -- an explicit ask before
each specialist dispatch, made in prose, not derived from any agent
frontmatter. That is the mechanism that actually governed every specialist
dispatch in this conversation.

**Decision: the explicit selection-and-confirmation prose in
`outer-loop-review` is the guarantee, not a fallback for a lost one.**
OpenCode's `permission.task` gate, where it still applies to whatever
OpenCode falls back to, is additional defense-in-depth worth keeping if it
turns out to be configurable on a built-in primary agent -- but this plan
does not block on confirming that, because the guarantee was never resting
on it alone.

### 3. What happens to `code-audit`?

Out of scope for this plan, named explicitly so it is not silently swept
in. `code-audit` is `mode: primary` on OpenCode and a directly-dispatched
subagent on Claude Code, but it is not part of the everyday coordination
loop ADR-0040 and this plan are about -- it is a standalone, occasionally
invoked style-audit tool, structurally closer to `specify-project` or
`security-review` than to `lead`. Converting it to a skill too is a
plausible, smaller follow-up, not a decision this plan makes.

### 4. `.opencode/agents/outer-loop-runner.md` still carries `mode: primary`

Found in passing, not introduced by this plan: OpenCode's copy of
`outer-loop-runner.md` was never updated when ADR-0040 landed, and a
developer could still select it directly today, bypassing `lead` entirely.
Whatever this plan does to `outer-loop-runner`, this loose end closes as a
side effect -- the file stops existing as an agent at all.

## What does not change

- `builder`, `reviewer`, `lightweight-reviewer`, `code-audit-gate`, and the
  five specialists remain subagents with their current tool restrictions.
  Their isolation is not the primary-agent problem this plan solves; it is
  ADR-0002's git-mutation posture and ADR-0021's independent-review
  posture, both still correct.
- `codev next`, the navigator, the composite verbs, and the risk-tiered
  gate -- everything the developer-experience plan built -- are unaffected.
  This plan changes who is following the guidance the navigator computes,
  not the guidance itself.
- The installer's role-retirement mechanism (deletes a role the bundle
  stops shipping, refuses to silently discard a locally-edited one) already
  handles removing `lead.md` and `outer-loop-runner.md` cleanly for an
  existing installation, per the migration built for ADR-0040 itself.

## Validation

- `codev adapter verify` on both platforms after the role files are removed
  -- confirms nothing still references a deleted agent name.
- A real Claude Code session, from a clean checkout, doing one full
  lifecycle turn without ever dispatching an agent named `lead` -- proving
  the coordination framing actually reaches a session through
  `ai-agent-guidelines.md` alone.
- The navigator-coverage measure (`tests/test_navigator_coverage.py`) is
  unaffected by this plan and should stay green throughout -- it measures
  what `codev next` recommends, not who is following the recommendation.
- Whatever the outer-loop skill becomes, exercise its CI-gate,
  specialist-selection, and triage paths at least once against a real pull
  request before calling this done -- the protocol is real and load-bearing,
  and moving it into a skill must not silently change what it does.

## Risks

- **Neither decision above was tested against a real OpenCode
  installation.** Both are reasoned from OpenCode's public documentation and
  from this repository's own files, not from an empirical run. `outer-loop-review`
  existing as a skill Claude Code loads correctly does not by itself confirm
  OpenCode's skill-invocation model handles it the same way -- that is
  validation work item one, not a settled fact.
- **Folding `lead`'s framing into `ai-agent-guidelines.md` makes that
  document the single point of failure for the guidance obligation.** It
  already is, in practice -- every role file already points back to it --
  but this plan removes the last agent file whose own body restated any of
  it independently.
- **Reopening a merged ADR two pull requests after it merged** is itself a
  cost: it means package 5's design was wrong in a way nothing in its own
  review caught, because nothing in that review actually dispatched `lead`
  as a subagent end-to-end. Worth naming plainly rather than treating as
  routine churn.

## Status of the four decisions

1. **Resolved:** a new `outer-loop-review` skill, not an extension of `pr-review`.
2. **Resolved:** the specialist-selection-and-confirmation prose already in
   `outer-loop-runner.md` carries into the skill unchanged and is the
   guarantee, not a fallback.
3. **Deliberately out of scope:** `code-audit`'s `mode: primary` status is
   untouched by this plan.
4. **Closes as a side effect:** removing `outer-loop-runner.md` as an
   OpenCode agent removes its stray `mode: primary`, whatever else this plan
   does.

Nothing here authorizes implementation on its own -- this document's
`Status` line is still `Draft`. It becomes buildable once that line reads
`Accepted`.
