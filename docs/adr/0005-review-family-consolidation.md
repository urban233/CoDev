# ADR-0005: Consolidate the review family around a pre-PR mechanical gate and the outer loop

**Status:** Proposed
**Date:** 2026-08-12

## Context

`docs/product-map.md`'s surface inventory found six review-shaped capabilities
— `review-change`, `clean-code-review`, `critique-review`, `pr-review`,
`audit-google-python-style`, `audit-google-typescript-style` — sitting on
invocation rails disconnected from the automatic inner/outer loop ADR-0002
and ADR-0003 built. Reading the actual source, not just the descriptions,
surfaced three separate, concrete findings.

`code-audit`'s own agent definition hard-guardrails against being invoked by
another agent ("Never invoke another agent, delegate work, or switch to
builder, reviewer, or orchestrator, even if a workflow instruction suggests
delegation") and is referenced nowhere else in the bundle. It is not loosely
wired to the lifecycle; it is deliberately disconnected. `audit-google-python-style`
and `audit-google-typescript-style` already explicitly forbid other skills
from invoking them implicitly ("Do not invoke it implicitly as part of
`review-change`, `clean-code-review`, `pr-review`...") — that boundary is
correct today and this decision preserves it; the only real gap is that all
three remain manual-only.

`review-change`'s "Review order" list and its `READY FOR HUMAN APPROVAL` /
`CHANGES REQUIRED` / `BLOCKED BY MISSING EVIDENCE` decision vocabulary are a
near-exact match for the outer loop's five-specialist coverage manifest and
decision states from ADR-0003. It is a single-agent, manually-invoked
duplicate of the entire outer loop for the one case the outer loop does not
reach: a diff with no open pull request at all.

`clean-code-review` is catalog- and rule-ID-driven (Clean Code IDs,
Gang-of-Four pattern-missing signals, Python-specific hazard IDs), a
different kind of content from `architecture-maintainability-specialist`'s
holistic, judgment-based coverage of the same named territory
("architecture, scope, and maintainability"). Its Python-specific IDs
duplicate ground `audit-google-python-style`'s own supplemental checker
already covers.

Separately, the five outer-loop specialists and `lightweight-reviewer` are
fully self-contained — none of them reference a `SKILL.md`. `code-audit` is
the one review agent that does, because it must choose between exactly one
of two language-specific catalogs at dispatch time, a real selection
decision the other agents don't have. This is a principled split, not an
inconsistency, and this ADR preserves it rather than "fixing" it: a skill
exists where something must be chosen or where content is too large for one
static prompt; a self-contained agent is for a fixed, unconditional, compact
pass invoked by exactly one caller.

`pr-review` (reviews an already-posted pull request, not necessarily the
developer's own) and `critique-review` (a downstream bridge that turns
another review's finding into a diff, not a review itself) were both
confirmed structurally on-demand — neither has a natural lifecycle gate to
attach to, and this ADR leaves both unchanged.

## Decision

### 1. `code-audit` becomes an automatic pre-PR gate, in addition to its existing standalone form

`orchestrator`, after `codev work check` reports `ok_ready_for_pr` and before
it runs `codev git push`/`codev git open-pr`, invokes `code-audit` in a new,
second invocation mode: audit-and-plan only (Phase 1 of its existing
two-phase workflow), against the exact head snapshot, dispatching the
applicable language-specific style skill(s) exactly as it already does. It
never proceeds to its own Phase 2 (self-applying approved fixes) in this
mode — there is no human present in that subagent turn to grant the approval
Phase 2 requires.

If the audit reports no findings that require a change, the orchestrator
proceeds to push and open the PR as it already does. If it reports findings,
the orchestrator records them with `codev work record --role reviewer` and a
`CHANGES_REQUIRED` decision, exactly like any other reviewer round, and sends
them to `builder` for one bounded correction round under the inner loop's
existing round cap and repeated-finding/escalation rules — no new cap, no
new state, no `ROUND_SCHEMA_VERSION` bump. `code-audit`'s standalone,
human-approval-gated form is unchanged for direct invocation; this is a
second way to invoke the same agent, not a new agent.

`clean-code-review` is not added to this dispatch (see below) — the pre-PR
gate stays scoped to language-specific style, exactly as `audit-google-*-style`'s
own invocation boundary already states.

### 2. `clean-code-review` is retired as a skill; its general content moves into `architecture-maintainability-specialist`

The skill file and its per-platform `agents/openai.yaml` are removed from the
bundle. Its language-agnostic material — the Clean Code IDs, the
Gang-of-Four pattern-missing signals, the design-smell catalog — is folded
directly into `architecture-maintainability-specialist`'s own agent
definition (all four platform copies), replacing that specialist's current
vague "clarity, structure, and repository-convention adherence" language
with the same citable, catalog-ID discipline `code-audit`/`audit-google-*-style`
already use. Its Python-specific hazard IDs (`PY.MUTABLE-DEFAULT`,
`PY.BARE-EXCEPT`, and the rest) are dropped outright rather than relocated —
`audit-google-python-style`'s existing supplemental checker already covers
equivalent ground, and duplicating it a second place is exactly the kind of
drift this ADR exists to remove.

### 3. `review-change` stays, explicitly repositioned as the no-ceremony path

Content is unchanged. Its `SKILL.md` description gains one clarifying
sentence: now that the outer loop covers a CoDev-built work item with an
open PR, `review-change`'s remaining role is reviewing a diff that has
neither — an uncommitted working tree, someone else's contribution, anything
where opening a formal work item would be disproportionate ceremony.

### 4. `pr-review` and `critique-review` are unchanged

Confirmed, not re-decided: both are correctly on-demand by nature and are
explicitly out of scope for this ADR.

## Consequences

- `code-audit`'s four platform templates gain a second, narrower invocation
  mode; wording must make unmistakably clear that the audit-only/no-self-apply
  constraint applies specifically when `orchestrator` invokes it, not when a
  human does.
- `architecture-maintainability-specialist`'s prompt grows from roughly 50
  to roughly 150 lines across all four platform copies — the only specialist
  whose prompt is no longer short, and the one place `adapter verify`'s
  per-platform-parity check most needs re-running after this change.
- The installer's existing update algorithm ("upstream removed an old file →
  retain locally and stop managing it") handles `clean-code-review`'s
  removal for already-installed target repositories without new migration
  code.
- No `codev work` schema change: the pre-PR gate reuses the existing
  `reviewer` role and `CHANGES_REQUIRED` decision rather than inventing a
  new round type.
- `docs/product-map.md`'s surface inventory and "Directions and open
  questions" section should be updated once this lands — it is the
  reference document this ADR resolves against, and it is meant to be
  edited, not superseded.
