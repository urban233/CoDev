# Walkthrough: auditing `audit-google-python-style` with `codev eval nvidia`

This walks through all three of NVIDIA SkillEvaluator's tiers against one
real, bundled CoDev skill (`.agents/skills/audit-google-python-style`), using
`codev eval nvidia`. Every command and every quoted line of output below was
actually run against the real `skillevaluator` CLI (pinned commit
`e70f0e3ee68bb72d8cf68178a7d4fa2052bc1433`, version 0.2.0) on macOS -- nothing
here is a hypothetical reconstruction. Where a tier could not be completed in
the environment this was written in (no Docker, no LLM/embedding
credentials), that is stated plainly rather than glossed over, and the exact
real error is shown instead of a guess.

For the CLI surface, flags, and envelope schema, see
[README.md](README.md); for the full engineering contract, see
[design.md](design.md).

## Before you start: what each tier needs

| Tier | What it checks | What it needs | Works with nothing configured? |
|---|---|---|---|
| **1** -- Static & Security | Schema, PII, license, code quality, lint, (optional) LLM-assisted security review | Nothing, for the deterministic subset. An LLM credential only if you add `--extra=--llm` | **Yes** |
| **2** -- Deduplication | Embedding-similarity duplicate/redundancy detection | An embeddings credential (`NVIDIA_API_KEY`, `OPENAI_API_KEY`, or `SKILL_EVAL_EMBEDDING_PROVIDER` + friends) | Only when it's the *default*, embedded-in-`validate` form -- it then skips gracefully. A standalone Tier 2 verb (`context-optimization-check`, `similarity-check`, `dedup-scan`) fails fast instead. |
| **3** -- Live agent evaluation | Runs a real agent, with and without the skill, in a sandbox | A public LLM credential, an agent CLI, and a sandbox (Docker by default; 8 other backends exist) | **No** -- always needs live setup |

Nothing below installs Docker, an agent CLI, or a credential for you. CoDev
never provisions or stores any of this -- see [design.md](design.md)'s
Quality and Risk section.

## Tier 1: static & security checks

This is the only tier guaranteed to run to completion out of the box.

```shell
mkdir -p ../skill-evidence/audit-google-python-style
codev eval nvidia validate .agents/skills/audit-google-python-style \
  --output ../skill-evidence/audit-google-python-style
```

Real output, on a machine without SkillSpector/Semgrep/Gitleaks installed:

```text
Note: 'skillevaluator validate' may exercise NVIDIA SkillEvaluator's
live-agent (Tier 3) path, which needs an agent CLI credential and a sandbox
(Docker by default). CoDev does not provision or store either -- configure
your own environment before this succeeds.

╭─ Tier 1 · Static & Security ─────────────────────────────────────────────╮
│  summary   7/11 passed  ·  4 failed  ·  5 warnings                       │
│  ✗ failed  Schema & Repository Governance — Author not specified        │
│  ✗ failed  Security Scan                                                │
│  ✗ failed  Code Risk Analysis                                           │
│  ✗ failed  Secrets Detection                                            │
│  quality   B  81.5 / 100                                                │
╰─────────────────────────────────────────────────────────── ✗ fail · 0.5s─╯

Evaluation failed: ../skill-evidence/audit-google-python-style
```

Only **one** of those four failures is a real, fixable finding: "Author not
specified in metadata" (a genuine gap in `audit-google-python-style/SKILL.md`'s
frontmatter). The other three -- Security Scan, Code Risk Analysis, Secrets
Detection -- are `status: "incomplete"` with an *empty* `findings` array in
the captured native report, because each depends on a separate scanner
SkillEvaluator does not bundle (SkillSpector, Semgrep, Gitleaks), and
SkillEvaluator's own default gating still blocks on an incomplete check. See
[README.md](README.md) for the exact install commands for all three, and for
a `--extra=--checks=...` recipe that narrows the run down to just the one
real finding (verified: 5/6 passed, 0.0s, instead of 4 failures in 0.5s).

**What this needs:** nothing. This is the tier that genuinely works with a
bare `skillevaluator` install and zero credentials.

## Tier 2: deduplication

Tier 2 needs a configured embeddings provider
(`SKILL_EVAL_EMBEDDING_PROVIDER` + `NVIDIA_API_KEY`/`OPENAI_API_KEY`, or the
`openai-compatible` trio `SKILL_EVAL_EMBEDDING_BASE_URL` /
`SKILL_EVAL_EMBEDDING_API_KEY` / `SKILL_EVAL_EMBEDDING_MODEL`). This
environment has none of those set, so Tier 2 could not be completed here --
but the two different ways it degrades without one are both real, observed
behavior, not a guess, and the difference matters:

### Embedded in `validate` (default): skips gracefully

The `validate` run above already shows this -- Tier 2 is on by default
inside `validate` (`--dedup`/`--tier2`), and its own panel reported:

```text
╭─ Tier 2 · Deduplication ──────────────────────────────────────────────────╮
│  skipped  Skipped: configure a public embedding provider (No provider    │
│  is configured (SKILL_EVAL_EMBEDDING_PROVIDER unset and no credential    │
│  found). Set one of: NVIDIA_API_KEY for NVIDIA Build (build.nvidia.com)  │
│  or OPENAI_API_KEY (auto-detected) — or set                             │
│  SKILL_EVAL_EMBEDDING_PROVIDER=openai|nv_build|openai-compatible         │
│  explicitly ...), or pass --no-dedup.                                    │
╰─────────────────────────────────────────────────────────────── · skipped ─╯
```

`validate`'s overall exit code was driven entirely by Tier 1 above; the
missing embeddings credential did not add a second failure on top of it.

### A standalone Tier 2 verb: fails fast instead

```shell
mkdir -p ../skill-evidence/audit-google-python-style-tier2
codev eval nvidia context-optimization-check .agents/skills/audit-google-python-style \
  --output ../skill-evidence/audit-google-python-style-tier2
```

Real output:

```text
INFO     Collecting files from audit-google-python-style...
INFO     Collected 3 file(s)
INFO     Chunking 3 file(s)...
INFO     Extracted 38 chunk(s)
INFO     Embedding 38 chunk(s) via the configured public provider...
INFO       Embedding batch 1/1 (38 chunks)...

Error: context optimization check failed
```
(`engine-result.json` here has `"outcome": "failed"`, `"exit_code": 1`; the
captured native report's `legacy.errors` names the exact cause:
`"[CONTENT_DEDUP-CRITICAL] Embedding provider error: No provider is
configured..."` -- the same message as above, just surfaced as a hard
failure rather than a graceful skip. This completed in well under a second;
it does not hang waiting on a network call that will never succeed.)

**What this needs, to actually complete:** set one credential before
running either command above, for example:

```shell
export NVIDIA_API_KEY=...   # or OPENAI_API_KEY, or SKILL_EVAL_EMBEDDING_PROVIDER + friends
codev eval nvidia context-optimization-check .agents/skills/audit-google-python-style \
  --output ../skill-evidence/audit-google-python-style-tier2-configured
```
CoDev forwards `SKILL_EVAL_*`/`SKILLEVALUATOR_*` and the three named
provider-key variables into the subprocess automatically once they are set
in your own shell (curated allowlist, never a passthrough of your full
environment -- see design.md). This was not run in this environment because
doing so would require a real credential.

## Tier 3: live agent evaluation

Tier 3 needs a public LLM credential, an agent CLI, and a sandbox. Check
readiness first, without running anything:

```shell
mkdir -p ../skill-evidence/nvidia-doctor
codev eval nvidia doctor --output ../skill-evidence/nvidia-doctor
```

Real output, in this environment:

```text
                             SkillEvaluator Doctor
 Check                 Status   Details
────────────────────────────────────────────────────────────────────────────
 CLI package           pass     skillevaluator 0.2.0
 Public LLM provider   fail     No provider is configured
                                (SKILL_EVAL_LLM_PROVIDER unset and no
                                credential found). Set one of: NVIDIA_API_KEY
                                for NVIDIA Build (build.nvidia.com),
                                OPENAI_API_KEY, or ANTHROPIC_API_KEY
                                (auto-detected) ...
 Harbor agents         pass     codex
 docker prerequisite   fail     Docker Compose v2 is required for Tier 3
                                Docker mode: [Errno 2] No such file or
                                directory: 'docker'
```

Two things worth calling out precisely, both observed here rather than
assumed:

- **`doctor` wants Docker *Compose v2* specifically**, not merely a `docker`
  binary. CoDev's own `--env-mode docker` precondition check (which fails
  fast with its own message before ever invoking SkillEvaluator) only checks
  that a `docker` executable resolves on PATH -- a coarser check than
  `doctor`'s. Run `codev eval nvidia doctor` yourself as the authoritative
  readiness signal before attempting a live run; do not rely on CoDev's own
  precondition check alone to mean "Tier 3 will work."
- **`Harbor agents: pass — codex` here despite no `codex` executable being
  on `PATH`** in this environment (confirmed with `which codex`). This check
  does validate the agent *name* against SkillEvaluator's own known roster
  -- passing an obviously made-up name (`totally-fake-agent-xyz`) correctly
  reports `fail: Unknown: totally-fake-agent-xyz`, and `opencode` is
  likewise recognized as a real, if publicly undocumented, option (see
  [how-to.md](how-to.md)'s OpenCode entry). But recognizing the *name*
  is not the same as confirming the binary is actually installed,
  authenticated, and invokable here -- this environment had a leftover
  `~/.codex/` config/auth directory with no real `codex` executable
  present, and that alone was enough for "codex" to report `pass`. Treat
  `doctor`'s agent check as "this is a name SkillEvaluator knows how to
  drive," not "this exact machine can definitely invoke it right now."

### What an actual attempt looks like without full setup

```shell
mkdir -p ../skill-evidence/audit-google-python-style-tier3
codev eval nvidia tier3 evaluate .agents/skills/audit-google-python-style \
  --output ../skill-evidence/audit-google-python-style-tier3 \
  --extra=--agents=codex --extra=--env-mode=docker
```

With Docker genuinely absent, CoDev's own precondition fires first and
SkillEvaluator is never even invoked:

```text
Note: 'skillevaluator tier3 evaluate' may exercise NVIDIA SkillEvaluator's
live-agent (Tier 3) path, which needs an agent CLI credential and a sandbox
(Docker by default). CoDev does not provision or store either -- configure
your own environment before this succeeds.
codev: this command was given --env-mode docker but no `docker` executable
is on PATH; install/start Docker or choose a different --env-mode
```
(exit code `2`; the output directory stays completely empty -- nothing is
published for a precondition failure this early, unlike a genuine subprocess
launch failure or timeout, which still publish a partial `error` envelope.)

There is no supported way to skip CoDev's own Docker precondition and reach
SkillEvaluator directly through `codev eval nvidia`. The following is what
SkillEvaluator itself reports for a missing LLM credential, captured by
running the real `skillevaluator` binary directly (not through CoDev) with
Docker still absent -- included here because it is the very next error a
user would hit immediately after installing Docker without also setting an
LLM credential:

```text
Tier 3 live evaluation: audit-google-python-style
  environment: docker
  agents/models: codex
  plan: baseline=yes
[00:00:00] configuration: running
[00:00:00] configuration: failed - A public LLM provider is required for
live evaluation: No provider is configured (SKILL_EVAL_LLM_PROVIDER unset
and no credential found)...
```
This also completed in a fraction of a second -- it checks its own
configuration before ever touching Docker or spawning an agent, so a
missing credential is caught immediately rather than after a slow sandbox
bring-up.

**What this needs, to actually complete:**

1. **Docker** (or one of 8 other `--env-mode` backends: `daytona`, `e2b`,
   `modal`, `runloop`, `langsmith`, `gke`, `novita`, `apple-container`) --
   installed and running, with Docker Compose v2 available specifically if
   using `docker` mode.
2. **A public LLM provider credential** -- `NVIDIA_API_KEY`, `OPENAI_API_KEY`,
   or `ANTHROPIC_API_KEY` (auto-detected), or `SKILL_EVAL_LLM_PROVIDER` set
   explicitly (`openai-compatible` also needs `SKILL_EVAL_LLM_BASE_URL` /
   `SKILL_EVAL_LLM_API_KEY` / `SKILL_EVAL_LLM_MODEL`).
3. **A working agent CLI** matching whatever `-a/--agents` you pass (e.g.
   `codex`) -- actually invokable, not just a leftover config directory; run
   `codev eval nvidia doctor` yourself to check, and do not treat "pass"
   there as a complete guarantee (see above).

None of this was run to completion in this environment for exactly the
reasons `doctor` reports: no Docker, no LLM credential, and an unverifiable
agent CLI.

## Summary: is it possible to run all three tiers?

Yes, all three are real, reachable code paths in `codev eval nvidia` -- none
are unimplemented. Whether a given tier *completes* in your environment
depends entirely on external setup CoDev deliberately does not provide:

- **Tier 1: yes, unconditionally.** No credentials, no containers, nothing
  to configure. Three of its eleven checks additionally need SkillSpector,
  Semgrep, and Gitleaks installed to move past `"incomplete"` -- see
  [README.md](README.md) for exact install commands.
- **Tier 2: yes, once you export one embeddings credential.** Its embedded
  form (inside `validate`) degrades gracefully without one; a standalone
  Tier 2 verb fails fast instead. Neither hangs.
- **Tier 3: yes, once Docker (or another supported sandbox) plus an LLM
  credential plus a working agent CLI are all genuinely present.** `codev
  eval nvidia doctor` is the right first command to run -- it reports
  exactly which of the three is missing, though its agent check can be a
  false "pass" if stale config exists without the actual binary.
