# Adoption guide

## New repository

1. Create the repository and its normal build, test, lint, ownership, and CI
   foundations.
2. Run `codev init --target <repo> --platform all`.
3. Add project-specific instructions outside the marked CoDev block in
   `AGENTS.md`.
4. Configure model/provider choices in the normal platform configuration.
5. Run `codev check --target <repo>` and the project's own validation.
6. Review and commit the installation as one infrastructure change.

## Existing repository

1. Start with a clean branch and inspect existing `AGENTS.md`, `.agents`, and
   `.opencode` content.
2. Run `codev init`; it will stop rather than replace a different file at a
   managed path.
3. Resolve naming collisions deliberately. Rename a project-local skill when it
   is semantically different; do not blend two authorities into one file.
4. Keep product-specific rules outside managed files.
5. Run deterministic validation and exercise a representative work item before
   team-wide adoption.

## Team rollout

Use one pilot repository and one real, bounded feature. Gather evidence about
planning quality, intervention frequency, review findings, lead time, and
developer comprehension. Expand only after the team agrees that authority
boundaries and handoffs are understandable.

Recommended ownership:

- Developer productivity owns CoDev version policy and installation tooling.
- Product teams own repository-specific instructions and technical authority.
- Security owns organization-wide restrictions and release provenance.
- Each code owner remains accountable for change acceptance and operation.

## Updating

Pin a released CoDev version in team automation. Use `codev diff` before
`codev update`; inspect the resulting Git diff and changelog; then run the
consumer repository's CI. Never update from a floating development branch and
never auto-merge workflow instruction changes.

## Publishing releases

`open-codev-workflow` is published from reviewed `vX.Y.Z` tags. The release
workflow validates the tag and package version, verifies the built artifacts,
creates provenance attestations, and publishes through PyPI trusted publishing.
See [the release guide](releasing.md) for the one-time PyPI configuration and
tagging procedure.
