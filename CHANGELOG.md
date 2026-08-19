# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/) and
Semantic Versioning.

## [Unreleased]

### Added
- `planner`, a fifth primary agent (ADR-0024): a human-started entry point
  for the Specify/Understand/Design/Plan phases, decoupled from
  `orchestrator`'s Build/Review/Ship scope -- wraps `specify-project`,
  `define-product`, `design-solution`, and `plan-delivery` in one session,
  and never invokes `builder`/`reviewer`/`orchestrator`. Gains an
  issue-only short circuit: given an accepted design or decision, draft a
  task and run `codev git issue-create` directly, skipping
  `plan-delivery`'s milestone/work-list machinery, and stop there --
  starting the task remains `orchestrator`'s job in a later session.
  `adapter.py` and `installer.py` register it the same way as every other
  role.
- `.github/pull_request_template.md` and `.github/ISSUE_TEMPLATE/task.md`:
  installed into every adopting repository the same way every other bundle
  file is (no new CLI surface). Adapted from an external design-doc-template
  review into CoDev's own vocabulary -- risk labels match
  `implementation-plan.template.md`'s existing `low`/`normal`/`high`/
  `critical` scale rather than inventing a new one, "Stop if" reuses the
  Focus card's existing term, and the `[unverified]` inline-assumption
  marker is adopted as a new lightweight convention. `codev git
  issue-create` already covers the CLI side (title/body/assignees, no
  labels yet -- flagged as a possible follow-up, not built here).

### Changed
- **Breaking:** "work item" is renamed to "task" throughout (ADR-0023): the
  `codev work ...` CLI group is now `codev task ...`, `.codev/work/` is now
  `.codev/task/`, and the `work_item_id` round-state field is now `task_id`.
  `ROUND_SCHEMA_VERSION` moves to 3; a schema-2 `round-state.json` is
  rejected with a clear error rather than migrated, the same precedent
  ADR-0003 set for the schema-1-to-2 bump -- an in-flight task must finish
  or restart under the previous CoDev version. `codev status --json`'s
  `work_items_in_progress`/`work_items_in_progress_by_owner` fields are now
  `tasks_in_progress`/`tasks_in_progress_by_owner`. The `docs/codev/work/`
  planning-artifact convention is now `docs/codev/task/`. All four platform
  adapters, `adapter.py`'s required-marker checks, and every skill/doc
  referencing the old terminology are updated together.

## [0.2.3] - 2026-08-14

### Fixed
- `codev git mark-ready` no longer silently drops `Closes #N` from the pull
  request body. `open_pr` appended it correctly; `mark_ready` -- which runs
  at the end of every outer-loop pass -- regenerated the body from
  `work.pr_description()` alone and never called `_closes_issue_number()`,
  so the auto-close link was lost from the *final* PR body every time, even
  when `link_ref` was a correct issue URL. Both now share one
  `_with_closes_line()` helper. `tests/test_git_ops.py::MarkReadyTests`
  gains a regression test.

### Added
- `docs/codev/onboarding/starting-prompts.md`: copy-paste starting prompts
  for the next work item and for outer-loop review, cross-linked from
  `onboarding-guide.md`. The outer-loop prompt explicitly asks for the
  numbered specialist menu and to wait for selection before dispatching --
  a prompt-level reinforcement of ADR-0021's permission gate, on every
  platform, not only OpenCode.
- `codev work relink --id <id> --github-issue N|--link <ref> [--by <name>]`
  (ADR-0020): corrects `link_ref` after `codev work start` already ran.
  `--github-issue` can only be resolved at `start()` time and `link_ref` was
  otherwise write-once for an item's life, with no way to recover from a
  human catching a missing issue link mid-session -- traced directly to a
  real session where the only available "fix" was noting the link in the
  implementation plan's prose, never in state, so `Closes #N` could never
  fire for that item. Modeled on `waive()`: appends to a new additive
  `link_ref_updates` list rather than silently overwriting history;
  `codev work log` renders each correction.
- `codev work start` refuses to proceed when the repository has a GitHub
  remote and neither `--github-issue`, `--link`, nor the new
  `--no-github-issue` acknowledgment flag was given (ADR-0020) -- turns a
  workflow decision that previously depended entirely on prompt convention
  into a CLI-level gate, the same "refuse until resolved" shape
  `codev diff`/`codev update` already use for install conflicts. New
  best-effort `git_ops.has_github_remote()`, modeled on `detect_identity()`,
  backs the check without introducing a hard GitHub dependency.

### Design
- ADR-0020 -- the mechanical issue-linkage gate and `relink` above.
- ADR-0021 -- OpenCode's `outer-loop-runner` specialist-dispatch permission
  gate. ADR-0018's own conclusion was that no CLI mechanism can prevent an
  agent from skipping the numbered specialist menu; a second real session,
  run on 0.2.2 with that fix's prompt text confirmed present, reproduced the
  identical skip verbatim. OpenCode's bundled agent file already exposes a
  real per-subagent permission gate and already uses it elsewhere in the
  same file (`bash: "*": ask`) -- it was simply configured to `allow` all
  five specialists. They now require `ask`. Codex/Antigravity/Junie have no
  equivalent lever today and remain prompt-only, a documented asymmetry
  rather than a silent one. `adapter.py` gains `_SPECIALIST_ALLOW_MARKERS`
  so a future edit cannot quietly revert this.
- ADR-0022 -- bundled workflow-instruction hardening: `orchestrator` (all
  four platforms) now checks and creates a missing GitHub issue itself
  instead of only passing one through when it already exists; every
  `codev git issue-create` call site now instructs `--body-file` over
  inline `--body` for text with shell metacharacters (unused since ADR-0014,
  confirmed the literal cause of two separate body-corruption incidents);
  `orchestrator` now actually populates `codev work start --description`
  from the approved implementation plan's Approach/Risks, a CLI argument
  that has existed, unreferenced by any prompt, since ADR-0014;
  `outer-loop-runner` step 1 now narrates that its fetch is read-only before
  running it. `adapter.py`'s `_REQUIRED_MARKERS["orchestrator"]` gains
  `"codev git issue-create"` and `"--no-github-issue"`.

## [0.2.2] - 2026-08-13

### Changed
- `outer-loop-runner` (all four platforms) and the canonical
  `ai-agent-guidelines.md` land ADR-0017/0018/0019 together in one combined
  step 1/2 rewrite: step 1 now attempts one bounded CI repair before gating,
  then runs `codev work check` before dispatching anything and branches on
  `ok_outer_loop_needs_reopen`; step 2/3 now records `--selection` alongside
  every reviewer round. `ai-agent-guidelines.md`'s "Outer-loop execution"
  previously under-specified the numbered specialist menu and waiver
  mechanism entirely relative to what all four platforms actually implement,
  and omitted step 6's "no PR yet" recovery branch -- brought in line with
  the platform files rather than left thinner than its own implementations.
  `adapter.py` requires `codev work reopen` and `--selection` in
  `outer-loop-runner`'s rendered text on every platform.

### Design
- ADR-0019 decides `outer-loop-runner` should own attempting to get red CI
  green, not only gate on it -- previously a deliberate scope decision
  (ADR-0003), not a bug, but a real gap against the self-healing precedent
  ADR-0002 and ADR-0015 already established elsewhere in this system. One
  bounded attempt (`github-actions-ci-results` diagnostic, one scoped
  `builder` dispatch, re-check), falling through to today's stop-and-report
  otherwise. Prompt implementation lands together with ADR-0017/0018's own
  `outer-loop-runner` step 1/2 changes in one combined edit.

### Added
- `codev work record --role reviewer` gains an optional `--selection
  <file.json>` flag recording which of the outer loop's five specialists
  actually ran a round (ADR-0018) -- a saved session showed the model
  skipping `outer-loop-runner`'s numbered specialist menu (ADR-0016)
  entirely. `codev` cannot gate dispatching a subagent, so this cannot force
  the pause itself; it makes the omission visible and durable in `codev work
  log` instead of only inferable after the fact. Deliberately optional, like
  `--coverage`: a comment-sourced round (ADR-0010) legitimately dispatches
  none of the five.

### Fixed
- `lightweight-reviewer` (all four platforms) now checks that an
  implementation plan's `Status:` line and Completion Evidence agree with
  the round's actual head and decision before returning `READY FOR OUTER
  LOOP`, and treats a mismatch as a normal blocking finding on the cheap
  inner round rather than something that slips through to be caught late as
  an expensive outer-phase round with mandatory human triage. Neither
  planning template previously tied its `Status:` field to anything that
  would trigger an update: `build-change`'s evidence-receipt step now
  updates it alongside Completion Evidence, and `plan-delivery` now states an
  explicit trigger for moving a delivery plan's own document state from
  `Draft` to `Accepted` once its open decisions are resolved.
- `record_reviewer` now rejects `READY_FOR_OUTER_LOOP` on a round whose phase
  is already `"outer"` (ADR-0017) instead of silently accepting it and
  producing a state `_round_slot` later refuses to build on. Traced to a real
  incident where this exact corrupted shape -- reached via a legitimate
  human-authorized `reopen` -- blocked a genuine five-specialist outer-loop
  pass (six blocking findings, including an SSRF hole) from ever being
  recorded; the findings survived only in a saved chat transcript.
  `check()` gains `ok_outer_loop_needs_reopen` as a distinct, defense-in-depth
  signal for any round-state already in this shape, and the write-once guard
  messages on `record_builder`/`record_reviewer` now name `codev work
  reopen` as the fix instead of leaving the caller to work it out.
- `codev git issue-create` and `codev work start --github-issue` are now
  actually referenced by the workflow that was always meant to call them.
  ADR-0004 built the full feature (issue creation, `--github-issue`
  resolution, `codev git open-pr`'s automatic `Closes #N`) and explicitly
  flagged wiring it into `plan-delivery` and `orchestrator` as a follow-up --
  "Not done as part of this ADR." It stayed undone: no agent prompt on any
  platform referenced `issue-create` at all. `plan-delivery`'s Handoff now
  pushes a ready item as an issue before implementation starts;
  `orchestrator` (all four platforms) and the canonical
  `.codev/for-ai/ai-agent-guidelines.md` now start work items with
  `--github-issue <N>` when one exists. `adapter.py` gains `--github-issue`
  as a required marker for `orchestrator`.
- `orchestrator` and `outer-loop-runner` (all four platforms) no longer
  hardcode `--body <body>` on `codev git open-pr`. ADR-0014 already made
  omitting `--body`/`--body-file` fall back to `work.pr_description()` at the
  CLI layer, but every prompted call site kept supplying a literal body
  placeholder, which made that fallback structurally unreachable and left
  agents hand-composing PR descriptions instead -- traced directly to a real
  session's "utter ugly" PR body. `adapter.py` gains a
  `_HANDWRITTEN_PR_BODY_MARKERS` forbidden-marker check so this cannot
  silently regress on any platform again.

## [0.2.1] - 2026-08-13

### Changed
- Relocate `docs/for-ai/ai-agent-guidelines.md` to `.codev/for-ai/ai-agent-guidelines.md`:
  it is read by agents, not browsed by humans, so it now lives under the same
  dot-directory as the rest of CoDev's own operational state
  (`.codev/lock.json`, `.codev/work/`, `.codev/fixtures/`) instead of the
  human-facing `docs/` tree. Every reference across all four platforms'
  `orchestrator`/`builder`/`outer-loop-runner` files, `AGENTS.md`, and
  `scripts/validate-development-workflow.py`'s `EXPECTED_GUIDES` updated to
  match.
- Replace `docs/for-human/development-guide.md` with
  `docs/codev/onboarding/onboarding-guide.md` and a new
  `docs/codev/onboarding/examples.md`, joining `docs/codev/`'s existing
  planning-artifact convention (ADR-0004). Shorter, and illustrated with
  worked bio- and cheminformatics scenarios (a BED-to-VCF coordinate bug, a
  SMILES canonicalization gap, a variant-annotation contract for parallel
  development, a docking-score cache race caught by the outer loop, a
  toxicity-model staged rollout) instead of abstract description alone.
- **Breaking:** `round-state.json` moves to schema version 2 (ADR-0002,
  ADR-0003). `codev work` round-state now supports a self-healing inner loop
  ending in a `READY_FOR_OUTER_LOOP` reviewer decision and a phase-tagged
  outer loop with a human-triage step, per work item:
  - New `READY_FOR_OUTER_LOOP` reviewer decision, exempt from the full
    coverage-completeness gate (`_incomplete_coverage`), and a new
    `ok_ready_for_pr` `codev work check` outcome.
  - Findings gain an optional `expansion_reason` (`regression` or
    `newly_discovered_critical`); a blocking finding introduced after a
    phase's first round with no `expansion_reason` now stops with
    `stop_scope_expansion` rather than silently expanding the round's scope.
  - Round entries are tagged `"phase": "inner" | "outer"`. `max_rounds`
    becomes phase-scoped (`{"inner": 2, "outer": 2}` by default); `start`
    still accepts a plain int, applied to both phases. The round cap and
    repeated-finding checks are now phase-local.
  - `REQUIRED_COVERAGE_DIMENSIONS`'s combined
    `security_privacy_data_concurrency_compatibility` key splits into
    `security_privacy_data_compatibility` and a new standalone
    `concurrency` key.
  - New `codev work triage` records the human's `address`/`defer`
    disposition for each blocking finding in an outer-loop round; deferring
    a blocking finding requires a non-empty `override_reason`. A new
    `ok_waiting_on_triage` check outcome gates opening the outer phase's
    correction round until triage is recorded.
  - No migration path: a v1 `round-state.json` is rejected by the existing
    version guard. Pre-1.0, consistent with this project's existing
    breaking-change policy.

### Added
- Add `codev work waive` and human-selectable specialist dispatch in
  `outer-loop-runner` (ADR-0016, all four platforms): `outer-loop-runner`
  now presents the five specialists as a numbered list and dispatches only
  the ones selected, pushing back with its own reasoning (never blocking)
  when it judges a skipped one relevant to the actual diff. Immediately
  after selection, any dimension left uncovered can be waived on the spot
  with a required reason (`codev work waive --id --dimension --reason
  [--by]`) instead of only ever being deferred to a later round.
  `_effective_coverage` folds waivers into its existing round-ordered,
  most-recent-wins coverage merge (ADR-0011) -- a later real specialist
  verdict always overrides an earlier waiver, and vice versa. A waiver is
  never recorded or rendered as `passed`; `codev work log` and
  `pr_description()` (ADR-0014) always show it distinctly.
- Add `code-audit-gate`, a new always-autonomous subagent, to all four
  platform adapters (ADR-0015): `code-audit`'s automatic pre-PR invocation
  mode is retired in favor of this dedicated agent, since that mode never
  used the human-approval gate that keeps `code-audit` itself `mode:
  primary` — audit-only, no approval to grant. `orchestrator` now dispatches
  it between the builder's round and `lightweight-reviewer`, self-fixing
  style/documentation issues directly and resolving before the reviewer
  round is ever recorded, so a pre-PR cleanup pass can no longer exhaust the
  outer phase's round cap before the five specialists run even once (a real
  failure mode in the old routing, traced and fixed). `orchestrator`'s final
  step now names `outer-loop-runner` explicitly as the human-triggered next
  action instead of leaving the hand-off implicit; OpenCode's
  `permission.task` allow-list gains `code-audit-gate` (the agent it can
  actually task-dispatch, unlike the old `mode: primary` `code-audit`,
  which the allow-list never actually covered).
- Add `--description` to `codev work start` and a new
  `work.pr_description()` formatter (ADR-0014): `codev git mark-ready` no
  longer overwrites the pull request body with `codev work log`'s
  mechanical, round-by-round evidence dump -- it now regenerates a
  self-contained prose description (why/what, a plain-language validation
  summary per review dimension, a link to the full evidence trail) that a
  reviewer can read without opening any of the repository's own docs.
  `codev git open-pr` falls back to the same formatter when neither
  `--body` nor `--body-file` is given, instead of requiring one.
  `codev work log`'s own output is completely unchanged -- the evidence
  trail stays linked from the PR body, never embedded in it.
- Add a `git.pr_base` config key (ADR-0013): `codev git open-pr` now
  resolves it (via the existing layered `codev config` mechanism) before
  falling back to the repository's actual default branch, so a repository
  that doesn't PR directly into its default branch no longer needs every
  caller to pass `--base` explicitly to avoid opening against the wrong
  branch. An explicit `--base` still wins. Also fixes a latent bug this key
  was the first to trigger: `codev config set` wrote dotted keys (e.g.
  `git.pr_base`) unquoted, which TOML parses as a nested table rather than
  one literal key, so they never round-tripped back through `codev config
  get`/`resolve` at all.
- Add `--paths`/`--staged`/`--round`/`--evidence` to `codev git commit`
  (ADR-0012): `--paths`/`--staged` scope the commit instead of the always-on
  `git add -A`, so concurrent unrelated worktree changes (most often
  CoDev's own workflow files) no longer have to ride into a product commit
  with no way to avoid it -- the default now refuses a commit when the
  dirty worktree mixes `.codev/lock.json`-managed paths with anything else,
  pointing at `--paths`/`--staged` instead of silently combining them.
  `--round`/`--evidence` (given together) atomically records the builder's
  round via `codev work record --role builder` against the commit's actual
  resulting head in the same call, removing the manual repair step
  ADR-0007's session needed when that second call used a stale head.
- Add `codev git branch|commit|push|open-pr|mark-ready` (ADR-0002,
  ADR-0003): a guarded mutation surface so a work item's inner/outer loop
  can create its own branch, commit, push, and land a pull request without
  agents ever holding raw `git commit`/`git push`/`gh pr create` permission.
  Mechanically enforces, not by agent-prompt convention: operates only on
  the one branch it created for a work item, refuses any target resolving
  to the repository's default branch, never accepts or constructs a
  force-push flag, and independently re-verifies `codev work check` returns
  `ok_ready_for_pr`/`ok_approve` before `open-pr`/`mark-ready` proceed,
  rather than trusting the caller already checked. `open-pr` always creates
  a draft PR; `mark-ready` regenerates the PR body from the work item's
  round-state (via `codev work log`'s formatting) before converting it out
  of draft.
- Add `codev work escalate` / `codev work escalations [--since DATE]`
  (ADR-0003): a local, gitignored, append-only escalation log
  (`.codev/work/escalations.jsonl`) recording every human escalation --
  round-cap hit, drift, repeated finding, scope expansion, missing
  evidence, a pre-build critical interrupt, or a human overriding a
  blocking finding during triage -- with cause, phase, and round. Written
  explicitly by the caller; `codev work check` stays read-only and never
  logs as a side effect. Not yet done: `codev init`/`update` don't manage
  this entry in a target repository's `.gitignore` the way they already do
  for `AGENTS.md` -- tracked as follow-up work.
- Add a `lightweight-reviewer` role to all four platform adapters (ADR-0002):
  a narrow, fast inner-loop check -- correctness and intent-match against
  the work item, plus independent re-verification of the builder's reported
  validation -- distinct from the full-dimension `reviewer`, which remains
  available for other uses (e.g. `pr-review`). `orchestrator` no longer
  requires human plan-approval before every delegated build by default; it
  proceeds unless the existing "Stop conditions" or "Risk overrides size"
  categories apply, checked cheaply by path/diff-shape before any judgment
  call. On a clean pass it now creates the work item's branch, commits,
  pushes, and opens a draft pull request through the new `codev git`
  surface automatically -- merge remains the only human-gated step. Updated
  `docs/for-ai/ai-agent-guidelines.md`'s "Three-agent Build execution" and
  all four `orchestrator`/`builder`/`reviewer` bundle files to match, and
  extended `codev adapter verify` to require `lightweight-reviewer` and a
  `codev git open-pr` reference on every orchestrator, and to flag a raw
  `"git push*"`/`"git commit*": allow` permission as a retired pattern now
  that the guarded surface exists.
- Add a human-triggered `outer-loop-runner` role and five specialist
  reviewer roles (ADR-0003) to all four platform adapters:
  `correctness-tests-specialist`, `security-data-specialist`,
  `concurrency-specialist`, `architecture-maintainability-specialist`, and
  `rollout-specialist`, each scoped to a disjoint set of `codev work`'s
  coverage dimensions and none of them recording state directly. The
  `outer-loop-runner` fetches a pull request and gates on CI status before
  dispatching any specialist, merges their findings and coverage into one
  round, presents blocking findings to the human for an `address`/`defer`
  triage via `codev work triage`, drives the one permitted correction round
  scoped to only the selected findings, and lands the change with
  `codev git mark-ready` on approval. Updated
  `docs/for-ai/ai-agent-guidelines.md` with a matching "Outer-loop
  execution" section and `review-change`'s dimension list to give
  concurrency its own numbered item. Extended `codev adapter verify` to
  verify all ten roles per platform.
- `codev init`/`update`/`remove` now manage a small marked block in the
  target repository's `.gitignore` (create it if absent, merge into
  existing content otherwise) ignoring `.codev/work/escalations.jsonl`,
  the same safely-merged pattern already used for `AGENTS.md`. Backward
  compatible with installs that predate this: a missing block and no
  recorded hash integrate cleanly on the next `update` rather than
  conflicting. `codev status`/`check_project` flags a tampered block only
  for installs that already have one recorded.
- Add `--link`, `--summary`, `--owner`, and `--github-issue` to `codev work
  start`, and `--by` to `codev work triage` (ADR-0004): purely additive,
  optional traceability and identity fields on `round-state.json` -- no
  `ROUND_SCHEMA_VERSION` bump. `--owner`/`--by` default to a new
  `git_ops.detect_identity()` (the authenticated `gh` login, falling back to
  local git config, never fabricated) rather than requiring the human to
  type identity every time; `--github-issue N` populates `--link`/`--summary`
  from a read-only `gh issue view` unless given explicitly. `codev work
  check` now prints a non-blocking note when the same identity both owns a
  work item and triaged it, mirroring `plan-delivery`'s existing "owners do
  not approve their own changes" guidance with a data hook instead of only
  documentation.
- `define-product`, `design-solution`, `plan-delivery`, and `build-change`
  now default their planning-artifact locations under a common
  `docs/codev/` prefix (ADR-0004) -- `docs/codev/features/`,
  `docs/codev/product/`, `docs/codev/design/`, `docs/codev/delivery/`, and a
  new `docs/codev/work/<work-item-id>/implementation-plan.md`, keyed by the
  same id `codev work start` uses, closing the traceability gap for the one
  planning artifact that is genuinely 1:1 with a single work item. Each
  skill's existing instruction to defer to an established repository
  convention instead of forcing its own structure is unchanged, so an
  already-adopted repository's existing paths are unaffected.
- Add `codev git issue-create` (ADR-0004): the one operation in the guarded
  `codev git` surface with no work-item precondition, since pushing a
  delivery-plan work item to GitHub happens before `codev work start` exists
  for it. Takes explicit `--title`/`--body` (never parses a delivery plan's
  Markdown); an optional, repeatable `--path` prints a best-effort
  CODEOWNERS-suggested assignee without ever forwarding it as `--assignee`
  automatically. `codev git open-pr` separately appends `Closes #N` to the
  generated PR body when a work item's `--link` is a GitHub issue URL for
  the same repository, closing the loop for free on merge.
- Add `codev codeowners init` (ADR-0004): a one-shot local scaffold of a
  starter `.github/CODEOWNERS`, refusing rather than overwriting if one
  already exists at any of the three locations GitHub reads. Unlike
  `AGENTS.md` and the `.gitignore` block, it is not a managed integration --
  no `lock.json` entry, no hash tracked -- and is intended to be run
  directly by a human during repository setup, the same as `codev init`
  itself.
- `codev status --verbose` now reports non-blocking work-in-progress counts
  per owner and changed-file overlaps between concurrently open work items
  (ADR-0004), surfacing `plan-delivery`'s existing WIP guidance and the
  residual collision risk that small, fast-merging changes shrink but do not
  eliminate -- informational only, never a gate.
- `code-audit` gains a second invocation mode (ADR-0005): `orchestrator` now
  invokes it automatically, audit-and-plan phase only, immediately before
  opening a pull request, in addition to its existing standalone
  human-approval-gated form. A clean pass proceeds to `codev git
  push`/`open-pr` as before; a finding is recorded with `codev work record
  --role reviewer --decision CHANGES_REQUIRED` and, since this opens the
  outer phase's round 1 (not another inner round -- see the round-cap/triage
  correction under Fixed below), routed to `builder` only after a `codev
  work triage` pass, rather than `code-audit` self-applying a fix -- there
  is no human present in that turn to grant Phase 2's approval.
  `audit-google-python-style`/`audit-google-typescript-style` are unchanged;
  only who invokes `code-audit` and what happens with its findings changed,
  not the skills it dispatches to.
- Add `--entry {takeover,direct-review}` to `codev work start` (ADR-0006):
  purely additive, optional -- omitted means today's implicit cold start,
  unchanged, no `ROUND_SCHEMA_VERSION` bump. `takeover` marks a work item
  whose branch already carries unfinished human commits beyond `--base`;
  round 1 still opens in the inner phase, and `orchestrator`'s three-agent
  protocol (all four platforms) now tells `builder` to read that existing
  diff and continue it rather than replace it. `direct-review` marks a work
  item as already finished by a human; round 1 opens directly in the outer
  phase instead of inner, and `codev work check` now recognizes a fresh
  `direct-review` item (no builder or reviewer recorded yet) as immediately
  `ok_ready_for_pr` -- previously this exact state (`head` already beyond
  `base_snapshot` with nothing recorded) would have been reported as
  `stop_drift`. `describe`/`log_text` surface the new `entry` field
  alongside `owner`/`summary`/`link_ref`. A guided `codev work next`
  command was considered and dropped in the same ADR -- GitHub's own Issues
  list, populated via `codev git issue-create` (ADR-0004), already serves
  that need.
- Add `codev work reopen --id <id> --head <head> --reason <text>
  [--max-rounds N] [--by <identity>]` (ADR-0007): a human-authorized
  recovery path for a work item `codev work check` reports as stuck --
  closed, round-capped, or drifted -- none of which previously had any
  supported way back. Unlike `start`, works regardless of `status`. Requires
  a non-empty `reason` (no default), re-baselines `base_snapshot` to `head`,
  and appends exactly one new, empty round -- it never edits a previously
  recorded round's builder/reviewer entry. `max_rounds` may only be raised,
  never lowered below rounds already recorded for a phase. Every call is
  appended to a new, additive `reopens` list on `round-state.json` (no
  `ROUND_SCHEMA_VERSION` bump) and printed by `codev work log`. `start`'s
  duplicate-id error and `_round_slot`'s round-cap error now name it
  directly.
- `outer-loop-runner` (all four platforms) gains a comment-sourced entry
  mode (ADR-0010): human-triggered, fetches a PR's existing `comments`/
  `reviews` (`publish_review.py --fetch`) instead of dispatching the five
  specialists fresh, drafts a finding directly from each actionable
  comment -- trusting its content, not independently re-verifying it,
  unless the comment itself names a specialist -- records and auto-triages
  every drafted finding as `address` (the human's own request to fix these
  comments is the authorization), then corrects and verifies with the
  inner loop's fast `lightweight-reviewer` standard rather than a full
  specialist pass. No `work.py`/`git_ops.py` change: `_round_slot`,
  `record_triage`, and the coverage gate already operate generically on
  whatever produced a round's findings. `ok_approve` still requires
  complete eight-dimension coverage, now explicitly carried forward from
  whichever round most recently established each dimension (an unstated
  assumption the existing narrow-correction path already relied on;
  written down for both paths in the same change). `critique-review`'s
  accepted inputs drop the developer-supplied review comment case, now
  strictly better served by this entry for any work item with an open PR.
- Coverage carry-forward (ADR-0008, ADR-0010) is now mechanized instead of
  agent-executed prose (ADR-0011): `codev work check` computes an
  *effective* coverage manifest from a work item's full round history —
  the most recent round to establish each dimension wins — instead of
  reading only the latest round's own coverage dict. A round now only
  needs to record the dimension(s) it actually re-verified; `check` fills
  in the rest and names exactly what's still missing when coverage is
  genuinely incomplete. `record_reviewer` still stores exactly what it is
  given, so the per-round audit trail is unchanged; only the completeness
  check reads across history. Fixes a real failure mode: a narrow
  post-approval correction (a PR-comment fix, for example) that only
  re-verified one or two dimensions used to report `stop_incomplete_
  coverage` for dimensions a much earlier round had already established,
  because carrying that forward correctly was previously the recording
  agent's responsibility to get right by hand every time.

### Fixed
- `builder` (all four platforms) was instructed to call `codev work record
  --role builder --head <head-sha>` before returning, while denied commit
  permission and only `orchestrator` commits, afterward (`orchestrator.md`
  step 6). The only head that existed at record time was therefore the
  pre-existing base commit, not the head the builder's own uncommitted
  changes would produce -- so `codev work check` reported `stop_drift` on
  the very next check after the orchestrator's commit, on the ordinary path,
  not as an edge case (ADR-0007). `builder.md` no longer records its own
  evidence or reports a head snapshot; `orchestrator.md` (all four
  platforms) and `.codev/for-ai/ai-agent-guidelines.md` now commit first and
  record the builder's round immediately after, against the commit's actual
  resulting head.
- `code-audit.md.template` and `orchestrator.md` (all four platforms)
  described a post-`ok_ready_for_pr` `code-audit` finding as routing to
  `builder` "under the inner loop's existing round cap." Mechanically false:
  `_round_slot` always transitions to the outer phase after a
  `READY_FOR_OUTER_LOOP` decision, and an outer-phase `CHANGES_REQUIRED`
  round requires `codev work triage` before the next round can open --
  neither file mentioned it, so following the documented path hit an
  undocumented `WorkError` (ADR-0007). Corrected in `orchestrator.md` and
  `ai-agent-guidelines.md`, which are now the single source of truth for
  this transition; `code-audit.md.template` no longer restates it.
- `codev update` orphaned a bundle file whenever upstream relocated it (for
  example `docs/for-ai/ai-agent-guidelines.md` moving to `.codev/for-ai/`):
  `plan_update` could not distinguish a rename from a genuine removal, since
  both simply have no entry in the new bundle under the old path, so it
  always "retired" (left in place, unmanaged) the stale copy instead of
  removing it -- meaning a repository could end up with two diverging
  copies, with not-yet-updated role files still pointing at the abandoned
  one. `plan_update` now matches an old-only path against the new bundle by
  content hash: an unmodified local copy that moved to exactly one new path
  is now deleted (`remove`, detail names the new path) instead of retained;
  a copy with local edits is still retired, with a message identifying
  where upstream moved it, so nothing is silently discarded.
- `.codev/for-ai/ai-agent-guidelines.md` and every file under
  `docs/codev/onboarding/` were silently missing from every real (built,
  non-editable) install -- `pipx`/`uv tool install`, not `uv run` against a
  source checkout -- even though `codev update`'s logic (the fix above) was
  otherwise correct. Root cause: `[tool.setuptools.package-data]` in
  `pyproject.toml` is a hand-maintained glob allowlist that never got
  updated for the `docs/for-ai` -> `.codev/for-ai` relocation or the new
  `docs/codev/onboarding/` layout, so `_walk_bundle()` found these files
  from an editable checkout (which reads the source tree directly) but the
  built wheel never packaged them at all. `codev update`/`init` against a
  real install therefore reported "No changes." for these files instead of
  adding them, with no error. Fixed the glob list, and added
  `scripts/verify_release.verify_bundle_packaging`: a new release-check step
  that inspects the actual built wheel's contents against
  `src/codev_workflow/bundle/` and fails release verification if any bundle
  file has no matching package-data glob, so this class of drift can't ship
  silently again.
- `codev git open-pr` required `codev work check` to return exactly
  `ok_ready_for_pr`, a result `check()` only ever produces once, at the
  inner-to-outer transition. An item recovered straight into the outer
  phase with `codev work reopen` (ADR-0007) skips that transition entirely,
  so once outer-loop review reached `ok_approve` there was no supported way
  left to open the pull request at all: `open-pr` refused (wrong
  checkpoint) and `mark-ready` also couldn't help, since `gh pr edit`/`gh
  pr ready` need a pull request that was never created. `open_pr` now
  checks GitHub directly for an existing pull request on the branch
  (`gh pr view`) instead of inferring readiness from one specific
  historical `check()` reason: it refuses only when a pull request already
  exists (duplicate) or `check()` reports a hard stop, and otherwise
  accepts `ok_ready_for_pr` or any outer-phase state with no pull request
  yet. `orchestrator.md`'s automatic PR-open behavior is unchanged -- it
  still only triggers at `ok_ready_for_pr` in the normal flow; this only
  removes a false refusal in the recovery path. `outer-loop-runner.md` and
  `ai-agent-guidelines.md` (all platforms) now document running `open-pr`
  before `mark-ready` when a reopened item reaches `ok_approve` with no
  pull request yet.
- `OPENCODE_AGENT_CONFIGS` in `installer.py` -- the allowlist that gets
  merged into a target repository's `.opencode/opencode.json` -- only ever
  registered `orchestrator`, `code-audit`, `builder`, and `reviewer`. It was
  never updated as `lightweight-reviewer`, `outer-loop-runner`, and the five
  outer-loop specialists were added to the bundle (ADR-0002, ADR-0003): the
  agent `.md` files were installed to `.opencode/agents/`, but nothing told
  OpenCode's config they existed, so OpenCode could not offer
  `outer-loop-runner` as a selectable primary agent even though its own
  file correctly declares `mode: primary`. Same root cause, same fix shape,
  as the `[tool.setuptools.package-data]` drift above: a hand-maintained
  allowlist silently fell behind a growing bundle. Added the seven missing
  entries and a regression test (`test_every_bundled_opencode_agent_is_registered`)
  that fails whenever a bundled `.opencode/agents/*.md` file has no matching
  `OPENCODE_AGENT_CONFIGS` entry.
- A triaged blocking finding could not resolve `stop_scope_expansion` or
  `stop_repeated_finding` (ADR-0008): `check()` evaluated those guards
  unconditionally, before ever consulting the round's triage, so deferring
  a newly surfaced but non-critical finding -- Google's own documented
  practice for exactly this situation -- had no working path; even a
  triage-only fix would still have dead-ended on the outer phase's round
  cap, which is exhausted by definition whenever scope expansion fires on
  the one permitted correction round. `_find_scope_expansion` and
  `_find_repeated_blocking_finding` now exempt any finding already
  triaged (address or defer) on the same round -- the guard still fires
  the first time, unconditionally, but a human's one required look
  resolves it, the same as it already does for every other outer-loop
  finding. New `check()` outcome `ok_approve_with_deferrals`: when every
  blocking finding on a `CHANGES_REQUIRED` round is triaged as `defer`,
  there is nothing left for a builder to do, so `check()` reports this
  directly (after the same coverage-completeness gate `READY_FOR_HUMAN_APPROVAL`
  already applies) instead of falling through to the round cap. The
  round's own recorded decision stays `CHANGES_REQUIRED` -- an honest
  record of what was actually found -- `codev git mark-ready` now accepts
  this reason alongside `ok_approve`. Wires up
  `human_override_blocking_finding`, a `VALID_ESCALATION_TRIGGERS` entry
  unused since ADR-0003: `outer-loop-runner.md` and
  `ai-agent-guidelines.md` (all platforms) now name the exact moment to
  record it. `codev work reopen` (ADR-0007) needed no change -- it remains
  the tool for a round cap or drift that genuinely requires more building,
  which a deferred finding does not.

### Removed
- Remove the `clean-code-review` skill (ADR-0005). Its catalog-driven
  content (Clean Code principles, Gang-of-Four missing-pattern signals,
  design smells) was a different kind of thing from
  `architecture-maintainability-specialist`'s holistic judgment of the same
  named territory (architecture, scope, and maintainability) -- rather than
  keep it as a separate, always-manual skill, its language-agnostic material
  moves directly into that specialist's prompt across all four platforms,
  replacing previously vague "clarity, structure" language with citable,
  named criteria. Its Python-specific hazard IDs are dropped outright, not
  relocated -- `audit-google-python-style`'s existing supplemental checker
  already covers equivalent ground. `review-change`'s description gains one
  clarifying sentence: now that the outer loop covers a CoDev-built work
  item with an open PR, it is explicitly the zero-ceremony path for a diff
  with neither.
- Stop shipping `scripts/evaluate-development-workflow.py`,
  `scripts/validate-development-workflow.py`, and
  `evals/development-workflow/scenarios.json` into target repositories
  (ADR-0009). Both scripts and the catalog they operate on are this
  repository's own workflow-validation tooling -- `validate-development-
  workflow.py`'s expected skills/guides are hardcoded to this project's own
  bundle shape, and the catalog's scenarios test routing among this
  project's own bundled skills -- referenced nowhere a target repository's
  agent is instructed to run them except one dead-end mention in
  `ai-agent-guidelines.md` (removed; the equivalent guidance for this
  repository's own contributors moved to `CONTRIBUTING.md`). They move from
  `src/codev_workflow/bundle/` to this repository's top-level `scripts/`
  and `evals/` directories, which already held stale, independently
  drifted duplicates of them (missing docstrings, a retired skill
  reference, pre-relocation doc paths) -- refreshed to the bundle copies'
  content in the same move, so there is now exactly one copy. A target
  repository that already has these files (including one that deleted them
  locally, the discovery that prompted this) sees `codev update` report
  `retire`, not `conflict`, the next time it runs -- no manual restore
  needed first. `[tool.setuptools.package-data]`'s now-pointless entries
  for them are removed; `scripts/verify_release.py` invokes both from
  their new location. New regression test
  (`test_walk_bundle_excludes_internal_dev_tooling`) asserting neither
  script nor the catalog ever reappears in `_walk_bundle()`'s output.

## [0.2.0] - 2026-08-11

### Added
- Add layered configuration (`codev config get|set|list`, flags > env >
  project > global > default) via `.codev/config.toml`.
- Add a `codev work start|record|check|close|status|log` lifecycle subsystem
  that tracks builder/reviewer correction rounds as state instead of prose,
  enforcing the round cap, repeated-blocking-finding detection, and coverage
  completeness by exit code. See `docs/adr/0001-work-lifecycle-invariant.md`.
- Add `codev status`, `codev adapter list|add|verify`, and `codev self
  version|update`. `adapter verify` checks that an installed platform adapter
  still references the `codev work` lifecycle wiring, hasn't regressed to the
  retired P0-P3 finding scale, and doesn't grant unrestricted shell execution;
  the same check runs in CI against the shipped bundle for all four platforms.
- Add `codev eval snapshot run <skill>`: discovers every fixture tagged with
  a skill (`fixture.json` now requires `skill` and `category`), and for each
  category runs the fixture with the skill staged into the worktree and
  without it, repeated (`--repetitions`, default 3), reporting a pass
  percentage per condition and the delta between them - empirical evidence
  that a skill measurably outperforms not having it, not just a recall
  number in isolation. `codev eval run` gained `--without-skill` for
  single-fixture use. Replaces the fixture-only `scripts/run_seeded_defect_suite.py`.
  Backed by the seven-fixture seeded-defect corpus
  (`.codev/fixtures/seeded-defect-*`, one per review dimension, `skill:
  review-change`), each seeding a small reviewable change with one
  deliberately planted, known defect verified deterministically rather than
  trusted from the coverage checklist alone. The scheduled `live-eval` CI job
  runs a snapshot against a live OpenCode actor and gates `prepare-release`;
  its OpenCode installation/authentication step is a placeholder pending this
  project's actual CI credentials.

### Changed
- Default programming-language selection to `none`, omit language-specific audit
  skills unless requested, and render the OpenCode code-audit agent from a
  language-aware template.
- Add the language-aware code-audit agent to the Junie, Codex, and Antigravity
  adapters.
- Replace the reviewer's P0–P3 severity scale with a ranked, binary
  `blocking` finding model and a mandatory per-dimension coverage record, in
  `review-change` and all four platform reviewer agents.
- Narrow the "no CoDev process runs during a build" invariant so `codev work`
  commands may run during a build session (ADR-0001).
- Deprecate `codev check`, `codev doctor`, `codev fixture create`, and bare
  `codev eval <name>` in favor of `codev status`, `codev status --verbose`,
  `codev eval fixture create`, and `codev eval run <name>`; the old forms
  still work and print a warning.

## [0.1.7] - 09.08.2026

### Fixed
- Prevent release preparation from rebuilding distributions by validating tag and
  version metadata before downloading the exact tested artifacts.

## [0.1.6] - 09.08.2026

### Fixed

- Align workflow validation expectations with the current bundled documentation.

## [0.1.5] - 09.08.2026

### Changed

- Rename the platform-selection flag to `--agent-platform` to distinguish agent
  platforms from operating-system platforms.
- Add the `--programming-language` flag with lock-file persistence to install
  only the selected Python, TypeScript, or all code-style audit skills.
- Clarify `pr-review` summaries and publication/retry guidance to prevent
  duplicate reviews and make authorized submissions explicit.
- Complete Codex adapter distribution and platform filtering so `.codex/agents/`
  TOML agents install, update, validate, and remove safely.

## [0.1.4] - 2026-08-06

### Added

- Add the GitHub-only `pr-review` skill with exact-head validation, anchored
  inline comments, `gh api` authentication with token fallback, and PR context
  fetching for metadata, diffs, files, commits, reviews, comments, and checks.
- Add Google Antigravity support with managed `builder`, `orchestrator`, and
  `reviewer` subagents under the official `.agents/agents/` workspace location,
  selectable through `--platform antigravity` or `--platform all`.
- Add JetBrains Junie support with managed `builder`, `orchestrator`, and
  `reviewer` subagents under `.junie/agents/`, selectable through
  `--platform junie` or `--platform all`.
- Allow `update --platform junie` to add Junie to an existing CoDev
  installation with the same conflict-aware preflight as initial installs.
- Add the Junie project slash command `/pr-review repo=OWNER/REPO pr=123`, plus
  the secure GitHub-token helper for the PR-review workflow.
- Add the read-only `critique-review` specialist skill, which turns concrete
  review or presubmit findings into precise suggested diffs and requires an
  explicit handoff to `build-change` or the developer before application.

### Changed

- Move verification, linting, packaging, and wheel smoke tests into the default
  CI workflow for pull requests, `main`, and release tags.
- Gate the PyPI release phase on successful checks from the exact tag run and
  publish the distributions produced by that run.

## [0.1.3] - 2026-08-05

### Fixed

- Correct import ordering in the versioning script to satisfy Ruff.
- Format the version-script changelog fixture so the test suite remains lint-clean.

## [0.1.2] - 2026-08-05

### Changed

- Publish the CLI distribution as `open-codev-workflow` through an attested,
  trusted-publishing release workflow.
- Add the catalog-driven `clean-code-review` specialist skill for Clean Code,
  GoF, and Python-specific review findings.

## [0.1.1] - 2026-08-02

### Added

- Initial CoDev brand and standalone Python package.
- Safe `init`, `check`, `doctor`, `diff`, and `update` commands.
- Seven human-AI delivery skills and the three-agent OpenCode adapter.
- Human and AI workflow references, handbooks, cookbook, and prompt library.
- Deterministic workflow validators and behavioral scenario catalog.
- Cross-platform tests and GitHub Actions validation.
