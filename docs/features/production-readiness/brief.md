**Status:** Accepted
**Owner:** Martin Urban
**Last reviewed:** 2026-08-31

## Problem and users

CoDev's maintainers need honest confidence that the tool is safe and correct to
hand to a real small team, not just internally consistent when inspected by
hand. This session surfaced concrete evidence that it is not there yet: this
repository's own root install silently drifted from bundle source for over a
week with nothing to catch it; every guardrail claim was verified through
fixture tests and binary inspection, never a live session, until checked by
hand today; every gate is ask-only with no stricter tier and no
adversarial-input testing; the bundle is hand-maintained parallel trees that
already produced a real bug during a routine rename; and `plan-wave`'s
multi-developer machinery has never run against a real team.

## Desired outcome

CoDev's guardrails stay verifiably correct over time, not only at the moment
someone happens to check them by hand, and a maintainer can see whether the
tool is actually doing its job without manual inspection.

## Success measures

- A gate's ask-or-allow decision is recorded somewhere a maintainer can query,
  not only visible in the moment it fires.
- `codev status` answers "is my own dogfood install still in sync with the
  bundle" without a manual `codev diff`.
- A CI job catches root-install drift before it sits unnoticed for a week, the
  way it did this time.
- At least one live, non-simulated Claude Code session has confirmed the hook
  payload shape and the human-facing "ask" prompt, recorded as dated evidence
  -- closing the item deferred since 2026-08-30.

## Essential scenarios

- A maintainer runs `codev status --verbose` after a week away and can tell,
  from that one command, whether a gate has been silently misfiring or the
  root install has drifted, without reading hook source or running `codev
  diff` by hand.
- A future bundle change accidentally breaks a hook's JSON contract; a
  scheduled CI check catches it before a real user hits it, the same way
  `claude-code-compat` already catches Claude Code's own surface drifting.

## First release

### Now

- A local, gitignored decision log for `require_plan.py` and
  `require_wave_shape.py` -- every ask-or-allow decision recorded; the log
  write itself fails open and never changes a gate's own exit behavior.
- `codev status` surfaces a summary of that log: counts by hook and decision
  over a window.
- A scheduled, release-gated CI job that runs `codev diff` against this
  repository's own root install and fails loudly on drift, mirroring
  `claude-code-compat`'s existing pattern.
- One real, live Claude Code session against an installed bundle, confirming
  the hook payload shape and the human-facing prompt match what the fixture
  tests assume, recorded as dated evidence in
  `docs/features/claude-code/design.md`.

### Next

- An opt-in, stricter hard-deny gate tier, and adversarial-input
  (prompt-injection) testing of the bundled skills and agents.
- A real templating or rendering layer replacing the hand-maintained parallel
  per-platform trees.
- Running `plan-wave`'s multi-developer machinery against a real team and
  recording what actually happens.
- Bus-factor mitigation and external-tracker integration (Jira, Linear, Asana)
  beyond GitHub Issues.
- The narrower debt already named in ADR-0032 and ADR-0033: `Edit`/`MultiEdit`
  content-checking for the wave-shape gate, and the per-issue-precision
  alternative for the issue-boundary check.

### Not planned

- Cross-repository or vendor-side telemetry -- "phone home" usage data across
  adopters. This wave is local observability inside one repository, not
  fleet-wide visibility; the latter would break the project's stated
  no-network-access posture and is not a decision to make as a side effect of
  this work.
- A full single-source-templating rewrite of the bundle in this wave. The
  *system* it would replace is scoped Next; rebuilding it needs its own design
  pass first.

## Constraints

- The decision log and any status reporting stay fully local and offline -- no
  network calls, consistent with `docs/architecture.md`'s existing invariants
  and with `plan-wave`'s own containment posture from this session.
- Logging must never change a gate's own exit behavior; a broken log degrades
  to "no log," never to "no guardrail" or "blocked edit."
- The live-session verification task may need you directly, not only me. The
  one thing genuinely unconfirmed is whether Claude Code's real runtime
  invokes the hook with the exact payload shape assumed, and whether its
  permission-prompt UI actually surfaces the decision correctly to a human. I
  can exercise the hook script directly -- already done twice this session --
  but cannot fully self-certify the UI/runtime half from inside my own
  session.

## Assumptions and discovery

| Assumption | Evidence needed | Owner | Decision point |
|---|---|---|---|
| A local, file-based log is sufficient for "is this working" visibility, without a real database or external service | Try it against this repository's own real usage for a week | Implementer | After the first real week of use |
| Staying local-only, with no cross-adopter telemetry, is the right call rather than a gap | None needed -- a deliberate product-fit decision given every existing invariant this session found, recorded here for visibility | Martin Urban | Already decided |

## Acceptance

- [x] Outcome, scope, non-goals, and success measures accepted by the accountable human.

Wave 1 (the "Now" scope) is complete as of 2026-08-31 -- all four success measures above are met.
See `docs/codev/wave/production-readiness.md` for the wave-by-wave record and the "Next" scope's
coarse outcomes.
