# Phase 6 - Cleanup & Promotion

**Status:** Draft, not yet approved for implementation
**Depends on:** Phases 1-5 of the "uv for AI delivery workflows" redesign -
config foundation, work lifecycle, CLI grammar consolidation, structural
adapter parity, eval/CI maturity - all implemented in the working tree. See
`CHANGELOG.md`'s `[Unreleased]` section for the authoritative list of what
shipped; this document does not repeat it.
**Risk:** normal - task 1 is a deliberate breaking change and needs one
human decision before it starts.

## Context

This is the last phase from the originally approved redesign plan. Nothing
in it has been started. It was deliberately not begun in the same session
that built Phases 1-5, so it gets picked up fresh with its own review rather
than being rushed at the end of a long implementation run.

## Task 1 - Remove the deprecated CLI aliases

**Change:** Delete `_apply_deprecated_aliases` and its call site in
`src/codev_workflow/cli.py::main`. After this, `codev check`, `codev
doctor`, `codev fixture create`, and bare `codev eval <name>` stop working
entirely; `codev status`, `codev status --verbose`, `codev eval fixture
create`, and `codev eval run <name>` become the only forms.

**Repository evidence:**
- `src/codev_workflow/cli.py`: `_apply_deprecated_aliases` and
  `_warn_deprecated` (added in Phase 3) are the functions to remove, along
  with the `_apply_deprecated_aliases(raw_argv)` call in `main`.
- `tests/test_cli.py` currently has tests written against the *old* forms
  that need updating to the new forms (not just deleting): the `check` calls
  inside `test_init_check_diff_round_trip`, `test_missing_install_returns_error`,
  `test_update_can_add_a_platform_to_an_existing_install`, and
  `test_update_can_add_codex_to_an_existing_install`. Also remove
  `test_doctor_alias_forwards_to_verbose_status`,
  `test_deprecated_aliases_rewrite_to_new_command_forms`, and
  `test_deprecated_fixture_create_matches_new_eval_fixture_create`-style
  tests outright, and trim `test_new_command_forms_pass_through_unchanged`
  down to whatever `_apply_deprecated_aliases`'s removal leaves meaningful
  (likely nothing, if the function is gone).

**Decision needed before starting:** CoDev is still pre-1.0 (0.1.7 as of
this writing). Under SemVer, the 0.x line treats the *minor* version as the
breaking-change boundary - there is no "major version" to bump yet in the
conventional sense. `docs/architecture.md`'s compatibility section talks
about "major releases" requiring migration and review without addressing
the 0.x case explicitly. Get an explicit human call on whether this breaking
change ships as the next 0.x.0 minor release or is held until a deliberate
1.0.0 cut, before touching any version number. Do not assume either answer.

**Validation:** `python -m unittest discover -s tests -v` green with the
alias-dependent tests updated or removed, not incidentally passing; grep the
bundle and root docs (`README.md`, `docs/`) for the four retired command
spellings to confirm nothing still recommends them.

## Task 2 - Reconcile skill-eval Windows-support docs

**Change:** `docs/features/skill-eval/README.md`'s "Platform and known
risks" section and `docs/features/skill-eval/design.md`'s "Goals" section
both still say Windows support is "deferred risk, not a V1 acceptance
requirement." That was accurate when written; it no longer matches reality.

**Repository evidence:**
- `src/codev_workflow/eval.py` has real, exercised `nt`-branch code:
  `_read_windows_source` (ctypes `CreateFileW` / `msvcrt.open_osfhandle`),
  `_sync_directory`'s `FlushFileBuffers` path, `_terminate`'s
  `taskkill /T /F`, and `_run`'s `CREATE_NEW_PROCESS_GROUP` flag.
- The entire Phase 1-5 redesign, including the Phase 5 seeded-defect corpus
  and its fixture-schema/verifier tests, was implemented and its full test
  suite run on Windows. The harness was exercised on Windows throughout this
  work, not merely theoretically supported by unexercised code branches.

**Proposed change:** Update both docs to state Windows is supported and has
been exercised in practice, keeping only the risk language that is still
genuinely open and platform-independent: the accepted V1 privacy risk for
URL credentials in diagnostics, and the publication crash/concurrent-output
issue. Do not silently drop those two - they are still real.

**Validation:** re-read both docs after editing to confirm no remaining
sentence contradicts what `eval.py` actually does. No code changes, so no
test-suite implication beyond re-running
`scripts/validate-development-workflow.py`.

## Task 3 - Promote past Alpha (conditional - likely not yet ready)

**Change:** `pyproject.toml`'s `Development Status :: 3 - Alpha` classifier
becomes `4 - Beta` (or later `5 - Production/Stable`).

**Stop condition:** the original plan gated this explicitly on Phases 1-5
having "shipped and held for one full release cycle." As of this writing,
Phases 1-5 exist in the working tree but have not shipped in any tagged
release. Do not do this task in the same pass as items 1 and 2 -
revisit it only after the next tagged release has been out and stable for a
cycle. If picking this document up shortly after items 1-2 land, the correct
action is usually to stop and report that this item's precondition isn't met
yet, not to complete it anyway.

## Task 4 - Reconcile other stale docs found during review

Found by actually running the tooling against this repo's own installation,
not by inspection alone - see "Known gaps" below for the live evidence.

**Change:**
- `docs/adoption.md:11` still tells adopters to run `codev check --target
  <repo>`; update to `codev status --target <repo>`.
- `docs/for-human/development-guide.md`'s "Retry spiral" row (both the root
  copy and `src/codev_workflow/bundle/docs/for-human/development-guide.md`)
  says "Stop after two failed attempts with the same root cause; escalate to
  the human" as if it were still pure convention. It is now mechanically
  enforced for the builder/reviewer round loop by `codev task check`'s
  `stop_round_cap` and `stop_repeated_finding` outcomes - update the row to
  say so, while keeping in mind the *builder's own* single-session retry loop
  (a different, smaller thing - see `build-change/SKILL.md` step 3) is still
  just convention and should not be described as enforced.

**Validation:** grep both docs after editing; no code change implied.

## Known gaps from Phases 1-5 (not part of Phase 6, but adjacent)

Carried over here so a future session has the full picture without
re-deriving it from a long conversation history:

- `codev adapter remove` was never built (Phase 3). The installer's
  `plan_remove` only removes an entire installation; per-platform removal
  needs new installer logic that did not exist before this redesign either.
- The full "adapter files rendered from one config source" ambition (Phase
  4's original, larger goal) was not built. `codev adapter verify` - the
  conformance checker that *was* built - is a second line of defense, not a
  structural fix. Rendering all four platforms' agent files from one
  canonical source remains open-ended future work of its own size.
- The `live-eval` CI job's "Install and authenticate OpenCode" step in
  `.github/workflows/ci.yml` is a deliberate failing placeholder. It needs
  this project's actual OpenCode CI installation and headless-auth mechanism
  wired in before that job does anything beyond fail loudly by design.
- Pre-existing ruff lint debt in `src/codev_workflow/eval.py` and two
  `.agents/skills/` scripts, and a separate pre-existing cluster of ~24
  errors/2 failures in `tests/test_eval.py` (distinct from the double-close
  bug already fixed), predate this redesign and were spun off separately -
  check whether they were resolved before assuming this document's
  "Validation" sections start from a fully green baseline.

## Completion evidence (fill in when implemented)

- **Delivered:**
- **Changed:**
- **Head commit/snapshot:**
- **Validation actually run:**
- **Review state:**
