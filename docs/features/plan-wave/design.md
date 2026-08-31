**Status:** Accepted
**Owner:** Martin Urban
**Reviewers:** Martin Urban (accountable owner; implemented in the same session, no separate domain review recorded)
**Brief:** [brief.md](./brief.md)
**Last reviewed:** 2026-08-31

## Summary

Rename `plan-delivery` to `plan-wave` and make rolling-wave planning the
enforced default: a session can produce a detailed, ready-to-build task
table only for the current wave, backed by deterministic, ask-posture gates
rather than the single advisory sentence that carries this today. Add a new
`git.workflow` config key (`trunk` by default, `feature-branch` as a
first-class override), built on the exact mechanism ADR-0013 already
established for `git.pr_base`, so `plan-wave` and `build-change` can slice a
wave's tasks along engineering-dependency order instead of forcing every
task to be independently useful. `design-solution` needs no changes.

## Goals and non-goals

### Goals

- Rolling-wave planning is a checked property of the wave-plan document and
  the issue-creation path, not a rule a session can silently skip.
- Every new gate defaults to asking and pausing, matching the posture
  ADR-0030 already established, never a hard refusal.
- Trunk-based development is the default git workflow, with
  `feature-branch` as a fully supported, not degraded, override.
- `plan-wave` keeps its existing team-profile gate, capability lanes,
  reviewer capacity, and WIP-limit machinery unchanged.

### Non-goals

- The `Pair`/`Bounded delegate` work-style split and the hard separation
  between `planner` and `orchestrator` sessions. Related — it shares this
  design's root cause, an agent-judged binary switch instead of a tunable,
  deterministic check — but scoped as a separate follow-on so this change
  stays independently reviewable.
- Any change to `design-solution`'s own steps or template.
- CoDev shipping, bundling, or managing actual feature-flag infrastructure
  for a target repository.

## Current system and evidence

Confirmed by direct repository inspection (2026-08-31):

- `plan-delivery/SKILL.md` step 2 already says: *"Plan the current milestone
  in detail. Keep later milestones coarse and revise them using evidence
  from working software."* That is the entire mechanism today — one
  sentence, no gate. Its own Handoff step pushes a ready item to
  `codev git issue-create` with nothing that checks which wave the item
  belongs to. `docs/codev/delivery/` — the skill's own stated default output
  location — holds no files; this repository has never exercised the skill
  on itself. `docs/plans/phase-6-cleanup-and-promotion.md` is a real,
  fully-scoped four-task plan for a deliberately deferred phase, unrevisited
  since, and outside every current planning-artifact location — a live
  example of the failure mode.
- `build-change/SKILL.md` step 3 requires each task to remain "buildable and
  useful," and explicitly allows splitting a task only "when each part
  remains buildable and useful" — no path today for a task that is safe to
  merge but not independently valuable, such as an isolated schema change
  ahead of the logic that uses it.
- `git.pr_base` (ADR-0013) is CoDev's only config key today. `config.py`
  resolves any key through one function, `resolve(key, *, target, override)`
  — flag, then `CODEV_<KEY>` env var, then `.codev/config.toml` project
  values, then a global config file, then `DEFAULTS` (currently an empty
  dict, by design: `"Populated as features grow their own config keys...
  Intentionally empty until a feature needs one"`). `set_value` writes
  through the same TOML file, quoting both key and value so a dotted key
  like `git.workflow` round-trips correctly — ADR-0013 already fixed the one
  bug class this could hit.
- `.claude/hooks/require_plan.py` (bundle source; see below) is the one
  real, shipped precedent for a deterministic, ask-posture gate. It gates
  `Edit`/`Write`/`MultiEdit`/`NotebookEdit` and a fixed list of destructive
  `Bash` prefixes, fails open on any internal error, and already excludes
  every path starting with `docs/` from gating entirely — confirmed at
  `require_plan.py:163`, `if relative.parts and relative.parts[0] ==
  "docs": _allow()`. Its spec-exists check has two layers: a precise
  filesystem check against `docs/codev/task/<task-id>/implementation-plan.md`
  when the branch follows `codev git branch`'s `codev/<task-id>` naming, and
  a coarse fallback that matches the branch's slug against
  `docs/features/*/design.md` or `docs/codev/features/*/design.md`.
- This repository's own root `.claude/` directory is not a CoDev-managed
  install — it holds only a local `launch.json`, no `agents/`, `hooks/`, or
  `settings.json`. None of ADR-0030's guardrails are live here today; this
  design's new gates can be verified by the same fixture-stdin tests
  `test_claude_hook.py` already established, but not by observing them fire
  in a live session against this repository until `codev update
  --agent-platform claude` is run here.
- Per `docs/product-map.md`, the full role set — and therefore this hook
  mechanism — exists only for OpenCode and Claude Code (ADR-0031 narrowed
  Junie and Antigravity to a single `assistant` role and dropped Codex).
  ADR-0030 scoped its guardrail to Claude Code specifically because it is
  "the one platform in CoDev's lineup with a native, structural mechanism
  for addressing exactly this... which none of the other four platforms
  expose in the same way." The same reasoning applies here: OpenCode's
  `permission.bash`/`permission.task` system allow-lists or denies a command
  pattern outright; it has no primitive for "ask, informed by current
  repository file state," so it cannot run the same check.

## Proposed design

### Components and ownership

| Component | Responsibility | Owner | Existing or new |
|---|---|---|---|
| `plan-wave` skill (renamed from `plan-delivery`) | Wave-scoped planning; detail only the current wave | `.agents/skills/plan-wave/SKILL.md` | Renamed |
| `wave-plan.template.md` (renamed from `delivery-plan.template.md`) | Current-wave task table vs. coarse later-wave bullets | `.agents/skills/plan-wave/assets/` | Renamed |
| `git.workflow` config key | Selects `trunk` (default) or `feature-branch` | `config.py` | New |
| `require_wave_shape.py` | Wave-shape lint and the issue-creation wave-boundary check | `.claude/hooks/` | New |
| Plan-wave existence check | Extends the coarse-fallback glob to also recognize `docs/codev/wave/*.md` | `.claude/hooks/require_plan.py` | Extended |
| Task issue template containment field | Optional description of how incomplete work stays contained | `.github/ISSUE_TEMPLATE/task.md` | Extended |
| Implementation-plan containment field | Same, for the implementation-plan artifact | `build-change/assets/implementation-plan.template.md` | Extended |
| Workflow-aware slicing guidance | Task-splitting rule reads `git.workflow` | `plan-wave/SKILL.md`, `build-change/SKILL.md` | Updated prose |

### Data and control flow

A developer with an accepted brief, and an accepted design where real
architectural risk exists, runs `plan-wave` once per wave. Each run reads
the wave-plan document's current state and the repository's evidence,
details only the next wave's task table, and leaves later waves as coarse
statements. Saving the document triggers `require_wave_shape.py`'s lint: a
non-current wave section holding a populated task table is a violation, and
the hook asks for confirmation rather than allowing the save silently.

Pushing a ready task with `codev git issue-create` re-runs the same
violation check against the wave-plan document before the command
proceeds. If the document is currently well-formed, the command proceeds
without interruption, matching today's behavior. If it is not, the hook
asks — this checks the document's overall shape, not which specific wave
the issue being created targets; see Alternatives and trade-offs for why.

Once a wave's tasks build under `build-change`, workflow-aware slicing
applies when `git.workflow` resolves to `trunk`: a task may split at an
engineering-dependency boundary rather than only a usefulness boundary,
provided it names its containment. Closing a wave runs the existing
evidence check plus a bounded hardening pass when the evidence calls for
one, before the next wave's detail is allowed to start — the revisit
checkpoint named in the brief.

### APIs and contracts

| API/contract | Owner | Consumers | Guarantees | Errors/timeouts | Compatibility | Test/fixture |
|---|---|---|---|---|---|---|
| `config.resolve("git.workflow", target=target)` | `config.py` | `plan-wave`/`build-change` prose, `require_wave_shape.py`, `require_plan.py` | Flag > env > project > global > default; `DEFAULTS["git.workflow"] = "trunk"` | Returns `None` only if `DEFAULTS` is bypassed by a caller error; an unrecognized string value is not validated at this layer | New key; no config schema version change | Config round-trip test mirroring `PersistenceTests`'s existing dotted-key regression test |
| `require_wave_shape.py` `PreToolUse` hook | `.claude/hooks/` | Claude Code's hook runner | Asks, never denies, on a wave-shape violation at `Edit`/`Write` to `docs/codev/wave/*.md` or at a `Bash` command starting `codev git issue-create` while a violation exists; fails open on any internal error | Unparseable stdin or an unexpected payload shape allows the call | New file; Claude-Code-only in this release | Fixture-stdin tests mirroring `test_claude_hook.py`'s pattern |
| Containment field (task and implementation-plan templates) | Template owners | The human or agent authoring a task | Free text; blank when `git.workflow` is not `trunk` or the task stands alone | None — advisory, not machine-checked in this release | Additive template field | Manual review; no automated test for free text |

## Alternatives and trade-offs

| Decision | Option | Benefits | Costs/risks | Recommendation |
|---|---|---|---|---|
| Issue-boundary check precision | Match the issue's title or body against a specific wave row | Would catch the exact violation this is meant to prevent | Fragile string inference against free-text titles; no reliable link between an issue-create call and a specific plan-doc row without a new `--wave` flag | Rejected for this release |
| Issue-boundary check precision | Reuse the wave-shape lint's whole-document check at issue-create time (this design) | One mechanism, two trigger points; no new CLI surface; consistent with `require_plan.py`'s own "does a spec exist," not "does this exact edit match it" scoping | Can ask when the specific issue actually is for the current wave but an unrelated later-wave section is malformed, and can stay silent for a future-wave issue when the document's shape is otherwise fine | **Recommended** |
| Issue-boundary check precision | Add a `--wave` flag to `codev git issue-create` for an exact match | Precise | New CLI surface, new required argument on an existing command, a bigger change than this release's scope | Deferred — possible future refinement, not committed |
| Gate implementation surface | Extend `require_plan.py` directly | One fewer file | Mixes two different concerns — "does a plan exist" and "is the existing wave-plan document well-formed" — the same reasoning that split `code-audit-gate` from `code-audit` (ADR-0015) | Rejected |
| Gate implementation surface | New sibling hook, `require_wave_shape.py` (this design) | Clean separation of concerns; independently testable | One more file to register in `.claude/hooks/` and `pyproject.toml` package data | **Recommended** |
| Gate platform scope | Claude Code only (this design) | Matches ADR-0030's own precedent and its stated reason — no other current platform exposes an equivalent primitive | OpenCode sessions get no new mechanical enforcement, only the updated prose | **Recommended** |
| Gate platform scope | Also add OpenCode `permission.bash` rules | Some coverage on OpenCode too | OpenCode's permission system allow-lists or denies a command pattern outright; it cannot run repository-state-dependent logic, so it could only hard-deny or hard-allow `codev git issue-create`, not ask conditionally | Rejected — wrong primitive for what this needs |
| `git.workflow` key granularity | One key drives both branch-lifetime guidance and slicing/containment guidance (this design) | Matches `git.pr_base`'s precedent of one key, one concern; simplest to explain | May turn out too coarse if a project wants trunk-style slicing without branch-lifetime nudges, or vice versa | **Recommended**, flagged as an assumption to test during implementation |
| `git.workflow` key granularity | Two separate keys | More precise if the two concerns diverge in practice | Two things to explain and keep in sync for no evidence yet of a real need | Deferred unless the assumption above fails |
| Containment mechanism | CoDev ships or manages real feature-flag infrastructure | Precise, potentially machine-checkable | Contradicts a target repository never importing CoDev as a runtime dependency; wrong scale of tooling for a solo-to-ten-engineer audience | Rejected |
| Containment mechanism | A free-text field the human or agent fills in (this design) | Zero new dependency; works with whatever mechanism a project already has, including none | Not machine-checked — a human can write a description that does not match reality | **Recommended** |

## Quality and risk

- **Security/privacy:** `require_wave_shape.py` reads only local repository
  file state and resolved config values, the same posture as
  `require_plan.py` — no network access, no secrets, no credentials.
- **Reliability:** the new hook fails open on any internal error, exactly
  like `require_plan.py`; a bug in this gate degrades to "no extra check,"
  never to "no issue-creation possible."
- **False positive/negative risk, named explicitly:** the whole-document
  check is not per-issue-precise. It can ask when the triggering issue
  genuinely is for the current wave but an unrelated later-wave section is
  malformed, and it can stay silent when an issue targets a future wave
  while the document's overall shape happens to be fine. Both outcomes cost
  at most one confirmation click or one missed nudge — never a block and
  never data loss.
- **Compatibility:** the new gates are Claude-Code-only in this release, a
  deliberate scope limit (see Alternatives), not a regression — OpenCode
  sessions keep exactly the guidance they have today, expressed in updated
  prose.
- **Observability:** consider a local, gitignored decision log under
  `.codev/`, the same pattern already flagged as worth considering for
  `require_plan.py` and not yet built for it either — not blocking for this
  release.

## Test strategy

Fixture-stdin tests for `require_wave_shape.py`, pinned against fake JSON
payloads covering the well-formed document, the violated document, and the
`codev git issue-create` trigger path — the same pattern `test_claude_hook.py`
already uses for `require_plan.py`, so it needs no real Claude Code install.
A config round-trip test for `git.workflow` mirrors `PersistenceTests`'s
existing dotted-key regression test. `build-change`'s and `plan-wave`'s
updated slicing prose is exercised through the existing
`scripts/validate-development-workflow.py` behavioral scenario catalog,
extended with one new scenario covering a workflow-aware split.

## Migration, rollout, rollback, and cleanup

Purely additive. The `plan-delivery` to `plan-wave` rename is a hard break
with no dual-support window, following ADR-0023's precedent — nothing
persists the old name in state or schema, so no migration script is needed,
only the mechanical file and reference updates the brief already lists.

`git.workflow` defaulting to `trunk` for every adopter who does not set it
is a real behavior change the moment this ships, not something a project
opts into — the updated slicing prose and the new gates apply immediately
on update. Call this out explicitly in the changelog, the same way the
Claude Code adapter's platform-count change was. Rollback for an individual
project is `codev config set git.workflow feature-branch`; because every
gate here only ever asks, declining a prompt costs nothing further. Because
this repository's own root has no installed Claude Code adapter yet, this
design's gates need `codev update --agent-platform claude` run against this
repository, or a scratch install, before they can be observed live here —
fixture-stdin tests do not depend on that.

## Open questions

| Question | Owner | Evidence needed | Blocking? |
|---|---|---|---|
| ~~Does wave-scoping get an explicit step classifying a wave's uncertainty as requirements-shaped or architecture-shaped, or stay implicit judgment under the existing risk-level field?~~ | Martin Urban | Resolved 2026-08-31: explicit named step. Implemented in `plan-wave/SKILL.md` step 2. | Resolved |
| Does one `git.workflow` value cleanly drive both branch-lifetime guidance and slicing/containment guidance? | Implementer | Prototype against one real multi-wave feature during implementation | No — ship with one key, split later if this fails |
| Is the wave-shape lint's whole-document check (not per-issue-precise) an acceptable trade-off long-term, or does it need the `--wave` flag alternative? | Martin Urban | Real usage evidence after this ships | No — named limitation, not a blocker |

## Acceptance

- [x] Material decisions resolved, including both blocking open questions above.
- [x] Required domain review complete (accountable owner, no separate reviewer for this dogfooded change).
- [x] Accountable human accepts planning against this design.
