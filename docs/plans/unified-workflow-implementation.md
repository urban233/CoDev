# Unified Workflow - Implementation Plan

**Status:** Draft, not yet approved for implementation
**Owner:** Martin Urban
**Author:** Claude Opus 5 (drafted; not an approval)
**Brief:** [docs/features/unified-workflow/brief.md](../features/unified-workflow/brief.md)
**Decisions:** [ADR-0035](../adr/0035-slice-is-the-unit-of-execution.md),
[ADR-0036](../adr/0036-cli-is-an-agent-interface.md),
[ADR-0037](../adr/0037-human-review-and-ownership-gate.md),
[ADR-0038](../adr/0038-work-style-is-a-slice-property.md)
**Base commit:** `bb54a6b`
**Risk:** normal overall; two slices are high and are named as such below.

## Context

The accepted brief lists nine items under "Now." This plan turns them into
eight tasks and twenty slices, in the vocabulary ADR-0035 established: a
**task** is the collection that gets one GitHub issue, and a **slice** is the
unit that gets one branch, one round state, and one pull request. Every slice
below is sized to stay inside `review.max_lines` (400 non-generated changed
lines) including its tests, because a plan that proposes the small-pull-request
discipline and then violates it is not credible.

This plan follows the rolling-wave discipline ADR-0032 accepted: **Wave 1 is
detailed and ready; Waves 2 to 4 are deliberately coarse.** Their slice
boundaries and sizes are real, but their focus cards are not written, because
the evidence that should shape them does not exist yet — Wave 1 answers three
of the brief's open assumptions, and detailing later waves now would bake in
guesses this plan would then have to defend.

Nothing here is started. This document is authority to be reviewed, not work in
progress.

## Ordering, and why it is not the brief's order

The brief lists its nine items roughly by conceptual importance. Implementation
order differs for two reasons that only became visible when sizing the work:

- **The `ok_approve` rename (ADR-0037) must precede the oracle (ADR-0036).**
  The oracle's whole job is to translate `task.check` outcomes into
  recommendations. Writing it against a name scheduled for renaming means
  writing it twice.
- **The round-state schema change (ADR-0035) must also precede the oracle**, for
  the same reason: the oracle reads round state, and reading a schema that is
  about to gain a slice dimension is wasted work.

So the two changes the pull request for #15 flagged as needing to land early are
not merely early — they are Wave 1, ahead of the capability that motivated the
whole brief.

| Wave | Tasks | Outcome |
|---|---|---|
| 1 | A, D-prep, E-prep | The CLI is machine-readable, the schema carries slices, and the misleading state name is gone |
| 2 | D, B | The slice model is real and the oracle answers from it |
| 3 | C, E, F | Guidance becomes obligatory, the human gate exists, pair work is supported |
| 4 | G, H | Gates work on every adapter, and the documentation describes what now exists |

---

# Wave 1 - Foundation

Three tasks. Everything after this depends on all three, so the wave has a hard
integration checkpoint: `.tools/just ci` green on `main` before Wave 2 opens.

## Task A - Complete the agent surface

**Issue:** to be created
**Risk:** low
**Containment:** N/A - `--json` is additive and off by default
**Decision:** [ADR-0036](../adr/0036-cli-is-an-agent-interface.md)
**Slices:** 3

### Focus card

- **Change:** Every `codev` command an agent invokes emits machine-readable
  output for every value the agent needs next.
- **Success:** No agent instruction in the bundle directs an agent to read a
  value out of prose or to fall back to raw `git`; `codev git commit --json`
  returns the head an agent must pass to the next check.
- **Non-goals:** Changing any command's default human-readable output; adding
  new commands; the oracle itself.
- **Allowed scope:** `src/codev_workflow/cli.py`, `git_ops.py`, `task.py`
  (return shapes only), `tests/test_cli.py`, `tests/test_git_ops.py`,
  `docs/cli-reference.md`, `docs/product-map.md`, the bundle's agent files.
- **Validation:** `.tools/just test`, `.tools/just lint`, `.tools/just typecheck`.
- **Stop if:** any existing human-readable output cannot be preserved
  byte-for-byte, which would make this a breaking change rather than an
  additive one.
- **Work style:** Bounded delegate. Mechanical, well-specified, fully covered by
  tests.

### Repository evidence

- `src/codev_workflow/cli.py`: eight leaf parsers accept `--json` today —
  `status`, `adapter list`, `adapter verify`, `config get`, `config list`,
  `task check`, `task status`, `task size`. Roughly forty exist.
- `src/codev_workflow/cli.py:_run_git_command`: every `git` verb prints a
  sentence. `commit` prints `Committed {head} on {id}'s branch`; `restack`
  prints `Restacked {id}'s branch onto its parent; new head {new_head}`.
  `open-pr` and `issue-create` print a bare URL.
- `src/codev_workflow/git_ops.py`: `commit` (line 873), `push` (904), `open_pr`
  (953), `mark_ready` (1020), `restack` (1034), `create_branch` (543) already
  compute or hold every value the printed sentences summarize.
- `docs/product-map.md:83`, `docs/cli-reference.md:120`, and `cli.py:404` each
  document `codev codeowners init` as human-run, never agent-invoked.

### Slices

**A1 - `--json` across the `git` group.** *Contract-first.* Add `--json` to
`branch`, `commit`, `push`, `open-pr`, `mark-ready`, `restack`, `issue-create`,
and `issue-view`, each emitting the identifiers the next command consumes
(branch, head, pull-request URL and number, issue number, new head after a
restack). Human-readable output unchanged. Estimated 300 lines with tests.

**A2 - `--json` across the remaining `task` verbs.** *Contract-first.* `start`,
`record`, `close`, `reopen`, `waive`, `relink`, `triage`, `escalate`, `log`,
`escalations`. `log` and `escalations` return structured rounds and records
rather than rendered text. Estimated 300 lines with tests.

**A3 - Close the human-run carve-outs.** *Behavior-vertical.* Give `codev
codeowners init` an agent-invocable form under the ordinary confirmation
posture, and make `codev init` the single documented bootstrap exception in
`docs/product-map.md`, `docs/cli-reference.md`, and the parser help. Sweep the
bundle's agent and skill files for any instruction to parse prose or shell out
to raw `git` for a value a guarded command now returns. Estimated 200 lines.

### Validation

- `.tools/just test` -> all suites pass, including new `--json` cases in
  `tests/test_cli.py` and `tests/test_git_ops.py`.
- `.tools/just lint`, `.tools/just fmt-check`, `.tools/just typecheck` -> clean.
- A golden-output test asserting each command's non-`--json` stdout is unchanged.

### Risks and rollout

- The compatibility risk is inverted from the usual case: the danger is not the
  new flag but an accidental edit to default output that an adopter's script or
  a recovery procedure depends on. The golden-output test is the control.
- No flag or config guard is needed; absent `--json`, nothing changes.

### Decisions needed

None. ADR-0036 settles the shape.

---

## Task D-prep - Slice identity in the state layer

**Issue:** to be created
**Risk:** **high** - schema change to the file that carries every task's
evidence trail
**Containment:** version-gated reader accepting both schema shapes
**Decision:** [ADR-0035](../adr/0035-slice-is-the-unit-of-execution.md)
**Slices:** 1

### Focus card

- **Change:** Round state gains a slice dimension, and every existing record
  reads as a task holding exactly one slice.
- **Success:** Every closed task in the repository's own history replays
  correctly under the new reader with no file rewritten, and no CLI behavior
  changes at all.
- **Non-goals:** Any user-visible change; generating slices from a plan;
  moving the git surface onto slices. Those are Wave 2.
- **Allowed scope:** `src/codev_workflow/task.py`, `tests/test_task.py`.
- **Validation:** `.tools/just test`, plus a replay test over recorded fixtures.
- **Stop if:** any existing round-state file cannot be read without rewriting
  it — that would make this a migration rather than a defaulted field, and
  needs a separate human decision.
- **Work style:** **Pair.** This is the evidence trail. `ROUND_SCHEMA_VERSION`
  is at 3 (`task.py:51`) and the drift, round-cap, and coverage guards all read
  the structure this slice changes.

### Repository evidence

- `src/codev_workflow/task.py:51`: `ROUND_SCHEMA_VERSION = 3`.
- `src/codev_workflow/task.py:732`: `check` reads `state["rounds"]`, the
  latest round's `phase`, `builder`/`reviewer` head snapshots, `triage`, and
  the coverage manifest. Every one of the thirteen outcomes is derived from
  that structure.
- `src/codev_workflow/git_ops.py:82`: task state lives at
  `.codev/task/<task_id>/`, holding `round-state.json` and `git-state.json`.
- `.codev/task/` is absent from this repository's working tree, so the replay
  fixtures must be constructed rather than harvested.

### Slices

**D-prep-1 - Version the schema and default the slice identity.**
*Preparatory refactor.* Increment `ROUND_SCHEMA_VERSION` to 4; teach the reader
to accept both 3 and 4; give every round a slice identity defaulting to the
task id; leave every writer, every guard, and every CLI verb behaving exactly
as before. No observable change. Estimated 350 lines, the majority of it the
replay tests.

### Validation

- `.tools/just test` -> all existing `tests/test_task.py` cases pass unmodified.
  This is the acceptance criterion: an unmodified existing suite is the evidence
  that behavior did not change.
- A new replay test constructing a version-3 round-state file for each of the
  thirteen `check` outcomes, then asserting the version-4 reader returns the
  identical `CheckResult`.

### Risks and rollout

- Highest-risk slice in the plan. It is deliberately first, alone in its task,
  and paired, so that it lands with maximum attention and nothing else in flight.
- Rollback is a revert: no file on disk is rewritten, so a revert leaves no
  version-4 artifacts behind. That property is worth preserving explicitly and
  is why the writers stay untouched in this slice.

### Decisions accepted

**Version-4 writing is deferred to Wave 2 (accepted 2026-09-02).** This slice
reads both schema shapes and writes only version 3. The revert therefore leaves
no version-4 artifact on disk, which is the property that makes the highest-risk
slice in this plan safe to land first. Slice D1 enables the writers.

---

## Task E-prep - Rename the misleading approval state

**Issue:** to be created
**Risk:** **high** - observable behavior change with external consumers
**Containment:** deprecation window, both names accepted
**Decision:** [ADR-0037](../adr/0037-human-review-and-ownership-gate.md)
**Slices:** 1

### Focus card

- **Change:** `task.check`'s `ok_approve` is renamed to say what it means —
  that the machine gates are satisfied, not that a human approved anything.
- **Success:** Every internal caller uses the new name; the old name still
  resolves, with a deprecation warning, for one release.
- **Non-goals:** `ok_human_approved` itself, CODEOWNERS, and reviewer requests.
  Those are Wave 3, and depend on the task owning a reviewer, which does not
  exist until Wave 2.
- **Allowed scope:** `src/codev_workflow/task.py`, `git_ops.py` (the gate checks
  in `open_pr` and `mark_ready`), `cli.py`, `tests/`, the bundle's agent files,
  `docs/cli-reference.md`, `CHANGELOG.md`.
- **Validation:** `.tools/just ci`.
- **Stop if:** the deprecation cannot be expressed without branching the exit
  code as well as the reason string, which would widen this past a rename.
- **Work style:** **Pair.** The name appears in agent instructions, adopter
  scripts we cannot see, and two gate checks that refuse to act on the wrong
  value.

### Repository evidence

- `src/codev_workflow/task.py:732`: `check` returns `ok_approve` once the
  coverage manifest is complete and the reviewer decided
  `READY_FOR_HUMAN_APPROVAL`.
- `src/codev_workflow/git_ops.py:978` and `:1026`: `open_pr` and `mark_ready`
  each refuse on the wrong `codev task check` result and name it in the refusal
  message, so both messages change with the name.
- `src/codev_workflow/bundle/.claude/agents/outer-loop-runner.md` and
  `.codev/for-ai/ai-agent-guidelines.md` both instruct agents on `ok_approve`
  and `ok_approve_with_deferrals` by name.

### Slices

**E-prep-1 - Rename with a deprecation window.** *Preparatory refactor.*
`ok_approve` becomes `ok_machine_review_complete` and
`ok_approve_with_deferrals` becomes `ok_machine_review_complete_with_deferrals`,
in the same slice. Both old names keep resolving with a deprecation warning for
one release. Updates both gate checks (`git_ops.py:978`, `:1026`), every bundle
instruction naming either value, `docs/cli-reference.md`, and `CHANGELOG.md`.
Estimated 300 lines.

### Validation

- `.tools/just ci` -> green, including `tests/test_documentation_links.py`,
  which will catch bundle instructions that still name the old value.
- A test asserting the deprecated name still resolves and warns.

### Risks and rollout

- Adopters may have scripts reading `codev task check --json`'s reason. The
  deprecation window is the containment; the changelog entry is the notice.
- The name was referred to the accountable human rather than chosen by the
  drafting agent, and is now settled; see "Decisions accepted" above.

### Decisions accepted

**The replacement name is `ok_machine_review_complete` (accepted 2026-09-02)**,
paired with `ok_machine_review_complete_with_deferrals`. It is long, and it is
long in the direction that prevents the confusion ADR-0037 exists to prevent.
Both names change together in this slice; renaming one of the pair and not the
other is worse than renaming neither.

---

# Wave 2 - The model and the oracle

Coarse by intent. Wave 1 resolves the schema-migration and output-compatibility
assumptions that should shape these slices.

## Task D - The slice becomes the unit of execution

**Risk:** high. **Decision:** ADR-0035. **Depends on:** D-prep, A1.

- **D1 - Write version 4, and move round state onto the slice.**
  *Preparatory refactor.* Enables the writers D-prep deliberately deferred.
  ~350 lines.
- **D2 - The task owns an ordered slice list.** *Contract-first.* `parent_task`
  is populated from that list; `Part of #N` versus `Closes #N` is read from it
  rather than derived by `_has_recorded_child` (`git_ops.py:363`). ~300 lines.
- **D3 - Generate a task's slices from an accepted plan.** *Behavior-vertical.*
  The task issue template's `Slices:` field stops being advisory prose and
  becomes the input, carrying its decomposition strategy as slice metadata.
  ~350 lines.
- **D4 - Per-slice size reporting.** *Behavior-vertical.* `codev status`'s size
  budget applies per slice, since a reviewer reads a pull request. The task
  total stays reported and stays uncapped. ~200 lines.

## Task B - The state oracle

**Risk:** normal. **Decision:** ADR-0036. **Depends on:** D2, E-prep, A1, A2.

- **B1 - Local positions.** *Behavior-vertical.* `codev next --json` over
  branch, git state, slice round state, and `task.check`, covering all thirteen
  outcomes plus no-task and no-branch. ~350 lines.
- **B2 - GitHub positions.** *Behavior-vertical.* Pull-request state, review
  state, and merged-slice-with-slices-remaining. ~300 lines.

**Open assumption this wave must answer:** whether every one of the thirteen
outcomes maps to a distinct recommendation, or several collapse. The brief
records this; B1 is where it gets settled.

---

# Wave 3 - Obligation, gate, and pair work

Three tasks that can run concurrently once Wave 2 lands, subject to the review
capacity noted at the end of this plan. Each opens with an assumption its first
slice must settle.

## Task C - The guidance obligation

**Risk:** low. **Decision:** ADR-0036. **Depends on:** B2.

- **C1 - Amend the interaction contract and the three entry-point agents** to
  consult the oracle at the start of every turn and after every state change,
  and to open every phase boundary with position, recommendation, and reason.
  Bundle files plus `.codev/for-ai/ai-agent-guidelines.md`. ~250 lines.

**Gate before C1 starts:** the brief's discovery step — run one real task with
the oracle stubbed by hand and judge whether each boundary recommendation was
worth stating. If recommendations read as noise, C1 does not ship as written.

## Task E - The human review and ownership gate

**Risk:** high. **Decision:** ADR-0037. **Depends on:** D2, E-prep.

- **E1 - Reviewer request and ownership statement.** *Behavior-vertical.*
  `codev git mark-ready` requests review from the task's independent reviewer,
  resolved from the wave plan or `.github/CODEOWNERS`, and writes the owner's
  ownership statement into the pull-request body. ~300 lines.
- **E2 - `ok_human_approved`.** *Behavior-vertical.* Reads GitHub's review state
  and requires an approving review from someone who is neither the task owner
  nor a bot. ~300 lines.
- **E3 - The two-approval rule.** *Wiring behind a guard.* Applies only at
  `risk:high`/`risk:critical` or a configured sensitive path set. ~250 lines.

**Open assumption this wave must answer first:** whether GitHub's review API
distinguishes an author's own approval from an independent one on every plan
tier. If it does not, E2's design changes before it is built.

**Named risk:** a repository with no CODEOWNERS and no wave plan cannot resolve
a reviewer, and a solo adopter cannot satisfy this gate at all. ADR-0037 records
that as correct; E1 must let such a repository record that it deliberately
operates without one, rather than failing every task silently.

## Task F - Work style and pair work

**Risk:** normal. **Decision:** ADR-0038. **Depends on:** D1.

- **F1 - Style as a slice property.** *Contract-first.* `pair`/`delegate`,
  defaulting to `delegate`; `orchestrator` skips builder dispatch at a `pair`
  slice and rejoins at the reviewer step. ~300 lines.
- **F2 - Declared critical paths.** *Wiring behind a guard.* `review.pair_paths`
  resolved through `config.py`, gated with ADR-0030's ask-and-pause posture.
  ~250 lines.
- **F3 - Pause, resume, and `critical_interrupt`.** *Behavior-vertical.* Closes
  the interruption hole, reusing `task.reopen`'s re-baselining. ~300 lines.

**Note:** F3 is a correctness fix, not only a feature. A `stop_drift` after an
interrupt is a false report about what happened.

---

# Wave 4 - Portability and documentation

The two tasks with no dependency on each other, and the two most separable from
the plan as a whole if scope has to be cut.

## Task G - Gate logic moves into `codev`

**Risk:** normal. **Decision:** brief item 8. **Depends on:** nothing in Waves 1
to 3. **In scope, scheduled last within Wave 4** (accepted 2026-09-02).

- **G1 - `codev gate check`** owning the decisions in `require_plan.py`,
  `require_wave_shape.py`, and `require_small_change.py`. ~350 lines.
- **G2 - Hooks become shims, and other adapters are wired.** ~250 lines.

**Caution:** `.claude/hooks/` and `src/codev_workflow/bundle/.claude/hooks/` are
byte-identical, and the root copy is installed from the bundle — commit
`49640c0` exists because that sync broke once. Every hook change edits the
bundle and re-syncs; it never edits the root copy directly.

## Task H - The documentation site describes what now exists

**Risk:** low. **Depends on:** every wave above, deliberately. Documenting a
workflow before it exists is how the current site drifted from the product.

- **H1 - Navigation and the mental model.** Promote `onboarding-guide.md` to a
  sidebar entry and the first home-page card; make the conversational page the
  primary path and the CLI pages reference material; rewrite Concepts as a model
  with the inner and outer loops drawn, correcting the claim that Understand
  equals `codev task start`.
- **H2 - The missing pages.** A roles page covering every agent, including
  `lightweight-reviewer` and `code-audit-gate`, which appear on zero pages
  today; pages for slicing and stacking, and for the evaluation harness.
- **H3 - Dialogue for every phase**, including the agent's recommendations,
  extending `working-with-your-agent.mdx` past its current four exchanges.

**Acceptance for H:** two engineers unfamiliar with CoDev browse the site and
state the mental model back correctly. The brief records this as the discovery
step for the site, and it is the only honest acceptance criterion for
documentation.

---

## Validation, everywhere

Every slice runs the same gate before its pull request opens:

- `.tools/just test` - the standard-library suite under the default toolchain
- `.tools/just lint` and `.tools/just fmt-check`
- `.tools/just typecheck` - mypy, `strict = true`
- `.tools/just ci` at each wave's integration checkpoint

`just` is the required entry point per `AGENTS.md`; `bazel` and raw
`python -m ruff`/`mypy` are never invoked directly. `.tools/just` is the
repo-local binary.

## Risks carried across the whole plan

- **Two high-risk slices, both in Wave 1.** D-prep-1 touches the evidence trail;
  E-prep-1 changes an observable value external scripts may read. Both are
  marked `Pair`, both land alone, and both are revertible without leaving
  artifacts behind.
- **This plan proposes changing the workflow that is building it.** Wave 1 lands
  before the slice model exists, so Wave 1 itself is tracked the old way. That
  is not a defect to engineer around; it is worth stating so nobody tries to use
  Wave 2's machinery to build Wave 1.
- **Twenty slices is a lot of review capacity.** `plan-wave` treats review as
  real work and caps concurrent items per reviewer. At one reviewer this is a
  long queue. Task G was offered as the first cut and was kept (accepted
  2026-09-02), scheduled last within Wave 4; it remains the separable task if
  capacity turns out to be the binding constraint later.
- **The docs site is last on purpose**, which means the product is
  under-documented for the duration. Accepted deliberately: the alternative is
  documenting a workflow that is about to change.

## Decisions accepted before Wave 1

All three were referred to the accountable human and settled on 2026-09-02.
Wave 1 is unblocked.

1. **`ok_approve` becomes `ok_machine_review_complete`**, with
   `ok_approve_with_deferrals` becoming
   `ok_machine_review_complete_with_deferrals` in the same slice.
2. **D-prep-1 reads version 4 without writing it.** Slice D1 enables the
   writers, so the highest-risk slice stays cleanly revertible.
3. **Task G stays in scope**, scheduled last within Wave 4.

No decision remains outstanding for Wave 1. Waves 2 and 3 each still open with
an assumption their first slice must settle — the outcome-to-recommendation
mapping for B1, and GitHub's review-authorship distinction for E2 — both
recorded in the brief and named in place above.

## Completion evidence

To be filled in per slice as it lands. This plan is authority, not a record.
