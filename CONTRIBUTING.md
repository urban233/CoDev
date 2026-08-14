# Contributing

CoDev accepts focused changes with observable evidence.

1. Open an issue describing the user problem and expected behavior.
2. Keep installer behavior backwards compatible within a major version.
3. Add focused tests for important install, merge, drift, or migration behavior,
   favoring a few high-value integration tests over exhaustive unit coverage.
4. Run the commands in the README before requesting review.
5. Update the changelog when users or installed artifacts are affected.

Changes to bundled skills, agent policy, or workflow rules must also validate
the behavioral scenario catalog: run `scripts/validate-development-workflow.py
--repo src/codev_workflow/bundle` and `scripts/evaluate-development-workflow.py
--self-test` (both included in `scripts/verify_release.py`'s release checks).
Score externally observed actions — tool calls and artifacts — never private
chain-of-thought, and never let the agent under evaluation grade itself.
Cover: path selection, repository grounding, focus and scope discipline,
required stops, validation evidence, read-only review behavior, and
human-authorization boundaries. These two scripts and
`evals/development-workflow/scenarios.json` are this repository's own
development tooling, not part of the bundle shipped to a target repository —
see `docs/adr/0009-drop-internal-dev-scripts-from-the-bundle.md`.

The implementing AI cannot approve its own change; use an independent human
review and, for material behavior changes, a fresh AI review as additional
evidence.
