# ADR-0008: A triaged blocking finding can resolve scope expansion, not just repeat it

**Status:** Accepted
**Date:** 2026-08-12

## Context

A real outer-loop round hit this shape: the correction round re-verified an
`address`-selected fix, found it correct, but the re-verification also
surfaced two new blocking findings the specialists had not raised in round
one. Neither carried an `expansion_reason`. `codev work check` correctly
returned `stop_scope_expansion` (ADR-0002) — the guard doing exactly its job,
forcing a human to look before the loop silently chased a moving target.

The human's judgment was reasonable and unremarkable: these two findings
were real, but not worth blocking this PR on — file them, defer them, land
the rest. Tracing the actual path to record that decision found it does not
exist:

1. **`codev work triage` cannot resolve `stop_scope_expansion` or
   `stop_repeated_finding`.** `check()` evaluates
   `_find_scope_expansion`/`_find_repeated_blocking_finding` unconditionally,
   before ever consulting the round's `triage` field. Recording a triage that
   defers the offending finding, with a valid `override_reason`, changes
   nothing — the next `check()` call returns the identical stop.
2. **`record_triage` requires the round's decision to be `CHANGES_REQUIRED`.**
   Re-recording `CHANGES_REQUIRED` on a later round with the same untagged
   finding re-triggers the same stop immediately (the phase's scope-expansion
   baseline is fixed at the phase's first round, permanently). There is no
   way to both keep the finding on record as blocking *and* let the loop
   conclude.
3. **The outer phase's round cap (`max_rounds["outer"] = 2`, ADR-0003) is
   defined so that scope-expansion, when it happens, coincides with the cap
   already being exhausted** — round 2 (the specialists' initial assessment)
   never counts as "a correction" by ADR-0003's own reasoning; round 3 (the
   one permitted correction round) is where a re-verification surfacing new
   findings would land, and it is simultaneously the cap-defining round. So
   even a hypothetical triage-based fix to (1) alone would still dead-end on
   the round cap for this, the common case.

This was not a one-off. Deferring a newly surfaced, non-critical blocking
finding to a follow-up is Google's own documented practice
(`google.github.io/eng-practices`'s review standard: favor approving a CL
that clearly improves code health over blocking for perfection; file a bug
and reference it rather than stall the CL) and is exactly the shape CoDev's
own `triage`'s `defer` + `override_reason` mechanism already handles for
every *other* blocking finding in the outer loop. Scope-expansion findings
were the one category triage could not actually resolve, for reasons
internal to `check()`'s evaluation order rather than any considered
decision to treat them differently.

`VALID_ESCALATION_TRIGGERS` already contains `"human_override_blocking_finding"`,
unused since ADR-0003 introduced it, and `record_escalation`'s own docstring
already names "a human override of a blocking finding during triage" as one
of the events a caller should log. The trigger anticipated exactly this
case; nothing before this ADR ever wired an actual path to it.

## Decision

### 1. A round's own triage exempts its findings from scope-expansion and repeat detection

`_find_scope_expansion` and `_find_repeated_blocking_finding` now skip any
finding whose id already has a triage disposition recorded on the *same*
round (`_triaged_finding_ids`, new). Either disposition — `address` or
`defer` — counts: both are the one explicit human look the guard exists to
force. This does not weaken the guard: an untriaged offending finding still
stops the first time `check()` sees it, exactly as before. Only a round that
has *already* been triaged is exempt, and `_validate_triage` (ADR-0003)
already requires a disposition for every blocking finding before triage can
be recorded at all — there is no way to triage around the guard partially.

### 2. A `CHANGES_REQUIRED` round where every blocking finding is deferred needs no further round

New `_all_blocking_deferred(findings, triage)`. When the outer phase's
latest round is `CHANGES_REQUIRED`, has a recorded triage, and every
blocking finding's disposition is `defer` — nothing is left for a builder to
build. `check()` now applies the same `_incomplete_coverage` gate
`READY_FOR_HUMAN_APPROVAL` already uses, and on success reports a new
outcome, `ok_approve_with_deferrals`, instead of falling through to the
round-cap check. The round's own recorded `decision` stays `CHANGES_REQUIRED`
— an honest record of what the specialists actually found — `check()`'s
reason is a distinct, later verdict about what happens next, the same
relationship it already has with every other `CHANGES_REQUIRED` sub-case.
If even one finding was `address`-selected instead, real building work is
implied and the existing round-cap/`ok_continue` logic applies unchanged
(deferring is free; addressing still costs a round and, if the cap is
already spent, still needs `codev work reopen`, ADR-0007 — asymmetric on
purpose).

`codev git mark_ready` (`git_ops.py`) now accepts `ok_approve_with_deferrals`
alongside `ok_approve`. `codev git open_pr`'s existing outer-phase acceptance
(ADR-0007's follow-up) already covers this reason without change, since it
only requires the outer phase and `result.ok`.

### 3. The stop messages, and the workflow docs, point at the resolution

`stop_scope_expansion`/`stop_repeated_finding`'s messages now append a
phase-gated hint — `codev work triage may address or defer it (with a
reason) to resolve this` — present only in the outer phase, where triage
actually applies (`record_triage` still rejects the inner phase outright;
inner-phase scope expansion is unchanged and still a hard escalation,
consistent with the inner loop having no human-triage step by design,
ADR-0002). `outer-loop-runner.md` (all four platforms) and
`ai-agent-guidelines.md` now describe the full decision tree: triage
resolves `ok_waiting_on_triage` and a scope-expansion/repeat stop the same
way; an all-deferred triage skips straight to landing, recording
`codev work escalate --trigger human_override_blocking_finding` for the
audit trail on the way.

## Consequences

- Deferring a legitimately out-of-scope finding to a tracked follow-up (a
  new work item or a GitHub issue via `codev git issue-create`) is now a
  fully mechanical path, not a hand-guided workaround through `codev work
  reopen`. `reopen`'s own design (ADR-0007) needed no change — it remains
  the tool for a round cap or drift genuinely requiring more building, which
  this is not.
- No `ROUND_SCHEMA_VERSION` bump: no new stored field, only a new `check()`
  outcome derived from data already recorded (`reviewer.decision`,
  `reviewer.findings`, `triage.dispositions`).
- `human_override_blocking_finding` is no longer a documented-but-unused
  escalation trigger; the outer-loop-runner workflow now names the exact
  moment to use it.
- The evidence trail stays honest by construction: a deferred finding is
  never silently downgraded to non-blocking or dropped from the round's own
  findings list to make the round *look* clean — `codev work log` and the
  regenerated PR body (`mark-ready`) show the actual `CHANGES_REQUIRED`
  verdict and the triage disposition side by side.
- Testing needs: scope-expansion and repeated-finding exemption once
  triaged (both `address` and `defer` dispositions), `ok_approve_with_deferrals`
  on full and incomplete coverage, a mixed address/defer round correctly
  falling through to `ok_continue`/`stop_round_cap` instead, the zero-blocking-
  findings edge case, the inner-phase message carrying no triage hint, and
  `mark_ready` accepting the new reason.
