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

:::tip[Who actually types these commands]
Every `codev ...` command below is shown so you can see exactly what happens under the
hood. In a real session, your agent runs almost all of them for you — you only supply
the plain-language parts, in Step 2 and wherever the tutorial shows you approving
something. See [Talking to Your Agent](/CoDev/working-with-your-agent/) for the shape of
that conversation.
:::

For the concepts behind these steps, see the
[Onboarding Guide](/CoDev/onboarding-guide/); this tutorial is the narrated "do
this" companion to it.

## Who this is for

You have `codev` installed (`pipx install open-codev-workflow` or
`uv tool install open-codev-workflow`) and a Git repository you want to try it in — your
own, or a scratch one. You don't need to know anything about CoDev's internals to follow
this.

## The bug

A compound-screening pipeline's molecular-weight calculator is wrong for salt forms: it's
supposed to strip the counter-ion fragment before summing atomic mass when
`exclude_salts=True`, but sums every fragment regardless — so a salt-form compound's
computed weight comes out too high. The fix is genuinely small — this tutorial is
deliberately about the smallest realistic case, because that's the case most people hit
first, and the full lifecycle still applies to it.

## Step 1: install CoDev into the repository

```shell
codev init --target . --agent-platform opencode
```

```text
ADD       .agents/skills/build-change/SKILL.md
ADD       .agents/skills/build-change/agents/openai.yaml
...
ADD       .opencode/agents/builder.md
...
ADD       docs/codev/README.md
...
INTEGRATE AGENTS.md — append managed policy block
INTEGRATE .gitignore — append escalation-log ignore rule
INTEGRATE .opencode/opencode.json — integrated OpenCode agents: code-audit,
code-audit-gate, builder, reviewer, lightweight-reviewer, ...
Installed CoDev 0.6.0 into /path/to/your/repo
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
CoDev 0.5.0 - /path/to/your/repo
Bundle: healthy (76 managed files, no drift)
Adapters: opencode
Tasks in progress: 0
```

## Step 2: describe the bug to your AI assistant

Start a session in the repository and state the outcome in plain language --
there is no agent to switch to first:

```text
Fix compute_molecular_weight so exclude_salts=True actually strips the counter-ion
fragment before summing mass. Add a regression test with a salt-form compound.
```

You don't need to name a skill. The assistant begins with **Understand**: it inspects the
actual descriptor code, and for a change this small and unambiguous, presents a short
focus card instead of a full brief — something like:

```text
Change:      exclude_salts=True should drop counter-ion fragments before summing mass.
Success:     A salt-form compound's computed weight matches its free-base weight; a
             single-fragment compound's weight is unchanged.
Non-goals:   No change to fragment-splitting itself.
Scope:       screening/descriptors.py, tests/test_descriptors.py
Validation:  python -m unittest discover -s tests
Stop if:     split_into_fragments doesn't reliably separate the salt from the parent
             (that would be a different, bigger bug upstream).
```

Nothing here needs a design document or a wave plan — no shared contract changes, no
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
codev task start --id descriptor-salt-stripping-fix \
  --base 4f3aaf0537be7fd58ef431d146c750df6a2a2461 \
  --summary "Strip counter-ion salts before summing molecular weight" --no-github-issue
```

```text
Started task descriptor-salt-stripping-fix at /path/to/your/repo/.codev/task/descriptor-salt-stripping-fix/round-state.json
```

(`--no-github-issue` is only correct for a scratch repo with no GitHub remote, like the one
this was run against. In a real GitHub-backed repository, use `--github-issue <number>` or
let your agent create one for you — see
[Starting Prompts](/CoDev/starting-prompts/) for why that's worth naming up
front.)

```shell
codev git branch --id descriptor-salt-stripping-fix \
  --base 4f3aaf0537be7fd58ef431d146c750df6a2a2461
```

```text
Created branch codev/descriptor-salt-stripping-fix for descriptor-salt-stripping-fix
```

Your agent normally performs this recording and branching itself as part of the
same conversation, in one call to `codev slice begin` -- these two commands are shown
separately here so you see exactly what state they create.

## Step 4: build, with evidence

Ask the assistant to implement the approved focus card. It inspects the actual code before
editing:

```python
# screening/descriptors.py, before
def compute_molecular_weight(mol, exclude_salts=True):
    fragments = split_into_fragments(mol)
    total = sum(
        fragment_mass(f) for f in fragments
    )  # <- salts included unconditionally
    return total
```

```python
# screening/descriptors.py, after
def compute_molecular_weight(mol, exclude_salts=True):
    fragments = split_into_fragments(mol)
    if exclude_salts:
        fragments = [largest_fragment(fragments)]
    return sum(fragment_mass(f) for f in fragments)
```

...and adds the regression test alongside the existing one, runs the suite, and reports
back:

```text
Delivered:    Salt-form compounds no longer include counter-ion mass in the computed
              weight; single-fragment compounds are unchanged.
Changed:      screening/descriptors.py, tests/test_descriptors.py
Validation:   python -m unittest discover -s tests -v -- both tests pass
Known limitations: none
Review state: AWAITING INDEPENDENT REVIEW
```

The builder does not commit or call `codev task record` itself — whoever
dispatched it commits the diff and records the evidence against that exact
resulting head, in one call to `codev round close`:

```shell
codev git commit --id descriptor-salt-stripping-fix \
  --message "Strip counter-ion salts before summing molecular weight"
```

```text
Committed cc62907e9ef4942d401826e2d0021f7ed6ab62d4 on descriptor-salt-stripping-fix's branch
```

```shell
codev task record --id descriptor-salt-stripping-fix --round 1 --role builder \
  --head cc62907e9ef4942d401826e2d0021f7ed6ab62d4 --evidence evidence.json
```

```text
Recorded round 1 (builder) for descriptor-salt-stripping-fix
```

## A mistake you will probably also make

Calling `codev task check` right after `codev git commit`, before recording the builder
round, looks like this:

```shell
codev task check --id descriptor-salt-stripping-fix --head cc62907e9ef4942d401826e2d0021f7ed6ab62d4
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
codev task record --id descriptor-salt-stripping-fix --round 1 --role reviewer \
  --head cc62907e9ef4942d401826e2d0021f7ed6ab62d4 \
  --findings findings.json --coverage coverage.json \
  --decision READY_FOR_OUTER_LOOP
```

```text
Recorded round 1 (reviewer) for descriptor-salt-stripping-fix
```

Now check whether the loop may proceed:

```shell
codev task check --id descriptor-salt-stripping-fix --head cc62907e9ef4942d401826e2d0021f7ed6ab62d4
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
codev git push --id descriptor-salt-stripping-fix
codev git open-pr --id descriptor-salt-stripping-fix \
  --title "Strip counter-ion salts before summing molecular weight"
```

These need an actual GitHub remote to do anything (this tutorial's demo repo didn't have
one, so there's no output to show here — in a real repository you'll see the PR URL). The
PR opens as a draft. For a change this small, the outer loop's five specialists are
optional but still available — see [Tutorial 3](/CoDev/tutorials/outer-loop-review/) if
you want to see that in action on a slightly larger change. When ready:

```shell
codev git mark-ready --id descriptor-salt-stripping-fix
```

## Step 7: the human decision, and closing the task

You inspect the actual pull request and CI, and decide whether to merge. After that human
decision:

```shell
codev task close --id descriptor-salt-stripping-fix --outcome approved
```

```text
Closed task descriptor-salt-stripping-fix as approved
```

```shell
codev status --target .
```

```text
CoDev 0.5.0 - /path/to/your/repo
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
  [Manual CLI Walkthrough](/CoDev/workflow-checklist/)
