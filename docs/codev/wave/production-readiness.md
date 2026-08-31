# CoDev Production Readiness Wave Plan

**Status:** Active
**Owner:** Martin Urban
**Brief:** [../../features/production-readiness/brief.md](../../features/production-readiness/brief.md)
**Design:** Not needed -- Wave 1's real technical decisions (decision-log
format and location, and staying local-only rather than adding telemetry)
are resolved directly in the brief's Constraints and Assumptions, since this
wave is built in one continuous session rather than parallel developers
needing a shared contract in advance. A design pass is warranted before
anyone besides the current implementer picks up Wave 1's remaining tasks.
**Project tracker:** Not used
**Supersedes:** Not applicable
**Last reviewed:** 2026-08-31

## Changes since last review

- Wave 1 complete: W-01 through W-04 all done. W-03's design changed during
  implementation: it runs on every push and pull request, not release-gated
  like `claude-code-compat` -- that restriction exists there because it
  needs network access to fetch the real Claude Code CLI, which this check
  does not need. W-04 closed through unplanned, real evidence gathered mid-session
  rather than a deliberately scheduled live-test session: Martin's own
  permission dialogs while W-01 was being implemented, confirmed stopped
  after the branch rename. All four of brief.md's success measures are now
  met.

## Current wave

**Outcome:** A maintainer can tell, from one command, whether CoDev's own
guardrails are actually working -- without manual log-reading or ad hoc
diffing.
**Evidence:** `codev status --verbose` reports gate-decision counts and
root-install drift status; a live Claude Code session's evidence is recorded
in `claude-code/design.md`; a scheduled CI job is green against this
repository's own root.
**Target:** Not committed.

## Current work

| ID | Task and acceptance | Owner | Reviewer | Risk | Status | Blocked by | Integrates with / lands after | Validation | Containment |
|---|---|---|---|---|---|---|---|---|---|
| W-01 | Local, gitignored decision log for `require_plan.py` and `require_wave_shape.py`. Every ask/allow decision recorded; a broken log write never changes the gate's own exit code. | Implementer | TBD | normal | Done | — | Lands before W-02 | Fixture-stdin tests asserting a decision is appended for every real decision point, and that irrelevant tool calls log nothing | N/A -- purely additive, no existing behavior changes |
| W-02 | `codev status --verbose` (and `--json`, and a new `--since`) surfaces a summary of W-01's log: counts by hook and decision, optionally windowed. | Implementer | TBD | normal | Done | W-01 | Integrates with W-01's log format | Unit tests against fixture log files, including `--since` filtering; `codev status --json` gains a documented `gate_decisions` field | N/A |
| W-03 | CI job (`scripts/verify_self_install.py`) running `codev diff` against this repository's own root install on every push/PR; fails loudly on drift. Not release-gated like `claude-code-compat` -- it needs no network access, so it runs on the fast path instead. | Implementer | TBD | normal | Done | — | Independent of W-01/W-02 | Tests against a fixture install (clean and deliberately-drifted cases); wired into `.github/workflows/ci.yml`; verified live against this repository -- caught real drift from W-01/W-02's own bundle changes, then confirmed clean after `codev update --on-conflict override` | N/A |
| W-04 | One real, live Claude Code session against an installed bundle: confirm the hook payload shape and the human-facing prompt match what the fixture tests assume. Requires a human-driven interactive session, not only subprocess-level checks. | Martin Urban | — | normal | Done | — | Closes the item deferred in `claude-code/design.md` since 2026-08-30 | Dated evidence recorded in `claude-code/design.md`'s header and Acceptance checklist; Martin confirmed 2026-08-31 the dialogs stopped after the branch rename | N/A |

## Integration checkpoints

| Checkpoint | Participating work | Owner | Entry evidence | Completion evidence |
|---|---|---|---|---|
| End-to-end observability check | W-01, W-02 | Implementer | Both in `ok_ready_for_pr` | Done, 2026-08-31: `.codev/hooks/decisions.jsonl` shows real entries from this repository's own actual tool calls during this session (not fixtures), and `codev status --verbose` correctly summarizes them (`require_plan.py: allow=7`, `require_wave_shape.py: allow=1` at time of writing). |

## Risks and discovery

| Risk or unknown | Impact | Evidence-producing action | Owner | Decision point |
|---|---|---|---|---|
| W-04 depends on a human-driven interactive session; it cannot be fully self-certified from an agent session alone | Wave 1's "closes the live-verification gap" outcome stays partially open until this runs | **Resolved 2026-08-31**, unplanned: while implementing W-01, Martin reported getting repeated real permission dialogs on the `improve-planning` branch, matching `require_plan.py`'s "ask" behavior exactly. After the branch rename, Martin confirmed directly that the dialogs stopped -- both halves of the guardrail claim are now live-verified, not simulated. | Martin Urban | Resolved |
| A local, file-based log may not be the right shape once real usage volume is seen | Could need revisiting before it's trusted as the long-term mechanism | Use it for a real week, then reassess | Implementer | After first real week of use |
| A local, file-based log may not be the right shape once real usage volume is seen | Could need revisiting before it's trusted as the long-term mechanism | Use it for a real week, then reassess | Implementer | After first real week of use |

## Later waves

- **Security hardening:** an opt-in hard-deny gate tier, and
  adversarial/prompt-injection testing of the bundled skills and agents.
  Refine once Wave 1's decision log shows real ask/allow rates to inform how
  strict to go.
- **Single-source bundle templating:** replace the hand-maintained parallel
  per-platform trees with a real rendering system. Needs its own design pass;
  refine once the current two-platform maintenance cost is actually measured,
  partly enabled by Wave 1's drift-detection CI job.
- **Field-proof `plan-wave`:** run the multi-developer machinery against a
  real team and record what breaks. Refine after Wave 1 gives visibility to
  actually observe it working.
- **Governance maturity:** bus-factor mitigation, and tracker integrations
  beyond GitHub Issues (Jira, Linear, Asana).
- **Today's tracked debt:** `Edit`/`MultiEdit` content-checking for the
  wave-shape gate, and the per-issue-precision alternative for the
  issue-boundary check (see ADR-0032's Revisit when).

## Team agreements

- Default implementation WIP: one item per developer.
- Owners do not approve their own changes.
- Status and availability live here; no linked tracker for this plan yet.
