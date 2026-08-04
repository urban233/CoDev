# Release process

1. Confirm the working tree contains one reviewed release purpose.
2. Run the focused test suite, integration checks, compilation, Ruff, mypy, and
   package build. Coverage percentages are diagnostic only, not a release gate.
3. Validate the behavioral catalog and independently evaluate material workflow
   changes.
4. Update `CHANGELOG.md`, `pyproject.toml`, and `src/codev_workflow/__init__.py`
   to the same release version.
5. Review the exact release diff.
6. Create and push a reviewed, signed `vX.Y.Z` tag after human authorization.

The tag starts the release workflow. It verifies that the tag matches package
metadata, reruns the quality checks, builds and checks the distributions,
installs the wheel in a clean environment, creates provenance attestations,
and publishes to PyPI.

## One-time PyPI setup

No PyPI API token is stored in GitHub. Before the first release, create a
pending trusted publisher on PyPI with these exact values:

- **PyPI project:** `open-codev-workflow`
- **Owner:** `urban233`
- **Repository:** `CoDev`
- **Workflow:** `release.yml`
- **Environment:** `pypi`

In GitHub, create the `pypi` environment and configure required reviewers if a
separate approval after tagging is required. The `pypi` environment name must
match the PyPI trusted-publisher configuration.
