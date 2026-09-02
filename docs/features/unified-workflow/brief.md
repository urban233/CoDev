**Status:** Accepted
**Owner:** Martin Urban
**Last reviewed:** 2026-09-02

## Problem and users

CoDev's users are its adopters: a developer, or a small team of roughly two to
ten engineers, building a product in a repository that has CoDev installed. The
target this brief aims at is narrower and worth stating plainly, because it
settles several arguments below: a small team at a company like Google or
Anthropic that relies heavily on AI to generate code, and that enforces a strict
review and ownership policy precisely so the generated code is high-quality
rather than slop that merges automatically.

### The aim this brief is subordinate to

Every action in CoDev must be performable by an LLM that drives the `codev` CLI.
The developer runs no CLI commands. They describe intent in plain language, and
the agent translates that into the guarded command sequence, reports back in
plain language, and **recommends the next step in the workflow without being
asked**. The CLI is an agent surface; the conversation is the developer surface.

This is already CoDev's stated intent, and the documentation says so accurately
in several places. `docs-site/src/content/docs/getting-started.md` tells a reader
that `codev init` is "the last `codev` command you type today." The home page
says the agents "run the `codev` CLI on your behalf so you don't have to."
`docs-site/src/content/docs/working-with-your-agent.mdx` has a section titled
"What you'll never have to type."

The gap is that the intent is asserted in prose and only partly true in
mechanism. Closing that gap is the first-order goal of this brief, and every
other problem below is either a cause of it or a symptom of it. Where an earlier
draft of this brief proposed developer-facing conveniences, treat those as
superseded: a new command is not an affordance for a human, it is a capability
an agent must invoke unprompted at the right moment.

The accountable owner's experience of using CoDev is that it is "sometimes too
rigid, then it goes off the rails, and then it works quite good." That sentence
is this brief's primary evidence. Seven findings explain it, ordered by how
directly they block the aim above.

### The CLI is not yet a complete agent surface

An agent driving CoDev has to read English sentences to obtain values it must
feed straight back into the next command. Of roughly forty leaf commands in
`src/codev_workflow/cli.py`, eight accept `--json`: `status`, `adapter list`,
`adapter verify`, `config get`, `config list`, `task check`, `task status`, and
`task size`.

The `git` group — the group an agent is *required* to use, because raw `git
commit`, `git push`, and `gh pr create` are denied to every role — emits no
machine-readable output at all. `codev git commit` prints `Committed <sha> on
<id>'s branch`. The agent's very next obligation is `codev task check --id <id>
--head <sha>`, so the head commit either gets scraped out of that sentence or
re-derived with a raw `git rev-parse` the guarded surface was built to avoid.
`codev git restack` prints its new head the same way. `codev task log`, the
item's whole history, is prose only.

Two further carve-outs assume a human at a keyboard. `codev codeowners init` is
documented as "human-run directly, never agent-invoked"
(`docs/product-map.md:83`, `docs/cli-reference.md:120`, and the parser's own help
string at `cli.py:404`). `codev init` is genuinely a bootstrap exception — no
agent session exists before the bundle is installed — but nothing distinguishes
the two cases for a reader, so both read as "sometimes you do run commands."

### The agent responds; it does not guide

Nothing obliges the agent to tell a developer where they are and what it
recommends next. `.codev/for-ai/ai-agent-guidelines.md`'s interaction contract
asks it to "state the current step and why it matters" and to "recommend a path
or a default," which is close, but both fire only once the agent is already
acting on a request. There is no obligation to volunteer a recommendation at a
phase boundary, and nothing mechanizes one.

The consequence is that the developer supplies the workflow knowledge. They have
to know that a draft pull request means outer-loop review comes next, that
outer-loop review is a separate session they must start, that a blocking finding
needs triage before anything else can happen, and that a merged slice means the
next slice can begin. Every one of those facts is already computable from
`task.check`'s exit code and the pull-request state. None of them is offered.

That is the mechanism behind "sometimes too rigid, then it goes off the rails."
The tool holds the state and the rules; the developer is asked to hold the
sequence.

### The mental model is documented, not embodied

The phase spine — Specify, Understand, Design, Plan, Build, Review, Ship, Launch
— exists as prose in `docs/product-map.md` and
`.codev/for-ai/ai-agent-guidelines.md`. Behind the conversation sit two
human-startable agents (`orchestrator`, `planner`), a third human-triggered one
(`outer-loop-runner`), fifteen skills, fifty-four argparse parsers, and 26,789
words of instruction shipped inside the bundle.

`task.check` (`src/codev_workflow/task.py:732`) already returns thirteen distinct
outcomes that between them describe every position a task can occupy. Nothing
turns that into an answer to "where am I and what now?" `codev status`
(`cli.py:872`) reports bundle health, adapters, in-progress counts, per-owner
work-in-progress, changed-file overlaps, task sizes, stack depth, and gate
decisions — everything except position in the workflow and the next action.

### Rigidity and drift share one root cause

Inside a task, everything is mechanized: round caps, `stop_drift`,
`stop_repeated_finding`, `stop_scope_expansion`, the coverage manifest, and
`ok_outer_loop_needs_reopen`'s demand for an explicit `codev task reopen`. That
is where the tool feels rigid.

Outside a task, nothing is mechanized: choosing a skill, deciding whether a
change needs a design, drawing slice boundaries, and handing a ready task from
`planner` to `orchestrator` are left to an agent improvising from a 2,800-word
contract. That is where the tool goes off the rails.

Every part of the workflow that "works quite good" is a part where a `codev` exit
code, not prose, made the decision. Treat that correlation as the design
principle this brief follows: **anything the agent must get right should be a
value it reads, not a paragraph it interprets.**

### The workflow is a relay of cold sessions

`planner` produces a ready task, the human starts a fresh `orchestrator` session,
`orchestrator` opens a draft pull request, and the human starts a fresh
`outer-loop-runner` session. Three cold starts, each re-reading the same
contract, and each requiring the developer to know that the handoff is theirs to
perform.

ADR-0024 made the `planner`/`orchestrator` split deliberate, and the underlying
authority boundary is real and worth keeping. The session boundary is an
implementation detail that leaked into the developer's job: `planner` must not
implement product code, but that is enforceable through tool permissions, not by
making the developer notice a transition and restate their intent.

### Opinionation exists on one platform only

The three hooks in `.claude/hooks/` — `require_plan.py`, `require_wave_shape.py`,
`require_small_change.py` — are the mechanism that makes CoDev opinionated rather
than merely advisory. They are Claude Code-only standalone scripts that duplicate
logic `codev` should own, and by design never import `codev_workflow`
(`src/codev_workflow/hook_log.py`'s module docstring records why). Every other
adapter gets the prose version of the same rules, which means every other adapter
gets the version that can be talked out of.

### The documentation site leads with the CLI, not the conversation

The Astro site at `docs-site/` totals 12,648 words across sixteen pages, and its
framing of the agent-driven model is accurate where it appears. Four structural
problems work against it.

- **The mental-model page is orphaned.** `onboarding-guide.md` is the longest page
  at 1,734 words and holds exactly what a reader needs first — "The mental
  model", "Who does what", "Review, in practice", "Where it breaks down". It has
  no sidebar entry in `docs-site/astro.config.mjs`. Eight pages link to it and all
  four tutorials assume it has been read, but a reader browsing the sidebar cannot
  find it.
- **The Concepts page is a command list, not a model.** At 386 words it is among
  the shortest pages on a site whose central difficulty is an unclear mental
  model. It maps each phase to a CLI command, and thereby equates "Understand"
  with `codev task start` — wrong in a way that matters, since Understand is the
  product and design phase while `task start` is a Build mechanic. It never names
  the agents, never draws the inner and outer loops, and never says who decides
  what.
- **The navigation contradicts the stated model.** "CLI Reference" sits in the
  primary sidebar carrying the version badge, and a "Manual CLI Walkthrough" page
  presents the command sequence, while the page that shows the actual developer
  experience — `working-with-your-agent.mdx`, with its worked dialogue exchanges —
  is a sub-item. Both CLI pages open with an accurate note saying this is what the
  agent runs, not what you type; the information architecture says the opposite.
  The conversational page also covers four exchange moments, not every phase, and
  no page anywhere shows the agent recommending a next step.
- **Whole capabilities are absent.** `lightweight-reviewer` and `code-audit-gate`
  — two agents inside the loop — appear on zero pages. "Slice" appears on zero
  pages despite the slicing work that just landed. "Stack" appears only in the CLI
  reference. The evaluation harness, which `docs/product-map.md` itself calls "one
  of the largest single capabilities in the product," has no dedicated page.

### What already exists, measured against the intended workflow

The workflow this brief aims at is: the developer discusses an idea with the
agent; the agent plans by team size, produces a wave of tasks as GitHub issues
from a fixed template, and stops; a developer picks up their issue and plans an
implementation with the agent; the agent manages git; the plan carries slices;
the developer approves the plan; a builder and reviewer inner loop runs per
slice; the agent opens the pull request; the relevant outer-loop specialists run;
the agent requests a human code review; review comments are addressed through the
inner loop; and after merge the agent continues to the next slice. At every one
of those boundaries the agent says where things stand and what it recommends.

Roughly seventy percent is built. The table below is the honest mapping, with the
"agent-driven" column recording whether the step happens without the developer
knowing a command or a session name.

| Intended step | Current state | Agent-driven |
|---|---|---|
| Discuss idea, plan by team size, wave of tasks | Built: `planner` plus `plan-wave`, team-profile aware and rolling-wave | Yes |
| GitHub issues from a fixed template | Built: `codev git issue-create` and `.github/ISSUE_TEMPLATE/task.md`, already carrying Slices, Containment, Stop-if, acceptance criteria | Yes |
| Developer picks up their assigned issue | Missing: no entry point; ADR-0006 dropped a "next item" command | No |
| Agent manages git, including branch creation | Built: the guarded `codev git` surface | Yes, but the agent parses prose for values it must reuse |
| Implementation plan carries slices | Built: landed with the `small-prs` work | Yes |
| Developer approves the plan | Partial: `orchestrator` step 4 makes approval conditional on risk | Yes |
| Builder and reviewer inner loop per slice | Partial: the loop runs per task, not per slice | Yes |
| Agent opens the pull request | Built: a draft pull request opens at `ok_ready_for_pr` | Yes |
| Outer loop runs the relevant specialists | Missing: a separately human-triggered session, and selection is asked of the developer rather than inferred from the diff | No — the developer must know to start it |
| Agent requests a human code review | Missing: `open_pr` never requests a reviewer | No |
| Developer comments, agent addresses them | Built: ADR-0010's comment-sourced outer-loop entry | Yes |
| Merge, then continue to the next slice | Missing: nothing continues | No |
| A recommendation at every boundary | Missing: nothing obliges or computes one | No |

The missing thirty percent is entirely connective tissue, and every missing row
is a row where the developer has to supply workflow knowledge the tool already
holds.

## Desired outcome

A developer talks to an agent, and the agent runs CoDev. At every phase boundary
the agent states where the work stands, recommends the next step, and says why —
without being asked, and without the developer learning a command, a session
name, or a state machine. CoDev's opinions are enforced by exit codes on every
platform rather than by prose on one. Five moves carry that, ordered by
dependency.

**The CLI becomes a complete agent surface.** Every command an agent must invoke
emits machine-readable output for every value the agent will need next,
`--json` included on the whole `git` group. No agent parses an English sentence
to learn a commit sha. The human-run carve-outs are re-examined: `codev
codeowners init` gains an agent-invocable form under the ordinary confirmation
posture, and `codev init` is documented explicitly as the single bootstrap
exception rather than as one of several.

**A state oracle the agent consults, not a command the developer types.** `codev
next --json` reports the current branch, task state, `task.check`'s exit code,
pull-request state, review state, and the recommended next action with its
reason. The agent calls it at the start of every turn and after every state
change, then renders it as one plain-language recommendation. This needs no new
state: the thirteen `task.check` outcomes already are the routing table. ADR-0006
rejected a *shelf* of available work, which is a different object from a position
oracle, so that rejection does not bind this. A developer-facing form exists only
for debugging and CI, and the documentation says so.

**Guidance becomes an obligation, not a courtesy.**
`.codev/for-ai/ai-agent-guidelines.md`'s interaction contract gains a rule that
the agent opens every phase boundary with position, recommendation, and reason,
sourced from the oracle rather than from its own judgment. Because the
recommendation is computed, it is consistent across adapters and across sessions,
and it is testable.

**The slice becomes the first-class citizen, and the task becomes its
container.** Today `task -> branch -> pull request` is hardcoded, and a stack is
N hand-created task ids related after the fact by `--stack-on`, so the slice list
in a plan and the tasks in the state machine are different objects a human
translates between. The correct model inverts that. A **slice** is the unit that
executes: it owns a branch, a builder-and-reviewer round state, a size budget, a
work style, and one pull request. A **task** owns nothing that executes — it is
the higher-level collection its slices belong to, holding the GitHub issue, the
acceptance criteria, the owner and independent reviewer, and the ordered slice
list. A change that genuinely fits in one pull request is a task with exactly one
slice, which is the degenerate case rather than the normal shape. After this
change, "continue to the next slice" is a state transition inside one task that
the oracle can recommend, not a new conversation the developer must start.

**Gate logic moves into `codev`, and the three sessions collapse into one run.**
A `codev gate check` subcommand owns the gate decisions and each platform's hook
becomes a three-line forwarder, so opinionation becomes a property of CoDev. The
authority checkpoints stay exactly where they are; the cold restarts do not,
because a session boundary the developer has to notice is a command by another
name.

Alongside these, the documentation site is restructured so the conversation is
the primary path and the CLI is reference material for debugging: the mental
model is the first thing a browsing reader finds, the loop is drawn rather than
described, the worked dialogue covers every phase including the agent's
recommendations, and every agent and major capability has a page.

## Success measures

- A developer completes a full task — issue to merged pull request — having typed
  no `codev` command other than the one-time `codev init`, verified by replaying
  a recorded session and counting developer-issued commands.
- At every phase boundary in that session, the agent volunteered position,
  recommendation, and reason before the developer asked.
- Every value an agent consumes from a prior `codev` invocation is available as a
  JSON field; no agent instruction in the bundle tells an agent to read a value
  out of prose or to fall back to raw `git`.
- `codev next --json` returns a correct recommendation for every one of
  `task.check`'s thirteen outcomes, plus the no-task, no-branch, and
  merged-slice-remaining cases.
- A developer who has read only the site's mental-model page can state which
  phase their task is in and what the agent will recommend next.
- An accepted three-slice implementation plan produces one task holding three
  stacked slices, each with its own branch and pull request, without a developer
  creating an identifier by hand — and the task's issue closes only when the last
  slice merges.
- A pull request cannot reach an approved state without a recorded approving
  review from a human who is neither the task owner nor a bot.
- Every gate currently enforced by a Claude Code hook produces the same decision
  on every other adapter, verified by exercising `codev gate check` directly.
- Every agent named in `docs/product-map.md`'s agent table, and the evaluation
  harness, has a documentation-site page reachable from the sidebar.

## Essential scenarios

- A developer returns after a week and says "where are we?" The agent, having
  consulted the oracle, replies that task `auth-rotation-2` is in the outer phase
  with two blocking findings awaiting triage, recommends triaging them now,
  explains that nothing can proceed until they are addressed or deferred with a
  reason, and asks the one question that unblocks it. The developer types no
  command.
- A developer accepts a plan containing three slices. The agent creates one task
  holding three stacked slices, builds and reviews the first, opens its pull
  request, and says what it recommends next. After the first merges, the agent
  proposes starting the second without the developer restating anything, and the
  task stays open until the third lands.
- A pull request reaches human review. GitHub shows a review request against the
  CODEOWNERS owner for the touched paths, who is not the developer who directed
  the change, and the body distinguishes the five specialists' machine evidence
  from that human's approval.
- A developer marks the token-rotation slice as pair work when approving the plan.
  When the loop reaches it the agent does not dispatch `builder`; it works with
  the developer directly, and records the same rounds and evidence as a delegated
  slice.
- An agent midway through a delegated build reaches a path the team declared
  critical. The gate stops with an ask, the agent explains why in plain language,
  and the loop drops to pair mode for the rest of that round — without the
  developer having been watching.
- A developer interrupts a running build, works by hand for twenty minutes, and
  returns. The agent recognizes the state, absorbs the hand-written work into the
  task's round state, and reports what it did, rather than the next check
  reporting `stop_drift`.
- A prospective adopter lands on the site's home page and reaches a correct model
  of the loop, the roles, and the review layers within one page and one diagram,
  seeing a conversation before seeing a command.

## Open questions carried into design

Two questions are genuinely unresolved and are the reason this brief stops short
of a complete design. Both have a recommended answer; neither is accepted.

### How a second independent reviewer fits

Google's model separates three approvals that are easy to conflate:

- **LGTM** — a competent engineer read the change and believes it is correct.
- **OWNERS approval** — an engineer accountable for that directory consents to
  the change landing there. Path-scoped and hierarchical; `.github/CODEOWNERS` is
  the approximation available on GitHub.
- **Readability** — a language-level certification. If the author does not hold it
  for the language, someone who does must sign off.

One person may supply all three, but the roles stay distinct, and an author never
approves their own change. The insight that matters: the second reviewer is not a
second opinion on correctness. LGTM says "this is right." OWNERS says "I will own
this."

The first consequence for CoDev is a naming problem with real teeth. The five
specialist reviewers are a presubmit, not a reviewer; they produce machine
evidence. `codev task check` returns `ok_approve` once they are satisfied, which
is a dangerous name in a tool whose pitch is that generated code is not merged as
slop.

The second consequence is the trap AI-heavy teams fall into. Because the AI wrote
the code, the developer who directed it feels like the reviewer. They are not.
They are the author. Their signature means "I directed this change and I own it,"
not "I approved it."

CoDev holds both pieces and wires neither. `codev codeowners init` scaffolds a
CODEOWNERS file nothing later consumes; CODEOWNERS is read only to suggest an
issue assignee (`src/codev_workflow/git_ops.py:300`), never to request a
pull-request reviewer. `plan-wave` names an independent reviewer per task in the
wave plan's prose, and that name never reaches GitHub.

Recommended answer for a team of two to ten:

- One required approval from a CODEOWNERS owner for the touched paths, who is not
  the task owner.
- The task owner signs a separate, explicitly worded ownership statement that
  `codev git mark-ready` writes into the pull-request body. Different signature,
  different meaning.
- Two approvals only for changes labelled `risk:high` or `risk:critical` — labels
  the issue template already defines — or for a designated sensitive path set.
  Requiring two everywhere will not survive contact with a team of eight, and
  Google does not require it either.
- Specialist output stays in the pull-request body as clearly labelled machine
  evidence and never counts toward an approval.
- `ok_approve` is renamed to something honest, and a distinct `ok_human_approved`
  reads GitHub's actual review state — which the oracle then reports, so the agent
  can tell the developer plainly that the machine gates are green and a human
  approval is still outstanding.

The machine readability analogue is `code-audit-gate` and the
`audit-google-*-style` skills, a reasonable mechanical style gate. The human
judgment about whether code is idiomatic and maintainable for this team belongs
to the independent reviewer, and should be stated as their expectation rather
than assumed covered by the audit gate.

### How the automated loop yields to tandem work

Two findings say this was designed and never mechanized. The focus card in
`.codev/for-ai/ai-agent-guidelines.md` already carries a **Work style: `Pair` |
`Bounded delegate`** field; it is chosen once, expressed only in prose, and
`task.py` has no representation of it. Separately, `VALID_ESCALATION_TRIGGERS`
includes `critical_interrupt` (`src/codev_workflow/task.py:87`), a vocabulary word
with no producer anywhere in the codebase — only `tests/test_task.py` references
it.

Recommended answer, in three levels, cheapest first:

**Work style becomes a task field with per-slice granularity.** `codev task start
--style pair|delegate`, carried per slice in the implementation plan. A developer
approving a plan marks the token-rotation slice as pair work — in conversation,
not by typing the flag. When the loop reaches that slice, `orchestrator` does not
dispatch `builder`; it stays in the developer's session. One field and one branch
in the protocol, and it covers the planned case, which is most of them.

**Path-based tripwires cover the unplanned case.** An intervention mechanism that
requires the developer to be watching will not work, because they are not
watching. A `review.pair_paths` setting makes "critical to my judgment" a declared
property of the code rather than a real-time decision. When a builder's scope
reaches such a path, the gate stops with the ask-posture ADR-0030 already
established, the agent explains why, and the loop drops to pair mode for the rest
of that round.

**`critical_interrupt` gets a producer, and the Ctrl-C hole is closed.** Today,
interrupting a running build leaves files edited, nothing committed, nothing
recorded, and the next `codev task check` reporting `stop_drift`. That is a
defect in the tandem story, not a missing feature. The shape is a pause that
records the partial head and a resume that re-enters in pair mode. `task.reopen`
already performs the mechanical part — it re-baselines onto a head and opens a
fresh empty round — and needs the agent to recognize the situation and offer it,
rather than a developer knowing to ask.

The framing that decides the design: pair mode is not an escape hatch from the
loop, it is a work style the loop supports. The same rounds are recorded, the same
reviewer runs, and the same evidence lands in the pull request; the only
difference is whose hands are on the keyboard. If pair mode falls outside the
state machine, half the work carries no record, which reproduces exactly the
"sometimes it works, sometimes it goes off the rails" experience this brief
exists to fix.

## First release

The work below is sequenced as a stack of small pull requests, each independently
useful and reviewable on its own. The first two are ordered first because every
later item depends on an agent being able to read state rather than parse it.

### Now

1. **Complete the agent surface.** `--json` across the `git` group and the
   remaining `task` verbs, covering every value an agent must reuse; an
   agent-invocable form of `codev codeowners init`; and one documented bootstrap
   exception rather than an unexplained set of human-run commands.
2. **`codev next --json`**, the state oracle: a pure read over branch, task state,
   `task.check` exit code, and pull-request and review state, returning the
   recommended next action and its reason. No schema change.
3. **The guidance obligation.** The interaction contract requires position,
   recommendation, and reason at every phase boundary, sourced from the oracle;
   `orchestrator`, `planner`, and `outer-loop-runner` are updated to consult it at
   the start of every turn and after every state change.
4. **The slice becomes the unit of execution.** Round state, the guarded git
   surface, and the size budget move from the task to the slice; a task becomes
   the ordered collection its slices belong to. An accepted plan's slice list
   generates that collection directly, reusing the stacking machinery ADR-0034
   accepted, with a one-slice task as the compatible degenerate case.
5. **The human review gate.** CODEOWNERS-driven reviewer request at `codev git
   mark-ready`, the ownership statement in the pull-request body, the honest rename
   of `ok_approve`, and `ok_human_approved` reading GitHub's review state.
6. **Work style as a per-slice task field**, with `orchestrator` honoring it.
7. **Pair paths, pause and resume, and a producer for `critical_interrupt`.**
8. **`codev gate check`**, with the three Claude Code hooks reduced to shims and
   the same gates available to every adapter.
9. **The documentation-site restructure.** Promote the mental model to a sidebar
   entry and the first home-page card; make the conversational page the primary
   path and the CLI pages reference material; rewrite Concepts as a model with the
   inner and outer loops drawn; extend the worked dialogue to every phase,
   including the agent's recommendations; add a roles page covering every agent,
   including `lightweight-reviewer` and `code-audit-gate`; add pages for slicing
   and stacking and for the evaluation harness; align the site's vocabulary with
   `docs/product-map.md`'s terminology table.

### Next

- Automatic specialist selection inferred from the diff's shape, replacing the
  question `outer-loop-runner` currently asks, with the developer's override
  preserved.
- Collapsing the three entry-point sessions into one continuous run with the
  authority checkpoints intact, once the oracle makes the handoffs computable.
- Continuous progression to the next slice after a merge, once the oracle and the
  slice-as-unit change have both landed.
- Shrinking `.codev/for-ai/ai-agent-guidelines.md`. It performs three jobs at once
  — mental model, interaction contract, and protocol specification — and every
  numbered protocol step in it is duplicated in
  `bundle/.claude/agents/orchestrator.md`, which is two places to drift. The
  protocol belongs in exit codes and error messages, where `task.check` already
  puts it. The document should shrink to what genuinely cannot be mechanized,
  which after the oracle lands is considerably less than today.

### Not planned

- Removing the human authority boundaries. Merge, deployment, migration,
  publication, and rollout expansion stay human decisions; this brief moves
  session boundaries and command invocation, never authority.
- Replacing GitHub Issues with a CoDev-native work tracker. ADR-0006's reasoning
  stands.
- Integration with an external stacking tool, per
  `docs/features/small-prs/design.md`'s recorded non-goal.
- Making the five specialists count as a review approval under any configuration.
- Removing the CLI reference documentation. The CLI stays fully documented for
  debugging, CI, and recovery; it stops being the primary path.

## Constraints

- Additive changes to the round-state schema only. ADR-0001's decision to track
  state as local JSON files stands, and `task.check`'s convergence semantics stay
  as they are except where this brief names an explicit change.
- Machine-readable output is additive. Existing human-readable output stays
  byte-compatible unless `--json` is passed, so recovery and CI use keep working.
- Every new gate asks and pauses rather than refusing, matching ADR-0030's
  accepted posture.
- Target repositories acquire no runtime dependency on CoDev.
- An adopter who never uses the oracle, slices, or pair mode keeps today's
  behavior unchanged.
- The documentation site stays a Starlight site deployed to GitHub Pages under the
  `/CoDev` base path; this brief changes content and navigation, not platform.

## Assumptions and discovery

Martin Urban owns every assumption below as the accountable human.

| Assumption | Evidence needed | Decision point |
|---|---|---|
| The oracle needs no new state beyond `task.check`, pull-request, and review state | Enumerate each outcome against a concrete recommendation, including the no-task, no-branch, and merged-slice-remaining cases | Before the oracle is designed |
| No agent instruction in the bundle currently depends on parsing human-readable CLI output in a way `--json` cannot replace | Audit every `codev` invocation named in the bundle's agent and skill files against the value it consumes next | Alongside item 1 in "Now" |
| A computed recommendation improves the developer experience rather than adding noise the agent must suppress | Run one real task end to end with the oracle stubbed by hand and judge whether each boundary recommendation was worth stating | Before item 3 in "Now" |
| GitHub's review API exposes enough to distinguish an author's own approval from an independent one on every plan tier | Confirm against the `gh` CLI on a real repository | Before the human review gate is designed |
| Every existing single-pull-request task can be read as a task holding exactly one slice, with no round-state migration beyond a defaulted field | Replay the recorded round state of a closed task under the slice-scoped reader | Before item 4 in "Now" |
| Collapsing the three sessions preserves ADR-0024's guarantee that `planner` never implements | Confirm tool-permission enforcement is equivalent to session separation on each adapter | Before the session collapse is designed |
| Readers stall on the current site because the mental model is unreachable and the navigation leads with the CLI, not because the model is unwritten | Have two engineers unfamiliar with CoDev browse the site and state the model back | Before the site restructure |

## Acceptance

- [x] Outcome, scope, non-goals, and success measures accepted by the accountable
      human on 2026-09-02.
- [x] [ADR-0035](../../adr/0035-slice-is-the-unit-of-execution.md) — the slice is
      the unit of execution and a task is the collection its slices belong to.
- [x] [ADR-0036](../../adr/0036-cli-is-an-agent-interface.md) — the `codev` CLI is
      an agent interface with one documented bootstrap exception, and
      phase-boundary guidance is computed rather than conventional.
- [x] [ADR-0037](../../adr/0037-human-review-and-ownership-gate.md) — the human
      review and ownership gate.
- [x] [ADR-0038](../../adr/0038-work-style-is-a-slice-property.md) — work style is
      a first-class property of a slice.
