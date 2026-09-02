# Architecture

## Purpose

CoDev separates workflow maintenance from workflow use. The canonical bundle
lives in this project; agents consume ordinary, repository-local files in each
software project. CoDev's install, update, and remove machinery never runs
while product code is being built. The `codev task` lifecycle commands are the
one exception: they may run during a build session, are strictly read-only
with respect to product source, and only read or write their own state under
`.codev/task/` (see [ADR-0001](adr/0001-work-lifecycle-invariant.md) and
[ADR-0023](adr/0023-work-item-renamed-to-task.md)).

```text
CoDev source -> versioned Python package -> explicit CLI command -> target repo
       |                                                    |
       +---- tests and behavioral evaluations               +---- local agent discovery
```

## Components

### Bundle

`src/codev_workflow/bundle` mirrors target-relative paths. It contains the
skills, and the OpenCode, Junie, Antigravity, and Claude Code agents,
documentation, validators, and evaluation catalog. Junie and Antigravity
carry a single narrow-tier `assistant` agent rather than the full workflow
(ADR-0031); OpenCode and Claude Code carry the complete role set.
The installer's runtime file walk (`importlib.resources`) and the Bazel
`glob(["bundle/**"])` both discover a new bundled file automatically; the
setuptools sdist build does not -- `pyproject.toml`'s
`[tool.setuptools.package-data]` is an explicit glob list per bundle
subdirectory and needs its own new entry for a new bundled path or file type.

Every bundled skill carries a `skill-card.md` alongside its `SKILL.md` --
owner, license, use case, dependencies, and known risks, filled out with real
facts rather than left as a template placeholder -- and a `license`
frontmatter field on `SKILL.md` itself. See
`docs/adr/0029-adopt-skill-cards-and-license-metadata.md`.

`AGENTS.md` and `.opencode/opencode.json` are integrations rather than copied
files. CoDev owns one marked block in `AGENTS.md` and selected missing values
in OpenCode configuration, preserving all project-owned content. Junie's
`assistant` agent is an ordinary managed Markdown file under
`.junie/agents/`, while Antigravity's uses its official `.agents/agents/`
location alongside CoDev's `.agents/skills/` directory. Claude Code agents
use its official `.claude/agents/` location; unlike Antigravity, Claude Code
has no configurable skills path, so the shared skills are mirrored into
`.claude/skills/` at install time instead of referenced in place. Claude
Code additionally ships a `.claude/settings.json` and three guardrail hooks
-- a category no other adapter has: `require_plan.py` defaults new sessions
into Plan Mode and pauses for confirmation before the first source edit, or
the first repository-mutating git command, when no design or plan document
exists yet for the active branch (`docs/features/claude-code/design.md`);
`require_wave_shape.py` asks (never denies) when a wave plan's "Later
waves" section already holds a populated task table
(`docs/features/plan-wave/design.md`); `require_small_change.py` asks when
a task's diff exceeds its `review.max_lines`/`review.max_files` budget at
`codev git open-pr` (`docs/features/small-prs/design.md`). All three fail
open on any internal error.

### Installer

The standard-library CLI performs a complete preflight before mutation. It
computes SHA-256 hashes over bundled bytes and records them in
`.codev/lock.json`. Files are written atomically in their destination
directories.

### Lock file

The lock file records schema version, bundle version, selected platforms,
source hashes, and integration state. It is committed to the consumer
repository so CI and other developers observe the same installation.

## Update algorithm

For each managed file, CoDev compares:

1. the source hash recorded at the last successful install;
2. the current target file; and
3. the source file in the running CoDev version.

| State | Action |
|---|---|
| Target matches old source; source changed | Update |
| Target matches new source | Adopt as current |
| Target and source both match old source | Keep |
| Target differs; upstream is unchanged | Report local drift |
| Target differs and upstream changed | Conflict; write nothing |
| New upstream file is absent locally | Add |
| New upstream file collides locally | Conflict; write nothing |
| Upstream removed an old file | Retain locally and stop managing it |

Retaining removed files is conservative: an update cannot unexpectedly delete
repository instructions. The explicit `codev remove` command preflights and
removes only unchanged managed files and integrations; it remains opt-in.

A conflict left unresolved (`--on-conflict skip`, the conflict wizard's
`skip`, or simply no resolution supplied for that path) stays a visible
conflict: `codev status` keeps reporting it as a managed file with local
changes until a real resolution (`override` or `keep`) supersedes it, rather
than the file quietly falling out of management the moment an update chooses
not to touch it. `delete` is the one exception -- it adopts upstream's
removal, so nothing is left to compare a future hash against, and the path
stops being tracked the same way an ordinary upstream removal does.

## Invariants

- Every multi-file change is atomic at the decision level: conflicts prevent
  all planned writes.
- A target repository never imports CoDev as a runtime dependency.
- Provider and model selection remain project-owned.
- Installed instruction changes are reviewable source changes.
- Deterministic checks run without network access or model calls.
- Behavioral model evaluations remain externally observed and separately run.
- `codev task` lifecycle commands are read-only with respect to product
  source; they only mutate their own state under `.codev/task/`
  (see [ADR-0001](adr/0001-work-lifecycle-invariant.md) and
  [ADR-0023](adr/0023-work-item-renamed-to-task.md)).

## The plan gate is risk-tiered

The plan gate asks for a written plan before the first source edit on a task
branch. Keyed purely on a file existing, it asked the same question of a
one-file bug fix and a subsystem rewrite, and ceremony that cannot tell those
apart teaches agents to route around the gate rather than to plan.

It is now tiered, as a changed default rather than a configuration key --
CoDev's answer to "more structure" is a better default, not another knob:

- On a task branch whose recorded slice is **within the size budget**, the
  focus card in the conversation satisfies the gate and no plan file is
  required.
- A change that has **grown past the budget** asks again, on the first edit
  after it crosses.
- Some paths ask **regardless of size**: dependency and environment manifests,
  CI workflow definitions, and migrations. A one-line version bump changes what
  the code computes, which for research software surfaces as an unreproducible
  result rather than an outage; a workflow file decides whether anything is
  checked at all; a migration is irreversible against real data.
- A **repository-mutating git command** is never tiered by size. A push is not
  made safe by the change being small.

The tier reads as a weakening and is not, because of when the gate fires. It
runs *before* an edit, so the only diff it can see is the one already on the
branch. The old gate therefore interrupted before the work started, when a
developer knows least about what the change will need. The tiered one
interrupts when the change outgrows what a focus card can carry, which is when
a written plan is worth its cost. Toll booth to tripwire.

Two things the tier refuses to treat as small: a task whose round state does
not exist, and one whose state carries no base to diff against. Both measure
as zero changed lines, and a measurement of nothing is not a measurement of a
small change -- without that guard any branch merely *named* `codev/...` would
skip the gate. The size is measured in-process for the same reason: shelling
out to `codev task size` made both gates depend on an executable being on PATH
and being the same build.

## Navigator coverage

CoDev's claim about its own developer experience is that a developer directs
work in conversation rather than by typing commands. That claim was asserted
for as long as it existed, because nothing measured it.

**Navigator coverage** is the measure: the number of steps in a complete task
lifecycle where `codev next` does not name the single action that advances the
work. A developer types a command for exactly one reason -- the agent did not
know what to run -- and the agent knows what to run when, and only when, the
navigator tells it (ADR-0036 rule three). Every uncovered step is a step where
the agent must fall back on the procedural prose in its role file.

`tests/test_navigator_coverage.py` walks one single-slice lifecycle against a
real repository and a real remote, asking the navigator before every
transition, and asserts the result against
`tests/navigator-coverage-baseline.json`. A regression fails the build; so does
an unrecorded improvement, so that every gain arrives as a reviewable baseline
edit rather than a silent ratchet. The baseline records a reason per uncovered
step, and a test asserts that the reasons and the uncovered list stay in step
with each other.

The measure is a proxy and the test says so: coverage at zero does not prove a
developer typed nothing, since an agent may still hand a command over and a
human still makes every decision the loop stops for. Zero proves that nothing
in the lifecycle *forces* a developer to supply a command, which is the part
CoDev controls. The definition of a step lives in that module's docstring; a
baseline recorded under a different definition is not comparable.

## Compatibility

Lock schema changes require a migration before managed files are touched.
Bundle behavior follows semantic versioning. Patch releases preserve artifact
contracts; minor releases may add compatible files or behaviors; major releases
may require an explicit migration and review.
