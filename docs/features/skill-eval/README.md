# Skill evaluation harness

The local harness evaluates one installed skill in an isolated temporary Git
worktree (or, opt-in, a Docker container -- see
[`../skill-eval-ergonomics/design.md`](../skill-eval-ergonomics/design.md)
and `docs/adr/0027-opt-in-docker-sandbox-for-the-native-eval-harness.md`). It
runs one OpenCode actor, one verifier (a custom script or declarative
`checks.json`), and—only when the verifier passes—a fresh OpenCode judge.

**Note:** this harness's own vocabulary and CLI surface were renamed for
clarity partway through this project (fixture → task, snapshot → benchmark,
`--without-skill` → `--baseline`). CoDev is Alpha, so this was a clean break,
not an aliased migration -- see
[`../skill-eval-ergonomics/brief.md`](../skill-eval-ergonomics/brief.md) for
why. This document describes the current, renamed surface.

New to this harness? [how-to-write-a-task.md](how-to-write-a-task.md) is a
narrated, start-to-finish guide to writing and testing a task for your own
skill; this document is the architecture reference it links back to.

## Task layout

Committed tasks live at `.codev/eval/tasks/<name>/` and use this layout:

```text
task.json      # name, description, and actor/judge timeouts
prompt.md      # actor task
rubric.md      # judge criteria
verifier.json  # a custom verifier: one argv command and timeout
checks.json    # OR a declarative alternative to verifier.json (see below)
repository/    # small, self-contained seed repository
```

A task declares exactly one of `verifier.json` or `checks.json` -- never
both, never neither. The seed must contain only regular safe files. Do not
include `.git`, secrets, symlinks, dependencies, or external-service
assumptions.

`verifier.json`'s command is an argv array, not a shell string; use
deterministic standard-library tooling, or import
`codev_workflow.eval_checks`'s shared helpers
(`load_structured_output`, `finding_matches`, `changed_paths_since_seed`,
`require`) instead of reimplementing them -- every verifier script this
project shipped before this helper existed reinvented the same JSON-loading
and finding-matching logic by hand.

`checks.json` expresses the common cases as data instead:

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

Four built-in check types cover every pattern this project's own verifier
scripts have ever needed: `json_field_equals`, `finding_matches`,
`files_unchanged_except`, and `command_succeeds` (an escape hatch for "run
this and check it exits 0," e.g. "the test suite still passes"). See
[`../skill-eval-ergonomics/design.md`](../skill-eval-ergonomics/design.md)
for the exact schema of each.

## Create and evaluate a task

From a Git repository, create a reviewed starter by selecting explicit paths:

```shell
codev eval task create my-scenario \
  --target . \
  --include src/example.py \
  --include tests/test_example.py
```

Edit the generated contract files and seed, then evaluate it into a caller-
created empty directory outside the active repository when practical:

```shell
mkdir -p ../skill-evidence/my-scenario
codev eval task run my-scenario --target . --output ../skill-evidence/my-scenario
```

Before spending real API budget on a full run, check your environment is
ready:

```shell
codev eval doctor --target .
```

...and, once you have a result, read it back without manually `cat`-ing JSON:

```shell
codev eval report ../skill-evidence/my-scenario
```

While iterating on a `verifier.json`/`checks.json`, point `--agent` at a
small fake-executable stub script instead of waiting on a real ~10-minute
OpenCode run -- the same pattern this project's own test suite already uses
internally to fake OpenCode:

```shell
codev eval task run my-scenario --target . --output <dir> --agent ./fake-agent.py
```

Evaluation copies the seed to temporary Git storage and never uses the active
working tree for actor changes. The verifier runs with the temporary worktree
as its current directory, without shell parsing or dependency installation.

OpenCode must already be installed and authenticated through the user's existing
OpenCode account/subscriber configuration. CoDev does not choose a provider or
model, read or print credentials, or mutate OpenCode configuration. Project-owned
OpenCode configuration remains project-owned and is discovered in the isolated
worktree.

## Reading the evidence

Successful output contains `result.json`, `trajectory.json` (the actor's
merged event stream and final text output), verifier stdout/stderr,
`diff.patch`, and (after a passing verifier) `judge-trajectory.json` and
`judge-output.json`. The hidden `.codev-eval-commit.json` marker is the
durable completeness marker: consumers should validate its manifest and
every listed file before treating the bundle as complete. `result.json`
reports `passed`, `failed`, or `error`; a verifier failure has a skipped
judge, and no failed verifier can be overridden by the judge. Use the diff
and captured stdout/stderr as observable evidence, not agent private
reasoning. `codev eval report <output-dir>` renders this as plain text
instead of requiring a manual walk through each file.

## Skill performance benchmarks

Every task declares a `"skill"` and a `"category"` in its `task.json`.
`codev eval benchmark run <skill>` discovers every task tagged with that
skill, groups them by category, and runs each one twice: once with the skill
staged into the worktree (`.agents/skills/<skill>/` plus its `AGENTS.md`
routing block, copied from `--target`) and once as the baseline, without it.
The prompt is identical in both conditions - it never names the skill - so
the only variable is whether the actor can discover and use it on its own,
the same way it would in a real installed repository. Repeat each condition
with `--repetitions` (default 3; live model output has real sampling
variance, so a single run is a noisy point estimate, not a score).

```shell
codev eval benchmark run review-change --target . --output ../skill-evidence/review-change
```

The report (`benchmark.json` in the output directory) gives a pass
percentage per category for each condition (with-skill and baseline), plus
the delta between them - the empirical answer to whether the skill
measurably outperforms not having it at all, not just whether the reviewer
catches a known defect in isolation. `.codev/eval/tasks/seeded-defect-*/`
is the committed corpus backing `review-change`'s benchmark: one task per
review dimension, each seeding a small reviewable change with one
deliberately planted, known defect, verified deterministically by
`repository/check_review.py` rather than trusted from the coverage checklist
in `review-change/SKILL.md` alone. See `docs/adr/0001-work-lifecycle-invariant.md`
for why this exists. CI runs a benchmark on a schedule (not per pull request)
and on release tags.

`.codev/eval/tasks/audit-google-python-style-phase-a/` is a second,
standalone worked example -- a template to copy when writing a task for a
skill of your own, not part of a larger corpus, and the reference example
for `checks.json` specifically (all four built-in check types are
available; this task uses three). Against a real production controller
file, its `checks.json` verifies the actor's plan flags the planted
wildcard import, illegal `tmp_` binding, and non-PascalCase class name,
requests approval rather than editing anything, and leaves every source
file byte-for-byte unchanged -- the read-only "Phase A" contract this
particular skill requires. Its sibling,
`.codev/eval/tasks/audit-google-python-style-phase-b/`, covers the
corresponding "Phase B" remediation contract (approved edits applied,
verified with a hand-written `verifier.json` script instead of
`checks.json`, since that check needs real AST analysis of the edited
file). Run either the same way:

```shell
codev eval task run audit-google-python-style-phase-a --target . --output ../skill-evidence/audit-google-python-style-phase-a
```

A single task can still be run in isolation with `codev eval task run
<name>`; pass `--baseline` to see that one task's baseline condition without
running a full benchmark. `codev eval benchmark run` also accepts `--agent`,
the same fake-executable-stub override as `eval task run --agent`, for a
zero-cost dry run of a whole category's plumbing before spending real model
budget on it -- and `--sandbox docker`, forwarded to every trial in the run
the same way `eval task run --sandbox docker` does for a single one; every
task in the benchmark still needs its own declared `environment` block to
use it (see ADR-0027).

## Packaged eval trace

An unrestricted `codev eval benchmark run <skill>` (no `--category` filter)
also writes the report into the skill's own directory --
`.agents/skills/<skill>/evals/benchmark.json` plus a Markdown rendering at
`.agents/skills/<skill>/evals/BENCHMARK.md` -- so the skill carries evidence
of its own measured effect, not just instructions. This mirrors NVIDIA
SkillEvaluator's Recommended Artifact Set for a skill package; see
[ADR-0028](../../adr/0028-skill-packages-carry-their-own-eval-trace.md).
Pass `--no-package` to skip this (e.g. a scratch run against a target you
don't want written to); a `--category`-restricted run never packages, since
its partial coverage shouldn't silently overwrite a fuller trace.

```shell
codev eval show review-change --target .
```

`codev eval show <skill>` reads that packaged trace back and renders it as
text -- no need to locate or retain the `--output` directory from whatever
run produced it. If the skill has never been benchmarked (or was benchmarked
with `--no-package`), it says so and names the command to run.

## Platform and known risks

V1 is verified on macOS with OpenCode 1.18.11. Windows and Linux support,
including process-tree termination and cleanup semantics, is deferred risk and
not a V1 acceptance requirement. `DockerEnvironment` (the opt-in Docker
sandbox) carries the same deferred-risk posture.

The accepted V1 privacy risk for URL credentials remains: unstructured
diagnostics may contain credential-bearing URL user-info or sensitive query
parameters that redaction does not reliably remove. Do not put credentials in
task or process diagnostics; URL-aware hardening is follow-up work.

Publication also has a deferred crash/concurrent-output issue. An interruption
while evidence is being published, or concurrent replacement of the output
directory, can leave partial evidence. Use a unique output directory and
discard any output without a valid commit marker. Crash-consistent single-bundle
publication is not fixed in V1.
