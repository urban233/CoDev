# How to write and run a CoDev eval task

A start-to-finish guide for writing your own evaluation task against your
own skill, aimed at a developer who has never touched `codev eval` before.
By the end you'll be able to: scaffold a task, seed it with a real defect,
write its prompt/checks/rubric, test it for free before spending any real
model budget, prove it actually measures something, and read back the
result. Every command and every quoted line of output below was actually
run against the real `codev` CLI while writing this guide -- nothing here
is a hypothetical reconstruction, including the two mistakes in "Two real
mistakes you will probably also make" below.

For the architecture and full flag reference, see
[README.md](README.md) and
[../skill-eval-ergonomics/design.md](../skill-eval-ergonomics/design.md).
This guide is the narrated, "do this" companion to those; it does not
replace them.

## Who this is for

You have (or are about to write) a skill under `.agents/skills/<your-skill>/`
and want an empirical answer to "does this skill actually change what an
agent does" -- not just "does it read well." You don't need to know
anything about CoDev's internals to follow this; you do need:

- a Git repository with your skill already installed under
  `.agents/skills/<your-skill>/`;
- `git` and `codev` on `PATH` (run `codev eval doctor --target .` to check);
- `opencode`, installed and authenticated, **only** for the "running it for
  real" section near the end -- everything before that uses a small stub
  script instead, and costs nothing.

## The mental model, in six terms

| Term | What it means here |
|---|---|
| **Task** | One scenario: a seed repository, a prompt, a way to check the result, and a judge rubric. Lives at `.codev/eval/tasks/<name>/`. |
| **Trial** | One execution of a task: seed copied into an isolated worktree, actor runs, then (if the check passes) a judge runs. |
| **Baseline vs. with-skill** | The same trial run twice: once with your skill staged into the worktree, once without. The prompt never names the skill -- staging it is the *only* difference between the two. |
| **Verifier / checks.json** | The deterministic pass/fail gate. Either a hand-written script (`verifier.json`) or a declarative list of built-in checks (`checks.json`) -- a task has exactly one, never both. |
| **Judge** | Only runs after a passing check. Reads your `rubric.md` plus the captured evidence (never the worktree itself) and returns a pass/fail verdict per criterion. |
| **Benchmark** | Every task tagged with one `"skill"`, grouped by `"category"`, run with and without the skill, repeated `N` times. The output is a per-category pass-rate delta -- the actual signal for "does this skill help." |

## Orientation: the commands you'll use

```shell
codev eval doctor --target .                         # is my environment ready?
codev eval task create <name> --target . --include <path>   # scaffold a task
codev eval task run <name> --target . --output <dir>  # run one task once
codev eval report <output-dir>                        # read a result back as text
codev eval benchmark run <skill> --target . --output <dir>  # run every task for a skill
codev eval show <skill> --target .                    # read a skill's own packaged trace
```

Every one of these accepts `--target` (defaults to the current directory for
`doctor` and `show`; required for the others) and works from anywhere inside
your project. The rest of this guide walks through all six, in the order
you'd actually use them.

## Worked example: a skill that flags hardcoded secrets

The example below is a real, complete task, built the same way you'll build
yours. It tests a fictional skill, `flag-hardcoded-secrets`: *when
reviewing a diff, flag any hardcoded credential-shaped literal and
recommend moving it to configuration.*

### Step 0: your skill has to exist first

`codev eval` tests a skill that's already installed under
`.agents/skills/<name>/` in your repository -- it does not write the skill
for you. For this example, that's a two-line `SKILL.md`:

```markdown
---
name: flag-hardcoded-secrets
description: Use when reviewing a diff. Flags any hardcoded credential-shaped literal (an API key, a password, a token, a connection string with embedded credentials) introduced in the changed code, and asks the author to move it to configuration or environment variables instead.
---

# Flag Hardcoded Secrets

When reviewing a diff, check every changed line for a literal value that
looks like a credential -- an API key, a password, a token, or a connection
string carrying embedded credentials. If you find one, flag it explicitly
and recommend moving it to an environment variable or a secrets manager
instead of leaving it as a literal in source code.
```

(Ignore, for now, the odd phrasing around "a credential -- an API key"
instead of "a credential: an API key" -- that's not a style choice. It's the
fix for the first real mistake below; read on and it will make sense.)

### Step 1: decide your ground truth

This is the decision that determines whether your task is actually useful,
and it's worth getting right before you write anything else:

- **Seeded-defect (prefer this).** Plant one specific, deliberately broken
  thing in the seed repository, and check the actor's output for evidence
  *that specific thing* was caught. This is what the example below does: the
  seed has a hardcoded credential, and the check looks for a finding that
  names it.
- **Rubric-only (only when a seeded task genuinely isn't constructible).**
  For open-ended output (synthesis, exploratory design) where "did it catch
  the one planted thing" doesn't apply, the judge's rubric carries the whole
  signal. This is a strictly weaker guarantee -- say so explicitly in the
  task's `description` if you go this way.

Don't pick rubric-only because it's less work to write; it produces a task
that can't tell you whether the skill actually changed anything.

### Step 2: scaffold it

From a Git repository (your real project, not a scratch copy):

```shell
codev eval task create seeded-hardcoded-api-key \
  --target . \
  --include src/config_loader.py
```

```text
Created task at .codev/eval/tasks/seeded-hardcoded-api-key
```

`--include` copies existing files from `--target` into the task's own
`repository/` seed -- it must already exist at that path in your repo.
This writes four starter files for you to edit, none of them a working task
yet:

```json
{
  "schema_version": 1,
  "name": "seeded-hardcoded-api-key",
  "description": "Describe the bounded scenario.",
  "skill": "replace-with-skill-name",
  "category": "replace-with-category",
  "actor_timeout_seconds": 600,
  "judge_timeout_seconds": 300
}
```

`prompt.md` and `rubric.md` are just `# Prompt` / `# Rubric` headers, and a
starter `verifier.json` runs `python -m unittest discover -s tests` --
delete it if you're using `checks.json` instead (this example does). Do not
hand-write `task.json` from scratch instead of scaffolding it: a missing
`actor_timeout_seconds`/`judge_timeout_seconds` field, or an invented field
that isn't one of the six above, both fail validation outright, and both
have been observed in practice from skipping this step.

### Step 3: seed the defect

Add the "changed" variant of your file under `repository/changed/` -- the
buggy version the actor will actually review. For this example:

```python
# .codev/eval/tasks/seeded-hardcoded-api-key/repository/changed/config_loader.py
"""Load application configuration from environment variables."""

# TODO: remove before merging -- using the staging value directly for now
_STATIC_VALUE = "abcdef123456789"


def load_database_url() -> str:
    import os

    return os.environ["DATABASE_URL"]


def load_billing_key() -> str:
    """Return the billing-provider credential used to sign outgoing requests."""
    return _STATIC_VALUE
```

**Real mistake #1, and why the variable isn't called `API_KEY`.** The first
version of this file used `API_KEY = "sk-live-abcdef123456789"` -- the
obvious name. Scaffolding worked, but the very first `task run` failed
immediately with:

```text
codev: secret-like content is not allowed: .../repository/changed/config_loader.py
```

CoDev redacts anything secret-shaped from every captured output *and*
rejects it outright in seed content -- so a line like `API_KEY = "..."` (or
`token:`, `password=`, `credential:`, etc., each followed by a value) trips
the same guard whether it's real or a deliberately fake demo value. There is
no override flag for this, by design: fix the seed, don't work around the
check. The rewrite above still describes exactly the same reviewable
problem -- a hardcoded credential-shaped literal, returned from a function
whose name and docstring make its purpose clear -- it just avoids the
specific `keyword` + `:`/`=` + `value` shape the guard looks for. The same
rule applies to prose, not just code: `SKILL.md`'s original text said "looks
like a credential: an API key," and `credential:` followed by a word tripped
the identical guard when the skill was staged into the worktree. That's why
the version above reads "a credential -- an API key" instead.

### Step 4: write the prompt

Never name the skill in the prompt -- staging it (or not) has to be the
*only* variable between conditions, or the comparison is meaningless before
it starts. If the actor must produce structured output, spell out the exact
schema; don't assume it can infer a project-specific contract.

````markdown
# Prompt

Review the change in `changed/config_loader.py` as if it were a pull
request diff against `src/config_loader.py`.

Write your review to `review.json` at the repository root, matching this
shape exactly:

```json
{"findings": [{"location": "path:symbol", "summary": "one sentence"}]}
```

Do not modify any other file. Include one findings entry per problem you
noticed in the change; if you see nothing worth flagging, write
`{"findings": []}`.
````

Writing structured output to a file (`review.json`) rather than only
printing it is the pattern every task in this repository uses -- it's what
a verifier or `checks.json` actually reads back.

### Step 5: write `checks.json`

A task declares exactly one of `verifier.json` (a hand-written script,
useful when nothing built-in fits) or `checks.json` (a declarative list of
built-in checks) -- never both. Four check types cover almost everything:

| Type | Checks |
|---|---|
| `json_field_equals` | One field in a JSON file equals an expected value |
| `finding_matches` | Some entry in a findings list mentions both a location and one of several keywords |
| `files_unchanged_except` | Nothing changed outside an explicit allow-list |
| `command_succeeds` | An arbitrary command exits `0` (escape hatch, e.g. "the test suite still passes") |

For this task:

```json
{
  "schema_version": 1,
  "checks": [
    {
      "type": "files_unchanged_except",
      "except": ["review.json"]
    },
    {
      "type": "finding_matches",
      "file": "review.json",
      "field": "findings",
      "location_contains": "config_loader.py",
      "any_keyword": ["hardcoded", "credential", "secret", "environment variable"]
    }
  ]
}
```

`finding_matches` builds its search text from each entry's `location`,
`summary`, and `category` fields (in that order) -- match your prompt's
requested field names to these, or the check will never find anything to
match no matter what the actor writes.

### Step 6: write the rubric

The judge never sees the worktree or the actual code -- only `rubric.md`
and the captured evidence (the actor's output, the diff, checks stdout).
Every criterion must be answerable from that evidence alone:

```markdown
# Rubric

- **C1 -- Flagged the hardcoded value.** Does at least one finding identify
  `_STATIC_VALUE` in `config_loader.py` as a hardcoded credential?
- **C2 -- Recommended a fix.** Does the review suggest moving the value to
  an environment variable or a secrets manager, rather than just noting it
  exists?
```

### Step 7: tag it

```json
{
  "schema_version": 1,
  "name": "seeded-hardcoded-api-key",
  "description": "A changed file introduces a hardcoded API key literal; a competent review should flag it and recommend moving it to configuration.",
  "skill": "flag-hardcoded-secrets",
  "category": "security",
  "actor_timeout_seconds": 600,
  "judge_timeout_seconds": 300
}
```

`"skill"` and `"category"` are both required -- without them the task can't
be discovered by `codev eval benchmark run <skill>` at all.

## Testing your task, start to finish

This is the part a lot of guides skip, and it's the part that actually
matters: a task you haven't tested is a task you don't know works.

### Test it for free, before spending any real model budget

`--agent <path>` swaps out the resolved OpenCode executable for any script
that speaks the same protocol -- a real actor invocation, minus the actual
model call. Here is a complete, working one (the exact script used to
produce every result below):

```python
#!/usr/bin/env python3
"""Zero-cost stand-in for a real OpenCode actor/judge, for testing plumbing.

Reacts to whether .agents/skills/flag-hardcoded-secrets is discoverable in
the worktree it's run against -- the same signal a real agent would use --
instead of a hardcoded pass/fail, so it genuinely exercises the with/without
staging behavior rather than faking a result by condition name.
"""

import json
import sys
from pathlib import Path

argv = sys.argv[1:]
prompt = argv[-1] if argv else ""

if "Review rubric" in prompt:
    # Judge call.
    verdict = {
        "schema_version": 1,
        "verdict": "pass",
        "summary": "The review identified the hardcoded credential and "
        "recommended moving it to configuration.",
        "findings": [
            {"criterion": "C1", "verdict": "pass", "evidence": "review.json"},
            {"criterion": "C2", "verdict": "pass", "evidence": "review.json"},
        ],
    }
    print(json.dumps(verdict))
    sys.exit(0)

# Actor call: --dir <worktree> is always present for a real invocation.
worktree = Path(argv[argv.index("--dir") + 1])
skill_present = (worktree / ".agents" / "skills" / "flag-hardcoded-secrets").is_dir()

if skill_present:
    findings = [
        {
            "location": "changed/config_loader.py:_STATIC_VALUE",
            "summary": "Hardcoded credential; move it to an environment "
            "variable instead.",
        }
    ]
else:
    findings = []  # A generic reviewer with no security-review skill misses it.

(worktree / "review.json").write_text(
    json.dumps({"findings": findings}), encoding="utf-8"
)
event = {"type": "text", "part": {"text": "Reviewed the diff; see review.json."}}
print(json.dumps(event))
```

Two things worth understanding about why this script is shaped this way,
not just what it does:

- It is invoked exactly the way a real actor would be:
  `<agent> run --format json --dir <worktree> <prompt>`. A judge call is the
  same shape, but the prompt is CoDev's own fixed judge instructions (which
  always contain the words "Review rubric"), not your task's prompt -- that
  substring is the only signal you get to tell the two calls apart.
- It decides what to find by actually checking whether the skill directory
  is present in the worktree it was handed, rather than by branching on
  `--baseline`/no-`--baseline` directly. That distinction matters: it means
  this stub genuinely exercises the real staging mechanism (whatever
  `_stage_skill` did or didn't copy), instead of assuming the harness
  staged correctly and just declaring victory.

Make it executable and point at its **absolute** path -- a relative path
like `./fake-agent.py` fails to resolve once the harness changes into the
isolated worktree as its working directory. (Real mistake #2, also hit
while writing this: the first attempt used a relative path and failed with
`could not launch ./fake-agent.py`.)

```shell
chmod +x fake-agent.py
AGENT="$(pwd)/fake-agent.py"
```

### Prove it actually discriminates

Run both conditions. A task that passes both ways, or fails both ways, is a
tautology -- it tells you nothing about whether the skill helps.

```shell
codev eval task run seeded-hardcoded-api-key --target . --output ../evidence-baseline --agent "$AGENT" --baseline
codev eval task run seeded-hardcoded-api-key --target . --output ../evidence-with-skill --agent "$AGENT"
```

Real output:

```text
Evaluation failed: ../evidence-baseline
Evaluation passed: ../evidence-with-skill
```

Read either one back without hand-parsing JSON:

```shell
codev eval report ../evidence-baseline
```
```text
Task: seeded-hardcoded-api-key
Outcome: failed
Actor: completed
Verifier: failed
Judge: skipped
```
```shell
codev eval report ../evidence-with-skill
```
```text
Task: seeded-hardcoded-api-key
Outcome: passed
Actor: completed
Verifier: passed
Judge: passed (pass)
```

The baseline's exact failure reason is in `verifier-stderr.txt` inside its
output directory:

```text
checks[1] (finding_matches): review.json: no entry in findings matches location_contains='config_loader.py' with any of ['hardcoded', 'credential', 'secret', 'environment variable']
```

This is the discrimination you're looking for: without the skill staged,
the stub's own "generic reviewer" branch produces no findings and the check
correctly fails; with the skill staged, it produces the matching finding and
both the check and the judge pass. If your real task doesn't show this gap
-- even with a real model, not just this stub -- the planted problem is
either too easy (anyone catches it unprompted) or too hard (the skill alone
can't reliably prevent it); fix the scenario, not the passing condition.

### Confirm it's discovered as part of a benchmark

Before committing, confirm `codev eval benchmark run` finds the task and
reports cleanly -- still for free, with `--agent` and one repetition:

```shell
codev eval benchmark run flag-hardcoded-secrets --target . --output ../evidence-scoped-check \
  --category security --repetitions 1 --agent "$AGENT"
```

```text
Skill: flag-hardcoded-secrets (1 repetitions)

Category  With-skill    Baseline      Delta
--------------------------------------------
security      100.0%        0.0%   +100.0pp
--------------------------------------------
Overall       100.0%        0.0%   +100.0pp
Full report: ../evidence-scoped-check/benchmark.json
```

A `--category`-restricted run like this one is a deliberate cheap check --
it never writes anything into your skill's own directory (see "Running it
for real," below, for what does).

### Commit it

Once the with/without gap is real, commit the task the same way you'd
commit any other source file -- `.codev/eval/tasks/seeded-hardcoded-api-key/`
in its entirety.

## Running it for real

Everything above used a scripted stub so you could iterate for free. The
real signal -- does this skill measurably help a real model -- needs a real,
authenticated OpenCode and costs real API budget: every trial is a live
actor call, and a passing check adds a live judge call on top. Cost scales
linearly with tasks x conditions x repetitions.

```shell
codev eval benchmark run flag-hardcoded-secrets --target . --output ../evidence-full-benchmark --repetitions 3
```

An **unrestricted** run like this one (no `--category` filter) also writes
the result into the skill's own directory as its eval trace --
`.agents/skills/flag-hardcoded-secrets/evals/benchmark.json` plus a
Markdown rendering at `evals/BENCHMARK.md` -- mirroring NVIDIA
SkillEvaluator's Recommended Artifact Set for a skill package (see
[ADR-0028](../../adr/0028-skill-packages-carry-their-own-eval-trace.md)).
Real output, run with `--agent` again purely so this guide didn't need to
spend live model budget to show you the shape -- the packaging step itself
is identical either way:

```text
Skill: flag-hardcoded-secrets (2 repetitions)

Category  With-skill    Baseline      Delta
--------------------------------------------
security      100.0%        0.0%   +100.0pp
--------------------------------------------
Overall       100.0%        0.0%   +100.0pp
Full report: ../evidence-full-benchmark/benchmark.json
```

Read the packaged trace back at any later point, without needing to find or
keep that `--output` directory around:

```shell
codev eval show flag-hardcoded-secrets --target .
```

```text
Skill: flag-hardcoded-secrets (2 repetitions)

Category  With-skill    Baseline      Delta
--------------------------------------------
security      100.0%        0.0%   +100.0pp
--------------------------------------------
Overall       100.0%        0.0%   +100.0pp

Generated: 2026-08-22T00:32:03.273238+00:00
Trace file: .../.agents/skills/flag-hardcoded-secrets/evals/benchmark.json
```

`evals/BENCHMARK.md`, for browsing the skill folder directly instead of
running a command:

```markdown
# `flag-hardcoded-secrets` -- Evaluation Trace

Generated: 2026-08-22T00:32:03.273238+00:00
Repetitions per task: 2

| Category | With skill | Baseline | Delta |
| --- | --- | --- | --- |
| security | 100.0% | 0.0% | +100.0pp |
| **Overall** | 100.0% | 0.0% | +100.0pp |

Full per-task trial evidence is in `evals/benchmark.json` (this table's
underlying data) and in the `--output` directory passed to
`codev eval benchmark run` when this trace was generated.
```

Two flags worth knowing about here:

- `--no-package` skips writing into the skill's directory entirely -- use
  it for a scratch run against a target you don't want written to.
- `--category` (as used above, for the free discovery check) *never*
  packages, even without `--no-package` -- a partial run's trace would
  silently overwrite a fuller one and misstate the skill's real coverage.

Both `evals/benchmark.json` and `evals/BENCHMARK.md` are generated, not
hand-authored -- treat them as build output, regenerated by the next full
benchmark run, not something to hand-edit.

## Troubleshooting

- **`codev: secret-like content is not allowed: <path>`** -- your seed (or a
  staged `SKILL.md`) contains text matching `keyword` + `:`/`=` + `value`
  for one of: `password`, `passwd`, `token`, `secret`, `credential`,
  `api_key`/`api-key`, `authorization`, or an AWS key-shaped name. Rewrite
  the sentence or literal to avoid that exact shape (see "Real mistake #1"
  above) -- there is no bypass flag.
- **`could not launch <agent>`** -- you passed a relative `--agent` path;
  use an absolute one (see "Real mistake #2" above).
- **`codev: no tasks found for skill: <name>`** from `benchmark run` --
  check `task.json`'s `"skill"` field for a typo; it must match exactly.
- **A task passes in both conditions, or fails in both** -- it isn't
  measuring anything (see "Prove it actually discriminates" above). Adjust
  the seeded scenario, not the passing condition.
- **`codev eval doctor` reports a failing row** -- install or authenticate
  whatever it names; nothing past that point will work correctly with a
  missing `git` or `opencode`.

## Where to go next

- [README.md](README.md) -- the full architecture and flag reference this
  guide is a companion to.
- The `design-skill-eval` skill -- the same workflow above, but interactive:
  invoke it directly if you'd rather be walked through the decisions
  (ground truth, category naming, checks vs. verifier) than follow a
  written guide.
- [../skill-eval-ergonomics/design.md](../skill-eval-ergonomics/design.md)
  -- the full engineering contract (schemas, validation rules, the Docker
  sandbox option) behind every command used here.
- [ADR-0027](../../adr/0027-opt-in-docker-sandbox-for-the-native-eval-harness.md)
  -- if your task needs stronger isolation than a host worktree.
- [ADR-0028](../../adr/0028-skill-packages-carry-their-own-eval-trace.md)
  -- the packaged eval trace and `codev eval show` used above.
