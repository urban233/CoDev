**Status:** Accepted
**Owner:** Martin Urban
**Last reviewed:** 2026-08-31

## Problem and users

CoDev's users are its adopters: a developer, or a small team of up to roughly
eight to ten engineers, building a product with AI-agent-driven development
in a repository that has CoDev installed.

`plan-delivery` already names rolling-wave planning as a supported pattern —
its own trigger description says so — and its second step already instructs
detailing the current milestone while keeping later ones coarse. That
instruction is one advisory sentence with no mechanical backing, unlike the
Build phase's plan-first guardrail (ADR-0030), which pauses for confirmation
before an edit proceeds without a plan. Nothing stops `codev git issue-create`
from pushing an issue for a future milestone whose assumptions have not been
tested yet, and nothing forces a look back at those assumptions when a later
milestone's premise turns out to be wrong. This repository has never actually
exercised `plan-delivery` on itself — `docs/codev/delivery/` holds no files —
and it carries a live example of the failure mode this causes:
`docs/plans/phase-6-cleanup-and-promotion.md`, a fully-scoped, four-task plan
for a phase that was deliberately deferred and has sat unrevisited since.

Separately, `build-change`'s task-slicing rule requires every task to be
independently "buildable and useful." That rule fights work with a genuine
engineering dependency order — schema before logic before wiring — and makes
a wave harder to slice than it needs to be: a wave-scoped plan often wants to
land foundation work before any of it is independently valuable on its own.

## Desired outcome

`plan-wave` (renamed from `plan-delivery`) makes rolling-wave planning the
enforced default instead of a documented option a session can skip under
pressure. A session can produce a detailed, ready-to-build task table only
for the current wave; later waves stay coarse outcome statements until their
own turn, and deterministic, ask-posture gates back that mechanically — the
same posture ADR-0030 already established for the plan-first guardrail,
pausing for a human decision rather than silently blocking or silently
allowing drift.

CoDev also defaults every repository to trunk-based development through a
new `git.workflow` config key (`trunk` by default, `feature-branch` as a
fully-supported override), layered through the config system exactly like
the existing `git.pr_base` key (ADR-0013). Under the `trunk` default,
`plan-wave` and `build-change` can slice a wave's tasks along real
engineering-dependency order instead of forcing every task to stand alone,
provided the task states how incomplete work stays contained — tested,
non-breaking, and flag- or config-gated. CoDev prompts for that containment
description; it never ships or manages flag infrastructure itself.

`design-solution` does not change. It already supports amending a design as
implementation reveals new facts, and its handoff already avoids generating
an exhaustive task list — the architecture-design artifact for real
cross-cutting risk stays exactly as rigorous and upfront as it is today.

## Success measures

- `plan-wave` is exercised on this repository at least once, producing a
  real `docs/codev/wave/` artifact.
- No GitHub issue is created for a wave other than the current one without
  an explicit, recorded override reason.
- A wave that closes with an invalidated assumption in a later wave triggers
  a visible revisit, not a silently stale file like
  `docs/plans/phase-6-cleanup-and-promotion.md`.
- At least one real task ships sliced along an engineering-dependency
  boundary under the `trunk` default, rather than forced into an
  artificially self-contained shape.

## Essential scenarios

- A developer with an accepted brief and, where needed, an accepted design
  for a multi-wave feature runs `plan-wave` once per wave. Each run reads
  the repository's current evidence, details only the next wave's tasks,
  and leaves later waves as coarse statements no gate will let become
  GitHub issues yet.
- A session tries to create a GitHub issue for a task in a future wave. The
  issue-creation gate pauses and asks for an explicit reason before
  proceeding, rather than silently allowing it or refusing it outright.
- A team that does not want trunk-based development sets
  `git.workflow=feature-branch` and sees none of the containment-field
  prompts or branch-lifetime guidance the `trunk` default adds — the
  override behaves as a first-class path, not a degraded one.

## First release

### Now

- Rename `plan-delivery` to `plan-wave` across the skill directory,
  description, prose, and storage paths (`docs/codev/delivery/` to
  `docs/codev/wave/`, `delivery-plan.template.md` to
  `wave-plan.template.md`), and in every file that references it, including
  the public docs site. Follow ADR-0023's hard-rename precedent: no dual
  support, and historical ADRs (0004, 0020, 0022, 0023, 0024) stay
  unedited, accurate to their own time.
- Make rolling-wave planning directive inside `plan-wave`'s own steps:
  detail only the current wave, and gate the start of the next wave's
  detail behind a named revisit checkpoint — an evidence check plus a
  bounded hardening pass when the evidence calls for one, in the spirit of
  Shape Up's cool-down between cycles.
- Add deterministic, ask-posture gates: a wave-shape lint confirming a
  future wave's section holds no populated task table, an issue-creation
  wave-boundary check on `codev git issue-create`, and a `plan-wave`
  existence check for multi-milestone work, mirroring ADR-0030's mechanism.
- Add the `git.workflow` config key (`trunk` default, `feature-branch`
  override), resolved through `config.py`'s existing layered resolution
  exactly like `git.pr_base`. No schema version change.
- Make `build-change`'s and `plan-wave`'s task-slicing guidance
  workflow-aware: under `trunk`, a task may split at an
  engineering-dependency boundary instead of only a usefulness boundary,
  provided it states its containment.
- Add an optional containment field to the task issue template
  (`.github/ISSUE_TEMPLATE/task.md`) and the implementation-plan template,
  populated only when a task is not independently standalone under the
  `trunk` default.

### Next

- `codev status` gains a branch-age signal, extending its existing
  WIP-per-owner and changed-file-overlap reporting.
- Whether wave-scoping gets an explicit step classifying a wave's
  uncertainty as requirements-shaped (resolve by building) or
  architecture-shaped (resolve by looping back to `design-solution` before
  committing the wave's task table), or stays implicit judgment under the
  existing risk-level field. Undecided; resolve in `design.md`.
- A gate that cross-references live GitHub issue state through the GitHub
  API or `gh` CLI. The offline, repository-local gates above are the first
  cut; this is a possible later extension, not a commitment.

### Not planned

- The AI-autonomy-spectrum redesign: the `Pair`/`Bounded delegate` work
  styles and the hard separation between `planner` and `orchestrator`
  sessions. Related — it shares the same root cause, agent-judged binary
  switches instead of tunable deterministic knobs — but scoped as a
  separate follow-on effort so this change stays independently reviewable.
- Any change to `design-solution`'s own steps or template.
- CoDev shipping, bundling, or managing actual feature-flag infrastructure
  for a target repository.

## Constraints

- The audience spans a solo developer through roughly eight to ten
  engineers doing AI-agent-driven development. `plan-wave` keeps its
  existing team-profile gate, capability lanes, reviewer-capacity, and
  WIP-limit machinery unchanged — this work narrows the planning horizon,
  not team-coordination support.
- Every new gate defaults to asking and pausing, never a hard refusal,
  matching ADR-0030's established posture.
- The rename touches live, deployed content in `docs-site/` (`examples.md`,
  `onboarding-guide.md`, `tutorials/multi-developer-coordination.md`), not
  only internal bundle and documentation files.
- The containment/flag-guard convention stays a description the human or
  agent writes; it is never an actual dependency injected into a target
  repository, consistent with a target repository never importing CoDev as
  a runtime dependency.
- Independent review and `testing-craft` discipline stay exactly as
  required regardless of wave or workflow style. Defaulting to trunk-based
  development raises how load-bearing that discipline is; it does not
  loosen it.

## Assumptions and discovery

| Assumption | Evidence needed | Owner | Decision point |
|---|---|---|---|
| The wave-shape lint and issue-boundary gate can be built as fully offline, repository-local checks, with no `gh` CLI or network dependency, for the first release | Prototype the wave-shape lint against the current wave-plan template during design | Implementer | Before `design.md` is accepted |
| One `git.workflow` value can cleanly govern both branch-lifetime guidance and task-slicing/containment guidance without needing separate keys | Prototype against one real multi-wave feature during implementation | Implementer | During implementation, before Accepted |
| ~~Whether the requirements-versus-architecture uncertainty classification becomes a named `plan-wave` step~~ | Resolved 2026-08-31: yes, explicit named step | Martin Urban | Resolved |

## Acceptance

- [x] Outcome, scope, non-goals, and success measures accepted by the accountable human.
