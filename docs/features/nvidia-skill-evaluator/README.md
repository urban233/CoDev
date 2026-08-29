# NVIDIA SkillEvaluator engine

`codev eval nvidia <verb>` runs the externally installed NVIDIA
SkillEvaluator CLI (https://docs.nvidia.com/skills/skillevaluator) against a
skill directory and publishes the result as a durable evidence bundle, using
the same atomic commit-marker convention as the native fixture harness (see
[`../skill-eval/README.md`](../skill-eval/README.md)). It is a second,
independent evaluation engine, not an extension of that harness -- see
[design.md](design.md) and
[`../../adr/0026-external-evaluation-engines-are-thin-subprocess-wrappers.md`](../../adr/0026-external-evaluation-engines-are-thin-subprocess-wrappers.md)
for why.

Where the native harness answers "does an actor use this skill well on a
task," this engine answers a different question: "is the skill directory
itself well-formed" -- schema-valid, free of obvious security/PII/secrets
issues, well-documented, non-duplicative.

## Usage

General shape:

```shell
codev eval nvidia <verb> [SKILL_PATH] --output DIR [--extra FLAG]...
```

`--output` must be an existing, empty directory; `codev eval nvidia` never
writes into `SKILL_PATH` itself. `--extra` is repeatable and forwarded
verbatim, in order, to `skillevaluator` after CoDev's own flags -- the
escape hatch for every flag this wrapper does not model by name (`--full`,
`--llm`, `--tiers`, `-a/--agents`, `--env-mode`, and everything else in
`skillevaluator <verb> --help`). **Use `--extra=VALUE` (with `=`, not a
space) whenever `VALUE` itself starts with `-`** -- e.g.
`--extra=--llm`, or `--extra=--env-mode --extra=docker` (two flags) /
`--extra=--env-mode=docker` (one, glued) for a value that also needs a
value of its own. Every verb below is a real, registered command; none are
placeholders.

| Tier | Verb | What it does |
|---|---|---|
| 1 | `validate` | Tier 1 (always) + Tier 2 (default-on) + optional Tier 3, in one run; the umbrella command |
| 1 | `quality-check` | Correctness/discoverability/reliability/efficiency scoring |
| 1 | `rubric-eval` | LLM-as-judge rubric scoring (needs an LLM credential) |
| 1 | `security-scan` | Security vulnerability scan |
| 1 | `pii-scan` | PII / local-identifier scan |
| 1 | `lint-scripts` | Advisory lint on the skill's scripts |
| 2 | `similarity-check` | Cross-skill duplicate detection over a *collection* (a folder of multiple skills, not one skill) |
| 2 | `context-optimization-check` | Intra-skill redundancy detection, one skill at a time |
| 2 | `dedup-scan` | Alias/variant of the intra-skill redundancy check |
| -- | `compare` | Compare prior live-evaluation results across agents |
| -- | `doctor` | Full live-evaluation runtime readiness report (no target path) |
| -- | `health-check` | Quick readiness check, same idea as `doctor` (no target path) |
| -- | `models` | List the configured provider's authenticated model catalog (no target path) |
| 3 | `tier3 evaluate` | Live agent evaluation, with and without the skill |
| 3 | `tier3 validate` | Validate an existing `evals/` directory and optional Harbor BYOT contract |

Not wired into `codev eval nvidia` at all: `create-eval-dataset`,
`init-custom-grader`, `init-harbor-task` (these intentionally write into the
target skill directory itself, a different contract than "everything lands
in `--output`") and `view`/`harbor-view` (open an interactive browser
viewer). Run `skillevaluator` directly for those. See design.md's
Alternatives table for why.

For a complete, real, tier-by-tier worked run against one actual skill --
including exactly what Tier 2 and Tier 3 need to move past "not
configured" -- see
[walkthrough-audit-google-python-style.md](walkthrough-audit-google-python-style.md).
For the step-by-step guide to actually getting Tier 1, 2, *and* 3 all fully
working (what to install, in what order, and how to verify each stage), see
[setup-guide.md](setup-guide.md). For short, focused recipes on individual
tasks (installing Docker, setting environment variables, using your own
OpenCode installation as the Tier 3 agent, and so on), see
[how-to.md](how-to.md).

## Prerequisites

Install SkillEvaluator itself (no pinned release exists upstream, so this
pins a specific verified commit):

```shell
uv tool install --python 3.13 "skillevaluator[all] @ git+https://github.com/NVIDIA/SkillEvaluator.git@e70f0e3ee68bb72d8cf68178a7d4fa2052bc1433"
```

Three of Tier 1's checks depend on separate scanners SkillEvaluator does not
bundle. Without them, `validate` still runs and still gates on them by
default (see "Reading a `failed` result" below) -- install them too if you
want those three checks to actually complete rather than report
`"incomplete"`:

```shell
uv tool install git+https://github.com/NVIDIA/SkillSpector.git   # Security Scan
uv tool install semgrep                                          # Code Risk Analysis
# Gitleaks has no PyPI package, so there is no uv tool install option for
# it -- use whatever your system uses for a Go-built CLI binary: your
# package manager (Homebrew, apt, a declarative manager like nix-darwin/
# NixOS, ...), or `go install github.com/gitleaks/gitleaks/v8@latest`.
```

See [setup-guide.md](setup-guide.md) for a full walkthrough of installing
all three and the real before/after result on `audit-google-python-style`.

CoDev never installs any of this for you and never stores credentials on
your behalf -- see [design.md](design.md)'s Quality and Risk section.

## Example: auditing `audit-google-python-style`

Any bundled or project-local skill directory works; this uses CoDev's own
`.agents/skills/audit-google-python-style/` since it is a real skill you
already have if you have CoDev installed.

```shell
mkdir -p ../skill-evidence/audit-google-python-style
codev eval nvidia validate .agents/skills/audit-google-python-style \
  --output ../skill-evidence/audit-google-python-style
```

On a machine without SkillSpector/Semgrep/Gitleaks installed, this is what a
real run actually produces (trimmed):

```text
Note: 'skillevaluator validate' may exercise NVIDIA SkillEvaluator's
live-agent (Tier 3) path, which needs an agent CLI credential and a sandbox
(Docker by default). CoDev does not provision or store either -- configure
your own environment before this succeeds.

╭─ Tier 1 · Static & Security ─────────────────────────────────────────────╮
│  summary   7/11 passed  ·  4 failed  ·  5 warnings                       │
│  ✗ failed  Schema & Repository Governance — Author not specified        │
│  ✗ failed  Security Scan                                                │
│  ✗ failed  Code Risk Analysis                                           │
│  ✗ failed  Secrets Detection                                            │
│  quality   B  81.5 / 100                                                │
╰─────────────────────────────────────────────────────────── ✗ fail · 0.5s─╯

Evaluation failed: ../skill-evidence/audit-google-python-style
```

(The Tier 3 notice above prints for every `validate` call, whether or not
`--tier3`/`--full` is actually requested -- see design.md's CLI Behavior
table for why this wrapper prints it unconditionally rather than only "the
first time.")

### Reading a `failed` result

`../skill-evidence/audit-google-python-style/engine-result.json` records
strictly the process outcome (this is the real, complete file from the run
above, path shortened for width):

```json
{
  "schema_version": 1,
  "engine": "nvidia-skillevaluator",
  "verb": "validate",
  "target": {
    "kind": "skill_directory",
    "path": ".../.agents/skills/audit-google-python-style"
  },
  "process": {
    "exit_code": 1,
    "duration_seconds": 0.863,
    "timeout": false
  },
  "outcome": "failed",
  "summary": "skillevaluator validate exited 1",
  "artifacts": {
    "stdout": "nvidia-stdout.txt",
    "stderr": "nvidia-stderr.txt",
    "report:BENCHMARK.md": "native-report__BENCHMARK.md",
    "report:skillevaluator-output-20260821203006.json": "native-report__skillevaluator-output-20260821203006.json"
  }
}
```

`exit_code: 1` here is *not* four genuine problems -- it is one real finding
plus three checks SkillEvaluator could not complete. Open the captured
native report (`native-report__skillevaluator-output-<timestamp>.json` in
the same directory) and check each failed validator's `status` field, not
just its `passed` boolean:

- **`Schema & Repository Governance` -- a real, fixable finding:** `status:
  "failed"`, with an actual `findings` entry: `"Author not specified in
  metadata"` (plus two lower-severity missing-section advisories). This is
  a genuine gap in `audit-google-python-style/SKILL.md`'s frontmatter.
- **`Security Scan` / `Code Risk Analysis` / `Secrets Detection` -- not
  findings at all:** each has `status: "incomplete"` and an *empty*
  `findings` array. Their own `legacy.warnings` say why: `"skillspector not
  installed"`, `"semgrep not installed"`, `"gitleaks not installed"`.
  SkillEvaluator's own gating still treats an incomplete Tier 1 check as
  blocking by default, which is why the overall run still exits 1. This is
  a real, empirically observed sharp edge, documented in
  [design.md](design.md)'s Quality and Risk section rather than glossed
  over: **a stock `validate` run will fail this way on almost any skill
  until all three extra scanners are installed.**

Tier 2 (embedding-based dedup) shows as `skipped`, not failed, in the same
run -- with no embeddings credential configured
(`SKILL_EVAL_EMBEDDING_PROVIDER`/`NVIDIA_API_KEY`/`OPENAI_API_KEY`),
SkillEvaluator degrades gracefully there instead of blocking, which is a
deliberate difference from Tier 1's stricter gating (see design.md's
Compatibility spike findings).

### A narrower, faster check

If you only want the one real, fixable finding without the three
scanner-dependency noise, run a narrower Tier 1 verb instead of the full
`validate` umbrella:

```shell
mkdir -p ../skill-evidence/audit-google-python-style-schema
codev eval nvidia validate .agents/skills/audit-google-python-style \
  --output ../skill-evidence/audit-google-python-style-schema \
  --extra=--checks=schema,pii,license,unicode,quality,lint
```

(confirmed by running it: `security` is the check name behind Security
Scan/SkillSpector; `code-integrity` is behind both Code Risk
Analysis/Semgrep and Secrets Detection/Gitleaks. Omitting a check name from
`--checks` skips it entirely rather than reporting it incomplete. Remember
the `--extra=VALUE` form, not a space, whenever the forwarded value itself
starts with `-`.)

## See also

- The native harness's own worked example for this same skill --
  `.codev/eval/tasks/audit-google-python-style-phase-a/` and its
  `-phase-b` sibling, exercised via `codev eval task run`/`codev eval
  benchmark run` -- tests whether an *actor* uses this skill correctly on a
  task, a different question from this engine's "is the skill directory
  itself well-formed." See
  [`../skill-eval/README.md`](../skill-eval/README.md).
- [brief.md](brief.md) and [design.md](design.md) for the full contract,
  scope, and known gaps.
