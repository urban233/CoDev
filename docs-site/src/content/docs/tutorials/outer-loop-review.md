---
title: "Tutorial 3: outer-loop review on an open pull request"
description: Starting the outer loop, choosing specialists, triaging findings, and reaching a mergeable state.
---

Once a pull request is open, five specialist reviewers — correctness, security,
concurrency, architecture, rollout — can examine it in parallel, on top of the fast
correctness pass and style gate that already ran during Build. This tutorial walks that
outer loop end to end: starting it, choosing which specialists actually run, triaging
findings, and getting to a mergeable state.

## Who this is for

You have an open pull request from a task that went through the inner loop (Tutorial 1 or
2), on a platform with subagent support (OpenCode or Claude Code), and want independent
review beyond the automatic per-build checks.

## Starting the outer loop

Switch to the `outer-loop-runner` agent (on OpenCode: `/agent outer-loop-runner`) and give
it the PR number. [Starting Prompts](/CoDev/starting-prompts/) has the exact
phrasing worth using every time:

```text
Start outer-loop review for PR #47. Present the five specialists as a
numbered menu and wait for my selection before dispatching anything — don't
run a fresh five-specialist pass on your own judgment.
```

That second sentence matters. `outer-loop-runner` is instructed to present the menu before
dispatching anything
([ADR-0016](https://github.com/urban233/CoDev/blob/main/docs/adr/0016-human-selectable-specialist-dispatch-with-authorized-coverage-waivers.md)),
but nothing mechanically forces a model to render it first — restating the expectation
closes that gap. On OpenCode, each specialist dispatch also requires its own explicit
permission confirmation regardless of what gets narrated, as a mechanical backstop
independent of the prompt
([ADR-0021](https://github.com/urban233/CoDev/blob/main/docs/adr/0021-opencode-specialist-dispatch-permission-gate.md))
— you'll see one confirmation prompt per specialist either way.

It fetches the PR and CI state, then presents something like:

```text
Ready to dispatch. Which specialists?
  1. correctness-tests-specialist
  2. security-data-specialist
  3. concurrency-specialist
  4. architecture-maintainability-specialist
  5. rollout-specialist
  all. all five
```

For a checkout pricing change, security/data and concurrency are plausible skips if
nothing here touches auth, PII, or shared mutable state — but say so explicitly rather than
letting the assistant decide. Reply with the numbers you want, or `all`. Whatever you pick,
CoDev records exactly which specialists ran, distinct from what was merely asked, in
`codev task log --id <id>`.

## Reading findings

Each dispatched specialist returns findings ranked most-important-first with a binary
`blocking` flag — no severity scale to argue about, just "does this block merge or not."
A finding that's real but not blocking (a naming nit, a missing edge-case test for
something genuinely low-risk) doesn't have to stop the PR; you decide which findings need
a fix before merge and which can be tracked separately.

## Triaging findings

Record your triage decision per finding:

```shell
codev task triage --id checkout-percentage-discounts --round 2 --triage triage.json
```

Where `triage.json` maps each finding id to a disposition — fix now, defer with a reason,
or accepted as-is. If a whole review dimension doesn't apply (say, rollout, for a change
with no staged exposure to plan), waive it explicitly rather than leaving it silently
incomplete:

```shell
codev task waive --id checkout-percentage-discounts \
  --dimension rollout --reason "internal pricing logic; no staged exposure"
```

A waiver is an authorized, recorded decision — not the same thing as a reviewer simply not
covering that dimension. `codev task check` treats an unwaived, uncovered dimension as
incomplete coverage and refuses to call the round ready.

## Sending a fix back through Build

If a finding needs code changes, that goes back through the inner loop, not a quick patch
applied outside it: hand the specific finding to `build-change` (or the `builder`
subagent), get the correction, and get a *new* review of the changed snapshot — reusing the
same round-recording mechanics as Tutorial 1, at the next round number. Never treat a
review comment as authorization to skip re-review of the fix itself.

## Marking the PR ready

Once every review dimension passes or is explicitly waived:

```shell
codev git mark-ready --id checkout-percentage-discounts
```

This is the last mechanical step. From here it's the same human decision as Tutorial 1:
you read the actual PR, the evidence, and CI, and decide whether to merge — CoDev and the
AI supply evidence, never the approval itself.

## Where to go next

- The full round-state and waiver mechanics:
  [docs/product-map.md](https://github.com/urban233/CoDev/blob/main/docs/product-map.md)
- Coordinating this kind of review load across two developers:
  [Tutorial 4](/CoDev/tutorials/multi-developer-coordination/)
