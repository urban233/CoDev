---
name: plan-delivery
description: Turn an accepted product or feature brief and any required design into a lightweight multi-developer delivery plan. Use when a team needs outcome-based milestones, ready work items, owners, independent reviewers, simple dependencies, integration checkpoints, WIP limits, risks, or rolling-wave planning. Do not create a separate architecture or capacity bureaucracy.
---

# Plan Delivery

Create a plan that helps a team choose the next useful work, not a prediction of
every future edit. Use `assets/delivery-plan.template.md` when the repository has
no external project tracker.

## 1. Verify planning inputs

Read the accepted brief and applicable design. Confirm the next outcome, fixed
contracts, important risks, available developers, current commitments, and
required reviewers. Return unresolved product questions to `define-product` and
architectural questions to `design-solution`.

## 2. Define outcome milestones

Each milestone must demonstrate observable value or retire a named risk, such as
"internal user completes the primary workflow." Avoid component-completion
milestones such as "backend done."

Plan the current milestone in detail. Keep later milestones coarse and revise
them using evidence from working software.

## 3. Create reviewable work items

Each current work item must include:

- outcome and acceptance criteria;
- relevant design/API links;
- owner and independent reviewer;
- dependencies and integration checkpoint;
- risk level: low, normal, high, or critical;
- expected validation; and
- status: discovery, ready, in progress, review, blocked, or done.

A work item should normally produce one small pull request or a short stack of
independently valid pull requests. Split by behavior, not by technical layer.

Use only ordinary dependency language:

- **Blocked by:** work cannot begin safely.
- **Integrates with:** work can proceed against an agreed contract or fixture;
  integration happens later.
- **Lands after:** source-control or migration order matters.

## 4. Coordinate the team

Default maximum work in progress to one implementation item per developer.
Assign by relevant capability and support, not title alone. Ensure owners do not
approve their own changes. Name an integration owner only for milestones that
cross ownership boundaries.

Treat review capacity as real work. Confirm reviewer availability before an item
becomes ready and define a small review queue limit (default two active reviews
per reviewer unless the team chooses otherwise). For high- or critical-risk
work, separately name any policy-authorized security, privacy, compliance, or
operations approver; never assume an ordinary code reviewer has that authority.

Track changing assignments, availability, and status in the existing project
tracker. Do not version them as architecture.

## 5. Check readiness

An item is ready only when its outcome, acceptance, required design decisions,
dependencies, owner, reviewer, and test environment are known. Use a bounded
discovery item when evidence is missing. Never disguise uncertainty as an
implementation task.

Review the plan with the team in one pass: current milestone, ready work,
parallel work, blockers, integration points, and risks. Update routine status
without formal approval; seek human decisions only for scope, priority, risk,
ownership conflicts, or commitments.

## Handoff

Give each developer only their work item, relevant brief/design/API links,
integration constraints, and acceptance criteria. Start `build-change` for the
next ready item.
