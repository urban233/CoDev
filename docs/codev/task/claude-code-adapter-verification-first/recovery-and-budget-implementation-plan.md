# Slice 5: Recovery, Frontmatter, Compat, Budget Assertion - Implementation Plan

**Status:** Accepted
**Owner:** urban233
**Reviewer:** independent reviewer, to be named before the pull request is marked ready
**Risk:** medium. `SessionStart`/`PreCompact` are new hook events for this
bundle; `statusLine` is new UI surface; `isolation: worktree` changes how the
five specialists run and, if misconfigured, would review the wrong code
silently (see Repository evidence). No change to any gate's decision logic.
**Containment:** every new hook fails open on infrastructure error, matching
the existing four. `statusLine` failure degrades to Claude Code's own
default status line, not a broken session. `isolation: worktree` is
reversible per agent by deleting one frontmatter line. Rollback is deleting
the new hook/settings entries and the two new scripts.
**Work style:** `pair` (recorded, per the parent plan's own designation)
**Slices:** 5, per the parent plan -- reordered 2026-09-11: this slice builds
**before** `scientific-gates`. See
[docs/plans/claude-code-adapter-verification-first.md](../../../plans/claude-code-adapter-verification-first.md),
"Reordering" section.
**Slice:** `recovery-and-budget` (4th to build; kept as "slice 5" throughout
this document to match the parent plan's D7/ledger references, which predate
the reorder)
**Base commit:** `99a46f1` (head of merged slice 3, evidence-hooks)
**Issue/work item:** [urban233/CoDev#47](https://github.com/urban233/CoDev/issues/47)
**Brief/design/API:** [docs/plans/claude-code-adapter-verification-first.md](../../../plans/claude-code-adapter-verification-first.md), Accepted 2026-09-08 -- D7, and D3's `PreCompact` bullet (deferred here by the evidence-hooks plan's own Decision 3)

## Focus card

- **Change:** add `SessionStart` and `PreCompact` hooks, a `statusLine`
  script, `isolation: worktree` (correctly based on the reviewed branch, not
  main) on the five outer-loop specialists, extend
  `verify_claude_code_compat.py` to cover the frontmatter/hook surface this
  bundle now depends on, and make the instruction-budget rule enforceable by
  a test instead of a manually-updated ledger comment.
- **Success:** every session start shows `codev next`'s current position to
  Claude without being asked; a session that survives a mid-conversation
  compaction still has that position available afterward; the status line
  shows branch/slice/round/context-used at a glance; the five specialists
  run in worktrees isolated from each other **and correctly checked out from
  the branch under review**, so two of them can no longer collide on the
  same file; `verify_claude_code_compat.py` would catch it if any of this
  surface disappeared from a future Claude Code release; and the always-on
  instruction payload has a test asserting it, not just a table someone has
  to remember to update.
- **Non-goals:** D5's scientific gates (builds after this slice -- see the
  parent plan's Reordering note). Any other adapter. Raising the
  specialists' `maxTurns` (issue #39 -- a real, separate problem this
  slice's `isolation` change does not touch).
- **Allowed scope:** `.claude/settings.json` and its bundle mirror, two new
  hook scripts (`restore_position.py`, `checkpoint_state.py`) plus the three
  existing gate hooks and `format_touched.py` (folding in the
  `_gate_common.py` extraction -- see "Scope: what is folded in"), one new
  `statusline.py` script, all five `.claude/agents/*-specialist.md` files,
  `scripts/verify_claude_code_compat.py`, `tests/`,
  `AGENTS.md`/`.codev/for-ai/ai-agent-guidelines.md`, `CHANGELOG.md`.
- **Validation:** new hook/statusline tests by fixture-stdin subprocess,
  matching `tests/test_claude_hook.py`'s pattern; full test suite; the new
  instruction-budget regression test itself; manual confirmation of
  `SessionStart` (all four sources: `startup`, `resume`, `clear`, `compact`)
  in a real session, and of the status line rendering.
- **Stop if:** the instruction-budget baseline measured below turns out to
  already exceed the ratcheted ceiling by more than this slice's own
  housekeeping can retire (see Decision 1) -- that is a stop-and-revise
  condition, not something to quietly widen the ceiling around.

## Scope: what is folded in, and what is not

**Folded in -- the `_gate_common.py` extraction (issue #65).** The three
existing gate hooks each carry an identical, independently-maintained copy
of `_codev_argv()`, `_log_decision()`, and the `_INFRASTRUCTURE`/
`_HOOK_ERROR` constants. This slice adds two more hooks needing the same CLI
resolution and the same local decision log -- copying it a fourth and fifth
time is the point triplication becomes quintuplication. Extracting now costs
one shared module and touches the three existing hooks only to replace their
copy with an import, no behavior change (pinned by the existing hook tests
passing unmodified). Closes issue #65.

**Not folded in -- raising the specialists' `maxTurns`.** Issue #39 (five of
six outer-loop subagents hit their 40-turn cap in this session's own work)
is real, but it is a capacity-tuning question, not a recovery or
frontmatter-surface one, and `isolation`/`worktree.baseRef` (this slice) are
unrelated settings keys on the same files for a different reason. Left as
its own follow-up.

## Repository evidence

- `.claude/settings.json` currently declares four hooks (`PreToolUse` x3,
  `PostToolUse` x1, `Stop` x1) and the D6 permission surface; no
  `SessionStart`, `PreCompact`, `statusLine`, or `worktree` key exists yet.
- All five specialist agents already set `model`; only
  `correctness-tests-specialist` sets `maxTurns`/`permissionMode`; none sets
  `isolation`.
- `scripts/verify_claude_code_compat.py` already lists `SessionStart` and
  `PreCompact` in `_EXPECTED_HOOK_EVENTS` (added ahead of use during an
  earlier spike), but has no marker for `statusLine`, `isolation`, `effort`,
  `memory`, `worktree.baseRef`, or per-subagent `hooks` -- the gap the
  parent plan's own repository evidence named.
- No script or test measures the always-on instruction payload today.
  Slices 1 and 3 tracked it by hand, for two of the five sources the
  original 2026-09-08 research measured (`ai-agent-guidelines.md` and
  `AGENTS.md` -- not `.claude/CLAUDE.md`, skill descriptions, or agent
  descriptions).
- **Confirmed against the current Claude Code docs (`hooks.md`,
  `statusline.md`, `sub-agents.md`, `worktrees.md`), 2026-09-11:**
  - `SessionStart`'s payload carries a `source` field (`startup`, `resume`,
    `clear`, `compact`, `fork`), so a hook can tell these apart, but its
    output supports `hookSpecificOutput.systemMessage` (shown to Claude),
    **not** `additionalContext` -- that field is `PreToolUse`/`PostToolUse`
    only.
  - `PreCompact` and `SessionStart` both receive the same `scratchpad_dir`
    in their payload. A file `PreCompact` writes there is still present and
    readable by the `SessionStart` hook that fires once compaction
    completes (`source: "compact"`) -- this is the native mechanism D3 and
    D7 need, and it needs no `.codev/`-side gitignore entry, since
    `scratchpad_dir` already lives outside the repository.
  - `statusLine` is a top-level `.claude/settings.json` key:
    `{"type": "command", "command": "..."}`. Its stdin payload includes
    `context_window.used_percentage`, pre-calculated -- no token counting
    of our own needed.
  - `isolation: worktree` is a plain string frontmatter field. **Critically:
    "Subagent worktrees use the same base branch as `--worktree`, so they
    branch from your repository's default branch unless `worktree.baseRef`
    is set to `"head"`."** Applied to the five specialists with no other
    change, this would silently check each one out from `main` rather than
    from the pull request's own head -- they would review the wrong code
    and every finding they returned would be worthless, with nothing in
    their output shape signaling the mistake. `worktree.baseRef: "head"` is
    therefore not an optional refinement; it is required for this slice's
    `isolation` change to do anything other than actively break outer-loop
    review. Both settings ship together in the same commit.

## Decisions needed

**1. The instruction budget's enforced unit and ceiling.**
The original research measured "tokens (approx.)" once, by hand, at
`d13e0a9`, and set a 7,500-token ceiling. Slices 1 and 3's per-slice ledger
entries tracked byte deltas for two files only. Measuring all five of the
original sources in bytes, now:

  | Source | `d13e0a9` (bytes) | Current (bytes) |
  |---|---:|---:|
  | `ai-agent-guidelines.md` | 25,751 | 15,563 |
  | `AGENTS.md` | 6,570 | 7,090 |
  | `.claude/CLAUDE.md` | 2,411 | 3,514 |
  | Skill descriptions (15 files) | 6,903 | 6,903 |
  | Agent descriptions (10 files) | 1,183 | 1,319 |
  | **Total** | **42,818** | **34,389** |

  The original baseline's own bytes-per-token ratio (42,818 / 9,698 $\approx$
  4.41 bytes/token) puts the accepted 7,500-token ceiling at roughly
  **33,100 bytes**. The current 34,389-byte total across all five sources is
  already **~1,300 bytes above that**, before this slice or `scientific-gates`
  (building after this one) add anything -- because the per-slice ledger
  only ever tracked two of the five sources, `.claude/CLAUDE.md` and the
  agent-description growth went unmeasured against the ceiling the whole
  time.

  This is a derived estimate (a byte/token ratio from one snapshot), not a
  re-run of a real tokenizer, so it is a proxy, but it is exactly the gap
  this slice exists to close.

  **Proposed resolution, needing your confirmation:** adopt bytes as the
  enforced unit going forward (no new tokenizer dependency; matches what
  slices 1 and 3 already did in practice for the two files they tracked),
  set the ceiling at **33,100 bytes** across the same five sources (derived
  above), and treat the ~1,300-byte gap as this slice's own problem to close
  via retirement -- not a reason to raise the ceiling -- before calling the
  slice done. If the retirement this slice's own hooks license (see step 8)
  isn't enough to close it, that is a stop condition for this slice, per the
  focus card.

## Proposed change

1. **Extract `.claude/hooks/_gate_common.py`.** Move `_codev_argv()`,
   `_log_decision()`, `_INFRASTRUCTURE`, `_HOOK_ERROR` out of the three
   existing gate hooks into one shared module; each hook imports it. No
   behavior change -- the existing hook test suite is the regression guard,
   run unmodified.
2. **`restore_position.py`** (`SessionStart`, all four `source` values).
   Resolve `codev` via the shared module, run `codev next --json`, translate
   its `position` and `recommendation` fields into
   `hookSpecificOutput.systemMessage`, plain language. Fails open (no
   output, never a block) on unreachable `codev`, a nonzero exit, a timeout,
   or unparseable output.
3. **`checkpoint_state.py`** (`PreCompact`). Writes the same `codev next
   --json` output, plus the currently accepted plan's path if one is
   recorded for the active branch, to `<scratchpad_dir>/checkpoint.json`.
   `restore_position.py` (step 2) reads this file when present and the
   payload's `source` is `"compact"`, folding its content into the same
   `systemMessage` -- redundant with a fresh `codev next --json` call in the
   common case, but independently useful if `codev` itself is briefly
   unreachable right after a compaction.
4. **`statusline.py`** (`statusLine`). Reads branch, current slice, and
   current round directly from the task's own `round-state.json` (cheaper
   and more current than shelling out to `codev` on every prompt render),
   plus `context_window.used_percentage` from the statusLine payload
   directly. One line of plain text on stdout.
5. **`isolation: worktree` on all five `.claude/agents/*-specialist.md`
   files, together with `"worktree": {"baseRef": "head"}` in
   `.claude/settings.json`.** Both land in the same commit -- see Repository
   evidence for why the second is not optional.
6. **Extend `verify_claude_code_compat.py`**: add `statusLine`, `isolation`,
   `worktree`, `baseRef`, `effort`, `memory`, and per-subagent `hooks` to the
   expected-marker set, alongside the `SessionStart`/`PreCompact` markers
   already present.
7. **The instruction-budget regression test**
   (`tests/test_instruction_budget.py`): measures the five sources above by
   byte count and asserts the total is at or below 33,100 bytes (Decision
   1). A second assertion compares against a small on-disk baseline file
   this slice adds (`.codev/instruction-budget-baseline.json`, committed,
   not gitignored -- meant to be read and updated deliberately, unlike the
   hook decision log), so a later slice that increases the total fails
   loudly rather than only at the absolute ceiling.
8. **Retire whatever prose these six changes make redundant**, per the
   standing instruction-budget rule, in this same slice -- exact lines
   identified once steps 1-6 are built. This retirement is load-bearing for
   Decision 1's ~1,300-byte gap, not cosmetic.
9. **Tests**: fixture-stdin subprocess tests for `restore_position.py`
   (each `source` value; the `compact` + checkpoint-file combination;
   fail-open on missing `codev`) and `checkpoint_state.py` (file actually
   written to the payload's `scratchpad_dir`); a test for `statusline.py`'s
   output; a test confirming all five specialist files carry
   `isolation: worktree` and that `worktree.baseRef` is `"head"`; the
   instruction-budget test itself; `_gate_common.py`'s extraction verified
   by the existing hook tests passing unmodified.

## Validation

- `just test` -> full suite green, including the new instruction-budget test.
- `just lint`, `just typecheck`, `just fmt-check` -> clean.
- `bazel run //scripts:verify_self_install` -> clean.
- `scripts/verify_claude_code_compat.py` passes against the currently
  published Claude Code CLI with the extended marker set.
- Manual, in a real Claude Code session: a fresh start, a `/clear`, and a
  `--resume` each show the restored position; the status line renders; a
  specialist dispatched under `isolation: worktree` is confirmed (via its
  own `git branch --show-current` or equivalent) to be checked out from the
  reviewed branch, not `main`.
- Re-measure the five-source instruction payload against this slice's own
  ledger row after step 8; confirm it is at or under 33,100 bytes.

## Risks and rollout

- **`isolation: worktree` without `worktree.baseRef: "head"` is an active
  regression**, not a neutral change -- named explicitly above because it is
  the one mistake in this slice that would ship silently green (every test
  could pass while every specialist reviews the wrong commit). Mitigation:
  shipped together, and pinned by the manual validation step that greps the
  isolated worktree's actual checked-out branch.
- **A bug in `checkpoint_state.py` or `restore_position.py` is silent by
  design** (fail-open, no block) -- correct for advisory context, but a
  broken restoration would not announce itself. Mitigation: both are
  covered by tests asserting the actual translated `systemMessage`, not
  only that the hook exits zero.
- **The instruction-budget ceiling may already be missed** (Decision 1) --
  if so, this slice is not done until the real total is back under it.
- **Rollback**: remove the new/changed hook and `worktree` entries from
  `.claude/settings.json`, delete `_gate_common.py` (reverting the three
  existing hooks' import), delete the two new scripts and `statusline.py`,
  remove the `isolation` line from the five specialist files, revert the
  compat-script and budget-test additions.

## Completion evidence

- [x] Full suite green (39/39), including the new instruction-budget test
- [x] `verify_claude_code_compat.py` passes against the published CLI (2.1.269)
      with the extended marker set (35/35)
- [x] `_gate_common.py` extracted; existing hook tests pass unmodified
- [x] `SessionStart`, `PreCompact`, `statusLine` each covered by fixture-stdin
      tests (14 tests total, both fail-open directions and the
      compact-checkpoint fallback in both directions)
- [ ] Manual confirmation in a real Claude Code session (startup, `/clear`,
      `--resume`, and after a real compaction) -- needs the developer's own
      session; not reproducible from inside this one
- [x] All five specialist files carry `isolation: worktree`;
      `worktree.baseRef` is `"head"`; both mutation-checked
      (`tests/test_installer.py::test_specialists_install_isolated_and_correctly_based`)
- [ ] Manually confirmed a specialist worktree is actually cut from the
      reviewed branch, not `main`, in a live outer-loop review -- needs a
      real pull request and a real specialist dispatch after this merges
- [x] Instruction-budget total measured (34,389 bytes) and recorded in
      `.codev/instruction-budget-baseline.json`; **not** at or under 33,100
      bytes -- see Decision 1's resolution and issue #69 (developer-approved
      follow-up, 2026-09-12), ceiling assertion explicitly skipped with that
      reasoning rather than silently passing or blocking this slice
- [x] Retired prose identified: this slice's own hooks license only ~294
      bytes (the "Say where things stand" bullet), not retired separately
      since it remains partially true (SessionStart covers only the
      session-boundary case, not "after every state change") -- folded into
      issue #69 rather than a token trim that would not move the real number
- [x] CHANGELOG entry
- [x] `git diff` confirms no change outside the allowed scope
