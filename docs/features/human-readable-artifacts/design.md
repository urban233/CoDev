# Human voice for generated PR, issue, and wave-plan text

**Status:** Accepted
**Owner:** Martin Urban
**Reviewers:** Martin Urban (project maintainer; no second reviewer is
currently active on this repository)
**Brief:** Not applicable. This design responds directly to maintainer
feedback recorded in Current system and evidence below, not a separate
product brief — the outcome is narrow and the scope was not in question.
**Parent design:** Not applicable (this is the parent)
**Last reviewed:** 2026-09-06

## Summary

CoDev's GitHub issues, pull request titles and descriptions, and wave-plan
prose currently read as machine output — audit-trail checklists, restated
field labels, and echoed template examples — rather than as text one
engineer wrote for another to read. This design splits the fix into two
independently reviewable children, because they touch different kinds of
material with different reviewers and test strategies:

- [Agent-authored guidance](agent-authored-guidance.md) changes what
  skills and templates tell an agent before it drafts free text from
  scratch: PR titles, an issue's opening sentence, and wave-plan prose.
  This is a documentation change with no runtime behavior.
- [Generated PR-body wording](generated-pr-body-wording.md) rewords three
  Python string templates that already produce PR body text mechanically.
  This is a code change with unit tests.

Both children keep every existing structural guarantee — task IDs, issue
links, review-dimension coverage, the ownership statement, the wave-plan
table shape — unchanged. Only wording changes.

## Goals and non-goals

Both children share the same three goals and the same four boundaries.

### Goals

- Every issue, pull request, and wave-plan artifact CoDev produces reads
  as though a competent engineer wrote it for another engineer, not as
  formatted tool output.
- The fix lives entirely in agent-consumed material — skill prose,
  template comments, generated string templates, a style-check script —
  never a developer-facing instruction. Developers do not read CoDev's
  templates or run its CLI directly; only the agent does.
- Every existing structural or traceability guarantee (task IDs, issue
  links, coverage reporting, the ownership statement, wave-plan table
  shape) survives unchanged. This is a wording change, not a removal of
  information.

### Non-goals

- Redesigning the wave-plan table structure, the issue template's field
  list, or the PR template's marker set. These are load-bearing
  (`require_wave_shape.py`, ADR-0014) and out of scope.
- `bug-report.yml`'s GitHub issue form. Dropdown-based forms are
  inherently structured; that is a separate, lower-priority problem this
  design does not solve.
- Any new automation gate, config flag, or CLI command. Nothing here
  changes behavior, only text.
- Reopening ADR-0014's separation of the PR description from the evidence
  log, or ADR-0037's ownership-statement requirement. Both stand; only
  their wording changes.

## Current system and evidence

Three different mechanisms produce today's mechanical tone, and they need
different fixes. [Child A](agent-authored-guidance.md) has the exact file
and line evidence for the two agent-authored mechanisms — PR titles have
no style guidance anywhere, issue bodies and wave-plan prose are drafted
from checklist-shaped templates with no framing sentence and a worked
example that risks being echoed verbatim, and issue titles carry a
leading internal-ID token by documented convention. [Child B](generated-pr-body-wording.md)
has the exact evidence for the third: the generated PR body is Python
string-building, not agent prose, so fixing its tone means editing string
literals rather than instructions.

This is round two of a problem CoDev has hit before. **ADR-0014**
([docs/adr/0014-pr-description-separated-from-the-evidence-log.md](../../adr/0014-pr-description-separated-from-the-evidence-log.md))
replaced an earlier PR body — the raw round-by-round audit log — after a
real session's feedback called it "utter ugly" and "nowhere near
professional." `task.pr_description()` was ADR-0014's fix. What survived
that fix — the Validation checklist's framing, the tracking footer, the
ownership statement — is exactly the material Child B still needs to
address, alongside titles, issues, and wave plans that ADR-0014 never
touched.

One existing hook is worth building on rather than duplicating: the
`technical-writing-style` skill
([SKILL.md](../../../.claude/skills/technical-writing-style/SKILL.md))
already provides a Google-derived writing-style reference and a
structural checker (`check_structure.py`), already read by
`define-product`, `design-solution`, `launch-product`, `plan-wave`, and
`specify-project` before drafting prose. It is calibrated for long-form
documents — specifications, briefs, designs — not one-line titles, and
`build-change`/`outer-loop-review`, where PR titles actually get
authored, never reference it at all. This gap is what motivates the new
shared reference below, owned at the parent level because both children
would otherwise have reason to invent their own.

## Proposed design

At the parent level, the design is one new shared reference plus two
areas of change; each child details its own data flow, contracts, and
alternatives.

### Components and ownership

| Component | Responsibility | Owner | Existing or new |
|---|---|---|---|
| New short-form style reference | Style rules and example pairs for one-line free text (titles, framing sentences, wave-plan prose) | `technical-writing-style` skill | New — see [Child A](agent-authored-guidance.md) |
| Agent-authored guidance (skills and templates) | PR-title wording, issue framing sentence, wave-plan prose discipline | `build-change`, `outer-loop-review`, `plan-wave` skills; `task.md`, `wave-plan.template.md` | Modified — see [Child A](agent-authored-guidance.md) |
| Generated PR-body wording | Validation-section framing, tracking-footer presentation, ownership-statement phrasing | `task.pr_description()`, `git_ops._render_pr_template()`, `git_ops._OWNERSHIP_STATEMENT` | Modified — see [Child B](generated-pr-body-wording.md) |

### Data and control flow

Nothing about which commands run, in what order, or what data they carry
changes. For the agent-authored surfaces (issues, PR titles, wave-plan
prose), the only new element in the flow is what the agent reads before
it composes a string argument — the string still travels through the same
unmodified commands (`codev slice publish`, `codev git issue-create`) to
GitHub exactly as before. For the generated PR body, the same functions
run in the same order at the same checkpoints (`open_pr`, `mark_ready`);
only the string literals they return change. See each child for the exact
call chain in its own area.

### APIs and contracts

Neither child adds, removes, or changes the signature of any CLI command
or public function. The one shared "contract" this design introduces is
the new short-form style reference itself:

| Contract | Owner | Consumers | Guarantees | Compatibility |
|---|---|---|---|---|
| Short-form style reference | `technical-writing-style` skill | `build-change`, `outer-loop-review`, `plan-wave` | A short, directly quotable set of example pairs for one-line text; never restates `writing-style.md`'s long-form rules | Additive; existing long-form reference and its callers are unaffected |

Child B's own function-level contract (`pr_description()`'s return-value
guarantees) is unchanged by this design and is detailed in that child for
completeness, not because this design revises it.

## Alternatives and trade-offs

| Option | Benefits | Costs/risks | Decision |
|---|---|---|---|
| One combined design covering both children | Single document to read | Mismatched reviewers and test strategies | Rejected |
| Two children under one parent (this design) | Each child acceptable and testable on its own schedule | One extra cross-reference to maintain | Chosen |
| Extend `writing-style.md` in place | One fewer file | Dilutes a long-form-calibrated document | Rejected — detailed in Child A |
| Do nothing | No effort | Complaint already recurred once (ADR-0014) | Rejected |

The rejected combined-design option fails this project's own split
heuristic directly: the two children have different reviewers (prose
review vs. code review), different test strategies (manual example
review vs. unit tests), and different risk profiles (behavior-free vs. a
code change) — the exact signal `design-solution` names for splitting a
document rather than one broad topic being long.

## Quality and risk

- **Security/privacy:** None. Both children change or add plain text
  consumed by an agent or rendered into GitHub; no new data is collected,
  stored, or transmitted.
- **Reliability/concurrency:** None. No control flow changes in either
  child.
- **Observability/capacity/cost:** None.
- **Accessibility/internationalization:** A small positive. Plainer,
  shorter sentences are easier for non-native English readers, consistent
  with `writing-style.md`'s own global-writing guidance.
- **Risk:** Wording is inherently a matter of taste, and instructing an
  agent not to do something is probabilistic, not guaranteed — the same
  limitation every other behavioral instruction in this repository's
  skills already carries, not a new one this design introduces. Both
  changes are low blast radius and fully reversible with a normal git
  revert.

## Test strategy

- Child A: `check_structure.py` re-run against every modified skill and
  template file; before/after example review by the maintainer, the same
  acceptance bar ADR-0014 used.
- Child B: existing unit tests (`PrDescriptionTests`, `MarkReadyTests`,
  and the ownership-statement assertion in
  `test_integration_lifecycle.py`) updated to match new wording; no new
  test dimensions, since no new branch or field is introduced.

## Migration, rollout, rollback, and cleanup

No migration and no flag. Text changes take effect the next time an
artifact is created or, for Child B, the next time `open_pr` or
`mark_ready` runs. Already-existing issues, PRs, and wave plans keep
whatever text they already have; nothing here rewrites history. Rollback
is a normal git revert of the skill, template, or source-file commit.

## Open questions

Both questions this design opened are now resolved; none remain.

**Resolved (2026-09-06):** `bug-report.yml` is not worth a follow-up —
Martin Urban decided its dropdown-based issue form is inherently
structured and lower-value than the free-text surfaces already fixed.

**Resolved (2026-09-06):** "sounds human" stays a human-judgment gate,
closed for this design by one trial batch rather than left as an ongoing
open question. Applying `short-form-voice.md` fresh to real material from
this session produced:

- PR title for commit `5fb045d`: "Give PR titles, issue text, and wave
  plans a human voice."
- PR title for commit `9537f90`: "Stop the generated PR body reading
  like a checklist."
- A hypothetical issue opening sentence, for the one remaining open
  question in
  [agent-authored-guidance.md](agent-authored-guidance.md#open-questions)
  (whether this guidance should also cover commit-message subjects):
  "Commit subject lines will get the same plain-English guidance PR
  titles already have, instead of being left to each session's own
  habits."
- A hypothetical wave-plan outcome and task sentence, for a possible next
  wave continuing this same initiative: "A developer reviewing a batch of
  AI-generated PR titles can no longer pick out which ones a machine
  wrote"; "`short-form-voice.md` ships with example pairs a reviewer can
  spot-check against real PR titles, not just synthetic ones."

Martin Urban's verdict: "Looks good to me." No further trial is planned;
the ordinary bar going forward is the same as ADR-0014's own acceptance
bar -- a human reads the artifact and judges it, not a script.

## Acceptance

- [x] Material decisions resolved: the split, the shared short-form
      reference, and the goal/non-goal boundaries.
- [x] Required domain reviews complete (sole maintainer; no independent
      reviewer active on this repository).
- [x] Accountable human (Martin Urban) accepted planning against this
      design on 2026-09-06. Both children are now `Accepted` and
      implemented.
