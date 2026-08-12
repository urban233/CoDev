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

Surface inventory current as of 2026-08-12.

## Identity

CoDev is for one audience: a developer, or a small team, using it to build
their own product in a repository that has CoDev installed. Every command,
skill, and agent below exists to serve that one relationship — a human
directing AI-assisted work in their own repository. Where CoDev's own
repository uses these same capabilities on itself (running its own eval
fixtures against its own skills), that is CoDev dogfooding its product, not
a second audience the product is designed for.

## The phase spine

```text
Specify -> Understand -> Design -> Plan -> Build -> Review -> Ship -> Launch
```

Build and Ship are the only universal phases — every path reaches them, down
to the smallest case (a bounded fix with an obvious implementation, no
upstream artifact at all). Everything else is an on-ramp or off-ramp that a
given work item may skip, matching the existing design principle "deeper
design and delivery planning appear only when risk or coordination requires
them" (README, Design principles).

| Phase | Entry condition | Skipped when |
|---|---|---|
| Specify | New greenfield product, or an explicit whole-product redesign | Almost always — this is the rare entry point, not the default one |
| Understand | Default entry for both a brand-new idea and an existing (brownfield) product's feature request | Never for anything beyond a trivial, obvious change |
| Design | Real architecture, contract, or cross-component trade-off risk | Local, low-risk change with an obvious implementation |
| Plan | Multi-developer or multi-milestone coordination is needed | One bounded, single-developer change |
| Build | Always | Never |
| Review | Always | Never |
| Ship | Always | Never |
| Launch | Real rollout risk: flags, migration, staged exposure | Internal or low-risk change |

Brownfield work overwhelmingly enters at Understand or directly at Build; a
whole-product redesign is the one brownfield case that legitimately re-enters
at Specify (`specify-project`'s own scope explicitly includes it).

## Surface inventory

### CLI commands

| Command | Phase | Purpose |
|---|---|---|
| `init` / `diff` / `update` / `remove` | Cross-cutting | Install, preview, apply, or remove the bundle itself |
| `status [--verbose] [--json]` | Cross-cutting | Bundle health, installed adapters, open work items, WIP-per-owner and changed-file overlap |
| `adapter list/add/verify` | Cross-cutting | Manage and structurally verify one platform adapter |
| `config get/set/list` | Cross-cutting | Layered configuration (flags > env > project > global > default) |
| `self version/update` | Cross-cutting | Installed-tool version and upgrade guidance |
| `codeowners init` | Ship (one-time setup) | Scaffold a starter `.github/CODEOWNERS`; human-run directly, never agent-invoked |
| `work start/record/check/close/status/log/triage/escalate/escalations` | Build, Review | Read/write one work item's round state; read-only w.r.t. product source (ADR-0001). `start --entry {takeover,direct-review}` (ADR-0006) marks whether the item's code is unfinished human work joining the inner loop, or finished human work going straight to the outer loop |
| `git issue-create/branch/commit/push/open-pr/mark-ready` | Understand (issue-create only), Build, Ship | The only path to mutating the repository or GitHub; `issue-create` alone has no work-item precondition |
| `eval fixture create/run` / `eval snapshot run` | Cross-cutting | General-purpose skill-evaluation harness — bring your own skill or agent, in your own repository, and test it with OpenCode; not limited to CoDev's bundled skills |

### Named skills (all manually invoked by name, unless noted)

| Skill | Phase | Invocation today |
|---|---|---|
| `specify-project` | Specify | Manual |
| `define-product` | Understand | Manual, or selected by `orchestrator` when a build surfaces an unresolved product question |
| `design-solution` | Design | Manual, or selected by `orchestrator` when a build surfaces an architectural question |
| `plan-delivery` | Plan | Manual, or selected by `orchestrator` when a build surfaces a dependency/assignment problem |
| `build-change` | Build | Selected by `orchestrator` to frame every three-agent build, or manual standalone |
| `review-change` | Review | Manual only — the zero-ceremony path for a diff with no work item and no open PR |
| `critique-review` | Review (downstream) | Manual only — consumes another review's findings, does not itself review |
| `pr-review` | Review (existing PR) | Manual only as a guided skill; its fetch *script* is reused mechanically by `outer-loop-runner` step 1 |
| `audit-google-python-style` | Review / pre-Ship | Manual only, by explicit design ("invoke only when the user explicitly requests") |
| `audit-google-typescript-style` | Review / pre-Ship | Manual only, by explicit design |
| `github-actions-ci-results` | Ship | Manual only as a guided skill; reused mechanically by `outer-loop-runner` step 1 |
| `design-skill-eval` | Cross-cutting | Manual — scaffolds a new eval fixture for an existing skill |
| `launch-product` | Launch | Manual — not referenced by `orchestrator` |

Per ADR-0005, the review family is now two clusters rather than an
undifferentiated six: `review-change`, `pr-review`, and `critique-review`
stay manual/on-demand, each for a genuinely on-demand case (no work item, an
already-posted PR, or a downstream finding-to-diff bridge); `code-audit` and
the two `audit-google-*-style` skills it dispatches are mechanical,
catalog-driven, and now auto-gate immediately before every PR opens, no
longer purely manual. `clean-code-review` is retired — its catalog absorbed
into `architecture-maintainability-specialist` below, not kept as a seventh
rail.

### Agents (four platform copies each: OpenCode, Codex, Junie, Antigravity)

| Agent | Phase | Invocation today |
|---|---|---|
| `orchestrator` | Build (session entry point) | Human-started; chains the rest of this table automatically within one session |
| `builder` | Build | Auto-invoked by `orchestrator` |
| `lightweight-reviewer` | Review (inner loop) | Auto-invoked by `orchestrator`, fresh context each round |
| `outer-loop-runner` | Review -> Ship (session entry point) | Human-started, separate entry point from `orchestrator`; does not run on a PR event |
| `correctness-tests-specialist`, `security-data-specialist`, `concurrency-specialist`, `architecture-maintainability-specialist`, `rollout-specialist` | Review (outer loop) | Auto-dispatched in parallel by `outer-loop-runner`. `architecture-maintainability-specialist` now carries the Clean Code/Gang-of-Four catalog absorbed from the retired `clean-code-review` skill (ADR-0005) |
| `code-audit` | Review / pre-Ship | Two modes (ADR-0005): a human may still invoke it directly for its full two-phase, human-approval-gated workflow; `orchestrator` also invokes it automatically, audit-only, immediately before every PR opens. Its "never invoke another agent" guardrail is about it calling out, not about being called into — unchanged either way |

## Directions and open questions

**Resolved and implemented (ADR-0005):** the review family is consolidated —
`code-audit`/`audit-google-*-style` auto-gate before every PR;
`clean-code-review` is retired, its catalog absorbed into
`architecture-maintainability-specialist`; `review-change` stays as the
explicit zero-ceremony path; `pr-review` and `critique-review` confirmed
correctly on-demand, unchanged. `orchestrator`'s Build-only scope (never
naming `specify-project`/`launch-product`) is confirmed deliberate, not a
gap — neither phase has a build-and-review loop to orchestrate.

**Resolved and implemented (ADR-0006):** work-item entry modes give
human-authored work a first-class path into the inner/outer loop instead of
funneling everything through `review-change`. `--entry takeover` opens round
1 in the inner phase and tells `builder` to continue an already-started
human diff rather than replace it; `--entry direct-review` opens round 1
directly in the outer phase, and `codev work check` now reports
`ok_ready_for_pr` for a fresh `direct-review` item with nothing recorded yet
— previously indistinguishable from `stop_drift`. A guided "next item from
the shelf" CLI command was considered and dropped in the same ADR: GitHub's
own Issues list, populated via `codev git issue-create` (ADR-0004), already
covers it without a second, CoDev-specific mechanism.

**Still open:**

- Now that `eval` is understood as a general, adopter-facing capability
  rather than a maintainer side-channel, should the README's "Why CoDev"
  pitch name it? It is currently one of the largest single capabilities in
  the product and is not mentioned there.

## Non-goals

- Does not change `codev work`'s round-state schema or file-based storage
  (ADR-0001's decision stands) beyond ADR-0006's additive `entry` field.
- Does not propose dropping or merging any of the four platform adapters
  (OpenCode, Codex, Junie, Antigravity).
- Does not relax `code-audit`'s no-delegation guardrail — the guardrail is
  about it calling other agents, not about being called by `orchestrator`,
  and ADR-0005 left it textually unchanged.
- Does not restructure the CLI's command tree (e.g. moving `codeowners`
  under `git`, splitting `work`'s subcommands) — surfaced in the inventory
  above, not decided here.
