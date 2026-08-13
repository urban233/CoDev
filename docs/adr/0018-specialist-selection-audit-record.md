# ADR-0018: Specialist-selection audit record

**Status:** Accepted
**Date:** 2026-08-13

## Context

`outer-loop-runner.md` step 2's numbered 1-5 specialist menu (ADR-0016) is
correctly specified on every platform: present the five specialists, ask
which to run, offer a waiver for anything skipped. A real session's saved
transcript shows the model skipping straight past all of it -- from the CI
gate directly to "I'm proceeding with a fresh five-specialist pass," no menu,
no waiver question, anywhere in the conversation.

This is fundamentally a harness execution-fidelity gap, not a state-machine
one: `codev` has no way to gate *dispatching a subagent* -- that happens
through the harness's own `task`/`invoke_subagent` mechanism, entirely
outside the CLI. No new `check()` outcome or CLI command can force the pause
itself. What a mechanism *can* do is make the omission visible and
structurally present in the permanent record, the same way
`_incomplete_coverage` already prevents a round from silently reaching
`ok_approve` with missing coverage -- after the fact, but durably.

## Decision

`record_reviewer` gains an optional `specialist_selection` field: a small
audit object naming which of the five specialists actually ran this round --
`{"specialists": [...]}`, drawn from a new `SPECIALIST_NAMES` constant,
duplicates rejected. Exposed as `codev work record`'s new `--selection
<file.json>` flag, following the exact `--coverage`/`--findings` JSON-file
pattern already established.

**Deliberately optional, not hard-required, at the `record_reviewer` API
level** -- this is a refinement made during implementation, not the original
framing. `coverage` itself is optional at this same layer
(`_validate_coverage(coverage) if coverage else {}`) despite being at least
as important, which is the direct precedent followed here. The harder reason
is ADR-0010's comment-sourced entry: it records an outer-phase round with
`CHANGES_REQUIRED` while dispatching *none* of the five specialists (findings
come from PR comments directly), and several other legitimate outer-phase
paths -- narrow re-verification of only the categories a triaged finding
touched, a fully-deferred triage round -- don't cleanly map to "the general
five-specialist menu ran." Making the field unconditionally required at
outer phase would have forced every one of those paths, and every existing
test exercising them, to supply a value that doesn't mean anything for that
case. `specialists: []` is a legal, meaningful answer for a comment-sourced
round ("none of the five ran; findings came from comments"); the field
exists to be an honest record of what happened, not to gatekeep every shape
of outer-phase round through one menu.

The actual enforcement is prompt-level, landed together with ADR-0017 and
ADR-0019's own step 1/2 changes in one combined `outer-loop-runner.md` edit
(not part of this ADR's own change): the fresh, full specialist-dispatch
path is instructed to always pass `--selection`, and `adapter.py` requires
the reference appears in the rendered prompt text on every platform.

`codev work log` renders `specialist_selection` when present, immediately
under the reviewer's decision line -- visible in the same audit trail
`triage` and `coverage_waivers` already are, distinctly from `pr_description()`,
which stays free of this kind of process detail per ADR-0014.

## Consequences

- No `ROUND_SCHEMA_VERSION` bump: additive and optional, same precedent as
  every other field added since ADR-0004.
- This does not, and cannot, prevent an agent from skipping the numbered menu
  and dispatching all five (or some) specialists without ever asking a
  human -- that remains a harness-level limit no CLI mechanism reaches. What
  it changes: the omission is now visible in `codev work log` as a durable
  fact about what actually ran, rather than only inferable, after the fact,
  from which coverage dimensions happen to be present.
- Testing needs: `record_reviewer` accepting a valid selection, rejecting an
  unknown specialist name and a repeated name, accepting an empty
  `specialists` list (the comment-sourced case), and `log_text` rendering it.
