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
verified compatibility spike behind it. CI has not yet been migrated to
this (see the design doc's implementation plan, step 8) -- until then, CI
still runs the raw `python -m unittest discover -s tests -v`,
`python -m compileall -q src tests`, `python -m ruff check .`,
`python -m ruff format --check .`, and `python -m mypy` commands directly.

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
| `just test [args]` | `bazel test //...`, extra args/targets pass through |
| `just lint` | Ruff check, via `bazel_skylib`'s `native_binary` wrapping the pip-resolved ruff wheel -- no Aspect Build ruleset |
| `just fmt` | Ruff format (mutates files) |
| `just fmt-check` | Ruff format, check-only -- what CI runs |
| `just typecheck` | Mypy, `strict = true` per `pyproject.toml`, via `rules_python`'s `py_console_script_binary` |
| `just lock-check` | Fail if `requirements_lock.txt` has drifted from `uv.lock` -- what CI runs |
| `just ci` | Aggregate of the above, matching CI's `quality`/`test` jobs |

`pyproject.toml`/`uv.lock` remain the sole source of Python dependency and
packaging metadata, and `docs/releasing.md`'s `python -m build` + `twine`
release pipeline is unchanged by this migration.

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
