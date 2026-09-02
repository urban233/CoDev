# Product Map

This is a living reference, not a decision record. Unlike the ADRs it
complements, it has no `Status` field and is expected to be edited directly
as CoDev's surface changes, rather than superseded by a new document. Its job
is to say what CoDev currently *is*, in one place, so that a new capability
gets checked against the whole product before it's added, not judged only on
its own merits. `docs/architecture.md` stays scoped to the distribution
model (how the bundle is built, installed, and updated); this document is
the product itself — the skills, agents, and CLI surface a developer
actually uses once CoDev is installed.

Surface inventory current as of 2026-08-31.

## Identity

CoDev is for one audience: a developer, or a small team, using it to build
their own product in a repository that has CoDev installed. Every command,
skill, and agent below exists to serve that one relationship — a human
directing AI-assisted work in their own repository. Where CoDev's own
repository uses these same capabilities on itself (running its own eval
tasks against its own skills), that is CoDev dogfooding its product, not
a second audience the product is designed for.

## Terminology

One concept, one name, checked here rather than left to drift per document
(the discipline a companion review of external design-doc conventions
surfaced as CoDev's one gap, see ADR-0023). Where a rename supersedes an
older term, only the new term is current — the old one survives only inside
already-published ADRs and historical session transcripts, which are not
rewritten.

| Concept | Current term | Superseded |
|---|---|---|
| The unit `codev task` tracks round-state for | **task**, `task_id` | work item, `work_item_id` (ADR-0023) |
| Round-state's on-disk location | `.codev/task/` | `.codev/work/` (ADR-0023) |
| GitHub's tracker artifact for a task | **issue** | ticket, bug |
| Session entry point for Specify/Understand/Design/Plan | **`planner`** | — (new, ADR-0024) |
| Session entry point for Build/Review/Ship | **`orchestrator`** | — |
| A durable, cross-cutting decision that outlives one design document | **ADR** (Architecture Decision Record), `design-solution`'s `assets/adr.template.md`, stored at `docs/adr/NNNN-slug.md` | decision, `assets/decision.template.md` (ADR-0025) |
| The Plan-phase skill, and the planning unit it details one at a time | **`plan-wave`**, **wave** | plan-delivery, milestone (ADR-0032) |

## The phase spine

```text
Specify -> Understand -> Design -> Plan -> Build -> Review -> Ship -> Launch
```

Build and Ship are the only universal phases — every path reaches them, down
to the smallest case (a bounded fix with an obvious implementation, no
upstream artifact at all). Everything else is an on-ramp or off-ramp that a
given task may skip, matching the existing design principle "deeper
design and wave planning appear only when risk or coordination requires
them" (README, Design principles).

| Phase | Entry condition | Skipped when |
|---|---|---|
| Specify | New greenfield product, or an explicit whole-product redesign | Almost always — this is the rare entry point, not the default one |
| Understand | Default entry for both a brand-new idea and an existing (brownfield) product's feature request | Never for anything beyond a trivial, obvious change |
| Design | Real architecture, contract, or cross-component trade-off risk | Local, low-risk change with an obvious implementation |
| Plan | Multi-developer or multi-wave coordination is needed | One bounded, single-developer change |
| Build | Always | Never |
| Review | Always | Never |
| Ship | Always | Never |
| Launch | Real rollout risk: flags, migration, staged exposure | Internal or low-risk change |

Brownfield work overwhelmingly enters at Understand or directly at Build; a
whole-product redesign is the one brownfield case that legitimately re-enters
at Specify (`specify-project`'s own scope explicitly includes it).

## Surface inventory

Three tables follow: the CLI commands, the named skills, and the agents.
Together they are the whole surface a developer touches once CoDev is
installed, which is what makes them the place to check a proposed capability
against -- including whether something already here covers it.

### CLI commands

| Command | Phase | Purpose |
|---|---|---|
| `init` / `diff` / `update` / `remove` | Cross-cutting | Install, preview, apply, or remove the bundle itself |
| `status [--verbose] [--json]` | Cross-cutting | Bundle health, installed adapters, open tasks, WIP-per-owner and changed-file overlap |
| `adapter list/add/verify` | Cross-cutting | Manage and structurally verify one platform adapter |
| `config get/set/list` | Cross-cutting | Layered configuration (flags > env > project > global > default) |
| `self version/update` | Cross-cutting | Installed-tool version and upgrade guidance |
| `codeowners init` | Ship (one-time setup) | Scaffold a starter `.github/CODEOWNERS`; human-run directly, never agent-invoked |
| `task start/record/check/close/status/log/triage/escalate/escalations` | Build, Review | Read/write one task's round state; read-only w.r.t. product source (ADR-0001). `start --entry {takeover,direct-review}` (ADR-0006) marks whether the item's code is unfinished human work joining the inner loop, or finished human work going straight to the outer loop |
| `git issue-create/branch/commit/push/open-pr/mark-ready` | Understand (issue-create only), Build, Ship | The only path to mutating the repository or GitHub; `issue-create` alone has no task precondition |
| `eval task create/run` / `eval benchmark run` | Cross-cutting | General-purpose skill-evaluation harness — bring your own skill or agent, in your own repository, and test it with OpenCode; not limited to CoDev's bundled skills |
| `eval show <skill>` | Cross-cutting | Render a skill's packaged eval trace (`.agents/skills/<skill>/evals/benchmark.json`), written automatically by an unrestricted `eval benchmark run` (ADR-0028) |

### Named skills (all manually invoked by name, unless noted)

| Skill | Phase | Invocation today |
|---|---|---|
| `specify-project` | Specify | Manual, or the human-started entry point for a `planner` session |
| `define-product` | Understand | Manual, selected by `orchestrator` when a build surfaces an unresolved product question, or the entry point for a `planner` session |
| `design-solution` | Design | Manual, selected by `orchestrator` when a build surfaces an architectural question, or the entry point for a `planner` session |
| `plan-wave` | Plan | Manual, selected by `orchestrator` when a build surfaces a dependency/assignment problem, or the entry point for a `planner` session |
| `build-change` | Build | Selected by `orchestrator` to frame every three-agent build, or manual standalone |
| `review-change` | Review | Manual only — the zero-ceremony path for a diff with no task and no open PR |
| `critique-review` | Review (downstream) | Manual only — consumes another review's findings, does not itself review |
| `pr-review` | Review (existing PR) | Manual only as a guided skill; its fetch *script* is reused mechanically by `outer-loop-runner` step 1 |
| `audit-google-python-style` | Review / pre-Ship | Manual only, by explicit design ("invoke only when the user explicitly requests") |
| `audit-google-typescript-style` | Review / pre-Ship | Manual only, by explicit design |
| `github-actions-ci-results` | Ship | Manual only as a guided skill; reused mechanically by `outer-loop-runner` step 1 |
| `design-skill-eval` | Cross-cutting | Manual — scaffolds a new eval task for an existing skill |
| `technical-writing-style` | Cross-cutting | Read automatically by `specify-project`, `define-product`, `design-solution`, `plan-wave`, and `launch-product` before they draft or revise prose; also manual, to audit or revise the writing quality of an existing document |
| `testing-craft` | Cross-cutting | Read automatically by `specify-project` and `design-solution` before they decide test strategy and by `build-change` before it writes tests; `correctness-tests-specialist` uses its references as review criteria; also manual, to design a test strategy, audit an existing test suite's health, or triage a flaky test |
| `launch-product` | Launch | Manual — not referenced by `orchestrator` |

Per ADR-0005, the review family is now two clusters rather than an
undifferentiated six: `review-change`, `pr-review`, and `critique-review`
stay manual/on-demand, each for a genuinely on-demand case (no task, an
already-posted PR, or a downstream finding-to-diff bridge); `code-audit` and
the two `audit-google-*-style` skills it dispatches are mechanical,
catalog-driven, and no longer purely manual — a pre-PR gate runs
automatically immediately before every PR opens, now via the dedicated
`code-audit-gate` subagent rather than `code-audit` itself (ADR-0015).
`clean-code-review` is retired — its catalog absorbed into
`architecture-maintainability-specialist` below, not kept as a seventh
rail.

### Agents (full role set on OpenCode and Claude Code)

Junie and Antigravity no longer carry this table's role set (ADR-0031): each
ships a single `assistant` role for bounded, surgical edits, decoupled from
the task lifecycle. Codex is dropped entirely (ADR-0031).

| Agent | Phase | Invocation today |
|---|---|---|
| `orchestrator` | Build (session entry point) | Human-started; chains the rest of this table automatically within one session |
| `planner` | Specify, Understand, Design, Plan (session entry point) | Human-started, separate entry point from `orchestrator`; wraps `specify-project`/`define-product`/`design-solution`/`plan-wave` in one session and never invokes `builder`/`reviewer`/`orchestrator` (ADR-0024). Can short-circuit straight to `codev git issue-create` once a task is ready, without a wave plan |
| `builder` | Build | Auto-invoked by `orchestrator` |
| `lightweight-reviewer` | Review (inner loop) | Auto-invoked by `orchestrator`, fresh context each round |
| `outer-loop-runner` | Review -> Ship (session entry point) | Human-started, separate entry point from `orchestrator`; does not run on a PR event |
| `correctness-tests-specialist`, `security-data-specialist`, `concurrency-specialist`, `architecture-maintainability-specialist`, `rollout-specialist` | Review (outer loop) | Auto-dispatched in parallel by `outer-loop-runner`. `architecture-maintainability-specialist` now carries the Clean Code/Gang-of-Four catalog absorbed from the retired `clean-code-review` skill (ADR-0005); `correctness-tests-specialist` judges `test_quality` against `testing-craft`'s references |
| `code-audit` | Review / pre-Ship | Human-invoked only (ADR-0015): the full two-phase, human-approval-gated audit-and-fix workflow. No longer has an automatic pre-PR invocation mode — that responsibility moved entirely to `code-audit-gate` below, since Phase 1's audit-only pass never needed the approval gate that makes this agent `mode: primary` in the first place |
| `code-audit-gate` | Build (pre-PR gate) | Auto-invoked by `orchestrator`, between the builder's round and `lightweight-reviewer`'s dispatch (ADR-0015). Always-autonomous subagent, style/documentation scope only, never logic — self-fixes and reports back rather than stopping for approval. Resolves before the reviewer round is recorded, so it never opens the outer phase or spends any of its round cap |

## Directions and open questions

**Resolved and implemented (ADR-0005):** the review family is consolidated —
`code-audit`/`audit-google-*-style` auto-gate before every PR;
`clean-code-review` is retired, its catalog absorbed into
`architecture-maintainability-specialist`; `review-change` stays as the
explicit zero-ceremony path; `pr-review` and `critique-review` confirmed
correctly on-demand, unchanged. `orchestrator`'s Build-only scope (never
naming `specify-project`/`launch-product`) is confirmed deliberate, not a
gap — neither phase has a build-and-review loop to orchestrate.

**Resolved and implemented (ADR-0024):** the Specify/Understand/Design/Plan
phases gain their own human-started session entry point, `planner`, decoupled
from `orchestrator`'s Build/Review/Ship scope above — the two are
independent entry points a human chooses between, neither invoking the
other. `planner` also gains an issue-only short circuit: given an accepted
design or decision, draft a task and run `codev git issue-create` directly,
skipping `plan-wave`'s wave/work-list machinery, and stop —
`orchestrator`'s existing step-5 fallback (create the issue itself if still
missing) is unchanged and still correct either way.

**Resolved and implemented (ADR-0025):** `design-solution`'s decision asset
is formalized into an explicit ADR practice — renamed `assets/adr.template.md`
(was `decision.template.md`), with a fixed storage convention
(`docs/adr/NNNN-slug.md`, sequential four-digit numbering) and an explicit
append-only rule once `Accepted` (a later reversal writes a new ADR and marks
the old one `Superseded by ADR-NNNN`, never edits it). This repository now
practices it on itself too, documented at `docs/adr/README.md`.

**Resolved and implemented (ADR-0006):** task entry modes give
human-authored work a first-class path into the inner/outer loop instead of
funneling everything through `review-change`. `--entry takeover` opens round
1 in the inner phase and tells `builder` to continue an already-started
human diff rather than replace it; `--entry direct-review` opens round 1
directly in the outer phase, and `codev task check` now reports
`ok_ready_for_pr` for a fresh `direct-review` item with nothing recorded yet
— previously indistinguishable from `stop_drift`. A guided "next item from
the shelf" CLI command was considered and dropped in the same ADR: GitHub's
own Issues list, populated via `codev git issue-create` (ADR-0004), already
covers it without a second, CoDev-specific mechanism.

**Resolved and implemented (ADR-0015):** `code-audit`'s automatic pre-PR
gate mode is retired in favor of a new, dedicated subagent,
`code-audit-gate` — the two were always doing different jobs under one
`mode: primary` agent: a human-approval-gated audit-and-fix workflow, and a
narrower, always-autonomous audit-and-fix pass with no approval step to
gate. Splitting them also fixed a round-cap bug the automatic mode's old
routing had: recording its findings as an outer-phase round could spend
both of that phase's rounds on mechanical style fixes before the five
specialists ever ran once. `code-audit-gate` now resolves entirely before
the reviewer round is recorded, so it never opens the outer phase at all.

**Resolved and implemented (ADR-0032, ADR-0033):** `plan-delivery` is
renamed `plan-wave` and its rolling-wave discipline — detail only the
current wave, keep later waves coarse — is backed by a deterministic,
ask-posture Claude Code gate (`require_wave_shape.py`) instead of prose
alone. `git.workflow` (`trunk` by default, `feature-branch` as a
first-class override) lets `plan-wave` and `build-change` slice a wave's
tasks at an engineering-dependency boundary instead of only a usefulness
boundary, provided the task names its containment. `design-solution` is
unchanged.

**Still open:**

- Now that `eval` is understood as a general, adopter-facing capability
  rather than a maintainer side-channel, should the README's "Why CoDev"
  pitch name it? It is currently one of the largest single capabilities in
  the product and is not mentioned there.

## Non-goals

- Does not change `codev task`'s round-state schema or file-based storage
  beyond ADR-0006's additive `entry` field and ADR-0023's terminology
  rename (`work item` -> `task`, `.codev/work/` -> `.codev/task/`,
  `work_item_id` -> `task_id`) — ADR-0001's underlying decision to track
  state as local JSON files still stands.
- **Resolved and implemented (ADR-0031):** the Codex adapter is dropped
  entirely; Junie and Antigravity are narrowed to a single `assistant` role,
  decoupled from the task lifecycle.
- Does not relax `code-audit`'s no-delegation guardrail — the guardrail is
  about it calling other agents, not about being called by `orchestrator`,
  and ADR-0005 left it textually unchanged.
- Does not restructure the CLI's command tree (e.g. moving `codeowners`
  under `git`, splitting `task`'s subcommands) — surfaced in the inventory
  above, not decided here.
