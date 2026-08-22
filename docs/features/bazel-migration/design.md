# Bazel Build Migration Design

**Status:** Draft
**Owner:** CoDev maintainers
**Reviewers:** Python maintainer
**Brief:** [brief.md](brief.md)
**Last reviewed:** 2026-08-22

## Summary

Add a bzlmod-only `MODULE.bazel` targeting Bazel 9 and `rules_python` 2.3.x.
`rules_python`'s `pip.parse` extension resolves CoDev's Python dependencies
from a `requirements_lock.txt` that is *generated from* `uv.lock` via
`uv export`, never authored by hand -- `uv.lock` stays the single source of
truth. `BUILD.bazel` files for `src/` and `tests/` are hand-written: the
repository is small and flat enough (12 source modules in one package
directory, 18 test files, no subpackages) that a generator adds indirection
without buying much, so this migration does not take a dependency on
`rules_python`'s gazelle extension. Ruff and mypy
are wired in as `py_console_script_binary` targets against the pip-resolved
wheels -- native `rules_python` functionality, not a third-party ruleset. A
root `Justfile` gives humans and AI agents one small, self-documenting,
non-interactive command surface (`just test`, `just lint`, `just typecheck`,
`just build`, `just lock`) that wraps the underlying `bazel`
invocations, and `AGENTS.md` gets a section directing agents to use it
instead of raw `bazel`/`python -m` commands.

This is additive: the existing `pyproject.toml` + `uv` + `python -m build` +
`twine` release pipeline in `docs/releasing.md` is untouched. Bazel and Just
become the primary dev-loop entry point; PyPI packaging stays on its current,
already-working path.

## Goals and Non-goals

### Goals

- Hermetic, cached `bazel build`/`bazel test` for CoDev's own source and test
  tree, reproducible across macOS, Linux, and Windows.
- `uv.lock` remains the sole hand-edited dependency declaration; the Bazel
  pip lock is a generated, CI-verified derivative.
- `BUILD.bazel` files are hand-written, explicit, and reviewed like any
  other source change -- a small `py_library`/`py_test` target added
  alongside the file it covers.
- Ruff and mypy run as Bazel targets built from the same pip-resolved wheels
  as everything else, using only `rules_python`'s own primitives.
- A `Justfile` that is the *only* command surface a contributor or AI agent
  needs to discover (via `just --list`) and invoke, with deterministic exit
  codes and no interactive prompts.
- `AGENTS.md` documents that surface so an agent never has to guess between
  `bazel`, `uv`, and raw `python -m` invocations.

### Non-goals

- Replacing `pyproject.toml`/`uv` as the Python packaging metadata source.
- Replacing the PyPI release pipeline (`python -m build`, `twine`, the
  trusted-publisher CI phase) described in `docs/releasing.md`.
- `rules_python`'s gazelle extension, or any other BUILD-file generator --
  BUILD files are hand-maintained. For a repository this small and flat,
  a generator's manifest file, extra `bazel_dep`, and generated-file
  etiquette cost more than the file-list upkeep it would save.
- Any Aspect Build ruleset (`aspect_rules_py`, `aspect_rules_lint`,
  `aspect_bazel_lib`, `aspect_bazel_pnpm`, etc.) -- these package
  `rules_python`/toolchain setup as convenience, which is exactly the
  convenience layer this migration deliberately does not take a dependency
  on.
- Any third-party community Bazel ruleset that wraps ruff or mypy as its own
  repository rule, in place of `rules_python`'s native
  `py_console_script_binary`.
- Changing the CI OS matrix (`ubuntu-latest`/`windows-latest`/`macos-latest`).
  Python-version coverage under Bazel is now in scope (see "Toolchain and
  Multi-Python Strategy"); the OS matrix itself is not -- Bazel's
  multi-version testing is only verified on Linux (via CI) and macOS (this
  machine), not Windows.
- Treating the `py_wheel`-built distribution
  (`//packaging:wheel`) as the actual published PyPI artifact. It is
  built, verified byte-for-byte against `python -m build`'s real output,
  and checked in CI (see "PyPI Packaging") -- but `python -m build` +
  `twine` stays the artifact that is actually published, given the known,
  structural `Metadata-Version`/`License-Expression`/sdist gaps documented
  there.

## Current System and Evidence

- `pyproject.toml`: `setuptools` build backend, `requires-python = ">=3.11"`,
  one runtime dependency (`pre-commit>=4.6.1`), a `dev` extra
  (`build`, `mypy`, `ruff`, `twine`), `[tool.ruff]` (`select =
  ["E","F","I","UP","B","SIM"]`, `line-length = 88`, excludes
  `src/codev_workflow/bundle` and `.codev/eval/tasks/*/repository`), and
  `[tool.mypy]` (`strict = true`, `mypy_path = "src"`, `files =
  ["src/codev_workflow", "tests"]`, same bundle exclusion).
- `uv.lock`: 52 resolved packages (schema `version = 1`, `revision = 3`,
  `requires-python = ">=3.11"`), covering both the runtime dependency and the
  `dev` extra's transitive closure. It is a uv-native TOML lock format, not a
  pip-compatible `requirements.txt` -- `rules_python`'s `pip.parse` cannot
  read it directly (see "Dependency Lock Strategy" below).
- `src/codev_workflow/`: 12 top-level modules (`cli.py`, `installer.py`,
  `eval*.py`, `git_ops.py`, `task.py`, `adapter.py`, `config.py`,
  `conflict_wizard.py`) plus a `bundle/` tree of non-Python assets
  (skills, agent configs, docs) shipped as `package-data`, explicitly
  excluded from both ruff and mypy.
- `tests/`: 18 standard-library `unittest` files (~12k lines total), run via
  `python -m unittest discover -s tests -v`. No `pytest` in the dependency
  graph.
- `scripts/`: four standalone scripts (`verify_release.py`,
  `evaluate-development-workflow.py`, `validate-development-workflow.py`,
  `version.py`) used by the release process and CI, run directly with
  `python`, not as an installed package entry point.
- `.github/workflows/ci.yml`: a `test` job matrixed over
  `{ubuntu,windows,macos}-latest` x `{3.11,3.12,3.13}` running
  `pip install -e .` + `unittest` + `compileall`; a `quality` job (Ubuntu,
  3.13 only) running `ruff check`, `ruff format --check`, `mypy`, `python -m
  build`, and a wheel smoke test; a `release-integrity` job running
  `scripts/verify_release.py`; and release-only jobs (`prepare-release`,
  `attest`, `publish`) that consume the `quality` job's built distributions.
- No Bazel files (`MODULE.bazel`, `WORKSPACE*`, `BUILD*`) exist in the
  repository today; this is a clean-slate migration.

## Proposed Design

### Components and Ownership

| Component | Responsibility | Owner | State |
|---|---|---|---|
| `MODULE.bazel` / `.bazelversion` / `.bazelrc` | Declare Bazel 9 + `rules_python` 2.3.x, register hermetic toolchains and the pip hub | Repo root | New |
| `requirements_lock.txt` | pip-compatible, hash-verified lock generated from `uv.lock`, consumed by `pip.parse` | Generated, checked in | New |
| `BUILD.bazel` (`src/codev_workflow/`, `tests/`, `scripts/`) | Declare `py_library`/`py_test`/`py_binary` targets, hand-written | Repo contributors | New, hand-maintained |
| `evals/development-workflow/BUILD.bazel` | `exports_files` for `scenarios.json`, consumed as `data` by the evaluator `py_binary` | Repo contributors | New, hand-maintained |
| Root `BUILD.bazel` + `tools/*.sh` | Declares the `ruff`/`mypy` runnable targets and their workspace-root wrapper scripts; `exports_files` for `README.md`/`LICENSE` | Repo root | New, hand-maintained |
| `packaging/BUILD.bazel` | `py_package`/`py_wheel` verification build of the PyPI wheel | Repo root | New |
| `Justfile` | Single command surface: lock, build, test(-all), lint, fmt(-check), typecheck, lock-check, validate-catalog, self-test-evaluator, wheel, verify-wheel-parity, ci | Repo root | New |
| `AGENTS.md` | Documents the `just` surface as the required entry point for agents | Repo root | Extend |
| `.github/workflows/ci.yml` | `test`'s Ubuntu/3.13 leg and `quality` job call `just` recipes | CI | Extend |
| `scripts/version.py` / `scripts/verify_release.py` | `VERSION_FILES` and version-consistency checks extended to cover `packaging/BUILD.bazel`'s hand-kept version literal | Repo root | Extend |
| `pyproject.toml` / `uv.lock` | Remains the authoritative Python packaging and dependency source | Repo root | Unchanged |
| `docs/releasing.md` release pipeline | Remains on `python -m build` + `twine` | Repo root | Unchanged |

### Workspace Layout

```text
MODULE.bazel
MODULE.bazel.lock          # Bazel's own bzlmod resolution lock; commit it,
                            # same reproducibility rationale as uv.lock
.bazelversion               # pins an exact Bazel release (9.2.0)
.bazelrc                    # shared flags (see "CI Migration")
BUILD.bazel                # ruff/mypy runnable targets; exports README.md/LICENSE
tools/
  ruff.sh                  # cd-to-workspace-root wrapper (see "Tooling Integration")
  mypy.sh                  # cd-to-workspace-root wrapper
requirements_lock.txt      # generated from uv.lock, hash-verified; one lock, three hubs
Justfile
.tools/                    # gitignored: repo-local `just` binary, not committed
src/codev_workflow/
  BUILD.bazel              # hand-written: one py_library target, select()-ed pip deps
  <module>.py
tests/
  BUILD.bazel              # hand-written: one py_test target per file
  test_<module>.py
scripts/
  BUILD.bazel              # hand-written: py_library + two py_binary targets
  <script>.py
evals/development-workflow/
  BUILD.bazel              # exports_files(["scenarios.json"])
  scenarios.json
packaging/
  BUILD.bazel              # py_package + py_wheel (verification build, see "PyPI Packaging")
```

`src/codev_workflow/bundle/` (non-Python package data) is deliberately left
out of the Python target graph -- it stays a plain `glob()` input if a
future `py_wheel` target needs it, matching how `pyproject.toml` already
excludes it from ruff/mypy. `py_library`'s default `glob(["*.py"])` is
non-recursive, so it does not need an explicit exclusion to keep `bundle/`
out.

### Dependency Lock Strategy

`rules_python`'s `pip.parse` extension consumes a pip-compatible,
line-oriented lock file (the `pip-compile`/`pip freeze --require-hashes`
shape), not `uv.lock`'s TOML format. Treating `uv.lock` as the actual source
of truth means the Bazel-facing lock is a *generated derivative*, the same
relationship the existing `.codev/lock.json` already has to CoDev's bundled
source files (a generated, hash-verified artifact, never hand-edited):

```bash
uv export --frozen --no-emit-project --all-extras -o requirements_lock.txt
```

`--frozen` refuses to silently re-resolve if `uv.lock` is stale relative to
`pyproject.toml`; `--no-emit-project` excludes the CoDev package itself from
its own dependency lock. **`--all-extras` is required**, not optional --
verified by actually running the export: without it, `uv export` only emits
the plain `dependencies` closure (9 packages, just `pre-commit` and its
transitive deps) and silently drops the `dev` extra entirely, so
`ruff`/`mypy`/`build`/`twine` would never reach `pip.parse`'s hub. With
`--all-extras`, the export produces the full 51-package closure (every
`uv.lock` entry except the CoDev package itself, correctly excluded by
`--no-emit-project`). The export keeps hashes by default, which
`pip.parse` uses for the same supply-chain verification uv itself already
performs -- dropping them with `--no-hashes` would be a regression, not a
simplification.

```python
# MODULE.bazel
pip = use_extension("@rules_python//python/extensions:pip.bzl", "pip")
pip.parse(
    hub_name="pip",
    python_version="3.13",
    requirements_lock="//:requirements_lock.txt",
)
use_repo(pip, "pip")
```

One hub covering the full resolved closure (all 52 packages -- runtime and
`dev` extra together) is enough for V1: the dependency set is small, and a
second runtime-only hub is speculative until something actually needs the
distinction (see brief.md's constraint against designing for hypothetical
requirements). `uv.lock`'s `resolution-markers` split
(`python_full_version >= '3.15'` vs `< '3.15'`) does not overlap this
project's supported `3.11`-`3.13` range, so a single `requirements_lock.txt`
resolved against `python_version = "3.13"` is sufficient; `pip.parse`
resolves per-interpreter wheel selection itself from the same lock rather
than needing uv's marker branches replayed.

CI fails a job that regenerates `requirements_lock.txt` and finds a diff
against the checked-in copy -- the same "generated artifact must match its
source" gate `codev update`'s hash comparison already models for the bundle.

### BUILD File Strategy (hand-written)

No BUILD-file generator is introduced. `src/codev_workflow/` is one flat
package directory (12 modules, no subpackages other than the non-Python
`bundle/` data tree), and `tests/` is one flat directory of 18
`test_*.py` files, so two hand-written `BUILD.bazel` files cover the entire
first-party target graph.

`src/codev_workflow/BUILD.bazel` declares a single `py_library` for the
package -- Bazel's default `glob(["*.py"])` is non-recursive, so it picks up
exactly the 12 top-level modules and nothing under `bundle/`:

```python
load("@rules_python//python:defs.bzl", "py_library")

py_library(
    name="codev_workflow",
    srcs=glob(["*.py"]),
    data=glob(["bundle/**"]),
    imports=[".."],
    deps=["@pip//pre_commit"],
    visibility=["//visibility:public"],
)
```

Two attributes here were confirmed necessary by actually running the real
test suite under Bazel, not assumed up front:

- **`imports = [".."]`.** `pyproject.toml`'s `package-dir = {"" = "src"}`
  makes `codev_workflow` a top-level importable package today. Without
  `imports`, Bazel's default import-path derivation makes the package
  importable as `src.codev_workflow` instead (matching each file's
  repo-relative path), and every test's `from codev_workflow import ...`
  fails with `ModuleNotFoundError`. `imports = [".."]`, read relative to
  `src/codev_workflow/`, adds `src/` to the import roots and restores the
  `pyproject.toml`-equivalent import path.
- **`data = glob(["bundle/**"])`.** `bundle/` is non-Python package data,
  but it is not merely inert: `installer.py`'s `_walk_bundle()` and the
  `pr-review` skill's `publish_review.py` loader both read it *at runtime*
  via real filesystem/`importlib.resources` access, not import statements.
  Three real tests (`test_cli`, `test_installer`, `test_pr_review`) fail
  with `FileNotFoundError` without this -- Bazel's sandboxed test runfiles
  only contain files a target actually declares, so "excluded from the
  Python target graph" (true) does not mean "excluded from the runfiles
  needed at runtime" (false). `bundle/` still gets no `py_library`/`py_test`
  of its own; it is data on the one target that touches it.

`tests/BUILD.bazel` declares one `py_test` per file via a plain Starlark
loop over `glob(["test_*.py"])` -- still one hand-authored file a
contributor reads and edits directly, not a separate generator binary or
manifest:

```python
load("@rules_python//python:defs.bzl", "py_test")

[
    py_test(
        name=test_file.removesuffix(".py"),
        srcs=[test_file],
        deps=[
            "//src/codev_workflow:codev_workflow",
            "//scripts:scripts",
        ],
    )
    for test_file in glob(["test_*.py"])
]
```

Every test target depends on `//scripts:scripts` uniformly, even though only
`test_verify_release.py` and `test_version.py` actually import from it
(`from scripts import verify_release` / `from scripts import version`) --
running the real suite under Bazel surfaced this as a genuine dependency,
not an assumption: `scripts/` (`verify_release.py`,
`evaluate-development-workflow.py`, `validate-development-workflow.py`,
`version.py`) was originally scoped as release-process tooling outside the
Bazel target graph, but two tests import it directly, so it needs its own
small `py_library`:

```python
# scripts/BUILD.bazel
load("@rules_python//python:defs.bzl", "py_library")

py_library(
    name="scripts",
    srcs=glob(["*.py"]),
    imports=[".."],
    visibility=["//visibility:public"],
)
```

Depending on it uniformly from every `tests/BUILD.bazel` target rather than
selectively is a deliberate simplicity trade-off: an unused `deps` entry
costs nothing at Bazel's dependency granularity, and keeping the loop
identical for all 17 targets is worth more than trimming two lines.

This keeps the per-file caching and parallelism a generator's default shape
would have given (a failing file is individually addressable, unlike today's
single `unittest discover` run) without adding a generator dependency. A
contributor adding a new test file needs zero BUILD.bazel edits -- it is
picked up by the existing glob; adding a new *source* module still needs
zero edits for the same reason. Only a new pip dependency being imported, or
a new file under `bundle/`, requires an explicit one-line addition to
`codev_workflow`'s `deps`/`data`.

Verification: symlinking the real `src/` and `tests/` into a throwaway
Bazel workspace with exactly this BUILD-file shape and running
`bazel test //tests/...` reproduces all 17 `python -m unittest discover`
results exactly (17/17 pass), and a second no-op `bazel test //tests/...`
run is a full cache hit (`Executed 0 out of 17 tests: 17 tests pass`),
confirming the design's stated cache-hit success measure.

### Toolchain and Multi-Python Strategy

```python
# MODULE.bazel
python = use_extension("@rules_python//python/extensions:python.bzl", "python")
python.toolchain(python_version="3.13", is_default=True)
python.toolchain(python_version="3.12")
python.toolchain(python_version="3.11")
use_repo(python, "python_3_11", "python_3_12", "python_3_13")
```

This registers hermetic, prebuilt CPython interpreters (matching the
existing `requires-python = ">=3.11"` and the CI matrix's `3.11`/`3.12`/
`3.13` legs) for macOS, Linux, and Windows without depending on whatever
Python happens to be on a runner's `PATH`.

**Registering a toolchain is not the same as being able to select it --
and the flag that actually does select it is not the one you'd guess.**
This design originally shipped believing `--python_version=3.11` was a
silent no-op for this target graph (verified at the time: `bazel cquery
--python_version=3.11 //tests:test_config` still resolved `python_3_13`).
That conclusion was correct for the flag tried, but incomplete -- there
are *two* different flags with overlapping names. The bare
`--python_version` is not a `rules_python` setting at all here; the one
that actually drives toolchain and `pip.parse`-hub resolution is the fully
qualified Starlark build setting:

```bash
bazel test '--@rules_python//python/config_settings:python_version=3.11' //tests/...
```

Confirmed with the same cquery check that caught the original problem:
under this flag, `deps(//tests:test_config)` resolves to
`python_3_11_*//:py3_runtime` and (once a `pip_311` hub exists, see below)
`pip_311//pre_commit`, not `python_3_13`/`pip`. `bazel test` under this
flag genuinely executes with the 3.11 interpreter -- this is not the same
false confidence the original `--python_version` check produced.

**Multi-version hubs.** `pip.parse` needs one hub per Python version a
target should be selectable under. Rather than three separate
`requirements_lock_3.1{1,2,3}.txt` files, this checks out simpler: `uv
export --python 3.11/3.12/3.13` were compared directly and produce
byte-identical dependency content for this project's dependency set (no
package here has version-specific wheel selection across 3.11-3.13), so
all three hubs resolve from the same `requirements_lock.txt`:

```python
pip.parse(
    hub_name="pip", python_version="3.13", requirements_lock="//:requirements_lock.txt"
)
pip.parse(
    hub_name="pip_312",
    python_version="3.12",
    requirements_lock="//:requirements_lock.txt",
)
pip.parse(
    hub_name="pip_311",
    python_version="3.11",
    requirements_lock="//:requirements_lock.txt",
)
use_repo(pip, "pip", "pip_311", "pip_312")
```

`src/codev_workflow/BUILD.bazel`'s `deps` then `select()`s the matching
hub using `rules_python`'s generated per-version `config_setting`s
(`@rules_python//python/config_settings:is_python_3.11` etc., confirmed to
exist via `bazel query`):

```python
deps = (
    select(
        {
            "@rules_python//python/config_settings:is_python_3.11": [
                "@pip_311//pre_commit"
            ],
            "@rules_python//python/config_settings:is_python_3.12": [
                "@pip_312//pre_commit"
            ],
            "//conditions:default": ["@pip//pre_commit"],
        }
    ),
)
```

Verified end to end: `bazel test
'--@rules_python//python/config_settings:python_version=3.11'
//tests/...` and the 3.12 equivalent each report `Executed 17 out of 17
tests: 17 tests pass` for real (not a cache hit reusing the 3.13 run) --
matching the non-Bazel `python -m unittest` baseline under all three
interpreters.

**One scoping gotcha this produced:** the root `BUILD.bazel`'s `ruff`/
`mypy` targets are pinned to the `pip` (3.13) hub only. Running `bazel
test '--@rules_python//...:python_version=3.11' //...` (the whole-repo
wildcard) fails at analysis time, because Bazel must configure every
target the pattern matches -- including those single-version tool
targets -- even though `test` only executes test rules. `just`'s
per-version test recipes scope to `//tests/...`, not `//...`, to avoid
this; see "Justfile Design".

**Why this is in scope after all.** The original design deferred
per-version Bazel coverage as unnecessary, reasoning CoDev is pure Python.
That reasoning doesn't fully hold: this repository's own history has a
real, version-specific bug --
[487a273](https://github.com/urban233/CoDev/commit/487a273), "Fix NVIDIA
engine executable resolution on Python 3.12+ Windows" -- caught by exactly
the 3.12 CI leg that reasoning would have left uncovered under Bazel. The
raw CI matrix already covers this today regardless of what Bazel does;
extending Bazel to match closes the gap between "what CI actually
exercises" and "what `just test`/`just ci` locally exercises," which is
the more relevant risk for an agent or contributor running `just` instead
of raw commands.

### Release-Process Scripts as Bazel Targets

`scripts/validate-development-workflow.py` and
`scripts/evaluate-development-workflow.py` (hyphenated filenames, so no
`main =` inference -- set explicitly) are pure-stdlib, so wiring them in is
mechanical: `py_binary` targets in `scripts/BUILD.bazel`, alongside the
existing `scripts` `py_library`.

```python
py_binary(
    name="validate_development_workflow",
    srcs=["validate-development-workflow.py"],
    main="validate-development-workflow.py",
    data=["//src/codev_workflow:codev_workflow"],
)

py_binary(
    name="evaluate_development_workflow",
    srcs=["evaluate-development-workflow.py"],
    main="evaluate-development-workflow.py",
    data=[
        "//evals/development-workflow:scenarios.json",
        "//src/codev_workflow:codev_workflow",
    ],
)
```

Both scripts default `--repo` to `Path(__file__).resolve().parents[1]`,
not the invocation directory -- this was checked, not assumed, since it's
exactly the kind of path-resolution assumption that broke ruff/mypy under
`bazel run` (see "Tooling Integration" below). It turns out fine here for
a different reason: under `bazel run`, `__file__` resolves through
Bazel's runfiles symlinks back to the real source tree, not a sandboxed
copy, so `validate_development_workflow` needs no
`BUILD_WORKSPACE_DIRECTORY` wrapper. `evaluate_development_workflow`'s
`--repo .` self-test additionally reads
`evals/development-workflow/scenarios.json`, which is outside
`src/codev_workflow/` entirely -- a small `evals/development-workflow/
BUILD.bazel` with `exports_files(["scenarios.json"])` makes that file
referenceable as `data` from another package. Verified: `bazel run
//scripts:validate_development_workflow -- --repo
src/codev_workflow/bundle` and `bazel run
//scripts:evaluate_development_workflow -- --repo . --self-test` both
match their non-Bazel `python scripts/...` baselines exactly (`Workflow
validation passed: 12 skills, 3 guides, and 0 handbooks, plus 7 behavioral
scenarios` / `Workflow evaluator self-test passed`).

### PyPI Packaging (`py_wheel`)

The highest-risk piece of this migration, because the output is the
artifact that actually reaches users' installs. Verified by direct,
repeated comparison against `python -m build`'s real wheel -- file
manifest, METADATA content, and the exact CI smoke-test assertion -- not
by trusting the tool's defaults.

**This is a verification build, not a replacement for the release
pipeline.** `python -m build` + `twine` (`docs/releasing.md`) remain the
actual PyPI publish path; see brief.md's Non-goals for why the gaps below
make that the right call for now.

**Setup: `packaging/BUILD.bazel`**, using `rules_python`'s native
`py_package` (collects a first-party package's transitive files) and
`py_wheel` (builds the wheel):

```python
py_package(
    name="codev_workflow_pkg",
    packages=["src.codev_workflow"],
    deps=["//src/codev_workflow:codev_workflow"],
)

py_wheel(
    name="wheel",
    distribution="open-codev-workflow",
    version="0.3.0",  # hand-kept in sync -- see "Version sync" below
    python_tag="py3",
    python_requires=">=3.11",
    author="Martin Urban",
    summary="Human-guided AI software delivery for real repositories.",
    license="BSD-3-Clause",
    description_file="//:README.md",
    description_content_type="text/markdown",
    project_urls={"Homepage": "...", "Repository": "...", "Issues": "..."},
    classifiers=[...],  # mirrors pyproject.toml's [project] classifiers
    requires=["pre-commit>=4.6.1"],
    extra_requires={"dev": ["build>=1.2.2", "mypy>=1.15", "ruff>=0.11", "twine>=6.1"]},
    entry_points={"console_scripts": ["codev = codev_workflow.cli:main"]},
    extra_distinfo_files={
        "//:LICENSE": "licenses/LICENSE",
        ":top_level_txt": "top_level.txt",  # write_file; setuptools emits this, py_wheel doesn't
    },
    strip_path_prefixes=["src"],
    deps=[":codev_workflow_pkg"],
)
```

Three real, non-obvious things surfaced by actually building and diffing,
not by reading the rule's documentation:

- **`py_package`'s `packages` filters by repo-relative path, not Python
  import path.** `packages = ["codev_workflow"]` (the intuitive choice)
  matches nothing -- the rule's implementation compares each input's
  `short_path` (e.g. `src/codev_workflow/cli.py`) against the filter as a
  literal path prefix, unaware of `imports = [".."]` or any import-path
  remapping. `packages = ["src.codev_workflow"]` (dots become `/`) is what
  actually matches. First attempt produced a wheel with only `dist-info`
  and zero package content -- a completely silent, non-erroring failure
  mode worth flagging for anyone else hitting this.
- **`homepage` and `project_urls["Homepage"]` conflict, not stack.**
  Setting both produces a legacy `Home-page:` METADATA header that the
  real setuptools 77+ wheel no longer emits (it uses `Project-URL:
  Homepage, ...` once `Homepage` is in `project.urls`). Diffing METADATA
  byte-for-byte against the baseline caught this; the fix is to drop the
  `homepage` attribute entirely and rely on `project_urls` alone.
  Confirmed the same way: `strip_path_prefixes = ["src"]` was necessary to
  turn `src/codev_workflow/...` paths into `codev_workflow/...` in the
  wheel, matching the manifest exactly.
- **`data = glob(["bundle/**"])` is not hermetic without an exclusion.**
  Building the wheel initially included four stray
  `__pycache__/*.pyc` files that happened to exist on this machine's
  checkout from earlier local test runs -- Bazel's `glob()` matches
  whatever is actually on disk at analysis time, so a build's output can
  depend on incidental local state, not just checked-in sources. Fixed
  for both the wheel and the existing test/dev `data` glob on
  `src/codev_workflow/BUILD.bazel`: `exclude = ["bundle/**/__pycache__/**",
  "bundle/**/*.pyc"]`.

**Confirmed working, not merely built:**

- File manifest: byte-for-byte identical set of 149 files against the
  real `python -m build` wheel (`diff` of sorted `unzip -l` output is
  empty).
- Sample file content (`cli.py`): byte-identical.
- `METADATA`: every field `py_wheel` supports matches after the fixes
  above (`Author`, `Summary`, `License`, all three `Project-URL`s,
  classifiers, `Requires-Python`, `Requires-Dist` for both the base and
  `dev`-extra requirements).
- `twine check` on the Bazel-built wheel: `PASSED`.
- The exact CI wheel-smoke-test assertion (install with `--no-deps`,
  `codev --version`, and the literal sorted-filename assertion against
  `bundle/.codex/agents`) run against the Bazel wheel: passes unmodified.

**Known, accepted gaps -- structural to `rules_python`'s `py_wheel`, not
closeable via BUILD-file attributes:**

- `Metadata-Version: 2.1` (Bazel) vs `2.4` (setuptools 77+). `py_wheel`'s
  generator predates PEP 639 license-expression metadata. 2.1 is a valid,
  fully PyPI-accepted metadata version; the gap is only that it can't
  carry the newer optional fields below.
- `License: BSD-3-Clause` (legacy field) instead of `License-Expression:
  BSD-3-Clause` (PEP 639, what `license = "..."` produces in the real
  wheel) -- consequence of the same generator-version gap. No
  `License-File:` / `Dynamic: license-file` pair either, for the same
  reason.
- No `Keywords:` header -- `py_wheel` has no attribute for it.
- `extra == "dev"` uses single quotes (`extra == 'dev'`) instead of
  double (`extra == "dev"`) in `Requires-Dist` marker syntax. Cosmetic:
  both are valid PEP 508 marker syntax that `pip`/`packaging` parse
  identically.
- No sdist equivalent. `rules_python` has no stable `py_sdist`-equivalent
  rule; only the wheel is reproduced.

None of these caused `twine check` or the smoke test to fail, but they are
real, and are the reason this stays a verification build rather than the
publish path.

**Version sync.** `py_wheel`'s `version` attribute is a plain string, not
something it can read live from `pyproject.toml`, so
`packaging/BUILD.bazel` becomes a *third* place carrying the version
literal, alongside `pyproject.toml` and `src/codev_workflow/__init__.py`.
Two safety nets close this, not just documentation:
`scripts/version.py`'s `VERSION_FILES` tuple (used by the release version
bump) now includes `packaging/BUILD.bazel`, and
`scripts/verify_release.py`'s `verify()` gained a `read_bazel_wheel_version`
check (a targeted regex read, since Starlark isn't parseable by the
existing `tomllib`/`ast` readers already used for the other two files)
that fails release verification if it drifts -- covered by two new tests
in `tests/test_verify_release.py`.

**CI wiring** (`just wheel` builds it; `just verify-wheel-parity` builds
both the Bazel wheel and a throwaway `python -m build` wheel, diffs their
manifests, and runs `twine check` on the Bazel one -- wired into `quality`
right after the existing wheel smoke test, and into `just ci`).

### Tooling Integration: Ruff and Mypy (native `rules_python`, no third-party ruleset)

This section originally assumed `rules_python`'s `py_console_script_binary`
macro would wrap both tools identically. Actually building and running both
against the real dependency lock surfaced two real, tool-specific wrinkles;
what follows is what was verified working, not the original assumption.

**Mypy** is a standard `console_scripts` entry point, so
`py_console_script_binary`
(`@rules_python//python/entry_points:py_console_script_binary.bzl`) applies
directly -- the same mechanism that already backs `codev`'s own
`[project.scripts]` entry point:

```python
py_console_script_binary(
    name="mypy_bin",
    pkg="@pip//mypy",
    script="mypy",
)
```

`script = "mypy"` must be explicit: the macro's default behavior infers the
desired console script from the *target's own name*, and `mypy`'s wheel
declares five scripts (`dmypy`, `mypy`, `mypyc`, `stubgen`, `stubtest`), so a
target not literally named `mypy` fails to build with `RuntimeError: Tried
to guess that you wanted 'mypy_bin' ...` until the script is named
explicitly.

**Ruff does not work with `py_console_script_binary` at all.** Its wheel
ships a compiled native executable as wheel `.data/scripts/ruff`, not a
Python `console_scripts` entry point -- inspecting the real resolved wheel's
`.dist-info` confirms it has no `entry_points.txt`, and `pip.parse` itself
records `entry_points = {}` for it. `py_console_script_binary` fails with
`does not contain entry_points.txt`. The correct native wiring for a
binary-wheel tool is `bazel_skylib`'s `native_binary`
(`@bazel_skylib//rules:native_binary.bzl`) pointed at the wheel's `:data`
target, which resolves to exactly the extracted `bin/ruff` executable --
still first-party Bazel-ecosystem tooling (`bazel_skylib` is maintained by
the Bazel project itself), not an Aspect convenience ruleset:

```python
native_binary(
    name="ruff_bin_native",
    src="@pip//ruff:data",
    out="ruff_bin",
)
```

**Both need a `BUILD_WORKSPACE_DIRECTORY` wrapper.** `bazel run` executes
the target with its working directory set to the target's own runfiles
directory, not the directory `bazel run` was invoked from -- confirmed by
running a diagnostic binary: `pwd` lands inside
`.../check_pwd.runfiles/_main`, while the real invocation directory is only
available via the `BUILD_WORKSPACE_DIRECTORY` environment variable `bazel
run` exports. Without accounting for this, `bazel run //:ruff -- check
src/codev_workflow` fails to find that path, and `bazel run //:mypy --
--config-file=pyproject.toml ...` fails to find the config file -- both
tools silently stop behaving like their `python -m` equivalents. The fix is
a two-line wrapper per tool, using `rules_shell`'s `sh_binary` (Bazel 9
unbundles `sh_binary`/`py_binary`/etc. from the builtin native rule set, so
this needs its own `bazel_dep` the same way `py_library`/`py_test` need
`rules_python`'s):

```bash
# tools/ruff.sh
#!/usr/bin/env bash
set -euo pipefail
cd "${BUILD_WORKSPACE_DIRECTORY}"
exec bazel-bin/ruff_bin "$@"
```

```bash
# tools/mypy.sh
#!/usr/bin/env bash
set -euo pipefail
cd "${BUILD_WORKSPACE_DIRECTORY}"
exec bazel-bin/mypy_bin "$@"
```

```python
# BUILD.bazel
load("@bazel_skylib//rules:native_binary.bzl", "native_binary")
load(
    "@rules_python//python/entry_points:py_console_script_binary.bzl",
    "py_console_script_binary",
)
load("@rules_shell//shell:sh_binary.bzl", "sh_binary")

native_binary(
    name="ruff_bin_native",
    src="@pip//ruff:data",
    out="ruff_bin",
)

py_console_script_binary(
    name="mypy_bin",
    pkg="@pip//mypy",
    script="mypy",
)

sh_binary(
    name="ruff",
    srcs=["tools/ruff.sh"],
    data=[":ruff_bin_native"],
)

sh_binary(
    name="mypy",
    srcs=["tools/mypy.sh"],
    data=[":mypy_bin"],
)
```

With this, `bazel run //:ruff -- check .` and `bazel run //:ruff --
format --check .` reproduce today's `python -m ruff check .` / `python -m
ruff format --check .` exactly (verified: a clean run against
`src/codev_workflow` reports `All checks passed!`), reading the same
`[tool.ruff]` table in `pyproject.toml` with no separate Bazel-specific
config. `bazel run //:mypy` reproduces `python -m mypy` the same way,
reading `[tool.mypy]`'s `strict = true` and `mypy_path = "src"` directly
(verified: `bazel run //:mypy -- --config-file=pyproject.toml
src/codev_workflow tests` reports `Success: no issues found in 31 source
files`).

`MODULE.bazel` needs two more `bazel_dep`s for this, beyond `rules_python`:

```python
bazel_dep(name="bazel_skylib", version="1.9.2")
bazel_dep(name="rules_shell", version="0.8.0")
```

Ruff and mypy run via `bazel run`, not `bazel test`: both are whole-tree,
config-driven checks (`ruff format --check .` and `mypy`'s cross-module
analysis do not decompose per-file the way independent unit tests do), and
the wrapper above gives them the same effectively-repo-root-relative
semantics `python -m ruff`/`python -m mypy` already have today. `just
lint`/`just typecheck` are the actual command surface; which underlying
Bazel mechanism they use is an implementation detail an agent should not
need to know.

### Justfile Design

Design principles, driven by the brief's "AI agents work confidently"
outcome:

- **One discoverable surface.** `just` with no arguments (or `just --list`)
  prints every recipe; an agent never has to read `MODULE.bazel` or memorize
  `bazel` target labels to find the right command.
- **Zero interactive prompts, unambiguous exit codes.** Every recipe either
  exits `0` or a nonzero code an agent can branch on; none read from stdin.
- **Recipes are thin wrappers, not new logic.** Each one is a short,
  auditable `bazel`/`uv` invocation -- an agent (or a human) can read a
  recipe body and immediately see the real command it runs.

This is the actual `Justfile` now in the repository, not an illustrative
sketch:

```just
# CoDev build/test/lint/type-check entry point. See
# docs/features/bazel-migration/design.md. Run `just` or `just --list` to
# discover recipes; every recipe is a thin, non-interactive wrapper around
# a `bazel`/`uv` command with a deterministic exit code.

default:
    @just --list

# Regenerate the Bazel pip lock from uv.lock (uv.lock stays source of truth).
# `uv export -o` also echoes the full file to stdout; silenced here.
lock:
    uv export --frozen --no-emit-project --all-extras -o requirements_lock.txt > /dev/null

build:
    bazel build //...

# Pass extra bazel test flags/targets through, e.g. `just test //tests:test_cli`.
# Runs under the default toolchain (3.13); see test-all for every supported
# version. Scoped to //tests/... rather than //... -- the root BUILD.bazel's
# ruff/mypy targets are pinned to the 3.13 pip hub and fail to even analyze
# under a --python_version override for a different hub.
test *args:
    bazel test //tests/... {{args}}

test-3-12 *args:
    bazel test --@rules_python//python/config_settings:python_version=3.12 //tests/... {{args}}

test-3-11 *args:
    bazel test --@rules_python//python/config_settings:python_version=3.11 //tests/... {{args}}

# Run the test suite under every supported Python version (3.11, 3.12, 3.13).
test-all: test test-3-12 test-3-11

lint:
    bazel run //:ruff -- check .

fmt:
    bazel run //:ruff -- format .

# Non-mutating format check, for CI.
fmt-check:
    bazel run //:ruff -- format --check .

typecheck:
    bazel run //:mypy -- --config-file=pyproject.toml src/codev_workflow tests

# Fail if requirements_lock.txt has drifted from uv.lock. Skips the
# autogenerated header's first two lines: uv embeds the literal -o path
# there, which is cosmetic and not a real drift signal.
lock-check:
    #!/usr/bin/env bash
    set -euo pipefail
    tail -n +3 requirements_lock.txt > /tmp/requirements_lock.txt.before
    uv export --frozen --no-emit-project --all-extras -o requirements_lock.txt > /dev/null
    if ! diff -q /tmp/requirements_lock.txt.before <(tail -n +3 requirements_lock.txt) > /dev/null; then
        echo "requirements_lock.txt is stale relative to uv.lock -- run 'just lock' and commit the result." >&2
        exit 1
    fi

validate-catalog:
    bazel run //scripts:validate_development_workflow -- --repo src/codev_workflow/bundle

self-test-evaluator:
    bazel run //scripts:evaluate_development_workflow -- --repo . --self-test

# Build the wheel via py_wheel. This is a verification build, matched
# file-for-file and metadata-field-for-field against `python -m build`'s
# output -- it is not the actual release artifact. `python -m build` +
# twine stay the real PyPI publish path (docs/releasing.md); see
# docs/features/bazel-migration/design.md's "PyPI Packaging" section for
# the known gaps (older Metadata-Version, no sdist).
wheel:
    bazel build //packaging:wheel

# Verify the Bazel wheel still matches python -m build's real output.
verify-wheel-parity: wheel
    #!/usr/bin/env bash
    set -euo pipefail
    rm -rf /tmp/codev-wheel-parity
    mkdir -p /tmp/codev-wheel-parity
    uv run python -m build --outdir /tmp/codev-wheel-parity/setuptools-dist > /dev/null
    setuptools_whl=$(ls /tmp/codev-wheel-parity/setuptools-dist/*.whl)
    bazel_whl=$(bazel cquery --output=files //packaging:wheel 2>/dev/null)
    unzip -l "$setuptools_whl" | awk '{print $4}' | sed '/^$/d' | sort > /tmp/codev-wheel-parity/setuptools.manifest
    unzip -l "$bazel_whl" | awk '{print $4}' | sed '/^$/d' | sort > /tmp/codev-wheel-parity/bazel.manifest
    if ! diff -q /tmp/codev-wheel-parity/setuptools.manifest /tmp/codev-wheel-parity/bazel.manifest > /dev/null; then
        echo "Bazel wheel file manifest has diverged from python -m build's output:" >&2
        diff /tmp/codev-wheel-parity/setuptools.manifest /tmp/codev-wheel-parity/bazel.manifest >&2 || true
        exit 1
    fi
    uv run twine check "$bazel_whl"

# Everything CI's quality gate checks, in one command.
ci: lint fmt-check typecheck lock-check test-all validate-catalog self-test-evaluator verify-wheel-parity
```

`fmt-check`, `lock-check`, `test-3-11`/`test-3-12`/`test-all`,
`validate-catalog`, `self-test-evaluator`, `wheel`, and
`verify-wheel-parity` were all added after the original single-`test`/
single-Python sketch above, as the scope grew to cover every Python
version, the two release scripts, and the wheel. Two implementation
details worth calling out: `uv export -o` was found to echo the full lock
file to stdout even though `-o` already writes it to disk -- silenced with
`> /dev/null` in `lock`/`lock-check`/`verify-wheel-parity`; and `test`/
`test-3-11`/`test-3-12` scope to `//tests/...` rather than `//...` because
the root `BUILD.bazel`'s single-version-pinned `ruff`/`mypy` targets fail
to even analyze under a different hub's `--python_version` override (see
"Toolchain and Multi-Python Strategy").

### CI Migration

Landed in `.github/workflows/ci.yml`. The `quality` job (Ubuntu, Python
3.13 only) switches its ruff/mypy steps to `just lint`, `just fmt-check`,
and `just typecheck`, adds `just lock-check` (fails if
`requirements_lock.txt` has drifted from `uv.lock`), and adds `just
verify-wheel-parity` right after the existing wheel smoke test (builds
the Bazel wheel, diffs its manifest against the `python -m build` wheel
already produced earlier in the same job, and runs `twine check` on the
Bazel one). `python -m build`/`twine check dist/*`/the wheel smoke test
against `dist/*.whl` are themselves untouched -- `dist/*.whl` stays the
artifact that gets uploaded and eventually published, per this design's
non-goals. Bazel and `just` are provisioned via
[`bazel-contrib/setup-bazel`](https://github.com/bazel-contrib/setup-bazel)
(the actively maintained action; `bazelbuild/setup-bazelisk` is archived)
and [`extractions/setup-just`](https://github.com/extractions/setup-just),
and `uv` via [`astral-sh/setup-uv`](https://github.com/astral-sh/setup-uv)
(needed by `lock-check` and `verify-wheel-parity`) -- all three published
actions from their respective upstream projects, not an OS package manager
and not an Aspect action.

The `test` job's `{ubuntu,windows,macos}-latest` x `{3.11,3.12,3.13}`
matrix is **unchanged** -- its raw `unittest discover`/`compileall`/
catalog-validation/evaluator-self-test steps still run for all nine
combinations; nothing was removed. Three supplementary steps were added,
gated to `matrix.os == 'ubuntu-latest' && matrix.python == '3.13'`: `just
test-all` (all three Python versions, see "Toolchain and Multi-Python
Strategy" for how that actually selects toolchains), `just
validate-catalog`, and `just self-test-evaluator`. These add real signal
(the first confirmation the whole Bazel graph -- not just tests, the
release scripts too -- also works on Linux, not just the macOS machine it
was built and verified on) without replacing or weakening any existing
coverage.

A `.bazelrc` sets shared, CI-appropriate flags (remote cache wiring is
deliberately out of scope for V1 -- local disk cache only until the
design's cache-hit success measure is validated in CI, which it now has
been, locally).

### AGENTS.md Changes

A new section is added to the repository's `AGENTS.md`, directing agents to
`just` as the required entry point rather than raw `bazel`/`uv`/`python -m`
invocations, so an agent never has to choose between four different tools
for the same check. See the actual diff applied to `AGENTS.md` as part of
this change; its content mirrors the "Justfile Design" recipe table above.

## Alternatives and Trade-offs

| Option | Benefits | Costs/risks | Decision |
|---|---|---|---|
| `pip.parse` from a `uv export`-generated lock | `uv.lock` stays sole source of truth; hash-verified; no format the team maintains by hand | Requires a regeneration step and a CI staleness check | Chosen |
| Point `pip.parse` at `pyproject.toml` directly (no lock) | One less generated file | No hash pinning; re-resolves on every fetch; diverges from `uv.lock` immediately | Rejected |
| `aspect_rules_py` for Python rules and toolchain setup | Less MODULE.bazel boilerplate | Adds a third-party convenience layer the brief explicitly rules out; another dependency to track for Bazel 9/rules_python 2.3.x compatibility | Rejected |
| `aspect_rules_lint` for ruff/mypy wiring | Pre-built lint aspect wiring; would have absorbed the `entry_points.txt`/cwd wrinkles below automatically | Same convenience-layer objection; also obscures the exact command being run, which works against agent legibility | Rejected |
| `py_console_script_binary` for both ruff and mypy | Uniform wiring for both tools | Verified broken for ruff: its wheel has no `entry_points.txt` (native binary, not a Python entry point) | Rejected for ruff, kept for mypy |
| `bazel_skylib`'s `native_binary` + a `BUILD_WORKSPACE_DIRECTORY` `sh_binary` wrapper for ruff | Verified working against the real wheel; stays first-party Bazel-ecosystem tooling | One more `bazel_dep` (`bazel_skylib`) and a two-line shell script to maintain | Chosen |
| Hand-written `BUILD.bazel`, glob-driven (two files total) | No generator dependency; new source/test files need zero BUILD edits via `glob()`; a `deps` change is a small, reviewable diff | A contributor must know to add a `deps` entry when importing a new pip package; would not scale past a small, flat package layout | Chosen |
| `rules_python` gazelle extension | Fully automatic target + deps upkeep, scales to a large/nested source tree | New `bazel_dep`, a manifest file (`gazelle_python.yaml`), a "DO NOT EDIT" generated-file convention -- more moving parts than this repository's size justifies | Rejected |
| One `py_test` per `tests/test_*.py` (via the `BUILD.bazel` glob loop) | Per-file caching, parallelism, isolated failures | More targets to reason about than one aggregate suite | Chosen |
| One aggregate `py_test` running `unittest discover` | Minimal target count; closest port of today's command | Loses per-file caching/parallelism, the main reason to move test execution into Bazel at all | Rejected |
| `py_wheel` as a verification build, `python -m build` stays canonical | Proves Bazel packaging parity continuously in CI without betting the real release on it | Two wheel-build code paths to keep in sync (mitigated by `just verify-wheel-parity` + the version-sync checks) | Chosen |
| `py_wheel` as the actual PyPI publish path | Fully Bazel-native release build, one fewer tool | Structural gaps found by direct comparison: older `Metadata-Version` (2.1 vs 2.4), `License:` instead of `License-Expression:`, no `Keywords:`, no sdist equivalent -- real regressions for a package that already publishes today | Rejected for now |
| Three separate `requirements_lock_3.1{1,2,3}.txt` files for multi-version hubs | Each hub resolved against a version-specific export, in case content ever diverges | `uv export --python 3.11/3.12/3.13` verified byte-identical for this dependency set -- three files would be redundant duplication with no behavior difference | Rejected |
| One `requirements_lock.txt` feeding three `pip.parse` hubs (`pip`, `pip_311`, `pip_312`) | Single generated file stays the only lock artifact; still three real, independently-selectable hubs | Would silently stop being correct if a future dependency ever needs different wheels per version (not currently the case, verified) | Chosen |

## Quality and Risk

- **Security/privacy:** `requirements_lock.txt` keeps hash verification, so
  Bazel's pip resolution has the same supply-chain guarantee `uv.lock`
  already provides; dropping hashes for convenience is explicitly rejected
  above. `//packaging:wheel` is a verification build only (see "PyPI
  Packaging"), so its known metadata gaps never reach a real install --
  the artifact users actually get is still `python -m build`'s output.
- **Reliability/concurrency:** Bazel's sandboxed, content-addressed actions
  make `bazel test //...` reruns and parallel `bazel build`/`bazel test`
  invocations safe by construction; this is a property gained, not a new
  risk introduced. One hermeticity gap was found and closed rather than
  left as a latent risk: `src/codev_workflow/BUILD.bazel`'s `data =
  glob(["bundle/**"])` initially picked up stray `__pycache__/*.pyc` files
  that happened to exist on the build machine from earlier local test
  runs -- a build whose output depends on incidental local filesystem
  state, not just checked-in sources. Fixed with an explicit `exclude`.
- **Observability/cost:** `just <recipe>` output is the underlying `bazel`
  command's normal stdout/stderr; no new logging layer is introduced. Local
  disk caching only for V1 keeps this change free of new infrastructure
  cost; remote caching is future work, not required for the stated success
  measures.
- **Compatibility:** Confirmed directly, not merely read from
  documentation -- `rules_python` 2.3.2 (the latest 2.3.x patch on the
  Bazel Central Registry at implementation time) was actually fetched and
  built against with Bazel 9.2.0, and `pip.parse`, `python.toolchain`, and
  `py_console_script_binary` all behave as this design assumes, with the
  two corrections folded into "Tooling Integration" above (ruff needs
  `native_binary` instead; `py_console_script_binary` needs an explicit
  `script =` for a multi-script wheel like mypy's). This was the
  "compatibility spike, stop if it doesn't hold" gate the implementation
  plan's step 1 called for, the same pattern used for the OpenCode CLI
  contract in `docs/features/skill-eval/design.md` -- it held, with two
  corrections rather than a stop.
- **Accessibility/internationalization:** Not applicable; this is
  build-tooling with no user-facing interface beyond CLI text.

## Test Strategy

- Every existing `tests/test_*.py` file must pass under its hand-written
  `py_test` target with the same pass/fail verdict as today's
  `python -m unittest discover -s tests -v`, **under all three supported
  Python versions**. **Verified**: `bazel test //tests/...` under the
  default (3.13), and under
  `--@rules_python//python/config_settings:python_version=3.12`/`3.11`,
  each report `Executed 17 out of 17 tests: 17 tests pass` -- the 3.11/3.12
  runs execute for real (not cache hits reusing 3.13), confirmed by `bazel
  cquery` showing the matching `python_3_11`/`python_3_12` runtime and
  `pip_311`/`pip_312` hub resolved. Matches `uv run python -m unittest
  discover -s tests -v`'s `Ran 551 tests ... OK` baseline (551, not 17:
  `unittest discover` counts individual test methods; `py_test` counts
  files).
- `bazel run //:ruff -- check .` and `bazel run //:ruff -- format --check .`
  must report the same violations as today's `python -m ruff` invocations.
  **Verified**: both report zero violations against the real repository
  root, matching `uv run ruff check .`/`ruff format --check .` (a set of
  71 pre-existing errors and 6 unformatted files was found and fixed
  during this work -- unrelated to the Bazel wiring itself, which
  reproduced them identically before the fix; see brief.md's history for
  that fix).
- `bazel run //:mypy` must report the same violations as today's
  `python -m mypy`, with `strict = true` still enforced. **Verified**:
  `bazel run //:mypy -- --config-file=pyproject.toml src/codev_workflow
  tests` reports `Success: no issues found in 31 source files`, matching a
  clean `strict = true` baseline.
- `bazel run //scripts:validate_development_workflow` and `bazel run
  //scripts:evaluate_development_workflow -- --self-test` must match their
  non-Bazel baselines. **Verified**: both report the identical pass
  messages (`Workflow validation passed: 12 skills, 3 guides, and 0
  handbooks, plus 7 behavioral scenarios` / `Workflow evaluator self-test
  passed`).
- `//packaging:wheel` must match `python -m build`'s real wheel --
  manifest, `twine check`, and the CI smoke-test assertion. **Verified**:
  see "PyPI Packaging" for the full comparison; `just verify-wheel-parity`
  automates this check going forward.
- A deliberately staled `requirements_lock.txt` (edited out of sync with
  `uv.lock`) must fail the CI staleness check.
- A second, no-change `bazel test //...` run must be a full cache hit,
  verifying the design's stated cache-hit success measure. **Verified**
  against the real repository files: `Executed 0 out of 17 tests: 17
  tests pass`.

## Migration, Rollout, Rollback, and Cleanup

This migration is additive and reversible at every step: `pyproject.toml`,
`uv.lock`, and the `pip install -e .` developer loop are never modified, so
a contributor or CI job that ignores Bazel entirely keeps working throughout.
Suggested phased rollout, each phase independently landable and revertable:

1. `MODULE.bazel`, toolchains, and the pip lock/hub, with no consumers yet.
2. Hand-written `BUILD.bazel` files for `src/codev_workflow/` and `tests/`;
   `bazel build //...` succeeds.
3. `py_test` targets green; `just test` matches `unittest discover`.
4. `ruff`/`mypy` `py_console_script_binary` targets; `just lint`/`just
   typecheck` match today's raw invocations.
5. `Justfile` finalized; `AGENTS.md` section added.
6. CI's `test`/`quality` jobs switch to `just` recipes, with the
   stale-lock check added.
7. Per-version `pip.parse` hubs (`pip_311`, `pip_312`) and `select()`-ed
   deps; `just test-all` exercises all three Python versions.
8. `py_binary` targets for the two release scripts, plus the small
   `evals/development-workflow/BUILD.bazel` their self-test needs.
9. `packaging/BUILD.bazel`'s `py_wheel` verification build, plus the
   version-sync safety net in `scripts/version.py`/`verify_release.py`.

Rollback at any phase is deleting that phase's new files; nothing in the
repository outside `MODULE.bazel`, `MODULE.bazel.lock`, `.bazelrc`,
`.bazelversion`, `BUILD.bazel` files, `requirements_lock.txt`, `tools/*.sh`,
`Justfile`, and `packaging/` depends on Bazel existing --
`pyproject.toml`/`uv.lock`/the `pip install -e .` loop and the actual
`python -m build` release pipeline are untouched throughout. `.tools/just`
is gitignored and never committed in the first place.

## Open Questions

None remain open. Every question from the original design, and every one
that came up while extending it to multi-version testing, the release
scripts, and packaging, was resolved by actually running it against real
`rules_python` 2.3.2, Bazel 9.2.0, and this repository's own files, rather
than left as a paper assumption -- see "Dependency Lock Strategy",
"Toolchain and Multi-Python Strategy", "Tooling Integration",
"Release-Process Scripts as Bazel Targets", and "PyPI Packaging" above for
what each investigation actually found.

## Implementation Plan

1. **Compatibility spike -- done.** `rules_python` 2.3.2 (the current
   2.3.x patch) was fetched and built against Bazel 9.2.0 in a throwaway
   workspace, `uv export --frozen --no-emit-project --all-extras` was run
   against this repo's real `uv.lock`, and the real `src/`/`tests/` trees
   were symlinked in and built/tested against hand-written BUILD files.
   Result: the design held, with the corrections already folded into
   "Dependency Lock Strategy" and "Tooling Integration" above.
2. **Done.** `MODULE.bazel`, `.bazelversion` (`9.2.0`), `.bazelrc`,
   `requirements_lock.txt` (generated with the `--all-extras` command
   above), and the pip/toolchain/`bazel_skylib`/`rules_shell` wiring are in
   the repository. `bazel build //...` succeeds.
3. **Done.** `src/codev_workflow/BUILD.bazel` (`py_library` with `imports
   = [".."]` and `data = glob(["bundle/**"])`), `scripts/BUILD.bazel`
   (`py_library` with `imports = [".."]`), and `tests/BUILD.bazel` (the
   glob-loop `py_test` targets depending on both) are in the repository.
4. **Done.** `bazel test //tests/...` against the real repository files:
   17/17 pass, matching `python -m unittest discover -s tests -v` exactly.
5. **Done.** Root `BUILD.bazel` has the `ruff` (`native_binary` +
   `sh_binary` wrapper) and `mypy` (`py_console_script_binary` with
   `script = "mypy"` + `sh_binary` wrapper) targets, with
   `tools/ruff.sh`/`tools/mypy.sh`. Confirmed against the real repository:
   `bazel run //:ruff -- check .` and `bazel run //:ruff -- format --check
   .` match `uv run ruff check .`/`ruff format --check .` exactly (both
   now clean -- see "Test Strategy"); `bazel run //:mypy` reports `Success:
   no issues found in 31 source files`.
6. **Done.** Root `Justfile` with `lock`, `build`, `test`, `lint`, `fmt`,
   `typecheck`, `ci` recipes; `just --list` and `just lint`/`just
   typecheck` verified against the real repository. `just` itself is
   installed as a repo-local, gitignored binary at `.tools/just` (no
   system-wide/Homebrew install), per the accountable human's choice.
7. **Done.** The `AGENTS.md` section is in place, updated to describe the
   implemented state rather than a plan.
8. **Done.** `quality` job's ruff/mypy steps now call `just lint`/`just
   fmt-check`/`just typecheck`, with `just lock-check` added; `test` job
   gained supplementary `just`-based steps gated to `ubuntu-latest`/Python
   3.13. `release-integrity`, `prepare-release`, `attest`, and `publish`
   are untouched. YAML-validated locally (not yet run on an actual GitHub
   Actions runner -- that happens on push/PR).
9. Document the new workflow in `docs/releasing.md` only if the release
   process itself changes -- it should not, per this design's non-goals.
10. **Done.** Per-version `pip.parse` hubs (`pip_311`, `pip_312`) and
    `select()`-ed `deps` on `src/codev_workflow/BUILD.bazel`; `just
    test-all` verified to actually execute (not cache-reuse) under all
    three interpreters, matching `--@rules_python//python/config_settings:
    python_version=X.Y`'s real toolchain/hub resolution (`bazel cquery`
    confirmed) -- not the bare `--python_version` flag the original spike
    (incorrectly) concluded was a no-op for the whole graph.
11. **Done.** `scripts/BUILD.bazel` gained `py_binary` targets for
    `validate-development-workflow.py`/`evaluate-development-workflow.py`;
    `evals/development-workflow/BUILD.bazel` added so the evaluator
    self-test's `scenarios.json` dependency resolves. Both verified against
    their non-Bazel baselines.
12. **Done.** `packaging/BUILD.bazel`'s `py_package`/`py_wheel`
    verification build, matched file-for-file and metadata-field-for-field
    against `python -m build`'s real wheel, `twine check`-clean, and
    passing the exact CI smoke-test assertion. `just wheel`/`just
    verify-wheel-parity` recipes; `quality` job runs the latter after its
    existing wheel smoke test. `scripts/version.py`'s `VERSION_FILES` and
    `scripts/verify_release.py`'s `verify()` extended to keep
    `packaging/BUILD.bazel`'s hand-kept version literal in sync, with new
    tests in `tests/test_verify_release.py`.

## Acceptance

- [x] Material decisions above (lock strategy, hand-written BUILD files
  with no generator, native `rules_python`/`bazel_skylib` wiring for
  ruff/mypy, no Aspect ruleset, `python -m build`/`twine` left untouched)
  accepted by the accountable human. (Martin Urban, 2026-08-22)
- [x] `rules_python` 2.3.x compatibility spike (step 1) passes. -- run
  against real `rules_python` 2.3.2 + Bazel 9.2.0 with this repo's actual
  `uv.lock`, `src/`, and `tests/`; two design corrections were folded in
  (see "Dependency Lock Strategy" and "Tooling Integration"). The one
  residual item -- confirming a full-tree strict-mode `mypy` run has zero
  unexpected violations -- is tracked in "Open Questions", not blocking
  this checkbox: the wiring itself is confirmed correct.
- [x] Accountable human accepts implementation planning against this
  design. (Martin Urban, 2026-08-22) -- implementation starts at step 1,
  the compatibility spike, below.
- [x] Extended scope -- multi-version Python coverage under Bazel, the two
  release scripts as Bazel targets, and a `py_wheel` verification
  build -- accepted by the accountable human. (Martin Urban, 2026-08-22)
  Each was implemented and verified, not merely designed: real
  toolchain/hub switching confirmed via `bazel cquery` for 3.11/3.12 (see
  "Toolchain and Multi-Python Strategy"), both release scripts confirmed
  against their non-Bazel baselines, and the wheel confirmed
  file-for-file, `twine check`-clean, and passing the exact CI smoke-test
  assertion against `python -m build`'s real output (see "PyPI
  Packaging").
