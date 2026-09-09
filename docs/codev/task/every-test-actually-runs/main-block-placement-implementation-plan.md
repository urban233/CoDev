# main-block-placement Implementation Plan

**Status:** Accepted
**Owner:** urban233
**Reviewer:** lightweight-reviewer (inner loop)
**Risk:** low
**Containment:** N/A -- test-only change, no runtime behavior guarded
**Slices:** One PR
**Slice:** main-block-placement
**Base commit:** e41242b29725c84b345de3358ed09c6b9a8bf545
**Issue/work item:** Not linked
**Brief/design/API:** Not needed

## Focus card

- **Change:** Move the `if __name__ == "__main__": unittest.main()` block in
  `tests/test_gate.py` and `tests/test_task.py` to the end of each file, so
  every test class defined after it is still collected.
- **Success:** `bazel test //tests:test_gate //tests:test_task` runs every
  test class in both files -- 20/20 in `test_gate`, 180/180 in `test_task` --
  instead of stopping short at the classes that used to sit below the
  `__main__` block.
- **Non-goals:** No production code changes; no change to what the tests
  assert, only where the `__main__` block sits in the file.
- **Allowed scope:** `tests/test_gate.py`, `tests/test_task.py`,
  `CHANGELOG.md`.
- **Validation:** `bazel test //tests:test_gate //tests:test_task` (the same
  runner `just test` and CI's Bazel leg use) with the exact-count evidence
  above.
- **Stop if:** Any other `test_*.py` under `tests/BUILD.bazel` is found with
  the same shape (a `__main__` block followed by more classes) -- that would
  widen scope beyond these two files.
- **Work style:** Pair (already the slice's recorded style).

## Repository evidence

- `tests/BUILD.bazel`: builds every `test_*.py` as a `py_test` with no
  explicit `main=`, so Bazel imports and runs each file as `__main__`.
- `tests/test_gate.py` (pre-fix): `SubdirectoryCwdTests` was defined below
  the file's `if __name__ == "__main__": unittest.main()` block, so
  `unittest.main()` ran and exited the process before that class existed --
  Bazel collected 16 of 20 tests.
- `tests/test_task.py` (pre-fix): `SliceScopedCoverageTests` sat below the
  same kind of block -- Bazel collected 176 of 180 tests.
- CI's raw `python -m unittest discover` legs import each module instead of
  executing it as `__main__`, so they did collect every class and stayed
  green; only the Bazel leg (and `just test` locally) was affected, which is
  why the gap was invisible until scanned for directly.
- The same shape was caught earlier in this stack in
  `tests/test_permission_surface.py` by an outer-loop specialist; this slice
  is the rest of it, found by checking every `test_*.py` module for a
  `__main__` block with classes appended after it.

## Proposed change

1. In `tests/test_gate.py`, move the `if __name__ == "__main__":
   unittest.main()` block from above `SubdirectoryCwdTests` to the end of the
   file, after that class.
2. In `tests/test_task.py`, move the `if __name__ == "__main__":
   unittest.main()` block from above `SliceScopedCoverageTests` to the end of
   the file, after that class.
3. Add a `CHANGELOG.md` entry under `[Unreleased] / Fixed` describing the bug,
   its cause, and the general lesson (check a new test class's position
   relative to any `__main__` block, and verify counts under Bazel rather
   than under `python -m unittest`).

## Validation

- `bazel test //tests:test_gate //tests:test_task` -> `test_gate` 20/20 pass,
  `test_task` 180/180 pass (previously 16/20 and 176/180).

## Risks and rollout

- None beyond the change itself: this only reorders code within two test
  files and adds a changelog entry, with no behavior or API surface touched.
  No feature flag or rollback needed.

## Decisions needed

- None.

## Completion evidence

- **Delivered:** Both files' `__main__` blocks moved to the end; every test
  class in `tests/test_gate.py` and `tests/test_task.py` now runs under
  Bazel.
- **Changed:** `tests/test_gate.py`, `tests/test_task.py`, `CHANGELOG.md`
  (commit `eba8ea2d7a9fc25876ed8db4801e76c06dd7ac97`).
- **Head commit/snapshot:** `eba8ea2d7a9fc25876ed8db4801e76c06dd7ac97`.
- **Validation actually run:** `bazel test //tests:test_gate
  //tests:test_task` -- `test_task` 180/180, `test_gate` 20/20 (per the
  commit message; the task owner ran this directly before the fix was
  committed).
- **Acceptance evidence:** Success criterion above -> the bazel run counts
  recorded in the commit message.
- **Scope deviations:** None -- the fix was scanned across every
  `test_*.py` module and only these two files had the shape described.
- **Known limitations:** None.
- **Review state:** Not yet reviewed by `lightweight-reviewer`; this plan is
  being written after the fact because the change was applied directly by
  the task owner, outside the tracked builder/reviewer round -- the task was
  paused and resumed (ADR-0038) to absorb it as `pair` work before this plan
  was written.
