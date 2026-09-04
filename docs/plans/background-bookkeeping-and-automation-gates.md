# Background Bookkeeping and Automation Gates - Implementation Plan

**Status:** Accepted 2026-09-05 by Martin Urban
**Owner:** Martin Urban
**Author:** Claude Sonnet 5 (drafted; not an approval)
**Implements:** [ADR-0045](../adr/0045-background-bookkeeping-and-boolean-automation-gates.md)
**Base commit:** `5db58f6`
**Risk:** medium. Touches every state-mutating `codev task`/`codev
round`/`codev slice` call site and changes default CLI behavior (commits an
agent used to make explicitly now happen inside a command it was already
calling). The highest-consequence piece — a merge-capable command — is
deliberately not part of this plan's build scope; see "Deferred" below.

## What this plan adds beyond the ADR

ADR-0045 decided the shape: mechanical bookkeeping self-heals silently,
`git.auto_commit`/`git.auto_open_pr`/`git.auto_merge` gate it, and merge gets
a narrow guarded command. It did not fully specify two things this plan
resolves: the mechanism that actually collapses a multi-step sequence into
one commit, and how to keep the bookkeeping commits that do land legible to
a human reviewer rather than merely quiet in conversation. Both were raised
directly: minimizing bookkeeping commits "because these are ugly and for
human reviewer difficult" is as much a concern about what ends up in the
PR's commit list as about what gets narrated while building it.

## Making bookkeeping commits minimal and reviewer-invisible

Five mechanisms, each independent of the others, each addressing a different
part of "ugly and difficult for a human reviewer":

1. **Commit moves inside the verb (ADR-0045 decision 1).** Removes the
   conversational ceremony. On its own this does not reduce how many
   bookkeeping commits land in the PR — it only removes the separate,
   narrated `codev git commit` step. That is why (2) and (4) below exist
   too.

2. **A defer/flush mechanism actually implements "collapse into one
   commit."** Every state-mutating verb gains a `--defer-commit` flag (and
   its `_defer_commit()` internal counterpart used by the composite verbs
   directly). With it set, the verb writes its state to disk exactly as
   today but does not commit. A plain `codev git commit` (or the next verb
   called *without* `--defer-commit`) then sweeps up everything accumulated
   since the last commit into one commit, exactly like `git add -A` already
   does. `.codev/for-ai/ai-agent-guidelines.md` and `outer-loop-review`
   gain one explicit rule: **defer within one continuous automated stretch;
   flush immediately before yielding to a human for a decision, and always
   before a push.** Both boundaries are natural and easy to hold to — a
   push already needs everything relevant committed, and a question put to
   a human is exactly the point where "what has actually happened so far"
   should be durable, not sitting in an uncommitted working tree. This is
   guidance layered on a mechanical primitive, not guidance alone: getting
   it wrong only costs an extra commit, it cannot silently lose state, and
   nothing about correctness depends on an agent remembering it perfectly.

3. **A mandatory, mechanically-enforced message prefix.** Every auto-commit
   (deferred-and-flushed or immediate) is prefixed `chore(codev-bookkeeping):`
   by the commit function itself — not by convention, not optional, and not
   overridable by a caller-supplied `--message` for this class of commit.
   This alone makes the noise filterable: `git log --oneline --grep
   '^chore\(codev-bookkeeping\)' --invert-grep` shows only commits with real
   content, and a reviewer working from the command line can do the same in
   one line without CoDev needing to build anything further.

4. **A `.gitattributes` block collapses their diffs in GitHub's own PR
   view, independent of how many of them exist.** GitHub treats a path
   marked `linguist-generated=true` as generated content: its diff is
   collapsed behind a "Load diff" control in the pull request view and it
   is excluded from the file list's visual weight. The installer gains a
   new managed block — parallel to the existing `AGENTS_BLOCK` and
   `GITIGNORE_BLOCK` mechanism in `installer.py` — that ensures
   `.codev/task/**/*.json` and `.codev/lock.json` carry that attribute in
   every installed project's `.gitattributes`. This is the one mechanism
   here that helps a reviewer today even if every other slice in this plan
   were dropped, and does not depend on commit count, message convention,
   or anything else landing first — which is why it is sequenced early,
   below.

5. **For drift that is independently verifiable against an external source
   of truth, skip persisting the correction at all until something else
   already needs to commit.** Not every repair has to become a commit of
   its own — see Slice 5 below for the concrete split between the two kinds
   of drift this plan actually found, and why only one of them needs a
   dedicated write path at all.

Together: (1)+(2) minimize how many bookkeeping commits exist at all; (5)
can eliminate a whole class of them outright; (3) makes the ones that
remain trivially filterable from the command line; (4) makes them visually
absent from GitHub's own PR review surface regardless of how many there
are. A human reviewer opening the PR sees code; a human reviewer who wants
the audit trail still has it, unfiltered, in `git log`, for everything that
actually needed one.

## Slices

Ordered by dependency; each sized to land as its own reviewable pull
request. `git.workflow=trunk` stacking (ADR-0034) applies — later slices
branch from the previous slice's head, not from `main`, until each merges.

### Slice 1 — Typed boolean config keys

`config.py` gains `resolve_bool(key, *, target, override=None) -> bool`,
built on the existing `resolve()`, accepting only the literal strings
`"true"`/`"false"` and raising `ConfigError` otherwise. `DEFAULTS` gains
`git.auto_commit="true"` and `git.auto_open_pr="true"` — `git.auto_merge` is
deliberately not added yet; see "Deferred" below. `codev config set` gains a
small `_BOOLEAN_KEYS` registry checked before writing: setting either
registered key to anything but `true`/`false` fails at write time, not just
at the next read. No caller reads these flags yet — this slice is pure
plumbing, and is intentionally inert on its own so it can be reviewed on its
own.

*Tests:* valid/invalid values through `resolve_bool` at every layer (flag,
env, project, global, default); `codev config set` rejecting a non-boolean
value for a registered key; `codev config list --json` round-tripping a set
boolean.

### Slice 2 — `.gitattributes` managed block

New managed block in `installer.py`, following `GITIGNORE_BLOCK`'s existing
shape exactly (marker comments, conflict-on-hand-edit, clean add/update/
remove through `plan_init`/`plan_update`/`plan_remove`). Ships
`.codev/task/**/*.json` and `.codev/lock.json` as `linguist-generated=true`.
Independent of every other slice — the reviewer-facing benefit (4 above)
lands the moment this merges, regardless of how many bookkeeping commits
still happen manually.

*Tests:* parallel to the existing gitignore-block installer tests — create,
update, conflict-on-local-edit, remove. *Validation not coverable by an
automated test:* GitHub's actual collapse behavior needs one manual check
against a real pull request carrying a `.codev/task/` change, noted here
rather than assumed.

### Slice 3 — Auto-commit primitive and defer/flush

The actual commit mechanism behind decisions 1-2: a shared
`git_ops._maybe_commit_bookkeeping(task_id, *, target, defer)` that every
state-mutating call routes through — `task.record`, `waive_review`,
`reopen`, `escalate`, `triage`, and the `close` path `slice land` uses.
Resolves `git.auto_commit` once per invocation; `defer=True` (from
`--defer-commit`) skips committing regardless of the flag's value, so a
caller can always force accumulation even with auto-commit on. Applies the
mandatory prefix from mechanism (3) above. When `git.auto_commit` resolves
`false`, behavior is exactly what it is today: the state write lands on
disk, nothing commits, a human or agent runs `codev git commit` by hand.

A conformance test (grep-shaped, matching this repo's existing pattern for
adapter and skill-card conformance) asserts every CLI subcommand that calls
one of the six state-mutating functions above passes through the shared
helper, so a future new subcommand cannot silently bypass it and reintroduce
a manual-commit-only path by omission.

*Tests:* auto-commit on/off for each of the six mutating operations;
defer-then-flush across two calls produces exactly one commit containing
both operations' state changes; the mandatory prefix is present and not
overridable; the conformance test itself, and a deliberate negative case
(a call site that bypasses the helper) failing it.

### Slice 4 — Wire the composite verbs and update agent guidance

`round close`, `slice land`, `slice begin`, `slice publish` pass
`defer=True` internally wherever a further mutation in the same logical
sequence is coming immediately after (documented per-verb, not left to the
caller to guess), and flush on the last step of the sequence. Update
`.codev/for-ai/ai-agent-guidelines.md` and `outer-loop-review`'s SKILL.md
with the defer-within-a-stretch / flush-before-yielding-or-pushing rule
from mechanism (2), including one concrete worked example drawn from this
repository's own outer-loop review of PR #41 — reopen, record, and land
collapsing into one flush point instead of the four separate commits that
review actually produced.

*Tests:* an end-to-end lifecycle test (extending
`tests/test_navigator_coverage.py`'s existing full-lifecycle walk) asserting
the total commit count for a representative round sequence drops relative
to today's baseline, not just that individual operations behave correctly
in isolation.

### Slice 5 — Self-healing, split by whether the correction is derivable

Working through whether self-healing can avoid a commit at all turned up a
real distinction between the two seed cases this plan started from, and the
answer is different for each.

**5a. Externally-derivable status needs no dedicated write path at all.**
The recurring `slice land` case — a task's last slice merged, but its
`"closed"` status commit landed only on the now-merged feature branch and
never reached the default branch — is independently checkable: the task's
recorded PR (already tracked via its slice's linkage) either is or is not
merged, and GitHub is the authoritative answer, not CoDev's own copy.
`codev task status` and the navigator stop trusting a locally-recorded
`"in_progress"` at face value once a task's last slice has a PR reference:
they check GitHub directly — the same live-PR-state read the navigator
already performs for other positions — and report the derived truth
immediately, with nothing to write or commit first. The stored value is
corrected **opportunistically**: only the next time some other real
mutation already touches that task's bookkeeping, routed through the same
defer/flush primitive from Slice 3, so it is folded into whatever commit
already exists rather than standing alone. If nothing else ever touches
that task again, the stale string sits inertly in an already-merged file
forever, and that is fine — it is no longer what anything trusts. GitHub's
own merge record is the audit trail for "this task is done"; CoDev's copy
becomes a cache of it, not a second, independent ledger entry that also
needs its own commit. This repository's own three prior merged tasks
(`accepted-status-and-prose`, `navigator-rename`, `navigator-coverage`) and
`lead-as-skill-plan` are real fixtures for the "already drifted" case this
mechanism reads correctly without writing anything.

**5b. Facts that are not derivable from present state still need a real,
committed write — but it never has to stand alone.** The
`opencode_default_agent_managed`-style stale-flag class records what a
*past* action did (whether CoDev itself set a value), which cannot be
reconstructed by inspecting the present config alone. A repair here has to
persist to be real and shared — an uncommitted, unpushed correction is a
silent local/remote divergence, worse than a quiet commit nobody has to
read, for the same reason the ADR gives for keeping repairs committed at
all. What changes from the ADR's original framing: this repair is not
special-cased with its own commit. It is just another caller of Slice 3's
`_maybe_commit_bookkeeping`, deferred by default, so it only produces a
standalone commit when nothing else is already in flight for that task —
otherwise it is absorbed for free into whatever real commit comes next.

Net effect: the class of drift that is genuinely just a stale local copy of
an externally-checkable fact can go its entire life without ever producing
a commit. The class that is a real, un-derivable fact still gets one, but
essentially never a *dedicated* one.

*Tests:* 5a — a task whose PR is merged but whose local status still reads
`in_progress` reports correctly through `codev task status`/`codev next`
with zero commits produced by the read itself; a subsequent unrelated
mutation on the same task absorbs the correction into its own commit,
verified by diffing that commit's contents. 5b — the mutation-testing bar
ADR-0045's Consequences section sets explicitly (idempotent; never fires
against a healthy repository), plus a case proving it defers rather than
committing standalone when another mutation is already pending in the same
call sequence.

### Slice 6 — Gate `codev git open-pr` / `slice publish` on `git.auto_open_pr`

When `git.auto_open_pr` resolves `false`, the command refuses with a message
naming the flag, instead of opening the draft PR. The navigator (`codev
next`) reads the same flag: at the `ok_ready_for_pr` position, its computed
recommendation is "open the pull request" when `true` (today's behavior,
unchanged) and "ask before opening the pull request" when `false`, per
ADR-0036's rule that the branch lives in the oracle's computed output.

*Tests:* both flag states, both through the direct CLI refusal and through
the navigator's recommendation text/JSON.

### Slice 7 — Close an existing OpenCode permission gap (independent of the rest of this plan)

Found while researching the now-deferred merge command below, but real and
already present regardless of it: `builder` and all five outer-loop
specialists' OpenCode permission blocks deny `git commit*`/`git push*`
explicitly but have no `"git merge*"` or `"gh pr merge*"` entry — both
currently fall through to the generic `"*": ask` rather than being flatly
refused. `code-audit` and `code-audit-gate` already carry the explicit
deny; this slice brings the other seven role files to the same standard.
On Claude Code there is no equivalent per-command permission block on any
role file at all — protection there is the session-level plan-first hook, a
different and coarser mechanism — so this slice states that platform
asymmetry explicitly in its own commit rather than silently assuming parity
with OpenCode. Small, mechanical, and has no dependency on Slices 1-6 or on
the deferred merge command below — it can land whenever, including first.

*Tests:* an adapter-conformance test asserting every role not explicitly
authorized to merge denies `git merge*` and `gh pr merge*` explicitly on
OpenCode.

## Deferred — `codev git merge` and `git.auto_merge`

Working through the "Slice 7 needs its own explicit check-in" risk from the
prior draft, the sharper resolution is not a heavier check-in inside this
plan — it is not building the merge command in this plan at all.
`codev git merge` and `git.auto_merge` stay accepted design (ADR-0045
decisions 5-6 are unchanged), but this plan builds only Slices 1-7 above.
The merge command becomes its own later plan, taken up only after
`git.auto_commit` and `git.auto_open_pr` have real usage behind them —
which is also the only way to actually learn whether `task.check` plus
ADR-0037's approval gate is sufficient protection on its own, the exact
open question ADR-0045's own "Revisit when" section names.

Concretely: `git.auto_merge` is not added to `config.py`'s `DEFAULTS` by
Slice 1 either — an inert config key gating a command that does not exist
yet is exactly the kind of premature surface this project's "more
opinionated, not more configurable" posture argues against. Both land
together, in the follow-up plan, when there is something real for the flag
to gate. When that plan is written, it inherits the same shape ADR-0045
decision 5 already specifies: task's own branch only, refuses the default
branch as a source, never a force flag, independently re-derives the
navigator's `ok_human_approved`/`ok_human_review_waived` position rather
than trusting the caller, and refuses outright when the flag is off.

This resolves the risk structurally rather than procedurally: the
highest-consequence piece is not a labeled checkpoint inside a stack a
reviewer could still wave through — it is simply not being built yet.

## Validation (whole plan)

- `ruff check`, `mypy src tests` (whole tree, one invocation — a prior
  mistake in this project was running mypy per file and missing a
  cross-file error), and the full suite
  (`GIT_CONFIG_GLOBAL=/dev/null .venv/bin/python -m unittest discover -s
  tests`) clean after every slice, not only at the end.
- `tests/test_navigator_coverage.py`'s baseline should still pass unchanged
  through slices 1-5; slice 6 is expected to need a deliberate baseline
  update, since it adds a genuinely new navigator position (the
  auto-open-pr refusal) rather than changing an existing one.
- `codev adapter verify` on both platforms after slice 7.
- At least one real end-to-end pass with `git.auto_commit=true` (the
  default) on a throwaway task, read back afterward to confirm the
  resulting commit history is what mechanisms (1)-(3) above predict —
  the same "don't trust the self-report, verify the actual diff" standard
  this session already held itself to for the `default_agent_managed` fix.

## Risks

- **Auto-commit becoming the default is an observable behavior change for
  every existing adopter**, not just new installs. **Resolved**: keep the
  default `true` — it matches the explicit vision this plan is built from
  (self-healing, backgrounded, opinionated by default), and the actual
  exposure is low, since this flag only ever governs commits to
  `.codev/task/` bookkeeping, never product code, never a push, never a PR,
  never a merge. The concrete mitigation is making the transition loud
  exactly once: `codev update` prints an explicit one-line notice the first
  time it applies a version where this default takes effect ("this version
  starts auto-committing task bookkeeping by default; set
  git.auto_commit=false to keep committing manually"), and records having
  shown it as a provenance flag in `.codev/lock.json` — the same shape
  already used for `opencode_default_agent_managed` — so the notice fires
  once per installation, not on every subsequent `codev update` forever.
  Still worth a `CHANGELOG.md` "Upgrading" entry alongside it, but the
  in-tool notice is the mitigation that actually reaches someone who
  doesn't read changelogs.
- **The defer/flush mechanism accumulates uncommitted state across multiple
  tool calls.** If an agent's session ends, or something goes wrong, before
  a flush point, that state is uncommitted-but-not-lost (it is still on
  disk, recoverable the same way any uncommitted edit is) — but it is a real
  window this plan introduces that does not exist when every mutation
  commits immediately. Named here rather than glossed over; mitigated, not
  eliminated, by the flush-before-yielding-or-pushing rule in slice 4.
  Every mutation still committing immediately when `git.auto_commit=false`
  keeps a full manual-control fallback available.
- **GitHub's `linguist-generated` collapse behavior is asserted, not
  verified by this plan's own test suite** — it is GitHub UI behavior with
  no API this repository's tests can exercise. Slice 2's validation section
  names the one manual check needed; this plan does not claim automated
  coverage for it.
- **The `codev git merge` slice (numbered 7 in the previous draft, before
  the permission-gap fix took that number instead) was the
  highest-consequence piece of this plan.** **Resolved**: not by adding a
  checkpoint inside it, but by not building it in this plan at all — see
  "Deferred" above. Removing the highest-stakes piece from the stack
  entirely is a stronger answer than a labeled checkpoint a reviewer could
  still wave through.

## What does not change

- `codev git commit`'s existing behavior, guards, and `--paths`/`--staged`
  options — unaffected for product-code commits and for any project that
  sets `git.auto_commit=false`.
- ADR-0037's independent-approval requirement — unaffected by this plan;
  `codev git merge`'s own eventual design (deferred, see above) must read
  it, never bypass it, whenever it is actually built.
- The five specialists, `builder`, `reviewer`, `lightweight-reviewer`,
  `code-audit`/`code-audit-gate` — no role gains new dispatch or commit
  authority. This plan ships no new merge capability at all; Slice 7 only
  tightens an existing permission gap toward what `code-audit` already
  does.

Accepted 2026-09-05. Built as a single task with one pull request, per
explicit instruction, rather than the seven stacked pull requests the
"Slices" section above describes — each slice below is instead one bounded
build round within that one task, verified before the next begins.
