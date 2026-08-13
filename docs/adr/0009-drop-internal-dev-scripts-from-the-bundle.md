# ADR-0009: Stop shipping this repository's own workflow-validation tooling to target repositories

**Status:** Accepted
**Date:** 2026-08-12

## Context

A target repository deleted `scripts/evaluate-development-workflow.py` and
`scripts/validate-development-workflow.py` by hand. `codev update` correctly
reported both as `CONFLICT — managed file is missing or not a file` and (by
design, ADR unrelated to this one) refused to write anything at all until
every conflict was resolved — blocking unrelated fixes the same update would
otherwise have applied. Looking at what these two files actually do settled
whether that conflict was protecting something a target repository needs, or
just cost real time for no reason:

- `validate-development-workflow.py`'s `EXPECTED_SKILLS`/`EXPECTED_GUIDES`
  are hardcoded to this repository's own bundle shape: skill frontmatter
  conventions, `agents/openai.yaml` UI fields, a 500-line skill budget, and a
  check that specific guide files reference every one of *this project's*
  bundled skill names. It is never invoked by anything a target repository's
  agent is instructed to run — its only caller anywhere in the codebase is
  `scripts/verify_release.py`, and only against `src/codev_workflow/bundle`,
  this repository's own pre-packaging source tree.
- `evaluate-development-workflow.py` is more generic (a JSON-catalog scorer,
  not hardcoded to specific skill names), but the catalog it operates on,
  `evals/development-workflow/scenarios.json`, is not: every scenario tests
  routing among *this project's own* bundled skills, illustrated with
  bio/cheminformatics examples specific to validating CoDev's own skill
  catalog. It was referenced by exactly one place a target repository would
  ever see, `ai-agent-guidelines.md`'s "Evaluate workflow changes" section —
  telling a target repository's agent to score its own `AGENTS.md`/skill
  edits against a catalog that tests *this project's* routing decisions, not
  anything about the target repository's own change. The proper mechanism
  for a target repository to evaluate its *own* skills already exists and is
  unrelated: `codev eval`/`design-skill-eval`, fixture-based, scoped to
  `.codev/fixtures/`.

Neither file is part of the day-to-day inner/outer loop, `codev eval`, or
anything else a target repository's engineering team would run. They are
this repository's own release-readiness gate, reproduced — by accident of
living inside `src/codev_workflow/bundle/`, the directory `_walk_bundle()`
(`installer.py`) treats as "everything that ships" — inside every repository
that installs CoDev, whether or not anyone there ever runs `python -m
build`.

Separately, this repository's own top-level `scripts/evaluate-development-
workflow.py`, `scripts/validate-development-workflow.py`, and
`evals/development-workflow/scenarios.json` already existed *outside* the
bundle, tracked in git independently of the bundle copies, and had already
drifted stale relative to them (missing docstrings, referencing the retired
`clean-code-review` skill and the pre-relocation `docs/for-ai/`/`docs/for-
human/` paths) — the same class of duplicate-source-of-truth drift this
session's other fixes kept finding, just not yet noticed here.

## Decision

`evaluate-development-workflow.py`, `validate-development-workflow.py`, and
`evals/development-workflow/scenarios.json` move out of
`src/codev_workflow/bundle/` entirely, to the top-level `scripts/` and
`evals/` directories that already held stale duplicates of them — refreshed
to the bundle copies' current content in the same move, since the bundle
copies were the actively maintained ones. `[tool.setuptools.package-data]`'s
now-pointless `bundle/scripts/*.py` and
`bundle/evals/development-workflow/*.json` entries are removed.
`scripts/verify_release.py` invokes both from their new top-level location.

`validate-development-workflow.py`'s `EVALUATION_SCRIPT`/
`EVALUATION_CATALOG` constants now resolve relative to its own file location
(`Path(__file__).resolve().parent.parent`), not relative to the `--repo`
argument it validates — the evaluator and its catalog are this script's own
sibling tooling, never part of whatever bundle `--repo` points at.
`evaluate-development-workflow.py` needed no code change: its existing
`--repo` default (`Path(__file__).resolve().parents[1]`) already resolves to
the correct root once the file itself lives at `<repo>/scripts/...` instead
of `<bundle>/scripts/...`.

`ai-agent-guidelines.md`'s "Evaluate workflow changes" section is removed —
dead instruction in a target repository with nothing left to run. The
equivalent guidance for this repository's own contributors moves to
`CONTRIBUTING.md`, naming the exact commands.

## Consequences

- `codev init`/`codev update` no longer install these three files into any
  target repository; `_walk_bundle()` no longer finds them (verified: not
  present in its output after the move).
- The exact conflict that started this ADR — a target repository that
  deleted these files locally — resolves the next time that repository runs
  `codev update`: the paths are no longer in the new bundle, so `plan_update`
  reports `retire` (upstream removed, not tracked further) instead of
  `conflict`, regardless of whether the local copy still exists. No manual
  restore is needed first.
- This repository's own `scripts/`/`evals/development-workflow/` copies are
  now the single source of truth — the duplicate-drift bug they had already
  accumulated cannot recur, since there is only one copy left.
- `scripts/verify_release.py`'s release gate is otherwise unchanged: the same
  two checks still run, against the same bundle (`src/codev_workflow/bundle`)
  for `validate-development-workflow.py`'s skill/guide checks.
- Testing needs: a regression test asserting `_walk_bundle()`'s output
  contains none of the three relocated paths, mirroring the existing
  `verify_bundle_packaging`/`OPENCODE_AGENT_CONFIGS` regression tests this
  session already added for the same class of bundle-drift bug.
