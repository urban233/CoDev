---
title: "Tutorial 2: a change that needs a design"
description: What changes when a fix touches a shared contract instead of being small and unambiguous.
---

:::tip[Who actually types these commands]
As in [Tutorial 1](/CoDev/tutorials/your-first-fix/), the `codev ...` commands below are
what your agent runs on your behalf. What's yours to do is stated in plain language at each
step — describing the change, and deciding the shared representation the design settles on.
:::

[Tutorial 1](/CoDev/tutorials/your-first-fix/) skipped Understand almost entirely — the bug
was small and unambiguous. This tutorial covers the other case: a change that touches
something other code depends on, where getting it wrong is expensive to unwind later. By
the end you'll know exactly which properties of a change trigger `design-solution`, what
it produces, and how that feeds into Build.

## Who this is for

You've already done [Tutorial 1](/CoDev/tutorials/your-first-fix/) or know the four-step
shape from the [Onboarding Guide](/CoDev/onboarding-guide/), and you want to see what
changes when a fix isn't small.

## The change

Continuing the descriptor example: product wants a second descriptor computed through the
same pipeline — TPSA (topological polar surface area) alongside the existing molecular
weight — and other code already calls `compute_molecular_weight(mol, exclude_salts)` in
three places. This isn't a bug fix; it's a new shape for an existing function every caller
depends on. That's the signal.

## Why this triggers Design

From the [Onboarding Guide](/CoDev/onboarding-guide/#two-steps-that-only-show-up-sometimes):
Design is conditional depth inside Understand, triggered by real properties of the
change — not by size. This change qualifies because:

- It changes a **shared contract** — `compute_molecular_weight`'s signature, called from
  three other places.
- Getting the descriptor representation wrong (a bare float? which units for which kind?
  what happens to a caller that doesn't know about TPSA yet?) is exactly the kind of
  decision that's cheap to get right once and expensive to unwind after three call sites
  depend on the wrong shape.

A one-line salt-stripping fix didn't have either property. This one has both.

## Step 1: describe the change

State the outcome to your assistant. Where the platform supports a separate `lead`
entry point (OpenCode, Claude Code), switch to it for Understand/Design work — it's a
distinct, human-started entry point from `lead`, decoupled from execution
([ADR-0024](https://github.com/urban233/CoDev/blob/main/docs/adr/0024-lead-primary-agent.md)):

```text
We need to compute TPSA alongside the existing molecular weight in the screening
pipeline. Three call sites use compute_molecular_weight today.
```

The assistant investigates the actual call sites first — not just the function
definition — and, because this is a shared-contract change, proposes a brief before
touching design: outcome, who's affected, what's explicitly out of scope (e.g. "no change
to how salts are excluded" if that's true), and success criteria. For a feature this size,
that's `docs/codev/features/descriptor-support/brief.md`. Review it, correct anything wrong
about the framing, and accept it.

## Step 2: the design

With the brief accepted, `design-solution` drafts
`docs/codev/features/descriptor-support/design.md`, grounded in the actual current code
(not an idealized rewrite). For a change this size, expect it to settle:

- **A unified entry point** — `compute_descriptor(mol, kind, exclude_salts=True)` returning
  a `Descriptor(kind, value, units)` result, instead of one hardcoded function per
  property.
- **Every call site**, named explicitly, with what changes at each one — not "update
  callers as needed."
- **What happens at the boundary values** — an unknown `kind`, whether `exclude_salts`
  even applies the same way to TPSA as it does to molecular weight. These are exactly the
  questions worth settling on paper before three call sites each guess differently.
- **Test strategy** — one test per call site's actual usage, not just the new function in
  isolation.

This is where a real decision belongs to you, not the AI: which representation to use, and
whether existing callers get migrated in this change or a follow-up. The assistant
proposes an option with trade-offs; you decide. Once you accept the design, it becomes the
authority the builder works against — matching [Tutorial 1](/CoDev/tutorials/your-first-fix/)'s
rule that later documents link to earlier ones rather than repeating them.

## Step 3: build against the accepted design

From here it's the same loop as Tutorial 1 — `codev task start`, `codev git branch`, build
in bounded rounds, `codev task record`, `codev task check` — except the builder now treats
the accepted design as authority it doesn't get to redesign to make coding easier. If the
implementation reveals the design missed a case (a fourth call site nobody remembered),
that's a stop condition, not something to quietly patch around: the builder returns
`BLOCKED` with exact evidence, and the design gets corrected before implementation
continues.

## The rule this tutorial is really about

Risk and coordination decide how much of Understand you need — not the size of the diff.
A five-line change to a permission check gets exactly this same design treatment even
though the diff is tiny, because the *property* that matters (a security boundary) is
present regardless of line count. A three-hundred-line change that's purely additive, with
no shared contract and no risk property, can skip straight to Build. Check the properties,
not the size.

## Where to go next

- Taking the resulting PR through outer-loop review: [Tutorial 3](/CoDev/tutorials/outer-loop-review/)
- Coordinating this kind of change across two developers:
  [Tutorial 4](/CoDev/tutorials/multi-developer-coordination/)
