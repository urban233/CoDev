# Repo Root Resolution - Implementation Plan

**Status:** Accepted 2026-09-08 by Martin Urban (instructed in session;
transcribed by Claude Opus 5, who does not hold acceptance authority)
**Owner:** urban233
**Reviewer:** independent reviewer, to be named before the pull request is marked ready
**Risk:** normal. Small diff, but it changes guardrail behavior, and a wrong fix restores enforcement in name only.
**Containment:** N/A -- fail-open is preserved throughout; the worst case of a bad fix is the status quo.
**Work style:** `pair` (recorded)
**Slices:** 1 -- one pull request, estimated well under budget
**Slice:** `repo-root-resolution`
**Base commit:** `355529c`
**Issue/work item:** none (kept local; no authorization to publish one)
**Brief/design/API:** Not needed -- bug fix against observed behavior, reproduction below

## Focus card

- **Change:** resolve the real repository root from the payload cwd before
  deciding any gate, instead of taking the cwd verbatim as the root.
- **Success:** the plan and wave-shape gates return the same decision for a
  file edit whether the session's cwd is the repository root or any
  subdirectory of it; the decisions that are already correct stay correct.
- **Non-goals:** changing fail-open policy; changing what any gate decides
  when the root is correct; the `.claude/` bundle work in
  `docs/plans/claude-code-adapter-verification-first.md`.
- **Allowed scope:** `src/codev_workflow/gate.py`, `.gitignore`, `tests/`,
  `CHANGELOG.md`.
- **Validation:** `just ci`, plus the reproduction below re-run as a test.
- **Stop if:** resolving the root turns out to change any decision other than
  the `degraded` ones -- that would mean the gates were relying on the cwd
  meaningfully somewhere I have not found.

## Repository evidence

Verified at `355529c` by piping synthetic `PreToolUse` payloads into
`codev gate check --gate <g> --json`:

| Gate | File edit, cwd = subdir | Bash git command, cwd = subdir |
|---|---|---|
| `plan` | `degraded` -- fails open | `ask` -- correct |
| `wave-shape` | `degraded` -- fails open | not gated by design |
| `small-change` | not gated by design | unaffected |

The exact observed reason: `internal error: '<abs file path>' is not in the
subpath of '<cwd>'`.

Mechanism, confirmed by reading the code:

- `gate.py:607` -- `repo_root = Path(payload.get("cwd") or target)` takes the
  cwd verbatim as the repository root.
- `gate.py:267` -- `_relative()` calls `path.relative_to(repo_root)`, which
  raises `ValueError` when the edited file is not under that assumed root.
- `gate.py:610` -- the blanket `except Exception` converts it to `_degraded`,
  which every shim treats as allow.

Two behaviors are already correct and must stay correct:

- The plan gate's `Bash` path never calls `_relative`, so raw
  `git commit`/`push`/`merge` is still gated from a subdirectory.
- `small-change` measures through `git_ops.slice_size`, which shells out to
  git, and git resolves the repository from any subdirectory on its own.

An earlier report of this bug -- the one that prompted this task -- claimed all
three gates fail open entirely. That is an overstatement, corrected above. It
matters here because it changes what the regression test has to pin.

## Proposed change

1. **`gate.py`** -- add a small `_repo_root(start)` helper that asks git for
   the working-tree root (`git rev-parse --show-toplevel`, via
   `git_ops._run_git`, which `gate.py` already imports for `git_ops`), and
   falls back to the given path when git cannot answer. Use it in `check()` so
   `repo_root` is the real root. Git already resolves from any subdirectory,
   so this reuses existing machinery rather than adding a directory walk.
2. **Distinguish the failure modes.** Keep fail-open, but make "could not find
   a repository root" its own `degraded` reason, separate from a genuine
   internal error, so the decision log says which happened.
3. **`.gitignore`** -- line 31 is `.codev/hooks/decisions.jsonl`, anchored to
   the repository root, so a log written into a subdirectory is not ignored
   and appears as untracked noise. Broaden to `**/.codev/hooks/decisions.jsonl`.
   Once the root resolves correctly the log should land at the root anyway;
   this covers logs already written and any shim invoked before the fix.

## Validation

- New tests in the existing gate/hook test module:
  - plan gate, file edit, cwd = repository subdirectory -> not `degraded`,
    and the same decision as cwd = root.
  - wave-shape gate, same shape.
  - **Pin the currently-correct behaviors** so the fix cannot silently regress
    them: plan gate `Bash` git command from a subdirectory still `ask`s; and a
    payload whose cwd is outside any git repository still fails open rather
    than raising.
- `just ci` -- Bazel build, three Python versions, ruff, mypy strict, catalog
  validation, evaluator self-test.
- Re-run the original reproduction by hand and confirm the decision log no
  longer records `degraded`.

## Risks and rollout

- **A subprocess call per gate decision.** `check()` currently touches only
  the filesystem on the edit path. Adding a git call costs a process spawn on
  every gated tool call. Mitigation: the gates already spawn git elsewhere
  (`_current_branch`, `slice_size`), so this is not a new class of cost;
  if it proves noticeable, resolve once and cache per invocation.
- **Restoring enforcement will surface `ask` prompts that were silently
  suppressed.** That is the fix working, not a regression, but it will look
  like new friction to anyone who had been running from a subdirectory.
  Worth a CHANGELOG line saying so plainly.
- **Rollback** is a revert; no state, no migration, no exposure.

## Decisions needed

None. The fix direction was specified in the task request; this plan narrows
it to what the reproduction actually shows.

## Completion evidence

- [ ] Reproduction re-run: plan and wave-shape gates decide identically from
      root and from a subdirectory
- [ ] Currently-correct behaviors pinned by test and still passing
- [ ] `just ci` green
- [ ] `git diff` confirms no change outside the allowed scope
- [ ] CHANGELOG entry noting that previously-suppressed prompts return
