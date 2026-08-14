# ADR-0013: Configurable pull request base branch

**Status:** Accepted
**Date:** 2026-08-13

## Context

`git_ops.open_pr()`'s `--base` silently defaulted to the repository's
actual default branch (`default_branch(target)`) whenever it was omitted.
Nothing ever surfaced the question, so an agent following the documented
protocol -- which never passes `--base` explicitly at the automatic
inner-loop bridge (`orchestrator` step 8) -- could open a pull request
against the wrong integration branch for a repository that doesn't PR
directly into its default branch, without ever considering it. Confirmed
as the literal cause of a real mistake in a session's feedback.

`--base` is also overloaded across the CLI in a way that likely
contributed: it means "starting commit" in `work start`/`git branch`, but
"target branch" only in `git open-pr` -- the same flag name, two different
kinds of value, on two different commands.

## Decision

One new layered config key, `git.pr_base`, using the existing
project/global/env/flag resolution in `config.py` as-is -- no new
mechanism, `DEFAULTS` stays empty. `open_pr()`: when `base` is `None`,
resolve `git.pr_base` (`config.resolve("git.pr_base", target=target)`)
before falling back to `default_branch(target)`. An explicit `--base` on
`git open-pr` is unchanged and still wins over both.

While wiring this up, found and fixed a latent bug in `config.py` that
this key was the first thing in the codebase to actually hit: `_write_config`
wrote TOML keys unquoted. An unquoted key containing a dot --
`git.pr_base = "develop"` -- is a TOML *dotted key*, parsed as a nested
table (`{"git": {"pr_base": "develop"}}`), not one literal string key.
`set_value("git.pr_base", ...)` therefore never round-tripped back through
`resolve("git.pr_base", ...)` at all. No feature had used a dotted config
key before (`DEFAULTS` was empty specifically "until a feature needs one"),
so this was untriggered until now. Fixed by quoting keys the same way
`_toml_scalar` already quotes values, making any key round-trip literally
regardless of its characters.

## Consequences

- No schema version changes anywhere -- this is a new config key plus one
  bug fix in existing, previously-unexercised config-writing code.
- `git open-pr`'s `--base` help text now names the fallback chain
  (`git.pr_base` config, then the repository's default branch) instead of
  only the repository default.
- The config-key quoting fix is general: any future config key containing
  a dot (a natural convention -- `git.pr_base`, and presumably more to
  come) now round-trips correctly, not just this one.
- Testing needs (added): `tests/test_config.py::PersistenceTests` gains a
  dotted-key round-trip regression test. `tests/test_git_ops.py::OpenPrTests`
  gains: configured `git.pr_base` used when `--base` is omitted (and
  `default_branch` is never even called); an explicit `--base` still
  overrides a configured value; the repository default branch is still
  used when nothing is configured.
