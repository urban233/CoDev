**Status:** Accepted
**Date:** 2026-08-31
**Owner:** Martin Urban
**Related design:** [docs/features/plan-wave/design.md](../features/plan-wave/design.md)

## Context

`plan-delivery` already names rolling-wave planning as a supported pattern
in its own trigger description, and step 2 already instructs detailing the
current milestone while keeping later ones coarse. That instruction is one
advisory sentence with no mechanical backing — unlike the Build phase's
plan-first guardrail (ADR-0030), which pauses for confirmation before an
edit proceeds without a plan. Nothing stops `codev git issue-create` from
pushing an issue for a future milestone whose assumptions have not been
tested yet.

This repository has never exercised `plan-delivery` on itself —
`docs/codev/delivery/` holds no files — and carries a live example of the
failure mode: `docs/plans/phase-6-cleanup-and-promotion.md`, a fully-scoped,
four-task plan for a deliberately deferred phase, unrevisited since.

## Decision

Rename `plan-delivery` to `plan-wave` end to end: the skill directory,
description, prose, `docs/codev/delivery/` to `docs/codev/wave/`, and
`delivery-plan.template.md` to `wave-plan.template.md`. This is a hard
break, no dual-support window, following ADR-0023's precedent exactly.
Historical ADRs referencing `plan-delivery` (0004, 0020, 0022, 0023, 0024)
stay unedited — an accurate record of what the skill was called at the
time.

`plan-wave`'s own steps make "detail only the current wave" directive: a
named revisit checkpoint — an evidence check plus a bounded hardening pass
when the evidence calls for one — gates the start of the next wave's
detail, rather than leaving that to memory.

Add `require_wave_shape.py`, a Claude-Code-only `PreToolUse` hook. It asks,
never denies, when a non-current wave section of the wave-plan document
holds a populated task table, checked both on `Edit`/`Write` to the
document itself and on a `Bash` command starting `codev git
issue-create` while the document is in that state. It fails open on any
internal error, matching `require_plan.py`'s existing posture.
`require_plan.py`'s own coarse-fallback glob is extended to also recognize
`docs/codev/wave/*.md`.

## Alternatives considered

- **Strengthen the advisory prose instead of gating it:** rejected — the
  same reasoning that produced ADR-0030's guardrail applies identically
  here: a session under pressure can skip prose discipline it cannot skip a
  mechanical check.
- **Match a specific issue to a specific wave row by title inference:**
  rejected as too fragile; no reliable link between an `issue-create` call
  and a document row without a new CLI flag, which this decision defers
  rather than commits to.
- **Hard-deny instead of ask:** rejected — ADR-0030 already established
  that a false-positive block costs more than an occasionally-quiet gate;
  "ask" bounds the damage to one confirmation click.
- **Extend `require_plan.py` directly instead of a new sibling hook:**
  rejected — mixes two different concerns ("does a plan exist" and "is the
  existing wave-plan document well-formed"), the same reasoning ADR-0015
  used to split `code-audit-gate` from `code-audit`.
- **Also gate OpenCode via its permission system:** rejected — OpenCode's
  `permission.bash` can only allow or deny a command pattern outright; it
  has no primitive for a check conditioned on current repository file
  state.

## Consequences

- 38 files referencing `plan-delivery` need updating, including live,
  deployed content in `docs-site/` and the changelog. ADRs 0004, 0020,
  0022, 0023, and 0024 are not touched.
- No config or state schema version change — no persisted field names
  `plan_delivery` or an equivalent.
- OpenCode sessions receive only the updated prose, no new mechanical
  enforcement — an accepted, named scope limit, not a regression from
  today's behavior.
- The wave-shape lint checks the whole document's shape, not which wave a
  specific `issue-create` call targets — a named, accepted imprecision (see
  design.md's Quality and risk).
- Testing: fixture-stdin tests for `require_wave_shape.py` mirror
  `test_claude_hook.py`'s existing pattern;
  `scripts/validate-development-workflow.py` gains a scenario covering the
  revisit checkpoint.

## Revisit when

Real usage shows the whole-document wave-shape check's imprecision — asking
over an unrelated malformed section, or staying quiet for a genuinely
mistargeted future-wave issue — causes enough friction or missed catches to
justify the `--wave`-flag alternative named in design.md's Alternatives and
trade-offs, or when design.md's own blocking open question about
wave-uncertainty classification resolves into a structural change beyond
what this decision covers.
