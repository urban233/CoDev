**Status:** Proposed
**Owner:** TBD (assign before implementation starts)

## Problem

CoDev installs and maintains workflow scaffolding — role subagents, shared skills, PR/task
lifecycle wiring — for four coding-agent platforms (Codex, Junie, OpenCode, Antigravity) through
its adapter/installer system. Claude Code, Anthropic's own first-party CLI, has no adapter at
all: `installer.VALID_PLATFORMS` doesn't include it, there is no `.claude/agents/` bundle
content, and the only `.claude/` directory in this repo is an empty, untracked artifact the
Claude Code app created locally on open — never a CoDev-managed install, never committed. Anyone
using Claude Code on a CoDev-managed repository today gets none of CoDev's role-based workflow,
none of its shared skills surfaced natively, and none of its spec-driven guardrails.

Separately, and specifically for Claude Code: Claude models are known to sometimes begin editing
code before proposing or discussing a plan, which is in direct tension with CoDev's core premise
— a repository-enforced brief → design → implementation sequence. Claude Code also happens to be
the one platform in CoDev's lineup with a native, structural mechanism for addressing exactly
this (plan-mode session defaults, permission-gating hooks), which none of the other four
platforms expose in the same way. Shipping Claude Code support without using it would leave
CoDev's most guardrail-capable platform with the weakest guardrails of the five.

## Outcome

`codev init --agent-platform claude` (and `--agent-platform all`) installs a complete, native
`.claude/` bundle with the same conflict-aware add/update/verify/remove lifecycle every other
platform already has:

- All 13 role subagents (11 static + templated `code-audit`/`code-audit-gate`) under
  `.claude/agents/`, same shared body prose as the other four platforms, Claude Code's own
  subagent frontmatter.
- CoDev's 15 shared skills discoverable natively under `.claude/skills/`.
- The existing `pr-review` command ported to `.claude/commands/`.
- A `.claude/settings.json` + `.claude/hooks/` pairing that defaults new sessions into Plan Mode
  and pauses for human confirmation before the first source edit when no spec/plan exists yet for
  the active work — CoDev's spec-driven premise enforced structurally, not only requested in
  prose.
- A short, Claude-Code-specific `.claude/CLAUDE.md` — not a copy of the shared contract, since
  Claude Code already reads CoDev's existing `AGENTS.md` managed block natively.

## First-release scope

- Extend the six known per-platform sites (`installer.VALID_PLATFORMS`, `AUDIT_AGENT_TEMPLATES`,
  `PRE_PR_CLEANUP_AGENT_TEMPLATES`, `_bundle_files()`'s filter chain, `adapter.ADAPTER_ROLE_PATHS`,
  `cli._AGENT_PLATFORMS`) plus the two packaging sites (`pyproject.toml` package-data globs,
  keywords list) with a `claude` entry.
- `.claude/agents/*.md` — 13 role files.
- `.claude/skills/` — shared skills surfaced for Claude Code (exact mechanism pending the Phase 0
  spike in design.md).
- `.claude/commands/pr-review.md`.
- `.claude/settings.json` + `.claude/hooks/require_plan.sh` (or equivalent) — the plan-first
  guardrail.
- `.claude/CLAUDE.md`.
- Full test coverage mirroring the existing per-platform patterns in `test_installer.py`,
  `test_adapter.py`, `test_cli.py`.
- `README.md`, `docs/architecture.md`, `AGENTS.md` updates; CHANGELOG entry; ADR-0030 recording
  the new settings.json/hooks bundled-content category and the CLAUDE.md-as-import decision.

## Non-goals

- Extending `codev eval run` to drive Claude Code as a fixture-attempting agent. Today that
  harness only drives OpenCode; adding a second drivable agent is a distinct, comparably-sized
  effort with its own compatibility surface — see design.md's Resolved Contracts and Deferred
  Risks.
- Shipping a `.mcp.json`. No MCP servers are currently part of CoDev's workflow; nothing here
  needs one.
- Restructuring `AGENTS.md` or its managed block. Phase 0 (design.md) found Claude Code already
  hardcodes `AGENTS.md` discovery natively, the same as `CLAUDE.md` — CoDev's existing shared
  contract there needs no Claude-specific changes to reach Claude Code; `.claude/CLAUDE.md` only
  needs to add what's Claude-Code-specific on top of it.
- A hard, unbypassable enforcement of plan mode. Claude Code's permission model only allows that
  at organization/managed-settings scope, outside a repo-local install's reach. This ships the
  strongest guardrail available at project scope, honestly documented as a nudge-plus-checkpoint,
  not an unbypassable lock.

## Evidence of value

Brings Claude Code to parity with the four already-supported platforms (Codex, Junie, OpenCode,
Antigravity), each added as a complete adapter in its own right per CHANGELOG precedent (v0.1.1,
v0.1.4, v0.1.5). Directly answers a specific, named pain point — premature implementation without
discussion — using a mechanism that is unique to Claude Code among CoDev's five platforms.

## Constraints

- V1 is macOS-verified, matching the precedent set by `skill-eval` and `nvidia-skill-evaluator`;
  Windows compatibility is deferred risk, not a V1 acceptance requirement. Linux is likely fine
  (hook scripts are POSIX shell) but is not itself verified, so it's called out rather than
  assumed.
- No network calls, no credentials, no containers — the same posture as every other adapter and
  as `docs/architecture.md`'s stated invariants.
- Must not alter behavior for existing Codex/Junie/OpenCode/Antigravity installs.
  `--agent-platform all` gaining a fifth platform is an intentional, CHANGELOG-called-out behavior
  change for anyone who re-runs `codev update --agent-platform all`.
- Exact Claude Code subagent/hook/settings schema is not to be trusted from public docs alone —
  it must be verified against the actually-installed Claude Code CLI version before this design
  moves to Accepted (Phase 0 in design.md), mirroring how `nvidia-skill-evaluator` pinned an
  exact verified commit rather than trusting NVIDIA's docs page.
