# ADR-0041: The CLI exposes intent, not steps

**Status:** Accepted
**Date:** 2026-09-03
**Owner:** Martin Urban
**Related design:** [docs/plans/developer-experience-implementation.md](../plans/developer-experience-implementation.md)
**Extends:** [ADR-0036](0036-cli-is-an-agent-interface.md)

## Context

ADR-0036 established that the CLI is an agent interface. It did not say how
large a unit that interface should expose, and the answer in practice was
"one git or state operation each" -- which pushed the sequencing into prose.
`orchestrator`'s step 5 was one paragraph containing six commands, four
conditional flags, an issue-existence check, three mutually exclusive linkage
options, a shell-escaping caveat, and a recovery path.

An interface whose correct use requires a twenty-five-line protocol is not an
interface. It is a procedure, and a procedure held in an LLM's working memory
across a long session is where "goes off the rails" comes from.

## Decision

**Every multi-command procedure in a role file becomes one verb.**

- `codev slice begin` -- branch, GitHub issue, and round state.
- `codev round close` -- commit and record the round against the resulting
  head. Named for its caller: only whoever holds commit permission can know
  that head, which is why a builder never records its own round.
- `codev slice publish` -- push and open the draft pull request.
- `codev slice land` -- advance to the next slice, or close the task when this
  was the last.

Every one emits `--json`. Every one composes existing `git_ops` and `task`
functions and adds no state semantics of its own. **The granular verbs stay**,
because recovery paths and mid-session agents still need one step alone.

The test that keeps this honest: a composite verb needing logic that does not
already exist is a new capability in disguise, and belongs in its own change.

## Alternatives considered

- **Document the procedures better.** Rejected: the `--body-file` caveat was
  already documented in two role files, which is the clearest evidence that a
  caveat documented twice is a missing verb.
- **Replace the granular verbs.** Rejected: recovery is exactly when the
  composite is wrong. "Branch exists, no round state" cannot be answered by
  `slice begin`, which creates the branch.
- **A fifth verb, `codev issue draft`.** Rejected during implementation:
  after `slice begin` exists, its only caller is the issue-only short circuit,
  and `codev git issue-create --body-file` already does that job. Adding a
  synonym to delete a caveat is worse than deleting the caveat.

## Consequences

- `_resolve_linkage` has one implementation that both `task start` and `slice
  begin` call, rather than two copies free to drift about when a task may
  exist without an issue.
- The "never pass `--body`" caveat cannot be violated, because `slice publish`
  takes no `--body`.
- Navigator coverage -- the count of lifecycle steps `codev next` cannot name
  -- only moves when this decision and ADR-0042's navigator work land
  together. Verbs nothing recommends are not an improvement.
