# Local OpenCode Skill Evaluation Harness

**Status:** Accepted
**Owner:** CoDev maintainers

## Problem

Teams of one to five developers need repeatable evidence that a repository-local
skill produces a correct change. The existing CoDev evaluator scores manually
observed workflow scenarios; it does not create an isolated repository, run an
OpenCode attempt, or execute a project verifier.

## Outcome

A developer can create a small, reviewable fixture and explicitly evaluate one
installed skill locally. The evaluation uses the developer's existing OpenCode
authentication, keeps the active repository untouched, and records objective
verifier evidence plus an independent qualitative review.

## First-release scope

- Version-controlled fixture directories under `.codev/fixtures/<name>/`.
- A fixture creator that copies only explicitly selected repository paths into a
  fixture starter.
- Local, temporary Git repository and detached-worktree isolation for every
  evaluation.
- One OpenCode actor run, one deterministic verifier command, and one separate
  OpenCode judge run when the verifier passes.
- A structured result written only to an explicit caller-provided output path.
- Cleanup after success, failure, timeout, or interruption.

## Non-goals

- CI or hosted execution.
- API-key, model, or provider configuration.
- Full-repository snapshots, containers, databases, or general MCP injection.
- Automatic mutation of a project's OpenCode configuration.
- Judge access to private reasoning or authority to override a failed verifier.

## Evidence of value

- A fixture committed by one developer can be rerun by another compatible local
  checkout and produce inspectable, structured evidence.
- Source files and Git state in the active repository are unchanged by `codev
  eval`.
- A deterministic failure produces a failing result and prevents a judge pass.
- The judge scores only the fixture rubric and observable run artifacts.

## Constraints

- Reuse existing OpenCode subscriber authentication; never read, print, or
  persist credentials.
- Preserve project-owned provider and model selection.
- V1 is macOS-verified. Windows and Linux compatibility, including cleanup
  behavior, is deferred risk rather than a V1 acceptance requirement.
- Keep target repositories free of CoDev runtime dependencies.
- All execution remains an explicit `codev` command.
