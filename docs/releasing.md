# Release process

1. Confirm the working tree contains one reviewed release purpose.
2. Run unit tests, compilation, Ruff, mypy, and package build.
3. Install the built wheel into a clean environment.
4. Initialize a fixture repository and run `codev check` from the wheel.
5. Validate the behavioral catalog and independently evaluate material workflow
   changes.
6. Update `CHANGELOG.md` and the version in `pyproject.toml`.
7. Review the exact release diff and artifact checksums.
8. Create a signed `vX.Y.Z` tag after human authorization.
9. Let GitHub Actions build the release artifact from that tag.
10. Publish to PyPI only after a separate explicit authorization and trusted
    publishing configuration.

Release automation builds evidence and artifacts. It does not independently
decide that a release is safe or publish to a package index.

