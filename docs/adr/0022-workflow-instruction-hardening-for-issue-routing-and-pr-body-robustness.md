# ADR-0022: Workflow-instruction hardening for issue routing, PR-body robustness, and reviewer narration

**Status:** Accepted
**Date:** 2026-08-14

## Context

Four smaller gaps surfaced from the same CLIP-session analysis that produced
ADR-0020 and ADR-0021, all "workflow-instruction surface only" — no schema
or CLI change needed, the same class of fix as ADR-0010/0019 — bundled into
one combined edit across all four platform adapters plus the canonical
`.codev/for-ai/ai-agent-guidelines.md`, the same precedent CHANGELOG 0.2.2
already used for ADR-0017/0018/0019 landing together.

**Issue-creation routing gap.** `orchestrator` step 5 only ever *passed
through* `--github-issue <N>` when a link already existed; nothing told it
to check and create one when the session never routed through
`plan-delivery`'s Handoff first (exactly the real L-03 gap ADR-0020's CLI
gate now surfaces, but the prompt never told `orchestrator` to resolve it
proactively). ADR-0020 is the mechanical backstop; this ADR is the
instruction that acts on it before the CLI has to refuse.

**Shell metacharacter corruption in body text.** Both `codev git issue-create`
and `codev git open-pr` have supported `--body-file` since ADR-0014 —
confirmed unused in both CLIP sessions examined: issue #11 in L-03 and PR #9
in L-02 each had their Markdown backticks corrupted by shell interpolation
before `codev` ever saw the text, before and after 0.2.2. `open-pr` itself
already avoids this structurally (`orchestrator`/`outer-loop-runner` are both
already instructed to never pass `--body`, relying on the auto-generated
description instead) — the live exposure is entirely at `codev git
issue-create` time, which has no such fallback and always needs literal body
text.

**PR-description narrative is thinner than the mechanism allows.** Grepping
the entire bundle found zero references to `--description` anywhere in any
agent prompt — `work.start()`'s `--description` argument (ADR-0014) has
never actually been wired into any platform's instructions since it was
added. Every PR body CoDev has ever generated therefore falls back to
`summary`, a one-line restatement, regardless of how much substance the
approved implementation plan actually contained.

**Unnarrated fetch step.** `outer-loop-runner` step 1 runs
`publish_review.py --fetch` — read-only, dry-run, exactly the mechanism
`pr-review`'s own skill file documents — without ever telling the human what
it does or why, despite `ai-agent-guidelines.md`'s own "state the current
step and why it matters, in plain language" principle already asking for
this generally.

## Decision

**4a.** `orchestrator` step 5 (all four platforms) and
`ai-agent-guidelines.md`'s "Three-agent Build execution" point 1 now
instruct: before opening round state, check whether the work item has a
linked GitHub issue; if the repository tracks issues on GitHub and none
exists yet, run `codev git issue-create` now — per `plan-delivery`'s
Handoff, check rather than assume an earlier session already did it — then
call `codev work start` with `--github-issue <N>`, `--link`, or
`--no-github-issue` (ADR-0020's gate requires one of the three). If linkage
is only resolved after round state already exists, use `codev work relink`
rather than leaving the link only in the implementation plan's prose.
`adapter.py`'s `_REQUIRED_MARKERS["orchestrator"]` gains `"codev git
issue-create"` and `"--no-github-issue"`, the same lock-in precedent 0.2.2
already used for `--github-issue` itself.

**4b.** Everywhere `codev git issue-create` is instructed —
`orchestrator` (all four platforms), `ai-agent-guidelines.md`, and
`plan-delivery/SKILL.md`'s Handoff — gains one clause: write the body to a
temp file and pass `--body-file` instead of inline `--body` whenever it may
contain a backtick, `$`, or double quote, since a shell corrupts those
before `codev` ever sees the text. `plan-delivery`'s Handoff also now notes
that `orchestrator` may resolve issue linkage itself when a direct-build
session skips the Handoff — cross-referencing 4a so the two paths don't read
as contradictory.

**4c.** `orchestrator` step 3 (all four platforms) and
`ai-agent-guidelines.md` point 1 now instruct keeping a short 2-4 bullet
Approach/Risks summary from the rendered implementation plan in mind; step 5
passes it as `--description <text>` at `work start` time alongside the
issue-linkage flags, whenever the full template was rendered (the same
existing size/risk gate that already decides this). A bounded item that
only ever gets `--summary` degrades gracefully, unchanged.
`build-change/SKILL.md` gains a cross-reference noting its Approach/risk
sections are what feeds this, so they stay readable on their own rather than
assuming repository context. No `work.py` change: `pr_description()` already
renders `description` verbatim; this is entirely about actually populating
the argument that has existed, unused, since ADR-0014.

**4d.** `outer-loop-runner` step 1 (all four platforms) and
`ai-agent-guidelines.md`'s "Outer-loop execution" point 1 now open with an
instruction to state plainly, before running it, that this step is a
read-only fetch of the PR's metadata/diff/CI status via the pr-review
skill's fetch script — not a review, not a write to GitHub.

## Consequences

- No `work.py`/`git_ops.py`/schema change anywhere in this ADR — entirely
  bundle-file and canonical-guidelines prose, plus two new `adapter.py`
  required markers for 4a.
- Testing needs (added): `tests/test_adapter.py`'s existing bundle-parity
  test already re-verifies all four platforms carry the two new required
  markers; no new executable surface for 4b-4d to unit-test, covered by the
  existing `scripts/validate-development-workflow.py` scenario catalog and
  adapter conformance checks per this project's own precedent for
  prompt-only changes.
- 4c's `--description` enrichment depends entirely on the model actually
  following the new instruction — same category of reliance as every other
  prompt-level checkpoint in this system, not a new risk class introduced
  here.
