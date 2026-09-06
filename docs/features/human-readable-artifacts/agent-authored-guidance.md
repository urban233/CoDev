# Agent-authored artifact text: titles, issue framing, wave-plan prose

**Status:** Accepted
**Owner:** Martin Urban
**Reviewers:** Martin Urban (project maintainer)
**Brief:** Not applicable — see parent design.
**Parent design:** [Human voice for generated PR, issue, and wave-plan text](design.md)
**Last reviewed:** 2026-09-06

## Summary

Add explicit style guidance and concrete example pairs to the three
skills and templates that produce free text an agent drafts from scratch:
PR titles (`build-change`, `outer-loop-review`), an issue's opening
sentence (`.github/ISSUE_TEMPLATE/task.md`), and wave-plan prose
(`plan-wave`). Back all three with one new, shared short-form style
reference so the same example pairs are not copied three times and do not
drift. No template's field structure, table shape, or marker set changes
— only what an agent is told before it fills a field in.

## Goals and non-goals

This child inherits the parent's three goals and four non-goals in full,
and adds the following specifics.

### Goals

- An agent drafting a PR title, an issue's opening sentence, or a
  wave-plan sentence has concrete, directly relevant guidance and example
  pairs at the moment it authors that text — not buried in a long-form
  document it was never told to read for this purpose.
- PR titles state the user-visible effect of a change in plain English;
  no internal vocabulary (`slice`, `round`, a task ID) appears in the
  title itself.
- Issue bodies open with one plain-English sentence before the structured
  fields begin.
- Wave-plan prose is specific to the actual feature, not a restatement of
  the planning skill's own worked example.

### Non-goals

- No change to any template's field list, table structure, or marker
  set. `task.md`'s fields, `wave-plan.template.md`'s tables, and
  `pull_request_template.md`'s markers are unchanged.
- No enforcement mechanism stronger than instructions plus an optional
  script check. An instruction to an LLM changes behavior probabilistically,
  the same limitation every other skill instruction in this repository
  already carries — this design does not claim to close that gap.
- No change to `bug-report.yml` (see parent design's non-goals).

## Current system and evidence

See the parent design's Current system and evidence for why these
surfaces read mechanically and for the `technical-writing-style` gap that
motivates the new reference below. This section lists only the exact file
and line locations this child's changes touch:

- **PR titles.** `codev slice publish --id <id> --title <title>`, defined
  at [cli.py](../../../src/codev_workflow/cli.py) lines 476-477 and
  1652-1659, is the command that actually opens the pull request, called
  per [ai-agent-guidelines.md](../../../.codev/for-ai/ai-agent-guidelines.md)
  lines 288-290. `--title` is required and freeform. Neither that file
  nor [`build-change/SKILL.md`](../../../.claude/skills/build-change/SKILL.md)
  nor [`outer-loop-review/SKILL.md`](../../../.claude/skills/outer-loop-review/SKILL.md)
  (which revises the title again around its `mark-ready` step, line 226)
  gives any tone guidance for that argument.

- **Issue bodies.** [`task.md`](../../../.github/ISSUE_TEMPLATE/task.md)
  opens directly on "**Design doc:**" (line 10) with no framing sentence
  before it.

- **Wave-plan prose.**
  [`plan-wave/SKILL.md`](../../../.claude/skills/plan-wave/SKILL.md)
  (the "Define the current wave" step) gives the skill's own worked
  example: "such as 'internal user completes the primary workflow.'"

- **Issue-title row-ID convention.** `task.md`'s own trailing comment
  (line 53) documents that a title "may keep that plan's row ID (e.g.
  `'W-01: ...'`)" — a leading internal-ID token, which is itself part of
  what reads as mechanical. This is `task.md`'s own convention, not
  `plan-wave`'s; `plan-wave/SKILL.md` never mentions a row-ID title
  format.

## Proposed design

This child adds one new reference file and edits five existing skill or
template files; nothing here changes a template's structure.

### Components and ownership

| Component | Responsibility | Owner | Existing or new |
|---|---|---|---|
| `.agents/skills/technical-writing-style/references/short-form-voice.md` | Style rules and good/bad example pairs for PR titles, issue framing sentences, and wave-plan outcome/task prose | `technical-writing-style` skill | New |
| `.codev/for-ai/ai-agent-guidelines.md` (and platform-adapter mirrors) around the `codev slice publish --title` step | Instructs reading `short-form-voice.md` before writing a PR title; states the no-internal-vocabulary rule | Shared agent guidelines | Modified |
| `outer-loop-review/SKILL.md` around its title-revision mention | Same title rule applies when outer-loop review revises a title at `mark-ready` | `outer-loop-review` skill | Modified |
| `.github/ISSUE_TEMPLATE/task.md` | Opening framing sentence; row-ID convention moved to a trailing parenthetical | Issue template | Modified |
| `plan-wave/SKILL.md` (wave-outcome guidance) | Instructs against echoing the skill's own worked example | `plan-wave` skill | Modified |
| `technical-writing-style/scripts/check_structure.py` | Optional new finding: prose in a produced document that is near-identical to a template's placeholder text or a skill's own cited worked example | `technical-writing-style` skill | New, deferred — see Open questions |

### Data and control flow

No command, argument, or data shape changes. The flow for each surface:

1. The agent reaches the point in its existing workflow where it must
   compose a title, an issue body, or a wave-plan sentence.
2. It reads the relevant skill section, which now points at
   `short-form-voice.md` (titles, issue framing) or states the
   anti-echo rule directly (`plan-wave`).
3. It composes the text inline — this is prompt-time authorship, not a
   code path — and passes it as an existing CLI argument (`--title`,
   `--body`) to an unmodified command (`codev slice publish`, `codev git
   issue-create`).
4. The unmodified command persists it to GitHub exactly as it does today.

### APIs and contracts

No new command or argument. The one contract this child introduces is the
new reference file:

| Contract | Owner | Consumers | Guarantees | Compatibility |
|---|---|---|---|---|
| `short-form-voice.md` | `technical-writing-style` skill | `build-change`/`ai-agent-guidelines.md`, `outer-loop-review`, `plan-wave` | Contains only short, directly quotable rules and example pairs for one-line text; does not restate `writing-style.md`'s long-form guidance | Additive; `writing-style.md` and its existing callers are unaffected |

## Alternatives and trade-offs

| Option | Benefits | Costs/risks | Decision |
|---|---|---|---|
| New sibling short-form reference (`short-form-voice.md`) | Small, targeted, quotable from three call sites | One more file to keep in tone with `writing-style.md` | Chosen |
| Extend `writing-style.md` in place | One fewer file | Dilutes a document calibrated for long-form prose | Rejected |
| Inline guidance separately into each of the three skill files | No new file | Triplicates the example pairs; drifts over time | Rejected |
| Issue-title row-ID as a trailing parenthetical | Reads as a title first, a reference second | Needs confirming no tooling parses the current leading token | Chosen, pending confirmation |
| Issue-title row-ID dropped entirely | Simplest title | Loses a scannable trace back to the plan | Rejected |
| Template-echo detection, extending `check_structure.py`'s existing near-duplicate machinery | Reuses proven logic | False-positive risk on legitimate short-phrase reuse; needs new test coverage | Deferred — see Open questions |
| Template-echo detection, skipped entirely | No new code or false-positive risk | No mechanical safety net if the instruction is ignored | Fallback if deferred permanently |

The chosen sibling reference avoids two failure modes of its
alternatives: extending `writing-style.md` would force a skill drafting a
five-word title to read a document written for specifications and
designs, and inlining the same guidance into three skill files would
drift the moment one copy is edited and the others are not — the exact
defect `check_structure.py`'s own cross-file-duplicate check exists to
catch elsewhere in this repository.

## Quality and risk

- **Security/privacy/reliability/concurrency/observability:** None. Pure
  documentation and template-comment changes; no runtime code path is
  touched.
- **Accessibility/internationalization:** A small positive — plainer,
  more specific sentences read more easily for non-native English
  speakers than restated jargon or generic worked-example phrasing.
- **Risk:** An instruction change to skill prose cannot guarantee
  compliance from an agent; it can only make the desired behavior the
  easiest, most immediately available one at the point of authorship.
  This is the same limitation every other instruction in this
  repository's skills already carries.

## Test strategy

- Run `python3 .agents/skills/technical-writing-style/scripts/check_structure.py`
  against every modified file (`short-form-voice.md`, `task.md`,
  `plan-wave/SKILL.md`, `ai-agent-guidelines.md`,
  `outer-loop-review/SKILL.md`) and fix any `violation`-level finding.
- Manual before/after review by the maintainer of a representative sample
  of PR titles, issue bodies, and wave-plan sentences — the same
  acceptance bar ADR-0014 used for the original PR-body complaint. This
  is a judgment call, not a mechanical test; see the parent design's Open
  questions for why "sounds human" resists full automation.
- If the template-echo check in `check_structure.py` is built (see Open
  questions), it needs its own unit tests, following the pattern the
  existing cross-file-duplicate check would use if it had tests today —
  none currently exist for that script.

## Migration, rollout, rollback, and cleanup

None. Guidance and template changes take effect the next time an agent
runs the relevant skill step. No flag, no migration, no cleanup of prior
artifacts — existing issues, PRs, and wave plans are documents, not
stateful records, and are unaffected. Rollback is a normal git revert.

## Open questions

**Resolved before acceptance:** a repository-wide search
(`grep -rn "W-[0-9]" src tests`) found no code, test, or documentation
that parses a GitHub issue title's leading `"W-01:"` token — the only
matches are `require_wave_shape.py`'s own tests, which match `W-01`
against the wave-plan table's row-ID column, not an issue title. The
row-ID placement change is unblocked.

**Resolved (2026-09-06):** the template-echo detector stays deferred —
Martin Urban decided the false-positive risk on legitimate short-phrase
reuse and the missing test coverage for a new heuristic outweigh building
it now, on top of guidance-only changes already having landed without it.

Martin Urban owns the one remaining question below.

| Question | Evidence needed | Blocking? |
|---|---|---|
| Should the same short-form reference also cover git commit-message subject lines? | Decision only | No |

## Acceptance

- [x] Material decisions resolved, including the previously blocking
      row-ID question (see Open questions).
- [x] Required domain reviews complete (sole maintainer; no independent
      reviewer active on this repository).
- [x] Accountable human (Martin Urban) accepted planning against this
      design on 2026-09-06.
