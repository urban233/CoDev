---
title: CLI reference
description: Every codev command, grouped by what it's for.
---

:::note[You typically never run these yourself]
Your agent runs this CLI on your behalf during a normal session — see
[Talking to Your Agent](/CoDev/working-with-your-agent/). This page is the exact reference
for what they run: useful for scripting, CI, debugging, or understanding the mechanism —
not a list of commands you're expected to type.
:::

Every `codev` command, grouped by what it's for. If you're looking for a narrated
walkthrough instead of a reference table, start with
[the tutorials](https://github.com/urban233/CoDev/blob/main/src/codev_workflow/bundle/docs/codev/tutorials/01-your-first-fix.md)
or the [onboarding guide](https://github.com/urban233/CoDev/blob/main/src/codev_workflow/bundle/docs/codev/onboarding/onboarding-guide.md).

## Install, update, remove the bundle

| Command | Purpose |
|---|---|
| `codev init --target <path> [--agent-platform <platform>] [--programming-language <lang>]` | Install the bundle into a repository |
| `codev diff --target <path>` | Preview what `update` would change, without writing anything |
| `codev update --target <path>` | Apply a previewed update |
| `codev remove --target <path> [--dry-run]` | Remove the installed bundle and integrations |

All four preflight the entire operation first. A locally modified managed file becomes a
visible conflict; CoDev never silently overwrites it.

`--agent-platform` accepts `opencode`, `junie`, `antigravity`, `claude`, or `all` (the
default). OpenCode and Claude Code get the full workflow; Junie and
Antigravity get a single narrower `assistant` agent for bounded, surgical edits — see
[ADR-0031](https://github.com/urban233/CoDev/blob/main/docs/adr/0031-drop-codex-narrow-junie-and-antigravity-to-an-edit-assistant.md)
for why. Pass it more than once, or a comma-separated list, to select several platforms at
once instead of `all`.

`--programming-language` selects which language-specific style-audit skill gets installed:
`python`, `typescript`, `all` (both), or `none` (the language-agnostic audit only, and the
default). An `update` with no `--programming-language` preserves whatever was already
selected, recorded in `.codev/lock.json`.

## Health and status

| Command | Purpose |
|---|---|
| `codev status [--verbose] [--json] [--since <date>]` | Bundle health, installed adapters, open tasks, WIP-per-owner, changed-file overlap, per-task size vs. `review.max_lines`/`review.max_files`, stacked-task depth, and (`--verbose`/`--json`) a `gate_decisions` count of Claude Code guardrail-hook asks by hook and decision |
| `codev adapter list` | Show which platform adapters are installed |
| `codev adapter add <platform>` | Add one adapter to an existing installation |
| `codev adapter remove <platform>` | Remove one adapter (still works for a platform an older CoDev version installed, even after the current version drops it — see ADR-0031's migration note) |
| `codev adapter verify <platform>` | Check one adapter's structural conformance: lifecycle wiring present, no unrestricted shell access, no retired review-scale patterns |

`codev check` and `codev doctor` still work as deprecated aliases for `status` and
`status --verbose` — each prints a warning and will be removed in a future major version.

## Configuration

| Command | Purpose |
|---|---|
| `codev config get <key>` | Read one configuration value |
| `codev config set <key> <value> [--global]` | Write one configuration value |
| `codev config list [--global]` | Show all configuration values |

Configuration is layered: command-line flags override environment variables, which
override project config, which overrides global config, which overrides the built-in
default. `codev config set git.pr_base <branch>` is the one most people need early — it
sets the pull-request base branch once, repository-wide, instead of repeating it on every
task. `git.workflow` defaults to `trunk`; set it to `feature-branch` to let `plan-wave` and
`build-change` split a task at an engineering-dependency boundary instead of only a
usefulness boundary, provided the task states its own containment.

## The task lifecycle

| Command | Purpose |
|---|---|
| `codev task start --id <id> --base <sha> [--entry takeover\|direct-review]` | Open a new task |
| `codev task record ...` | Record one builder or reviewer round (normally automated by your agent, not typed by hand) |
| `codev task check --id <id> --head <sha>` | Ask whether the task may proceed to a pull request |
| `codev task status [--target <path>]` | List tasks in progress |
| `codev task log --id <id>` | Show one task's full round history |
| `codev task close --id <id> --outcome approved\|abandoned\|escalated` | Close a task |
| `codev task triage \| escalate \| escalations \| waive \| reopen \| relink` | Outer-loop and recovery operations — read [ADR-0001](https://github.com/urban233/CoDev/blob/main/docs/adr/0001-work-lifecycle-invariant.md) before scripting against any of these |

This tracks one task's round state as local JSON under `.codev/task/`; it never writes
product source itself.

## Git and GitHub

| Command | Purpose |
|---|---|
| `codev git issue-create ...` | Create a GitHub issue (no task precondition) |
| `codev git issue-view --number <n>` | Print an issue's body and all comments as JSON (read-only, no task precondition) |
| `codev git branch --id <id> [--base <sha> \| --stack-on <task-id>] [--allow-dirty]` | Create the task's own branch; `--base` defaults to `git.pr_base`, then the repository's default branch; `--stack-on` targets another task's own branch instead (ADR-0034, trunk workflow only) |
| `codev git commit --id <id> --message <msg>` | Commit on that task's branch |
| `codev git push --id <id>` | Push that task's branch |
| `codev git open-pr --id <id> --title <title>` | Open the pull request as a draft |
| `codev git mark-ready --id <id>` | Mark the PR ready for human review once the outer loop says so |
| `codev git restack --id <id>` | Rebase a stacked task's branch onto its recorded parent's current head and force-push with `--force-with-lease` (ADR-0034) |

This is the only path for an agent to mutate the repository or GitHub — raw `git
commit`/`git push` are denied to every role for exactly this reason
([ADR-0002](https://github.com/urban233/CoDev/blob/main/docs/adr/0002-inner-loop-self-healing-and-pr-open.md)).

## Skill evaluation

| Command | Purpose |
|---|---|
| `codev eval doctor [--target <path>]` | Zero-cost readiness check before a real trial run |
| `codev eval task create <name> --target <path> --include <path>` | Scaffold a new evaluation task |
| `codev eval task run <name> --target <path> --output <dir>` | Run one task once |
| `codev eval benchmark run <skill> --target <path> --output <dir>` | Run every task tagged with a skill, with and without it, and report the pass-rate delta |
| `codev eval report <output-dir>` | Render a trial's or benchmark's output directory as plain text |
| `codev eval show <skill> [--target <path>]` | Render a skill's packaged eval trace |
| `codev eval nvidia <verb>` | Second, independent engine wrapping the externally installed NVIDIA SkillEvaluator CLI against a skill directory itself |

Bring your own skill or agent, in your own repository, and test it with OpenCode — no
CoDev-hosted execution, no credentials read or stored. `--sandbox docker` opts a task with
its own declared `environment` block into container isolation
([ADR-0027](https://github.com/urban233/CoDev/blob/main/docs/adr/0027-opt-in-docker-sandbox-for-the-native-eval-harness.md));
worktree isolation on the host stays the default.

## Other

| Command | Purpose |
|---|---|
| `codev codeowners init` | Scaffold a starter `.github/CODEOWNERS` — human-run directly, never agent-invoked |
| `codev self version` | Show the installed CoDev version |
| `codev self update` | Show how to upgrade the installed CoDev tool |

## Reviewing an existing GitHub Pull Request

The installed `pr-review` skill reviews an existing GitHub Pull Request and can prepare
validated inline comments for the exact PR head, using the GitHub CLI credential store by
default. See [PR review setup](https://github.com/urban233/CoDev/blob/main/docs/pr-review-github-cli-setup.md)
for installing and authenticating the GitHub CLI (Windows-specific steps included) and the
full fetch/publish command reference.
