# ADR-0027: Opt-in Docker sandbox for the native eval harness

**Status:** Accepted
**Date:** 2026-08-22
**Owner:** CoDev maintainers
**Related design:** [../features/skill-eval-ergonomics/design.md](../features/skill-eval-ergonomics/design.md)

## Context

The native skill-evaluation harness (`codev eval task run`) isolates its
actor by copying a task's seed into a temporary Git worktree on the host
machine. `docs/architecture.md` and the original harness design
(`docs/features/skill-eval/design.md`) treat "no containers" as a deliberate
non-goal, alongside "no API-key/model/provider configuration" -- the harness
was built to run with nothing beyond the developer's own authenticated
OpenCode and a local Git checkout.

Some tasks genuinely need stronger isolation than a host worktree gives:
installing untrusted dependencies, running network-touching code, or simply
wanting defense-in-depth against a misbehaving actor. NVIDIA SkillEvaluator's
Harbor framework (wrapped separately as `codev eval nvidia`, per
[ADR-0026](0026-external-evaluation-engines-are-thin-subprocess-wrappers.md))
already does this for its own Tier 3 live evaluations, giving direct,
first-hand precedent for what a Docker-backed sandbox costs to support
(Docker Compose v2, a user-supplied image, its own readiness checks) and,
just as importantly, what it does not need to cost: CoDev never provisions,
builds, or ships the container image itself.

## Decision

Add a Docker-backed environment as a second, strictly opt-in backend for a
trial's isolation, behind an `Environment` protocol that also covers the
existing (and still default) worktree isolation:

- `WorktreeEnvironment` is the existing `evaluate()` logic, extracted behind
  the protocol with no behavior change. It remains the default; nothing
  about an existing task's behavior changes unless the caller explicitly
  asks for Docker.
- `DockerEnvironment` runs the actor inside a container built from an image
  the *task itself* declares (`task.json`'s optional `environment: {"backend":
  "docker", "image": "..."}` block). CoDev never builds, pulls, or ships that
  image -- the same posture ADR-0026 already established for the NVIDIA
  engine's own Docker requirement.
- Selected per run via `codev eval task run --sandbox docker`, and only
  usable when the task declares an `environment` block; a task with no such
  block cannot be run with `--sandbox docker`, so opting a task into Docker
  is a decision its own author makes, not one a caller can force on a task
  that never asked for it.

## Alternatives considered

- **Docker as the new default:** rejected. Silently reverses the "no
  containers" invariant for every existing task without any of them having
  asked for it.
- **CoDev builds or ships a default image:** rejected. Directly contradicts
  the "never provision infrastructure" posture already established for the
  NVIDIA engine; a maintained image is its own ongoing liability (staleness,
  security patching) this project has deliberately avoided taking on
  elsewhere.
- **A caller-side `--sandbox docker` flag usable on any task, image
  unspecified:** rejected. Without the task itself declaring an image, there
  is nothing to build the container from, and guessing one would be exactly
  the kind of infrastructure provisioning being avoided.

## Consequences

- A task's own `environment` block is the single place that decides whether
  Docker isolation is available for it at all; `--sandbox docker` only
  selects it when already declared.
- A declared image can go stale (missing a dependency, wrong Python version)
  with no CoDev-side detection -- this is surfaced as a doctor-style
  precondition message, not silently swallowed inside a failing container.
- Windows/Linux support for `DockerEnvironment` is deferred risk, the same
  posture the native harness already carries for `WorktreeEnvironment`.

## Revisit when

A task author needs isolation Docker itself cannot provide (e.g. GPU access,
a non-container sandbox already supported by another tool this project
wraps), or Docker's opt-in cost (declaring and maintaining an image) turns
out to be prohibitive enough that a lighter-weight alternative is worth
designing.
