# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/) and
Semantic Versioning.

## [Unreleased]

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
