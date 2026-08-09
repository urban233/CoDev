# Release process

1. Confirm the working tree contains one reviewed release purpose.
2. Run the focused test suite, integration checks, compilation, Ruff, mypy, and
   package build. Coverage percentages are diagnostic only, not a release gate.
3. Validate the behavioral catalog and independently evaluate material workflow
   changes.
4. Update `CHANGELOG.md`, `pyproject.toml`, and `src/codev_workflow/__init__.py`
   to the same release version.
5. Run the release metadata and quality-gate preflight locally:
   `python scripts/verify_release.py --tag vX.Y.Z`.
6. Review the exact release diff.
7. Create and push a reviewed, signed `vX.Y.Z` tag after human authorization.

Pull-request, `main`, and release-tag CI runs the complete verification,
quality, packaging, and wheel smoke-test path. On a release tag, the same CI
workflow enables a separate release phase only after those checks succeed. It
verifies the tag and package versions, downloads the distributions produced by
that exact CI run, rechecks their metadata, creates provenance attestations,
and publishes them to PyPI. Branch and pull-request runs skip that release
phase.

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
