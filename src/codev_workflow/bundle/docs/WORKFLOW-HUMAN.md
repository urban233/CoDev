# Product Development Workflow

This workflow helps developers and AI build software together. Humans remain
accountable for product intent, material design decisions, code acceptance, and
release authorization. AI investigates, proposes, implements, validates, and
reviews bounded work with frequent human checkpoints.

The workflow uses familiar engineering artifacts and scales with risk. It is not
an autonomous coding loop and it does not require every change to produce every
document.

For complete setup and operating guidance, use the companion handbooks:

- [Google-inspired Python project setup](handbooks/PYTHON-PROJECT-HANDBOOK.md)
- [Google-inspired language-agnostic project setup](handbooks/LANGUAGE-AGNOSTIC-PROJECT-HANDBOOK.md)
- [Idea-to-production human-AI delivery](handbooks/IDEA-TO-PRODUCTION-HANDBOOK.md)
- [Four common workflow recipes](WORKFLOW-COOKBOOK.md)
- [Ready-to-use workflow prompts](AI-WORKFLOW-PROMPTS.md)

## Start here: four steps

Developers do not need to learn or select the skills below. Describe the change
in normal language; the AI routes it and explains why any design or planning is
needed.

1. **Understand:** agree on the outcome. Resolve material architecture and team
   coordination only when the change needs them.
2. **Build:** implement and validate one bounded, reviewable change.
3. **Review:** independently inspect the exact change and its evidence.
4. **Ship:** authorize controlled exposure, observe it, and learn.

Small fixes can move directly from Understand to Build. Design and delivery
planning deepen Understand; they are not mandatory extra stages.

## Choose the lightest safe path

| Path | Use for | Flow |
|---|---|---|
| Quick change | Local, reversible, low-risk fixes or refactors | Issue -> build -> review -> merge |
| Feature | Bounded user-visible or cross-file behavior | Feature brief -> optional design -> build/review loops -> rollout |
| Product, modular | New products, cross-team systems, migrations, or high-risk work | Product brief -> design -> delivery plan -> build/review loops -> launch |
| Product, guided | Greenfield or whole-product blueprint where one continuous interview is helpful | `SPECIFICATION.md` with product/design checkpoints -> delivery plan -> build/review loops -> launch |

Security, privacy, permissions, public APIs, persistent data, billing,
compliance, and destructive behavior always require explicit design and review,
even when the diff is small.

## Lifecycle and skills

```text
Idea
  -> specify-project      Optional guided facade: product frame + design in one specification
     OR
  -> define-product       Modular path: why, users, outcome, scope, success
  -> design-solution      Modular path: architecture, APIs, trade-offs, risk
  -> plan-delivery        Milestones, work items, owners, dependencies
  -> build-change         Interactive plan, implementation, validation
  -> review-change        Independent evidence-based review
  -> launch-product       Readiness, staged rollout, measurement, learning
```

`specify-project` combines the first two forms of thinking for a new or
whole-product blueprint; it does not add a lifecycle stage. It asks one
recommendation-led question at a time, accepts the product frame before the
technical design, and creates one canonical `SPECIFICATION.md`. Do not also
create a brief and design containing the same facts.

Small work may enter at `build-change`. A feature may skip `design-solution`
when there is no material technical decision. A product uses either the guided
specification or the modular brief/design path, and only the current milestone
is planned in detail.

## Canonical artifacts

| Artifact | Purpose | When needed |
|---|---|---|
| Project specification | Combined product frame and high-level technical blueprint with separate acceptance checkpoints | Optional guided path for greenfield or whole-product definition |
| Product or feature brief | Outcome, users, success, scope, non-goals | Features and products |
| Design document | Architecture, ownership, APIs, trade-offs, quality and rollout | Material or risky technical change |
| Delivery plan or project tracker | Milestones, ready work, owners, reviewers, dependencies, status | Multi-developer work |
| Implementation plan | Repository-grounded steps and validation for one work item | Complex, risky, or cross-session changes |
| Pull request/change | Small implementation plus tests | Every code change |
| Launch plan | Readiness, exposure stages, thresholds, rollback, learning | Material releases |

Git history is the revision record. Use `Draft`, `Accepted`, `Active`, and
`Superseded` for document state. Version APIs and schemas when consumers need a
compatibility contract; do not invent a second revision system for planning
documents.

## How a developer works with AI

For each work item:

1. **Frame:** agree on the outcome, acceptance criteria, non-goals, and risk.
2. **Inspect:** AI reads the current repository, relevant design, tests, and
   conventions. It separates verified facts from assumptions.
3. **Plan:** AI proposes the smallest coherent change and validation. The human
   decides any product, API, data, security, dependency, or architecture choice.
4. **Build:** AI edits one reviewable slice and shares concise progress at
   meaningful boundaries.
5. **Verify:** AI runs formatting, static checks, affected tests, and
   proportionate broader tests, then inspects the complete diff.
6. **Review:** an independent human reviews every change. A fresh AI review is
   recommended for normal or higher-risk changes.
7. **Accept:** the human inspects the exact diff and authorizes commit or merge
   according to repository policy.

The AI stops when required behavior conflicts, a material decision is missing,
the base changed unexpectedly, concurrent work collides, or required evidence
cannot be produced. It gives facts, a recommendation, and one precise question.

Immediately before editing, the AI presents a short focus card: change,
observable success, non-goals, allowed scope, validation, stop conditions, and
whether the work remains interactive pairing or is safe for bounded delegation.
When implementation finishes, it returns an evidence receipt containing what
changed, validation actually run, acceptance evidence, deviations, limitations,
and review state. Neither requires a separate document for ordinary work.

On a subagent-capable platform, the developer stays in one orchestrator
conversation. The orchestrator creates the plan, sends it to a bounded editing
builder, sends the exact resulting snapshot and evidence to a fresh read-only
reviewer, and routes findings back automatically. The human does not copy
messages between agents, but still approves delegation, material plan changes,
merge, and release. Use separate branches/worktrees and orchestrator sessions
for concurrently executing work items.

## Multi-developer rules

### Own components and APIs

Each important component or API has a team or person responsible for design,
review, compatibility, and operation. Describe these in the design document or
repository ownership configuration; do not maintain a separate ownership graph
unless it provides independent value.

### Agree on contracts before parallel work

Two developers may work concurrently when they share an accepted API/schema and
a contract fixture or test. Record ordinary relations in the tracker:

- **Blocked by:** work cannot begin safely.
- **Integrates with:** work proceeds against a contract; integration occurs at a
  named checkpoint.
- **Lands after:** merge or migration order matters.

### Keep work and branches small

Prefer short-lived branches and one-purpose pull requests. Incomplete behavior
may merge behind a feature flag when the intermediate state is safe. Revalidate
after updating the target branch. Shared migrations, generated files, schemas,
and other hotspots need one named coordination rule.

### Limit work in progress

Default to one implementation item per developer. Queue additional work instead
of opening several half-finished changes. The owner and reviewer must differ.
Name an integration owner only where several work items meet.

## Team operating rhythm

- Review outcomes, the current milestone, and major risks weekly.
- Review architecture and API changes when they arise, not in recurring ritual
  meetings without a decision.
- Select one ready work item per developer.
- Merge small validated changes continuously.
- Demonstrate working behavior at every milestone.
- Plan the next wave using evidence from the demonstration and production.
- Treat launch as a measured learning cycle, not a finish line.

## Quality and approval

Automation supplies evidence; it does not approve work. The implementing AI
cannot approve its own change. Reviewer readiness does not authorize merge.
Merge, deployment, data migration, publication, and rollout expansion require
the responsible human action or the repository's established approval policy.

High- and critical-risk work may additionally require security/privacy review,
two-person approval, immutable test suites, restricted tool permissions,
staging, canaries, and tested rollback.

## Maintenance rule

Every fact has one owner:

- outcome and scope live in the brief, or in the accepted specification when
  using the guided path;
- architecture and contracts live in the design/API source, or in that same
  accepted specification;
- assignment and status live in the tracker;
- code behavior lives in code and tests;
- durable rationale lives in a design decision;
- rollout state and evidence live in the launch record and observability system.

Link to facts instead of copying them. Add process only when it prevents a named
failure and cannot be enforced by existing code, tests, CI, ownership, or
deployment tooling.

Workflow rules are also software behavior. Changes to `AGENTS.md`, skills, or AI
workflow policy should be exercised against the repository's behavioral
scenarios. An external harness, human, or independent AI records observable
actions and evidence; the agent being evaluated does not score itself, and
private reasoning is never required.

```text
python scripts/evaluate-development-workflow.py
python scripts/evaluate-development-workflow.py --write-template <results.json>
python scripts/evaluate-development-workflow.py --results <results.json>
```

The first command validates the six-scenario catalog. The second creates an
observation record for an evaluation run; the third scores the completed record
and fails when a required behavior lacks evidence.

## Migrating from workflow v2

The earlier ADS/MDG/EWP/ALLOC/SPEC files remain historical evidence. They are
not the guided path's canonical `SPECIFICATION.md`. Do not rename them or treat
their custom revision codes as current approvals.

For active work:

1. summarize the approved product outcome and non-goals in a brief;
2. carry forward only current architecture, API contracts, decisions, and risks
   into a normal design document;
3. put current milestones, work items, owners, reviewers, dependencies, and
   status in the project tracker or delivery plan;
4. convert only the next active EWP into a small work item or implementation
   plan; and
5. archive the old planning packet after the human confirms nothing active was
   lost.

No semantic migration is automatic; the responsible human confirms the new
brief, design, and current plan.
