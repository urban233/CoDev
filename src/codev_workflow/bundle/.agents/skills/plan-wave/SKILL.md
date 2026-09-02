---
name: plan-wave
description: Turn an accepted product or feature brief and any required design into a lightweight, team-profile-aware, rolling-wave delivery plan. Detail and ready only the current wave; keep later waves coarse until their own turn. Use when a team needs outcome-based waves, unassigned capability lanes or ready tasks, owners, independent reviewers, simple dependencies, integration checkpoints, WIP limits, or risks. Do not create a separate architecture or capacity bureaucracy, and do not pre-decompose work beyond the current wave.
license: BSD-3-Clause
---

# Plan Wave

Create a plan that helps a team choose the next useful work, not a prediction of
every future edit. A completed wave plan is a durable, reviewable project
artifact, not a chat-only response. Detail only the current wave in depth;
later waves stay coarse outcome statements until their own turn — this is the
plan's central discipline, not a preference, and where the platform provides
it, `require_wave_shape.py` checks it mechanically rather than relying on this
sentence alone.

## 0. Persist the plan

First inspect the repository for an existing wave-plan location and for a
linked project tracker. The repository plan is the durable coordination
baseline, even when an external tracker holds routine, high-churn status.

For an explicit request to create or update a wave plan, create or update
the plan in the repository. Default to
`docs/codev/wave/<feature-slug>.md`; use an established equivalent
location when the project already has one. Start from
`assets/wave-plan.template.md` when creating a new plan. Read
`.agents/skills/technical-writing-style/references/writing-style.md`
completely before drafting or revising the plan's prose.

An initial request to *show* or frame a wave without creating a plan may
remain an unassigned, chat-only planning brief. Make that limitation explicit
and do not describe it as a completed wave plan.

Before writing, verify that every referenced brief and design is a durable
repository artifact or stable tracker record. Never use a conversation as an
authority link. If accepted product or architectural decisions exist only in
conversation, return to `define-product` or `design-solution` to persist the
appropriate authority before making tasks ready.

Before updating an existing plan, inspect its current content and the Git
working tree. Do not silently overwrite a locally changed plan; surface the
conflict and ask for direction. Preserve the plan's document state using only
`Draft`, `Accepted`, `Active`, or `Superseded`; Git history is its revision
record. `Draft` is not a resting state: once every row in "Risks and
discovery" tied to a Decision point has a recorded human answer, that is the
point to move the document state to `Accepted` — say so and ask, rather than
leaving a plan the team is already acting on marked as if it were still
unresolved.

## 1. Verify planning inputs

Read the accepted brief and applicable design. Confirm the next outcome, fixed
contracts, important risks, current commitments, and required reviewers. Return
unresolved product questions to `define-product` and architectural questions to
`design-solution`.

If a previous wave in this plan closed, confirm its evidence was actually
recorded and compare it against this wave's assumptions before detailing
anything new. When the evidence contradicts an assumption behind a later
wave, or leaves a defect or cleanup item the previous wave's evidence named
but did not resolve, run a bounded hardening pass — fix what the evidence
calls for — before continuing. Do not detail a new wave on top of
unaddressed fallout from the last one; this revisit checkpoint is what makes
the rolling-wave discipline real between sessions, not an optional courtesy.

Classify uncertain facts before planning:

- **fixed:** accepted product or architectural decisions;
- **hard blocker:** a missing decision or contract that prevents a specific item
  from starting safely;
- **risk track:** evidence that can be retired independently without blocking
  unrelated work;
- **staffing input:** capability, capacity, ownership, or reviewer information;
  and
- **deferred:** a decision that is not needed for the current wave.

Do not call a risk track, staffing input, or deferred decision a blocker unless
it actually prevents the named work from starting.

### Team-profile gate

Headcount is not a delivery profile. Do not infer a developer's skills,
availability, component ownership, review authority, or security/domain
qualification from a team size, title, or anonymous label.

Before assigning ready work, establish the smallest useful profile for each
developer: stable name or label, relevant strengths, current capacity or WIP,
component/API ownership, and independent-review restrictions. Inspect existing
ownership and tracker facts first; ask only for missing information.

If profiles are incomplete:

1. recommend the next wave and show **unassigned capability lanes**, not
   `Developer 1`, `Developer 2`, or similar placeholders;
2. show only candidate concurrency, conditional on named contracts or fixtures;
3. do not claim that tasks are ready or assign reviewers; and
4. ask exactly one recommendation-led question for the missing team profile.

When the human explicitly asks for an initial wave framing first, provide
that framing as an unassigned planning brief, then make the team profile the
single remaining input before producing assignments.

## 2. Define the current wave

Each wave must demonstrate observable value or retire a named risk, such as
"internal user completes the primary workflow." Avoid component-completion
waves such as "backend done."

For a requested first **useful product** wave, name the target user, the
observable action, and the durable result. A foundation-only wave is valid
when it retires a named risk, but label it as an enabling or risk-retirement
wave rather than presenting it as user value. Include the smallest
in-scope product object when that is necessary to make the demonstration useful.

Before creating this wave's tasks, name what is actually uncertain about it.
Classify that uncertainty as one of:

- **requirements-shaped:** uncertain what the wave should do, or how a user
  will actually use it. Resolve it by building the smallest version and
  observing, inside this wave.
- **architecture-shaped:** uncertain whether the approach is correct, safe,
  or hard to reverse — a real contract, schema, or cross-component
  trade-off. Resolve it through `design-solution` before this wave's task
  table is committed, not after.

A wave can carry both kinds of uncertainty about different parts of its
scope; classify each part it actually applies to rather than labeling the
whole wave once. This classification is a required step here, not implicit
judgment folded into a task's risk level — the risk-level field in step 3
still applies separately, for review and reviewer-capacity purposes.

Plan the current wave in detail. Keep later waves coarse and revise them
using evidence from working software.

## 3. Create reviewable tasks

Before team profiles are available, create only capability lanes. For every lane
that could proceed concurrently, name the accepted API, schema, decision, or
contract fixture that makes it safe. If no such authority exists, state
**Blocked by** the missing contract; do not imply parallelism from technical
layer names alone.

Each current task must include:

- outcome and acceptance criteria;
- relevant design/API links;
- owner and independent reviewer;
- dependencies and integration checkpoint;
- risk level: low, normal, high, or critical;
- expected validation; and
- status: discovery, ready, in progress, review, blocked, or done.

A task should normally produce one small pull request or a short stack of
independently valid pull requests, split by behavior rather than by
technical layer. When the project's `git.workflow` configuration resolves to
`trunk` (the default; check with `codev config get git.workflow`), a task
may instead split at a real engineering-dependency boundary — a schema
change before the logic that uses it, an isolated component before it is
wired in — provided it stays safe to merge on its own: tested,
non-breaking, and, if it changes behavior before the wave is complete,
contained behind a flag, config toggle, or other guard the task names in
its own containment field. Leave that field blank when a task is
independently useful on its own, or when `git.workflow` resolves to
`feature-branch`. Use a bounded discovery item when a needed contract
cannot be resolved from accepted authority. Never turn an unresolved
decision into an implementation assignment.

Name the task's intended slicing in its own Slices field, choosing from
one of four decomposition strategies:

- **Preparatory refactor:** restructure existing code with no behavior
  change, ahead of the task that actually needs the cleaner shape.
- **Contract-first:** land the data model, schema, or API signature first,
  with no execution logic behind it yet.
- **Behavior-vertical:** build one small, end-to-end sub-feature at a time,
  thin but complete top to bottom, rather than one technical layer of the
  whole system at once.
- **Wiring-behind-a-guard:** land the public interface inert -- a stub, a
  not-implemented response, or off behind a flag -- then implement and
  expose it in a later task.

Use only ordinary dependency language:

- **Blocked by:** work cannot begin safely.
- **Integrates with:** work can proceed against an agreed contract or fixture;
  integration happens later.
- **Lands after:** source-control or migration order matters.

## 4. Coordinate the team

Default maximum work in progress to one implementation item per developer.
Assign only after the team-profile gate passes. Map by relevant capability,
capacity, ownership, and support needs, not title or headcount. Ensure owners do
not approve their own changes. Name an integration owner only for waves
that cross ownership boundaries.

Treat review capacity as real work. Confirm reviewer availability before an item
becomes ready and define a small review queue limit (default two active reviews
per reviewer unless the team chooses otherwise). For high- or critical-risk
work, separately name any policy-authorized security, privacy, compliance, or
operations approver; never assume an ordinary code reviewer has that authority.

Track changing assignments, availability, and status in the wave plan or a
linked project tracker. Do not version them as architecture. When a tracker is
used, retain the wave outcome, task definitions, ownership/reviewer
commitments, dependencies, checkpoints, risks, and tracker link in the
repository plan.

## 5. Check readiness

An item is ready only when its outcome, acceptance, required design decisions,
dependencies, owner, reviewer, and test environment are known. Use a bounded
discovery item when evidence is missing. Never disguise uncertainty as an
implementation task.

Do not assign an item merely because there are idle developers. Keep it
unassigned or blocked until its contract, owner, and independent reviewer are
known. If the plan is still awaiting team profiles, report it as an unassigned
planning brief rather than a ready wave plan.

Review the plan with the team in one pass: current wave, ready work,
parallel work, blockers, integration points, and risks. Update routine status
without formal approval; seek human decisions only for scope, priority, risk,
ownership conflicts, or commitments.

## 6. Complete the artifact handoff

After creating or updating the plan, report its exact repository path, document
state, and the Git change summary. Link to the saved artifact rather than
leaving the complete plan only in chat. Summarize the decision and next action;
do not duplicate the full document unless the user asks.

## Handoff

Before implementation starts on a ready item, and only when the project
actually tracks issues on GitHub, and only for an item in the **current**
wave, push it with `codev git issue-create --title <title> --body <body>
[--path <glob>]...` (`--path` suggests owners from an existing `CODEOWNERS`
when one exists) and record the returned issue URL back in the plan's own
Status/tracker column. A task belonging to a later wave stays a plan row,
not a GitHub issue, until its wave becomes current — pushing it early
recreates exactly the rigidity this skill exists to avoid, even though
`require_wave_shape.py` (where the platform provides it) only checks the
plan document's overall shape at that moment, not which wave the specific
issue being created targets, so this rule is binding on its own, not only
when the gate happens to catch it. This is what `codev task start
--github-issue N` and `codev git open-pr`'s automatic `Closes #N` depend
on; a project with no GitHub issue tracker in use skips this step and the
plan entry alone remains the required authority. Write the body to a temp
file and pass `--body-file` instead of inline `--body` whenever it may
contain a backtick, `$`, or double quote — a shell corrupts those
characters before `codev` ever sees the text, silently mangling the issue.

If a developer starts implementation directly, without a session that ran
this Handoff first, `lead` checks and creates the issue itself
before opening round state — this Handoff is the first opportunity to do it,
not the only one.

Give each developer only their task, relevant brief/design/API links,
integration constraints, and acceptance criteria (including the recorded
issue URL, when one exists). Start `build-change` for the next ready item.
