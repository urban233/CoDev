# ADR-0045: Routine bookkeeping self-heals silently; commit, PR-open, and merge become boolean-gated actions

**Status:** Accepted
**Date:** 2026-09-05
**Owner:** Martin Urban
**Related:** [ADR-0002](0002-inner-loop-self-healing-and-pr-open.md), [ADR-0036](0036-cli-is-an-agent-interface.md), [ADR-0037](0037-human-review-and-ownership-gate.md)

## Context

A real outer-loop review session on this repository's own `lead-as-skill-plan`
task (PR #41) produced a clear pattern in how much of CoDev's own ceremony is
mechanical rather than a decision. Across two correction rounds, the agent
running the loop made four separate `codev git commit` calls purely to
persist `.codev/task/` bookkeeping — a `task reopen`, a `task record`, a
`task waive-review`, and a `slice land` — each one narrated in the
conversation as its own step, though only two of those four (the reopen and
the waiver) reflected an actual human decision. The other two were the
mechanical consequence of decisions already made.

The same session also produced a concrete instance of bookkeeping drift with
*no* decision content at all: `codev slice land`'s own documented sequence —
call it once the pull request has merged — writes the task's `"closed"`
status locally, after the merge already happened, so that commit lands only
on the now-merged feature branch and never reaches the default branch unless
someone separately notices and lands it. Checking this repository's own
history at the time confirmed it was not a one-off: two of the three
previously merged tasks in `.codev/task/` show the same drift, sitting at
`"in_progress"` on `main` despite being fully shipped. `codev git commit`
already supports collecting everything currently dirty into one commit
(`git add -A`, guarded by `_refuse_if_mixed_dirty_paths`); nothing today uses
that capacity to avoid the four-separate-commits pattern above, and nothing
detects or repairs the drift-with-no-decision pattern at all.

`config.py` already resolves layered configuration — CLI flag, environment,
project `.codev/config.toml`, global `~/.config/codev/config.toml`, built-in
default — for `git.workflow`, `review.max_lines`, `review.max_files`,
`review.required_approvals`, `review.sensitive_paths`, and `review.pair_paths`.
Every key today is a free-form string; some are effectively enums or numbers
coerced ad hoc at the read site, but none is a validated two-value domain, and
nothing in the schema stops a key meant to gate a real capability from being
set to something that is neither `"true"` nor `"false"`.

ADR-0002 already used the term "self-healing" for a different thing: making
the *inner* loop's human-approval checkpoint conditional and structural
instead of unconditional. This ADR reuses the same instinct — check for a
condition structurally instead of asking about it every time — for a
different layer: whether a *bookkeeping* commit, a PR's opening, or a merge
needs to reach the developer's attention at all. ADR-0037 separately
established that "CoDev does not enforce the merge itself. GitHub's branch
protection does" — there is, by design, no `codev git merge` in the guarded
surface today; every merge in this project's own history, including PR #41's,
happened through a raw `gh pr merge` call outside the guarded CLI entirely,
on an explicit human "merge it."

## Decision

**Distinguish mechanical bookkeeping from decision content, and treat them
differently.** A state transition is mechanical bookkeeping when a human
already authorized the thing it records and the transition itself carries no
new discretionary content — persisting a round's already-reported evidence,
reconciling a flag or status a prior transition failed to propagate, closing
a task once its last slice's merge is externally observed. A transition is
decision content when a human's judgment shapes the outcome now — a
specialist's finding, a waiver, an escalation, a reopen authorization. Only
the first category is in scope for silent, automatic handling below; the
second stays exactly as visible as it is today.

1. **Commit becomes the mutating verb's own responsibility, gated by
   `git.auto_commit`.** Every `codev task` / `codev slice` / `codev round`
   verb that writes to `.codev/task/<id>/` performs its own commit as the
   last step of the same invocation when `git.auto_commit` resolves `true`
   (see key table below) — the same `git add -A` plus
   `_refuse_if_mixed_dirty_paths` guard `codev git commit` already runs, not
   a new commit mechanism. There is no longer a separate, narrated
   `codev git commit` call for pure bookkeeping, because the obligation to
   remember and announce one disappears — it is inside the command the agent
   was already calling. `codev git commit` itself is unchanged and stays the
   only path for actual product-code commits (the builder's own edits) and
   for any project or developer that sets `git.auto_commit` to `false` and
   keeps full manual control.

2. **A sequence with no human decision in between collapses into one commit,
   not several.** The existing composite verbs (`round close`, `slice land`,
   `slice begin`, `slice publish`) already do this for builder-round data;
   extend the same principle to the reviewer-recording path. Recording a
   round's outcome and a `slice land` that immediately follows it with no
   intervening human step are one filesystem transaction and one commit.
   Where a genuine decision boundary sits between two mutations — `reopen`
   requires human authorization before `record` may run at all — they stay
   separate commits, because they are separate authorized events in time,
   not a CLI shortcoming to fix.

3. **Mechanical drift gets a repair pass, not a report.** For the
   no-decision-content class specifically — a provenance flag a related
   transition failed to clear, a `"closed"` status stranded off `main` by
   `slice land`'s post-merge timing — `codev task check` detects and repairs
   the drift itself as part of the same invocation, committing the repair
   under the same `git.auto_commit` gate, rather than surfacing it as a
   question. It is reported afterward, in passing, if the agent's guidance
   mentions it at all — never as a blocking checkpoint. The two instances
   found this session (the stale `opencode_default_agent_managed` flag class
   fixed in PR #41 itself, and the `slice land` stranded-commit class) are
   the seed cases; both are mechanical by the definition above, since no
   human judgment changes what the correct repaired state is.

4. **`codev git open-pr` / `slice publish` are gated by
   `git.auto_open_pr`.** True (the default) preserves ADR-0002 decision 5's
   existing behavior exactly: reaching `ok_ready_for_pr` already means the
   relevant loop's own gates cleared, so opening a still-draft PR is not a
   new decision. When `false`, the verb refuses and the navigator's computed
   recommendation (ADR-0036) changes from "open the PR" to "ask before
   opening the PR" — the branch lives in the oracle's own computed output,
   not in agent-side convention, matching ADR-0036's rule that phase-boundary
   guidance is computed rather than remembered.

5. **A new, narrow `codev git merge` joins the guarded surface, gated by
   `git.auto_merge`, defaulting to `false`.** Shaped exactly like the rest of
   ADR-0002's git surface: operates only on the task's own branch, refuses
   any target resolving to the default branch as a merge *source*, never
   accepts or forwards a force flag, and independently re-derives the
   navigator's own position rather than trusting the caller already checked.
   It refuses to run unless that position is `ok_human_approved` or
   `ok_human_review_waived` — so `git.auto_merge=true` only ever removes the
   need for a human to personally type the merge command; it never removes
   ADR-0037's independent-approval requirement, which stays enforced exactly
   as it is today. Every existing installation keeps today's behavior
   unchanged — merge stays a human action outside the guarded surface —
   until a team explicitly opts in.

6. **Three new config keys, each a strict two-value domain, never prose:**

   | Key | Default | Governs |
   |---|---|---|
   | `git.auto_commit` | `"true"` | Whether a state-mutating verb commits itself (1) and repairs mechanical drift silently (3), instead of leaving the tree dirty for a manual `codev git commit`. |
   | `git.auto_open_pr` | `"true"` | Whether reaching `ok_ready_for_pr` opens the draft PR as part of the same call (4), instead of stopping to ask first. |
   | `git.auto_merge` | `"false"` | Whether `codev git merge` is permitted to run at all (5). Independent of, and never a substitute for, ADR-0037's approval gate. |

   `config.py` gains a `resolve_bool(key, ...)` accessor used by every read
   site that consumes one of these three keys. It accepts only the literal
   strings `"true"` or `"false"` — matching TOML's own boolean-literal
   spelling, for a project that would rather write `git.auto_merge = "true"`
   by hand and have it mean exactly one thing — and raises `ConfigError` for
   any other value, at both read time and at `codev config set` write time.
   A typo or a free-text policy description fails loudly; it cannot silently
   resolve to either boolean.

## Alternatives considered

- **Keep manual `codev git commit` after every mutation; just ask the agent
  to narrate it less.** Rejected. The stranded post-merge bookkeeping commit
  this ADR is partly a response to was not caused by over-narration — it was
  a real ordering gap between when `slice land` runs and when its output can
  reach `main`. Quieter narration around an uncorrected gap still leaves the
  gap.
- **One repo-wide automation-level setting (e.g., `off` / `bookkeeping-only`
  / `full`) instead of three independent booleans.** Rejected outright: the
  request this ADR responds to was explicit that these must be separate,
  hard booleans, not one combined, prose-flavored level. It is also the
  wrong shape on its own merits — `auto_commit=true, auto_open_pr=true,
  auto_merge=false` is the natural default combination, and an enum would
  either fail to express it or multiply into as many named levels as there
  are meaningful combinations anyway.
- **Let `git.auto_merge=true` also imply skipping ADR-0037's
  independent-approval requirement, as a convenience for a genuinely solo
  repository.** Rejected. `codev task waive-review` already exists as that
  repository's honest, explicit escape hatch. Folding approval policy into
  the same boolean that governs whether the merge *mechanism* runs would let
  one flag silently change what counts as reviewed — exactly the conflation
  ADR-0037 exists to prevent.
- **Have mechanical drift repair silently patch the working tree with no
  commit at all, and let the next real commit absorb it.** Rejected. An
  unrecorded state change is a worse audit story than a quiet, correctly
  labeled commit nobody has to read. This tool's standing bar is that every
  state change is attributable to a commit; a repair is not an exception to
  that, only to whether it is narrated.

## Consequences

- Total real commit count for a routine outer-loop round does not
  necessarily fall to one — a reopen requiring authorization and a triage
  answer are still separate real events and still get separate commits.
  What disappears is the agent's obligation to separately invoke and narrate
  `codev git commit` for the mechanical ones; that step moves inside the
  verb the agent was already calling.
- `codev git commit`'s existing guards and `--paths`/`--staged` options are
  untouched; a project or developer that sets `git.auto_commit=false` keeps
  exactly today's manual flow, unchanged.
- The navigator (ADR-0036) gains a new read dependency on `config.py`
  alongside its existing reads of round-state, git state, and GitHub's
  PR/review state, since its computed recommendation must now branch on
  `git.auto_open_pr` and `git.auto_merge`.
- `codev git merge` is new git/GitHub mutation surface and needs the same
  adapter-conformance coverage ADR-0002 required for
  `branch|commit|push|open-pr`: raw `git merge` and `gh pr merge` stay denied
  in every role's permission block on every platform; only the guarded
  command is ever allowed.
- A misconfigured `git.auto_merge=true` in a repository with no branch
  protection is the single highest-consequence misconfiguration this ADR
  introduces. Defaulting it `false`, and still enforcing ADR-0037's approval
  gate even when it is `true`, are both load-bearing and should not be
  relaxed by a future change without a new ADR of its own.
- Mechanical drift repair needs the same mutation-testing discipline already
  applied to the `default_agent_managed` fix in PR #41 — proof that it is
  idempotent and never fires against a healthy repository — because a
  background repair that fires incorrectly is worse than the ceremony it
  replaces.

## Revisit when

Adopters report that silent auto-commit produced a change they did not
expect (an unfamiliar diff in CI, a commit they cannot account for) — that
would mean the boundary drawn here between "mechanical bookkeeping" and
"decision content" needs to move, or the default needs to flip. Also revisit
once a real repository runs with `git.auto_merge=true` for a while: whether
`task.check` plus ADR-0037's approval gate is sufficient protection on its
own, with no other safeguard, is an assumption this ADR makes and does not
yet have evidence for.
