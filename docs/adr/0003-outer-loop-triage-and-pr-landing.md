# ADR-0003: The outer loop specializes review, triages findings with the human, and lands the pull request

**Status:** Proposed
**Date:** 2026-08-11

## Context

ADR-0002 gives the inner loop a narrow, bounded path from a work item to a
draft pull request, ending in `READY_FOR_OUTER_LOOP` — a decision that
deliberately covers only `correctness` of `work.py`'s
`REQUIRED_COVERAGE_DIMENSIONS`. Nothing yet reviews the other dimensions,
nothing decides which of the outer loop's findings are worth acting on, and
nothing lands the draft PR anywhere. ADR-0002 named all of this explicitly as
future work, not solved in passing.

The same constraints from ADR-0002 continue to apply: every step below
executes inside one human-triggered local run, no CI-triggered inference, no
bot identity, no unattended fleet. The same failure mode named in ADR-0002 —
a reviewer adding new requirements each correction round instead of
converging — is equally possible here, on a wider surface, since review is
now split across several specialist agents instead of one.

## Decision

### Coverage dimensions gain a `concurrency` key

`REQUIRED_COVERAGE_DIMENSIONS`'s `security_privacy_data_concurrency_compatibility`
key splits into `security_privacy_data_compatibility` and a new standalone
`concurrency` key, at the user's request — concurrency review (races, shared
state, lock ordering, async correctness) is a different kind of attention
than security/privacy/data/compatibility review, and bundling them
understated it. This is a schema-breaking rename and requires
`ROUND_SCHEMA_VERSION` bumped from 1 to 2, using the version guard `_load`
already enforces. It also opens a gap in the seeded-defect fixture corpus
(`.codev/fixtures/seeded-defect-*`): no `concurrency` fixture exists today,
so eval coverage of the new dimension is incomplete until one is added. Not
resolved by this ADR.

### Round-state continues across the inner/outer boundary in one file

Each round entry gains `"phase": "inner" | "outer"`. `max_rounds` becomes
phase-scoped: `{"inner": 2, "outer": 2}`. `_round_slot` accepts opening a new
round when the previous round's decision was `READY_FOR_OUTER_LOOP` (starts
the outer phase's round 1) in addition to the existing `CHANGES_REQUIRED`
case. The round-cap, repeated-finding, and scope-expansion checks all
compare only within the current phase's rounds — the outer phase's round 1
is its own baseline, never compared against the inner loop's rounds.
`record_builder`/`record_reviewer` need no signature change: an outer-loop
round's reviewer entry is populated by the outer-loop-runner after merging
specialist output, same shape as a single reviewer's entry today, and the
same builder subagent handles corrections in either phase.

### Five specialist reviewers, each owning a disjoint set of coverage keys

| Specialist | Coverage keys owned |
|---|---|
| Correctness & Tests | `correctness`, `error_handling`, `test_quality` |
| Security, Privacy & Data | `security_privacy_data_compatibility` |
| Concurrency | `concurrency` |
| Architecture & Maintainability | `architecture_scope`, `maintainability` |
| Rollout | `rollout` |

Each is invoked in a fresh context, like today's `reviewer` and the inner
loop's `lightweight-reviewer`. Each applies the same "favor approving once
the change is safe and better than before, not once it's perfect" standard
established for the lightweight reviewer in ADR-0002 — one instruction,
applied uniformly everywhere review happens in this system, not
re-litigated per agent. The outer-loop-runner merges all five specialists'
partial coverage dicts into one before recording. That merged dict already
satisfies the *existing* `_incomplete_coverage` gate under
`READY_FOR_HUMAN_APPROVAL` unchanged — no new decision value is needed at
this stage, unlike the inner loop's `READY_FOR_OUTER_LOOP`. The existing
binary `blocking` field on each finding (already present in `work.py`
today) is reused as-is as the must-address/optional distinction; no schema
change was needed for this part.

### New `outer-loop-runner` role

Fetches PR and GitHub context, reusing `pr-review`'s existing `--fetch` mode
and the `github-actions-ci-results` skill — no new fetch mechanism. Checks
CI status *before* dispatching any specialist: red or pending checks stop
the run and report, rather than spending five specialist invocations on a
PR that doesn't even build. Once checks are green (or a human explicitly
overrides), dispatches to the five specialists, merges their coverage and
findings, and records the round.

### Human triage becomes durable state

A new `triage` record attaches to any outer-loop round that has findings.
Every blocking finding gets an explicit `address` or `defer` disposition
from the human; deferring a blocking finding requires a non-empty
`override_reason`; non-blocking findings need no disposition. A new
`check()` outcome, `ok_waiting_on_triage`, mirrors the existing
`ok_waiting_on_reviewer` and gates opening the correction round until
triage is recorded — nothing may be "fixed" that the human hasn't
authorized.

### The outer loop's correction round is capped at exactly one, narrowly

`max_rounds["outer"] = 2`: round 1 is the specialists' initial assessment
(not a correction), round 2 is the one human-triaged correction pass. The
existing round-cap check, now phase-scoped, implements "one targeted
correction round" with no new cap mechanism — if round 2 still shows a
selected finding unresolved, `_find_repeated_blocking_finding` (existing,
unchanged) or the round cap itself escalates to the human. Round 2 only
re-invokes the specialists that own the `address`-selected findings'
categories, each scoped to verifying only those specific findings — not a
fresh full five-specialist pass. Anything a narrowly re-invoked specialist
raises outside that scope is exactly what `expansion_reason` /
`stop_scope_expansion` (ADR-0002) exists to catch; that mechanism was built
generic for this reason and needs no extension here.

### A local, gitignored escalation log

`.codev/work/escalations.jsonl`, per-project rather than in the global
config location — the tuning value is specific to this project's threshold
and specialist-prompt choices, and mixing signal across unrelated repos
would dilute it. Explicitly gitignored; this is a new precedent for this
repository, since nothing under `.codev/` is gitignored today. One JSON
record per line: `timestamp`, `work_item_id`, `phase` (nullable, since a
pre-build critical interrupt from ADR-0002 has no round yet), `round`
(nullable), `trigger` (`critical_interrupt`, `stop_drift`,
`stop_repeated_finding`, `stop_round_cap`, `stop_scope_expansion`,
`blocked_missing_evidence`, `human_override_blocking_finding`), and `cause`.
Written explicitly through a new `record_escalation`
(`codev work escalate`) — `check()` remains read-only and does not log as a
side effect. Read back through a new `codev work escalations [--since DATE]`,
in the same plain style `log_text` already uses.

### Landing the pull request

The guarded git/GitHub command surface introduced in ADR-0002
(`codev git branch|commit|push|open-pr`) gains one more operation,
`codev git mark-ready`, which is not a raw `gh pr ready` pass-through: it
regenerates the PR body from the work item's full round-state — delivered
behavior, evidence, and every finding's triage disposition, explicitly
including deferred or overridden blocking findings with their reasons — and
only then converts the PR out of draft. This is the same "reversible
actions can be automatic" reasoning ADR-0002 used for opening the PR in the
first place: leaving draft status is not a merge, does not affect
production, and remains fully reversible. It fires only when the outer loop
reaches `READY_FOR_HUMAN_APPROVAL`. Publishing specialist findings as an
actual GitHub PR review is deliberately *not* part of this new surface — it
reuses `pr-review`'s existing `publish_review.py` unchanged, since the
merged specialist findings already fit the JSON review payload shape it
already knows how to send, dry-run by default, requiring the same explicit
`--publish` human authorization it requires today. A human pushing directly
to the PR branch is already caught by `stop_drift` (ADR-0002, unchanged) —
confirmed, not modified, by this ADR. A non-convergent outer loop (round cap
or scope-expansion hit) leaves the PR in draft, logs the escalation, and
surfaces the evidence — it is not deleted or hidden.

## Consequences

- All four platform adapters need the five specialist agents and the
  `outer-loop-runner` added, on top of the inner-loop changes from
  ADR-0002. `codev adapter verify`'s conformance checker needs extending
  again: assert the specialist agents and outer-loop-runner are present,
  and that the `mark-ready` operation follows the same guarded-surface
  pattern as `open-pr` rather than a raw permission grant.
- `ROUND_SCHEMA_VERSION` moves to 2. Any in-flight work item created under
  schema 1 is not forward-compatible without a migration path — not
  designed here, and worth resolving before implementation, since a
  mid-flight work item hitting this ADR's changes has nowhere defined to
  go today.
- The seeded-defect fixture corpus needs a `concurrency` fixture before
  `codev eval snapshot run review-change` gives complete signal on the new
  dimension.
- A new `.gitignore` entry is needed for `.codev/work/escalations.jsonl`.
- Together, ADR-0002 and this ADR describe the complete connected path from
  a work item to a landed, human-approved pull request, as designed in this
  round of work. Implementation should proceed in `build-change`-sized
  pieces per component (schema changes, each new subagent, the git
  wrapper's operations, the escalation log) rather than as one change,
  consistent with this project's own size guidance.
