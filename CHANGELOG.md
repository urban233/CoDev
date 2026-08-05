# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/) and
Semantic Versioning.

## [Unreleased]

### Added

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
