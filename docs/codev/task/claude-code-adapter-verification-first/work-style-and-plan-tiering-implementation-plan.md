# Slice 1: Work Style and Plan Tiering - Implementation Plan

**Status:** Draft
**Owner:** urban233
**Reviewer:** independent reviewer, to be named before the pull request is marked ready
**Risk:** normal. Prose and frontmatter only; no executable code path changes.
**Containment:** N/A -- reversible by `codev adapter remove claude` plus reinstall
**Work style:** `pair` (recorded)
**Slices:** 5, per the parent plan: work-style-and-plan-tiering, permission-surface, evidence-hooks, scientific-gates, recovery-and-budget
**Slice:** `work-style-and-plan-tiering` (1 of 5)
**Base commit:** `355529c` (round re-baselined onto `54cf0d6` after setup drift)
**Issue/work item:** [urban233/CoDev#47](https://github.com/urban233/CoDev/issues/47)
**Brief/design/API:** [docs/plans/claude-code-adapter-verification-first.md](../../../plans/claude-code-adapter-verification-first.md), Accepted 2026-09-08 -- D1, D2, and the instruction-budget ledger

## Focus card

- **Change:** make `pair` the default work style for the Claude Code adapter,
  tier the per-slice plan mandate to ADR-0043, narrow `builder` to mechanical
  work, and move Build execution and Bookkeeping commits out of the always-on
  guidelines into the `build-change` skill body.
- **Success:** a Claude Code session implements in the main thread by default;
  `builder.md` states the mechanical-work boundary in its own description;
  measured always-on payload lands at approximately 7,195 tokens, under the
  7,500 ceiling, before any later slice adds to it.
- **Non-goals:** hooks, settings, permission surface, scientific gates
  (slices 2-5); any other adapter's bundle; `task.py`'s `DEFAULT_WORK_STYLE`,
  which stays `delegate` for platforms other than Claude Code.
- **Allowed scope:** `src/codev_workflow/bundle/.claude/CLAUDE.md`,
  `src/codev_workflow/bundle/.claude/agents/builder.md`,
  `src/codev_workflow/bundle/.codev/for-ai/ai-agent-guidelines.md`,
  `src/codev_workflow/bundle/.agents/skills/build-change/SKILL.md`, mirrored
  `.claude/`/`.agents/`/`.codev/` copies at the repository root, `tests/`,
  `CHANGELOG.md`.
- **Validation:** `just ci`; a payload measurement reconciled against the
  parent plan's ledger.
- **Stop if:** a retirement estimate misses by more than the 275-token
  headroom plus the 428-token reserve; or moving Build execution into the
  skill body would drop a guarantee rather than relocate it.

## Repository evidence

Confirmed at `54cf0d6`:

- `task.py:142` sets `DEFAULT_WORK_STYLE = "delegate"` while the focus card in
  `ai-agent-guidelines.md` states "`Pair` by default". This slice resolves the
  divergence for the Claude adapter in the bundle, not in `task.py`.
- `codev task style --set pair|delegate` exists (`cli.py:706`) and
  `codev task start --pair-slice` records it at task open. No new CLI surface.
- ADR-0043 already tiered the plan **gate**; `ai-agent-guidelines.md` still
  states the per-slice plan is "the one approval that is not risk-tiered".
- Measured section sizes in `ai-agent-guidelines.md`: Build execution
  (lines 197-338) 2,272 tokens; Bookkeeping commits (lines 417-440) 353
  tokens; Implementation + Review behavior (lines 149-196) 681 tokens.
- Baseline always-on payload 9,698 tokens, itemized in the parent plan.
- Observed this session, and worth recording as motivation rather than as a
  claim about this diff: `codev next` asked for this very document with the
  reason "the builder executes an accepted plan rather than deciding the
  approach itself", on a slice recorded `pair`, where no builder runs. That is
  exactly the divergence D2 removes.

## Proposed change

1. **`.claude/CLAUDE.md`** -- state that this adapter defaults to `pair`: the
   session implements directly and dispatches subagents to verify. Name
   `builder` as the exception for mechanical work, with the boundary. Add the
   rule that a `delegate` slice still requires a written accepted plan.
2. **`.claude/agents/builder.md`** -- narrow the `description` to mechanical,
   low-judgment, reversible work whose correctness is decided by a check
   rather than by taste, so the dispatch decision is legible at the point of
   dispatch. Body prose otherwise unchanged.
3. **`ai-agent-guidelines.md`** -- retire Build execution steps 3-5's
   builder-dispatch choreography and step 2's mandatory-plan prose; replace
   the mandate with ADR-0043's tiering (focus card satisfies a slice within
   budget; a written accepted plan is required when the slice exceeds the
   budget, touches an `_ALWAYS_PLANNED` path, or is dispatched to `builder`).
   Move the remaining Build execution bulk and the Bookkeeping commits section
   into the `build-change` skill body, leaving a pointer.
4. **`build-change/SKILL.md`** -- receive the relocated sections, so they load
   on demand during Build rather than on every Understand, Review, and Ship
   turn.

## Validation

- `just ci` (Bazel build, three Python versions, ruff, mypy strict, catalog
  validation, evaluator self-test).
- Payload measurement: recompute the five always-on sources and reconcile
  against the ledger's 7,195 figure for this slice. A miss inside the 275-token
  headroom is acceptable and recorded; a larger miss draws the named
  428-token reserve (`Recovering a stuck task`), and a miss beyond that is a
  stop condition per the parent plan.
- `codev adapter verify claude` against a fresh install.
- Confirm no diff outside the allowed scope, in particular that no other
  platform's bundle changed.

## Risks and rollout

- **Commit separation weakens.** Accepted knowingly in the parent plan: with
  `pair` as default, "the builder cannot commit" becomes gate-enforced rather
  than structural. Slice 2's `permissions.deny` restores cover for the
  irreversible surface; this slice ships in between, so the gap is real but
  bounded to the stacked branch, not to `main`.
- **Relocation could drop a guarantee.** Mitigation: the move is verbatim, and
  review should diff the relocated text rather than read it fresh.
- **The eval catalog will score this lower** via
  `orchestrator_builder_separated`. Known, recorded as follow-up F1, out of
  scope.

## Decisions needed

None. D1, D2, the work-style assignment, and the budget ceiling were all
decided on the parent plan on 2026-09-08.

## Completion evidence

- [ ] `just ci` green
- [ ] Payload measured and reconciled against the ledger
- [ ] `codev adapter verify claude` passes
- [ ] `git diff` confirms no change outside the allowed scope
- [ ] CHANGELOG entry
- [ ] Relocated sections verified verbatim against their pre-move text
