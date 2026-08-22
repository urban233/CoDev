# Architecture

## Purpose

CoDev separates workflow maintenance from workflow use. The canonical bundle
lives in this project; agents consume ordinary, repository-local files in each
software project. CoDev's install, update, and remove machinery never runs
while product code is being built. The `codev task` lifecycle commands are the
one exception: they may run during a build session, are strictly read-only
with respect to product source, and only read or write their own state under
`.codev/task/` (see [ADR-0001](adr/0001-work-lifecycle-invariant.md) and
[ADR-0023](adr/0023-work-item-renamed-to-task.md)).

```text
CoDev source -> versioned Python package -> explicit CLI command -> target repo
       |                                                    |
       +---- tests and behavioral evaluations               +---- local agent discovery
```

## Components

### Bundle

`src/codev_workflow/bundle` mirrors target-relative paths. It contains the
skills, Codex and OpenCode agents, documentation, validators, and evaluation
catalog.
The installer discovers package data recursively, so adding a bundled file does
not require maintaining a second file list.

Every bundled skill carries a `skill-card.md` alongside its `SKILL.md` --
owner, license, use case, dependencies, and known risks, filled out with real
facts rather than left as a template placeholder -- and a `license`
frontmatter field on `SKILL.md` itself. See
`docs/adr/0029-adopt-skill-cards-and-license-metadata.md`.

`AGENTS.md` and `.opencode/opencode.json` are integrations rather than copied
files. CoDev owns one marked block in `AGENTS.md` and selected missing values
in OpenCode configuration, preserving all project-owned content. Junie
subagents are ordinary managed Markdown files under `.junie/agents/`, while
Antigravity subagents use its official `.agents/agents/` location alongside
CoDev's `.agents/skills/` directory. Codex agents use the official
`.codex/agents/` directory and TOML format.

### Installer

The standard-library CLI performs a complete preflight before mutation. It
computes SHA-256 hashes over bundled bytes and records them in
`.codev/lock.json`. Files are written atomically in their destination
directories.

### Lock file

The lock file records schema version, bundle version, selected platforms,
source hashes, and integration state. It is committed to the consumer
repository so CI and other developers observe the same installation.

## Update algorithm

For each managed file, CoDev compares:

1. the source hash recorded at the last successful install;
2. the current target file; and
3. the source file in the running CoDev version.

| State | Action |
|---|---|
| Target matches old source; source changed | Update |
| Target matches new source | Adopt as current |
| Target and source both match old source | Keep |
| Target differs; upstream is unchanged | Report local drift |
| Target differs and upstream changed | Conflict; write nothing |
| New upstream file is absent locally | Add |
| New upstream file collides locally | Conflict; write nothing |
| Upstream removed an old file | Retain locally and stop managing it |

Retaining removed files is conservative: an update cannot unexpectedly delete
repository instructions. The explicit `codev remove` command preflights and
removes only unchanged managed files and integrations; it remains opt-in.

## Invariants

- Every multi-file change is atomic at the decision level: conflicts prevent
  all planned writes.
- A target repository never imports CoDev as a runtime dependency.
- Provider and model selection remain project-owned.
- Installed instruction changes are reviewable source changes.
- Deterministic checks run without network access or model calls.
- Behavioral model evaluations remain externally observed and separately run.
- `codev task` lifecycle commands are read-only with respect to product
  source; they only mutate their own state under `.codev/task/`
  (see [ADR-0001](adr/0001-work-lifecycle-invariant.md) and
  [ADR-0023](adr/0023-work-item-renamed-to-task.md)).

## Compatibility

Lock schema changes require a migration before managed files are touched.
Bundle behavior follows semantic versioning. Patch releases preserve artifact
contracts; minor releases may add compatible files or behaviors; major releases
may require an explicit migration and review.
