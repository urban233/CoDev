---
title: FAQ
description: Common questions about how CoDev behaves and what it touches.
---

### Does my repository need to depend on CoDev at runtime?

No. A target repository never imports CoDev as a runtime dependency. CoDev installs
ordinary, repository-local files that agents read directly.

### Which agent platforms does CoDev support?

`opencode`, `junie`, `antigravity`, and `claude`, selected with `--agent-platform` on
`codev init`. See [Agent Platforms](/CoDev/agent-platforms/) for what differs between
them.

### Can an agent run raw `git commit` or `git push`?

No. `codev git commit` and `codev git push` are the only path for an agent to mutate the
repository or GitHub — raw `git commit`/`git push` are denied to every role for exactly
this reason.

### What happens if I've locally modified a file CoDev manages?

It becomes a visible conflict. CoDev never silently overwrites a locally modified managed
file — `codev status` keeps reporting it as a conflict until you resolve it with
`override` or `keep`. See the update algorithm in [Architecture](/CoDev/architecture/#update-algorithm).

### Does `codev eval` read or store my API keys?

No. The skill-evaluation harness drives OpenCode using your own existing auth — no
CoDev-hosted execution, and no credentials read or stored.

### What license is CoDev under?

BSD-3-Clause.

### Where do I report a bug or ask something not covered here?

[Open an issue on GitHub](https://github.com/urban233/CoDev/issues).
