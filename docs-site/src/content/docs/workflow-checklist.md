---
title: Manual CLI Walkthrough
description: The exact command sequence a normal task goes through — what your agent runs, not what you type.
---

:::note[This is what your agent runs, not what you type]
In a normal session, `orchestrator` runs this exact sequence on your behalf — see
[Talking to Your Agent](/CoDev/working-with-your-agent/). Read this page to understand the
mechanism, to run CoDev outside an agent session (CI, scripting), or to recover a task by
hand.
:::

The exact command sequence for a normal bug fix, small feature, or planned task, once you
already know the shape from [Tutorial 1](/CoDev/tutorials/your-first-fix/) or the
[Onboarding Guide](/CoDev/onboarding-guide/). This page assumes you know *why* each command
exists; it's the terse reference, not the walkthrough.

## Daily command checklist

```shell
# Once per repository
codev init --target . --agent-platform all

# One normal task
git rev-parse HEAD
codev task start --id <id> --base <base-sha> --summary "<outcome>" --link <url>
codev git branch --id <id> --base <base-sha>

# During build and review
codev task status
codev task record --id <id> --round <n> --role builder --head <sha> --evidence <file>
codev task record --id <id> --round <n> --role reviewer --head <sha> \
  --findings <file> --coverage <file> --decision READY_FOR_OUTER_LOOP
codev task check --id <id> --head "$(git rev-parse HEAD)"

# When ready for a pull request
codev git commit --id <id> --message "<message>"
codev git push --id <id>
codev git open-pr --id <id> --title "<title>"
codev git mark-ready --id <id>

# After the human decision
codev task close --id <id> --outcome approved
codev status --target .
```

`--link` points to the issue, brief, design, or plan that authorizes the work. For work
already represented by a GitHub issue, use `--github-issue <number>` instead. `--outcome`
also accepts `abandoned` (intentionally stopped) or `escalated` (needs an unresolved human
decision).

## Starting from work already in progress

If you started coding before involving CoDev, pick one entry mode deliberately instead of
a cold `codev task start`:

```shell
# Unfinished work: let the build loop continue the existing diff.
codev task start --id <id> --base <base-sha> --entry takeover --summary "<outcome>"

# Finished work: skip the build loop and send it straight to review.
codev task start --id <id> --base <base-sha> --entry direct-review --summary "<outcome>"
```

## Updating the installed workflow

Preview first, and resolve any reported local changes rather than overwriting them:

```shell
codev diff --target .
codev update --target .
```

Never run `init`, `update`, or `remove` while product code is mid-build.

## Full reference

- [Talking to Your Agent](/CoDev/working-with-your-agent/) — how this sequence actually
  gets triggered in normal use: you talk, your agent runs it.
- [Tutorial 1: your first fix](/CoDev/tutorials/your-first-fix/) — the narrated version
  of the checklist above, with real output at every step.
- [CLI reference](/CoDev/cli-reference/) — every command, not just the ones in a normal
  task.
- [Starting Prompts](/CoDev/starting-prompts/) — copy-paste prompts for the two moments
  above that are easy to under-specify.
