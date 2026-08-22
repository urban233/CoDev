# ADR-0029: Adopt skill cards and license metadata from NVIDIA's Recommended Artifact Set

**Status:** Accepted
**Date:** 2026-08-22
**Owner:** CoDev maintainers
**Related design:** [../features/skill-eval-ergonomics/design.md](../features/skill-eval-ergonomics/design.md)

## Context

[ADR-0028](0028-skill-packages-carry-their-own-eval-trace.md) adopted only the
eval-trace half of NVIDIA SkillEvaluator's Recommended Artifact Set for a
skill package, and explicitly deferred the rest:

> CoDev adopts only the eval-trace half of NVIDIA's artifact set.
> `skill-card.md` (ownership/license/risk metadata) and `skill.oms.sig` (a
> signing step) solve problems CoDev does not yet have -- there is no
> catalog, no publication step, and no cross-organization trust boundary for
> an installed skill to be signed against.

That ADR's own "Revisit when" named the condition for revisiting this:
growing a real skill catalog, a publication step, or a cross-organization
trust boundary. That condition has not actually arrived -- this decision
instead reflects a direct, deliberate choice to adopt `skill-card.md` now
regardless, because a skill card is legible and useful on its own terms (a
reviewer can understand a skill's purpose, owner, output, and risks without
opening its source) independent of whether a catalog or publication pipeline
exists to consume it. Signing (`skill.oms.sig`) remains deferred: it solves a
cross-organization trust problem CoDev genuinely does not have yet, and
adopting it now would still be speculative infrastructure with no verifier on
the other end.

Separately, NVIDIA's own real skill listings (confirmed against a real
example, the `alphafold2` skill) show SKILL.md frontmatter extended beyond the
vendor-neutral Agent Skills specification's `name`/`description`/`license`/
`compatibility`/`metadata` (a flat string map) -- fields like `category`,
`requirements` (e.g. `[gpu]`), and a `metadata.third_party` list (each entry's
`kind`/`name`/`provider`/`license` or `terms_url`/`info_url`) for declaring a
third-party model or service dependency. None of CoDev's bundled skills use a
GPU or depend on a third-party model/service the way `alphafold2` depends on
DeepMind's AlphaFold2 weights and the ColabFold MSA server -- adding those
fields now, with no real value to put in them, would be exactly the kind of
fabricated-metadata risk a skill card exists to prevent. `license` is
different: every bundled skill is genuinely covered by this repository's own
license today, so it is both true and useful to state per skill, not
speculative.

## Decision

- **`skill-card.md`** joins `SKILL.md` as a real, filled-out artifact for
  every currently-bundled skill (15 at the time of this decision), copied
  into an installing project the same way any other file under
  `.agents/skills/<name>/` already is (`installer._walk_bundle()` copies the
  whole tree; no new install-time logic was needed). Each card states:
  Description, Owner, License/Terms of Use, Use Case, Deployment Geography
  for Use, Requirements/Dependencies, Known Risks and Mitigations,
  References, Skill Output, Skill Version, and Ethical Considerations --
  matching NVIDIA's own real template section list. A template,
  `docs/codev/onboarding/skill-card.template.md` (bundled, so it ships to
  every installed project too), is the copy-this-file starting point for a
  new skill, mirroring `assets/adr.template.md`'s own "how to use this file"
  convention.
- **`license` frontmatter field** is added to every bundled skill's
  `SKILL.md`, set to this repository's actual license
  (`BSD-3-Clause`) -- the one extended field genuinely true for all of them
  today.
- **`category`, `requirements`, and `metadata.third_party`** are explicitly
  **not** adopted in this decision. No bundled skill has a real GPU
  requirement or a third-party model/service dependency to declare; adding
  these fields with placeholder or absent values would document nothing real
  and risk looking authoritative when it isn't. A skill that genuinely
  gains one of these properties in the future should declare it then, using
  NVIDIA's own field names for consistency, rather than this decision
  inventing empty scaffolding for it now.
- **`skill.oms.sig` (signing)** remains deferred, unchanged from ADR-0028 --
  CoDev still has no catalog, publication step, or cross-organization trust
  boundary for a signature to mean anything against.

## Alternatives considered

- **Wait for ADR-0028's own "Revisit when" condition (a real catalog or
  publication step) before adopting skill cards:** rejected. A skill card's
  value (a reviewer understanding a skill without opening its source) does
  not depend on a catalog existing to browse it -- it is useful the moment
  more than one skill exists in a bundle, which is already true today.
- **Adopt `category`/`requirements`/`third_party` alongside `license`, using
  a placeholder or "none" value:** rejected. A skill card exists specifically
  to prevent exactly this: a plausible-looking but empty or invented claim.
  Better to omit a field entirely than to populate it with a value that
  documents nothing real.
- **Gate something functionally on `skill-card.md`'s presence (e.g. `codev
  check` failing without one):** rejected for this decision. CoDev has no
  release-gate concept for skills the way NVIDIA's trust pipeline does;
  introducing one now would be speculative enforcement ahead of any real
  need for it.

## Consequences

- Every bundled skill directory now has three real, non-code artifacts
  (`SKILL.md`, `skill-card.md`, and, where a benchmark has actually run,
  `evals/benchmark.json` + `evals/BENCHMARK.md` per ADR-0028) instead of just
  one.
- `skill-card.md` is hand-authored prose, not a generated artifact like the
  eval trace -- it needs a human (or an agent under human review) to update
  it when a skill's real scope, dependencies, or risks change; nothing
  currently checks it for staleness.
- A future skill with a genuine GPU requirement or third-party dependency has
  real precedent (NVIDIA's own field names) to declare it by, without this
  decision having pre-built unused scaffolding for that case.

## Revisit when

A bundled skill gains a genuine `requirements`/`category`/third-party
dependency to declare, at which point adopt exactly the fields needed for
that real case rather than retrofitting all of them speculatively. Revisit
signing (`skill.oms.sig`) under the same condition ADR-0028 already named: a
real catalog, publication step, or cross-organization trust boundary.
