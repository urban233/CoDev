# Bazel Build Migration

**Status:** Draft
**Owner:** CoDev maintainers
**Last reviewed:** 2026-08-22

## Problem and users

Contributors and AI coding agents working in this repository today drive the
build, test, lint, type-check, and package steps through a mix of raw
commands (`python -m unittest discover`, `python -m ruff check .`,
`python -m mypy`, `python -m build`) documented separately in
`docs/releasing.md`, `AGENTS.md`, and `.github/workflows/ci.yml`. There is no
single, hermetic, cached build graph: every command re-resolves the
environment, nothing is content-addressed, and an agent has to already know
which of four different tools to invoke for a given check. There is also no
machine-checkable BUILD graph an agent can query to find "what depends on
this file" before making a change.

## Desired outcome

CoDev's own build, test, lint, format, and type-check steps run through
Bazel 9, with `rules_python` 2.3.x providing hermetic Python toolchains and
pip dependency resolution derived from the existing `uv.lock`. A small,
stable set of `just` recipes (casey/just) is the only interface a human or an
AI agent needs to memorize -- `just test`, `just lint`, `just typecheck`,
`just build` -- each backed by a deterministic, cacheable `bazel` invocation
with unambiguous exit codes. `uv.lock` remains the single source of truth for
Python dependencies; Bazel's pip lock is a generated, verified derivative of
it, never hand-edited.

## Success measures

- `just test`, `just lint`, `just fmt`, `just typecheck`, and `just build`
  each complete with the same pass/fail verdict as today's equivalent raw
  command, with zero interactive prompts.
- `just test-all` exercises the test suite under all three supported
  Python versions (3.11, 3.12, 3.13), each genuinely selecting its own
  toolchain and pip hub, not silently reusing the default.
- `just wheel` produces a wheel matching `python -m build`'s real output
  file-for-file and passing `twine check`; `just verify-wheel-parity`
  makes that an automated, repeatable check.
- A second `bazel test //...` run with no source changes is a 100% cache hit.
- `requirements_lock.txt` (Bazel's pip lock) can be regenerated from
  `uv.lock` by one `just lock` command and CI fails if the checked-in file
  drifts from `uv.lock`.
- `BUILD.bazel` files for `src/` and `tests/` are hand-written and small
  enough that a contributor never has to run a generator to add a file.
- No `aspect_rules_*` dependency, no BUILD-file generator, and no
  third-party ruff/mypy Bazel ruleset
  appears in `MODULE.bazel`.

## Essential scenarios

- A contributor adds a new module under `src/codev_workflow/` or a new test
  file under `tests/`; the existing hand-written, glob-driven `BUILD.bazel`
  in that directory picks it up automatically -- only a newly imported pip
  dependency needs an explicit one-line `deps` addition.
- An AI agent asked to "run the tests" or "check types" discovers the
  available commands via `just --list` and gets a clean exit code without
  needing Bazel-specific knowledge.
- A dependency bump lands in `uv.lock`; `just lock` regenerates the Bazel
  pip lock, and `bazel test //...` immediately reflects it.
- CI matrix jobs (`test`, `quality`) call the same `just` recipes a local
  contributor uses, so a red CI job is locally reproducible with one command.

## First release

### Now

- `MODULE.bazel` (Bazel 9, bzlmod-only) with `rules_python` 2.3.x, hermetic
  toolchains for Python 3.11/3.12/3.13.
- A `pip.parse` hub resolved from a `requirements_lock.txt` generated from
  `uv.lock` via `uv export --all-extras`, never authored by hand.
- Hand-written, glob-driven `BUILD.bazel` files for `src/codev_workflow/`,
  `scripts/`, and `tests/` -- no BUILD-file generator.
- `ruff` and `mypy` wired against the pip-resolved wheels via native
  `rules_python`/`bazel_skylib` primitives (a `native_binary` for ruff's
  compiled wheel, `py_console_script_binary` for mypy's console-script
  entry point) -- no third-party lint/format ruleset.
- A root `Justfile` covering lock regeneration, build, test, lint, format,
  type-check, and an aggregate `ci` recipe.
- `AGENTS.md` gains a section documenting the `just` surface as the required
  entry point for build/test/lint/type-check work.
- CI's `test` and `quality` jobs call `just` recipes instead of raw
  `python -m ...` invocations.
- Per-version `pip.parse` hubs (3.11, 3.12, alongside the default 3.13),
  so `just test`/`bazel test` can genuinely select any of the three
  supported Python versions, not just the default. Added after initially
  scoping this out as unnecessary for a pure-Python project -- reversed
  once a concrete counterexample from this repo's own history surfaced
  ([487a273](https://github.com/urban233/CoDev/commit/487a273), a real
  Python-3.12-and-Windows-specific bug); see design.md's "Toolchain and
  Multi-Python Strategy".
- `py_binary` targets for the two release-process scripts
  (`validate-development-workflow.py`, `evaluate-development-workflow.py`).
- A `py_wheel` verification build (`//packaging:wheel`) proven, by direct
  comparison, to match `python -m build`'s real wheel file-for-file and
  metadata-field-for-field, and wired into CI as an additional check --
  not as the actual publish path (see "Not planned" and design.md's "PyPI
  Packaging" for the structural gaps that keep it a verification build).

### Next

- Collapsing the *OS* leg of the CI matrix onto Bazel is not planned (see
  below); if it ever were, the Python-version leg would already be
  covered, unlike when this section was first written.

### Not planned

- Replacing `pyproject.toml`/`uv` as the source of Python packaging metadata
  and dependency declarations.
- Replacing the PyPI release pipeline (`python -m build` + `twine` +
  trusted-publisher CI) described in `docs/releasing.md`. `//packaging:wheel`
  is a verification build proven equivalent, not the actual publish path --
  see design.md's "PyPI Packaging" for the structural gaps (older
  `Metadata-Version`, no sdist) that make replacing the real pipeline the
  wrong call for now.
- Any `aspect_rules_py`, `aspect_rules_lint`, `aspect_bazel_lib`, or other
  Aspect Build convenience ruleset.
- Any third-party community Bazel ruleset for ruff or mypy specifically
  (e.g. rules that wrap those tools as their own repository rule) in place
  of `rules_python`'s native `py_console_script_binary`.
- `rules_python`'s gazelle extension, or any other BUILD-file generator.
- Changing the CI OS matrix shape (`ubuntu-latest`, `windows-latest`,
  `macos-latest` stay) -- Bazel's multi-version testing is verified on
  Linux (CI) and macOS (the dev machine) only, not Windows.

## Constraints

- `uv.lock` stays authoritative; the Bazel pip lock is generated, checked in,
  and CI-verified for staleness, never hand-edited.
- No new runtime dependency for the shipped `codev` package or the target
  repositories it installs into -- this migration only touches CoDev's own
  build tooling.
- Bazel invocations must be deterministic and non-interactive so an
  unattended AI agent can rely on exit codes alone.
- Keep the existing non-Bazel `pip install -e .` / `uv` developer loop fully
  working in parallel; Bazel is additive during this migration.
- Match Bazel 9's bzlmod-only model -- no `WORKSPACE` file.

## Assumptions and discovery

All three assumptions below were checked by actually running the
compatibility spike (Bazel 9.2.0, `rules_python` 2.3.2, this repo's real
`uv.lock`/`src`/`tests`) rather than left as paper assumptions; see
`design.md`'s "Dependency Lock Strategy" and "Tooling Integration" sections
for the two corrections it produced.

| Assumption | Evidence needed | Owner | Decision point |
|---|---|---|---|
| `rules_python` 2.3.x still exposes `pip.parse`, `python.toolchain`, and `py_console_script_binary` with the same shape as prior 0.x/1.x releases | Read the actual 2.3.x release notes/API docs at implementation time | Implementer | Confirmed: 2.3.2 built and ran correctly; `py_console_script_binary` needed an explicit `script =` for mypy and does not apply to ruff (native-binary wheel, no `entry_points.txt` -- `bazel_skylib`'s `native_binary` used instead) |
| `uv export` produces a `pip.parse`-compatible `requirements_lock.txt` (including hashes) from this repo's `uv.lock` without manual edits | Run `uv export` against the current `uv.lock` and feed the output to `pip.parse` in a throwaway workspace | Implementer | Confirmed, with a correction: `--all-extras` is required, not optional -- without it `uv export --no-emit-project` silently drops the `dev` extra (ruff/mypy/build/twine) entirely |
| Bazel-sandboxed `mypy` can still see enough of `src/` to satisfy the existing `[tool.mypy]` `strict = true` configuration | Run `mypy` under a `py_console_script_binary` target against the full `src/codev_workflow` tree | Implementer | Confirmed: `Success: no issues found in 31 source files` |

## Acceptance

- [x] Outcome, scope, non-goals, and success measures accepted by the
  accountable human. (Martin Urban, 2026-08-22)
- [x] Extended scope (multi-version Python coverage, release scripts as
  Bazel targets, `py_wheel` verification build) accepted and implemented.
  (Martin Urban, 2026-08-22) -- see design.md's Acceptance section for the
  verification evidence behind each.
