# ADR-0042: The oracle becomes the navigator, and answers for the whole lifecycle

**Status:** Accepted
**Date:** 2026-09-03
**Owner:** Martin Urban
**Related design:** [docs/plans/developer-experience-implementation.md](../plans/developer-experience-implementation.md)
**Extends:** [ADR-0036](0036-cli-is-an-agent-interface.md)

## Context

ADR-0036 rule three made phase-boundary guidance computed rather than
conventional, and called the module that computes it the oracle. Two problems
emerged from using it.

The name invited the reading that the answer is unexplained, which is the
opposite of what a module returning a `reason` with every answer is for. And
its coverage was narrower than the name suggested: it answered for the build
phases and collapsed every state before a task existed into one sentence, so
the entire Understand, Design and Plan half scored as unguided -- the half
where a developer has the least context and the most to decide.

## Decision

**The oracle is the navigator**, after the half of a driver/navigator pair
without hands on the keyboard. In a `pair` slice (ADR-0038) the metaphor is
literal. `guidance` and `workflow` were considered; an agent consults a
navigator but merely reads guidance, and `workflow` collides with the package
name.

**It answers for the planning phases**, resolving brief, design, wave plan and
plan from the artifacts a repository holds, and reading the `Status:` line
those artifacts already carry -- the same convention `gate.py` relies on, so no
new metadata format. A plan that declares no accepted status is reported as
blocking its own downstream work, because recommending work nothing authorizes
is worse than naming what is missing.

**A blocked position carries options.** Each is a label, a command, and what
choosing it means. No authority moves -- choosing stays a human's job -- but a
stop that offers "absorb the change as pair work" beside "escalate" is a
decision rather than a wall, and every one of those escapes already existed.

**GitHub is consulted for any position where a pull request could exist**, not
only the two check reasons that imply human review. The old restriction is why
a merged slice was told to open a pull request it had already merged.

**`ok_waiting_on_reviewer` is split into the three states it conflated.**
`task.check` cannot tell a freshly opened round from one whose builder has
reported, so the single entry recommended the reviewer even before any work
existed -- an agent that follows it reviews an empty diff.

**A draft pull request is not reported as awaiting human review.** Nobody can
review a draft; `mark-ready` is what requests it.

## Alternatives considered

- **Keep the oracle name and only widen coverage.** Rejected: the rename is
  cheap, mechanical, and CoDev's stated posture is that a name needing a
  paragraph of explanation is a defect in a tool whose problem is that it
  lacks a legible mental model.
- **A new front-matter field for artifact acceptance.** Rejected: the
  `Status:` line already exists and is already load-bearing.

## Consequences

- Navigator coverage falls from six uncovered steps of nine to zero of eight.
- `NextAction` gains `options`; `blocked` is unchanged, because something
  reads it and it is part of the machine contract.
- ADR-0036's "oracle" language reads as history. This ADR is its forward
  pointer; ADRs are append-only and it is not edited.
