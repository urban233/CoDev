# CoDev Onboarding Guide

*Start here.* This is the short version — what CoDev does, the mental model behind it, and
what a day of work actually looks like. Want to just try it right now instead of reading
first? [Tutorial 1](../tutorials/01-your-first-fix.md) walks one small bug fix start to
finish. For a command-led daily workflow once you know the shape, see
[normal-development-workflow.md](normal-development-workflow.md). For the full technical
map (every command, skill, and agent), see the CoDev project's `docs/product-map.md`.

## The problem

AI can now write plausible code faster than a human can review it. That creates a new
failure mode: velocity without accountability. A model can invent an API that doesn't
exist, "fix" a test by weakening it, or quietly expand a bug fix into a redesign — and do
all of it fluently enough that a tired reviewer skims past it. CoDev exists to make
AI-assisted development fast *without* being unaccountable.

## The mental model

Think of CoDev as a narrow waist between what you actually want (an outcome, a design
decision, a bug report) and the diff that delivers it. Three ideas carry almost all of its
behavior:

- **Repository grounding.** An AI's claims about how the code works are worth nothing
  until checked against the actual files. Every skill starts with inspection, not
  proposal.
- **One fact, one owner.** Outcome and scope live in a brief. Architecture lives in a
  design document. Assignment and status live in a delivery plan. Behavior lives in code
  and tests. Nothing gets copied between documents — later documents *link* to earlier
  ones. If you find yourself updating the same fact in two places, one of those places is
  wrong.
- **Small, reviewable, evidence-backed changes.** A change is done when it's small enough
  to review, validated with commands you can rerun, and an independent reviewer — human,
  and automatically also AI — has looked at the *exact* diff.

If you remember nothing else: **the AI supplies evidence, you supply authority.**

## A running example

Say your checkout total is wrong: a discount applied to a tax-exempt item is still being
taxed. That one bug threads through every section below, and it's the exact example
[Tutorial 1](../tutorials/01-your-first-fix.md) builds end to end with real commands.

## The four steps you'll actually see

You never have to name a skill. Describe what you want, and CoDev resolves it to one of
four steps:

| Step | Question it answers | The checkout example |
|---|---|---|
| **Understand** (`define-product`) | What are we building, and what has to be decided first? | Nothing to decide here — the expected behavior is unambiguous: tax-exempt items don't get taxed, discounts still apply. Straight to Build. |
| **Build** (`build-change`) | What's the smallest change that delivers this, with evidence it works? | Fix the total calculation so tax-exempt status is checked before tax is applied, not after. Add a regression test with a tax-exempt, discounted item. |
| **Review** (`review-change`, plus an automatic pass) | Is this exact change correct, safe, and consistent with what we agreed? | Confirm the fix doesn't break the case where a *taxable* item has a discount — a real, narrow correctness check, not a style nit. |
| **Ship** | Are we ready to expose this, and how will we know it's working? | A pricing bug fix like this usually ships straight through — no staged rollout needed unless checkout volume or revenue risk says otherwise. |

A small, local, reversible fix like this one goes **Understand → Build → Review → Ship**
in minutes, with Understand collapsing to "here's the bug, here's the expected behavior."
A new product spends real time in Understand instead, because getting the outcome and
architecture right is what makes everything after it cheap. **The step names don't
change. Only how much work each step requires changes** — and that's decided by risk and
coordination need, not by habit.

Two of the twelve installed skills sit outside this table because they don't fit the
four-step shape: `pr-review` reviews a GitHub Pull Request that already exists (possibly
not even yours), and `critique-review` turns an existing finding into a concrete suggested
diff — a bridge from a review to a fix, not a review itself. `design-skill-eval`,
`technical-writing-style`, and `testing-craft` are different kinds of tools again:
`design-skill-eval` scaffolds evaluation tasks so you can measure whether a skill actually
helps, empirically, rather than just trusting it; `technical-writing-style` is what the
other planning skills read automatically before drafting prose, and what you can invoke
directly to revise an existing document's writing quality; and `testing-craft` is what
`specify-project`, `design-solution`, and `build-change` read automatically before they
design or write test content, and what you can invoke directly to design a test strategy,
audit an existing suite's health, or triage a flaky test.

## Two steps that only show up sometimes

**Design** (`design-solution`) and **Plan** (`plan-delivery`) are not extra stages
everything passes through — they're conditional depth inside Understand, triggered by real
properties of the change: a shared API or data contract, an authentication or privacy
boundary, or more than one developer working the same area concurrently. The checkout fix
above skips both — it's a one-line, single-developer, non-contract change.
[Tutorial 2](../tutorials/02-a-design-worthy-change.md) walks a change that *does* need
`design-solution`, and [Tutorial 4](../tutorials/04-multi-developer-coordination.md) walks
one that needs `plan-delivery`.

At the very edges: **Specify** (`specify-project`) is for a genuinely new product or a
whole-product redesign — one guided interview producing a single canonical specification,
used rarely. **Launch** (`launch-product`) is for real rollout risk — staged exposure,
rollback readiness, the kind of decision a change touching real money or real users at
scale needs. Most changes never touch either.

## Who does what

| | Human | AI |
|---|---|---|
| **Understand** | States the problem, makes the product/architecture call | Investigates the repository, proposes framing, asks one targeted question at a time |
| **Build** | Approves the plan, answers stop-condition questions | Grounds the plan in real code, implements, tests, self-checks |
| **Review** | Reads the exact diff, decides whether it may merge | Produces an independent, evidence-based review |
| **Ship** | Authorizes exposure and expansion | Assembles readiness evidence, proposes rollout stages |

Two artifacts carry the handoff between AI activity and human control, and neither needs
to be a separate document for ordinary work like the checkout fix — a few lines in the
conversation is enough:

- **The focus card**, presented before any editing begins: what's changing, what success
  looks like, what's explicitly out of scope, which files are fair game, how it'll be
  validated, and what should stop work and return to you.
- **The evidence receipt**, returned when implementation is "done": what changed, the
  exact commands run and their output, which acceptance criteria map to which evidence,
  any deviations from the plan, and current review status.

They become written artifacts (the templates under `.agents/skills/*/assets/`) once work
spans sessions, touches several components, or carries enough risk that a reconstructable
record matters.

## Review, in practice

Every change gets an independent human review — whoever wrote it, human or AI, does not
approve it. Where the platform supports subagents, this mostly happens without you
orchestrating it by hand: a fast correctness check runs after each build, a style and
maintainability gate runs automatically right before a pull request opens, and once that
PR exists, five specialist reviewers — correctness, security, concurrency, architecture,
rollout — examine it in parallel and hand you exactly the findings that need a decision.
You triage; CoDev does not decide for you which finding matters
([Tutorial 3](../tutorials/03-outer-loop-review.md) walks this end to end). `review-change`
still exists for the case none of that covers: a diff with no task and no open PR yet,
reviewed on demand.

## Where it breaks down (and how CoDev catches it)

| Failure mode | What it looks like | The guardrail |
|---|---|---|
| Hallucinated implementation | AI invents an API or config key that doesn't exist | Mandatory repository inspection before proposing; the reviewer checks claims against the diff |
| Scope creep | A bug fix quietly becomes a refactor | The focus card's allowed scope is a drift boundary; expansion must be surfaced before acting on it |
| Self-approval | The implementing AI declares its own work done | The builder cannot invoke another agent or approve; the reviewer is a fresh, independent context |
| Retry spiral | Repeated attempts at the same broken approach | Stop after two failed attempts with the same root cause; escalate to the human |
| Stale plan drift | The repository moved under the plan mid-implementation | Base-commit and snapshot checks; a changed base is a stop condition, not something to paper over |
| Rubber-stamp review | A review that restates the diff instead of finding problems | Reviews must cite evidence and end in one of three explicit states: `READY FOR HUMAN APPROVAL`, `CHANGES REQUIRED`, `BLOCKED BY MISSING EVIDENCE` |

## Multi-developer, briefly

One rule carries most of it: every component or contract has one responsible owner, and
the owner and reviewer are never the same person. Two developers can work in parallel once
they agree on a shared contract — say, the exact shape of a `DiscountResult` the pricing
and checkout modules both depend on — and a fixture to test against it, rather than
discovering the mismatch after both branches are done. See
[Tutorial 4](../tutorials/04-multi-developer-coordination.md) for a worked example.

## Where to go next

- **Just want to try it?** [Tutorial 1: your first fix](../tutorials/01-your-first-fix.md)
  — install to merged PR, one small bug, every command shown.
- A change that touches a shared contract:
  [Tutorial 2](../tutorials/02-a-design-worthy-change.md)
- Reviewing an already-open pull request:
  [Tutorial 3](../tutorials/03-outer-loop-review.md)
- Two developers, one shared contract:
  [Tutorial 4](../tutorials/04-multi-developer-coordination.md)
- Commands for a normal task, once you know the shape:
  [Normal Development Workflow](normal-development-workflow.md)
- Copy-paste prompts for starting a task or outer-loop review:
  [starting-prompts.md](starting-prompts.md)
- More worked walkthroughs: [examples.md](examples.md)
- The full command/skill/agent reference: `docs/product-map.md`
- How the bundle installs and updates: `docs/architecture.md`
