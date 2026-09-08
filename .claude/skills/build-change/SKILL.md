---
name: build-change
description: Pair with a developer to investigate, plan, implement, test, and prepare one bounded code change, bug fix, refactor, or delivery-plan task. Use when the user wants hands-on AI-assisted coding with frequent checkpoints and human control rather than a long autonomous implementation loop. Ground every plan in the current repository and keep changes small and reviewable.
license: BSD-3-Clause
---

# Build Change

Work as an interactive pair engineer. The human owns intent and acceptance; the
AI investigates, proposes, edits, validates, and explains.

**Inside a task, a plan covers one slice, and the developer accepts it before
the builder runs.** Use `assets/implementation-plan.template.md` and persist it
at `docs/codev/task/<task-id>/<slice-id>-implementation-plan.md` — or
`docs/codev/task/<task-id>/implementation-plan.md` when the task holds a single
slice named for itself, which is the same file this skill has always written.
One plan per slice, not one per task: a task-level plan is the document the
slice list came out of, and the slice being built needs its own. Acceptance is
the developer writing `Status: Accepted` into that file; never record it for
them. Its Approach and risk points are also what the orchestrating session
carries into `--description` — the eventual pull request body renders that text
verbatim and nothing else about the plan, so keep those sections readable on
their own.

When invoked directly by a developer with no orchestrating session and no task
id (e.g. a single bounded edit), skip the task-lifecycle step entirely: use the
template only when work spans sessions, affects several components, or needs a
reviewed written plan, and write it at whatever location the developer names —
or keep it inline per the next section.

## 1. Frame the change

Read the issue or task, relevant brief/design/API references, repository
instructions, and current Git state. Before editing, show a compact inline focus
card:

- **Change:** intended outcome;
- **Success:** observable acceptance behavior;
- **Non-goals:** explicit exclusions;
- **Allowed scope:** expected components or paths;
- **Validation:** checks that will provide acceptance evidence;
- **Stop if:** material decisions or conditions that require the human; and
- **Work style:** `Pair` by default, or `Bounded delegate` only for isolated,
  well-specified, testable, reversible work.

For an obvious low-risk change, keep this inline. Do not manufacture planning
documents. Treat the allowed scope as a drift boundary: surface a needed
expansion before editing outside it.

## 2. Ground the plan

Inspect actual files, symbols, tests, build commands, conventions, ownership,
and recent related changes before proposing edits. Identify mismatches between
the request and repository reality.

A new request does not silently supersede an accepted brief, design, API, or
repository policy. When they conflict, stop, show the exact conflict, recommend
the safest resolution, and obtain an explicit human decision in the owning
artifact before implementation.

Propose the smallest coherent change, expected files, test approach, risks, and
any intentional follow-up. Obtain a human decision before editing when the plan
introduces or changes an API, data model, dependency, security behavior,
architecture, user-visible scope, or destructive operation. Otherwise announce
the plan and proceed interactively.

## 3. Implement a small change

Prefer one review purpose. As a soft warning, reconsider the slice when it
exceeds roughly 600 non-generated changed lines or twelve files; generated code,
mechanical migrations, and tightly coupled tests may justify more. Split by
default only when each part remains buildable and useful on its own.

When the project's `git.workflow` configuration resolves to `trunk` (the
default; check with `codev config get git.workflow`), a part may instead
split at a real engineering-dependency boundary — a schema change ahead of
the logic that uses it, an isolated component before it is wired in —
provided it stays safe to merge alone: tested, non-breaking, and, if it
changes behavior before the larger change is complete, contained behind a
flag, config toggle, or other guard named explicitly in the plan's
containment field. Under `feature-branch`, keep every part independently
useful; do not assume containment is available.

When a split is needed, choose the boundary from one of four decomposition
strategies, and name which one in the plan's Slices field:

- **Preparatory refactor:** restructure existing code with no behavior
  change, ahead of the change that actually needs the cleaner shape --
  reviewers only check for regressions, so it merges fast.
- **Contract-first:** land the data model, schema, or API signature first,
  with no execution logic behind it yet.
- **Behavior-vertical:** build one small, end-to-end sub-feature at a time,
  thin but complete top to bottom, rather than one layer of the whole
  system at once.
- **Wiring-behind-a-guard:** land the public interface or route first,
  inert (a stub, a not-implemented response, or off behind a flag), then
  implement and finally expose it in a later slice -- this is what the
  containment field above describes.

Reuse repository patterns. Read
`.agents/skills/testing-craft/references/writing-tests.md` before adding or
updating tests -- it covers naming, structure, and the test-doubles
priority ladder. Add or update tests with the behavior. Do not weaken
tests, invent missing APIs, silently expand scope, or edit accepted product and
design decisions to make implementation easier.

Share concise progress at meaningful boundaries. Do not run unattended retry
loops. After two failed attempts with the same root cause, stop, present the
evidence, and agree on the next approach with the human.

## 4. Validate and inspect

Run the repository's formatter, static checks, affected tests, and proportionate
broader tests. Report exact commands, outcomes, and any checks that could not run.

Review the complete diff for accidental files, debug code, weakened assertions,
security or compatibility regressions, unnecessary complexity, and stale docs.
Map important acceptance criteria to evidence; formal requirement IDs are only
needed when policy or risk requires them.

## 5. Prepare review

Return a compact evidence receipt:

- **Delivered:** outcome and observable behavior;
- **Changed:** files and components;
- **Validation actually run:** exact commands and outcomes;
- **Acceptance evidence:** criteria mapped to evidence;
- **Scope deviations:** none, or accepted deviations;
- **Known limitations:** risks and follow-up work; and
- **Review state:** independent review status and rollout implications.

When a written implementation plan exists for this task, update its
`Status:` line to match this Completion Evidence in the same edit — a plan
that still says `Draft` while its own Completion Evidence claims delivery is
a stale artifact, not a harmless formality; independent review checks for
exactly this mismatch.

For normal or higher-risk work, invoke `review-change` in a fresh context when
available. The implementing AI never declares its own work approved. The human
must inspect the diff and explicitly authorize commit, merge, publication, or
release actions according to repository policy.

## Stop conditions

Stop and ask for one precise decision when required behavior conflicts, a
material design choice is missing, the repository is unexpectedly stale,
permissions or a dependency are unavailable, concurrent changes collide, or
safe validation cannot be produced. Include evidence and safe alternatives.

## The inner loop, end to end

Moved here from `.codev/for-ai/ai-agent-guidelines.md` so it loads when
Build actually starts, rather than on every turn of every phase.

Where the platform provides repository-local subagents, keep the developer in
one conversation and automate the mechanical handoffs between agents — but
never the authority checkpoints.

**Say where things stand, before you are asked.** Run `codev next --json` at
the start of every turn and after every state change, and open every phase
boundary with three things in plain language: the position it reports, the
step it recommends, and why that step follows. The developer must never have
to know that a draft pull request means outer-loop review is next, that a
blocking finding needs triage before anything else, or that a merged slice
means the next one may begin -- all of that is computed, and stating it is
your job, not theirs. When the navigator reports `blocked`, say so and stop;
do not work around it.

**Read values, never prose.** Every `codev` command accepts `--json` wherever
its result feeds a later command, and that is the only supported way to carry
a value forward. Never scrape an identifier out of a command's
human-readable sentence, and never fall back to raw `git` for something a
guarded command already returns — `codev round close --json` reports the
`head` the next task check needs, `codev slice publish --json` reports the
pull request's `url` and `number`, and `codev git restack --json`
reports the new `head`. Human-readable output is for the developer reading
along; it is not an interface and may be reworded.

Most tasks start cold, and every numbered step below applies as
written. Two other entry modes (takeover and direct-review): a
**takeover** item already has unfinished human commits beyond its base
snapshot — follow every step below, but tell `builder` at step 3 to read
that existing diff before changing anything and continue it rather than
replace it. A **direct-review** item is already-finished human work that
needs only review — skip straight to step 5's `ok_ready_for_pr` handling;
`codev task check` recognizes a fresh `direct-review` item as immediately
ready, with no inner-loop round recorded at all.

1. Read authority and repository evidence, confirm the task is ready, and
   present the focus card. Open the task with `codev slice begin`, which
   handles the branch, issue linkage, and round state in one operation —
   **passing every slice the accepted plan names to `--slice`, in order.**
   Omitting `--slice` records a task holding exactly one slice named for
   itself, which is a real case only when the plan really is one pull
   request; otherwise it is how a plan's slice list stops existing the
   moment work starts on it, and every later slice lands in the first
   slice's pull request. There is no command that adds a slice afterwards.
   `codev slice begin` warns when an accepted plan names more slices than
   you recorded; `codev next` names the count before you start. Raw `git`
   and `gh` writes stay denied.
2. **Plan the slice you are about to build, and get the developer to accept
   it.** Write it to `docs/codev/task/<task-id>/<slice-id>-implementation-plan.md`
   (for a task holding one slice named for itself, `implementation-plan.md`
   in that same directory) using
   `.agents/skills/build-change/assets/implementation-plan.template.md`, and
   keep a short 2-4 bullet Approach/Risks summary from it in mind for
   `--description`, since the eventual pull request body renders that text
   and nothing else about the plan. A plan covering the whole task is the
   document the slice list came out of, not a plan for the slice being
   built.

   Then stop and ask. Acceptance is the developer writing `Status:
   Accepted` into that file — you never record it on their behalf, and
   `codev next` will keep naming this step until they do. This is the one
   approval that is not risk-tiered: it applies to every slice, however
   small, because the builder executes an accepted plan rather than
   deciding the approach itself. Raise the "Stop conditions" below and the
   risk categories in "Risk overrides size" as part of the same single
   decision rather than as a second interruption. Never edit product code
   yourself in this role — that is `builder`'s job, delegated below, or your
   own hands only under an explicitly recorded `pair` slice.
3. **Builder** executes only the accepted plan. It may edit and test, but it
   cannot invoke other agents, alter accepted authority, commit, push, merge,
   publish, deploy, migrate data, or expand rollout. It returns an evidence
   receipt with the exact base snapshot, validation, deviations, and
   limitations — not a head snapshot, since it never commits and so cannot
   know one. Close the builder's round yourself with `codev round close
   --role builder --evidence <file>`, against the exact resulting head. The
   builder never records its own evidence.
4. Verify the evidence receipt is complete, then invoke
   **lightweight-reviewer** in a *fresh* task with the exact snapshot and
   task. This pass is deliberately narrow: correctness and intent-match
   against the task, plus independent re-verification that the
   builder's reported validation actually passes — the full dimension set is
   the outer loop's job, not this pass's.

   **Dispatch it cheaply, and record its round yourself.** Re-verification is
   the most turn-expensive job in the loop, not the cheapest: the reviewer
   re-runs everything the builder ran and reads the whole diff. So write the
   diff to a file and name it in the dispatch rather than making the reviewer
   reconstruct it, and tell it to batch validation into one command — every
   tool call spends a turn. The reviewer writes `findings.json` and
   `coverage.json` and states its decision; **you** then run `codev task
   record --role reviewer --head <head> --findings <f> --coverage <c>
   --decision READY_FOR_OUTER_LOOP|CHANGES_REQUIRED|BLOCKED_BY_MISSING_EVIDENCE`,
   the same way you close `builder`'s round from its evidence receipt. No
   subagent records its own round. The reviewer still owns the verdict — you
   pass its files through unchanged, you do not author or edit them.
5. Run `codev task check` and act on its exit code instead of judging
   convergence yourself.
   - On `ok_continue` (`CHANGES REQUIRED`, under the round cap), route
     actionable findings back to the builder without asking the human to
     relay them, then reinvoke the lightweight reviewer on the corrected
     snapshot.
   - On `ok_ready_for_pr` (`READY FOR OUTER LOOP`), dispatch
     `code-audit-gate` — a narrow, autonomous subagent scoped to style and
     documentation only, never logic or behavior — against the exact head
     snapshot, *before* recording the reviewer round that produced
     `ok_ready_for_pr`. It self-fixes anything it finds and reports back a
     short summary instead of stopping for approval, since nothing in its
     scope needs one; commit again only if it changed anything, then
     record the reviewer round exactly once, against whichever head is now
     final, carrying `lightweight-reviewer`'s verdict plus that summary as
     an evidence note. Resolving this before the phase transition, not
     after, matters mechanically: it means mechanical cleanup never opens
     the outer phase or spends any of its round cap — that stays reserved
     for the five specialists' actual review. A clean or now-clean head is
     published with `codev slice publish --title <title>`. Read
     `.agents/skills/technical-writing-style/references/short-form-voice.md`
     before choosing `<title>`: state the change's user-visible effect in
     plain English, imperative mood, with no internal vocabulary (`slice`,
     `round`, a task or wave-row ID) — that traceability information
     already lives in the pull request body's tracking line. Publishing
     pushes the branch and opens the draft pull request for outer-loop
     review; it is fully reversible and has no effect on production, and
     it is not the same authority as merge.
   - On any other nonzero exit — the round cap is reached, a blocking
     finding repeats a prior round's, scope quietly expanded past the
     round's first pass, or the snapshot drifted — record the escalation
     with `codev task escalate` and hand the item to the human with the
     printed reason and a recommendation, the same as when the accepted plan
     must change materially, work collides, or safe validation is
     unavailable.
6. Once a pull request opens, tell the human plainly that outer-loop review
   is next -- load the `outer-loop-review` skill for this task once they
   authorize the specialist spend below; it is not something that continues
   on its own. Close the item with `codev task close` only once that
   concludes and the human has acted. Return the final evidence receipt,
   reviewer decision, and residual risks. Stop before merge, publish,
   deploy, migration, or rollout expansion — never before opening the pull
   request itself.
7. When that slice's pull request merges and the task holds a later slice,
   `codev slice land` advances to it and puts it on its own branch, stacked
   on the slice it follows. Then start again from step 2: the new slice
   needs its own plan and its own acceptance before its own builder runs.
   One slice is one branch is one pull request (ADR-0035) — if you find
   yourself adding a second slice's work to a pull request that is already
   open, the advance did not happen and the state is wrong, not the rule.

Pass task-local facts and evidence between agents — never private reasoning or
a raw chat transcript. Never spawn unrelated agents or run parallel builders
in the same worktree; if the platform lacks subagents, one interactive builder
performs implementation, but review still runs in a fresh context with human
approval before merge.

## Bookkeeping commits

Most `codev task`/`codev round`/`codev slice` state-mutating commands commit
their own write automatically (`git.auto_commit`, default true) — there is
no separate `codev git commit` step to remember for a pure bookkeeping
write. Within one continuous automated stretch of several such commands with
no human decision in between, pass `--defer-commit` to every call except the
last: the deferred writes accumulate uncommitted, and the final call's own
commit sweeps them all up together, producing one commit instead of several.
Flush — omit `--defer-commit` — immediately before yielding to a human for a
decision, and always before a push: a push needs everything relevant
committed, and a question put to a human is exactly the point where what has
happened so far should be durable, not sitting in an uncommitted working
tree.

Concretely, from this project's own history: reopening a task, recording a
round's outcome against it, and closing the task used to take three separate
commands — `codev task reopen`, `codev task record`, `codev task close` (or
`codev slice land`) — each committing on its own, four bookkeeping commits
in total once a review waiver was involved too. The same sequence today is
`codev task reopen --defer-commit`, `codev task record --defer-commit`
(twice, if a waiver is also needed), then a final `codev slice land` with no
flag — one commit, not four.

## Recovering a stuck task

A task start refuses to reuse an id once its state file exists at all — closed
or not — and task checking treats a round cap or a snapshot
mismatch (`stop_drift`) as a hard stop by design. Those guards protect the
evidence trail; they are correct, not a bug to route around by hand-editing
`.codev/task/<id>/round-state.json` or restarting under a new id and losing
the item's history.

When a human decides recovery is warranted — the round cap was genuinely
too low, an approved change (a triaged fix, a pre-PR audit remediation)
landed after the item converged or closed, or a closed item should
continue — `codev task reopen --id <id> --head <current-head> --reason
<text>` re-baselines the item onto that head and opens one fresh, empty
round so the ordinary builder/reviewer flow can resume. It never edits a
previously recorded round's evidence, and every call is appended to the
item's `reopens` history, visible in `codev task log`. Treat this exactly
like any other item above: present the stuck state and propose reopening as
the recommendation, do not run it on your own initiative because a round
merely looks stuck.

A reopened item can land directly in the outer phase (when the round it
reopened from had decided `READY_FOR_OUTER_LOOP`), skipping the inner
loop's own bridge into a pull request. Publishing accounts for this: it accepts
any non-stop task-check result once the item is in the outer phase, not only
`ok_ready_for_pr`, provided the branch has no pull request yet — so if
outer-loop review reaches `ok_machine_review_complete` with none open, publish
the slice once before `codev git mark-ready`, which still requires that pull
request to already exist.
