---
title: Evaluating Skills
description: Measure whether a skill actually helps, empirically, instead of trusting that it does.
---

A skill is a prompt. Prompts are asserted to work far more often than they are
measured. CoDev ships a general-purpose evaluation harness so you can find out
whether yours does — with **your** skill, in **your** repository.

It is not limited to CoDev's own skills, and it is one of the largest
capabilities in the product.

## What a task looks like

An evaluation task is a directory holding four things:

| File | What it carries |
|---|---|
| `prompt.md` | What the agent is asked. **Never names the skill** — a prompt that names it measures obedience, not usefulness |
| `repository/` | The starting state the agent works against |
| `verifier.json` | A deterministic check: a command and the result it must produce |
| `rubric.md` | What a judge should weigh where determinism runs out |

The prompt not naming the skill is the load-bearing rule. If the prompt says
"use the X skill", a passing result tells you the agent can follow an
instruction, which you already knew.

## Running one

Your agent runs these for you, as with everything else. A task runs against a
disposable copy of `repository/`, so a run cannot damage your working tree.

A **benchmark** runs a skill's whole task set twice — once with the skill
available and once without — and reports the difference. The comparison is the
measurement. A high with-skill score on its own says nothing: the model may
have been able to do it anyway.

Repetitions matter, because a single run of a non-deterministic system is an
anecdote.

## Reading the result

The number that means something is the **delta** between with-skill and
baseline, per category. A skill that scores well on both is not earning its
place in the context window.

A benchmark run writes its trace into the skill's own package, so a skill
carries its evidence with it rather than leaving it in someone's terminal
history.

## Designing a good task

- Pick a falsifiable ground truth. "Better documentation" is not one.
- Prefer a deterministic verifier; reach for a judge only where you must.
- Write the prompt as a developer would actually phrase it.
- Seed a real defect rather than an implausible edge case.

## Next

- [The Workflow](/CoDev/concepts/) — where skills sit in the phases
- [CLI reference](/CoDev/cli-reference/) — every `codev eval` command
