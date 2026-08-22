# ADR-0020: Mechanical GitHub-issue linkage gate and `codev work relink`

**Status:** Accepted
**Date:** 2026-08-14

## Context

ADR-0004 built the full issue-linkage feature: `codev git issue-create`,
`codev work start --github-issue N` resolving `link_ref`/`summary` from it,
and `codev git open-pr`'s automatic `Closes #N`. 0.2.2 wired it into
`orchestrator` and `plan-delivery`'s Handoff so a normal delivery-plan-driven
session passes `--github-issue` through correctly once an issue already
exists.

A real session (CLIP, work item L-03) exposed the gap that wiring alone
doesn't close: the human started the item directly ("take the next work item
... create a branch and an implementation plan"), never routing through
`plan-delivery`'s Handoff in that conversation. `orchestrator` reached
`codev work start` with no issue linked, and nothing at the CLI layer
noticed — `--github-issue` is optional, so `work start` succeeded silently
with `link_ref` unset. The human caught it only after the fact ("Hold on,
you have to first create a GitHub issue for that work item") — by which
point `codev work start` had already run. `link_ref` is write-once
(ADR-0004's `--github-issue N` resolution only happens inside `start()`),
so the only available "fix" was noting the issue link in the implementation
plan's own prose. `link_ref` in `round-state.json` stayed a local file path
for the rest of the item's life, and `_closes_issue_number()` never matched
it — the eventual PR shipped with no `Closes #N`, silently, with no error or
warning anywhere in the trail.

Two distinct problems, one root cause: nothing makes a missing issue
linkage *visible* at the moment it's still cheap to fix (`work start` time),
and nothing lets a human *correct* it once it's already been missed.

## Decision

### 1. `codev work start` refuses an unresolved issue linkage, for a
GitHub-backed repository

When neither `--github-issue`, `--link`, nor a new `--no-github-issue`
acknowledgment flag is given, and the repository resolves to a real GitHub
remote (`git_ops.has_github_remote()`, a new best-effort, never-raising
check modeled directly on `detect_identity()` — `gh repo view` succeeding or
not, swallowing failure the same way, so a repository with no `gh` install
or no GitHub remote is never blocked by this), `codev work start` raises
before writing any state, naming the three ways to proceed: `--github-issue
N`, `--link`, or `--no-github-issue` for a repository that intentionally
doesn't track issues on GitHub for this item. This is the same "refuse
until resolved, rather than silently proceed" shape `codev diff`/`codev
update` already use for install conflicts, applied for the first time to a
workflow decision instead of an installation one.

### 2. `codev work relink` — recovery once `start()` already ran

Modeled directly on `waive()`'s shape, not `record_triage`'s: a human
routinely discovers the missing linkage only after round-state exists (as
in the real session above), so the correction has to be possible *after*
`start()`, and — per this project's "never silently overwrite" discipline —
has to leave a durable trace rather than quietly replacing history.
`relink(work_item_id, link_ref, *, target, by=None)` validates `link_ref`
non-empty, requires the item still be `in_progress`, sets `state["link_ref"]`
to the new value, and appends `{timestamp, previous, new, by}` to a new
additive `link_ref_updates` list — same no-schema-bump precedent as
`coverage_waivers`/`reopens`. `codev work log` renders each correction
(`relinked by <who>: <previous> -> <new>`) alongside the top-level `link:`
line, which already reflects whatever `link_ref` currently is. Exposed as
`codev work relink --id <id> [--github-issue N | --link <ref>] [--by
<name>]`, reusing the exact `git_ops.fetch_issue` resolution `work start
--github-issue` already uses.

No other code path needs to change: `git_ops.open_pr()` and `mark_ready()`
both already read `link_ref` fresh through `work.describe()` on every call
(the latter as of the companion fix restoring `Closes #N` to `mark_ready`,
landed alongside this ADR), so a `relink` immediately makes the *next*
`open-pr`/`mark-ready` invocation pick up the corrected value.

### 3. `orchestrator` is instructed to create the issue itself when one is
missing, not only pass one through

Covered as part of ADR-0022 (workflow-instruction hardening) rather than
here — this ADR is the CLI/schema surface; ADR-0022 closes the prompt-level
routing gap that let a direct-build session skip `plan-delivery`'s Handoff
in the first place.

## Consequences

- No `ROUND_SCHEMA_VERSION` bump: `link_ref_updates` is additive and
  optional, same precedent as every field added since ADR-0004.
- A repository with no GitHub remote, or with `gh` unavailable, is never
  blocked by the new `work start` gate — `has_github_remote()` fails open
  (returns `False`) on any error, matching `detect_identity()`'s existing
  restraint against a hard GitHub dependency.
- `--no-github-issue` is a one-time acknowledgment at `start()` time, not a
  persisted preference — a repository that never tracks issues on GitHub
  will need it on every `work start` call. A project-level config default
  (mirroring `git.pr_base`, ADR-0013) would remove that repetition; not
  designed here, flagged as a natural follow-up if it proves annoying in
  practice.
- Testing needs (added): `tests/test_work.py::RelinkTests` — empty-`link_ref`
  rejection, rejection when not `in_progress`, round-trip through
  `describe()`, a later `relink` overriding an earlier one, `log_text`
  rendering the correction without losing the prior value.
  `tests/test_git_ops.py::HasGithubRemoteTests` — true/false on `gh`
  success/failure. `tests/test_cli.py` — `work start` refusal when linkage
  is unresolved and the repo has GitHub, `--no-github-issue` and `--link`
  both bypassing the gate, the gate never firing when the repo has no
  GitHub remote, and the `relink` subcommand's `--github-issue` sugar
  resolution end to end.
