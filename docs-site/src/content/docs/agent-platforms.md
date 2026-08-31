---
title: Agent Platforms
description: How the CoDev bundle differs across OpenCode, Claude Code, Junie, and Antigravity.
---

CoDev installs into a repository through a per-platform **adapter**. `--agent-platform`
accepts `opencode`, `junie`, `antigravity`, `claude`, or `all` (the default) — pass it more
than once, or a comma-separated list, to select several platforms at once instead of
`all`.

```shell
codev init --target . --agent-platform opencode,claude
```

OpenCode and Claude Code get the full orchestrator-driven workflow described in
[Concepts](/CoDev/concepts/); Junie and Antigravity get a single narrower `assistant`
agent for bounded, surgical edits instead — see
[ADR-0031](https://github.com/urban233/CoDev/blob/main/docs/adr/0031-drop-codex-narrow-junie-and-antigravity-to-an-edit-assistant.md)
for why.

## OpenCode

Full orchestrator-driven workflow. `AGENTS.md` and `.opencode/opencode.json` are
integrations rather than copied files — CoDev owns one marked block in `AGENTS.md` and
selected missing values in OpenCode configuration, preserving all project-owned content.

## Claude Code

Full orchestrator-driven workflow, using its official `.claude/agents/` location. Unlike
Antigravity, Claude Code has no configurable skills path, so the shared skills are
mirrored into `.claude/skills/` at install time instead of referenced in place. Claude
Code additionally ships a `.claude/settings.json` and `.claude/hooks/require_plan.py` — a
category no other adapter has — that default new sessions into Plan Mode and pause for
confirmation before the first source edit when no design or plan document exists yet for
the active branch.

## Junie

Single narrow-tier `assistant` agent for bounded, surgical edits, as an ordinary managed
Markdown file under `.junie/agents/`.

## Antigravity

Single narrow-tier `assistant` agent, using its official `.agents/agents/` location
alongside CoDev's `.agents/skills/` directory.

## Managing installed adapters

| Command | Purpose |
|---|---|
| `codev adapter list` | Show which platform adapters are installed |
| `codev adapter add <platform>` | Add one adapter to an existing installation |
| `codev adapter remove <platform>` | Remove one adapter (still works for a platform an older CoDev version installed, even after the current version drops it) |
| `codev adapter verify <platform>` | Check one adapter's structural conformance: lifecycle wiring present, no unrestricted shell access, no retired review-scale patterns |
