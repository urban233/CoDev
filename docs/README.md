# Documentation index

What's in `docs/`, grouped by who it's for. If you haven't installed CoDev yet, start with
the root [README.md](../README.md).

## If you're using CoDev in your own repository

Once installed, these live inside your own project too, so you can read them without
leaving your editor — they're listed here by their path *in the CoDev repository*; after
`codev init`, find them at `docs/codev/...` in your own repository instead.

1. [Onboarding guide](../src/codev_workflow/bundle/docs/codev/onboarding/onboarding-guide.md)
   — the mental model, read once.
2. [Tutorial 1: your first fix](../src/codev_workflow/bundle/docs/codev/tutorials/01-your-first-fix.md)
   — install to merged PR, narrated, real commands.
3. [Tutorial 2: a design-worthy change](../src/codev_workflow/bundle/docs/codev/tutorials/02-a-design-worthy-change.md),
   [Tutorial 3: outer-loop review](../src/codev_workflow/bundle/docs/codev/tutorials/03-outer-loop-review.md),
   [Tutorial 4: multi-developer coordination](../src/codev_workflow/bundle/docs/codev/tutorials/04-multi-developer-coordination.md)
   — the same shape, for the situations that need more of it.
4. [Normal Development Workflow](../src/codev_workflow/bundle/docs/codev/onboarding/normal-development-workflow.md)
   — the command checklist, once you know the shape.
5. [starting-prompts.md](../src/codev_workflow/bundle/docs/codev/onboarding/starting-prompts.md)
   — copy-paste prompts for the two moments worth getting exactly right.
6. [examples.md](../src/codev_workflow/bundle/docs/codev/onboarding/examples.md) — more
   worked walkthroughs.

Reference, kept here in the CoDev repository (not installed into your project, since it
describes CoDev itself rather than your work in it):

- [CLI reference](cli-reference.md) — every command.
- [PR review: GitHub CLI setup](pr-review-github-cli-setup.md) — Windows-specific
  authentication steps.
- [Product Map](product-map.md) — every skill, agent, and command, and how they're
  invoked; the full technical reference behind the tutorials.
- [Architecture](architecture.md) — how the bundle is built, installed, and updated.

## If you're rolling CoDev out to a team

- [Adoption guide](adoption.md) — new repository, existing repository, team rollout,
  updating a pinned version.
- [Brand](brand.md) — the visual and writing system, for anyone producing CoDev-branded
  material.

## If you're contributing to CoDev itself

- [CONTRIBUTING.md](../CONTRIBUTING.md) — what's expected of a change.
- [SECURITY.md](../SECURITY.md) — how to report a vulnerability.
- [Architecture Decision Records](adr/) — one durable, cross-cutting decision per file;
  read before changing a mechanism, not just a detail.
- [Release process](releasing.md) — the one-time PyPI setup and the tagging procedure.
- [Feature briefs and designs](features/) — the brief/design pair for each non-trivial
  feature, in the same spec-driven shape CoDev asks adopters to use on their own work.
- [Product Map](product-map.md) — also the map maintainers check a new capability against
  before adding it, so it's judged against the whole product, not just its own merits.

## Everything else in this directory

- `plans/` — point-in-time planning notes for a specific, usually-completed effort; not
  kept in sync afterward, read as history rather than current state.
- `flamingo-playbook.html` — a rendered artifact of the brand system in `brand.md`.
