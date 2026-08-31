# Documentation index

What's in `docs/`, grouped by who it's for. If you haven't installed CoDev yet, start with
the root [README.md](../README.md).

## If you're using CoDev in your own repository

This human-facing narrative documentation lives on the docs site, not bundled into your
own repository — after `codev init`, `docs/codev/README.md` in your own repository has a
short pointer back here instead of the full text. (`docs/codev/onboarding/skill-card.md`
templates are the one exception that still installs locally, since you fill one in inside
your own repo.)

1. [Onboarding Guide](https://urban233.github.io/CoDev/onboarding-guide/) — the mental
   model, read once.
2. [Tutorial 1: your first fix](https://urban233.github.io/CoDev/tutorials/your-first-fix/)
   — install to merged PR, narrated, real commands.
3. [Tutorial 2: a design-worthy change](https://urban233.github.io/CoDev/tutorials/a-design-worthy-change/),
   [Tutorial 3: outer-loop review](https://urban233.github.io/CoDev/tutorials/outer-loop-review/),
   [Tutorial 4: multi-developer coordination](https://urban233.github.io/CoDev/tutorials/multi-developer-coordination/)
   — the same shape, for the situations that need more of it.
4. [Workflow Checklist](https://urban233.github.io/CoDev/workflow-checklist/)
   — the command checklist, once you know the shape.
5. [Starting Prompts](https://urban233.github.io/CoDev/starting-prompts/)
   — copy-paste prompts for the two moments worth getting exactly right.
6. [Examples](https://urban233.github.io/CoDev/examples/) — more
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
