---
name: design-skill-eval
description: Guide a developer through designing and scaffolding one new fixture for an installed skill's performance-evaluation corpus -- pick a falsifiable ground truth, write a prompt that never names the skill, a deterministic verifier, and a judge rubric, then tag it with the right skill and category so `codev eval snapshot run` discovers it. Use when adding eval coverage for an existing skill, or bootstrapping the first fixture for a skill that has none. Do not use to run an existing snapshot, to build or edit the skill under test itself, or for general code review.
---

# Design Skill Eval

Help a developer turn "I want to know if skill X actually works" into one
committed fixture under `.codev/fixtures/<name>/` that `codev eval run` and
`codev eval snapshot run` can execute. The mechanical scaffolding
(`codev eval fixture create`) is the easy part; the design decisions below
are what make the resulting fixture worth running at all. Read
`references/eval-design-checklist.md` before writing prompt.md, verifier.json,
or rubric.md -- it has the failure modes that make a fixture worthless even
though it validates cleanly.

## 1. Confirm this is the right path

Use this skill to add or design one eval fixture for a skill that already
exists in this repository.

Redirect instead when:

- the developer wants to *run* fixtures that already exist -- point them at
  `codev eval run <name>` or `codev eval snapshot run <skill>`;
- the developer wants to build or change the skill itself, not evaluate it --
  that is ordinary `build-change` work on `.agents/skills/<name>/`;
- the request is a normal code review -- use `review-change`.

## 2. Understand the skill under test

Read the skill's `SKILL.md` completely: what does it promise, what does a
correct outcome look like, and what would a plausible failure look like?
Then inspect `.codev/fixtures/*/fixture.json` for existing fixtures already
tagged with this skill (`skill` field). Note their `category` values --
reuse an existing category if this fixture genuinely tests the same
dimension, or add a new one only if it doesn't. Don't invent a category name
that duplicates an existing one under a different spelling.

If this is the skill's *first* fixture, look at `.codev/fixtures/seeded-defect-*`
for `review-change` as a worked example of the seeded-defect pattern before
deciding whether it fits the skill you're evaluating.

## 3. Choose the ground-truth mechanism

This is the real design decision, and it determines everything downstream.

**Seeded-defect (falsifiable, deterministic) -- prefer this when possible.**
Seed the repository with one deliberately planted, specific, checkable
problem (a bug, a missing check, a wrong value, a broken contract). The
verifier is a small script that greps or parses the actor's output for
evidence the *specific* planted problem was addressed -- not just "did the
actor do something plausible." This is what every `seeded-defect-*` fixture
does for `review-change`.

**Rubric-only (open-ended) -- accept this only when a seeded fixture
genuinely isn't constructible.** Some skills produce output whose quality
isn't reducible to "did it catch one specific thing" (open-ended writing,
synthesis, exploratory design). Here the verifier can only check structural
validity (the output exists, parses, matches a schema), and the judge's
rubric carries the entire quality signal. Say explicitly in the fixture's
`description` that this fixture has no deterministic ground truth, so
nobody mistakes a passing judge verdict for the stronger guarantee a seeded
fixture gives.

Do not pick rubric-only by default because it's easier to write. It produces
a materially weaker fixture -- read
`references/eval-design-checklist.md#ground-truth` before deciding.

## 4. Pick a category

A category groups fixtures for aggregation in `codev eval snapshot run`'s
report -- it is not one-fixture-per-category by rule, just by convention so
far in this repository. Multiple fixtures can share a category; the
snapshot's percentage for that category is the aggregate pass rate across
all of them. Pick a name that describes the *dimension being tested*
(`security`, `error_handling`, `citation_accuracy`), not the fixture's
specific scenario.

## 5. Scaffold the fixture

`codev` is a real command, already installed and on `PATH` in this
environment -- run it directly as a shell command, the same way you would
run `git`. Do not hand-write `fixture.json` from scratch: `fixture.json`
accepts *only* `schema_version`, `name`, `description`, `skill`,
`category`, `actor_timeout_seconds`, and `judge_timeout_seconds` --
`validate_fixture()` rejects it outright for a missing required field or an
invented extra one (e.g. a `"prompt": "prompt.md"` field pointing at the
other files by name -- the filenames are fixed by convention, not declared
in the manifest). Observed directly, twice, from two different actors: one
otherwise well-designed fixture failed validation for a missing timeout
field after being hand-written instead of scaffolded; another failed for
inventing manifest fields that don't exist in the real schema. Both mistakes
disappear if you run the command below instead of guessing the file's shape.

```bash
codev eval fixture create <name> --target . --include <path> --include <path>
```

`--target` must be an existing Git repository; `--include` selects the
specific files that become the fixture's `repository/` seed (repeat the
flag per file or directory). This writes a starter `fixture.json`,
`prompt.md`, `rubric.md`, and `verifier.json` under
`.codev/fixtures/<name>/` for you to edit -- it does not infer a working
fixture on its own. `--include` requires paths that already exist in
`--target`; brand-new seed content (a toy target file, a bespoke verifier
script) still needs to be written by hand after scaffolding runs.

## 6. Design the seed repository

Keep `repository/` small and self-contained: only the files genuinely
needed for the scenario, no `.git`, no secrets, no symlinks, no external
dependencies, no assumption of network access. The actor will get a fresh
Git worktree built from exactly this seed and nothing else it doesn't
discover on its own.

## 7. Write `prompt.md`

The prompt must describe the task on its own terms and never name the skill
being evaluated. Staging (or not staging) `.agents/skills/<skill>/` into
the worktree is the *only* thing that should differ between the with-skill
and without-skill conditions (see `_stage_skill()` in `src/codev_workflow/eval.py`
if you want the mechanism, not just the rule); a prompt that says "follow
the X skill" defeats the comparison before it starts.

If the actor must produce output in a specific machine-checked shape,
**spell out the exact schema in the prompt itself** -- field names, allowed
values, format. Don't assume the actor can infer or already knows a
project-specific contract. This exact mistake silently broke this
project's own judge step earlier: the prompt said "return the required
JSON" without ever stating what "required" meant, and the model spent its
whole turn exploring instead of answering. Assume nothing is known that
isn't written down in this file.

## 8. Write the deterministic verifier

`verifier.json` is `{"schema_version": 1, "command": [...], "timeout_seconds": N}`
-- an argv array, not a shell string. Use only standard-library tooling; do
not assume network access or installed dependencies. The verifier script
must fail when the specific planted problem is missed, not merely when the
actor crashes or produces no output at all -- a verifier that only checks
"did something get written" cannot distinguish a real pass from a lucky one.

## 9. Write `rubric.md`

The judge never sees the actual worktree or code -- only `rubric.md` and
the captured evidence (`actor-output.txt`, `diff.patch`, verifier
stdout/stderr). Every rubric criterion must be answerable from that
evidence alone. A criterion that requires re-inspecting the source (e.g.
"is the fix idiomatic for this codebase") cannot be judged fairly and will
produce noise, not signal.

## 10. Tag the fixture

Set `"skill"` and `"category"` in `fixture.json` (required fields --
`validate_fixture()` rejects a fixture missing either). These are what
`codev eval snapshot run <skill>` uses to discover and group the fixture;
without them the fixture cannot be run as part of a snapshot at all.

## 11. Prove the fixture actually discriminates

Before treating the fixture as done, run it both ways:

```bash
codev eval run <name> --target . --output <dir-with-skill>
codev eval run <name> --target . --output <dir-without-skill> --without-skill
```

A fixture that passes in both conditions, or fails in both, carries no
signal about the skill -- it's a tautology, not an eval. You want a
realistic chance that without-skill fails and with-skill passes; if that
isn't true, the planted problem is either too easy (any capable model
avoids it unprompted) or too hard (the skill alone can't reliably prevent
it). Adjust the scenario, not the pass condition, to fix this.

## 12. Confirm corpus integration

Run `codev eval snapshot run <skill> --category <this-category> --repetitions 1`
once to confirm the fixture is discovered and reports cleanly before
committing it. Mention the live-model cost to the developer before running
anything beyond this one-repetition check -- see
`docs/features/skill-eval/README.md` for the cost shape of a full snapshot.

## Stop conditions

Stop and ask for one precise decision when:

- the skill under test has no clear definition of a correct outcome to seed
  a defect against;
- the developer wants a rubric-only fixture and hasn't been told about the
  weaker guarantee that implies;
- the planted problem can't be checked without either network access or a
  dependency beyond the standard library; or
- the fixture's with/without run (step 11) doesn't discriminate and the
  developer wants to ship it anyway.
