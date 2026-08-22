# How-to: short setup recipes for `codev eval nvidia`

Focused, single-purpose recipes for the individual setup tasks that come up
while getting `codev eval nvidia` fully working. For the narrated,
step-by-step journey through all three tiers in order, see
[setup-guide.md](setup-guide.md); for real captured output at each stage,
see [walkthrough-audit-google-python-style.md](walkthrough-audit-google-python-style.md).

Every recipe below assumes no specific package manager. This project does
not prescribe Homebrew, apt, or anything else -- use whatever you already use
to manage packages on your system (including a declarative one like
nix-darwin or NixOS), and prefer a language-native, isolated installer
(`uv tool install`, `pipx`, `go install`, ...) over a system package manager
where one exists.

## How do I install Docker (with Compose v2)?

SkillEvaluator's Tier 3 `--env-mode docker` needs Docker **with Compose
v2**, not just any `docker` binary. Options, pick one that fits how you
manage your system:

- **Docker Desktop** (macOS/Windows/Linux): the official installer from
  docker.com bundles Compose v2 automatically. This is the path most likely
  to just work without extra configuration.
- **Your package manager**: many distros/managers package `docker` and
  `docker-compose-plugin` (or equivalent) separately -- check that both land,
  since an older `docker` install without the Compose v2 plugin will still
  fail SkillEvaluator's own readiness check.
- **A declarative system config** (nix-darwin, NixOS, Home Manager, etc.):
  add Docker (and Colima, if you run it that way on macOS) through your own
  configuration the way you normally add packages, then rebuild/switch.
- **Colima / OrbStack** (macOS alternatives to Docker Desktop): both provide
  a `docker` CLI with Compose v2 support; either works as a drop-in.
  **Confirmed real:** OrbStack, declared through a nix flake (no Homebrew
  involved), satisfied SkillEvaluator's own `docker prerequisite` check in
  `codev eval nvidia doctor` -- it reported `docker compose version` as
  `Docker version 29.4.0` / `Compose v5.1.2` via OrbStack's context, and
  `doctor` flipped that row to `pass`.

Verify, regardless of which path you took:

```shell
docker compose version
```

If this fails, Tier 3's `--env-mode docker` will not work yet, no matter
what `docker --version` alone reports.

## How do I check my system is ready for Tier 3, before attempting a live run?

```shell
codev eval nvidia doctor --output <empty-dir>
```

This reports four things: the CLI package itself, your public LLM provider
credential, whether your named agent(s) are recognized, and the Docker
prerequisite (or whichever `--env-mode` you specify via `--extra`). Pass
your intended agent(s) so the "Harbor agents" row actually reflects what you
plan to use:

```shell
codev eval nvidia doctor --output <empty-dir> --extra=--agents=opencode --extra=--env-mode=docker
```

**Important caveat, confirmed by testing it:** the "Harbor agents" row
validates the agent *name* against SkillEvaluator's own known roster --
passing a made-up name like `totally-fake-agent` correctly reports
`fail: Unknown: totally-fake-agent`, so this check is real, not a rubber
stamp. But a "pass" only means *the name is recognized*, not that the
actual CLI binary is installed, authenticated, and invokable on your
machine right now -- separately confirm that yourself (e.g. run `opencode
--version` and check you're logged in).

## How do I set the environment variables SkillEvaluator needs?

Three different scopes, depending on how long you want a value to stick
around:

**One command only** (safest -- never touches your shell's persistent
state):

```shell
NVIDIA_API_KEY=... codev eval nvidia validate <skill> --output <dir>
```

**Current shell session** (until you close the terminal):

```shell
export NVIDIA_API_KEY=...
export SKILL_EVAL_LLM_PROVIDER=openai
```

**Persistently, across sessions:** add the same `export` lines to your
shell's startup file (`~/.zshrc`, `~/.bashrc`, or equivalent) -- or, if you
manage your shell environment declaratively (nix-darwin's
`environment.variables`, Home Manager's `home.sessionVariables`, etc.), add
them there instead so they stay reproducible along with the rest of your
configuration, rather than editing a dotfile by hand.

Never put a credential directly in a command you'll save to shell history
verbatim (some shells record it either way) or commit it to a fixture,
config file, or this repository -- see design.md's Quality and Risk section
for what CoDev itself does and does not do with these variables (never
stores, prints, or persists them; forwards only a curated, explicitly named
allowlist into the SkillEvaluator subprocess).

## How do I get an LLM provider credential (for SkillEvaluator's own grading)?

This is the credential SkillEvaluator uses for its *own* work -- optional
Tier 1 LLM-assisted security review and the Tier 3 dimension judge. It is
**not** the same thing as an agent's own credential (see the OpenCode
question below) -- SkillEvaluator's grading model and the agent being
evaluated can use entirely different providers, or the same one.

| Provider | What to set |
|---|---|
| NVIDIA Build | `NVIDIA_API_KEY` |
| OpenAI | `OPENAI_API_KEY` (an OpenAI **Platform/API** key with billing enabled -- not a ChatGPT Plus/Pro/Team login, which does not by itself grant API access) |
| Anthropic | `ANTHROPIC_API_KEY` |
| Any OpenAI-compatible endpoint (including **OpenRouter**) | `SKILL_EVAL_LLM_PROVIDER=openai-compatible`, `SKILL_EVAL_LLM_BASE_URL`, `SKILL_EVAL_LLM_API_KEY`, `SKILL_EVAL_LLM_MODEL` |

Set exactly one. Verify with `codev eval nvidia doctor` -- its "Public LLM
provider" row reports `pass`/`fail` directly.

**Can I use OpenRouter?** For this credential, yes -- OpenRouter exposes an
OpenAI-compatible chat-completions API (confirmed against OpenRouter's own
docs), so it fits the `openai-compatible` row above:

```shell
export SKILL_EVAL_LLM_PROVIDER=openai-compatible
export SKILL_EVAL_LLM_BASE_URL=https://openrouter.ai/api/v1
export SKILL_EVAL_LLM_API_KEY=sk-or-...
export SKILL_EVAL_LLM_MODEL=anthropic/claude-3.5-sonnet   # any model slug OpenRouter serves
```

This satisfies Tier 1's optional `--llm` security review and the Tier 3
dimension judge. It does **not** need to be the same provider your agent
itself uses -- see the OpenCode question below for that separate,
independent credential.

## How do I get an embeddings credential (for Tier 2 dedup)?

A separate, parallel namespace from the LLM provider above -- do not mix
the two up:

| Provider | What to set |
|---|---|
| NVIDIA Build | `NVIDIA_API_KEY` (same variable as the LLM provider table -- one key can satisfy both roles if it's from NVIDIA Build) |
| OpenAI | `OPENAI_API_KEY` (same caveat: needs real API/Platform access) |
| Any OpenAI-compatible endpoint | `SKILL_EVAL_EMBEDDING_PROVIDER=openai-compatible`, `SKILL_EVAL_EMBEDDING_BASE_URL`, `SKILL_EVAL_EMBEDDING_API_KEY`, `SKILL_EVAL_EMBEDDING_MODEL` |

There is no `doctor` row for this one -- verify by actually running a Tier 2
verb (`codev eval nvidia context-optimization-check <skill> --output <dir>`)
and checking whether it produces similarity findings instead of "no
provider configured."

**Can I use OpenRouter here too?** Unconfirmed, and the two checks I ran
disagreed with each other -- OpenRouter's own chat-completions reference
page shows no embeddings endpoint, but a broader OpenRouter docs page
claims client SDK support for "streaming, embeddings, and the complete API
reference" with no endpoint detail given. I could not resolve this
conflict from the documentation alone and did not have a credential to test
it directly. Treat OpenRouter as **confirmed only for the LLM/grading
credential above, not for embeddings** until you've verified it yourself
(e.g. a direct request to `https://openrouter.ai/api/v1/embeddings`) --
NVIDIA Build or OpenAI directly are the safer choice for this one if you
want Tier 2 working without first checking that.

## How do I use my own OpenCode installation, with my own OpenAI subscription, as the Tier 3 agent?

**Short answer: yes, this is a real, working combination** -- with two
things worth understanding precisely before you rely on it.

**1. `opencode` is a genuinely recognized Harbor agent, confirmed by
testing it directly** (not merely assumed from NVIDIA's public docs, which
only show `codex` and `claude-code` in their examples):

```shell
skillevaluator doctor -a opencode --env-mode docker
#  Harbor agents   pass   opencode
skillevaluator doctor -a totally-fake-agent --env-mode docker
#  Harbor agents   fail   Unknown: totally-fake-agent
```

Since the second command correctly rejects a made-up name, the first
confirms `opencode` is a real, known option -- just one NVIDIA's own README
does not currently list as an example. Treat it as real but undocumented:
it could change in a future SkillEvaluator release without that being
called out anywhere.

**2. Two separate credentials are involved, and your OpenAI subscription
covers the *agent's* side, not necessarily SkillEvaluator's own side:**

- **The agent's own credential** (what actually performs the task being
  evaluated) is whatever your local OpenCode installation already has
  configured -- run `opencode auth login` (or however you normally
  authenticate it) the same way you would to use OpenCode for anything
  else. If OpenCode is set up to use OpenAI as its model provider, this is
  exactly "your own OpenAI subscription" driving the agent.
- **SkillEvaluator's own grading credential** (the Tier 3 dimension judge) is
  the separate `SKILL_EVAL_LLM_PROVIDER`/`NVIDIA_API_KEY`/`OPENAI_API_KEY`/
  `ANTHROPIC_API_KEY` from the table above. You can point this at the same
  OpenAI account (set `OPENAI_API_KEY` once, and it satisfies both roles),
  or at a different provider entirely -- SkillEvaluator does not require
  the agent and the judge to match.
- **Confirmed, not assumed:** CoDev's own environment isolation already
  forwards `OPENCODE_API_KEY`, `OPENCODE_AUTH_TOKEN`, and
  `OPENCODE_SERVER_PASSWORD` into every `codev eval nvidia` subprocess
  unconditionally -- the same three variables the *native* OpenCode-based
  harness forwards to its own actor/judge. If your OpenCode authentication
  lives in one of those three environment variables, it reaches
  SkillEvaluator with zero extra CoDev-side configuration. If instead your
  OpenCode auth lives only in its own local config file (e.g. from `opencode
  auth login`), that is a file on disk, not an environment variable, and
  whether Harbor's sandbox can see it depends on Harbor's own
  volume/credential-mounting mechanism for the agent -- which is not
  documented publicly and was not possible to verify end-to-end while
  writing this guide (no Docker sandbox was available). Run `codev eval
  nvidia doctor -a opencode --env-mode docker` yourself once Docker is set
  up, then attempt a real `tier3 evaluate` run, to confirm your specific
  authentication method actually reaches the sandboxed agent.

```shell
export OPENAI_API_KEY=...   # satisfies SkillEvaluator's own grading credential
# authenticate opencode itself however you normally do, e.g.:
opencode auth login
codev eval nvidia tier3 evaluate <skill> --output <dir> \
  --extra=--agents=opencode --extra=--env-mode=docker
```

## How do I install and authenticate a different Tier 3 agent (e.g. `codex`, `claude-code`)?

Install and authenticate that agent CLI exactly the way you normally would,
outside of CoDev entirely -- SkillEvaluator's Harbor framework drives an
already-working agent CLI, it does not install or configure one for you, and
neither does CoDev. Confirm it is recognized the same way as above:

```shell
skillevaluator doctor -a codex --env-mode docker
skillevaluator doctor -a claude-code --env-mode docker
```

## How do I verify the whole system, end to end, before trusting a result?

```shell
skillevaluator --version                                    # Step: installed
codev eval nvidia doctor --extra=--agents=<yours> --extra=--env-mode=docker --output <dir>   # Tier 3 readiness
codev eval nvidia context-optimization-check <skill> --output <dir>   # Tier 2 readiness (no doctor row for this)
codev eval nvidia validate <skill> --output <dir>            # Tier 1, plus embedded Tier 2
```

Read each result's `native-report__*.json` (or the printed panel) and check
a failing check's `status` field, not just `passed` -- `"incomplete"` means
a dependency is missing, not that a real problem was found. See
[README.md](README.md)'s "Reading a `failed` result" section for the exact
distinction, confirmed on a real run.
