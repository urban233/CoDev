---
title: Getting Started
description: Install CoDev into a repository and run your first status check.
---

## Try it in 60 seconds

```shell
pipx install open-codev-workflow
# or: uv tool install open-codev-workflow

codev init --target . --agent-platform all
codev status --target .
```

```text
CoDev 0.4.0 - /path/to/your/repo
Bundle: healthy (76 managed files, no drift)
Adapters: opencode
Tasks in progress: 0
```

Commit the installed files as one infrastructure change, then start an AI session in the
repository and describe a small bug or task in plain language — you don't need to name a
skill. [Tutorial 1](/CoDev/tutorials/your-first-fix/) walks one small fix from here to a
merged pull request, with every command and real output shown.

## New repository

1. Create the repository and its normal build, test, lint, ownership, and CI foundations.
2. Run `codev init --target <repo> --agent-platform all`.
3. Add project-specific instructions outside the marked CoDev block in `AGENTS.md`.
4. Configure model/provider choices in the normal platform configuration.
5. Run `codev status --target <repo>` and the project's own validation.
6. Review and commit the installation as one infrastructure change.

## Existing repository

1. Start with a clean branch and inspect existing `AGENTS.md`, `.agents`, and `.opencode`
   content.
2. Run `codev init`; it will stop rather than replace a different file at a managed path.
3. Resolve naming collisions deliberately. Rename a project-local skill when it is
   semantically different; do not blend two authorities into one file.
4. Keep product-specific rules outside managed files.
5. Run deterministic validation and exercise a representative work item before team-wide
   adoption.

## Team rollout

Use one pilot repository and one real, bounded feature. Gather evidence about planning
quality, intervention frequency, review findings, lead time, and developer comprehension.
Expand only after the team agrees that authority boundaries and handoffs are
understandable.

Recommended ownership:

- Developer productivity owns CoDev version policy and installation tooling.
- Product teams own repository-specific instructions and technical authority.
- Security owns organization-wide restrictions and release provenance.
- Each code owner remains accountable for change acceptance and operation.

## Updating

Pin a released CoDev version in team automation. Use `codev diff` before `codev update`;
inspect the resulting Git diff and changelog; then run the consumer repository's CI. Never
update from a floating development branch and never auto-merge workflow instruction
changes.

## Where to go next

| I want to... | Go to |
|---|---|
| Understand the mental model before doing anything | [Onboarding Guide](/CoDev/onboarding-guide/) |
| Try it hands-on, one small fix at a time | [Tutorial 1](/CoDev/tutorials/your-first-fix/) |
| See every command | [CLI reference](/CoDev/cli-reference/) |
| See exactly what gets installed and why | [Architecture](/CoDev/architecture/) |
| Understand why a specific mechanism exists | [Architecture Decision Records](https://github.com/urban233/CoDev/tree/main/docs/adr) |
| Contribute to CoDev itself | [Contributing](https://github.com/urban233/CoDev/blob/main/CONTRIBUTING.md) |
