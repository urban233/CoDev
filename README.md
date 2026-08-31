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

CoDev installs a small, production-minded collaboration system into any Git repository. A
developer and AI move through four steps — **Understand, Build, Review, Ship** — plus two
that only show up when the work actually needs them: **Specify** for a genuinely new
product, **Launch** for a real rollout decision. Review is layered, not a single pass: a
fast correctness check after each build, an automatic style and maintainability gate
immediately before a pull request opens, and five parallel specialist reviewers once it's
open. It supports bounded three-agent execution without turning product development into
an unattended coding loop.

## Why CoDev

- One workflow for solo developers and multi-developer teams.
- Repository-grounded plans instead of invented APIs or architecture.
- A bounded builder, an automatic pre-PR audit gate, and five parallel specialist
  reviewers — not just one read-only pass.
- Human authority over material decisions, merge, deployment, and rollout.
- A general-purpose skill-evaluation harness — measure whether a skill (CoDev's own, or
  one you wrote) actually helps, empirically, rather than just trusting that it does.
- Versioned, conflict-aware installation across existing repositories.
- No runtime dependency in the software being built.

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
skill. **[Tutorial 1](https://urban233.github.io/CoDev/tutorials/your-first-fix/)
walks one small fix from here to a merged pull request, with every command and real
output shown.**

## Where to go next

| I want to... | Go to |
|---|---|
| Understand the mental model before doing anything | [Onboarding guide](https://urban233.github.io/CoDev/onboarding-guide/) |
| Just try it, right now | [Tutorial 1: your first fix](https://urban233.github.io/CoDev/tutorials/your-first-fix/) |
| See every command | [CLI reference](docs/cli-reference.md) |
| See exactly what gets installed and why | [Architecture](docs/architecture.md) |
| Adopt CoDev for a team, not just myself | [Adoption guide](docs/adoption.md) |
| Understand why a specific mechanism exists | [Architecture Decision Records](docs/adr/) |
| Set up GitHub CLI for PR review on Windows | [PR review setup](docs/pr-review-github-cli-setup.md) |
| Contribute to CoDev itself | [Contributing](CONTRIBUTING.md) |
| See everything `docs/` contains, organized by audience | [docs/README.md](docs/README.md) |

## Design principles

1. **Local at use time.** Agents read ordinary files in the target repository.
2. **Central at maintenance time.** This repository is the canonical source.
3. **Human at authority boundaries.** Automation supplies evidence, not approval.
4. **Small by default.** Deeper design and delivery planning appear only when risk or
   coordination requires them.
5. **Safe to adopt.** Existing instructions and OpenCode settings are preserved.

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
python scripts/check_bundled_doc_links.py
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for what's expected of a change, and
[docs/releasing.md](docs/releasing.md) for the release process.

CoDev is licensed under BSD-3-Clause.
