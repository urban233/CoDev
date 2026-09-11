# Slice 3: Evidence Hooks - Implementation Plan

**Status:** Accepted
**Owner:** urban233
**Reviewer:** independent reviewer, to be named before the pull request is marked ready
**Risk:** high. A `Stop` hook that fails open incorrectly removes a safety
property silently; one that fails closed incorrectly can block a developer's
session. Both directions matter more here than in slices 1-2.
**Containment:** every hook fails open on infrastructure error (missing
`codev`/`bazel`/`ruff`/`mypy` on PATH, timeout, unparseable output); Claude
Code force-overrides a `Stop` hook after 8 consecutive blocks, so this cannot
deadlock a session. Rollback is deleting the hook entries from
`.claude/settings.json` and the hook scripts.
**Work style:** `pair` (recorded, per the parent plan's own designation --
this is the judgment-heavy slice, unlike slice 2's `delegate`)
**Slices:** 5, per the parent plan
**Slice:** `evidence-hooks` (3 of 5)
**Base commit:** head of the merged slice 2 branch
**Issue/work item:** [urban233/CoDev#47](https://github.com/urban233/CoDev/issues/47)
**Brief/design/API:** [docs/plans/claude-code-adapter-verification-first.md](../../../plans/claude-code-adapter-verification-first.md), Accepted 2026-09-08 -- D3, D4

**Revision, 2026-09-11.** The three "Decisions needed" this plan raised on
2026-09-08 are now resolved below against measurements taken on this
repository rather than estimates, and the hook budget changed as a result.
One repair to the hook layer itself is folded in, and one deliberately is
not -- see "Scope: what is folded in, and what is not".

## Focus card

- **Change:** add two hooks to `.claude/settings.json` -- `Stop` ->
  `require_green.py` (refuses to end a source-touching turn while the
  repository's own checks fail, and flags a new test that would pass
  against the pre-change code too) and `PostToolUse` on `Edit|Write|MultiEdit`
  -> `format_touched.py` (formatter only). Make the existing hooks' `codev`
  invocation robust. Retire the always-on prose these hooks make redundant.
- **Success:** ending a turn that changed source with a failing test, lint
  error, or type error is refused with a clear reason; a touched Python file
  is reformatted automatically; a new test that cannot fail is reported as
  blocking; and no hook decides nothing because `codev` was not found on
  `PATH`.
- **Non-goals:** `PreCompact` -> `checkpoint_state.py` (slice 5, resolved
  below). Scientific gates (D5, slice 4). Any other adapter. The `gate.py`
  out-of-repo crash and the affected-test narrowing, both deliberately
  deferred below.
- **Allowed scope:** `.claude/settings.json` and its bundle mirror, two new
  hook scripts under `.claude/hooks/` plus the three existing ones and their
  bundle mirrors, `Justfile`, `tests/`,
  `AGENTS.md`/`.codev/for-ai/ai-agent-guidelines.md` (retiring validation
  prose these hooks make redundant), `CHANGELOG.md`.
- **Validation:** the new hooks' own test suite (fail-open on missing
  tooling, correct pass/fail translation to the `Stop`/`PostToolUse`
  protocol, PATH-independent invocation), full test suite,
  `verify_self_install.py`, and manual confirmation that a deliberately
  broken test/lint/type error is actually refused at `Stop`.
- **Stop if:** the `Stop` hook's measured cost on a source-touching turn
  exceeds the budget recorded below, or the pre-change-test mechanism turns
  out to need access to the developer's actual working tree.

## Scope: what is folded in, and what is not

**Folded in -- the `codev` invocation repair.** All three existing hooks
call `subprocess.run(["codev", ...])`, resolving a bare name from `PATH`.
When that lookup misses, every gate allows everything and nothing in the
session says so. This is not hypothetical: `.codev/hooks/decisions.jsonl`
records **508 of 1,112 calls** (46%) with the reason "`codev gate check`
could not be run, so this tool call was allowed without being checked" --
77% of all calls on 2026-09-02, recurring at 19-29% on four days after.
The fix belongs in this slice because this slice adds two more hooks to
that same foundation, and shipping them first means they inherit the
fragility. It is the same review purpose: the hook layer works.

**Not folded in -- the `gate.py` out-of-repo crash.** The same log records
8 calls failing with `internal error: '<path>' is not in the subpath of
'<repo root>'`, raised by `_relative()` at `src/codev_workflow/gate.py:311`
when a tool payload names a path outside the repository. It is a real
defect and the fix is small, **but the parent plan's accepted scope
boundary reads "`.claude/` bundle content only. No change to `installer.py`,
`adapter.py`, `cli.py`, `task.py`, `gate.py`."** Quietly widening an
accepted boundary because the fix is convenient is exactly what "allowed
scope is a drift boundary, not a suggestion" prohibits. It is filed as its
own task instead. The PATH repair above carries 98% of the value (508
occurrences against 8) and stays inside the boundary.

## Repository evidence

- The three existing hooks share one shape: read stdin JSON, shell out to
  `codev gate check --gate <name>` (or `codev task size`), translate to
  Claude Code's `PreToolUse` protocol, log to `.codev/hooks/decisions.jsonl`,
  fail open on any infrastructure error. `require_plan.py:97` is the
  invocation to repair; `require_wave_shape.py` and `require_small_change.py`
  carry the same line.
- **Measured check costs, after one source edit invalidates the Bazel
  cache** (2026-09-11, this repository):

  | Command | Cost |
  |---|---|
  | `ruff format`, one file | 0.10 s |
  | `ruff check`, one file | 0.03 s |
  | `just lint` (whole repo) | 0.28 s |
  | `just typecheck` (mypy strict, 52 files) | 0.78 s |
  | `just test` | **25.6 s** |

- `just test //tests:test_health` still executed all 33 tests in 24.6 s.
  `Justfile:22-23` is `bazel test //tests/... {{args}}` -- arguments are
  **appended** to the default target, so no subset is reachable today.
- `PostToolUse` fires after the tool already ran, so `format_touched.py`
  cannot prevent a bad edit -- only react to one.
- Claude Code force-overrides a `Stop` hook after 8 consecutive blocks,
  which is the documented backstop against a stuck session.

## Decisions, resolved

The 2026-09-08 draft left three questions open. Each is answered here with
evidence; accepting this plan accepts these answers.

**1. What does `require_green.py` run, and how is latency bounded?**
The measurements settle it: everything except the test suite is effectively
free. Resolution:

- **Gate on whether the turn changed source at all.** Most turns do not.
  A turn that touched no tracked source file skips every check and costs
  nothing. This, not a timeout, is the real latency control.
- **On a source-touching turn, run lint and typecheck unconditionally** --
  1.06 s combined, below any threshold worth engineering around.
- **Run the test suite on the same condition**, accepting 25.6 s as the
  honest price of the guarantee this slice exists to add. A 120 s timeout
  fails open and is logged as `unverified`, distinctly from a genuine
  failure, so a timeout can never be mistaken for a pass.
- Option (c) from the draft -- a short generous timeout on everything -- is
  **rejected**. It was proposed to control a latency cost that measurement
  shows sits entirely in one of the three checks, and it would have traded
  away correctness on the two that are already free.

**2. How does the pre-change test check execute without disturbing the
working tree?** Resolution: **the cheaper proxy this slice, not the
worktree.** For each test function added or modified in the current diff,
compare its assertions against the same file at the round's base snapshot
via `git show <base>:<path>`; a test function whose assertions are
unchanged from the base, or whose assertions are absent entirely, is
reported as a blocking finding. This reads git object storage and never
touches the working tree at all, which is a stronger safety property than
the read-only worktree the draft proposed, not merely a cheaper one. It is
also genuinely weaker as a check: it catches a test that asserts nothing
and a test that was not really changed, but not a test whose assertions
changed and still pass against old code. The rigorous execution-based
version needs a matching Python environment and doubles the 25.6 s, so it
is filed as a follow-up rather than smuggled into a slice already carrying
two hooks.

**3. Is `checkpoint_state.py` / `PreCompact` in this slice or slice 5?**
Resolution: **slice 5.** The parent plan's D3 lists three hooks under this
heading, but its own slice breakdown names two for slice 3, and the
checkpoint writes exactly the state slice 5's `SessionStart` recovery
reads. Confirmed reading, recorded rather than carried silently.

## Proposed change

1. **Repair the `codev` invocation in all three existing hooks.** Resolve
   the CLI through the interpreter already running the hook
   (`sys.executable -m codev_workflow`) with the bare-`codev` call retained
   only as a fallback. Add a test that the hooks still decide correctly
   with `PATH` emptied.
2. **Distinguish the two fail-open classes in `decisions.jsonl`.**
   `infrastructure` (tooling genuinely absent -- a legitimate fail-open)
   versus `hook_error` (a defect in the hook itself -- never acceptable, and
   what the health report should escalate on). Today both log as
   `degraded` and are indistinguishable.
3. **`require_green.py`** (`Stop`). Determine the repository root as the
   existing hooks do. If the turn changed no tracked source file, allow
   immediately. Otherwise run lint, then typecheck, then the test suite,
   refusing to end the turn on the first failure with that command's own
   output as the reason. Fails open on missing tooling, timeout (120 s,
   logged `unverified`), or any infrastructure error.
4. **The pre-change test check**, inside `require_green.py`, per decision 2
   above: `git show <base>:<path>` comparison of added or modified test
   functions' assertions, reported as a blocking finding.
5. **`format_touched.py`** (`PostToolUse` on `Edit|Write|MultiEdit`).
   **Formatter only.** Reads the touched path; if it is a `.py` file, runs
   `ruff format` against it (0.10 s). Non-Python files are a no-op.
   **The type checker moves to `require_green.py`** -- the draft put it
   here, and that is wrong on signal quality rather than cost: this hook
   fires between the edits of a multi-file sequence, where intermediate
   states are legitimately broken, so it would report errors that are
   expected and about to be fixed, and the agent would chase them.
6. **`Justfile`: let `just test` narrow.** One line, so that arguments
   replace the default target rather than appending to it. This does not
   itself make `require_green.py` run a subset -- mapping changed files to
   affected targets via `bazel query rdeps` is the follow-up -- but it is
   the prerequisite, and it is one line.
7. **Retire redundant prose** in `.codev/for-ai/ai-agent-guidelines.md` /
   `AGENTS.md`: sentences asking an agent to run the formatter or confirm
   tests pass become pointers to the now-deterministic hooks, per the
   instruction-budget rule that every hook added retires the prose it
   replaces in the same slice.
8. **Tests** for both new hooks and the repaired invocation: fail-open under
   missing tooling; correct block/refuse translation on a real failing
   check; correct allow on a real passing check; PATH-independent
   resolution; `format_touched.py` no-ops on a non-Python file; the
   source-untouched fast path allows without running anything.

## Validation

- `just test` -> full suite green.
- `just lint`, `just typecheck`, `just fmt-check` -> clean.
- `bazel run //scripts:verify_self_install` -> clean.
- New hook tests, by fixture-stdin subprocess in the style of
  `tests/test_claude_hook.py`.
- Manual: break a test, a lint rule, and a type annotation in turn; confirm
  `Stop` is refused each time with that check's own output. Touch a Python
  file; confirm it is reformatted. Empty `PATH`; confirm the gates still
  decide.
- Re-measure the always-on instruction payload against the slice's ledger
  row after step 7.

## Risks and rollout

- **Latency** is now measured, not estimated: 0 s on a turn that changed no
  source, ~26.7 s on one that did. Containment is the source-touched gate
  plus the 120 s timeout, both named above.
- **Working-tree safety**: the pre-change check reads git object storage via
  `git show` and never writes to or checks out the working tree.
- **Fail-open is the whole safety property.** A bug making either hook fail
  open on a *real* failure silently removes the guarantee this slice adds,
  which is why the tests cover the block/refuse path explicitly and not only
  fail-open.
- **A weaker pre-change check than D4 implies.** Recorded honestly above,
  with the rigorous version filed as follow-up rather than claimed.
- **Rollback**: remove the hook entries from `.claude/settings.json`, delete
  the two scripts, revert the one-line `Justfile` change.

## Decisions needed

None. The three the 2026-09-08 draft raised are resolved above; accepting
this plan accepts those resolutions. Two items are deliberately deferred and
need their own tasks, neither blocking this slice:

- the `gate.py:311` out-of-repo crash (outside this slice's accepted scope
  boundary); and
- affected-target test narrowing via `bazel query rdeps`, and the
  execution-based pre-change check.

## Completion evidence

- [ ] Full suite green
- [ ] `verify_self_install.py` clean
- [ ] Both hooks' fail-open and block/refuse paths covered by tests
- [ ] PATH-independent invocation covered by a test
- [ ] Manual: a real failing check refuses `Stop`; a touched file is
      reformatted; gates decide with an empty `PATH`
- [ ] Retired prose identified and removed, instruction budget re-measured
- [ ] CHANGELOG entry
- [ ] `git diff` confirms no change outside the allowed scope
