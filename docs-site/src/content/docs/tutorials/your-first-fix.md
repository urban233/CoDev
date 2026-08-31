---
title: "Tutorial 1: your first fix"
description: A start-to-finish walkthrough of one small, real bug fix through CoDev.
---

A start-to-finish walkthrough of one small, real bug fix through CoDev: install, describe
the bug, build, review, and (where a GitHub remote exists) open the pull request. By the
end you'll have run every CLI command in the normal inner loop yourself and know what real
output looks like at each step — not a hypothetical reconstruction. The CLI commands and
output below were run against the real `codev` CLI while writing this tutorial, including
the one mistake in "A mistake you will probably also make" further down.

For the concepts behind these steps, see the
[Onboarding Guide](/CoDev/onboarding-guide/); this tutorial is the narrated "do
this" companion to it.

## Who this is for

You have `codev` installed (`pipx install open-codev-workflow` or
`uv tool install open-codev-workflow`) and a Git repository you want to try it in — your
own, or a scratch one. You don't need to know anything about CoDev's internals to follow
this.

## The bug

A checkout total is wrong: a discount applied to a tax-exempt item still gets taxed. The
fix is genuinely small — this tutorial is deliberately about the smallest realistic case,
because that's the case most people hit first, and the full lifecycle still applies to it.

## Step 1: install CoDev into the repository

```shell
codev init --target . --agent-platform opencode
```

```text
ADD       .agents/skills/build-change/SKILL.md
ADD       .agents/skills/build-change/agents/openai.yaml
...
ADD       .opencode/agents/orchestrator.md
...
ADD       docs/codev/README.md
...
INTEGRATE AGENTS.md — append managed policy block
INTEGRATE .gitignore — append escalation-log ignore rule
INTEGRATE .opencode/opencode.json — integrated OpenCode agents: orchestrator, planner, ...
Installed CoDev 0.4.0 into /path/to/your/repo
```

(Real run had ~70 `ADD` lines — every skill and agent file gets listed. Trimmed here; your
terminal will show the full list.) Commit this as one infrastructure change:

```shell
git add -A && git commit -m "Install CoDev"
```

Check it installed cleanly:

```shell
codev status --target .
```

```text
CoDev 0.4.0 - /path/to/your/repo
Bundle: healthy (76 managed files, no drift)
Adapters: opencode
Tasks in progress: 0
```

## Step 2: describe the bug to your AI assistant

Start a session in the repository (on OpenCode, switch to the `orchestrator` agent) and
state the outcome in plain language:

```text
Fix the checkout total when a discount is applied to a tax-exempt item. The
total must include the discount but not tax. Add a regression test.
```

You don't need to name a skill. The assistant begins with **Understand**: it inspects the
actual pricing code, and for a change this small and unambiguous, presents a short focus
card instead of a full brief — something like:

```text
Change:      Tax-exempt items should never have tax applied, discount or not.
Success:     A tax-exempt, discounted order's total excludes tax; a taxable,
             discounted order's total is unchanged.
Non-goals:   No change to discount calculation itself.
Scope:       checkout/pricing.py, tests/test_pricing.py
Validation:  python -m unittest discover -s tests
Stop if:     the tax-exempt flag isn't reaching this function at all (that
             would be a different, bigger bug upstream).
```

Nothing here needs a design document or a delivery plan — no shared contract changes, no
new API, one file. Approve it and move to Build.

## Step 3: start and branch the tracked task

Capture the current commit as the base, then start the task and create its branch:

```shell
git rev-parse HEAD
```

```text
4f3aaf0537be7fd58ef431d146c750df6a2a2461
```

```shell
codev task start --id checkout-tax-exempt-total \
  --base 4f3aaf0537be7fd58ef431d146c750df6a2a2461 \
  --summary "Correct tax-exempt checkout totals" --no-github-issue
```

```text
Started task checkout-tax-exempt-total at /path/to/your/repo/.codev/task/checkout-tax-exempt-total/round-state.json
```

(`--no-github-issue` is only correct for a scratch repo with no GitHub remote, like the one
this was run against. In a real GitHub-backed repository, use `--github-issue <number>` or
let the orchestrator create one for you — see
[Starting Prompts](/CoDev/starting-prompts/) for why that's worth naming up
front.)

```shell
codev git branch --id checkout-tax-exempt-total \
  --base 4f3aaf0537be7fd58ef431d146c750df6a2a2461
```

```text
Created branch codev/checkout-tax-exempt-total for checkout-tax-exempt-total
```

An AI-driven `orchestrator` normally performs this recording and branching itself as part
of the same conversation — these two commands are shown separately here so you see exactly
what state they create.

## Step 4: build, with evidence

Ask the assistant to implement the approved focus card. It inspects the actual code before
editing:

```python
# checkout/pricing.py, before
def compute_total(subtotal, discount, is_tax_exempt, tax_rate=0.08):
    discounted = subtotal - discount
    tax = discounted * tax_rate  # <- tax applied unconditionally
    return discounted + tax
```

```python
# checkout/pricing.py, after
def compute_total(subtotal, discount, is_tax_exempt, tax_rate=0.08):
    discounted = subtotal - discount
    tax = 0 if is_tax_exempt else discounted * tax_rate
    return discounted + tax
```

...and adds the regression test alongside the existing one, runs the suite, and reports
back:

```text
Delivered:    Tax-exempt items no longer taxed; discounts still apply.
Changed:      checkout/pricing.py, tests/test_pricing.py
Validation:   python -m unittest discover -s tests -v -- both tests pass
Known limitations: none
Review state: AWAITING INDEPENDENT REVIEW
```

The builder does not commit or call `codev task record` itself — the orchestrator commits
the diff, then records the evidence against that exact resulting head:

```shell
codev git commit --id checkout-tax-exempt-total \
  --message "Fix tax-exempt checkout total"
```

```text
Committed cc62907e9ef4942d401826e2d0021f7ed6ab62d4 on checkout-tax-exempt-total's branch
```

```shell
codev task record --id checkout-tax-exempt-total --round 1 --role builder \
  --head cc62907e9ef4942d401826e2d0021f7ed6ab62d4 --evidence evidence.json
```

```text
Recorded round 1 (builder) for checkout-tax-exempt-total
```

## A mistake you will probably also make

Calling `codev task check` right after `codev git commit`, before recording the builder
round, looks like this:

```shell
codev task check --id checkout-tax-exempt-total --head cc62907e9ef4942d401826e2d0021f7ed6ab62d4
```

```text
stop_drift: round 1: expected head 4f3aaf053...; got cc62907e9...; code changed
outside the tracked builder/reviewer flow
```

That's not a bug — it's the drift guard working exactly as designed
([ADR-0001](https://github.com/urban233/CoDev/blob/main/docs/adr/0001-work-lifecycle-invariant.md)):
the tool has no evidence yet that the new head came from a recorded round, so it refuses
to assume it did. Record the round first, *then* check.

## Step 5: independent review

A fresh reviewer context — human, and where the platform supports subagents, automatically
also AI — looks at the exact diff, not the builder's private reasoning. It records its
verdict:

```shell
codev task record --id checkout-tax-exempt-total --round 1 --role reviewer \
  --head cc62907e9ef4942d401826e2d0021f7ed6ab62d4 \
  --findings findings.json --coverage coverage.json \
  --decision READY_FOR_OUTER_LOOP
```

```text
Recorded round 1 (reviewer) for checkout-tax-exempt-total
```

Now check whether the loop may proceed:

```shell
codev task check --id checkout-tax-exempt-total --head cc62907e9ef4942d401826e2d0021f7ed6ab62d4
```

```text
ok_ready_for_pr: round 1: inner loop satisfied, ready to open a pull request
```

`--decision READY_FOR_OUTER_LOOP` is what routes here — it's the normal inner-loop
handoff, distinct from `READY_FOR_HUMAN_APPROVAL` (used by `review-change`'s standalone,
no-task, no-PR review path). Using the wrong one is an easy mix-up; if `task check` reports
`ok_approve` instead of `ok_ready_for_pr`, that's why.

## Step 6: open the pull request (needs a real GitHub remote)

Once `task check` reports `ok_ready_for_pr`, push and open the PR using the guarded Git
commands — they act on this task's branch, never the default branch:

```shell
codev git push --id checkout-tax-exempt-total
codev git open-pr --id checkout-tax-exempt-total \
  --title "Fix tax-exempt checkout total"
```

These need an actual GitHub remote to do anything (this tutorial's demo repo didn't have
one, so there's no output to show here — in a real repository you'll see the PR URL). The
PR opens as a draft. For a change this small, the outer loop's five specialists are
optional but still available — see [Tutorial 3](/CoDev/tutorials/outer-loop-review/) if
you want to see that in action on a slightly larger change. When ready:

```shell
codev git mark-ready --id checkout-tax-exempt-total
```

## Step 7: the human decision, and closing the task

You inspect the actual pull request and CI, and decide whether to merge. After that human
decision:

```shell
codev task close --id checkout-tax-exempt-total --outcome approved
```

```text
Closed task checkout-tax-exempt-total as approved
```

```shell
codev status --target .
```

```text
CoDev 0.4.0 - /path/to/your/repo
Bundle: healthy (76 managed files, no drift)
Adapters: opencode
Tasks in progress: 0
```

That's the whole loop. Everything after this point is the same shape, just with more
happening inside "Understand" (Tutorials 2 and 4) or "Review" (Tutorial 3) as risk and
coordination need actually call for it — never because a bigger change means more
ceremony by default.

## Where to go next

- A change that touches a shared contract: [Tutorial 2](/CoDev/tutorials/a-design-worthy-change/)
- Reviewing an already-open pull request: [Tutorial 3](/CoDev/tutorials/outer-loop-review/)
- Two developers, one shared contract: [Tutorial 4](/CoDev/tutorials/multi-developer-coordination/)
- The command checklist for when you already know the shape:
  [Workflow Checklist](/CoDev/workflow-checklist/)
