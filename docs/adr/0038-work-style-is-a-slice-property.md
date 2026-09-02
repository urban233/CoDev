# ADR-0038: Work style is a first-class property of a slice, and pair work stays inside the loop

**Status:** Accepted
**Date:** 2026-09-02
**Owner:** Martin Urban
**Related design:** [docs/features/unified-workflow/brief.md](../features/unified-workflow/brief.md)

## Context

CoDev already has the concept this decision formalizes, in two places, and
mechanizes it in neither.

The focus card in `.codev/for-ai/ai-agent-guidelines.md` ends with **Work
style: `Pair` by default, or `Bounded delegate` only for isolated,
well-specified, testable, reversible work that will be independently reviewed
afterward.** It is stated once, before any file is touched, in prose, and
`src/codev_workflow/task.py` has no representation of it. Nothing downstream
behaves differently as a result.

`VALID_ESCALATION_TRIGGERS` (`src/codev_workflow/task.py:87`) includes
`critical_interrupt`. No workflow anywhere in the bundle produces it; the only
reference in the repository is `tests/test_task.py`. It is a vocabulary word
with no producer — a designed concept that was never wired.

The accepted brief records why this matters. A developer directing AI-heavy
work needs some parts of a change built under their hand rather than
delegated: the parts whose correctness they judge personally, which are rarely
the parts a size or risk heuristic would flag. Today the only ways to get that
are to not use the loop for that work, or to interrupt it. Both put the work
outside the evidence trail.

Interruption is worse than unsupported; it is broken. Stopping a running build
leaves files edited, nothing committed, nothing recorded, and the next `codev
task check` reporting `stop_drift`, because the recorded head no longer matches
(`task.py:732`). `task.reopen` performs exactly the mechanical recovery
needed — it re-baselines onto a given head and opens one fresh empty round —
but it is documented for recovering a stuck task, so nothing offers it here.

## Decision

**Work style is a recorded property of a slice**, per
[ADR-0035](0035-slice-is-the-unit-of-execution.md), with two values: `pair`
and `delegate`. It is chosen when a plan is accepted, per slice, and it is
changeable while the slice is open.

**In `pair` style the loop does not dispatch `builder`.** The orchestrator
works with the developer directly in their own session. Everything else is
unchanged: the same rounds are recorded, the same reviewer runs in a fresh
context, the same evidence and coverage land in the pull request, and the same
convergence outcomes apply. Pair mode is a work style the loop supports, not
an exit from it.

That last point is the whole decision. If pair work fell outside the state
machine, the parts of a change a developer cared most about would be the parts
carrying no record — inverting the guarantee CoDev exists to provide.

Three mechanisms follow:

- **Declared critical paths.** A `review.pair_paths` setting, resolved through
  `config.py` alongside `git.workflow` (ADR-0033) and `review.max_lines`
  (`docs/features/small-prs/design.md`), makes "critical to my judgment" a
  declared property of the code rather than a decision requiring a developer
  to be watching. When a slice's scope reaches such a path, the gate stops
  with the ask-and-pause posture ADR-0030 established, the agent explains why,
  and the slice's style becomes `pair` for the remainder of that round.
- **`critical_interrupt` gains a producer.** A developer may interrupt an open
  slice; the interruption is recorded against that trigger rather than
  discovered later as drift.
- **Pause and resume.** Pausing records the partial head; resuming re-enters
  in `pair` style, absorbing any hand-written work into the slice's round
  state. This reuses `task.reopen`'s existing re-baselining rather than adding
  a second path, and the agent offers it on recognizing the state, per
  [ADR-0036](0036-cli-is-an-agent-interface.md)'s guidance obligation, rather
  than waiting to be asked.

Style is chosen in conversation. A developer marking the token-rotation slice
as pair work says so in plain language; they do not type a flag.

## Alternatives considered

- **Keep work style as focus-card prose:** rejected. It has been prose since
  the focus card was introduced and has never changed any behavior, which is
  the evidence that prose is insufficient here.
- **Make work style a task property rather than a slice property:** rejected.
  The unit whose correctness a developer judges personally is one pull
  request's worth of change, not a whole task. A task that is entirely pair
  work is expressible as a task all of whose slices are `pair`.
- **Treat pair work as outside the loop, with no rounds recorded:** rejected,
  and it is the alternative this decision most exists to foreclose. It would
  leave the highest-judgment work with the weakest evidence.
- **Require the developer to intervene in real time rather than declaring
  critical paths:** rejected. An intervention mechanism that assumes the
  developer is watching does not work, because they are not. Declaration is
  what makes the mechanism fire when it is needed.
- **Infer pair-worthiness from risk labels or diff size:** rejected as a
  substitute, though it may be a useful prompt. The judgment being encoded is
  the developer's own, about code they know, and a heuristic that overrode it
  would be wrong in exactly the cases that matter.

## Consequences

- The round-state schema gains a style field per slice, additively, defaulting
  to `delegate` so every existing record reads correctly.
- `orchestrator`'s three-agent protocol acquires a branch: at a `pair` slice
  it skips builder dispatch and works directly, then rejoins at the reviewer
  step. The reviewer's independence is unaffected — it already runs in a fresh
  context and already may not edit.
- A developer pairing with the orchestrator is still the author, not the
  reviewer, for [ADR-0037](0037-human-review-and-ownership-gate.md)'s purposes.
  Pair work does not reduce the independent-approval requirement; if anything
  it is the case where confusing authorship with review is most tempting.
- `review.pair_paths` is a fourth gate reading configuration, and like every
  gate ADR-0030 governs it asks and pauses rather than refusing.
- Closing the interruption hole is a correctness fix, not only a feature: a
  `stop_drift` after a Ctrl-C is a false report about what happened, and it
  currently costs a developer their in-progress work's traceability.
- An adopter who never sets `review.pair_paths` and never marks a slice `pair`
  sees no change in behavior.

## Revisit when

Slices are observed switching style mid-round often enough that a per-round
rather than per-slice record is needed, or `review.pair_paths` proves to fire
so often that developers disable it — which would mean the declaration is
being used as a risk marker rather than as a judgment marker, and the two need
separating.
