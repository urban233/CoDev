# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/) and
Semantic Versioning.

## [Unreleased]

### Changed
- **Breaking:** `round-state.json` moves to schema version 2 (ADR-0002,
  ADR-0003). `codev work` round-state now supports a self-healing inner loop
  ending in a `READY_FOR_OUTER_LOOP` reviewer decision and a phase-tagged
  outer loop with a human-triage step, per work item:
  - New `READY_FOR_OUTER_LOOP` reviewer decision, exempt from the full
    coverage-completeness gate (`_incomplete_coverage`), and a new
    `ok_ready_for_pr` `codev work check` outcome.
  - Findings gain an optional `expansion_reason` (`regression` or
    `newly_discovered_critical`); a blocking finding introduced after a
    phase's first round with no `expansion_reason` now stops with
    `stop_scope_expansion` rather than silently expanding the round's scope.
  - Round entries are tagged `"phase": "inner" | "outer"`. `max_rounds`
    becomes phase-scoped (`{"inner": 2, "outer": 2}` by default); `start`
    still accepts a plain int, applied to both phases. The round cap and
    repeated-finding checks are now phase-local.
  - `REQUIRED_COVERAGE_DIMENSIONS`'s combined
    `security_privacy_data_concurrency_compatibility` key splits into
    `security_privacy_data_compatibility` and a new standalone
    `concurrency` key.
  - New `codev work triage` records the human's `address`/`defer`
    disposition for each blocking finding in an outer-loop round; deferring
    a blocking finding requires a non-empty `override_reason`. A new
    `ok_waiting_on_triage` check outcome gates opening the outer phase's
    correction round until triage is recorded.
  - No migration path: a v1 `round-state.json` is rejected by the existing
    version guard. Pre-1.0, consistent with this project's existing
    breaking-change policy.

### Added
- Add `codev git branch|commit|push|open-pr|mark-ready` (ADR-0002,
  ADR-0003): a guarded mutation surface so a work item's inner/outer loop
  can create its own branch, commit, push, and land a pull request without
  agents ever holding raw `git commit`/`git push`/`gh pr create` permission.
  Mechanically enforces, not by agent-prompt convention: operates only on
  the one branch it created for a work item, refuses any target resolving
  to the repository's default branch, never accepts or constructs a
  force-push flag, and independently re-verifies `codev work check` returns
  `ok_ready_for_pr`/`ok_approve` before `open-pr`/`mark-ready` proceed,
  rather than trusting the caller already checked. `open-pr` always creates
  a draft PR; `mark-ready` regenerates the PR body from the work item's
  round-state (via `codev work log`'s formatting) before converting it out
  of draft.
- Add `codev work escalate` / `codev work escalations [--since DATE]`
  (ADR-0003): a local, gitignored, append-only escalation log
  (`.codev/work/escalations.jsonl`) recording every human escalation --
  round-cap hit, drift, repeated finding, scope expansion, missing
  evidence, a pre-build critical interrupt, or a human overriding a
  blocking finding during triage -- with cause, phase, and round. Written
  explicitly by the caller; `codev work check` stays read-only and never
  logs as a side effect. Not yet done: `codev init`/`update` don't manage
  this entry in a target repository's `.gitignore` the way they already do
  for `AGENTS.md` -- tracked as follow-up work.
- Add a `lightweight-reviewer` role to all four platform adapters (ADR-0002):
  a narrow, fast inner-loop check -- correctness and intent-match against
  the work item, plus independent re-verification of the builder's reported
  validation -- distinct from the full-dimension `reviewer`, which remains
  available for other uses (e.g. `pr-review`). `orchestrator` no longer
  requires human plan-approval before every delegated build by default; it
  proceeds unless the existing "Stop conditions" or "Risk overrides size"
  categories apply, checked cheaply by path/diff-shape before any judgment
  call. On a clean pass it now creates the work item's branch, commits,
  pushes, and opens a draft pull request through the new `codev git`
  surface automatically -- merge remains the only human-gated step. Updated
  `docs/for-ai/ai-agent-guidelines.md`'s "Three-agent Build execution" and
  all four `orchestrator`/`builder`/`reviewer` bundle files to match, and
  extended `codev adapter verify` to require `lightweight-reviewer` and a
  `codev git open-pr` reference on every orchestrator, and to flag a raw
  `"git push*"`/`"git commit*": allow` permission as a retired pattern now
  that the guarded surface exists.
- Add a human-triggered `outer-loop-runner` role and five specialist
  reviewer roles (ADR-0003) to all four platform adapters:
  `correctness-tests-specialist`, `security-data-specialist`,
  `concurrency-specialist`, `architecture-maintainability-specialist`, and
  `rollout-specialist`, each scoped to a disjoint set of `codev work`'s
  coverage dimensions and none of them recording state directly. The
  `outer-loop-runner` fetches a pull request and gates on CI status before
  dispatching any specialist, merges their findings and coverage into one
  round, presents blocking findings to the human for an `address`/`defer`
  triage via `codev work triage`, drives the one permitted correction round
  scoped to only the selected findings, and lands the change with
  `codev git mark-ready` on approval. Updated
  `docs/for-ai/ai-agent-guidelines.md` with a matching "Outer-loop
  execution" section and `review-change`'s dimension list to give
  concurrency its own numbered item. Extended `codev adapter verify` to
  verify all ten roles per platform.
- `codev init`/`update`/`remove` now manage a small marked block in the
  target repository's `.gitignore` (create it if absent, merge into
  existing content otherwise) ignoring `.codev/work/escalations.jsonl`,
  the same safely-merged pattern already used for `AGENTS.md`. Backward
  compatible with installs that predate this: a missing block and no
  recorded hash integrate cleanly on the next `update` rather than
  conflicting. `codev status`/`check_project` flags a tampered block only
  for installs that already have one recorded.
- Add `--link`, `--summary`, `--owner`, and `--github-issue` to `codev work
  start`, and `--by` to `codev work triage` (ADR-0004): purely additive,
  optional traceability and identity fields on `round-state.json` -- no
  `ROUND_SCHEMA_VERSION` bump. `--owner`/`--by` default to a new
  `git_ops.detect_identity()` (the authenticated `gh` login, falling back to
  local git config, never fabricated) rather than requiring the human to
  type identity every time; `--github-issue N` populates `--link`/`--summary`
  from a read-only `gh issue view` unless given explicitly. `codev work
  check` now prints a non-blocking note when the same identity both owns a
  work item and triaged it, mirroring `plan-delivery`'s existing "owners do
  not approve their own changes" guidance with a data hook instead of only
  documentation.
- `define-product`, `design-solution`, `plan-delivery`, and `build-change`
  now default their planning-artifact locations under a common
  `docs/codev/` prefix (ADR-0004) -- `docs/codev/features/`,
  `docs/codev/product/`, `docs/codev/design/`, `docs/codev/delivery/`, and a
  new `docs/codev/work/<work-item-id>/implementation-plan.md`, keyed by the
  same id `codev work start` uses, closing the traceability gap for the one
  planning artifact that is genuinely 1:1 with a single work item. Each
  skill's existing instruction to defer to an established repository
  convention instead of forcing its own structure is unchanged, so an
  already-adopted repository's existing paths are unaffected.
- Add `codev git issue-create` (ADR-0004): the one operation in the guarded
  `codev git` surface with no work-item precondition, since pushing a
  delivery-plan work item to GitHub happens before `codev work start` exists
  for it. Takes explicit `--title`/`--body` (never parses a delivery plan's
  Markdown); an optional, repeatable `--path` prints a best-effort
  CODEOWNERS-suggested assignee without ever forwarding it as `--assignee`
  automatically. `codev git open-pr` separately appends `Closes #N` to the
  generated PR body when a work item's `--link` is a GitHub issue URL for
  the same repository, closing the loop for free on merge.
- Add `codev codeowners init` (ADR-0004): a one-shot local scaffold of a
  starter `.github/CODEOWNERS`, refusing rather than overwriting if one
  already exists at any of the three locations GitHub reads. Unlike
  `AGENTS.md` and the `.gitignore` block, it is not a managed integration --
  no `lock.json` entry, no hash tracked -- and is intended to be run
  directly by a human during repository setup, the same as `codev init`
  itself.
- `codev status --verbose` now reports non-blocking work-in-progress counts
  per owner and changed-file overlaps between concurrently open work items
  (ADR-0004), surfacing `plan-delivery`'s existing WIP guidance and the
  residual collision risk that small, fast-merging changes shrink but do not
  eliminate -- informational only, never a gate.
- `code-audit` gains a second invocation mode (ADR-0005): `orchestrator` now
  invokes it automatically, audit-and-plan phase only, immediately before
  opening a pull request, in addition to its existing standalone
  human-approval-gated form. A clean pass proceeds to `codev git
  push`/`open-pr` as before; a finding is recorded with `codev work record
  --role reviewer --decision CHANGES_REQUIRED` and routed to `builder` under
  the inner loop's existing round cap, rather than `code-audit` self-applying
  a fix -- there is no human present in that turn to grant Phase 2's
  approval. `audit-google-python-style`/`audit-google-typescript-style` are
  unchanged; only who invokes `code-audit` and what happens with its
  findings changed, not the skills it dispatches to.
- Add `--entry {takeover,direct-review}` to `codev work start` (ADR-0006):
  purely additive, optional -- omitted means today's implicit cold start,
  unchanged, no `ROUND_SCHEMA_VERSION` bump. `takeover` marks a work item
  whose branch already carries unfinished human commits beyond `--base`;
  round 1 still opens in the inner phase, and `orchestrator`'s three-agent
  protocol (all four platforms) now tells `builder` to read that existing
  diff and continue it rather than replace it. `direct-review` marks a work
  item as already finished by a human; round 1 opens directly in the outer
  phase instead of inner, and `codev work check` now recognizes a fresh
  `direct-review` item (no builder or reviewer recorded yet) as immediately
  `ok_ready_for_pr` -- previously this exact state (`head` already beyond
  `base_snapshot` with nothing recorded) would have been reported as
  `stop_drift`. `describe`/`log_text` surface the new `entry` field
  alongside `owner`/`summary`/`link_ref`. A guided `codev work next`
  command was considered and dropped in the same ADR -- GitHub's own Issues
  list, populated via `codev git issue-create` (ADR-0004), already serves
  that need.

### Removed
- Remove the `clean-code-review` skill (ADR-0005). Its catalog-driven
  content (Clean Code principles, Gang-of-Four missing-pattern signals,
  design smells) was a different kind of thing from
  `architecture-maintainability-specialist`'s holistic judgment of the same
  named territory (architecture, scope, and maintainability) -- rather than
  keep it as a separate, always-manual skill, its language-agnostic material
  moves directly into that specialist's prompt across all four platforms,
  replacing previously vague "clarity, structure" language with citable,
  named criteria. Its Python-specific hazard IDs are dropped outright, not
  relocated -- `audit-google-python-style`'s existing supplemental checker
  already covers equivalent ground. `review-change`'s description gains one
  clarifying sentence: now that the outer loop covers a CoDev-built work
  item with an open PR, it is explicitly the zero-ceremony path for a diff
  with neither.

## [0.2.0] - 2026-08-11

### Added
- Add layered configuration (`codev config get|set|list`, flags > env >
  project > global > default) via `.codev/config.toml`.
- Add a `codev work start|record|check|close|status|log` lifecycle subsystem
  that tracks builder/reviewer correction rounds as state instead of prose,
  enforcing the round cap, repeated-blocking-finding detection, and coverage
  completeness by exit code. See `docs/adr/0001-work-lifecycle-invariant.md`.
- Add `codev status`, `codev adapter list|add|verify`, and `codev self
  version|update`. `adapter verify` checks that an installed platform adapter
  still references the `codev work` lifecycle wiring, hasn't regressed to the
  retired P0-P3 finding scale, and doesn't grant unrestricted shell execution;
  the same check runs in CI against the shipped bundle for all four platforms.
- Add `codev eval snapshot run <skill>`: discovers every fixture tagged with
  a skill (`fixture.json` now requires `skill` and `category`), and for each
  category runs the fixture with the skill staged into the worktree and
  without it, repeated (`--repetitions`, default 3), reporting a pass
  percentage per condition and the delta between them - empirical evidence
  that a skill measurably outperforms not having it, not just a recall
  number in isolation. `codev eval run` gained `--without-skill` for
  single-fixture use. Replaces the fixture-only `scripts/run_seeded_defect_suite.py`.
  Backed by the seven-fixture seeded-defect corpus
  (`.codev/fixtures/seeded-defect-*`, one per review dimension, `skill:
  review-change`), each seeding a small reviewable change with one
  deliberately planted, known defect verified deterministically rather than
  trusted from the coverage checklist alone. The scheduled `live-eval` CI job
  runs a snapshot against a live OpenCode actor and gates `prepare-release`;
  its OpenCode installation/authentication step is a placeholder pending this
  project's actual CI credentials.

### Changed
- Default programming-language selection to `none`, omit language-specific audit
  skills unless requested, and render the OpenCode code-audit agent from a
  language-aware template.
- Add the language-aware code-audit agent to the Junie, Codex, and Antigravity
  adapters.
- Replace the reviewer's P0–P3 severity scale with a ranked, binary
  `blocking` finding model and a mandatory per-dimension coverage record, in
  `review-change` and all four platform reviewer agents.
- Narrow the "no CoDev process runs during a build" invariant so `codev work`
  commands may run during a build session (ADR-0001).
- Deprecate `codev check`, `codev doctor`, `codev fixture create`, and bare
  `codev eval <name>` in favor of `codev status`, `codev status --verbose`,
  `codev eval fixture create`, and `codev eval run <name>`; the old forms
  still work and print a warning.

## [0.1.7] - 09.08.2026

### Fixed
- Prevent release preparation from rebuilding distributions by validating tag and
  version metadata before downloading the exact tested artifacts.

## [0.1.6] - 09.08.2026

### Fixed

- Align workflow validation expectations with the current bundled documentation.

## [0.1.5] - 09.08.2026

### Changed

- Rename the platform-selection flag to `--agent-platform` to distinguish agent
  platforms from operating-system platforms.
- Add the `--programming-language` flag with lock-file persistence to install
  only the selected Python, TypeScript, or all code-style audit skills.
- Clarify `pr-review` summaries and publication/retry guidance to prevent
  duplicate reviews and make authorized submissions explicit.
- Complete Codex adapter distribution and platform filtering so `.codex/agents/`
  TOML agents install, update, validate, and remove safely.

## [0.1.4] - 2026-08-06

### Added

- Add the GitHub-only `pr-review` skill with exact-head validation, anchored
  inline comments, `gh api` authentication with token fallback, and PR context
  fetching for metadata, diffs, files, commits, reviews, comments, and checks.
- Add Google Antigravity support with managed `builder`, `orchestrator`, and
  `reviewer` subagents under the official `.agents/agents/` workspace location,
  selectable through `--platform antigravity` or `--platform all`.
- Add JetBrains Junie support with managed `builder`, `orchestrator`, and
  `reviewer` subagents under `.junie/agents/`, selectable through
  `--platform junie` or `--platform all`.
- Allow `update --platform junie` to add Junie to an existing CoDev
  installation with the same conflict-aware preflight as initial installs.
- Add the Junie project slash command `/pr-review repo=OWNER/REPO pr=123`, plus
  the secure GitHub-token helper for the PR-review workflow.
- Add the read-only `critique-review` specialist skill, which turns concrete
  review or presubmit findings into precise suggested diffs and requires an
  explicit handoff to `build-change` or the developer before application.

### Changed

- Move verification, linting, packaging, and wheel smoke tests into the default
  CI workflow for pull requests, `main`, and release tags.
- Gate the PyPI release phase on successful checks from the exact tag run and
  publish the distributions produced by that run.

## [0.1.3] - 2026-08-05

### Fixed

- Correct import ordering in the versioning script to satisfy Ruff.
- Format the version-script changelog fixture so the test suite remains lint-clean.

## [0.1.2] - 2026-08-05

### Changed

- Publish the CLI distribution as `open-codev-workflow` through an attested,
  trusted-publishing release workflow.
- Add the catalog-driven `clean-code-review` specialist skill for Clean Code,
  GoF, and Python-specific review findings.

## [0.1.1] - 2026-08-02

### Added

- Initial CoDev brand and standalone Python package.
- Safe `init`, `check`, `doctor`, `diff`, and `update` commands.
- Seven human-AI delivery skills and the three-agent OpenCode adapter.
- Human and AI workflow references, handbooks, cookbook, and prompt library.
- Deterministic workflow validators and behavioral scenario catalog.
- Cross-platform tests and GitHub Actions validation.
