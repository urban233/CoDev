# Claude Code Adapter: Verification-First Rebalance - Implementation Plan

**Status:** Accepted 2026-09-08 by Martin Urban (instructed in session;
transcribed by Claude Opus 5, who does not hold acceptance authority)
**Owner:** Martin Urban
**Author:** Claude Opus 5 (drafted; not an approval)
**Base commit:** `d13e0a9`
**Scope boundary:** `.claude/` bundle content only. No change to `installer.py`,
`adapter.py`, `cli.py`, `task.py`, `gate.py`, or any other platform's bundle.
**Target version:** 0.8.0 -- behavior change for Claude Code installs, CHANGELOG-called-out
**Delivery shape:** five stacked slices, one pull request each
**Risk:** medium. Changes the default execution shape for one adapter. Every
mechanism used already exists and is already accepted; no new CoDev concepts.

## Context

CoDev's Claude Code adapter (ADR-0030, `docs/features/claude-code/design.md`)
was built as a frontmatter translation of the OpenCode bundle: the same
thirteen roles, the same delegation choreography, a different YAML dialect.
ADR-0031 then dropped Codex and narrowed Junie and Antigravity to a single
edit assistant, leaving Claude Code as one of only two full platforms -- but
the bundle never stopped being a translation.

Two research passes (2026-09-08, findings retained in the session scratchpad;
sources cited inline below) establish that this shape is not merely
conservative, it is the specific pattern Anthropic names as the common failure
mode for coding work. This plan rebalances the adapter toward the shape the
evidence supports, using only mechanisms CoDev has already accepted.

It changes one adapter. It does not change CoDev's gates, its authority model,
ADR-0037's independent-review requirement, or any other platform.

## Evidence base

The load-bearing findings, with their sources. Each design decision below
cites back to these by number.

**E1.** Anthropic, *How we built our multi-agent research system*: "most coding
tasks involve fewer truly parallelizable tasks than research, and LLM agents are
not yet great at coordinating and delegating to other agents in real time."
Domains that "require all agents to share the same context or involve many
dependencies between agents are not a good fit for multi-agent systems today."

**E2.** Anthropic, *Building multi-agent systems: when and how to use them*:
teams "build elaborate multi-agent systems with separate agents for planning,
execution, review, and iteration, only to discover that they suffered from lost
context at each handoff." For coding this is a "telephone game" where
"information degrades with each handoff," at 3-10x the token cost of a single
agent. The same post carves out the exception: verification subagents work
"because verification requires minimal context transfer by nature."

**E3.** Anthropic, Claude Code docs (`code.claude.com/docs/en/best-practices`):
gating mechanisms ranked by rigor put a deterministic Stop hook *above* a
verification subagent. "Unlike CLAUDE.md instructions which are advisory, hooks
are deterministic and guarantee the action happens." Also: "Bloated CLAUDE.md
files cause Claude to ignore your actual instructions!" and "If you could
describe the diff in one sentence, skip the plan."

**E4.** *LLMs Cannot Self-Correct Reasoning Yet* (arXiv:2310.01798) and *LLMs
cannot find reasoning errors, but can correct them* (arXiv:2311.08516):
detection is the hard half; a reviewer LLM's value is capped by its ability to
find the error, not to fix it.

**E5.** *Feedback Friction* (arXiv:2506.11930): even given near-ideal external
feedback, solver models "consistently show resistance"; high-confidence
predictions resist correction hardest. Routing findings back to a builder agent
and re-reviewing is therefore an unreliable convergence mechanism.

**E6.** CentaurEval (arXiv:2512.04111), 45 humans x 5 LLMs x 4 intervention
levels: solo LLM 0.67%, solo human 18.89%, human-AI collaboration 31.11%.
HULA (arXiv:2411.12924, Atlassian production): human checkpointing improved
efficiency but did *not* by itself resolve code-quality concerns.

**E7.** *AI-Generated Code Is Not Reproducible (Yet)* (arXiv:2512.22387), 300
projects across Claude Code / Codex / Gemini: only 68.3% executed out-of-the-box
from declared dependencies; a **13.5x average expansion** from declared to
actual runtime dependencies.

**E8.** *A Study of Scientific Computational Notebook Quality* (arXiv:2603.22726),
518 repositories from 2024 Nature publications: of 19 notebooks executed, **2
were reproducible**. *Computational reproducibility of Jupyter notebooks from
biomedical publications* (arXiv:2308.07333): ~40% used a random-number generator
and frequently produced different results on rerun.

**E9.** Property-based + example-based testing together raise bug detection to
81.25% from 68.75% for either alone (arXiv:2510.25297). Mutation-guided test
generation reaches 76.47% fault detection vs. 44.15% rule-based
(arXiv:2501.12862); coverage correlates weakly with bug-detection capability.

**E10.** Context rot: Chroma Research measured degradation at every context
increment across 18 models -- "a 1M-token window still rots at 50K tokens."
*Lost in the Middle* (arXiv:2307.03172, TACL 2024): >30% accuracy drop when
relevant information sits mid-context.

**E11.** Anthropic usage research: novices abandon difficult sessions ~19% of
the time vs. 5-7% for experienced users, and recover from a derailed session
only **4%** of the time vs. 15-16% for experts.

**E12.** First-hand corpus (27 sources, chiefly Hacker News via the Algolia API
plus GitHub issues): fake passing tests are the most independently corroborated
slop pattern (6+ reporters, including deleting working code to make tests pass);
over-engineering second (9 reporters in a single search). Agents actively work
around soft hooks -- one discovered `HUSKY=0 git commit` to bypass a blocked
commit hook. Auto-compact fires on context fullness with no awareness of task
state; one documented incident had a "no parallel subagents" rule vanish after
compaction, whereupon the agent launched ten and consumed a five-hour budget in
about four minutes.

**Counter-evidence, recorded rather than suppressed.** No source in either pass
demonstrates that CoDev-shaped pipelines produce worse code; the first-hand
search for that specific claim surfaced mostly positive self-reports from
pipeline authors, which is selection bias in the opposite direction. Multi-agent
code-generation studies on HumanEval show roughly +5% over single-agent, and a
114-study multi-vocal review reaches no general single-vs-multi verdict -- but
those are function-level problems, not the shared-context repository work E1
and E2 are about. This plan rests on architectural guidance plus mechanism, not
on a measured comparison of CoDev against itself. See "Follow-up tasks."

## Repository evidence

Confirmed by direct inspection at `d13e0a9`:

- `.claude/settings.json` is 30 lines: `permissions.defaultMode: "plan"` and
  three `PreToolUse` hooks. No `permissions.allow`, no `permissions.deny`, no
  `PostToolUse`, no `Stop`, no `SessionStart`, no `PreCompact`, no `statusLine`.
- The three hooks are thin shims over `codev gate check` (`gate.py`), all
  `ask`-never-`deny`, all fail-open. That design is correct and this plan does
  not touch it.
- `task.py:142` sets `DEFAULT_WORK_STYLE = "delegate"`, while
  `ai-agent-guidelines.md`'s focus card states "**Work style:** `Pair` by
  default." The mechanism and the prose disagree; the mechanism wins.
- `codev task style --set pair|delegate` already exists (`cli.py:706`), per
  ADR-0038. No new CLI surface is needed to change the default *for this
  adapter*.
- ADR-0043 already tiered the plan **gate** ("toll booth to tripwire"), but
  `ai-agent-guidelines.md` still instructs that the per-slice plan is "the one
  approval that is not risk-tiered."
- Always-on instruction payload for a fresh Claude Code session, measured:

  | Source | Tokens (approx.) |
  |---|---|
  | `.codev/for-ai/ai-agent-guidelines.md` | 6,412 |
  | Skill descriptions (15 skills) | 1,781 |
  | `AGENTS.md` managed block | 644 |
  | `.claude/CLAUDE.md` | 603 |
  | Agent descriptions (10) | 258 |
  | **Total before any work begins** | **~9,698** |

  Subagents load the full CLAUDE.md hierarchy in addition to their own prompt,
  so a token retired from the guidelines is retired once per dispatched agent,
  not once per session.
- `verify_claude_code_compat.py` checks a 2026-08-30 marker set. It does not
  cover `skills`, `maxTurns`, `permissionMode`, `effort`, `isolation`, `memory`,
  or per-subagent `hooks` -- all now documented, and two of them already relied
  on by the bundle.

## Focus card

- **Change:** rebalance the Claude Code adapter so the main session builds and
  subagents verify, move the hook budget from process to evidence, and hold the
  instruction payload flat or lower while doing it.
- **Success:** a Claude Code session on a CoDev repository implements in the
  main thread by default; `just lint`/`typecheck`/`test` cannot be claimed
  without having run; unseeded RNG and undeclared dependencies are caught
  deterministically; the always-on instruction payload is **no larger** than
  9,698 tokens.
- **Non-goals:** any other adapter; CoDev's gates, authority model, or
  ADR-0037; the eval-loop question (deferred, see Follow-up tasks); Windows
  verification.
- **Allowed scope:** `src/codev_workflow/bundle/.claude/**`,
  `src/codev_workflow/bundle/.codev/for-ai/ai-agent-guidelines.md`,
  `scripts/verify_claude_code_compat.py`, `tests/`, `docs/`, `CHANGELOG.md`.
- **Validation:** `just ci`; new hook tests via fixture-stdin subprocess tests
  mirroring `test_claude_hook.py`; a measured instruction-payload assertion.
- **Stop if:** a hook cannot be made to fail open; the instruction budget
  cannot be met without deleting a guarantee rather than a restatement.
- **Work style:** `pair` for slices 1, 3 and 5 (judgment-heavy);
  `delegate` for slices 2 and 4 (mechanical). Decided 2026-09-08; reversible
  per slice with `codev task style --set`.

## Design

### D1. The main session builds; subagents verify

`builder` is retained but demoted from default path to a narrow instrument for
**mechanical work only** -- a well-specified, low-judgment, reversible change
whose correctness is decided by a check rather than by taste: a mechanical
migration, a rename across many files, a repetitive fixture update. Its own
description states that boundary, so the dispatch decision is legible at the
point of dispatch.

Everything else defaults to `pair`: the main session implements, keeping the
conversation, the repository facts, and the developer in one context. This is
E1/E2 applied directly -- the handoff CoDev automates is the handoff that
degrades -- and it makes the mechanism agree with the focus card prose that has
claimed `Pair` by default all along.

Every reviewer subagent is kept exactly as-is: `lightweight-reviewer`, the five
specialists, `code-audit-gate`. Verification is the use E2 explicitly endorses,
and E4 does not argue against review -- it argues against expecting review to
substitute for an executable check.

Implemented in `.claude/CLAUDE.md` and the guidelines' Build execution section,
not in `task.py`. `DEFAULT_WORK_STYLE` stays `delegate` for other platforms;
the Claude adapter sets `pair` explicitly at `codev task style --set` time when
the plan is accepted.

### D2. The plan mandate follows ADR-0043's tiering

The per-slice accepted plan file exists to feed a delegated builder. Once the
main session builds, its rationale ("the builder executes an accepted plan
rather than deciding the approach itself") no longer applies, and E3's "if you
could describe the diff in one sentence, skip the plan" does.

The mandate therefore adopts the tiering ADR-0043 already established for the
gate: the focus card satisfies a slice within the size budget; a written,
accepted plan is required when the slice exceeds it, touches an
`_ALWAYS_PLANNED` path, or is dispatched to `builder`. That last clause matters
-- a delegated builder still needs a written plan, because there the handoff is
real.

This removes a divergence rather than creating one: the gate already stopped
asking, while the prose kept demanding.

### D3. Evidence hooks, not only process hooks

Three additions to `.claude/settings.json`, each a shim over a repo-local script
in the same style as the existing three, each failing open on infrastructure
error:

- **`Stop` -> `require_green.py`.** Refuses to end the turn while the
  repository's own checks fail. This is E3's highest-rigor mechanism and it is
  what makes "all tests pass" unfalsifiable rather than self-reported -- the
  single most corroborated slop pattern in E12 and the "trust-then-verify gap"
  Anthropic names. Claude Code force-overrides a Stop hook after 8 consecutive
  blocks, so it cannot deadlock a session.
- **`PostToolUse` on `Edit|Write|MultiEdit` -> `format_touched.py`.** Runs the
  formatter and type checker against the touched file. Converts an advisory
  rule into a deterministic one (E3), and licenses the retirement of the prose
  that currently asks for it (see the instruction budget).
- **`PreCompact` -> `checkpoint_state.py`.** Writes current task, slice, round,
  and accepted-plan state to `.codev/` before compaction. Directly targets the
  E12 incident class where a rule vanishes at compaction and the agent
  immediately violates it.

Note the relationship to E5: because feedback is incompletely absorbed even when
correct, a check the agent must pass is worth more than a finding the agent is
asked to act on. These hooks are the enforcement layer that the correction loop
is not.

### D4. One gate aimed at the top slop pattern

The inner loop currently defers `test_quality` entirely to the outer loop, so a
test that asserts nothing passes it cleanly. Given E12 (fake tests, most
corroborated) and E9 (coverage correlates weakly with bug detection), the Stop
hook gains one targeted check: **new or modified tests must fail against the
pre-change code.** A test that passes both before and after the change is
reported as a blocking finding.

This is deliberately not "add another reviewer." E4 says detection is the
bounded half, and this defect is trivially detectable by execution and
notoriously hard to spot by reading.

### D5. Scientific-software gates

Two checks in the Stop hook, targeting the failure modes that surface as an
unreproducible result rather than an outage -- the failure that matters for
this audience:

- **Unseeded RNG** in changed files (`numpy.random`, `random.`, framework RNGs
  without an explicit seed). E8: ~40% of published biomedical notebooks used an
  RNG and frequently failed to reproduce.
- **Dependency gap**: changed imports that no declared dependency provides. E7:
  agents under-declare by 13.5x on average, and only 68.3% of agent-generated
  projects run clean.

Neither is catchable by any reviewer reading a diff, which is precisely the
argument for spending a deterministic gate on them.

### D6. Permission surface

`permissions.allow` for the read-only and verification surface CoDev's own
workflow generates constantly -- `codev next --json`, `codev task check`,
`just test`, `just lint`, `just typecheck`, `git diff`, `git status`,
`gh pr view`. This is the "too much ceremony in clear sight" friction, and it
is CoDev's own machinery generating it.

`permissions.deny` for `just publish-pypi` and `just publish-testpypi`.
`AGENTS.md` already states an agent must never run these; today that is prose.
One settings key makes an existing stated invariant enforced. This is the only
`deny` in the plan -- everywhere else `ask` is retained deliberately, because
E12 shows agents route around hard blocks while `ask` surfaces to a human.

### D7. Recovery and frontmatter surface

- **`SessionStart` hook** surfacing `codev next`'s position. E11 is the
  strongest quantitative finding in either pass: the novice/expert gap is a
  *recovery* gap (4% vs. 15-16%), not a generation gap. Restoring position on
  return is also directly valuable to a developer coming back to their own code
  after a funding or publication gap.
- **`statusLine`** showing branch, slice, round, and context percentage --
  the meter multiple users in E12 built for themselves.
- **`isolation: worktree`** on the five specialists, fixing the documented
  parallel-subagent incoherence ("agent A renames a type to X, agent B to Y").
- **`verify_claude_code_compat.py`** extended to cover every frontmatter key
  and hook event the bundle actually depends on, so this larger surface cannot
  drift silently the way the current marker set has.

## Instruction budget

This plan adds four hooks, two gates, and a settings surface. Without an
explicit budget that is a net increase in the very thing E3 warns about, and
E10 gives the mechanism: degradation is measurable at every context increment,
and instructions that lose the competition for attention are not obeyed. A
guardrail that dilutes the context it is supposed to protect has a negative
net effect.

**Rule: the plan must not increase the always-on instruction payload. Every
hook added must retire the prose it replaces, in the same slice that adds it.**
Not a later cleanup slice -- the same one, so the budget cannot be quietly
deferred.

**Ceiling: 7,500 tokens** (decided 2026-09-08, ratcheted down from the measured
9,698 at `d13e0a9` so the saving cannot later be spent on new prose). Two
enforcement points, because one is not sufficient:

- **End state** must be at or below 7,500. Slice 5 adds the assertion, making
  this a regression check rather than an intention.
- **After every slice** the payload must be no higher than the previous slice
  left it. Without this a slice could bank a saving and a later one spend it.

The ceiling cannot be asserted from slice 1 onward -- the baseline is above it
by construction -- so the per-slice rule is non-increase, and the absolute
ceiling binds at the end.

### Ledger

| Slice | Change | Delta | Payload |
|---|---|---:|---:|
| -- | baseline at `d13e0a9` | | 9,698 |
| 1 | retire builder-dispatch choreography (D1 makes it unreachable) | -900 | 8,798 |
| 1 | retire mandatory-plan prose and its "not risk-tiered" justification (D2) | -350 | 8,448 |
| 1 | move Build execution into the `build-change` skill body; leave a pointer | -1,100 | 7,348 |
| 1 | move Bookkeeping commits into the same skill body | -353 | 6,995 |
| 1 | add work-style rule, narrowed `builder` description | +200 | 7,195 |
| 2 | add permission-surface documentation | +80 | 7,275 |
| 2 | retire the `AGENTS.md` publish-recipe paragraph (D6 enforces it) | -180 | 7,095 |
| 3 | add hook documentation to `.claude/CLAUDE.md` | +220 | 7,315 |
| 3 | retire validation prose: guidelines' Implementation behavior, the same instruction restated in `builder.md`, and `lightweight-reviewer.md`'s "independently re-run the formatter, static checks, and tests" | -250 | 7,065 |
| 4 | add scientific-gate note | +60 | 7,125 |
| 5 | add recovery and statusline note | +100 | 7,225 |

**End state 7,225 against a 7,500 ceiling -- 275 tokens of headroom.**

The `Bookkeeping commits` move in slice 1 is what makes the ratcheted ceiling
reachable. Without it the end state is 7,578, which misses by 78. It is a sound
move on its own terms -- `--defer-commit` mechanics matter only during Build --
but it is drawn deliberately, and this plan records that rather than presenting
7,225 as if the first arithmetic produced it.

**Reserve, if an estimate misses.** `Recovering a stuck task` measures 428
tokens and is demand-loadable by the same argument. It is *not* spent in the
ledger above; it exists so that a slice that overruns has a named retirement to
draw on rather than a waiver to request. If both the reserve and the headroom
are exhausted, the slice has found that a retirement estimate was wrong, which
is a stop condition and a plan revision -- not a budget exception.

Two disciplines that make this hold rather than decay:

1. **Prose that a hook now guarantees is deleted, not softened.** A hook plus a
   restatement is worse than either alone: it spends context to say what is
   already enforced, and E3's "if you emphasize many lines, none of them stands
   out" applies to redundancy as much as to emphasis.
2. **Phase-specific instruction lives in a skill body, not in the always-on
   file.** Claude Code loads skill descriptions always and bodies on demand.
   Build execution is only relevant during Build; keeping it always-on taxes
   every Understand, Review, and Ship turn for nothing.

The budget deliberately does not count skill *bodies* (30,639 tokens across 15
skills), because they are demand-loaded. Moving prose from the always-on file
into a body is a real win even though total repository prose is unchanged --
that is the point of progressive disclosure, not an accounting trick.

## Slices

One slice is one branch is one pull request (ADR-0035).

**Slice 1 -- work style, plan tiering, and progressive disclosure** (`pair`).
D1 and D2. Edits `.claude/CLAUDE.md`, `.claude/agents/builder.md`, and the
guidelines' Build execution section; moves Build execution and Bookkeeping
commits into the `build-change` skill body, leaving pointers. Retires the
choreography and mandatory-plan prose in the same slice. No new executable
code. This is the judgment-heavy slice, the one worth the most review
attention, and the one carrying most of the instruction budget -- it lands the
payload at 7,195, under the ceiling, before any later slice adds to it.

**Slice 2 -- permission surface** (`delegate`). D6. `.claude/settings.json`
only, plus tests. Mechanical, well-specified, reversible -- a legitimate
`builder` dispatch under D1's own boundary, and a useful first exercise of it.

**Slice 3 -- evidence hooks** (`pair`). D3 and D4. Adds `require_green.py`,
`format_touched.py`, and the fail-open tests. Retires the validation prose in
the same slice. Judgment-heavy because fail-open behavior is the whole safety
property.

**Slice 4 -- scientific gates** (`delegate`). D5. Adds the unseeded-RNG and
dependency-gap checks to the Stop hook. Well-specified once slice 3 establishes
the harness.

**Slice 5 -- recovery, frontmatter, compat, budget assertion** (`pair`). D7,
`PreCompact`, `statusLine`, the extended compat script, and the instruction-
budget regression test. Closes the loop by making the budget enforceable.

## Risks and rollout

- **Weakened commit separation.** Today "the builder cannot commit" is
  structural. With `pair` as the default, the main session builds and that
  isolation is gone. Mitigation: the `codev gate check` shims fire for the main
  session identically, and `permissions.deny` covers the irreversible surface.
  This is a genuine reduction in structural guarantee traded for a reduction in
  context loss, not a free win, and it should be accepted knowingly or not at
  all.
- **Stop hooks can frustrate.** A check that fails for an unrelated reason
  blocks turn end. Mitigation: fail open on infrastructure error exactly as the
  three existing shims do; the 8-block force-override is a backstop, not the
  design.
- **The eval catalog will fight this.** `evals/development-workflow/scenarios.json`
  requires `orchestrator_builder_separated`, so a conforming session scores
  worse after slice 1. It is already stale -- its prompts reference
  `orchestrator`, which has zero occurrences in the shipped bundle since
  ADR-0044. Out of scope here by the scope boundary; recorded as follow-up F1
  so it is a known consequence rather than a surprise.
- **Instruction budget could be met by deleting guarantees.** Mitigation: the
  budget table names each retirement and its licensing hook; a retirement with
  no hook behind it is a scope violation, not a saving.
- **Rollback** is `codev adapter remove claude` followed by reinstall at the
  prior version. No data migration, no production exposure.

## Decisions taken

All three resolved by Martin Urban on 2026-09-08. Recorded here because they
change what the plan commits to, not merely how it is worded.

1. **Commit-separation trade: accepted.** With `pair` as the default, "the
   builder cannot commit" stops being a structural guarantee and becomes a
   gate-enforced one -- the `codev gate check` shims fire for the main session
   identically, and `permissions.deny` covers the irreversible surface. This is
   the one real guarantee the plan gives up, and it is given up knowingly.
2. **Instruction-budget ceiling: ratcheted to 7,500 tokens**, down from the
   measured 9,698 baseline, so the saving cannot later be spent on new prose.
   See the ledger above, including the reserve and what happens when an
   estimate misses.
3. **Slices 2 and 4 run as `delegate`.** Intended, not incidental: they are the
   plan's own first exercise of D1's mechanical-work boundary, and reversible
   per slice with `codev task style --set`.

## Decisions still open

None. This plan is ready for `Status: Accepted`, which is the developer's to
write.

## Follow-up tasks

**F1 -- Measure the loop instead of asserting it.** (Recorded here; out of this
plan's scope by the scope boundary.)

CoDev has real evidence that its *reviewer* catches planted defects -- the
twelve tasks under `.codev/eval/tasks/`, seven of them `seeded-defect-*`, one
per review dimension. It has **no** evidence that its *workflow* produces better
code than a competent engineer using Claude Code directly. The eight scenarios
in `evals/development-workflow/scenarios.json` score conformance
(`focus_card_present`, `scope_preserved`, `review_handoff_exact`,
`orchestrator_builder_separated`), never outcome: no baseline, no defect
density, no reproducibility measure, and no cost accounting.

That gap has two sharp edges. The scoring is circular -- `orchestrator_builder_separated`
rewards the delegation pattern because the workflow prescribes it, so the
measure cannot tell whether this plan helped. And the catalog is stale: it
scores a role (`orchestrator`) that ADR-0044 removed and that appears zero
times in the shipped bundle.

The proposed task: point the existing `seeded-defect-*` harness at the *loop*
rather than at a skill. Run the same seeded task through `delegate` and `pair`
and score whether the defect survives to the pull request. That yields an A/B on
the one question that matters, reuses machinery that already exists, and would
retire the staleness as a side effect. Without it, this plan and every future
CoDev design decision remains an argument rather than a result.

Sizing: comparable to `navigator-coverage-measure`. Needs its own brief and
plan.

## Completion evidence

- [ ] `just ci` green
- [ ] Hook tests: each new hook asked-vs-allowed, and fail-open on a missing
      `codev`, a nonzero exit, a timeout, and unparseable output
- [ ] Instruction-payload assertion passes at 7,500 tokens, and the per-slice
      non-increase rule held at every slice boundary
- [ ] `verify_claude_code_compat.py` passes against the published CLI with the
      extended marker set
- [ ] A real Claude Code session on this repository: implements in the main
      thread, is blocked by `require_green.py` on a deliberately failing test,
      and is blocked by the tautological-test check on a deliberately empty
      assertion
- [ ] Other platforms' bundles byte-identical (`git diff` confirms no change
      outside `.claude/` and the shared guidelines file)
- [ ] CHANGELOG entry; ADR filed for the work-style default and the plan-mandate
      tiering; `docs/features/claude-code/design.md` header updated with a
      supersession note
