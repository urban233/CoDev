#!/usr/bin/env bash
set -euo pipefail
# mypy_bin is a *data* dependency of this sh_binary, not the directly-run
# target, so Bazel only guarantees a materialized runfiles tree for this
# script's own target -- not a standalone bazel-bin/mypy_bin.runfiles on a
# cold build (reproduced locally with `bazel clean --expunge`; nothing to
# do with OS). Resolve mypy_bin from the cwd bazel run starts us in (this
# target's own runfiles root, where mypy_bin sits as a sibling with its
# runfiles context intact) before cd-ing away from it.
mypy_bin="$(pwd)/mypy_bin"
cd "${BUILD_WORKSPACE_DIRECTORY}"
exec "${mypy_bin}" "$@"
