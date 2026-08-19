# ADR-0023: "Work item" is renamed to "task"

**Status:** Accepted
**Date:** 2026-08-19

## Context

"Work item" was CoDev's name, from the first design, for the unit `codev
work` tracks round-state for: the `work_item_id` schema field, the `codev
work start/check/record/...` CLI group, the `.codev/work/` state directory,
and the term used throughout every skill, agent, and doc. It is grant/
work-breakdown-structure vocabulary, not the word an engineer reaches for —
"task" is both the plainer term and the type name GitHub's own Issues UI and
Google's issue tracker use for exactly this concept. A companion review of
external design-doc conventions surfaced this directly: keeping one concept
under one name, consistently, across every document a project produces is a
discipline worth having, and "work item" was the one place CoDev's own
vocabulary didn't already follow it.

The rename touches more than prose. `work_item_id` is a persisted key in
`round-state.json`, `.codev/work/` is an on-disk path, and `codev work ...`
is public CLI surface — none of these are cosmetic.

## Decision

### Hard break, no migration — following ADR-0003's precedent exactly

ADR-0003 already faced this question once, bumping `ROUND_SCHEMA_VERSION`
from 1 to 2 for a field rename, and chose not to build a migration: "v1
round-state files use the old combined key and are rejected by `_load`'s
version guard below -- no migration, consistent with this project's pre-1.0
breaking-change policy." This ADR follows the same precedent rather than
introducing a new one. `ROUND_SCHEMA_VERSION` moves from 2 to 3;
`_load()`'s existing version-equality gate rejects a schema-2 file outright,
with no dual-read fallback. A task mid-flight at upgrade time must finish or
restart under the previous CoDev version — the same cost ADR-0003 already
accepted once.

### What actually renames

- `src/codev_workflow/work.py` -> `src/codev_workflow/task.py`. `WorkError`
  -> `TaskError`; `work_item_id` -> `task_id` (function parameters, the
  persisted JSON key, every f-string); `WORK_DIR_RELATIVE` ->
  `TASK_DIR_RELATIVE`, value `.codev/work` -> `.codev/task`.
- The CLI subcommand group: `codev work start/record/check/close/reopen/
  waive/relink/status/log/triage/escalate/escalations` becomes `codev task
  ...`. Every `--id`/other flag is unaffected — `--id` was already generic.
- `codev status --json`'s `work_items_in_progress` and
  `work_items_in_progress_by_owner` fields become `tasks_in_progress` and
  `tasks_in_progress_by_owner`; the changed-file-overlap payload's
  `work_items` key becomes `tasks`.
- `git_ops.py`'s `work_item_id` parameters and its `work.` module reference
  (now `task.`) rename to match; `branch_name_for()`'s `codev/{id}` branch
  naming scheme is deliberately **not** touched — it is a git convention,
  not "work item" terminology, and churning it costs existing branches for
  no benefit.
- The `docs/codev/work/<id>/implementation-plan.md` planning-artifact
  convention (`build-change`, `lightweight-reviewer`) becomes
  `docs/codev/task/<id>/implementation-plan.md`.
- All four platform adapters (`orchestrator`, `builder`, `reviewer`,
  `lightweight-reviewer`, `outer-loop-runner`), `adapter.py`'s
  `_REQUIRED_MARKERS`, and every skill/doc referencing the old commands or
  terminology (`plan-delivery`, `specify-project`, `review-change`,
  `build-change`, `critique-review`, `pr-review`, `README.md`,
  `docs/product-map.md`, `ai-agent-guidelines.md`, the onboarding guides)
  are updated together, in the same change, so no platform or document is
  left speaking the old vocabulary.

### What deliberately does not rename

- `implementation-plan.template.md` (`build-change`'s asset) is explicitly
  excluded from this pass, at the user's direction — its structure is
  intentionally out of scope for the whole planning-template review this
  rename originated from, and that carve-out extends to its own "work item"
  wording rather than leaving it half-updated by accident.
- ADRs 0001-0022 are append-only history and are not edited. Where they
  name `work_item_id`, `codev work start`, or `.codev/work/`, that is an
  accurate record of what those commands were called at the time.
- `real-use-cases/` session transcripts document what actually happened
  under the old naming and are left as historical record, same reasoning.
- Fixture strings that happen to contain the substring `work` only as
  arbitrary example content (e.g. a test's placeholder `link_ref` path)
  are left alone; they are opaque data, not the renamed concept.

## Consequences

- Breaking for any repository with CoDev already installed: after
  upgrading, a `.codev/work/` directory from a previous install is invisible
  to the renamed CLI (it looks under `.codev/task/` now), and any task whose
  `round-state.json` still carries `round_schema_version: 2` is rejected by
  the version guard with a clear error naming the mismatch, not silently
  misread.
- `docs/product-map.md`'s former non-goal ("does not change `codev work`'s
  round-state schema... beyond ADR-0006's additive `entry` field") no longer
  holds as stated and is corrected in the same change to name this ADR
  instead of contradicting it.
- Root dogfood copies of the agent files (`.codex/agents/`,
  `.opencode/agents/`, etc.) are installed *from* the bundle by `codev
  update`, not maintained by hand in parallel — landing this ADR's bundle
  changes requires running `codev update` against this repository
  afterward, the same as any other bundle change, or the root copies stay
  on the old vocabulary until the next sync.
- Testing: `tests/test_work.py` -> `tests/test_task.py` (all 136 tests,
  identifiers updated in place); `tests/test_cli.py`, `tests/test_git_ops.py`,
  `tests/test_adapter.py`, and `tests/test_installer.py` updated for the
  renamed commands, payload keys, and gitignore path. `tests/test_adapter.py`
  additionally re-verifies bundle parity across all four platforms against
  the renamed required markers.
