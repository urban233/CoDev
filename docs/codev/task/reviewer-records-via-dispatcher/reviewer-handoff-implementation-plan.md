# reviewer-handoff Implementation Plan

**Status:** Accepted
**Owner:** urban233
**Reviewer:** lightweight-reviewer (inner loop)
**Risk:** low
**Containment:** N/A -- role-frontmatter and instruction-prose only, no executable code changed
**Slices:** One PR
**Slice:** reviewer-handoff
**Base commit:** 19a2829
**Issue/work item:** Not linked
**Brief/design/API:** Not needed

## Focus card

- **Change:** Stop `reviewer` and `lightweight-reviewer` from calling `codev
  task record` on themselves; both now write `findings.json`/`coverage.json`
  to disk and state their decision, and the dispatching session records the
  round -- the same shape `builder`'s evidence receipt and all five
  outer-loop specialists already use. Raise every review-shaped subagent's
  `maxTurns` to 40 (`reviewer` 25, the four opus specialists 20,
  `rollout-specialist` 15, `code-audit-gate` 30).
- **Success:** No role file instructs a reviewer to call `codev task record`
  itself; `ai-agent-guidelines.md` explicitly assigns that duty to the
  dispatcher; every `.claude/agents/*.md` change is mirrored byte-for-byte
  in `src/codev_workflow/bundle/.claude/agents/*.md`.
- **Non-goals:** No change to any review dimension, finding schema, or
  decision vocabulary; no change to `task.py`'s `record_reviewer` itself.
- **Allowed scope:** `.claude/agents/*.md`, `.codev/for-ai/ai-agent-guidelines.md`,
  and their `src/codev_workflow/bundle/` mirrors.
- **Validation:** `just test` (full Bazel suite) and `just validate-catalog`.
- **Stop if:** A role file's prose change accidentally reintroduces a
  self-record instruction, or a bundle copy diverges from its installed
  counterpart.
- **Work style:** Pair (already the slice's recorded style).

## Repository evidence

- `.claude/agents/reviewer.md`, `.claude/agents/lightweight-reviewer.md`
  (pre-fix): both told the reviewer to run `codev task record` itself
  before returning -- the least-recoverable action, last, under a turn cap.
  Four consecutive dispatches died there with their analysis finished and
  unrecorded.
- `.claude/agents/builder.md` and the five outer-loop specialists already
  return findings/evidence for the dispatching session to record -- this
  change brings the two reviewer roles in line with that established shape
  rather than inventing a new one.
- Review-shaped caps (`reviewer` 25, specialists 20, `rollout-specialist`
  15, `code-audit-gate` 30) were lower than build-shaped agents' 30-40,
  backwards given a reviewer re-runs everything the builder ran and reads
  the whole diff on top.

## Proposed change

1. Rewrite the recording instruction in `.claude/agents/reviewer.md` and
   `.claude/agents/lightweight-reviewer.md`: write `findings.json`/
   `coverage.json` to the dispatch-named paths, state the decision in the
   reply, and explicitly do not call `codev task record`.
2. Raise `maxTurns` in `.claude/agents/reviewer.md`,
   `architecture-maintainability-specialist.md`, `concurrency-specialist.md`,
   `correctness-tests-specialist.md`, `security-data-specialist.md`,
   `rollout-specialist.md`, and `code-audit-gate.md` to 40.
3. Update `.codev/for-ai/ai-agent-guidelines.md`'s step 4 to state the
   dispatcher's new recording duty, pre-staging the diff to a file and
   batching validation into one command.
4. Mirror every change into `src/codev_workflow/bundle/.claude/...` and
   `src/codev_workflow/bundle/.codev/...` so the installed copy and the
   bundle stay identical.

## Validation

- `just test` -> 31/31 Bazel targets pass.
- `just validate-catalog` -> passes (12 skills, 2 guides, 8 behavioral
  scenarios).
- Byte-diff of every changed `.claude/` file against its
  `src/codev_workflow/bundle/` counterpart -> identical.

## Risks and rollout

- Costs 188 tokens of always-on instruction (guidelines 6411 -> 6599;
  always-on payload ~9698 -> ~9886 at the time this landed). Called out
  because the separately accepted Claude Code adapter verification-first
  plan holds a ratcheted 7,500-token budget; this change landed outside
  that plan's own slices, so its ledger will need to absorb this addition
  when that plan's own instruction-budget slice runs.
- `code-audit-gate` is build-shaped, not review-shaped; raising its cap to
  40 is a minor scope stretch, included because it hit its own 30-turn cap
  in the same session that prompted this change.
- Claude Code caches agent definitions at session start, so neither the
  handoff nor the raised caps take effect for a dispatch made before a
  session restart.
- No migration, no runtime behavior change beyond subagent turn budgets and
  which process calls one CLI command; reversible by reverting this diff.

## Decisions needed

- None.

## Completion evidence

- **Delivered:** `reviewer` and `lightweight-reviewer` now write
  `findings.json`/`coverage.json` and state a decision rather than
  self-recording; `ai-agent-guidelines.md` assigns recording to the
  dispatcher; every review-shaped subagent's `maxTurns` raised to 40 (and
  `code-audit-gate`'s to 40 for the same reason).
- **Changed:** `.claude/agents/{reviewer,lightweight-reviewer,
  architecture-maintainability-specialist,concurrency-specialist,
  correctness-tests-specialist,security-data-specialist,
  rollout-specialist,code-audit-gate}.md`,
  `.codev/for-ai/ai-agent-guidelines.md`, and their
  `src/codev_workflow/bundle/` mirrors (18 files, 112 lines).
- **Head commit/snapshot:** `d9722a85553710d99d4a0a730517d359ac8c55bc`
  (pre-rebase; rebased onto `main` after PR #48 merged, see round-state
  `reopens` history for the post-rebase head).
- **Validation actually run:** `just test` 31/31; `just validate-catalog`
  passed (12 skills, 2 guides, 8 behavioral scenarios); ruff lint passed;
  byte-diff parity check between installed and bundle copies found no
  divergence.
- **Acceptance evidence:** Success criterion above -> the parity check and
  the absence of any remaining self-record instruction, both confirmed in
  round 2's builder evidence and reviewer coverage.
- **Scope deviations:** `code-audit-gate`'s cap raise (noted above) and the
  188-token instruction-budget cost landing outside the verification-first
  plan's own slices; both recorded as known limitations rather than hidden.
- **Known limitations:** 18 files changed against a 12-file budget
  (`over_budget: true`), purely because each edit is made twice (installed
  copy and bundle copy); reported, not capped, per this task's own size
  report. Claude Code's agent-definition caching means the fix is inert
  for any session already running when it lands.
- **Review state:** Inner loop: READY_FOR_OUTER_LOOP, no findings (round 2).
  This plan is being written after the fact, retroactively, because the
  work was implemented and inner-loop reviewed before a plan document
  existed for this slice -- discovered when `codev next` was consulted
  again after rebasing this branch onto `main` following PR #48's merge.
