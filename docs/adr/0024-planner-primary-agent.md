# ADR-0024: `planner`, a fifth primary agent for Specify/Understand/Design/Plan

**Status:** Accepted
**Date:** 2026-08-19

## Context

`docs/product-map.md`'s phase spine (`Specify -> Understand -> Design ->
Plan -> Build -> Review -> Ship -> Launch`) already names `orchestrator` as
the session entry point for Build/Review/Ship, and its own "Directions and
open questions" section already confirmed, deliberately, that
`orchestrator`'s Build-only scope is "not a gap — neither phase has a
build-and-review loop to orchestrate." That confirmation was correct as far
as it went: nothing about Build/Review/Ship was missing. But it did not
follow that the Specify/Understand/Design/Plan phases needed no entry point
of their own — only that `orchestrator` was not going to be it.

Today those four phases have no session identity: `define-product`,
`specify-project`, `design-solution`, and `plan-delivery` are each invoked
manually by name, or reactively by `orchestrator` mid-build when a build
surfaces a question it cannot answer itself. There is no human-started
session whose whole job is planning, decoupled from execution — a developer
who wants to think through a design without being one command away from
`orchestrator` reaching for `builder` has no dedicated place to do that.

The request that surfaced this: support planning work independently of
execution, and support a workflow that stops once a well-formed GitHub issue
exists, without continuing into a build. `codev git issue-create` already
has no work-item precondition (ADR-0004) and is already called from
`plan-delivery`'s own Handoff step — the capability existed; only the
decoupled entry point to it did not.

## Decision

### `planner`: a fifth primary agent, mapped onto the existing phase spine

`planner` joins `orchestrator`, `code-audit`, and `outer-loop-runner` as a
`mode: primary` (human-started) agent, one file per platform under each
bundle's `agents/` directory, following the exact frontmatter shape each
platform already uses for its other primary agents:

- OpenCode: `mode: primary`, `permission.task` denying every agent (`"*":
  deny`, no exceptions — `planner` invokes nothing), `permission.bash`
  scoped narrowly to read-only git plus `"codev git issue-create*": allow`
  only (not the wildcard `"codev git *": allow` `orchestrator` has —
  `planner` has no business with `branch`/`commit`/`push`/`open-pr`/
  `mark-ready`, all Build-phase operations).
- Codex: `sandbox_mode = "workspace-write"` (it writes planning-artifact
  markdown directly, unlike `orchestrator`, which mostly delegates writes to
  `builder`).
- Junie: minimal `name`/`description` frontmatter, matching every other
  Junie agent.
- Antigravity (`.agents/agents/`): `mainAgent: true`, `subagent: true`,
  `model: inherit`, `commandExecutionPolicy: sandbox`, matching
  `orchestrator`'s own file.

Scope: wraps `define-product`, `specify-project`, `design-solution`, and
`plan-delivery` exactly as they exist today — no change to those four
skills' own content beyond the terminology rename in ADR-0023. `planner`
never implements product code, never edits outside a planning artifact's own
location without authorization, and never invokes `builder`, `reviewer`,
`lightweight-reviewer`, `code-audit-gate`, or `orchestrator`. The reverse
also holds: `orchestrator`'s own `permission.task` allow-list is
**unchanged** — it does not gain the ability to invoke `planner` either.
The two are independent human-started entry points, the same relationship
`orchestrator` and `outer-loop-runner` already have; a human moves between
them by starting a new session, not by one agent handing off to the other
in-band.

### Issue-only short circuit

`planner` gains one mode beyond wrapping the four skills as-is: given an
already-accepted design or decision, draft a task directly and run `codev
git issue-create --title <title> --body <body>|--body-file <path> [--path
<glob>]... [--assignee <name>]...`, reusing exactly the fields
`plan-delivery`'s Handoff already uses. Skip the milestone, team-profile,
and work-item-list machinery entirely for this path — it exists for
multi-developer delivery-plan coordination, which this short circuit is
explicitly for when that coordination isn't needed. Stop once the issue is
created; do not run `codev task start` or anything in the `codev task` or
`codev git branch/commit/push/open-pr/mark-ready` surface — starting the
task remains `orchestrator`'s job, in a later, separate session.

This does not change `orchestrator`'s own step-5 fallback (create the issue
itself if one is still missing before opening round state, per ADR-0020) —
both paths already coexist by design; `orchestrator` checks rather than
assumes an earlier session already created the issue, so the short circuit
being skipped entirely changes nothing about `orchestrator`'s behavior.

### Registration

- `adapter.py:_role_paths` gains a `"planner"` entry (a standalone role, not
  part of `_OUTER_LOOP_ROLES`) so all four platforms are structurally
  verified the same way every other role is.
- `adapter.py:_REQUIRED_MARKERS["planner"] = ("codev git issue-create",)` —
  the one guarded mutation surface `planner` is allowed to touch.
- `installer.py:OPENCODE_AGENT_CONFIGS` gains a `"planner"` entry
  (`mode: primary`, not the default agent — `orchestrator` stays
  `default_agent`) so an OpenCode install registers it correctly.

## Consequences

- `docs/product-map.md`'s Agents table, phase table, and Named-skills
  "Invocation today" column are updated to name `planner` as the new entry
  point for Specify/Understand/Design/Plan, alongside `orchestrator`'s
  existing *reactive* redirects into the same four skills mid-build, which
  are unchanged. A new "Resolved and implemented (ADR-0024)" note is added
  next to the existing ADR-0005 note it follows on from.
- `ai-agent-guidelines.md` gains a short paragraph, next to the existing
  Understand/Build/Review/Ship framing, naming `planner` as the dedicated
  entry point for Design/Plan depth and stating explicitly that handing a
  ready task from a `planner` session into a `Build` session is a human
  decision (starting a fresh `orchestrator` session), not an automatic
  continuation.
- Testing: `tests/test_adapter.py`'s `BundleParityTests` (already
  platform-generic over `ADAPTER_ROLE_PATHS`) picks up the new role
  automatically. `tests/test_installer.py`'s two tests that pin the exact
  sorted list of installed Codex agent files needed a `planner.toml` entry
  added; no other platform's installer tests enumerate the full list.
  `tests/test_cli.py::test_adapter_verify_passes_on_a_fresh_install`'s
  hardcoded finding count moved from 10 to 11 roles.
- Root dogfood copies need the same `codev update` resync this repository
  already needs after ADR-0023's bundle changes — one sync covers both.
