# Developer Experience - Implementation Plan

**Status:** Accepted 2026-09-02 by Martin Urban
**Owner:** Martin Urban
**Author:** Claude Opus 5 (drafted; not an approval)
**Predecessor:** [docs/plans/unified-workflow-implementation.md](unified-workflow-implementation.md)
**Base commit:** `90cf9f4`
**Target version:** 0.6.0 (breaking; see "Version and release")
**Delivery shape:** one pull request, by explicit owner consent (see "Why one
pull request")
**Risk:** high overall. Two work packages are individually high and are named
as such below.

## Context

The unified-workflow plan delivered eight of its nine "Now" items. What it did
not deliver is one clause of item 8, and that clause is the one the brief
itself identified as the developer-experience defect:

> Gate logic moves into `codev`, **and the three sessions collapse into one
> run** ... because a session boundary the developer has to notice is a command
> by another name.
> -- [unified-workflow/brief.md:260](../features/unified-workflow/brief.md)

The gate half shipped in `57bde9c`. The session-collapse half did not, and
[.claude/CLAUDE.md:17](../../.claude/CLAUDE.md) still instructs the opposite:
"they are separate, human-started entry points by design; do not chain from
one into the other yourself."

That is the visible half of the problem. The larger half is structural, and no
prior document has stated it: **CoDev has two users, and only one of them has
been designed for.** The state oracle and the guidance obligation gave the
*developer* a good surface -- position, recommendation, and reason, volunteered
at every phase boundary. The *agent's* surface was never given the same
treatment, and the agent's experience is the developer's experience, because
every mis-sequenced call surfaces as the tool fighting them.

The evidence is in the role files. `orchestrator`'s step 5
([.claude/agents/orchestrator.md:80](../../.claude/agents/orchestrator.md)) is
one paragraph containing six commands, four conditional flags, an
issue-existence check, three mutually exclusive linkage options, a
`--body-file` versus `--body` shell-escaping caveat, and a recovery path via
`codev task relink`. That is not an interface. It is a manual an LLM is asked
to hold in working memory across a long session, and holding it is exactly
where "goes off the rails" comes from.

ADR-0036 established that the CLI is an agent interface. This plan finishes
that thought: an interface whose correct use requires a twenty-five-line
protocol is not an interface, it is a procedure. This plan turns the procedures
into verbs.

## What this plan changes, in one paragraph

The `oracle` is renamed to a name a working engineer can guess, and taught to
answer for the whole lifecycle rather than only the part after a task exists.
Its blocked answers become structured choices instead of dead ends. The
multi-command procedures in the role files become single composite `codev`
verbs. The plan gate stops asking about changes that are small and low-risk.
And `orchestrator`, `planner`, and `outer-loop-runner` stop being three
human-started sessions: one **lead agent** is the only agent a developer talks
to, and it dispatches the rest.

## Why one pull request

CoDev's own discipline is small stacked slices, and this plan violates it. The
owner consented to that explicitly, and the reason is real rather than
convenience: work packages 1 and 5 are a rename and a role restructure that
touch nearly every file the other packages also touch. Split across pull
requests they would produce three or four consecutive merge conflicts against
each other and a repository that is internally inconsistent between merges --
role files naming a module that no longer exists, or a lead agent invoking
verbs not yet added.

Two obligations follow from taking the exemption:

- **The pull request is ordered so a reviewer can read it in passes.** The work
  packages below are commit boundaries, not just headings. A reviewer reads
  package 2 without needing package 5.
- **The size budget is not silently waived.** `codev task size` will exceed
  `review.max_lines` by roughly a factor of five. That is recorded in the pull
  request body as a deliberate, owner-authorized deviation with this
  document's link, not passed over.

Estimated total: 2,500-3,500 changed lines including tests and documentation.

---

# Work package 1 - Rename the oracle

**Risk:** low. Mechanical, fully covered by existing tests.
**Blocks:** every later package, which is why it is first.

## Focus card

- **Change:** `src/codev_workflow/oracle.py` and the vocabulary around it take
  a name drawn from ordinary software-engineering usage.
- **Success:** No module, symbol, document, or role file uses the word
  "oracle"; `codev next` behaves identically; every existing `test_oracle.py`
  case passes under the new name.
- **Non-goals:** Any behavior change. This package is a rename and nothing
  else, so the packages after it are readable as behavior diffs.
- **Allowed scope:** `src/codev_workflow/oracle.py` (renamed),
  `src/codev_workflow/cli.py`, `tests/test_oracle.py` (renamed),
  `docs/`, `docs-site/src/content/docs/`, both adapter bundles.
- **Validation:** `.tools/just ci`; `grep -ri oracle` across the repository
  returns only ADR-0036's historical text, which is append-only and stays.
- **Work style:** Bounded delegate.

## The name

**Accepted 2026-09-02: `navigator.py`, "the navigator."**

The driver/navigator pair is the most established metaphor in software
engineering for precisely this division of labor: one party has hands on the
keyboard, the other says where the work stands and what comes next. CoDev
already ships pair work as a first-class slice property (ADR-0038), and in that
mode the alignment is literal rather than decorative -- the developer drives and
the agent navigates. "Consult the navigator" needs no gloss; "consult the
oracle" invites the reading that the answer is unexplained, which is the exact
opposite of what a module that returns a `reason` field with every answer is
for.

Alternatives considered and rejected:

- **`guidance.py`, "the guidance engine."** Conservative, and continuous with
  the brief's existing "guidance obligation" vocabulary. Weaker as a noun: an
  agent consults a navigator, but it merely reads guidance.
- **`workflow.py`, "the workflow resolver."** Accurate and dull. Risks
  collision with the package name `codev_workflow`, which is the reason it is
  third rather than second.

The name is settled, so nothing downstream is blocked on it. It is recorded
here rather than only in an ADR because every later package spells it.

## Repository evidence

- `src/codev_workflow/oracle.py` (13 KB): `NextAction`, `next_action`,
  `_BY_CHECK_REASON`, `_github_position`, `_open_pull_request_position`,
  `_task_id_for_branch`.
- `src/codev_workflow/cli.py:410` registers `next_parser`; `cli.py:1343` calls
  `oracle_module.next_action`. The public command name `codev next` does not
  change.
- Six role files and `.codev/for-ai/ai-agent-guidelines.md:201` name
  `codev next --json`; none name the module, so the role-file cost is limited
  to prose that calls it "the oracle."
- `docs/adr/0036-cli-is-an-agent-interface.md` uses the word throughout. ADRs
  are append-only (ADR-0025); it is not edited. The new ADR in package 5
  carries the forward pointer.

---

# Work package 2 - Composite lifecycle verbs

**Risk:** normal. Additive; the granular verbs it composes are untouched.

## Focus card

- **Change:** Every multi-command procedure currently written in prose in a
  role file becomes one `codev` verb that performs the whole intent and returns
  every value the next step consumes.
- **Success:** No role file contains a numbered step that issues more than one
  `codev` command; the `--body-file` shell-escaping caveat is deleted rather
  than reworded, because no body passes through a shell any more.
- **Non-goals:** Removing or changing any existing verb. Agents mid-session,
  other adapters, and recovery paths depend on the granular surface, and the
  composite verbs are thin compositions over the same functions, not
  reimplementations.
- **Allowed scope:** `src/codev_workflow/cli.py`, `git_ops.py`, `task.py`
  (composition only -- no new state semantics), `tests/test_cli.py`,
  `tests/test_git_ops.py`, `tests/test_integration_lifecycle.py`,
  `docs/cli-reference.md`.
- **Validation:** `.tools/just ci`; every new verb has an integration test in
  `test_integration_lifecycle.py` driving real git, matching the tier added in
  `8df4eb4`.
- **Stop if:** any composite verb needs logic that does not already exist in
  `git_ops` or `task`. That would mean it is a new capability wearing a
  convenience verb's clothes, and it belongs in its own package.
- **Work style:** Bounded delegate.

## The verbs

| New verb | Replaces | Returns |
|---|---|---|
| `codev slice begin --plan <path> [--task <id>]` | `orchestrator` step 5: `codev git branch`, the issue-existence check, `codev git issue-create`, `codev task start` with three mutually exclusive linkage flags, `--description`, and the `codev task relink` recovery path | task id, slice id, branch, base sha, issue number and URL, round number |
| `codev round close --role <role> --evidence <file> [--message <text>]` | `orchestrator` step 6: `codev git commit --id --message --round --evidence`, plus reading `head` out of `--json` to carry into step 9 | head, round number, slice id |
| `codev slice publish` | `orchestrator` step 9's `ok_ready_for_pr` arm: `codev git push` then `codev git open-pr --title`, plus the "never pass `--body`" caveat | pull request number and URL, head, draft state |
| `codev slice land` | `orchestrator` step 10 and the navigator's merged-slice arm: `codev task advance-slice` or `codev task close`, chosen from whether a later slice exists | outcome, next slice id or closed status |
| `codev issue draft --from <artifact>` | `planner`'s issue-only short circuit, including the `--body-file` versus `--body` caveat | issue number and URL |

Every verb takes `--json` and emits it by default when stdout is not a
terminal, per ADR-0036.

**`codev round close`, not `codev round record`.** The verb is named for its
caller, not its subject. `orchestrator` step 6 is explicit that the builder
must never record its own evidence -- "without commit permission it cannot know
that head in advance" -- and a verb spelled `record --role builder` invites
precisely the call the design forbids. `close` says that the round is being
sealed by whoever owns commit permission, which is the lead and only the
lead.

## Repository evidence

- `orchestrator.md` steps 5, 6, 9, and 10 are the source of the first four
  rows; `planner.md`'s "Issue-only short circuit" is the source of the fifth.
- `git_ops.py` already holds every value these verbs return: `create_branch`
  (543), `commit` (873), `push` (904), `open_pr` (953), `mark_ready` (1020),
  `restack` (1034).
- `task.py` already holds the state transitions: `start` (308), `advance_slice`
  (1319), `current_slice` (1446), `describe` (1281).
- The `--body-file` caveat appears in **two** role files
  (`orchestrator.md:83`, `planner.md`), which is the clearest single argument
  for this package: a caveat documented twice is a missing verb.

---

# Work package 3 - The navigator answers for the whole lifecycle

**Risk:** normal.

## Focus card

- **Change:** The navigator gains positions for the phases before a task
  exists, and every blocked position carries structured options instead of a
  single escalation command.
- **Success:** A developer on a clean `main` with an idea and no artifacts gets
  a real recommendation; each of the four `stop_*` outcomes plus
  `ok_waiting_on_triage` and `ok_blocked_missing_evidence` returns at least two
  options with consequences.
- **Non-goals:** Changing any `task.check` outcome, or having the navigator
  write state. It stays a pure read.
- **Allowed scope:** the renamed navigator module, `cli.py`,
  `tests/test_oracle.py` (renamed), `docs/cli-reference.md`.
- **Validation:** `.tools/just ci`; a test per new position; the existing
  thirteen-outcome coverage test extended rather than replaced.
- **Work style:** Bounded delegate.

## Part A - The planning phases

Today the navigator collapses the entire Understand, Design, and Plan half of
the workflow into one sentence. `oracle.py:184-195` returns "pick up an issue
and start a task" for every state in which no task branch exists. That means
the developer's hardest moment -- *"I have an idea, now what?"* -- receives the
least guidance in the system, and it is the moment the guidance obligation was
written for.

New positions, resolved by reading artifacts that already exist:

| Position | Condition | Recommendation |
|---|---|---|
| no product frame | no `SPECIFICATION.md`, no accepted brief, and the repository has no `docs/codev/brief/` | `specify-project` for greenfield, `define-product` for an addition |
| brief accepted, no design | an accepted brief exists with no matching `design.md` | `design-solution` |
| design accepted, no wave plan | accepted design, and the team profile names more than one developer | `plan-wave` |
| plan accepted, no task | an accepted plan with a slice list, and no branch for it | `codev slice begin` |
| plan drafted, not accepted | a plan whose `Status:` line does not read `Accepted` | present it for the owner's decision |

**How acceptance is read.** Every planning artifact in this repository carries
a `**Status:**` line in its first ten lines -- `docs/plans/*.md` and
`docs/adr/*.md` both do, consistently, and `gate.py`'s `_SPEC_GLOBS` already
encodes where these artifacts live. The navigator reads that line. No new
metadata format, no front matter, no schema: the convention exists and is
already load-bearing for the gate.

## Part C - A merged pull request stops being reported as unopened

`_github_position` is consulted only when `task.check` returns
`ok_machine_review_complete` or its deferrals variant. Every other reason
skips GitHub entirely, so a slice sitting at `ok_ready_for_pr` is told to open
a pull request no matter what GitHub actually holds -- including when the pull
request is already open, already merged, or closed.

This was found in use rather than by reading: on `main`, immediately after the
coverage measure's own pull request merged, `codev next` still recommended
"open the pull request". It is the mechanism behind the `dispatch_specialists`
row of the recorded baseline.

The fix is to consult GitHub for any position where a pull request could
exist, not only the two reasons that happen to imply human review. It stays
cheap: `pull_request_state` already returns `None` when GitHub cannot answer,
and the caller already falls back to the local recommendation rather than
reporting a guess as fact.

## Part B - Blocked becomes a choice

`NextAction` gains an `options` list. Each option carries `label`, `command`,
and `consequence`. `blocked` stays exactly as it is -- it is part of the machine
contract under ADR-0036 and something reads it -- but a blocked answer stops
being a wall.

Concretely, `stop_repeated_finding` today returns "escalate: a finding
repeated" and one escalate command. It will additionally carry the finding
itself, its location, and three options: address it with a differently scoped
builder brief, defer it with a recorded reason, or escalate. The developer sees
a decision. The authority model is unchanged -- every option is still something
a human chooses.

---

# Work package 4 - The plan gate is risk-tiered

**Risk:** high. This package deliberately weakens a guardrail, and is the one
most likely to be judged wrong in review.

## Focus card

- **Change:** The plan gate stops asking when the change on the branch is
  within the size budget and touches no sensitive path. The focus card in the
  conversation satisfies it; no `implementation-plan.md` file is required.
- **Success:** A one-file bug fix on a task branch proceeds without a gate
  prompt; a change that grows past `review.max_lines` or touches a declared
  sensitive path still asks, on the first edit after it crosses.
- **Non-goals:** A configuration option. CoDev's stated posture is to pick the
  default and say why, not to add a knob -- so this ships as a changed default
  with no new key in `config.DEFAULTS`.
- **Allowed scope:** `src/codev_workflow/gate.py`, `tests/test_gate.py`,
  `tests/test_claude_hook.py`, `tests/test_small_change_hook.py`,
  `docs/architecture.md`, `docs/features/claude-code/design.md`'s "Guardrail
  Design" section.
- **Validation:** `.tools/just ci`. Every existing gate test that asserts an
  `ask` must be re-examined individually and either kept with a case that still
  qualifies, or converted with the reason recorded in the test name -- a test
  that flips to `allow` incidentally is a regression wearing a passing suite.
- **Stop if:** the risk signal cannot be computed without a network call or
  without writing state. The gate must stay fast and pure.
- **Work style:** Pair. This is the judgment call in the plan and should not be
  delegated.

## The design insight that makes this safe

The gate fires *before* an edit, so the only diff it can see is the one already
accumulated on the branch. That initially reads as a flaw -- the first edit on a
fresh branch is trivially within budget, so the gate would always allow it.

It is actually the correct behavior, and it is why this package is worth doing
rather than merely tolerable. Under the current design the gate interrupts
*before the work starts*, when the developer knows least about what the change
will require. Under the risk-tiered design it interrupts *when the change grows
past what a focus card can carry*, which is the moment a written plan is
genuinely worth its cost. The gate stops being a toll booth and becomes a
tripwire.

## The plan gate does not recognize this repository's own plans

`gate.py`'s `_SPEC_GLOBS` covers `docs/features/*/design.md`,
`docs/codev/features/*/design.md`, and `docs/codev/wave/*.md`. It does not
cover `docs/plans/*.md`, which is where this repository actually keeps every
accepted plan -- including the two that authorize this work.

The consequence was reproduced live: on the branch that carried an accepted,
committed plan, `codev gate check --gate plan` still answered `ask`, because
neither the precise per-task path nor any glob matched. A guardrail that
cannot see the artifact it asks for teaches agents that the artifact is
pointless.

This is in scope for this package because it is the same decision surface:
the gate is being taught what evidence of planning looks like, and "a plan
document in the repository's plans directory" is evidence it currently
ignores. Widening the globs is not a risk-tiering change and should land even
if the risk-tiering half is dropped.

## Repository evidence

- `gate.py:_SPEC_GLOBS` omits `docs/plans/*.md`; `docs/plans/` holds
  `unified-workflow-implementation.md`, `navigator-coverage-measure.md`, and
  this document.
- `gate.py:_has_precise_task_plan` keys purely on a file existing at
  `docs/codev/task/{task_id}/implementation-plan.md`. Presence of a file is the
  entire test; nothing about the change is consulted.
- `gate.py` already has the machinery for the new signal: the `small-change`
  gate is one of the three in `GATES` and already computes diff size against
  `review.max_lines` and `review.max_files`.
- `config.DEFAULTS` (`config.py:46`) holds `review.max_lines` at 600 and
  `review.max_files` at 12 after `b54331b`. No new key is added.
- Every gate "fails open" already (`gate.py` module docstring, `_degraded`), so
  the failure mode of a miscomputed risk signal is an allow, which is the same
  failure mode the gate has today.

---

# Work package 5 - The lead agent

**Risk:** high. It changes the workflow that builds it and renames the agent
that would run it.

## Focus card

- **Change:** `orchestrator` becomes **`lead`**, the single agent a developer
  talks to. `planner` is removed. `outer-loop-runner` stops being a human entry
  point and becomes a subagent `lead` dispatches.
- **Success:** Exactly one role file on each full adapter declares itself
  human-facing; `lead.md` is at most 80 lines; a developer completes a task from
  idea to merged pull request without being told to start a different session.
- **Non-goals:** Changing any authority checkpoint. Every human decision that
  exists today still exists and still stops the loop -- what changes is that the
  developer is not also asked to perform session routing.
- **Allowed scope:** `.claude/agents/`, `.opencode/agents/`, both bundle
  copies, `.claude/CLAUDE.md`, `.codev/for-ai/ai-agent-guidelines.md`,
  `AGENTS.md`, `src/codev_workflow/installer.py`,
  `src/codev_workflow/adapter.py`, `tests/test_adapter.py`,
  `tests/test_installer.py`.
- **Validation:** `.tools/just ci`; `codev adapter verify` passes on both full
  adapters; `codev init` into a scratch repository produces the new role set
  and no orphaned files.
- **Work style:** Pair for the role-file content, bounded delegate for the
  installer and adapter wiring.

## Why `planner` can dissolve and `outer-loop-runner` cannot

`planner.md` is 56 lines, and roughly forty of them route to skills
(`specify-project`, `define-product`, `design-solution`, `plan-wave`) that
`lead` can invoke directly. Its one piece of unique behavior, the issue-only
short circuit, becomes `codev issue draft` in package 2. There is almost
nothing left to preserve, and after package 3 the navigator does the routing
that `planner`'s "Scope" section does in prose.

`outer-loop-runner.md` is the opposite: it holds real, irreducible protocol --
CI gating, five-specialist dispatch, a second entry mode for acting on existing
review comments, and the coverage-recording rules. Folding that into `lead`
would produce the 250-line role file this whole plan exists to avoid. It stays
its own agent; only its trigger changes, from the developer to `lead`.

Role count goes from thirteen to eleven. Human-facing role count goes from
three to one, which is the number that matters.

## Keeping `lead` thin

The 80-line budget is a validation criterion, not a style note. `orchestrator`
is 167 lines today, and packages 2 and 3 exist precisely to make the reduction
possible: the ten-step build protocol becomes four verbs, and the routing prose
becomes a navigator call.

**If `lead` still exceeds 80 lines, the overflow becomes a `lead-protocol`
skill, not a longer role file.** A skill is loaded when it is needed; a role
file is resident for the whole session and competes for attention with
everything else in context, which is the mechanism this plan is trying to
relieve. Relaxing the budget is not an option, because the budget is the only
thing standing between this plan and a `lead.md` that reproduces
`orchestrator.md` under a new name. Extending packages 2 and 3 is the preferred
remedy; the skill is the bounded fallback when the pull request cannot absorb
more.

## An open decision this surfaces

`planner` runs on `model: opus`; `orchestrator` runs on `model: sonnet`. Today
that split is coherent -- planning judgment gets the stronger model, execution
coordination does not. When `lead` absorbs planning, it inherits both jobs and
one model setting.

**Recommendation: `lead` runs on opus.** It now owns the judgment that
justified `planner`'s setting, and the volume work already lives in `builder`,
`reviewer`, and the five specialists, which stay on their current models. The
cost delta is real but small, because `lead` dispatches rather than implements.

**Decision needed before this package's role files are written.**

## ADRs

This package writes four, or three if the first two are judged one decision:

- **The lead agent is the single human-facing entry point.** Supersedes
  ADR-0024 (`planner` as a primary agent) and narrows ADR-0001's
  "every platform has an `orchestrator`."
- **The navigator rename**, carrying the forward pointer from ADR-0036's
  "oracle" language.
- **Composite lifecycle verbs: the CLI exposes intent, not steps.** Extends
  ADR-0036 rather than superseding it.
- **The plan gate is risk-tiered.** Narrows ADR-0030's guardrail description.

ADR-0030 and ADR-0031 are still `Status: Proposed`. Both should be resolved to
`Accepted` or `Rejected` in this pull request rather than left indefinite while
new ADRs are written on top of them.

---

# Work package 6 - Documentation and release

**Risk:** low, but it is the package most likely to be under-done, so it is
scoped explicitly rather than left as "update the docs."

## Focus card

- **Change:** Every surface that describes the old three-session model
  describes the lead agent; the version becomes 0.6.0.
- **Success:** `tests/test_documentation_links.py` green; no document mentions
  `planner` or `orchestrator` as an entry point; the docs site's roles page
  lists eleven roles with one marked human-facing.
- **Allowed scope:** `CHANGELOG.md`, `pyproject.toml`, `docs/README.md`,
  `docs/architecture.md`, `docs/cli-reference.md`, `docs/product-map.md`,
  `docs/adoption.md`, `docs-site/src/content/docs/` (`roles.md`, `concepts.md`,
  `working-with-your-agent.mdx`, `getting-started.md`, `agent-platforms.md`,
  `workflow-checklist.md`, `starting-prompts.md`, `onboarding-guide.md`,
  `index.mdx`), `README.md`.
- **Work style:** Bounded delegate.

## Version and release

**0.5.0 becomes 0.6.0.** This is a breaking change: role files are renamed and
removed, which breaks any existing installation on `codev init --update`, and
`planner` disappears as an invocable agent. CoDev is pre-1.0, and
`docs/plans/phase-6-cleanup-and-promotion.md` already establishes the reading
that in the 0.x line the *minor* version is the breaking-change boundary. This
follows that precedent rather than reopening it.

The `CHANGELOG.md` `[Unreleased]` section already holds the ADR-0039 and
`review.max_lines` entries; this package adds to it and cuts the release,
rather than starting a new section.

## The version must be able to distinguish two builds

`codev --version` cannot tell a source snapshot from the code it was taken
from. A tool installed from this working tree on 31 August reported `0.5.0`;
`main` reported `0.5.0` three waves of merged work later; and PyPI's latest
release was `0.4.0` the whole time. Nothing in that picture is detectable by
asking any of the three what version it is.

The consequence was not cosmetic. The three Claude Code hooks became shims
calling `codev gate check` in `57bde9c`, the frozen tool had no `gate`
command, and gates fail open by design -- so 496 guardrail decisions were
silently allowed without being checked, and only `452d5e7`'s degraded
reporting made it visible at all.

Two changes, both small and both belonging with the 0.6.0 cut:

- **`codev self update` must not recommend a downgrade.** It prints `uv tool
  upgrade open-codev-workflow` unconditionally, which for a source install
  consults PyPI and finds an older release. It should detect an editable or
  source install and say so instead.
- **A source build must be distinguishable.** Appending the short commit to
  the reported version for a non-release install is enough; the exact
  mechanism is the implementer's call, but "two different trees report the
  same version" must stop being possible.

## The migration note that must not be forgotten

Anyone who has run `codev init` has `orchestrator.md` and `planner.md` on disk.
`codev init --update` must remove them, not merely add `lead.md`, or every
existing installation ends up with four human-facing agents instead of one.
`tests/test_installer.py` needs a case for exactly this: update an installation
made at 0.5.0 and assert the old role files are gone.

---

# Validation, everywhere

- `.tools/just ci` green at every work-package boundary, not only at the end.
- `codev adapter verify` on both full adapters after package 5.
- `codev init` into a scratch repository, and `codev init --update` over a
  0.5.0 installation, after package 6.
- The integration tier added in `8df4eb4` covers each composite verb against
  real git and a real remote.

# The success measure that does not exist yet

The unified-workflow brief's first success measure is *"a developer completes a
full task -- issue to merged pull request -- having typed no `codev` command
other than the one-time `codev init`, verified by replaying a recorded session
and counting developer-issued commands."*

There is no harness for that in `tests/`. Nothing in this plan builds one,
which means this plan's central claim -- that the developer experience improves
-- is asserted rather than measured, exactly as every prior claim about it has
been.

**Accepted 2026-09-02, and landed 2026-09-02 in
[#33](https://github.com/urban233/CoDev/pull/33).** The baseline is recorded at
`90cf9f4`: six of nine walked lifecycle steps uncovered, and all five planning
positions absent. Three of the findings folded into this plan -- in packages 3,
4, and 6 -- were surfaced by building and using it, which is the first evidence
that the measure earns its place.

**The measure as the brief words it cannot be built, and is redefined.**
Replaying "a recorded session" requires a transcript format that does not exist
and would be adapter-specific -- Claude Code's JSONL and OpenCode's are
different shapes -- and it would audit a session that already happened rather
than being a test that runs in CI. The measure is restated in terms of the
thing that actually causes a developer to type a command, and the restatement
is planned in
[docs/plans/navigator-coverage-measure.md](navigator-coverage-measure.md).

That document is a prerequisite for this one and out of scope here.

# Risks carried across the whole plan

- **This plan changes the workflow that builds it, and renames the agent that
  would run it.** The predecessor plan hit the same problem and resolved it the
  same way: build on a branch using the current roles, and land the rename
  last. Package 5 is fifth for this reason, not by preference.
- **Package 4 weakens a guardrail in a tool whose entire pitch is that
  generated code is not merged as slop.** It was deliberately kept in scope
  (accepted 2026-09-02) rather than deferred, so it carries the plan's
  strongest test obligation -- see its "Validation", which requires every
  existing `ask` assertion to be re-examined individually. It remains the
  package to drop first if the pull request must shrink in review; the rest of
  the plan stands without it.
- **Composite verbs can drift from the granular ones they compose.** The
  mitigation is structural, not procedural: they must call the same `git_ops`
  and `task` functions, never reimplement. The "Stop if" in package 2 exists to
  catch the moment that stops being true.
- **Removing `planner` removes a human's ability to deliberately get a
  planning-only session.** That was a feature for some users. The lead agent
  must still be able to do planning-only work when asked and stop there; if it
  cannot, this trades one rigidity for another.
- **Eleven roles is still a lot.** This plan fixes the number the developer
  sees, not the number that exists. Whether the five specialists should be
  selected by diff shape rather than dispatched as a set is already the first
  item in the brief's "Next" list, and it stays there.

# Decisions

## Accepted 2026-09-02

1. **The navigator's name is `navigator`.** `guidance` and `workflow` were
   considered and rejected; the reasoning is in package 1.
2. **Package 4 stays in scope**, in this pull request, rather than being
   deferred or split out.
3. **The session-replay measure is built first**, as its own small pull
   request, and records a 0.5.0 baseline before this plan starts.

## Still open

4. **`lead`'s model.** Opus recommended -- it inherits the judgment that
   justified `planner`'s opus setting, and the volume work already sits in
   `builder`, `reviewer`, and the five specialists, which do not change. Needs
   only confirmation, and blocks nothing before package 5's role files are
   written.

## Outstanding

**Nothing.** The plan was accepted 2026-09-02. Package 1 begins once the
prerequisite in [navigator-coverage-measure.md](navigator-coverage-measure.md)
has landed and recorded a `90cf9f4` baseline.

# Completion evidence

To be filled in per work package as it lands. This document is authority, not
a record.
