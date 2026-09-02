# CLI reference

Every `codev` command, grouped by what it's for. If you're looking for a narrated
walkthrough instead of a reference table, start with
[the tutorials](https://urban233.github.io/CoDev/tutorials/your-first-fix/) or the
[onboarding guide](https://urban233.github.io/CoDev/onboarding-guide/).

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
default). OpenCode and Claude Code get the full orchestrator-driven workflow; Junie and
Antigravity get a single narrower `assistant` agent for bounded, surgical edits — see
[ADR-0031](adr/0031-drop-codex-narrow-junie-and-antigravity-to-an-edit-assistant.md) for
why. Pass it more than once, or a comma-separated list, to select several platforms at
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
task. `git.workflow` defaults to `trunk`, letting a task split at an engineering-dependency
boundary when it stays safely contained; set `codev config set git.workflow feature-branch`
to opt out and require every task to stand alone instead.

## The task lifecycle

| Command | Purpose |
|---|---|
| `codev task start --id <id> --base <sha> [--entry takeover\|direct-review]` | Open a new task |
| `codev task record ...` | Record one builder or reviewer round (normally done by the orchestrator, not typed by hand) |
| `codev task check --id <id> --head <sha>` | Ask whether the task may proceed to a pull request |
| `codev task status [--target <path>]` | List tasks in progress |
| `codev task log --id <id>` | Show one task's full round history |
| `codev task close --id <id> --outcome approved\|abandoned\|escalated` | Close a task |
| `codev task triage \| escalate \| escalations \| waive \| reopen \| relink` | Outer-loop and recovery operations — read [ADR-0001](adr/0001-work-lifecycle-invariant.md) before scripting against any of these |

This tracks one task's round state as local JSON under `.codev/task/`; it never writes
product source itself. See [Tutorial 1](https://urban233.github.io/CoDev/tutorials/your-first-fix/)
for what using this actually looks like end to end.

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
([ADR-0002](adr/0002-inner-loop-self-healing-and-pr-open.md)).

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
CoDev-hosted execution, no credentials read or stored. New to this? See
[`docs/features/skill-eval/how-to-write-a-task.md`](features/skill-eval/how-to-write-a-task.md)
for a start-to-finish walkthrough, or
[`docs/features/nvidia-skill-evaluator/README.md`](features/nvidia-skill-evaluator/README.md)
for the second engine. `--sandbox docker` opts a task with its own declared `environment`
block into container isolation
([ADR-0027](adr/0027-opt-in-docker-sandbox-for-the-native-eval-harness.md)); worktree
isolation on the host stays the default.

## Slice lifecycle

The verbs an agent reaches for by default. Each replaces a role-file step that
used to issue several commands with conditional flags between them; the
granular `codev git` and `codev task` verbs they compose all still exist, for
recovery and for a mid-session agent that needs one step on its own.

| Command | Purpose |
|---|---|
| `codev slice begin --id <id> --base <sha> [--title <t> --body-file <f>] [--github-issue <N>] [--slice <name>]... [--json]` | Branch, GitHub issue, and round state in one call. Replaces `codev git branch` + an issue-existence check + `codev git issue-create` + `codev task start` with three mutually exclusive linkage flags, plus the `codev task relink` recovery path when the issue arrived late |
| `codev round close --id <id> --role builder --evidence <file> [--message <t>] [--json]` | Commit the work and record the round against the exact resulting head. The round number is derived from state, not passed. Named for its caller: only whoever holds commit permission can know that head, which is why a builder never records its own round |
| `codev slice publish --id <id> --title <t> [--json]` | Push the branch and open the slice's draft pull request. The body is always the task's rendered evidence, so the old "never pass `--body`" caveat has no way to be violated |
| `codev slice land --id <id> [--outcome <o>] [--json]` | Advance to the next slice, or close the task when this was the last. Which one applies is a fact about the slice list, not a decision for the caller |

## Other

| Command | Purpose |
|---|---|
| `codev next [--id <id>] [--no-github] [--json]` | Where the work stands and the one thing to do next (ADR-0036). An agent consults this at every phase boundary; a developer does not have to run it. It answers for the planning phases as well as the build ones, and a blocked position carries an `options` list -- each with a label, a command, and what choosing it means -- so a stop is a decision rather than a dead end |
| `codev task advance-slice --id <id> --head <sha>` | Move a task on to its next slice and open a fresh round (ADR-0035) |
| `codev gate check --gate <name>` | Decide one guardrail for a tool-use payload read from stdin (ADR-0036). Every platform's hook calls this, so the rules are CoDev's, not one adapter's |
| `codev task style --id <id> [--set pair\|delegate]` | Read or change a slice's work style (ADR-0038) |
| `codev task pause --id <id> --head <sha> --reason <text>` | Record a human interruption of the current slice |
| `codev task resume --id <id> --head <sha> --reason <text>` | Re-enter a paused slice in pair style; raises the round cap so pausing costs no budget |
| `codev task waive-review --id <id> --reason <text>` | Record that this task lands without an independent human approval (ADR-0037). Human-authorized, never an agent's initiative |
| `codev codeowners init` | Scaffold a starter `.github/CODEOWNERS`; refuses if one already exists |
| `codev self version` | Show the installed CoDev version |
| `codev self update` | Show how to upgrade the installed CoDev tool |

## Reviewing an existing GitHub Pull Request

The installed `pr-review` skill reviews an existing GitHub Pull Request and can prepare
validated inline comments for the exact PR head, using the GitHub CLI credential store by
default. See [PR review setup](pr-review-github-cli-setup.md) for installing and
authenticating the GitHub CLI (Windows-specific steps included) and the full fetch/publish
command reference.
