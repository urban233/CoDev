# CoDev workflow (Claude Code)

This repository is managed by CoDev. Claude Code reads `AGENTS.md` natively,
the same as this file -- the workflow contract, invariants, and lifecycle
commands live there and in `.codev/for-ai/ai-agent-guidelines.md`, both
referenced from every role subagent below. This file only adds what's
specific to running that workflow through Claude Code.

## Role subagents, and what is not one

There is no agent to start or select (ADR-0044): coordination is what
`.codev/for-ai/ai-agent-guidelines.md` already says to every ordinary
session, not a named identity a developer dispatches into. `.claude/agents/`
holds only the roles whose isolation is the actual point --
`builder`/`reviewer`/`lightweight-reviewer` for the inner loop, five
specialist reviewers for the outer loop, and `code-audit`/`code-audit-gate`
for style. Load the `outer-loop-review` skill once a pull request is open;
it holds the outer loop's full protocol.

There is no second session to switch to. A session boundary a developer has
to notice is a command by another name, whether that boundary is a separate
agent or a separate skill they have to remember to load themselves -- start
from `AGENTS.md` and this file, and the guidance obligation carries the rest.

## Skills and commands

`.claude/skills/` mirrors this repository's shared skills. `/pr-review` is
available as a slash command.

## Plan-first guardrail

This project starts new sessions in Plan Mode (`.claude/settings.json`) and
a `PreToolUse` hook pauses for confirmation before the first source edit, or
the first repository-mutating git command -- raw (`git commit`, `git push`,
`git merge`, `git reset`, `git checkout`, `git clean`, `git rebase`) or
through the guarded surface (`codev git branch`, `codev git commit`,
`codev git push`, `codev git restack`) -- if no design or plan document
exists yet for the active branch -- checked both precisely, against the
current task's own recorded plan when the branch follows `codev git
branch`'s naming, and as a coarser repo-wide fallback for planning work
that predates a task. Both exist to keep implementation behind an explicit
discussion or an accepted plan -- propose a plan before
editing rather than starting directly, even when the guardrail doesn't
catch it. See `docs/features/claude-code/design.md` for why, and its
"Guardrail Design" section if the hook's check needs adjusting.
