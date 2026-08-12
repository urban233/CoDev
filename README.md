<p align="center">
  <img src="assets/codev-mark.svg" width="96" height="96" alt="CoDev mark">
</p>

<h1 align="center">CoDev</h1>

<p align="center"><strong>Human-guided AI software delivery.</strong></p>

![Active Feature Development](https://img.shields.io/badge/Project_State-Active_Feature_Development-brightgreen?style=flat-square)
![AI-driven](https://img.shields.io/badge/AI_Use-AI--driven-orange?style=flat-square)
![CI](https://img.shields.io/github/actions/workflow/status/urban233/CoDev/ci.yml?branch=main&label=CI&style=flat-square)
![PyPI version](https://img.shields.io/pypi/v/open-codev-workflow?style=flat-square)
![Python versions](https://img.shields.io/pypi/pyversions/open-codev-workflow?style=flat-square)
![License](https://img.shields.io/github/license/urban233/CoDev?style=flat-square)
![Latest release](https://img.shields.io/github/v/release/urban233/CoDev?style=flat-square)
![GitHub stars](https://img.shields.io/github/stars/urban233/CoDev?style=flat-square)
![GitHub issues](https://img.shields.io/github/issues/urban233/CoDev?style=flat-square)

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

### Install from PyPI

```shell
pipx install open-codev-workflow
# or
uv tool install open-codev-workflow
```

### Install from a wheel

For private, air-gapped, or pre-release distribution, install the supplied
wheel directly instead of publishing it to a package index:

```shell
pipx install ./dist/open_codev_workflow-0.1.1-py3-none-any.whl
# or
uv tool install ./dist/open_codev_workflow-0.1.1-py3-none-any.whl
```

Store the wheel with its SHA-256 checksum in a controlled artifact location.
The development workflow for building a wheel is documented below.

### Initialize a repository

```shell
codev init --target ../my-project --agent-platform all
codev status --target ../my-project
```

Language-specific audit skills are not installed unless selected explicitly.
Use `--programming-language python` or `--programming-language typescript` for
one language, `--programming-language all` for both, or
`--programming-language none` for the language-agnostic audit agent. The default
for `init` is `none`. An `update` without this flag preserves the selection in
`.codev/lock.json`.

To preview or apply a later bundle update:

```shell
codev diff --target ../my-project
codev update --target ../my-project
codev remove --target ../my-project --dry-run
```

`init`, `diff`, and `update` preflight the entire operation. A locally modified
managed file becomes a visible conflict; CoDev never silently replaces it.

### Command reference

| Command | Purpose |
|---|---|
| `codev init` / `diff` / `update` / `remove` | Install, preview, apply, or remove the bundle |
| `codev status [--verbose] [--json]` | Bundle health, installed adapters, and open work items in one place |
| `codev adapter list` / `codev adapter add <platform>` | Show or add one platform adapter to an existing install |
| `codev adapter verify <platform>` | Check one installed adapter's structural conformance (lifecycle wiring present, no unrestricted shell access, no retired patterns) |
| `codev config get\|set\|list [--global]` | Read or write layered configuration (flags > env > project > global > default) |
| `codev work start\|record\|check\|close\|status\|log` | Track builder/reviewer round state for one work item — read `docs/adr/0001-work-lifecycle-invariant.md` before scripting against it |
| `codev eval fixture create` / `codev eval run` | Create and run local skill-evaluation fixtures |
| `codev self version` / `codev self update` | Show the installed CoDev version, or how to upgrade it |

`codev check`, `codev doctor`, `codev fixture create`, and bare `codev eval
<name>` still work as deprecated aliases for `status`, `status --verbose`,
`eval fixture create`, and `eval run <name>` — each prints a warning and will
be removed in a future major version.

## GitHub Pull Request reviews

The installed `pr-review` skill reviews an existing GitHub Pull Request and can
prepare validated inline comments for the exact PR head. It uses the GitHub CLI
credential store by default, so agents do not need to read or print a token.

### Install and authenticate GitHub CLI on Windows

Install the official package from PowerShell with WinGet:

```powershell
winget install --id GitHub.cli --source winget
```

Open a new Windows Terminal window after installation, then verify and sign in:

```powershell
gh --version
gh auth login --web
gh auth status --active
```

Choose `GitHub.com`, the HTTPS protocol, and the browser login flow. `gh` stores
the credential using the Windows credential store when available. See the
[official Windows installation guide](https://github.com/cli/cli/blob/trunk/docs/install_windows.md)
and [`gh auth login` documentation](https://cli.github.com/manual/gh_auth_login).

Run the PR publisher in dry-run mode first:

```powershell
python .agents\skills\pr-review\scripts\publish_review.py `
  --repo OWNER/REPO `
  --pr 123 `
  --review review.json
```

The publisher automatically uses authenticated `gh api` when no
`GITHUB_TOKEN` or `GH_TOKEN` is set. Use `--auth gh` to require that backend or
`--auth token` for headless environments that provide a token variable. Add
`--publish` only after explicitly authorizing a GitHub review, and use
`--submit comment` only when it should be submitted immediately.

If a desktop agent does not inherit the Windows machine PATH, the publisher
also checks the standard `C:\\Program Files\\GitHub CLI\\gh.exe` location. For a
custom installation, set `CODEV_GH_PATH` to the full path of `gh.exe`.

To copy the already-authenticated `gh` credential into `GH_TOKEN` for the
current PowerShell process and the CLI started from it, dot-source the bundled
helper:

```powershell
. .agents\\skills\\pr-review\\scripts\\set-github-token.ps1
```

The helper calls `gh auth token` without printing the result and does not
persist it. The `gh` credential must be valid in the same process context. This
is useful for a CLI that needs `GH_TOKEN`; launch that CLI from the shell where
the helper has been dot-sourced. Do not put the token in a repository file or
command-line argument.

One-line equivalent:

```powershell
$g=Get-Command gh -ErrorAction SilentlyContinue;if($g){$p=$g.Source}else{$p='C:\\Program Files\\GitHub CLI\\gh.exe'};$env:GH_TOKEN=(& $p auth token --hostname github.com 2>$null).Trim()
```

Fetch the complete GitHub PR context before asking an agent to review it:

```powershell
python .agents\\skills\\pr-review\\scripts\\publish_review.py `
  --repo OWNER/REPO `
  --pr 123 `
  --fetch `
  --output-dir .codev\\pr-review\\123
```

This writes PR metadata, the patch, changed files, commits, reviews, comments,
and check runs. Use repeated `--include metadata`, `--include diff`, or other
parts to fetch a smaller set.

The installed Junie project command is also available directly inside Junie:

```text
/pr-review repo=OWNER/REPO pr=123
```

Project-specific Junie commands live under `.junie/commands`, so this command
is versioned with the repository and appears in Junie’s `/` command list.

## What gets installed

```text
my-project/
├── AGENTS.md                         # a managed policy block; local text survives
├── .gitignore                        # a managed block ignoring the local escalation log
├── .agents/skills/                   # lifecycle, PR, and specialist review skills
├── .agents/agents/                   # Antigravity workflow and audit agents
├── .codex/agents/                     # Codex workflow and audit agents
├── .opencode/agents/                 # OpenCode workflow and audit agents
├── .opencode/opencode.json           # safely merged; existing agent settings survive
├── .junie/agents/                    # Junie subagents
├── docs/                             # AI guidance and human delivery guide
├── evals/development-workflow/       # behavioral scenarios
├── scripts/                          # deterministic validators
└── .codev/lock.json                # installed version and source hashes
```

Use `--agent-platform codex` to omit the OpenCode, Junie, and Antigravity adapters.
The Codex adapter installs TOML agents under `.codex/agents/`.
Use `--agent-platform opencode`, `--agent-platform junie`, or
`--agent-platform antigravity` to select one adapter, or use
`--agent-platform all` for every supported platform. Core
skills and human/AI workflow references are installed for every platform.

The human delivery guide is installed at `docs/for-human/development-guide.md`.
The cookbook, prompt templates, and detailed handbooks are maintained as
dedicated Wiki pages.

To add an adapter to an existing installation, pass it to `update`, for example
`codev update --agent-platform junie`. Use `diff --agent-platform junie` to preview the
platform expansion first.

The Antigravity adapter follows its official workspace location:
`.agents/agents/<name>.md`.

The Codex adapter follows its official workspace location:
`.codex/agents/<name>.toml`.

## Design principles

1. **Local at use time.** Agents read ordinary files in the target repository.
2. **Central at maintenance time.** This repository is the canonical source.
3. **Human at authority boundaries.** Automation supplies evidence, not approval.
4. **Small by default.** Deeper design and delivery planning appear only when
   risk or coordination requires them.
5. **Safe to adopt.** Existing instructions and OpenCode settings are preserved.

Read [Architecture](docs/architecture.md) for the distribution model,
[Product Map](docs/product-map.md) for what CoDev actually is once
installed — phases, skills, agents, and how they're invoked,
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
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m build
```

CoDev is licensed under BSD-3-Clause.
