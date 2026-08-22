# Native Skill-Eval Harness: Ergonomics and Terminology Design

**Status:** Accepted
**Owner:** CoDev maintainers
**Brief:** [brief.md](brief.md)
**Last reviewed:** 2026-08-22

## Summary

Rename the native harness's vocabulary to the field's actual terms (task,
trial, trajectory, baseline, benchmark), all scoped under `codev eval` so
nothing collides with the pre-existing `codev task` work-item tracker. Add a
shared verifier-helpers library, a declarative-checks alternative to writing a
verifier script from scratch, `codev eval doctor`, a fake-agent dry-run mode,
a plain-text report renderer, and an opt-in Docker sandbox backend. Because
CoDev is Alpha, this is a clean break: `fixture`/`eval run`/`eval snapshot run`
are removed, not aliased, and every existing committed fixture is migrated in
one pass.

## Goals and Non-goals

### Goals

- Writing a new task should mean: scaffold it, write a prompt and a short list
  of expected-behavior assertions, check the assertions locally against a fake
  response in seconds, then run it for real -- with a shared library covering
  the common assertion shapes.
- Terminology anyone who has used SkillEvaluator, Google Cloud's agent-eval
  guidance, or DeepMind's own public agent work recognizes on first read.
- Zero collision with `codev task` (development work-item tracking).

### Non-goals

- Backward compatibility. No deprecated aliases; old commands are removed.
- Renaming `actor` to `agent` -- CoDev already uses "agent" for platforms
  (`--agent-platform`, `AGENTS.md`); keeping "actor" avoids a second, unrelated
  collision the same way avoiding `codev task` avoids the first.
- Renaming the `repository/` seed directory to `environment/` -- that name is
  reserved for the new sandbox-backend concept (Worktree vs. Docker) instead,
  to avoid two unrelated things sharing one name.
- Adopting SkillEvaluator's multi-tier or multi-dimensional reward structure --
  the actor/verifier/judge shape and its `passed|failed|error` +
  judge-verdict result contract are unchanged; only ergonomics and vocabulary
  change.
- Making Docker the default sandbox, or CoDev building/provisioning a Docker
  image itself -- opt-in, user-supplied image, matching the same
  never-provision-infrastructure posture already established for the NVIDIA
  engine.

## Current System and Evidence

- `src/codev_workflow/eval.py` (~2430 lines) implements fixture validation,
  git-worktree isolation, the OpenCode actor/judge driver, and result
  publication, all under "fixture" vocabulary. `evaluate()` already accepts an
  `opencode: str` executable-path parameter used today only by
  `tests/test_eval.py`'s fake-executable pattern -- this is the seam Goal 5
  (dry-run) reuses, not new plumbing.
- Three committed verifiers total 277 lines
  (`check_review.py`, `check_test_double.py`, `check_audit_plan.py`), each with
  an independent `json.load`/`except (OSError, json.JSONDecodeError)` block, an
  independent keyword-in-haystack finding matcher, and three different
  (`check_review.py`: none; `check_test_double.py`: re-run the test suite;
  `check_audit_plan.py`: `git diff`/`git status` against the root commit)
  ways of checking file-purity.
- `docs/adr/0023-work-item-renamed-to-task.md` and
  `src/codev_workflow/task.py:24` (`TASK_DIR_RELATIVE = PurePosixPath(".codev/task")`,
  singular) confirm `codev task` and its on-disk state are a separate,
  pre-existing system this rename must not collide with, visually or on disk.
- `docs/features/nvidia-skill-evaluator/design.md` and
  [`../../adr/0026-...md`](../../adr/0026-external-evaluation-engines-are-thin-subprocess-wrappers.md)
  are the precedent for this document's shape and for treating Docker as a
  scoped, explicitly-flagged exception rather than a silent one.

## Vocabulary Map

| Old | New | Notes |
|---|---|---|
| fixture / `.codev/fixtures/<name>/` | **task** / `.codev/eval/tasks/<name>/` | avoids colliding with `.codev/task/` (singular, work-item state) |
| `fixture.json` | `task.json` | same fields, see Task Contract below |
| `codev eval fixture create` | `codev eval task create` | |
| `codev eval run <name>` | `codev eval task run <name>` | |
| `--without-skill` | `--baseline` | |
| `codev eval snapshot run <skill>` | `codev eval benchmark run <skill>` | |
| one actor+verifier+judge attempt | **trial** | naming only, no schema change |
| `actor-events.jsonl` + `actor-output.txt` | `trajectory.json` | merged, see Result Contract |
| `judge-events.jsonl` | `judge-trajectory.json` | same merge, judge side |
| `verifier` / `verifier.json` / `result.json` / `judge-output.json` | unchanged | already correct |
| `repository/` | unchanged | reserved meaning kept; see Non-goals |
| `snapshot.json` | `benchmark.json` | follows the command rename |

## Components and Ownership

| Component | Responsibility | State |
|---|---|---|
| CLI | `codev eval task create\|run`, `codev eval benchmark run`, `codev eval doctor` | Rename + extend |
| `codev_workflow.eval` | Task validation, trial orchestration, result publication | Rename identifiers; behavior unchanged except Result Contract merge |
| `codev_workflow.eval_checks` (new) | Shared verifier-helper functions; declarative check runner | New |
| `codev_workflow.eval_environment` (new) | `Environment` protocol; `WorktreeEnvironment` (existing behavior, extracted) and `DockerEnvironment` (new, opt-in) | New |
| `codev_workflow.eval_report` (new) | Plain-text renderer for one trial's or one benchmark's output directory | New |

## Task Contract

`.codev/eval/tasks/<name>/` -- same five entries as today's fixture, renamed
file:

```text
task.json      # was fixture.json; same required fields, same strictness
prompt.md
rubric.md
verifier.json  # OPTIONAL now -- mutually exclusive with checks.json
checks.json    # OPTIONAL -- declarative alternative to verifier.json
repository/
```

`task.json` keeps every field name from `fixture.json` unchanged
(`schema_version`, `name`, `description`, `skill`, `category`,
`actor_timeout_seconds`, `judge_timeout_seconds`) -- only the file and
directory names change, not the schema, so `validate_fixture` becomes
`validate_task` with the same body plus a `name == root.name` check against
the new path.

A task declares **exactly one** of `verifier.json` or `checks.json` at
load time; declaring both or neither is a validation error, matching the
project's existing strict-schema ethos (unknown fields already rejected
today).

### `checks.json`: the declarative alternative

```json
{
  "schema_version": 1,
  "checks": [
    {"type": "json_field_equals", "file": "audit-plan.json", "field": "decision", "equals": "APPROVAL_REQUIRED"},
    {"type": "finding_matches", "file": "audit-plan.json", "field": "findings", "location_contains": "_compute_average", "any_keyword": ["docstring", "documentation"]},
    {"type": "files_unchanged_except", "except": ["audit-plan.json"]}
  ]
}
```

Four built-in check types cover every pattern the three existing verifiers
needed by hand:

| `type` | Does |
|---|---|
| `json_field_equals` | Load `file`, assert `field` (dot-path) equals `equals` |
| `finding_matches` | Load `file`, assert some entry in the array at `field` has combined `location`/`summary`/`category` containing `location_contains` and any of `any_keyword` |
| `files_unchanged_except` | `git diff`/`git status` against the seed root commit; assert only paths in `except` changed |
| `command_succeeds` | Run `argv` with `timeout`; assert exit code 0 (the escape hatch for "the test suite still passes"-style checks) |

All four are implemented once, in `eval_checks.py`, and reused by every task
that opts in -- a custom Python `verifier.json` remains available for
anything these four don't cover, including future check types added later
without a schema migration (a task never has to choose between "declarative"
and "possible" -- only between "declarative" and "one Python script").

`eval_checks.py` also exposes the same four building blocks as plain
functions (`load_structured_output`, `finding_matches`,
`changed_paths_since_seed`, `require`) for a custom `verifier.json` script to
import directly (`from codev_workflow.eval_checks import ...`) -- this works
because the verifier subprocess's `python3` is resolved to the same
interpreter running CoDev itself (see `_isolated_env`'s existing PATH
handling), so `codev_workflow` is always importable there without any new
plumbing.

## Result Contract

```text
<output>/
  .codev-eval-commit.json
  result.json          # unchanged schema
  trajectory.json       # was actor-events.jsonl + actor-output.txt
  verifier-stdout.txt
  verifier-stderr.txt
  judge-trajectory.json # was judge-events.jsonl; present only after verifier success
  judge-output.json     # unchanged schema; present only after verifier success
  diff.patch
```

`trajectory.json` merges the actor's JSONL event stream and its final text
output into one structured file mirroring SkillEvaluator's own shape
(confirmed directly this cycle: `json_pointer": "/steps/33"`-style references
into a single file):

```json
{
  "schema_version": 1,
  "steps": [
    {"index": 0, "event": {"...": "..."}},
    {"index": 33, "final_output": "..."}
  ]
}
```

Existing consumers of `actor-events.jsonl`/`actor-output.txt` (only
`tests/test_eval.py` today) are updated in the same change; there is no
external consumer to preserve compatibility for.

## CLI Behavior

| Command | Replaces | Behavior |
|---|---|---|
| `codev eval task create NAME --target PATH --include PATH...` | `eval fixture create` | unchanged behavior, new name |
| `codev eval task run NAME --target PATH --output PATH [--baseline] [--agent PATH]` | `eval run` | `--baseline` replaces `--without-skill`; `--agent PATH` is new -- overrides the resolved OpenCode executable, exposing the existing `evaluate(..., opencode=...)` parameter for a fake-agent dry run |
| `codev eval benchmark run SKILL --target PATH --output PATH [--repetitions N] [--category ...]` | `eval snapshot run` | unchanged behavior, new name; writes `benchmark.json` instead of `snapshot.json` |
| `codev eval doctor [--target PATH]` | *(new)* | Prints `git`/`opencode` presence and version, plain text, no network call; exit 0 only if both resolve |
| `codev eval report OUTPUT_DIR` | *(new)* | Renders one trial's or one benchmark's output directory as plain text -- the same rendering `_format_snapshot_report` already does for benchmarks, generalized to also cover a single trial's `result.json`/`trajectory.json`/`judge-output.json` |

`codev eval task run --agent PATH` is the dry-run mechanism: pointing it at a
small stub script (the same shape `tests/test_eval.py`'s `_opencode()` helper
already writes) lets a task author validate `checks.json`/`verifier.json`
logic against a synthetic response in under a second, with zero API cost --
no new flag semantics beyond what `evaluate()` already accepts internally.

## Environment Backend (opt-in Docker)

```python
class Environment(Protocol):
    def create(self, seed: Path) -> Path: ...  # returns the actor's cwd
    def run(self, argv, cwd, timeout, env) -> Run: ...
    def capture_diff(self, seed_commit: str) -> str: ...
    def cleanup(self) -> None: ...
```

`WorktreeEnvironment` is the existing `evaluate()` logic (seed copy, temp git
init, detached worktree, `_git`/`_run`) extracted behind this interface with
no behavior change -- it stays the default. `DockerEnvironment` is new:
`create()` starts a container from a user-supplied image (declared in
`task.json`'s optional `environment: {"backend": "docker", "image": "..."}`
block; CoDev never builds, pulls, or ships an image itself, matching the
NVIDIA engine's posture), mounts the seed there instead of a host worktree,
and runs the actor inside it. Selected via `codev eval task run --sandbox
docker`; the task itself declares whether it *supports* Docker (the
`environment` block), the CLI flag decides whether to *use* it for a given
run. A task with no `environment` block cannot be run with `--sandbox
docker`.

This is the piece flagged in the brief as needing its own ADR before
implementation: it is the only genuine exception to
`docs/architecture.md`'s "no containers" posture, and should be recorded the
same deliberate, scoped way ADR-0026 records the NVIDIA engine's
credential/Docker exceptions.

## Alternatives and Trade-offs

| Option | Benefits | Costs | Decision |
|---|---|---|---|
| Deprecated aliases for old commands | Softer migration | Real work for zero users, since Alpha has none to protect | Rejected -- clean break |
| Rename `actor` -> `agent` for full SkillEvaluator parity | Terminology purity | Collides with CoDev's existing "agent platform" vocabulary | Rejected |
| `checks.json` replaces `verifier.json` entirely | One way to do it | Loses the escape hatch for anything the four built-in types can't express (already true today, e.g. the test-suite-still-passes check) | Rejected -- both coexist, mutually exclusive per task |
| CoDev builds/ships a default Docker image | Fewer setup steps for Docker users | Directly contradicts the established "never provision infrastructure" posture from the NVIDIA engine | Rejected |
| Docker as the new default sandbox | Stronger isolation everywhere | Silently reverses the "no containers" invariant for every existing task | Rejected -- opt-in only |

## Quality and Risk

- **Migration risk:** every committed task (`normalize-slug`,
  `test-double-fidelity`, the `seeded-defect-*` corpus,
  `design-skill-eval-bootstrap`, `audit-google-python-style-demo`) must be
  moved and re-validated in the same change, not left half-migrated. Track
  this as one checklist in the implementation plan below, not "as needed."
- **Docker image drift:** since CoDev never builds the image, a task's
  declared `environment.image` can go stale (missing a dependency, wrong
  Python version) with no CoDev-side detection. Document this plainly in
  `codev eval doctor`'s Docker-mode output rather than silently failing deep
  inside a container.
- **`checks.json` schema growth:** four built-in types are enough for every
  existing task; adding a fifth later is additive (new `type` value, no
  version bump needed) as long as unknown `type` values are rejected at
  load time now, the same strict-unknown-field posture used everywhere else
  in this contract.
- **Compatibility:** unchanged from the existing harness -- macOS-verified,
  Windows/Linux deferred risk.

## Implementation Plan

1. Rename module-internal identifiers and public functions in `eval.py`
   (`validate_fixture`->`validate_task`, `Fixture`->`Task`, etc.); no behavior
   change. Run the full existing test suite to confirm zero regression before
   proceeding.
2. Add `eval_checks.py` (the four built-in check types plus the four
   importable helper functions) with its own unit tests, independent of the
   CLI.
3. Add the `verifier.json` XOR `checks.json` validation rule to task loading;
   wire the declarative runner in for tasks that declare `checks.json`.
4. Extract `Environment`/`WorktreeEnvironment` from `evaluate()`'s inlined
   worktree logic with no behavior change; run the full suite again.
5. Add `DockerEnvironment` behind `--sandbox docker`, gated on the task
   declaring an `environment` block; write the scoped ADR before merging
   this step specifically.
6. Merge `actor-events.jsonl`/`actor-output.txt` into `trajectory.json`
   (and the judge side to `judge-trajectory.json`); update
   `tests/test_eval.py`'s only internal consumer.
7. Add the CLI surface: `codev eval task create|run`, `codev eval benchmark
   run`, `codev eval doctor`, `codev eval report`, `--baseline`, `--agent`,
   `--sandbox`. Remove `fixture`/`eval run`/`eval snapshot run` and their
   `_apply_deprecated_aliases` entries in the same change.
8. Migrate every committed task: move directory, rename `fixture.json` to
   `task.json`, re-run `codev eval task run` (or the new dry-run `--agent`
   mode where a real run isn't warranted) to confirm each still passes.
9. Update `docs/features/skill-eval/README.md` (or fold it into this
   feature's own README, maintainer's call at implementation time) and the
   main `README.md`'s command-reference table.

## Test Strategy

- `python -m unittest discover -s tests -v`; the full suite must stay green
  after every implementation-plan step above, not just at the end.
- New unit tests for `eval_checks.py`'s four check types plus its four
  importable helpers, independent of any real CLI invocation.
- New unit tests for `DockerEnvironment` using a fake `docker`/`docker
  compose` executable, the same fake-executable convention already used for
  `opencode`/`git` -- no real Docker invocation in this part of the suite.
- **Addendum, added after this document's initial acceptance:**
  `tests/test_eval_docker_benchmark.py` additionally builds and runs a real
  local Docker image/container against the real `audit-google-python-style`
  skill and its real `audit-google-python-style-demo` task (copied into an
  isolated temporary repository, never the committed one), proving
  `DockerEnvironment`'s bind-mount/workdir contract against an actual
  container, not only against a scripted stand-in for `docker` itself. This
  is `@unittest.skipUnless`-gated on a real, running Docker daemon being
  detected at import time -- it is skipped, never failed, on a machine
  without Docker, consistent with Docker remaining opt-in, deferred-risk
  infrastructure rather than a hard test-suite dependency.
- One real, manually-run smoke check per migrated task (`codev eval task run
  <name> --target . --output <dir>`), the same "fake executables in unit
  tests, one real manual run" split already used for the native harness and
  the NVIDIA engine.
- `python -m ruff check .`, `python -m ruff format --check .`, `python -m mypy`.

## Migration, Rollout, Rollback, and Cleanup

Clean break, single change: old commands and `.codev/fixtures/` stop existing
in the same release that introduces `codev eval task`/`.codev/eval/tasks/`.
No dual-running period, no aliasing, because CoDev is Alpha and there is no
external compatibility surface to protect. Every committed task is migrated
in the same change (Implementation Plan step 8) -- this ships as one
release, not a phased rollout.

## Acceptance

- [ ] Full existing test suite passes after every implementation-plan step,
  not only at the end.
- [ ] Every currently-committed fixture has a migrated, passing equivalent
  under `.codev/eval/tasks/`.
- [ ] `checks.json` covers every pattern the three original verifier scripts
  needed, demonstrated by rewriting at least one migrated task
  (`audit-google-python-style-demo` is the natural candidate, since its
  verifier is the newest and best-understood) to use it instead of a custom
  script.
- [ ] `codev eval task run --agent <fake-script>` demonstrated finding a
  deliberately broken `checks.json`/verifier in under a second, with no real
  OpenCode invocation.
- [ ] `DockerEnvironment` unit-tested against a fake `docker` executable; its
  ADR written and accepted before that step merges.
- [ ] Python maintainer reviews and accepts this design.
