# Human-AI Development Policy

Read `docs/for-ai/WORKFLOW-AGENTS.md` before planning or implementing product
work. Use the applicable repository skill:

- `specify-project` for a recommendation-led greenfield or whole-product
  interview that produces one accepted `SPECIFICATION.md`;
- `define-product` for ideas, outcomes, scope, and workflow sizing;
- `design-solution` for material architecture, API, data, or risk decisions;
- `plan-delivery` for multi-developer milestones and work coordination;
- `build-change` for interactive implementation of one bounded change;
- `review-change` for an independent, read-only code review; and
- `clean-code-review` for a focused Clean Code, GoF, and Python smell scan; and
- `launch-product` for readiness, rollout, rollback, and learning.

Use the lightest safe path. Inspect the repository before prescribing code
mechanics, keep changes small, run proportionate validation, and stop for
material decisions instead of inventing them. Humans retain authority for
acceptance, merge, deployment, migration, publication, and rollout expansion.

Do not require developers to choose a skill. Route their request internally and
describe the current human-facing step as `Understand`, `Build`, `Review`, or
`Ship`; insert design or delivery planning only when risk or coordination needs
it.

Use `clean-code-review` as an optional specialist pass for requests about code
smells, maintainability, Clean Code practices, GoF signals, or Python-specific
hazards. It complements `review-change` and does not replace correctness,
security, regression, or release review.
