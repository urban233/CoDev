# ADR-0002: The inner loop becomes self-healing and may open pull requests

**Status:** Proposed
**Date:** 2026-08-11

## Context

CoDev's three-agent Build protocol (`docs/for-ai/ai-agent-guidelines.md`,
`.opencode/agents/orchestrator.md` and its Codex/Junie/Antigravity
equivalents) requires one precise human decision and explicit plan approval
before the `orchestrator` may delegate to the `builder`, on every delegated
build regardless of risk. The protocol also stops before commit or merge
unconditionally: `orchestrator.md`, `builder.md`, and `reviewer.md` all deny
`git commit*` and `git push*` in their permission blocks, on all four
platforms. The pieces needed for an actual end-to-end inner loop —
`build-change`, the `builder`/`reviewer` subagents, and the `codev work`
round-state lifecycle (ADR-0001) — exist, but nothing connects a work item to
an opened pull request without a human present for every step in between.

Separately, a prior version of this workflow (not the current one) exhibited
a specific failure mode during builder/reviewer correction rounds: the
reviewer kept adding new requirements each round, so the builder never had a
fixed target to converge on. Round-state tracking (ADR-0001) already turns
"stop after two attempts at the same root cause" into an exit-code check, but
nothing today detects a *new* blocking finding appearing in a later round
that wasn't raised in round one — the failure mode above is not structurally
prevented, only bounded in total round count.

CoDev's target audience is small developer teams, not organizations running
autonomous agent fleets. Every model invocation must remain a deliberate
action a human takes on their own device, to keep usage quota under the
developer's own control — this rules out CI-triggered inference, bot service
accounts, or unattended execution kicked off by anything other than a human
starting a run.

## Decision

Within a single human-triggered run, for one work item, the inner loop
proceeds without a human-approval checkpoint by default, stopping only when
one of the conditions below is met. This is a narrower, not looser, standard
than "always ask" — the loop still exists to protect the same things human
approval protects today, it just checks for them structurally instead of
pausing for all of them unconditionally.

1. **Critical-interrupt threshold.** Reuse `ai-agent-guidelines.md`'s
   existing stop-conditions list and risk-overrides-size rule verbatim
   (conflicting or missing acceptance criteria, an unsafe accepted design, a
   materially changed base, unavailable validation, colliding concurrent
   work, missing authorization; security, privacy, permissions, public APIs,
   persistent data, billing, compliance, destructive operations, or
   hard-to-reverse changes). No second taxonomy of "critical" is introduced.
   A cheap path/diff-shape heuristic runs before any LLM judgment call, so
   the common low-risk case costs nothing until the lightweight-reviewer
   stage. When the loop does stop, it presents what it found and a proposed
   answer and asks for one decision — it does not reopen a general question.

2. **Runner contract.** The orchestrator's mandatory plan-approval gate
   before delegating (`ai-agent-guidelines.md`, three-agent Build execution,
   step 4) is no longer the default path. After grounding the change
   (`build-change`), the run proceeds directly to the builder unless the
   threshold in (1) fires. The builder's own contract is unchanged.

3. **New `lightweight-reviewer` subagent**, invoked in a fresh context per
   round like today's `reviewer`. Scope is deliberately narrow: independent
   re-verification that the builder's reported local QA (formatter, lint,
   tests) actually passes against the exact head snapshot, plus a judgment
   pass on whether the diff plausibly satisfies the work item's intent with
   no obvious defect. It does not review security, architecture,
   maintainability, or rollout — those remain entirely the future outer
   loop's responsibility. Its standard favors approving once the change is
   safe and does what was asked, not once it is exhaustively reviewed, per
   Google's public code-review guidance ("favor approving a CL once it
   definitely improves the code health of the system... there is no such
   thing as perfect code, only better code"). It additionally runs the same
   critical-category tripwire from (1) as a final check — not a security
   review, a tripwire — and treats a hit as an immediate critical interrupt.

4. **`codev work` (`src/codev_workflow/work.py`) schema extensions:**
   - A fourth reviewer decision, `READY_FOR_OUTER_LOOP`, alongside the
     existing `READY_FOR_HUMAN_APPROVAL` / `CHANGES_REQUIRED` /
     `BLOCKED_BY_MISSING_EVIDENCE`. `check()` treats it as a success terminal
     state without running `_incomplete_coverage`, because full coverage of
     `REQUIRED_COVERAGE_DIMENSIONS` was never the lightweight reviewer's bar.
   - An `expansion_reason` field on each finding (`null`, `"regression"`, or
     `"newly_discovered_critical"`) and a new `_find_scope_expansion` check,
     mirroring the existing `_find_repeated_blocking_finding`. For any round
     after the first, a blocking finding at a `(location, category)` not
     present in round one's blocking set, with no `expansion_reason` set,
     produces a new `stop_scope_expansion` outcome. This is the mechanical
     form of the goalpost-moving guard named in Context, and it is shared
     infrastructure: it applies identically to a future outer-loop specialist
     round, not only the inner loop.
   - The existing round cap and repeated-finding detection are reused
     unchanged for the builder/lightweight-reviewer cycle.
   - Not resolved by this ADR: `max_rounds` is a single work-item-level
     field, but the inner loop and a future outer loop will want different
     caps. Left for the ADR or change that defines outer-loop wiring.

5. **Automatic PR-open as the inner loop's terminal action**, on
   `ok_ready_for_pr` only — never on a `stop_*` escalation, which hands the
   round-state evidence to the human instead without opening anything.
   Merge remains fully human-gated; opening a PR does not, because it is
   reversible and does not affect production. This requires git/GitHub
   mutation capability that no agent has today. Rather than relaxing the
   existing `"git commit*": deny` / `"git push*": deny` permission blocks
   directly — which would trust a model's judgment to never push to `main`
   or force-push — this ADR adopts a guarded abstraction instead: a new,
   narrow CLI surface (proposed as `codev git branch|commit|push|open-pr`,
   implemented similarly to `work.py` alongside the existing `codev work`
   family, but *not* part of it — `codev work` commands are read/write on
   `.codev/work/` state only per ADR-0001, and this new surface mutates the
   actual repository and remote, which is a different, explicitly wider
   contract). Agent permission blocks deny raw `git commit*`/`git push*`/
   `gh pr create*` exactly as today, and separately allow only this new
   command surface. The wrapper, not the agent's prompt, mechanically
   enforces:
   - operates only on the one branch created for the work item (name derived
     from the work item id), never the branch checked out at run start;
   - refuses any target resolving to the repository's default branch;
   - never accepts or forwards a force-push flag — it is not an exposed
     option;
   - the `open-pr` operation independently re-checks `codev work check`
     itself and refuses to run unless the result is `ok_ready_for_pr`, rather
     than trusting the caller already checked — the same
     don't-trust-the-self-report principle already applied to the
     lightweight reviewer's independent QA re-verification in (3);
   - opens the pull request as a draft, so it does not signal review-readiness
     to anyone before the (future) outer loop and human triage have run.

This ADR covers the inner loop only. The outer loop (specialist reviewers,
human finding-triage, and the bounded auto-correction that follows) is a
separate, not-yet-written design and will need its own ADR entry or
extension of this one before implementation, particularly for the
`max_rounds` question noted in (4).

## Consequences

- The three-agent protocol's human-approval checkpoint moves from
  "always, before every delegated build" to "only when the work is flagged
  critical" — a real autonomy increase, scoped by (1) and (4)'s structural
  checks rather than prompt discipline alone.
- `docs/architecture.md`'s invariants list will need a new line documenting
  the guarded git/GitHub command surface and its scope, the same way it
  already documents the `codev work` exception from ADR-0001. Not done as
  part of this ADR; a follow-up once this is accepted.
- All four platform adapters (OpenCode, Codex, Junie, Antigravity) need their
  `orchestrator`/`builder` (or equivalent) permission blocks and instructions
  updated consistently — `codev adapter verify`'s existing conformance check
  should be extended to also assert the new command surface is present and
  raw git mutation stays denied, the same way it already checks for
  unrestricted shell access.
- The goalpost-moving mechanical guard (`expansion_reason` /
  `stop_scope_expansion`) is built once, generically, in `work.py`, and is
  ready for the outer loop to reuse without re-deriving it.
- No CI-triggered inference or bot identity is introduced anywhere in this
  decision; every step above still executes inside one human-triggered local
  run.
