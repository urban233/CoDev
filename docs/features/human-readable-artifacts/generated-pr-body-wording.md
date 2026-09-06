# Wording of the code-generated PR body

**Status:** Draft
**Owner:** Martin Urban
**Reviewers:** Martin Urban (project maintainer)
**Brief:** Not applicable — see parent design.
**Parent design:** [Human voice for generated PR, issue, and wave-plan text](design.md)
**Last reviewed:** 2026-09-06

## Summary

Reword three Python-generated text fragments that make up the pull
request body: the Validation section's framing sentence, the tracking
footer's presentation, and the ownership statement — in
`task.pr_description()` and `git_ops.py`. This is round two of the same
complaint ADR-0014 already fixed once for this file, against the part of
its own fix that survived. Every field, fact, and condition the current
code renders stays exactly the same; only the wording changes.

## Goals and non-goals

This child inherits the parent's three goals and four non-goals in full,
and adds the following specifics.

### Goals

- The Validation section's full-coverage case reads as one human
  sentence describing what was checked, not a bare "All N review
  dimensions pass."
- The tracking footer (`Task: T-042 (#123)` / `Full review history:
  ...`) is visually set off from the narrative body, so a reader's eye
  does not have to switch registers mid-paragraph between prose and
  bookkeeping.
- `_OWNERSHIP_STATEMENT` keeps its exact legal and procedural meaning
  (ADR-0037) in a plainer register.
- Every existing test assertion about *content* — which facts appear,
  under which conditions — keeps passing unmodified; only assertions on
  literal wording strings change.

### Non-goals

- No change to `pr_description()`'s signature, return type, or call
  sites.
- No change to which coverage dimensions exist, how they are labeled, or
  their waiver semantics.
- No change to `mark_ready()` or `open_pr()`'s control flow.
- No revisiting ADR-0014's decision to keep the evidence log separate
  from and linked from the PR body — only the linked text's wording
  changes.
- No change to `_render_pr_template()`'s marker-substitution mechanism.

## Current system and evidence

See the parent design's Current system and evidence for why this file's
tone has been raised before (ADR-0014) and how this child is round two of
that fix. This section gives the exact construction this child rewords.

`task.pr_description()`, defined at
[task.py](../../../src/codev_workflow/task.py) lines 1656-1712, builds
the PR body in three parts:

1. A narrative paragraph from `description` or `summary` (unchanged by
   this design).
2. A "## Validation" section: for full coverage, the single line "All
   {len(REQUIRED_COVERAGE_DIMENSIONS)} review dimensions pass."; for
   incomplete coverage, a per-dimension bullet list ("- Correctness:
   passed", "- Test quality: waived (by Alice) -- doc-only change").
3. A tracking block: `"Task: {task_id}"`, optionally with `(link_ref)`
   appended, followed by `"Full review history: `codev task log --id
   {task_id}`"`.

`git_ops._OWNERSHIP_STATEMENT`, defined at
[git_ops.py](../../../src/codev_workflow/git_ops.py) lines 1458-1462,
reads: *"I directed this change and I own it. This is an ownership
statement, not an approval -- ADR-0037 requires a separate approving
review from someone who is neither this task's owner nor a bot."*
`mark_ready()` appends it unconditionally to the regenerated body.

**Confirmed exact-string dependents**, found by searching the repository
before drafting this design — every one of these needs its assertion (not
its meaning) updated alongside any wording change, and this list is the
concrete gate this child's Test strategy section below enforces:

- `tests/test_git_ops.py:1944` — `assertIn("I directed this change and I
  own it", body)`
- `tests/test_integration_lifecycle.py:119` — `assertIn("I directed this
  change and I own it", record["body"])`
- `tests/test_task.py:3074` — asserts the exact `"All {N} review
  dimensions pass"` string
- `docs/adr/0014-pr-description-separated-from-the-evidence-log.md:48` —
  cites `"All 8 review dimensions pass"` as descriptive text. ADR-0014 is
  `Accepted` and append-only; this reference is historical narration of a
  past decision, not a live contract, and is not edited by this design.
- `docs/features/unified-workflow/brief.md:361` — quotes "I directed this
  change and I own it" as the canonical description of an author's
  signature. This is a dependent document, not a contract; it should be
  checked for consistency once the new wording is chosen, though it is
  not required to quote the statement verbatim.

## Proposed design

This child touches three functions across two files, none of them a
public entry point beyond `pr_description()` itself.

### Components and ownership

| Component | Responsibility | Owner | Existing or new |
|---|---|---|---|
| `task.pr_description()` | Validation section's framing-sentence wording | `task.py` | Modified — wording only |
| `git_ops._OWNERSHIP_STATEMENT` | Ownership and no-independent-review disclosure wording | `git_ops.py` | Modified — wording only |
| `git_ops._render_pr_template()` | Visual separation of the tracking line from the narrative body in the rendered template | `git_ops.py` | Modified — formatting only |

### Data and control flow

Unchanged. Same callers (`open_pr`, `mark_ready`), same call order, same
markers substituted into `pull_request_template.md`
([pull_request_template.md](../../../.github/pull_request_template.md)).
No branch, condition, or field is added or removed — only the string
values returned along existing paths change.

### APIs and contracts

| API/contract | Owner | Consumers | Guarantees | Compatibility |
|---|---|---|---|---|
| `pr_description(task_id, *, target) -> str` | `task.py` | `git_ops.open_pr()`, `git_ops.mark_ready()`, direct CLI JSON payloads | Self-contained narrative body; no finding text, round numbers, or head hashes (ADR-0014, unchanged); reads as prose, not a checklist lead-in (new) | Breaking for exact-string matches only — see dependents above |

The per-dimension bullet list for incomplete coverage is a checklist and
stays one; only the full-coverage one-liner and the section's framing
sentence change. Any external tooling matching the literal phrase
"review dimensions pass" or "I directed this change and I own it" breaks
— the confirmed dependents listed above must be updated in the same
change.

## Alternatives and trade-offs

| Option | Benefits | Costs/risks | Decision |
|---|---|---|---|
| Reword in place, preserve structure | Small, reviewable diff; keeps ADR-0014's information architecture intact | Does not address any deeper structural complaint | Chosen |
| Restructure the Validation section into a collapsible `<details>` block | Could shrink the visible body further | A structural change, not a wording change; GitHub renders it fine but this goes beyond what this design set out to do | Rejected here — noted as a possible follow-up in Open questions |
| Leave Python-generated text unchanged; fix only agent-authored text (Child A) | Smaller total change | Leaves exactly the part of ADR-0014's own output the original "utter ugly" complaint was aimed at; defeats half of the request this design responds to | Rejected |
| Reword `_OWNERSHIP_STATEMENT` | Keeps ADR-0037's substance in plainer language | None identified | Chosen |
| Drop the ownership statement | Shortest body | ADR-0037 requires it; not this design's decision to make | Rejected |
| Move the ownership statement to a GitHub PR template checkbox instead of body text | Could feel less like a disclaimer | A bigger structural change than a wording fix; a separate design's scope | Rejected here |

## Quality and risk

- **Security/privacy/reliability/concurrency/observability:** None. Pure
  string-literal and formatting changes; no new data, no control-flow
  change.
- **Compatibility risk:** The exact-string dependents listed in Current
  system and evidence are the concrete risk here — an update to wording
  that does not also update `tests/test_git_ops.py:1944`,
  `tests/test_integration_lifecycle.py:119`, and `tests/test_task.py:3074`
  fails CI immediately, which is the intended safety net, not a gap.
- **Accessibility/internationalization:** A small positive, consistent
  with the parent design.

## Test strategy

- Update `PrDescriptionTests` (`tests/test_task.py`, around line 2966) and
  `MarkReadyTests` (`tests/test_git_ops.py`, around line 1884) to assert
  on the new wording, preserving every existing assertion about *which*
  facts appear under which conditions (waived vs. passed vs. not
  reviewed, summary-fallback, and so on).
- Update `tests/test_integration_lifecycle.py:119`'s ownership-statement
  assertion to match the new wording.
- No new test dimensions: no new branch, field, or condition is
  introduced, so no new categories of test are needed beyond literal
  string updates, following the same "Testing needs (added)" precedent
  ADR-0014 itself set.

## Migration, rollout, rollback, and cleanup

None needed. The new wording takes effect the next time `open_pr()` or
`mark_ready()` runs. Already-open pull requests keep their current body
text until their next `mark-ready` call regenerates it — the same
behavior any prior wording change to this function has always had since
ADR-0014 shipped it. Rollback is a normal git revert.

## Open questions

Martin Urban owns both questions below.

| Question | Evidence needed | Blocking? |
|---|---|---|
| Do the confirmed exact-string dependents above cover every match, or does a fresh repository-wide search turn up more once final wording is drafted? | Re-run the search from this design against the final chosen wording before merging | Yes — blocks landing, not drafting |
| Should the Validation section move to a `<details>` block as a later structural follow-up? | Decision only; out of scope here | No |

## Acceptance

- [ ] Material decisions resolved.
- [ ] Required domain reviews complete.
- [ ] Accountable human accepts planning against this design.
