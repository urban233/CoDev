<p align="center">
  <img src="assets/codev-mark.svg" width="96" height="96" alt="CoDev mark">
</p>

<h1 align="center">CoDev</h1>

<p align="center"><strong>Human-guided AI software delivery.</strong></p>

CoDev installs a small, production-minded collaboration system into any Git
repository. It helps a developer and AI move through four understandable steps:
**Understand, Build, Review, and Ship**. It supports bounded three-agent
execution without turning product development into an unattended coding loop.

## Why CoDev

- One workflow for solo developers and multi-developer teams.
- Repository-grounded plans instead of invented APIs or architecture.
- A bounded builder and an independent, read-only reviewer.
- Human authority over material decisions, merge, deployment, and rollout.
- Versioned, conflict-aware installation across existing repositories.
- No runtime dependency in the software being built.

## Quick start

CoDev is a Python 3.11+ command-line tool. Target repositories may use any
language or build system. Install it with an isolated tool manager; `pipx` and
`uv tool` are the two supported, primary installation methods. Neither adds
CoDev or its dependencies to a target repository.

### Install from a wheel

For private, air-gapped, or pre-release distribution, install the supplied
wheel directly instead of publishing it to a package index:

```shell
pipx install ./dist/codev_workflow-0.1.0-py3-none-any.whl
# or
uv tool install ./dist/codev_workflow-0.1.0-py3-none-any.whl
```

Store the wheel with its SHA-256 checksum in a controlled artifact location.
The development workflow for building a wheel is documented below.

### Initialize a repository

```shell
codev init --target ../my-project --platform all
codev check --target ../my-project
```

To preview or apply a later bundle update:

```shell
codev diff --target ../my-project
codev update --target ../my-project
```

`init`, `diff`, and `update` preflight the entire operation. A locally modified
managed file becomes a visible conflict; CoDev never silently replaces it.

## What gets installed

```text
my-project/
├── AGENTS.md                         # a managed policy block; local text survives
├── .agents/skills/                   # seven lifecycle skills
├── .opencode/agents/                 # orchestrator, builder, reviewer
├── .opencode/opencode.json           # safely merged, never model-pinned
├── docs/                             # workflow, prompts, handbooks, cookbook
├── evals/development-workflow/       # behavioral scenarios
├── scripts/                          # deterministic validators
└── .codev/lock.json                # installed version and source hashes
```

Use `--platform codex` to omit the OpenCode adapter. Use `--platform opencode`
or `--platform all` for the three-agent OpenCode topology. Core skills and
human/AI workflow references are installed for every platform.

## Design principles

1. **Local at use time.** Agents read ordinary files in the target repository.
2. **Central at maintenance time.** This repository is the canonical source.
3. **Human at authority boundaries.** Automation supplies evidence, not approval.
4. **Small by default.** Deeper design and delivery planning appear only when
   risk or coordination requires them.
5. **Safe to adopt.** Existing instructions and OpenCode settings are preserved.

Read [Architecture](docs/architecture.md) for the distribution model,
[Adoption](docs/adoption.md) for rollout guidance, and
[Brand](docs/brand.md) for the visual and writing system.

## Development

```shell
python -m unittest discover -s tests -v
python -m compileall -q src tests
python -m codev_workflow --version
```

Optional development checks:

```shell
ruff check .
ruff format --check .
mypy
python -m build
```

CoDev is licensed under BSD-3-Clause.
