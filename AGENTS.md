# CoDev Development Policy

CoDev is a distribution tool for repository-local AI workflow instructions.
Read `docs/architecture.md` before changing installation or update behavior.

Preserve these invariants:

- preflight every multi-file mutation before writing;
- never silently overwrite a locally changed managed file;
- preserve project-owned `AGENTS.md` and OpenCode configuration;
- keep model/provider choices project-local;
- keep target repositories free of CoDev runtime dependencies; and
- require explicit commands for mutations and human authorization for releases.

Use the workflow in the parent repository while CoDev remains nested there.
Run the standard-library test suite and compile check for every code change.
