---
title: "Tutorial 4: two developers, one shared contract"
description: Coordinating two developers on the same feature through a shared contract and wave plan.
---

:::tip[Who actually types these commands]
As in the earlier tutorials, the `codev ...` commands below are what each developer's
`orchestrator` runs on their behalf. What's yours to do — and Priya's and Marcus's, below —
is agreeing on the contract in plain language before either lane starts building.
:::

The descriptor-support feature from [Tutorial 2](/CoDev/tutorials/a-design-worthy-change/)
is bigger than it looked: the core calculation change is one piece of work, and exposing
the new descriptor through the screening pipeline's request surface is another, and they
can happen in parallel — if both developers agree on the shape between them first. This
tutorial walks that coordination.

## Who this is for

You've read [Tutorial 2](/CoDev/tutorials/a-design-worthy-change/) or the
[Onboarding Guide](/CoDev/onboarding-guide/#multi-developer-briefly) and now have
an actual case: more than one developer, same feature, work that can genuinely run
concurrently rather than being artificially split to look parallel.

## The one rule that carries most of it

Every component or contract has one responsible owner, and the owner and reviewer are
never the same person. Two developers can work in parallel once they agree on a shared
contract — here, the exact shape of a `Descriptor` value the calculation engine produces
and the screening request surface consumes — and a fixture to test against it, rather than
discovering a mismatch after both branches are done.

## Step 1: the design settles the contract, not just the intent

[Tutorial 2](/CoDev/tutorials/a-design-worthy-change/)'s accepted design already named the
`Descriptor` representation. That's not incidental — it's the precondition for step 2. Don't
start parallel work from "we'll figure out the exact shape as we go"; that's exactly the
handshake that goes wrong under parallel implementation. If the design didn't settle it
firmly enough to write a fixture against right now, that's a sign to go back and settle it
before splitting the work, not while splitting it.

## Step 2: a wave plan for two lanes of work

With the design accepted, `plan-wave` turns it into a lightweight plan at
`docs/codev/wave/descriptor-support.md`:

```text
Wave: TPSA available alongside molecular weight in the screening pipeline

Lane A — Core descriptor engine (owner: Priya)
  Ready: replace compute_molecular_weight with compute_descriptor(mol, kind,
  exclude_salts); migrate the 3 existing call sites. Depends on: accepted design.
  Blocks: Lane B's real integration test (can develop against the fixture until
  Lane A lands).

Lane B — Screening request surface (owner: Marcus)
  Ready: accept a descriptor kind in the screening request; validate it; pass
  through to compute_descriptor. Depends on: the Descriptor fixture below, not on
  Lane A's actual code landing first.

Shared fixture: a `Descriptor(kind="molecular_weight", value=314.5, units="g/mol")`
and `Descriptor(kind="tpsa", value=45.2, units="Å²")` pair, checked in once, that
both lanes' tests import.

Integration checkpoint: once both lanes have a task in `ok_ready_for_pr`,
before either merges — confirm Lane B's real screening request produces the
same `Descriptor` shape Lane A's compute_descriptor actually expects, not just
what the fixture assumed.
```

A wave plan is a durable, reviewable repository artifact once you're actually using
it to coordinate — not a chat-only summary that only exists in one person's conversation.

## Step 3: both lanes build against the shared fixture, independently

Priya and Marcus each run their own task through the normal inner loop from
[Tutorial 1](/CoDev/tutorials/your-first-fix/) — own branch, own `codev task start`, own
build/review rounds — with one difference: Lane B's tests import the shared fixture
instead of waiting on Lane A's real implementation. This is the entire point of agreeing
on the contract first: neither lane blocks on the other actually landing.

```shell
# Priya, Lane A
codev task start --id descriptor-engine-core --base <sha> \
  --summary "Core descriptor engine (molecular weight + TPSA)" --link docs/codev/wave/descriptor-support.md

# Marcus, Lane B — started independently, same day
codev task start --id descriptor-request-surface --base <sha> \
  --summary "Screening request surface for descriptor selection" --link docs/codev/wave/descriptor-support.md
```

Each `--link` points back to the same wave plan — one fact (the plan), not copied into
each task's own description.

## Step 4: the integration checkpoint

Before either PR merges, the plan's integration checkpoint is a real stop, not a formality:
confirm the actual shapes match, not just the fixture's assumption of them. This is
normally a short, targeted check — run Lane B's request through Lane A's real
`compute_descriptor` once, by hand or in a small integration test — not a full second review
of either lane's work. If they don't match, that's a fixture that was wrong, caught before
either change reached production instead of after.

## Step 5: merge order and WIP

Merge order follows whichever lane is actually ready first — there's no rule that Lane A
must land before Lane B. What does matter: keep branches short-lived, and by default one
active implementation task per developer, so neither Priya nor Marcus is context-switching
across three half-finished lanes at once. If a third lane's ready work shows up mid-feature,
it waits for the plan's owner to sequence it in, rather than starting unplanned.

## Where to go next

- If review load across two open PRs needs the outer loop:
  [Tutorial 3](/CoDev/tutorials/outer-loop-review/)
- The full wave-plan mechanics — rolling-wave planning, dependency vocabulary in
  detail: read `.agents/skills/plan-wave/SKILL.md` directly in your installed
  repository, or
  [docs/product-map.md](https://github.com/urban233/CoDev/blob/main/docs/product-map.md)
  for where it fits alongside every other skill.
