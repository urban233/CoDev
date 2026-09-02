# Navigator Coverage Measure - Implementation Plan

**Status:** Accepted 2026-09-02 by Martin Urban
**Owner:** Martin Urban
**Author:** Claude Opus 5 (drafted; not an approval)
**Successor plan:** [docs/plans/developer-experience-implementation.md](developer-experience-implementation.md), which this blocks
**Base commit:** `90cf9f4`
**Target version:** none -- no user-visible change, ships inside 0.5.x
**Delivery shape:** one small pull request
**Risk:** low. Test-only; adds no production code path.

## Context

The unified-workflow brief's first success measure reads:

> A developer completes a full task -- issue to merged pull request -- having
> typed no `codev` command other than the one-time `codev init`, verified by
> replaying a recorded session and counting developer-issued commands.

No harness for it exists. Every claim CoDev has made about its developer
experience, including the one the developer-experience plan is about to make,
is therefore asserted rather than measured.

The measure cannot be built the way the brief words it, and this plan restates
it rather than pretending otherwise.

## Why "replay a recorded session" is the wrong mechanism

Three problems, any one of which is disqualifying:

1. **There is no transcript format.** Claude Code and OpenCode record sessions
   in different shapes, neither of which CoDev controls or versions. A measure
   built on one adapter's format measures that adapter.
2. **It audits rather than tests.** A recorded session is a thing that already
   happened. It cannot run in CI, cannot fail a pull request, and cannot
   produce a number for a commit that has not been exercised by hand.
3. **It measures the wrong actor.** "Developer typed no command" is a property
   of how a particular agent behaved in a particular session -- which is
   model-dependent and non-deterministic. Two runs of the same session
   legitimately differ. A measure whose value depends on sampling an LLM is not
   a regression test.

## What is measured instead

**Navigator coverage: the number of steps in a complete task lifecycle where
`codev next` does not name the single command that advances the work.**

This is the precondition for the brief's measure rather than a substitute for
it. A developer types a `codev` command for exactly one reason: the agent did
not know what to run. The agent knows what to run when, and only when, the
navigator tells it -- that is what ADR-0036 rule three made the navigator for.
Every uncovered step is a step where the agent must fall back on the procedural
prose in its role file, and that prose is what this plan's successor is
deleting.

So the number is a direct count of the remaining gap, it is deterministic, it
runs in CI, and it falls as packages 2 and 3 of the successor plan land. It is
zero when a full lifecycle can be driven by consulting the navigator and
nothing else.

**It is a proxy, and this document says so plainly.** Coverage reaching zero
does not prove a developer typed nothing; an agent can still hand a command to
a human, and a human still makes every decision the loop stops for -- which is
intended and is not what this counts. What zero proves is that nothing in the
lifecycle *forces* a developer to supply a command. That is the part CoDev can
control, and it is the part that is broken today.

## Focus card

- **Change:** A test that drives one complete task lifecycle against a real
  repository and a real remote, consulting `codev next` before every step, and
  asserting the navigator-coverage count against a recorded baseline.
- **Success:** The count is computed, not hand-maintained; the test fails when
  coverage regresses; a baseline for `90cf9f4` is recorded in the repository.
- **Non-goals:** Changing the navigator, any command, or any role file. If the
  measure reveals gaps -- it will -- they are recorded as the baseline, not
  fixed here. Fixing them is the successor plan's whole point, and fixing them
  here would leave nothing to measure the improvement against.
- **Allowed scope:** `tests/test_navigator_coverage.py` (new),
  `tests/integration_support.py` (extension only),
  `tests/navigator-coverage-baseline.json` (new),
  `docs/architecture.md` (one paragraph describing the measure).
- **Validation:** `.tools/just ci`. The new test runs in the integration tier
  added in `8df4eb4`, so it is skipped on platforms that tier already skips.
- **Stop if:** driving the lifecycle requires mocking `codev next` itself, or
  requires a command that does not exist. Either means the measure is being
  bent to produce a flattering number.
- **Work style:** Pair. The definition of a "step" is the judgment call in this
  plan and should not be delegated.
- **Estimated size:** 250-350 lines including the test and the baseline.

## Repository evidence

- `tests/integration_support.py` already provides exactly the substrate this
  needs: a real repository, a real remote, and a `gh` stub installed as an
  executable on `PATH` rather than a patched attribute, "so the code under test
  takes exactly the path it takes in production." No new harness is required.
- `tests/test_integration_lifecycle.py` already walks a lifecycle end to end --
  `test_a_single_slice_task_reaches_a_ready_pull_request`,
  `test_only_the_final_slice_closes_the_issue`,
  `test_a_human_approval_is_read_from_the_pull_request`. The coverage test is a
  second walk over the same ground with a different assertion, not a new
  scenario.
- `oracle.NextAction` already carries the field the measure reads: `command`,
  which is `str | None`. `None` is an uncovered step by construction.
- `oracle._BY_CHECK_REASON` shows the gap is real before the test is written.
  Two entries return `None` for `command` outright, and two more return a
  sentence containing *two* commands -- `"codev git push, then codev git
  open-pr"` and `"codev git branch, then codev task start"` -- which the
  successor plan's package 2 collapses into `codev slice publish` and `codev
  slice begin`.

## Design

### A step, and when it counts as uncovered

A **step** is one state transition in the lifecycle: the work is in some
position, one command moves it to the next position. The test walks the
lifecycle and, before each transition, calls `next_action` and compares its
`command` field to the command the test is about to issue.

A step counts as **uncovered** when any of:

- `command` is `None` -- the navigator has no command for this position.
- `command` names a different command than the one that advances the work.
- `command` contains more than one command. A field that says "push, then
  open-pr" has not told an agent what to run; it has told it what to read.

The third rule is the one that makes the measure honest. Without it, today's
`"codev git push, then codev git open-pr"` would score as covered, and the
successor plan's package 2 -- whose entire purpose is collapsing exactly these
-- would show no improvement.

### Baseline rather than threshold

The test asserts against `tests/navigator-coverage-baseline.json`, which
records the count and the uncovered steps by name. Two properties matter:

- **A regression fails the build.** A count higher than the baseline, or a new
  step name in the uncovered list, fails.
- **An improvement fails the build too, with a message saying to update the
  baseline.** A measure that silently ratchets is a measure nobody reads. The
  successor plan's packages each land with a visible baseline edit in their
  diff, which is the point: the improvement becomes reviewable.

Recording step *names*, not just a count, is what makes the diff legible. A
reviewer of package 2 sees `open_pull_request` and `begin_slice` disappear from
the list rather than seeing `7` become `5`.

### Lifecycles walked

One is enough to start, and it must be the ordinary one: a single-slice task
from no branch to a merged pull request. A multi-slice walk is the obvious
extension and is deliberately deferred -- it shares every step with the
single-slice case except `advance-slice`, and adding it before the measure has
proved useful is speculative.

The walk includes the pre-task positions, which is where the largest gap is.
`oracle.py:184` returns one recommendation for every state in which no task
exists, so the entire Understand/Design/Plan half of the lifecycle scores as
uncovered today. That is the number the successor plan's package 3 exists to
move, and it must be in the baseline or package 3 shows no improvement either.

## Risks and rollout

- **The measure could be gamed by writing a `command` string for every
  position without the command working.** The walk executes the command it
  compares against, so a wrong command fails the lifecycle rather than scoring
  as covered. This is the reason the test drives a real repository instead of
  reading the `_BY_CHECK_REASON` table statically -- a static read would be
  cheaper and would measure nothing.
- **The definition of a step is arguable, and the number is meaningless across
  different definitions.** It is therefore recorded in the test module's
  docstring, not only here, and the baseline file is worthless if the
  definition changes silently. Any change to the definition resets the
  baseline and must say so.
- **This measures the navigator, not the developer.** Stated above, restated
  here so it is not lost: coverage at zero is a necessary condition for the
  brief's measure, not the measure itself.

## Decisions needed

1. **Does an uncovered pre-task step count the same as an uncovered build
   step?** Recommended: yes, one flat count, because weighting invites tuning
   the weights instead of closing the gaps. The step names in the baseline
   preserve the distinction for anyone who wants to read it.
2. **Does this ship in 0.5.x as a patch, or wait and ship with 0.6.0?**
   Recommended: 0.5.x, and soon. It is test-only, it has no user-visible
   surface, and its whole value is recording a baseline for code that is about
   to change.

Both have recommendations and need only confirmation. Neither blocks drafting.

## Completion evidence

To be filled in when it lands. This document is authority, not a record.
