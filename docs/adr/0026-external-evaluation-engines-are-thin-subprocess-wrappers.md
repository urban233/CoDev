# ADR-0026: External evaluation engines are thin subprocess wrappers

**Status:** Accepted
**Date:** 2026-08-21
**Owner:** CoDev maintainers
**Related design:** [../features/nvidia-skill-evaluator/design.md](../features/nvidia-skill-evaluator/design.md)

## Context

CoDev's local skill-evaluation harness (`codev eval fixture|run|snapshot`,
[../features/skill-eval/design.md](../features/skill-eval/design.md)) scores
one actor's attempt at one hand-written fixture: a fixed
`passed|failed|error` outcome plus an isolated judge verdict, produced by
driving OpenCode through a temporary Git worktree.

Adding NVIDIA's SkillEvaluator (https://docs.nvidia.com/skills/skillevaluator)
as a second evaluation engine raised a durable question this ADR settles once
so it does not get re-litigated per engine: when CoDev wraps an external
evaluation tool, does it conform that tool to a shared behavioral interface
with the native harness, or does it only share lower-level infrastructure?

SkillEvaluator scores a *skill directory* itself, across three tiers
(deterministic static/security checks, embedding-based dedup, live
with/without-skill agent runs), producing multi-dimensional scores, "Skill
Lift," and pass@k -- not a fixed pass/fail/judge-verdict shape. Any future
third engine is likely to differ from both existing ones in its own way, for
the same reason: external evaluation tools are built around what they
evaluate, not around CoDev's internal contract.

## Decision

An external evaluation engine wrapper:

- **Shares infrastructure with the native harness**: subprocess execution
  (`run_process`), curated environment isolation (`isolated_subprocess_env`),
  atomic evidence publication with the existing commit-marker convention
  (`publish_result_bundle`), captured-output redaction
  (`redact_process_text`), and the `EvaluationError` type -- all exposed as a
  small, stable, non-underscore surface on `codev_workflow.eval` that
  existing internals delegate to unchanged.
- **Never shares a behavioral Protocol** (e.g. one `run(request) -> result`
  contract) with the native harness or with any other engine. Each engine's
  CLI verbs and native result shape mirror the tool it wraps; CoDev does not
  invent a unified vocabulary that would have to either leak that tool's
  concepts into a "thin" interface or flatten its actual output to fit a
  shape it does not have.
- Publishes a minimal, engine-labeled envelope (e.g. `engine-result.json`)
  recording strictly the wrapped tool's own *process* outcome (exit code,
  duration, timeout) -- never a CoDev reinterpretation of the tool's
  findings or scores, which always live in that tool's own captured native
  report.
- Never introduces a central engine registry, dispatch dict, or plugin base
  class speculatively. `cli.py`'s subparser tree is registry enough for two
  engines with no shared dispatch consumer; add real structure only when a
  second consumer actually needs it.

## Alternatives considered

- **One shared behavioral Protocol, one class per engine:** rejected. Forces
  every wrapped tool's output through a lowest-common-denominator shape or
  leaks its vocabulary into the "shared" interface. Neither is honest once a
  wrapped tool's unit of evaluation differs from a fixture.
- **A speculative `ENGINES = {name: class}` registry:** rejected for now.
  Nothing in this codebase dispatches on an engine name today; `cli.py`'s
  existing subparser tree already plays that role for `fixture`/`run`/
  `snapshot`, and for `nvidia`.
- **Retrofitting the native harness's `result.json` schema onto the new
  engine (or vice versa) for symmetry:** rejected. `result.json` is an
  already-Accepted, documented contract; renaming or reshaping it for
  symmetry with a new engine is a gratuitous breaking change with no
  functional payoff.

## Consequences

- Adding a third external evaluation engine should reuse the same four
  `eval.py` wrappers and the `EvaluationError` type, and should expect to
  define its own verb surface and its own envelope-adjacent native report
  capture, not conform to an engine Protocol that does not exist.
- Two independently-shaped result artifacts (the native harness's
  `result.json` and each external engine's own envelope name) are an
  accepted, permanent asymmetry, not a gap to close later.
- If a future engine's own CLI turns out to be genuinely fixture/verdict
  shaped (unlike SkillEvaluator), revisit whether a real shared behavioral
  interface would then add value -- this decision is scoped to "engines with
  a genuinely different unit of evaluation," not to every possible future
  engine.

## Revisit when

A third external evaluation engine is proposed whose native unit of
evaluation and result shape are close enough to either existing engine that
a shared behavioral interface would stop being a flattening exercise and
start being a real simplification.
