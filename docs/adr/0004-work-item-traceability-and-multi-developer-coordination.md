# ADR-0004: Work items gain traceability, identity, and multi-developer coordination

**Status:** Proposed
**Date:** 2026-08-11

## Context

ADR-0001 through ADR-0003 connect a work item to a landed pull request
end-to-end, but entirely for one developer acting alone. Nothing in
`work.py`, `git_ops.py`, or the bundle's planning skills (`define-product`,
`design-solution`, `plan-delivery`, `build-change`) links a work item back to
the content that authorized it, records who is doing it, or accounts for a
second developer's work happening at the same time. `codev work
start(work_item_id, base_snapshot, ...)` carries neither.

This gap was scoped by grounding it against Google's public engineering
practices rather than assumption: *Software Engineering at Google* (the
Flamingo Book) chapters on Code Review, Version Control and Branch
Management, Large-Scale Changes, Continuous Integration/Delivery, How to Work
Well on Teams, and Leading at Scale; the public `google.github.io/eng-practices`
review guide; and public documentation of Buganizer's component/assignee
model. Two findings from that research shaped this decision:

- CoDev's planning skills already produce content equivalent to Google's
  PRD/Design Doc/mini-design-doc — `plan-delivery`'s work-item shape
  (outcome, acceptance criteria, links, owner, reviewer, dependencies, risk,
  validation, status) is already close to a Buganizer bug. The real gap is
  traceability from `codev work`'s state-tracking layer back to that content,
  not a missing content model.
- Google's multi-developer coordination is not a separate planning layer —
  it is the properties of the code-review and version-control system itself.
  OWNERS files route review authority by directory. Trunk-based development
  plus small CLs shrinks, rather than eliminates, the window in which two
  developers collide. Buganizer routes a new item to a component's
  configured default assignee, and a human triage step then refines that
  assignment. The same "structural default, human-refined" shape recurs for
  both review authority and task assignment — Google does not solve these
  with two different systems.

The constraints from ADR-0002/0003 are unchanged: every step below executes
inside one human-triggered local run; no CI-triggered inference, bot
identity, polling, or webhook of any kind. Unlike ADR-0002/0003, this ADR
introduces no new agent role and does not change the inner/outer loop
protocol — it is entirely about the data a work item carries and a small
amount of new CLI surface beneath the existing protocol.

## Decision

### `codev work start` gains optional identity and traceability fields

Four new optional keyword arguments on `work.start()`, all `str | None`
(`github_issue` is `int | None`), stored as new top-level keys on
`round-state.json` alongside the existing `work_item_id`/`base_snapshot`:

- `--link` → `link_ref`: a pointer to the durable artifact that authorizes
  this work — a `docs/codev/...` path, a GitHub issue URL, anything. Stored
  verbatim, never read or parsed by `codev work`, for the same reason
  `base_snapshot` is never verified against actual git state: `work.py`
  stays state-only per ADR-0001.
- `--summary` → `summary`: a one-line human-readable description, for the
  common case where no upstream artifact exists at all (an obvious,
  low-risk fix per `ai-agent-guidelines.md`'s "Choose the path" table).
- `--owner` → `owner`: who is doing the work.
- `--github-issue N`: CLI-layer sugar only, not a persisted field. Before
  calling `work.start()`, `cli.py` resolves it via a new
  `git_ops.fetch_issue(number)` (a read-only `gh issue view N --json
  title,url` call) and uses the result to default `link_ref`/`summary`
  unless `--link`/`--summary` were also passed explicitly, which win.

`--owner` defaults to a new `git_ops.detect_identity()` when omitted:
prefer the authenticated GitHub login (`gh api user --jq .login`, matching
what `CODEOWNERS` entries and GitHub assignees are keyed by), falling back
to `git config user.name` when `gh` is unavailable or unauthenticated —
`codev work` must not gain a hard GitHub dependency it doesn't have today.
If neither resolves, `owner` stays `None`; no fabricated placeholder value
is written. All four fields are validated only for "non-empty if provided,"
the same rule already used for `override_reason`.

This keeps the existing architecture split intact: `git_ops.py` is where
subprocess calls to `git`/`gh` live; `work.py` never shells out, so calling
`work.start()` directly (as the test suite already does, and as
`codev work start` does only after `cli.py` has resolved the above) stays
fully hermetic. No `ROUND_SCHEMA_VERSION` bump — all four fields are
additive and optional, read back with `state.get("link_ref")` etc., the
same pattern `triage` and `expansion_reason` already use.

### `codev work triage` gains `--by`; `check` gains a non-blocking note

`--by`, defaulting through the same `git_ops.detect_identity()`, is stored
as `by` on the round's existing `triage` record (added by ADR-0003) next to
each finding's `address`/`defer` disposition. When a round's `triage.by`
equals the work item's top-level `owner`, `codev work check`'s CLI output
(and `log_text`) print an informational note that the same person authored
and triaged the change — the mechanical form of `plan-delivery`'s existing
"owners do not approve their own changes" guidance. This is output text
only: it adds no new `check()` outcome value and cannot change the exit
code. `check()`'s contract — what a caller must branch on — is unchanged.

### `docs/codev/` becomes the default root for planning artifacts

`define-product`, `design-solution`, and `plan-delivery` each get one
default path changed, prefixed under `docs/codev/` rather than directly
under `docs/`:

| Skill | Old default | New default |
|---|---|---|
| `define-product` | `docs/features/<slug>/brief.md`, `docs/product/<slug>/brief.md` | `docs/codev/features/<slug>/brief.md`, `docs/codev/product/<slug>/brief.md` |
| `design-solution` | `docs/design/`, `docs/features/<slug>/design.md` | `docs/codev/design/`, `docs/codev/features/<slug>/design.md` |
| `plan-delivery` | `docs/delivery/<milestone-slug>.md` | `docs/codev/delivery/<milestone-slug>.md` |
| `build-change` (new) | unspecified | `docs/codev/work/<work-item-id>/implementation-plan.md` |

This is a prefix, not a restructuring: the type-based grouping
(`design/`, `delivery/`, `features/`) is unchanged, so it stays as
discoverable to a newcomer as it is today, while gaining one common root a
human or future tooling can walk to find everything CoDev's planning skills
produced. Each skill's existing instruction to defer to an established
repository convention instead of forcing its own structure is unchanged —
this only changes what a *fresh* repository gets by default, and an
existing repository's already-adopted paths remain "the existing
convention" the skill defers to, with no migration needed.

The `build-change` implementation-plan default is new, not a rename: today
it is unspecified beyond "use `assets/implementation-plan.template.md`."
Keying it by `work_item_id` — the same id `codev work start` uses — is the
actual point: it makes the implementation plan the natural default value
for `--link` with no typing required, closing the traceability gap for the
one planning artifact that is genuinely 1:1 with a single work item. Brief,
Design, and Delivery plan stay N:1 (one Brief authorizes many work items
over time) and are not given a work-item-keyed path.

`docs/codev/` is deliberately distinct from `docs/for-ai/` and
`docs/for-human/`, which remain CoDev's own bundled, lock-tracked
documentation about the tool itself. `docs/codev/` holds a specific team's
own planning content, produced using CoDev's skills but never managed,
hashed, or tracked by `lock.json`.

### `codev git issue-create`

A sixth operation alongside `branch|commit|push|open-pr|mark-ready`, but the
only one with no work-item precondition: it has no `--id` and does not call
`codev work check`, because pushing a delivery-plan work item to GitHub
happens *before* `codev work start` — there is no round-state yet to check
against. This is a deliberate asymmetry with the other five operations, not
an oversight.

```
codev git issue-create --title <title> --body <body> \
  [--path <glob>]... [--assignee <login>]...
```

Title and body are supplied explicitly by the caller, the same precedent
`open-pr --title --body` already set — `codev` does not parse a delivery
plan's Markdown to extract a work item's content. `--path` (repeatable,
optional) triggers a best-effort suggestion: `git_ops.py` reads
`CODEOWNERS` (checking the three locations GitHub itself recognizes — repo
root, `.github/`, `docs/`) and resolves the given paths against it with the
same last-match-wins glob semantics GitHub uses, printing suggested owners
without forwarding them as `--assignee` automatically. This mirrors
Buganizer's default-assignee-then-human-refines shape honestly: CoDev
suggests, a human decides via an explicit `--assignee`. If no `CODEOWNERS`
file exists or no `--path` is given, the suggestion step is silently
skipped — this operation never requires `CODEOWNERS` to exist.

Duplicate prevention is a workflow convention, not a mechanical guarantee:
`codev work`/`codev git` hold no state about delivery-plan work items (they
aren't work items yet), so nothing here parses or rewrites the delivery
plan to check "was this already pushed." The orchestrator records the
returned issue URL back into the plan's own status column after a
successful push and checks for an existing link there before pushing again
— the same restraint already applied to `--link`/`link_ref`, not turning
`codev` into a Markdown parser for another skill's output.

`codev git open-pr` (ADR-0002) gains one small addition: when the work
item's `link_ref` matches `https://github.com/<owner>/<repo>/issues/<N>`
for the same repository the PR is being opened in, it appends `Closes #N`
to the generated PR body. This is intentionally narrow — it inspects only
CoDev's own previously-recorded field, never a foreign document — and gives
the full loop a free close on merge: push a work item as an issue, start
work with `codev work start --github-issue N`, open the PR, merge closes
the issue natively, no new logic required for that last step.

### `codev codeowners init`

A new top-level command, unrelated to `codev work`/`codev git`'s state and
mutation surfaces: it is a one-shot local file scaffold, requires no `git`
or `gh` subprocess call, and is expected to be run directly by a human
during repository setup — the same way `codev init` itself is — not
invoked by an agent mid-workflow. It checks all three locations GitHub
reads (`CODEOWNERS`, `.github/CODEOWNERS`, `docs/CODEOWNERS`) and refuses
with a clear message if any already exists, rather than overwriting. On a
clean run, it writes `.github/CODEOWNERS` (the conventional location) with
a syntax-explaining comment header and one commented starter line per
existing top-level repository directory, excluding well-known VCS/tooling
directories — naming what exists so a human only has to fill in the owner,
never inventing an ownership claim CoDev has no basis for.

Unlike `AGENTS.md` and the `.gitignore` block, this file is not a managed
integration: there is no `lock.json` entry, no hash tracked, no
`codev update`/`codev remove` awareness of it. Once scaffolded, the file is
entirely the team's own, matching how little CoDev-specific content it
ever contains.

### `codev status --verbose` gains non-blocking multi-developer visibility

Two additions, both computed at `status` time from data the fields above
already make available, neither persisted anywhere new and neither
blocking:

- **WIP per owner** — `describe_all()`'s results, which now include
  `owner`, are grouped by `owner` for every `status == "in_progress"` item
  and printed as a count. This makes `plan-delivery`'s existing "default one
  in-progress item per developer" guidance visible instead of only
  documented, without CoDev enforcing it — refusing a second item would
  contradict the project's own "human authority over material decisions"
  principle (a legitimate hotfix while another item is in review is not an
  error).
- **Changed-file overlap** — for every pair of concurrently `in_progress`
  work items, `git_ops` diffs each one's `base_snapshot` against its
  branch head (read-only `git diff --name-only`) and flags any path
  appearing in more than one item's changed set. Trunk-based development
  with small, fast-merging changes (already how the inner loop behaves)
  only shrinks this collision window, it does not remove it; this surfaces
  the remaining risk instead of leaving two developers to discover it at
  merge time.

### `_gh_executable` stays inside `git_ops.py`

The new `fetch_issue`, `create_issue`, and `detect_identity` all reuse the
`_gh_executable` resolution `git_ops.py` already defines — being in the
same module, this introduces no new duplication. The pre-existing
duplication between `git_ops.py` and the `pr-review` skill's
`publish_review.py` is unrelated to this ADR: `publish_review.py` is
distributed as a standalone script inside the bundle and is expected to run
without the installed `codev_workflow` package necessarily being
importable in that context, so unifying it with `git_ops.py` is a
packaging question this ADR does not resolve.

## Consequences

- Unlike ADR-0002/0003, no new agent role is introduced and no permission
  block needs a new grant for most of this: `codev work start`'s new flags,
  `codev work triage --by`, and `codev git issue-create` are all already
  covered by the existing `"codev work *": allow` / `"codev git *": allow`
  wildcards on every platform. `codev codeowners init` needs none at all,
  since it is expected to run outside any agent's permission surface, the
  same as `codev init`.
- `ai-agent-guidelines.md` and `plan-delivery`'s "Handoff" section need a
  documentation pass to reference `codev git issue-create` and
  `codev work start --github-issue` at the right point in the flow (after a
  delivery-plan item is marked ready, before implementation starts). Not
  done as part of this ADR.
- `docs/architecture.md` will need a line documenting the `docs/codev/`
  convention and the new CLI surface, the same follow-up pattern
  ADR-0002/0003 left open for their own additions.
- `ROUND_SCHEMA_VERSION` stays at 2. Every new `work.py` field in this ADR
  is optional and additive; an in-flight work item created before this ADR
  reads back `None` for all of them with no migration and no version guard
  change.
- `codev adapter verify` needs no new required-marker checks: this ADR adds
  CLI surface, CLI-layer identity resolution, and skill-default paths, not
  new agent roles or a changed protocol, so there is nothing new for it to
  verify per platform.
- Testing needs: round-trip coverage for the four new `work.py` fields
  (present and absent), `git_ops` tests for `fetch_issue`/`create_issue`/
  `detect_identity` mocking only `_run_gh` (not `git` itself, consistent
  with the existing `git_ops` test suite), conflict/refuse-to-overwrite
  tests for `codev codeowners init`, and `status --verbose` tests for the
  WIP and overlap output.
- Implementation should proceed in `build-change`-sized pieces per
  component (work-item fields, triage `--by` and the note, the
  `docs/codev/` skill-default changes, `issue-create`, `codeowners init`,
  `status --verbose` visibility), consistent with this project's own size
  guidance and with how ADR-0002/0003 were implemented.
