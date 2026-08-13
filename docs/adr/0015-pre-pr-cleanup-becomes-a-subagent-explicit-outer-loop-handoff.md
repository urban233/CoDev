# ADR-0015: Pre-PR cleanup becomes a subagent; explicit outer-loop hand-off

**Status:** Accepted
**Date:** 2026-08-13

## Context

Two problems traced to the same root cause during a real session's
feedback review.

**`code-audit` was doing two jobs under one `mode: primary` shape.**
`orchestrator` invoked it automatically, pre-PR, in a narrower "Phase 1
only, audit and plan, never self-apply" mode (ADR-0005) — because Phase 2
(self-applying *approved* fixes) needs to hold a live conversation and wait
for explicit human approval, a subagent can't pause mid-task for a human
turn, so the whole agent stayed `mode: primary`. But the automatic mode
never used that capability: it's audit-only, structurally identical to
what `lightweight-reviewer` already does as a plain subagent. On OpenCode
specifically, this meant `orchestrator`'s `permission.task` allow-list
never actually included `code-audit` — both are `mode: primary`, and
OpenCode's task-dispatch is only confirmed working for `mode: subagent`
targets — so the documented pre-PR gate was silently unreachable there.
`reviewer` sat allowed-but-unused in that same list (no numbered step ever
named it), almost certainly the literal "generic reviewer agent" a session
reported falling back to in place of the real outer-loop tooling.

**Recording pre-PR findings as an outer-phase round could exhaust the
round cap on style fixes alone.** Traced precisely: `_round_slot`
(`work.py`) counts a round toward its phase's cap the instant it's
*created*, before it has any content. The documented routing — code-audit
findings become the outer phase's round 1 (`CHANGES_REQUIRED`), triage,
then a correction round — spends both of the outer phase's two rounds
(default `max_rounds`) before the five specialists have run even once.
Whenever they eventually do run and report even one blocking finding (the
normal case, not the exception), `stop_round_cap` fires immediately, with
no room for the outer loop's real review to have any correction round at
all.

**`orchestrator` step 9 was silent on the outer-loop hand-off mechanism.**
"The outer loop's specialist review... continues this same work item"
never said *how*, or who triggers it — leaving an orchestrator that just
opened a PR with no instructed next action.

## Decision

### 1. Split `code-audit` into a human-direct agent and an autonomous subagent

`code-audit` (all four platforms) is unchanged except for one removed
paragraph: the "Invocation modes" section describing `orchestrator` calling
it is gone, since `orchestrator` no longer does. It stays `mode: primary`,
human-invoked only, full two-phase audit-and-fix workflow.

A new agent, `code-audit-gate` (all four platforms, same
`{{LANGUAGE_INSTRUCTIONS}}`/`{{SKILL_PERMISSIONS}}`/`{{DESCRIPTION_SCOPE}}`
templating as `code-audit`, registered alongside it in `installer.py`'s
`PRE_PR_CLEANUP_AGENT_TEMPLATES` and, for OpenCode specifically,
`OPENCODE_AGENT_CONFIGS`): `mode: subagent`, always-autonomous. Its scope
is contractually style and documentation only, never logic or behavior —
narrow enough that nothing in it needs a judgment call, so unlike
`code-audit` it never stops for approval; it fixes what it finds directly
and reports back a short factual summary (what changed, that nothing
needed changing, or exactly what it could not resolve). It never commits
itself — the same permission shape as `builder` (no subagent in this
system holds git-mutation permission) — and never invokes another agent,
matching `code-audit`'s own guardrail. `adapter.py`'s `verify_adapter`
deliberately does not cover either agent (neither ever did, for
`code-audit`): both are templated, so the raw bundle only ever has a
`.template` source, never the rendered filename role-path checking
assumes. Coverage instead comes from the installer's own rendering tests —
`tests/test_installer.py` gained a dedicated regression asserting the
rendered file exists per platform and never contains `code-audit`'s
`Stop with \`APPROVAL REQUIRED\`` instruction, the one thing that must
never survive a copy from that shared body into this always-autonomous one.

### 2. `orchestrator` dispatches it between the builder's round and `lightweight-reviewer`, not after

Originally discussed as running *after* `lightweight-reviewer` forms its
verdict (deferring the single `codev work record --role reviewer` call
until the cleanup pass settles the final head). Implementation found a
simpler placement with the identical safety property and no changes to
`lightweight-reviewer.md` at all: dispatch `code-audit-gate` immediately
after the builder's round is committed and recorded (now one atomic call —
see (3) below), commit again if it changed anything, *then* dispatch
`lightweight-reviewer` against that now-final head. `lightweight-reviewer`
keeps recording its own round exactly as it always has; it simply now
always reviews the truly-final, post-cleanup code, which is strictly
better than reviewing an intermediate head and hoping a later cleanup pass
didn't introduce anything. `code-audit-gate` never creates a round-state
entry of its own — nothing about it touches `_round_slot` or any round
cap, inner or outer. Its evidence trail is a non-blocking finding
`lightweight-reviewer` includes in its own recorded round when there's a
summary to note, not a separate record.

This also fully answers the round-cap problem: mechanical cleanup now
resolves before the phase ever transitions to outer, so outer round 1 is
genuinely the five specialists' first pass, matching what ADR-0008 already
assumed was true.

`orchestrator` step 9's `ok_ready_for_pr` branch is now just "push and open
the PR" — the entire "invoke code-audit, route findings through outer-phase
triage" branch is deleted, since there is nothing left to find at that
point under normal operation.

Direct-review items (ADR-0006), which skip the builder/reviewer rounds
entirely, still get the cleanup pass: `check()`'s `ok_ready_for_pr`
special-case for a fresh `direct-review` item never inspects `head` at
all, so `code-audit-gate` can run and commit against the human's own
already-finished diff with no drift risk, same as any other path.

### 3. `codev git commit` gains `--round`/`--evidence` (used here for the first time)

Reused directly from ADR-0012's selective-commit work, landed earlier in
this same session: `codev git commit --round <n> --evidence <file>` commits
and records the builder's round in one call. `code-audit-gate`'s own
cleanup commit (if it changed anything) is a second, plain `codev git
commit` call with neither flag — it is not a builder round and must not be
recorded as one.

### 4. `orchestrator` step 9 (now 10) names the hand-off explicitly

All four platforms: once a pull request opens, tell the human plainly that
outer-loop review continues via `outer-loop-runner` for this work item — a
separate, human-triggered switch, never something `orchestrator` attempts
or continues on its own. This was already the intended design
(`outer-loop-runner`'s own text calls itself "a distinct entry point... the
human starts you deliberately"); the gap was purely that step 9 never said
so, leaving nothing for an agent to act on at that point in the protocol.

OpenCode specifically: added `code-audit-gate: allow` to `orchestrator`'s
`permission.task` map (the actual, task-dispatchable subagent this time).
Deliberately did *not* add `outer-loop-runner` there — the hand-off stays
human-mediated, sidestepping the unresolved question of whether OpenCode's
`task` tool can target a `mode: primary` agent at all.

`.codev/for-ai/ai-agent-guidelines.md` (the platform-agnostic canonical
reference) updated to match: the builder-evidence step now describes the
one atomic commit-and-record call, the `ok_ready_for_pr` step describes
`code-audit-gate`'s dispatch and why it never spends the outer round cap,
and the final step names `outer-loop-runner` explicitly instead of saying
"continues."

## Consequences

- No `ROUND_SCHEMA_VERSION` bump: `code-audit-gate` never touches
  round-state directly; its only trace is an ordinary non-blocking finding
  in a round `lightweight-reviewer` already records.
- `orchestrator`'s numbered steps grew by one (5–9 became 5–10) across all
  four platforms; the entry-mode preamble's "skip steps" and "step N's
  `ok_ready_for_pr`" references were updated to match everywhere, including
  fixing a regression caught during implementation: the direct-review path
  originally skipped straight past the new step 7, silently losing the
  cleanup pass it used to get for free as part of the old step 8. Direct
  review now explicitly routes through step 7 before jumping to step 9.
- Codex's `orchestrator.toml` is independently paraphrased prose, not a
  mechanical mirror of the other three platforms (confirmed by structural
  diffing before editing) — its rewrite matches its own established
  condensed style rather than copying the other three verbatim.
  `code-audit`/`code-audit-gate`'s bodies, by contrast, are shared
  verbatim across OpenCode/Codex/Junie (Antigravity's differs only to name
  `invoke_subagent`, as it does everywhere else in the bundle).
- Testing needs (added): `tests/test_installer.py` — `code-audit-gate`
  installs for every platform, language instructions render correctly, the
  human-approval instruction never appears in the rendered output;
  extended the existing hardcoded per-platform agent-file-list assertions
  to include it. `codev adapter verify` re-run for all four platforms
  against both the raw bundle and a fresh `codev init` target — clean on
  both. Full release gate (`scripts/verify_release.py`: unit tests, compile
  check, workflow validation, evaluator self-test, ruff lint/format, mypy,
  package build) passes.
