# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/) and
Semantic Versioning.

## [Unreleased]

### Changed

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
# Unreleased

- Add the GitHub-only `pr-review` skill with exact-commit validation and a
  standard-library publisher for dry-run or pending inline reviews.
