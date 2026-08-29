# CoDev Development Policy

CoDev is a distribution tool for repository-local AI workflow instructions.
Read `docs/architecture.md` before changing installation or update behavior.

Preserve these invariants:

- preflight every multi-file mutation before writing;
- never silently overwrite a locally changed managed file;
- preserve project-owned `AGENTS.md` and OpenCode configuration;
- keep model/provider choices project-local;
- keep target repositories free of CoDev runtime dependencies; and
- require explicit commands for mutations and human authorization for releases.

Use the workflow in the parent repository while CoDev remains nested there.
Run the standard-library test suite and compile check for every code change.

## Build system (Bazel + Just)

CoDev's build/test/lint/type-check tooling runs on Bazel 9 + `rules_python`
2.3.x, automated through a root `Justfile`. See
`docs/features/bazel-migration/brief.md` and
`docs/features/bazel-migration/design.md` for the accepted design and the
verified compatibility spike behind it. `.github/workflows/ci.yml`'s
`quality` job and one `test` matrix leg (Ubuntu, Python 3.13) call `just`
recipes; the other eight `test` matrix legs still run the raw
`python -m unittest discover -s tests -v` / `compileall` /
`validate-development-workflow.py` / `evaluate-development-workflow.py`
commands directly, since Bazel's multi-version testing is verified on
Linux and macOS only, not Windows (see design.md's "CI Migration").

`just` (casey/just) is the required entry point for local build, test,
lint, format, and type-check work -- never invoke `bazel` or raw
`python -m ruff`/`python -m mypy` directly. It is not installed
system-wide: run it as `.tools/just` (a repo-local, gitignored binary; add
`.tools` to your `PATH` if you want bare `just`). Run `just --list` (or
`just` with no arguments) to discover the current recipes; do not assume
the exact set below is final, since the design doc is the source of truth:

`BUILD.bazel` files under `src/codev_workflow/`, `scripts/`, and `tests/`
are hand-written and glob-driven, not generated -- adding a new source or
test file needs no `BUILD.bazel` edit at all; only a newly imported pip
dependency, or a new file under `bundle/`, needs a one-line `deps`/`data`
addition in `src/codev_workflow/BUILD.bazel`.

| Recipe | Purpose |
|---|---|
| `just lock` | Regenerate the Bazel pip lock from `uv.lock` via `uv export --all-extras` (never hand-edit the generated lock; `uv.lock` stays authoritative) |
| `just build` | `bazel build //...` |
| `just test [args]` | `bazel test //tests/...` under the default toolchain (3.13); extra args/targets pass through |
| `just test-3-12` / `just test-3-11` | Same, under the 3.12 / 3.11 toolchain and pip hub |
| `just test-all` | All three Python versions |
| `just lint` | Ruff check, via `bazel_skylib`'s `native_binary` wrapping the pip-resolved ruff wheel -- no Aspect Build ruleset |
| `just fmt` | Ruff format (mutates files) |
| `just fmt-check` | Ruff format, check-only -- what CI runs |
| `just typecheck` | Mypy, `strict = true` per `pyproject.toml`, via `rules_python`'s `py_console_script_binary` |
| `just lock-check` | Fail if `requirements_lock.txt` has drifted from `uv.lock` -- what CI runs |
| `just validate-catalog` | `bazel run //scripts:validate_development_workflow` against the bundle |
| `just self-test-evaluator` | `bazel run //scripts:evaluate_development_workflow -- --self-test` |
| `just wheel` | Build the PyPI wheel via `py_wheel` |
| `just verify-wheel-parity` | Diff the Bazel wheel's manifest against a fresh `python -m build` wheel and `twine check` it |
| `just dist` | Build the real release artifact set into `dist/`: sdist via `python -m build`, wheel via Bazel (parity-checked, then swapped in) -- what CI's `quality` job runs |
| `just verify-dist` | Validate `dist/` -- `twine check`, install, and the smoke-test assertion -- what CI's `quality` job runs next |
| `just publish-testpypi` | **Never run this as an agent.** Uploads the wheel to TestPyPI via `rules_python`'s own sandboxed `twine`, using whatever `TWINE_USERNAME`/`TWINE_PASSWORD` are already in the caller's shell. Human-run only. |
| `just publish-pypi` | **Never run this as an agent.** Same as above, against the real PyPI -- permanent, irreversible. Human-run only, and only with explicit human authorization for that specific release. |
| `just ci` | Aggregate of the non-publish recipes above, matching CI's `quality`/`test` jobs |

`pyproject.toml`/`uv.lock` remain the sole source of Python dependency and
packaging metadata, but the **published wheel is now Bazel-built**: CI's
`quality` job runs `just dist` (builds both wheels, parity-checks, swaps
the Bazel one into `dist/`) then `just verify-dist`, and that `dist/` is
what the automated, trusted-publisher `publish` job uploads to PyPI on a
tag push. `python -m build` still supplies the sdist only (`py_wheel` has
no sdist equivalent) -- see `docs/releasing.md` and design.md's "PyPI
Packaging" for the small, accepted metadata gaps this carries (older
`Metadata-Version`, no `Keywords`) against a pure setuptools wheel; none
of them fail `twine check` or the smoke test. The `publish-testpypi`/
`publish-pypi` recipes are a separate, human-run publish path via
`rules_python`'s own `twine` integration -- CI never calls them, and
publishing is exactly the kind of action this project's own policy
requires "human authorization for releases" for (see the invariants at
the top of this file), so an agent must never invoke them, even if asked
indirectly (e.g. "run the full ci suite including publishing").
`packaging/BUILD.bazel` carries a third, hand-kept copy of the package
version alongside `pyproject.toml`/`src/codev_workflow/__init__.py`;
`scripts/version.py`'s bump command and `scripts/verify_release.py`'s
consistency check both cover it now, so a manual edit that misses it is
caught, not silently allowed to drift.

<!-- codev:start -->
## CoDev human-AI delivery

Read `.codev/for-ai/ai-agent-guidelines.md` before planning or implementing product
work. Route requests internally through the installed skills and describe the
current human-facing step as `Understand`, `Build`, `Review`, or `Ship`.

Use the lightest safe path. Inspect repository facts before prescribing code,
keep changes bounded and reviewable, run proportionate validation, and stop for
material decisions instead of inventing them. Humans retain authority for
acceptance, merge, deployment, migration, publication, and rollout expansion.
<!-- codev:end -->
