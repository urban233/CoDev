# NVIDIA SkillEvaluator engine

**Status:** Accepted
**Owner:** CoDev maintainers

## Problem

CoDev's local skill-evaluation harness (`codev eval fixture|run|snapshot`,
see [`../skill-eval/brief.md`](../skill-eval/brief.md)) answers one narrow
question well: does an actor's attempt at one hand-written fixture pass a
deterministic verifier and a rubric judge. It does not check a skill
directory itself for schema/security/PII/license problems, does not detect
duplicated guidance across skills, and does not produce the kind of
dimensional, cross-agent live-evaluation report a external reviewer might
expect. NVIDIA's SkillEvaluator (https://docs.nvidia.com/skills/skillevaluator)
is a maintained, three-tier tool that already does these things for the
public Agent Skills format CoDev's own skills use.

## Outcome

A developer can run `codev eval nvidia <verb>` to invoke the externally
installed `skillevaluator` CLI against a skill directory and get the same
kind of durable, atomically-published evidence bundle the native harness
already produces -- without CoDev reimplementing any of SkillEvaluator's
checks, scoring, or live-evaluation logic itself.

## First-release scope

- A thin subprocess wrapper (`codev_workflow.eval_nvidia`) around the
  externally installed `skillevaluator` executable, covering its Tier 1
  (static/security/quality), Tier 2 (dedup), and introspection
  (`doctor`/`health-check`/`models`) commands, plus Tier 3's `evaluate` and
  `validate` aliases.
- `codev eval nvidia <verb> [TARGET] --output DIR [--extra FLAG]...`,
  mirroring SkillEvaluator's own verb names one-to-one rather than inventing
  new vocabulary.
- A small, engine-agnostic `engine-result.json` envelope recording strictly
  the *process* outcome (exit code, duration, timeout), published atomically
  alongside SkillEvaluator's own native report file(s) and captured,
  redacted stdout/stderr, using the native harness's existing commit-marker
  convention.
- Explicit, printed notices -- never silent attempts, never CoDev-managed
  credentials or containers -- whenever a verb may exercise SkillEvaluator's
  live-agent (Tier 3) path, which needs an agent CLI credential and a
  sandbox.

## Non-goals

- Reimplementing, re-scoring, or reinterpreting any SkillEvaluator finding;
  its native report is the source of truth, this wrapper only makes it
  reproducible and evidence-durable from CoDev.
- A shared behavioral interface with the native OpenCode-based harness. The
  two tools score different things (one actor's fixture attempt vs. a skill
  directory's own quality); see
  [`../../adr/0026-external-evaluation-engines-are-thin-subprocess-wrappers.md`](../../adr/0026-external-evaluation-engines-are-thin-subprocess-wrappers.md).
- CoDev provisioning, storing, or forwarding credentials, or provisioning
  Docker/sandbox infrastructure, on the user's behalf.
- Wrapping SkillEvaluator's `create-eval-dataset`, `init-custom-grader`,
  `init-harbor-task` (which intentionally write into the target skill
  directory, not an isolated output directory) or `view`/`harbor-view`
  (interactive viewers); see design.md for why.
- Pinning or vendoring the `skillevaluator` package itself; it remains an
  externally installed, externally authenticated executable, exactly like
  OpenCode is for the native harness.

## Evidence of value

- `codev eval nvidia quality-check <skill> --output <dir>` produces a
  `passed`/`failed` envelope plus SkillEvaluator's own native JSON report,
  reproducibly, without a developer needing to remember SkillEvaluator's own
  report-directory flags.
- Running the same verb twice against an unmet Tier 3 precondition (missing
  Docker, missing credential) fails fast with a clear, printed explanation
  rather than hanging or silently degrading.
- Every run's evidence is atomically published or not published at all, the
  same durability guarantee the native harness already gives.

## Constraints

- Never store, print, or persist SkillEvaluator's credentials; forward only
  a curated, explicitly named set of environment variables.
- Never mutate the target skill directory; every wired verb writes
  exclusively into the caller's `--output` directory.
- `skillevaluator` has no pinned PyPI release (git-install only); CoDev's own
  documentation pins a specific verified commit rather than tracking
  upstream's default branch.
- V1 is verified on macOS against the pinned commit; Windows/Linux
  compatibility is deferred risk, matching the native harness's own V1
  posture.
