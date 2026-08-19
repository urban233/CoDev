---
name: design-solution
description: Create or revise a practical technical design for a significant feature, product, migration, or cross-component change. Use when engineers need architecture, component ownership, APIs or contracts, data flow, trade-offs, risk controls, test strategy, or rollout design before implementation. Skip this skill for local low-risk changes with an obvious implementation.
---

# Design Solution

Help the developer make the few technical decisions that must be shared before
parallel implementation. Use `assets/design.template.md`; use
`assets/adr.template.md` only for a durable cross-cutting decision that must
outlive the design document -- an Architecture Decision Record (ADR).

## 1. Establish context

Read the accepted brief, relevant repository instructions, current architecture,
code, tests, and prior decisions. Confirm the design still solves the stated
outcome. Return to `define-product` if the outcome or scope is the real problem.

State which decisions the design must settle and which details can safely remain
with implementing engineers.

## 2. Investigate before proposing

Locate existing components, ownership, extension points, schemas, APIs, failure
conventions, deployment model, and comparable implementations. Distinguish
verified repository facts from assumptions.

For material choices, present the recommended option, meaningful alternatives,
and trade-offs. Ask the human only when alternatives change product behavior,
an interface, persistent data, risk, cost, or ownership.

## 3. Design stable boundaries

Describe components in ordinary language. For every cross-component API or
contract, define:

- owner, callers, and purpose;
- request/event/data shape or authoritative reference;
- guarantees and caller obligations;
- validation, errors, timeouts, and retries;
- compatibility and migration expectations; and
- a contract-level test or fixture when parallel work depends on it.

Do not prescribe classes, private methods, file layouts, or algorithms unless
they are genuinely architectural.

## 4. Design quality and delivery

Cover proportionate concerns:

- security, privacy, permissions, abuse, and data retention;
- reliability, concurrency, observability, capacity, and cost;
- accessibility and internationalization;
- unit, contract, integration, end-to-end, performance, and failure testing;
- migration, feature flag, rollout, rollback, and cleanup; and
- unresolved risks with an owner and evidence-producing next step.

Prefer a thin end-to-end path that can be tested early.

## 5. Review and accept

Save product designs under `docs/codev/design/` or feature-local designs under
`docs/codev/features/<slug>/design.md`, following repository conventions. Name
an owner and required domain reviewers. Keep open questions visible.

Mark the design `Accepted` only after material decisions are resolved and the
human confirms it is safe to plan against. Git history records revisions.
Implementation discoveries may update the design; explain affected work rather
than invalidating unrelated plans automatically.

Write an ADR (`assets/adr.template.md`) only for a decision that must outlive
this design document -- a choice other future designs will need to find and
respect, not a detail local to this one. Save it at `docs/adr/NNNN-slug.md`,
`NNNN` the next four-digit, zero-padded sequence number after the highest one
already in `docs/adr/` (start at `0001` if the directory doesn't exist yet).
An ADR is append-only once `Accepted`: never edit a past ADR's `Context` or
`Decision` to reflect new information -- write a new ADR and mark the old one
`Superseded by ADR-NNNN` instead. Link it from the design document; do not
duplicate its content there.

## Handoff

Send the accepted brief, design, API/contract references, open risks, and next
demonstrable outcome to `plan-delivery`. Do not assign people or generate an
exhaustive task list.
