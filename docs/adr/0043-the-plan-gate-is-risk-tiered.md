# ADR-0043: The plan gate is risk-tiered

**Status:** Accepted
**Date:** 2026-09-03
**Owner:** Martin Urban
**Related design:** [docs/plans/developer-experience-implementation.md](../plans/developer-experience-implementation.md)
**Narrows:** [ADR-0030](0030-claude-code-adapter-and-plan-first-guardrail.md)

## Context

The plan gate asked for a written plan before the first source edit on a task
branch, keyed purely on a file existing at a known path. It therefore asked
the same question of a one-file bug fix and a subsystem rewrite.

Ceremony that cannot tell those apart does not produce plans. It produces
agents that learn to approve past the prompt, which costs the guardrail its
meaning on the changes that actually warrant it.

Separately, `_SPEC_GLOBS` did not cover `docs/plans/*.md` -- where this
repository keeps every accepted plan. The gate could not see the artifact it
was asking for.

## Decision

The gate tiers by risk, as a **changed default with no new configuration key**:
CoDev's answer to "more structure" is a better default, not another knob.

- Within the slice's size budget on a task branch, the focus card in the
  conversation satisfies the gate; no plan file is required.
- Past the budget, it asks again.
- Dependency and environment manifests, CI workflow definitions, and
  migrations ask **regardless of size**. A version bump changes what the code
  computes, which for research software surfaces as an unreproducible result
  rather than an outage; a workflow file decides whether anything is checked
  at all; a migration is irreversible against real data.
- A repository-mutating git command is **never** tiered. A push is not made
  safe by the change being small.

`_SPEC_GLOBS` covers `docs/plans/*.md`. That half is not a risk-tiering change
and stands on its own.

## The timing is the design

The gate fires *before* an edit, so the only diff it can see is the one
already on the branch. That reads like a flaw and is the point. The old gate
interrupted before the work started, when a developer knows least about what
the change will need. The tiered gate interrupts when the change outgrows what
a focus card can carry, which is when a written plan is worth its cost. A toll
booth becomes a tripwire.

## Alternatives considered

- **A configuration key for the threshold.** Rejected on standing policy:
  prefer the default and state why.
- **CODEOWNERS-declared paths as the sensitivity signal.** Rejected: in most
  repositories CODEOWNERS covers everything, so the tier would never apply.

## Consequences

- **Three** measurement holes had to be closed, the third found by this
  pull request's own outer-loop review rather than by writing the tier. `codev task size` answers with
  zeros and `over_budget: false` for a task that does not exist, and for one
  whose state carries no base to diff against. A measurement of nothing is not
  a measurement of a small change; without the guard, any branch merely
  *named* `codev/...` would skip the gate. That `task size` reports a
  confident answer it cannot support remains a defect in its own right.
  The third was `_measure` returning a size of zero when it cannot load
  `git-state.json`: a branch merely *named* `codev/...`, given round state by
  hand without `codev git branch` ever recording it, measured as zero and
  skipped the gate however large it grew -- reproduced with a 500-line change
  scoring `within-budget-small-change`. That three separate paths all report a
  confident zero is the argument for fixing `_measure` at source, which this
  decision deliberately does not do.
- Size is measured in-process. Shelling out to `codev task size` dated from
  the hooks being standalone scripts; with the gates inside the package it
  made both depend on an executable being on PATH and being the same build --
  the class of silent failure that let 496 gate calls pass unchecked.
- No existing gate test changed from `ask` to `allow`, which is the evidence
  that the tier is additive rather than a relaxation.
