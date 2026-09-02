# ADR-0031: Drop the Codex adapter; narrow Junie and Antigravity to a single edit assistant

**Status:** Accepted 2026-09-03 (implemented; resolved rather than left indefinite while later ADRs built on it)
**Date:** 2026-08-30
**Owner:** CoDev maintainers
**Related design:** Not applicable

## Context

CoDev gave five agent platforms (OpenCode, Codex, Junie, Antigravity, Claude
Code) an identical 13-role workflow: `orchestrator`/`planner` as human entry
points, `builder`/`reviewer`/`lightweight-reviewer` for the inner loop,
`outer-loop-runner` plus five specialists for the outer loop, and
`code-audit`/`code-audit-gate`. This assumed rough capability parity across
all five harnesses.

First-hand use of CoDev in other projects showed that assumption doesn't
hold. Codex is used rarely and has not been validated against enough real
usage to justify continued maintenance alongside the other four. Junie's and
Antigravity's harnesses are not comparable in maturity or ease of use to
Claude Code and OpenCode — confirmed in the bundle itself: OpenCode enforces
"the builder cannot commit" with an actual per-command permission map
(`bash: {"git commit*": deny, "git push*": deny}`), while Junie's and
Antigravity's equivalent role only states it in prose ("you have no commit
permission") with no structural enforcement behind it. Giving those two
platforms the full orchestrator-driven, multi-agent workflow — which depends
on disciplined subagent dispatch and permission-mode enforcement to hold
guarantees like ADR-0002's git-mutation posture and ADR-0021's specialist
dispatch gate — risks silent guardrail failure rather than a working
process.

## Decision

Drop the Codex adapter entirely: no `.codex/` bundle content, no
`--agent-platform codex`, no adapter/installer/CLI wiring for it.

Narrow Junie and Antigravity from the full 13-role workflow to a single
`assistant` role each (`.junie/agents/assistant.md`,
`.agents/agents/assistant.md`): a bounded, surgical-edit helper invoked
directly by the developer, with or without an existing plan/brief/design
doc. It reuses the existing `build-change` skill (already optional-plan by
design) but is fully decoupled from the task lifecycle — it never calls
`codev task` or `codev git`, and does not commit, push, merge, or open a
pull request; the developer reviews and commits the diff through their own
git workflow. `code-audit`/`code-audit-gate` and the `pr-review` slash
command are dropped for both platforms along with the rest of the role set —
keeping an audit-only second role would undercut the point of a single,
narrow assistant.

`codev adapter verify` continues to check Junie's and Antigravity's
`assistant` role for the same forbidden patterns as every other platform
(unrestricted shell access, raw git mutation, the retired P0–P3 scale) — it
simply requires no task-lifecycle markers, since this role never emits any.

`assistant` bridges into the full workflow by telling the developer how,
never by acting on it: when a finished change is worth OpenCode's or Claude
Code's full review-and-PR lifecycle, it names the exact commands (`codev git
branch`, then `codev task start --entry direct-review` or `--entry
takeover` — the existing human-authored-work entry points from ADR-0006) for
the developer to run themselves. `assistant` never runs them itself; it has
neither the tools nor the task-lifecycle context to do so safely, and giving
it that trigger would just reintroduce the coupling this ADR removes.

This narrows the platform-parity assumptions made by earlier ADRs without
editing them (this directory is append-only): ADR-0001 (every platform has
an `orchestrator`), ADR-0002 (all four platform adapters' `orchestrator`/
`builder` deny raw git mutation), ADR-0016/ADR-0021 (specialist dispatch on
every platform), and ADR-0024 (per-platform `planner`) now describe OpenCode
and Claude Code only. This ADR is the forward pointer for that scope change.

## Alternatives considered

- **Keep Codex but reduce its role set too:** rejected — the problem with
  Codex is usage and validation, not workflow-tier fit; there's no evidence
  it needs a narrower tier the way Junie/Antigravity do. Dropping it
  entirely avoids maintaining a fourth thing nobody exercises.
- **Junie/Antigravity as `builder` + `lightweight-reviewer` pair:** rejected
  in favor of a single unified role — the point of the narrow tier is
  matching what these harnesses reliably do (direct, bounded edits with
  human review), not reproducing a smaller multi-agent loop with the same
  handoff risks at smaller scale.
- **Keep `codev task record` as opportunistic (record evidence when a
  task-id happens to exist):** rejected — it would reintroduce
  task-lifecycle branching into a role explicitly meant to be simple, for a
  workflow (task-tracked delivery) that has no orchestrator left on these
  platforms to drive `codev task start`/`check` in the first place.

## Consequences

- Removing "codex" from `VALID_PLATFORMS` on its own would have stranded
  any existing install that has it: `plan_update`, `plan_remove`, and
  `plan_adapter_remove` all read the lock file's recorded platforms, and
  the strict `normalize_platforms` validator would reject that reading on
  every single one of them, not just an attempt to re-add Codex. Fixed as
  part of this change: `installer._installed_platforms()` reads a lock
  file's recorded platforms as historical fact, never re-validating a name
  the current version no longer recognizes; only an explicitly *requested*
  platform (an `init`/`update --agent-platform` argument, or `adapter
  add`/`verify`'s positional argument) still goes through the strict
  `normalize_platforms` check. `adapter remove`'s CLI argument correspondingly
  dropped its argparse `choices=` restriction — `plan_adapter_remove` now
  allows removing any platform recorded in the lock even if it's no longer
  installable, so `codev adapter remove codex` remains the supported,
  tested migration path off of an existing Codex install.
- `installer.VALID_PLATFORMS` drops to four: `antigravity`, `claude`,
  `junie`, `opencode`. `adapter.ADAPTER_ROLE_PATHS["junie"]` and
  `["antigravity"]` each map to one role (`assistant`) instead of the
  eleven-plus role set every other platform still has.
- A junie/antigravity-only install still receives the complete shared
  `.agents/skills/` tree (only the audit-language subset is filtered by
  platform selection today), even though `assistant` only references
  `build-change`. Left as-is — trimming shared-skill installation by which
  platforms are actually selected is a separate, more invasive change
  (dynamic skill selection from agent frontmatter), not addressed here.
- `build-change`'s two `codev task start --id`/`--description` references
  were softened to branch on whether an orchestrating session actually
  provided a task id, so the skill still works unchanged for OpenCode and
  Claude Code while also serving the new standalone `assistant` role.

## Revisit when

Junie's or Antigravity's harness gains real per-command permission
enforcement (not just prose) and a track record of reliable subagent
dispatch — at that point, re-evaluate whether the full workflow tier is
worth re-extending to either platform. Similarly, revisit dropping Codex if
real adoption and testing against actual usage materialize.
