# Normal Development Workflow

The command checklist for a normal bug fix, small feature, or planned task, once you
already know the shape from [Tutorial 1](../tutorials/01-your-first-fix.md) or the
[onboarding guide](onboarding-guide.md). This page assumes you know *why* each command
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

- [Tutorial 1: your first fix](../tutorials/01-your-first-fix.md) — the narrated version
  of the checklist above, with real output at every step.
- `docs/cli-reference.md` in the CoDev project's own repository — every command, not just
  the ones in a normal task.
- [starting-prompts.md](starting-prompts.md) — copy-paste prompts for the two moments
  above that are easy to under-specify.
