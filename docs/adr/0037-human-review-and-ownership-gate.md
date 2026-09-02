# ADR-0037: An independent human approval, distinct from the task owner's signature, gates merge readiness

**Status:** Accepted
**Date:** 2026-09-02
**Owner:** Martin Urban
**Related design:** [docs/features/unified-workflow/brief.md](../features/unified-workflow/brief.md)

## Context

CoDev exists so that AI-generated code is reviewed rather than merged
reflexively. Its review architecture is genuinely layered: a fast
correctness check after each build round, an automatic style and
documentation gate immediately before a pull request opens (ADR-0015), and
five parallel specialist reviewers once it is open (ADR-0016, ADR-0018).
None of that is a human review, and the model does not currently say so.

`task.check` returns `ok_approve` once the specialists' findings are
resolved and the coverage manifest is complete
(`src/codev_workflow/task.py:732`). In a tool whose pitch is that generated
code is not merged as slop, naming that state "approve" invites exactly the
conflation it exists to prevent.

The pieces for a human gate exist and are unwired. `codev codeowners init`
scaffolds a `.github/CODEOWNERS` file that nothing subsequently consumes.
CODEOWNERS is read in only one place, to suggest an assignee for a newly
created issue (`src/codev_workflow/git_ops.py:300`), and never to request a
reviewer on a pull request — `open_pr` has no reviewer argument at all.
`plan-wave` names an owner and an independent reviewer per task and
instructs that owners must not approve their own changes, and that name
never leaves the wave plan's prose.

Google's published practice separates three approvals that are easy to
conflate. **LGTM** records that a competent engineer read the change and
believes it correct. **OWNERS approval** records that an engineer accountable
for that directory consents to the change landing there; it is path-scoped
and hierarchical, and `.github/CODEOWNERS` is the approximation GitHub
offers. **Readability** is a language-level certification: if the author does
not hold it, someone who does must sign off. One person may supply all three,
but the roles stay distinct, and an author never approves their own change.

The distinction that matters here is that the second reviewer is not a second
opinion on correctness. LGTM says "this is right." OWNERS says "I will own
this."

AI-directed work adds a specific trap, which the brief states in full:
directing a change is authorship, however little of it a person typed. The
consequence recorded here is that the task owner's signature must mean "I own
this," never "I approved it."

## Decision

Merge readiness requires **one approving review from a human who is neither
the task owner nor a bot**, recorded on the pull request by GitHub, and
**separately** an explicit ownership signature from the task owner.

Concretely:

- The **task** owns its owner and its independent reviewer, per
  [ADR-0035](0035-slice-is-the-unit-of-execution.md). Both are named by
  `plan-wave` where a wave plan exists, and resolved from `.github/CODEOWNERS`
  for the touched paths otherwise. A slice inherits both from its task.
- `codev git mark-ready` requests review from that reviewer on the slice's
  pull request, and writes the task owner's ownership statement into the
  pull-request body in wording that cannot be read as an approval.
- The independent reviewer must not be the task owner. Where CODEOWNERS
  resolves only to the task owner, that is a condition to surface to the
  human, not a case to approve automatically.
- `task.check`'s `ok_approve` is renamed to say what it means — that the
  machine gates are satisfied — and a distinct `ok_human_approved` reads
  GitHub's review state. [ADR-0036](0036-cli-is-an-agent-interface.md)'s oracle
  reports the difference so the agent can surface it unprompted.
- **Two** approvals are required only for changes labelled `risk:high` or
  `risk:critical` — labels `.github/ISSUE_TEMPLATE/task.md` already defines —
  or for a configured sensitive path set. Not for everything.
- The five specialist reviewers **never** count toward an approval under any
  configuration. Their findings stay in the pull-request body as clearly
  labelled machine evidence.

CoDev does not enforce the merge itself. GitHub's branch protection does, and
this decision is what makes CoDev's own state honest about it.

## Alternatives considered

- **Require two human approvals on every change:** rejected. For the two-to-
  ten-engineer team CoDev targets, a universal second approval will be routed
  around rather than honored, and Google does not require it either. Risk
  labels already exist to mark the changes that warrant it.
- **Let the five specialists satisfy the human gate when coverage is
  complete:** rejected outright. This is the failure CoDev exists to prevent,
  and no configuration should express it.
- **Let the task owner approve their own pull request, on the grounds that
  the AI wrote the code:** rejected. Directing a change is authorship. The
  ownership statement exists precisely so the owner's accountability is
  recorded without being mistaken for review.
- **Leave `ok_approve` named as it is and document the distinction:**
  rejected. The accepted brief's governing principle is that anything an
  agent must get right should be a value it reads rather than a paragraph it
  interprets, and a misleading state name is read far more often than the
  paragraph correcting it.
- **Implement a CoDev-native approval record instead of reading GitHub's:**
  rejected. GitHub already holds the authoritative review state, branch
  protection already enforces it, and a parallel record would drift.

## Consequences

- CoDev acquires a read dependency on GitHub's review API for
  `ok_human_approved`. Whether that API distinguishes an author's own approval
  from an independent one on every plan tier is recorded in the brief as an
  assumption to confirm before design.
- A repository with no `.github/CODEOWNERS` and no wave plan cannot resolve an
  independent reviewer. That is a state to report, not to default around;
  `codev codeowners init` becomes agent-invocable under
  [ADR-0036](0036-cli-is-an-agent-interface.md) partly for this reason.
- Renaming `ok_approve` is an observable behavior change for anything reading
  `task.check`'s output, including `codev git open-pr`'s and `mark-ready`'s own
  gate checks and any adopter script. It needs a deprecation path.
- The machine style gate (`code-audit-gate` and the `audit-google-*-style`
  skills) covers the readability axis mechanically and stays mechanical. Per
  the brief, the corresponding human judgment becomes a stated expectation of
  the independent reviewer rather than an assumed by-product of that gate.
- Solo adopters cannot satisfy this gate, by construction. That is correct —
  the gate encodes a team's review policy — and such a repository must be able
  to record that it is deliberately operating without one, rather than
  silently failing every task.

## Revisit when

GitHub changes how review state distinguishes authorship, or adopters report
that the risk-label threshold for a second approval is landing in the wrong
place — either routinely bypassed, or routinely triggered on changes that do
not warrant it.
