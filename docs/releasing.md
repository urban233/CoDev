# Release process

1. Confirm the working tree contains one reviewed release purpose.
2. Run the focused test suite, integration checks, compilation, Ruff, mypy, and
   package build (`just ci`, or `just dist && just verify-dist` for just the
   release-artifact build/validation). Coverage percentages are diagnostic
   only, not a release gate.
3. Validate the behavioral catalog and independently evaluate material workflow
   changes.
4. Update `CHANGELOG.md`, `pyproject.toml`, `src/codev_workflow/__init__.py`,
   and `packaging/BUILD.bazel`'s `version` attribute to the same release
   version. `scripts/verify_release.py` checks all four agree.
5. Run the release metadata and quality-gate preflight locally:
   `python scripts/verify_release.py --tag vX.Y.Z`.
6. Review the exact release diff.
7. Create and push a reviewed, signed `vX.Y.Z` tag after human authorization.

Pull-request, `main`, and release-tag CI runs the complete verification,
quality, packaging, and wheel smoke-test path. The published wheel is built
by Bazel (`py_wheel`, `//packaging:wheel`), not `python -m build` -- CI's
`quality` job builds both (`just dist`), parity-checks the Bazel wheel
against `python -m build`'s wheel before swapping it in, and validates the
result (`just verify-dist`: `twine check`, install, smoke test). The sdist
still comes from `python -m build`, since `rules_python`'s `py_wheel` has no
sdist equivalent. See `docs/features/bazel-migration/design.md`'s "PyPI
Packaging" section for the small, accepted metadata differences this
introduces (older `Metadata-Version`, no `Keywords`) and why they don't
block a release. On a release tag, the same CI workflow enables a separate
release phase only after those checks succeed. It verifies the tag and
package versions, downloads the distributions produced by that exact CI
run, rechecks their metadata, creates provenance attestations, and
publishes them to PyPI via trusted-publisher OIDC (`pypa/gh-action-pypi-
publish`). Branch and pull-request runs skip that release phase.

`just publish-testpypi` / `just publish-pypi` are a separate, human-run
publish path for the Bazel wheel via `rules_python`'s own `twine`
integration -- useful for testing against TestPyPI, never used by CI (which
stays on the OIDC trusted-publisher flow above; the two mechanisms don't
substitute for each other). Never run these as an unattended or
agent-initiated step.

## One-time PyPI setup

No PyPI API token is stored in GitHub. Before the first release, create a
pending trusted publisher on PyPI with these exact values:

- **PyPI project:** `open-codev-workflow`
- **Owner:** `urban233`
- **Repository:** `CoDev`
- **Workflow:** `ci.yml`
- **Environment:** `pypi`

In GitHub, create the `pypi` environment and configure required reviewers if a
separate approval after tagging is required. The `pypi` environment name must
match the PyPI trusted-publisher configuration.
