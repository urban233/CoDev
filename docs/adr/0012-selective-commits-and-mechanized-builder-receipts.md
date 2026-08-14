# ADR-0012: Selective commits and mechanized builder receipts

**Status:** Accepted
**Date:** 2026-08-13

## Context

A real session using `codev git commit` hit two related problems, both
traced to `git_ops.commit()`'s implementation rather than a workflow
misuse.

First, `commit()` always ran `git add -A`. In a worktree with concurrent,
unrelated dirty changes -- most commonly CoDev's own workflow files
(`.codev/`, `.agents/`, `.opencode/`, and similar, edited in the same
session for an unrelated reason) sitting alongside product changes -- there
was no way to commit only the product change. Every commit swept up
whatever else happened to be dirty, forcing a human to either separate the
changes by hand outside `codev git` entirely (defeating the point of the
guarded surface) or accept unrelated workflow edits riding into a product
PR unremarked.

Second, `orchestrator`'s documented protocol (ADR-0007) already establishes
the correct order -- commit first, then record the builder's round against
the commit's actual resulting head, because the builder itself never has
commit permission and cannot know that head in advance. But the tool only
half-supports this: `commit()` returns the resulting head, and the caller
is still responsible for remembering it and making a second, separate
`codev work record --role builder` call with it. In practice this is
exactly the repair step the ADR-0007 session had to perform by hand
whenever the second call was forgotten or used a stale head.

## Decision

`git_ops.commit()` gains four new, backward-compatible parameters:

- `paths: list[str] | None` -- stage and commit only these paths
  (`git add -- <paths>`) instead of everything dirty.
- `staged: bool` -- commit exactly what is already staged; skip `git add`
  entirely. Mutually exclusive with `paths`.
- `round_number: int | None` / `evidence: Any` -- optional pair, must be
  given together. When present, after the commit succeeds, `commit()`
  itself calls `work.record_builder(work_item_id, round_number,
  <the resulting head>, evidence, target=target)` -- one call both commits
  and records the receipt against the guaranteed-correct head, closing the
  gap ADR-0007 left open. Left unset for any commit that is not a builder
  round (for example a plain cleanup commit) so no receipt is fabricated
  for something that isn't one.

When none of `paths`/`staged` is given -- the default, and the only path
every existing caller and test already exercises -- `commit()` now first
inspects `git status --porcelain -uall` (`-uall` so files inside an
otherwise-untracked directory are listed individually, not collapsed into
one directory entry) and classifies each dirty path against
`.codev/lock.json`'s own recorded `files` map, the authoritative list of
every path this CoDev install manages -- reused as-is rather than
duplicated as a hardcoded prefix list, so it self-maintains as the bundle
grows. If the dirty set contains both CoDev-managed and non-managed paths,
`commit()` refuses with a `GitOpsError` naming both groups and pointing at
`--paths`/`--staged`. If the lock file is missing or unreadable, or the
dirty set is homogeneous (all one category, or -- the common case -- no
CoDev-managed paths dirty at all), behavior is unchanged: `git add -A` then
commit.

`cli.py`'s `git commit` subcommand exposes all four as `--paths` (nargs
`+`), `--staged` (flag, in a mutually exclusive group with `--paths`),
`--round`, and `--evidence` (a JSON evidence file, loaded the same way
`work record --role builder`'s own `--evidence` already is).

## Consequences

- No `ROUND_SCHEMA_VERSION` bump: `record_builder`'s own contract is
  unchanged, `commit()` just calls it internally under the same
  conditions an external caller already could.
- The mixed-path guard is a defensive default, not a hard requirement --
  every existing caller (real orchestrator sessions and the existing test
  suite) that never mixes CoDev-managed and product changes in one dirty
  worktree sees no behavior change at all.
- `orchestrator`'s documented protocol (all four platforms) can now commit
  and record a builder round in one `codev git commit --round <n>
  --evidence <file>` call instead of two, removing the exact manual-repair
  step ADR-0007's session needed. Updating that prose is left to whichever
  session next touches those files for another reason, to keep this change
  scoped to the tool surface.
- Testing needs (added, `tests/test_git_ops.py::BranchAndCommitTests`):
  `--paths` and `--staged` mutually exclusive; `--round` without
  `--evidence` (and vice versa) rejected; `--paths` commits only the named
  files and leaves the rest dirty; `--staged` commits only the index;
  `--round`+`--evidence` records a builder receipt against the true
  resulting head (verified via `codev work check` returning
  `ok_waiting_on_reviewer` rather than `stop_drift`); the default refuses a
  worktree mixing a `.codev/lock.json`-managed path with a non-managed one
  and allows a homogeneous one; an explicit `--paths` still succeeds on a
  mixed worktree.
