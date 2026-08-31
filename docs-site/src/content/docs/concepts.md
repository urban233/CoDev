---
title: Concepts
description: The workflow steps CoDev walks a developer and AI through, and the codev commands behind each one.
---

A developer and AI move through four steps — **Understand, Build, Review, Ship** — plus
two that only show up when the work actually needs them: **Specify** for a genuinely new
product, **Launch** for a real rollout decision.

## Understand

The task is opened and its round state starts tracking. `codev task start --id <id>
--base <sha>` opens a new task; this tracks the task's round history as local JSON under
`.codev/task/` and never writes product source itself.

## Build

A bounded builder makes the change. Every commit and push goes through CoDev's own git
commands (`codev git commit`, `codev git push`) — this is the only path for an agent to
mutate the repository or GitHub; raw `git commit`/`git push` are denied to every role for
exactly this reason.

## Review

Review is layered, not a single pass:

1. A fast correctness check runs after each build round.
2. An automatic style and maintainability gate runs immediately before a pull request
   opens.
3. Five parallel specialist reviewers run once the pull request is open.

`codev task check --id <id> --head <sha>` asks whether the task may proceed to a pull
request at all.

## Ship

`codev git open-pr --id <id> --title <title>` opens the pull request as a draft.
`codev git mark-ready --id <id>` marks it ready for human review once the outer loop says
so. `codev task close --id <id> --outcome approved|abandoned|escalated` closes the task.
Human authority stays over merge, deployment, and rollout — CoDev supplies evidence, not
approval.

## Specify (only for a genuinely new product)

Deeper design and delivery planning appear only when risk or coordination requires them —
small changes skip straight to Understand → Build.

## Launch (only for a real rollout decision)

Same principle as Specify: this step exists for the moments that actually need it, not as
a mandatory gate on every change.

## Recovery and coordination

`codev task triage | escalate | escalations | waive | reopen | relink` cover the
outer-loop and recovery operations — what happens when a task stalls, conflicts with
another developer's work, or needs a human decision before it can continue. See the
[CLI reference](/CoDev/cli-reference/#the-task-lifecycle) for the full command table.
