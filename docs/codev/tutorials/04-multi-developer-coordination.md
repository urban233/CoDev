# Tutorial 4: two developers, one shared contract

The percentage-discounts feature from [Tutorial 2](02-a-design-worthy-change.md) is bigger
than it looked: the core calculation change is one piece of work, and exposing the new
discount type through the checkout API is another, and they can happen in parallel — if
both developers agree on the shape between them first. This tutorial walks that
coordination.

## Who this is for

You've read [Tutorial 2](02-a-design-worthy-change.md) or the
[onboarding guide](../onboarding/onboarding-guide.md#multi-developer-briefly) and now have
an actual case: more than one developer, same feature, work that can genuinely run
concurrently rather than being artificially split to look parallel.

## The one rule that carries most of it

Every component or contract has one responsible owner, and the owner and reviewer are
never the same person. Two developers can work in parallel once they agree on a shared
contract — here, the exact shape of a `Discount` value the pricing module produces and the
checkout API consumes — and a fixture to test against it, rather than discovering a
mismatch after both branches are done.

## Step 1: the design settles the contract, not just the intent

[Tutorial 2](02-a-design-worthy-change.md)'s accepted design already named the `Discount`
representation. That's not incidental — it's the precondition for step 2. Don't start
parallel work from "we'll figure out the exact shape as we go"; that's exactly the
handshake that goes wrong under parallel implementation. If the design didn't settle it
firmly enough to write a fixture against right now, that's a sign to go back and settle it
before splitting the work, not while splitting it.

## Step 2: a delivery plan for two lanes of work

With the design accepted, `plan-delivery` turns it into a lightweight plan at
`docs/codev/delivery/percentage-discounts.md`:

```text
Milestone: Percentage discounts available in checkout

Lane A — Core calculation (owner: Priya)
  Ready: update compute_total for the Discount type; migrate the 3 existing
  call sites. Depends on: accepted design. Blocks: Lane B's real integration
  test (can develop against the fixture until Lane A lands).

Lane B — Checkout API surface (owner: Marcus)
  Ready: accept a Discount in the checkout request; validate it; pass
  through to compute_total. Depends on: the Discount fixture below, not on
  Lane A's actual code landing first.

Shared fixture: a `Discount(kind="percent", value=0.15)` and
`Discount(kind="flat", value=10)` pair, checked in once, that both lanes'
tests import.

Integration checkpoint: once both lanes have a task in `ok_ready_for_pr`,
before either merges — confirm Lane B's real checkout request produces the
same `Discount` shape Lane A's compute_total actually expects, not just what
the fixture assumed.
```

A delivery plan is a durable, reviewable repository artifact once you're actually using
it to coordinate — not a chat-only summary that only exists in one person's conversation.

## Step 3: both lanes build against the shared fixture, independently

Priya and Marcus each run their own task through the normal inner loop from
[Tutorial 1](01-your-first-fix.md) — own branch, own `codev task start`, own build/review
rounds — with one difference: Lane B's tests import the shared fixture instead of waiting
on Lane A's real implementation. This is the entire point of agreeing on the contract
first: neither lane blocks on the other actually landing.

```shell
# Priya, Lane A
codev task start --id percentage-discounts-core --base <sha> \
  --summary "Core calculation for percentage discounts" --link docs/codev/delivery/percentage-discounts.md

# Marcus, Lane B — started independently, same day
codev task start --id percentage-discounts-api --base <sha> \
  --summary "Checkout API surface for percentage discounts" --link docs/codev/delivery/percentage-discounts.md
```

Each `--link` points back to the same delivery plan — one fact (the plan), not copied into
each task's own description.

## Step 4: the integration checkpoint

Before either PR merges, the plan's integration checkpoint is a real stop, not a formality:
confirm the actual shapes match, not just the fixture's assumption of them. This is
normally a short, targeted check — run Lane B's request through Lane A's real
`compute_total` once, by hand or in a small integration test — not a full second review of
either lane's work. If they don't match, that's a fixture that was wrong, caught before
either change reached production instead of after.

## Step 5: merge order and WIP

Merge order follows whichever lane is actually ready first — there's no rule that Lane A
must land before Lane B. What does matter: keep branches short-lived, and by default one
active implementation task per developer, so neither Priya nor Marcus is context-switching
across three half-finished lanes at once. If a third lane's ready work shows up mid-feature,
it waits for the plan's owner to sequence it in, rather than starting unplanned.

## Where to go next

- If review load across two open PRs needs the outer loop:
  [Tutorial 3](03-outer-loop-review.md)
- The full delivery-plan mechanics — rolling-wave planning, dependency vocabulary in
  detail: read `.agents/skills/plan-delivery/SKILL.md` directly, or
  `docs/product-map.md` for where it fits alongside every other skill.
