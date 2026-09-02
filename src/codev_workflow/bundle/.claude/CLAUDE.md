# CoDev workflow (Claude Code)

This repository is managed by CoDev. Claude Code reads `AGENTS.md` natively,
the same as this file -- the workflow contract, invariants, and lifecycle
commands live there and in `.codev/for-ai/ai-agent-guidelines.md`, both
referenced from every role subagent below. This file only adds what's
specific to running that workflow through Claude Code.

## Role subagents

`.claude/agents/` holds the same role set every other CoDev-supported
platform gets: `orchestrator` and `planner` as the two human-facing entry
points, `builder`/`reviewer`/`lightweight-reviewer` for the inner loop,
`outer-loop-runner` plus five specialist reviewers for the outer loop, and
`code-audit`/`code-audit-gate` for style. Start with `orchestrator` for
build work and `planner` for anything upstream of a ready task (Specify,
Understand, Design, Plan) -- they are separate, human-started entry points
by design; do not chain from one into the other yourself.

## Skills and commands

`.claude/skills/` mirrors this repository's shared skills. `/pr-review` is
available as a slash command.

## Plan-first guardrail

This project starts new sessions in Plan Mode (`.claude/settings.json`) and
a `PreToolUse` hook pauses for confirmation before the first source edit, or
the first repository-mutating git command -- raw (`git commit`, `git push`,
`git merge`, `git reset`, `git checkout`, `git clean`, `git rebase`) or
through the guarded surface (`codev git branch`, `codev git commit`,
`codev git push`) -- if no design or plan document exists yet for the
active branch -- checked both precisely, against the current task's own
recorded plan when the branch follows `codev git branch`'s naming, and as a
coarser repo-wide fallback for planning work that predates a task. Both
exist to keep implementation
behind an explicit discussion or an accepted plan -- propose a plan before
editing rather than starting directly, even when the guardrail doesn't
catch it. See `docs/features/claude-code/design.md` for why, and its
"Guardrail Design" section if the hook's check needs adjusting.
