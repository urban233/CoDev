---
title: Architecture
description: How the CoDev bundle is built, installed, and updated.
---

## Purpose

CoDev separates workflow maintenance from workflow use. The canonical bundle lives in the
CoDev repository; agents consume ordinary, repository-local files in each software
project. CoDev's install, update, and remove machinery never runs while product code is
being built. The `codev task` lifecycle commands are the one exception: they may run
during a build session, are strictly read-only with respect to product source, and only
read or write their own state under `.codev/task/` (see
[ADR-0001](https://github.com/urban233/CoDev/blob/main/docs/adr/0001-work-lifecycle-invariant.md)
and [ADR-0023](https://github.com/urban233/CoDev/blob/main/docs/adr/0023-work-item-renamed-to-task.md)).

```text
CoDev source -> versioned Python package -> explicit CLI command -> target repo
       |                                                    |
       +---- tests and behavioral evaluations               +---- local agent discovery
```

## Components

### Bundle

`src/codev_workflow/bundle` mirrors target-relative paths. It contains the skills, and the
OpenCode, Junie, Antigravity, and Claude Code agents, documentation, validators, and
evaluation catalog. Junie and Antigravity carry a single narrow-tier `assistant` agent
rather than the full workflow (ADR-0031); OpenCode and Claude Code carry the complete role
set.

Every bundled skill carries a `skill-card.md` alongside its `SKILL.md` — owner, license,
use case, dependencies, and known risks — and a `license` frontmatter field on `SKILL.md`
itself.

`AGENTS.md` and `.opencode/opencode.json` are integrations rather than copied files. CoDev
owns one marked block in `AGENTS.md` and selected missing values in OpenCode
configuration, preserving all project-owned content. Junie's `assistant` agent is an
ordinary managed Markdown file under `.junie/agents/`, while Antigravity's uses its
official `.agents/agents/` location alongside CoDev's `.agents/skills/` directory. Claude
Code agents use its official `.claude/agents/` location; unlike Antigravity, Claude Code
has no configurable skills path, so the shared skills are mirrored into `.claude/skills/`
at install time instead of referenced in place. Claude Code additionally ships a
`.claude/settings.json` and two guardrail hooks — a category no other adapter has:
`require_plan.py` defaults new sessions into Plan Mode and pauses for confirmation before
the first source edit, or the first repository-mutating git command, when no design or
plan document exists yet for the active branch; `require_wave_shape.py` asks (never
denies) when a wave plan's "Later waves" section already holds a populated task table,
enforcing rolling-wave planning's detail-only-the-current-wave rule. Both fail open on any
internal error and log their decisions to a local, gitignored gate-decision log.

### Installer

The standard-library CLI performs a complete preflight before mutation. It computes
SHA-256 hashes over bundled bytes and records them in `.codev/lock.json`. Files are
written atomically in their destination directories.

### Lock file

The lock file records schema version, bundle version, selected platforms, source hashes,
and integration state. It is committed to the consumer repository so CI and other
developers observe the same installation.

## Update algorithm

For each managed file, CoDev compares:

1. the source hash recorded at the last successful install;
2. the current target file; and
3. the source file in the running CoDev version.

| State | Action |
|---|---|
| Target matches old source; source changed | Update |
| Target matches new source | Adopt as current |
| Target and source both match old source | Keep |
| Target differs; upstream is unchanged | Report local drift |
| Target differs and upstream changed | Conflict; write nothing |
| New upstream file is absent locally | Add |
| New upstream file collides locally | Conflict; write nothing |
| Upstream removed an old file | Retain locally and stop managing it |

Retaining removed files is conservative: an update cannot unexpectedly delete repository
instructions. The explicit `codev remove` command preflights and removes only unchanged
managed files and integrations; it remains opt-in.

A conflict left unresolved (`--on-conflict skip`, the conflict wizard's `skip`, or simply
no resolution supplied for that path) stays a visible conflict: `codev status` keeps
reporting it as a managed file with local changes until a real resolution (`override` or
`keep`) supersedes it, rather than the file quietly falling out of management the moment
an update chooses not to touch it. `delete` is the one exception — it adopts upstream's
removal, so nothing is left to compare a future hash against, and the path stops being
tracked the same way an ordinary upstream removal does.

## Invariants

- Every multi-file change is atomic at the decision level: conflicts prevent all planned
  writes.
- A target repository never imports CoDev as a runtime dependency.
- Provider and model selection remain project-owned.
- Installed instruction changes are reviewable source changes.
- Deterministic checks run without network access or model calls.
- Behavioral model evaluations remain externally observed and separately run.
- `codev task` lifecycle commands are read-only with respect to product source; they only
  mutate their own state under `.codev/task/` (see
  [ADR-0001](https://github.com/urban233/CoDev/blob/main/docs/adr/0001-work-lifecycle-invariant.md)
  and [ADR-0023](https://github.com/urban233/CoDev/blob/main/docs/adr/0023-work-item-renamed-to-task.md)).

## Compatibility

Lock schema changes require a migration before managed files are touched. Bundle behavior
follows semantic versioning. Patch releases preserve artifact contracts; minor releases
may add compatible files or behaviors; major releases may require an explicit migration
and review.

## Full decision history

Durable, cross-cutting decisions are recorded as append-only Architecture Decision
Records in the repository:
[docs/adr/](https://github.com/urban233/CoDev/tree/main/docs/adr).
