**Status:** Accepted
**Date:** 2026-08-31
**Owner:** Martin Urban
**Related design:** [docs/features/plan-wave/design.md](../features/plan-wave/design.md)

## Context

`build-change`'s task-slicing rule requires every task to remain
"buildable and useful," and permits splitting a task only when each part
keeps that property. That rule fights work with a genuine engineering
dependency order — schema before logic before wiring — and makes a wave
harder to slice than it needs to be: foundation work often has no
independent value on its own, only once later pieces land on top of it.

`git.pr_base` (ADR-0013) is CoDev's only config key today, resolved through
`config.py`'s single `resolve(key, *, target, override)` function — flag,
then environment variable, then project config, then global config, then
`DEFAULTS`, which is intentionally empty until a feature needs an entry.
CoDev's architecture already refuses to make a target repository depend on
CoDev at runtime; any containment mechanism this decision introduces must
respect that.

## Decision

Add `git.workflow`, resolved through `config.py`'s existing mechanism with
no new resolution logic — the same pattern `git.pr_base` already
established. `DEFAULTS["git.workflow"] = "trunk"`; `feature-branch` is an
explicit, fully-supported override, not a degraded path. No config schema
version change.

Under `trunk`, `plan-wave`'s and `build-change`'s task-slicing guidance
allows a task to split at an engineering-dependency boundary instead of
only a usefulness boundary, provided the task states how it stays
contained. A free-text containment field is added to the task issue
template and the implementation-plan template, describing whatever
mechanism — or none — the project already uses. CoDev never ships, bundles,
or manages actual feature-flag infrastructure; the field is advisory, not
machine-checked. Every prompt or nudge this adds must read `git.workflow`
and disable itself cleanly under `feature-branch`, not fire anyway.

## Alternatives considered

- **Two separate config keys**, one for branch-lifetime guidance and one
  for slicing/containment guidance: deferred rather than rejected — one key
  matches `git.pr_base`'s precedent and is simpler to explain; design.md
  names this an assumption to test during implementation, split only if one
  key proves too coarse.
- **CoDev ships or manages real feature-flag infrastructure:** rejected —
  contradicts a target repository never importing CoDev as a runtime
  dependency, and is the wrong scale of tooling for a solo-to-ten-engineer
  audience.
- **Treat `git.workflow` as a pure branch/PR-target convention with no
  effect on task slicing:** rejected — slicing is the facet that actually
  serves wave planning; a workflow key that never touches slicing would not
  address the problem this decision is scoped to solve.

## Consequences

- Real behavior change for every adopter the moment this ships:
  `git.workflow` resolves to `trunk` by default without an explicit
  opt-in, so updated slicing prose and new nudges apply on the next
  update, not only for projects that ask for them. Called out explicitly
  in the changelog, matching how the Claude Code adapter's platform-count
  change was called out.
- Rollback for one project is `codev config set git.workflow
  feature-branch`; no destructive rollback path is needed, since every
  affected gate or nudge only ever asks.
- Testing: a config round-trip test for `git.workflow` mirrors
  `PersistenceTests`'s existing dotted-key regression test from ADR-0013.

## Revisit when

Implementation shows one key cannot cleanly serve both branch-lifetime
guidance and slicing/containment guidance — the assumption named in
design.md — in which case split into two keys then, not preemptively. Also
revisit if real usage shows the free-text containment field is filled with
descriptions that do not match reality often enough to warrant a
machine-checked alternative.
