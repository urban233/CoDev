# Skill evaluation harness

The local harness evaluates one installed skill in an isolated temporary Git
worktree. It runs one OpenCode actor, one deterministic verifier, and—only when
the verifier passes—a fresh OpenCode judge.

## Fixture layout

Committed fixtures live at `.codev/fixtures/<name>/` and use the v1 layout:

```text
fixture.json   # name, description, and actor/judge timeouts
prompt.md      # actor task
rubric.md      # judge criteria
verifier.json  # one argv command and timeout
repository/    # small, self-contained seed repository
```

The seed must contain only regular safe files. Do not include `.git`, secrets,
symlinks, dependencies, or external-service assumptions. The verifier is an
argv array, not a shell string; use deterministic standard-library tooling.

## Create and evaluate a fixture

From a Git repository, create a reviewed starter by selecting explicit paths:

```shell
codev fixture create my-scenario \
  --target . \
  --include src/example.py \
  --include tests/test_example.py
```

Edit the generated contract files and seed, then evaluate it into a caller-
created empty directory outside the active repository when practical:

```shell
mkdir -p ../skill-evidence/my-scenario
codev eval my-scenario --target . --output ../skill-evidence/my-scenario
```

Evaluation copies the seed to temporary Git storage and never uses the active
working tree for actor changes. The verifier runs with the temporary worktree as
its current directory, without shell parsing or dependency installation.

OpenCode must already be installed and authenticated through the user's existing
OpenCode account/subscriber configuration. CoDev does not choose a provider or
model, read or print credentials, or mutate OpenCode configuration. Project-owned
OpenCode configuration remains project-owned and is discovered in the isolated
worktree.

## Reading the evidence

Successful output contains `result.json`, the actor event/output files,
verifier stdout/stderr, `diff.patch`, and judge artifacts. The hidden
`.codev-eval-commit.json` marker is the durable completeness marker: consumers
should validate its manifest and every listed file before treating the bundle as
complete. `result.json` reports `passed`, `failed`, or `error`; a verifier
failure has a skipped judge, and no failed verifier can be overridden by the
judge. Use the diff and captured stdout/stderr as observable evidence, not agent
private reasoning.

## Seeded-defect recall corpus

`.codev/fixtures/seeded-defect-*/` is a committed corpus of seven fixtures,
one per `review-change` dimension, each seeding a small reviewable change
with one deliberately planted, known defect. Run the whole corpus and get a
recall report with:

```shell
python scripts/run_seeded_defect_suite.py --output ../skill-evidence/seeded-defect
```

This measures whether a reviewer actually catches a known defect - empirical
evidence for review completeness, rather than trusting that the coverage
checklist in `review-change/SKILL.md` was followed. See
`docs/adr/0001-work-lifecycle-invariant.md` for why this exists. CI runs it on
a schedule (not per pull request) and on release tags; each fixture's
`repository/check_review.py` is the deterministic verifier, so a fixture
passes only when the actor's `review.json` actually names the planted defect.

## Platform and known risks

V1 is verified on macOS with OpenCode 1.18.11. Windows and Linux support,
including process-tree termination and cleanup semantics, is deferred risk and
not a V1 acceptance requirement.

The accepted V1 privacy risk for URL credentials remains: unstructured
diagnostics may contain credential-bearing URL user-info or sensitive query
parameters that redaction does not reliably remove. Do not put credentials in
fixture or process diagnostics; URL-aware hardening is follow-up work.

Publication also has a deferred crash/concurrent-output issue. An interruption
while evidence is being published, or concurrent replacement of the output
directory, can leave partial evidence. Use a unique output directory and
discard any output without a valid commit marker. Crash-consistent single-bundle
publication is not fixed in V1.
