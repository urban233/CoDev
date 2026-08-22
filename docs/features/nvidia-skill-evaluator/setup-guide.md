# Setup guide: getting NVIDIA SkillEvaluator fully working in CoDev

This is a step-by-step guide to installing and configuring everything
needed for `codev eval nvidia` to run *every* tier -- not just Tier 1 -- using
`.agents/skills/audit-google-python-style` as the running example throughout.
It complements two other documents in this directory:
[README.md](README.md) (CLI reference and a first example) and
[walkthrough-audit-google-python-style.md](walkthrough-audit-google-python-style.md)
(narrated, real captured output showing what each tier does when
prerequisites are and are not met). This guide is the "how do I actually get
there" companion to both.

**A note on package managers:** every install command below is shown with a
language-native installer (`uv tool install`) wherever one exists, because
that is isolated, works identically regardless of how you manage your
system, and is what CoDev itself uses to install `skillevaluator`. Where no
such installer exists, multiple options are listed side by side -- pick
whichever matches how you manage packages (Homebrew, apt, a declarative
manager like nix-darwin/NixOS, `go install`, etc.). CoDev has no opinion on
this and does not install anything for you; nothing in this guide assumes a
specific package manager as the default.

## What "fully working" means

| Tier | "Working" looks like |
|---|---|
| 1 | All 11 checks reach a real `pass`/`fail`, none stuck on `"incomplete"` |
| 2 | Deduplication actually runs and reports similarity findings, instead of skipping/failing on "no embedding provider configured" |
| 3 | A live agent run actually executes in a sandbox and produces a comparison report, instead of failing on a missing credential, agent, or sandbox |

You do not need all three to use `codev eval nvidia` productively -- Tier 1
alone is a real, complete capability. This guide covers all three because
that was asked for, not because Tier 2/3 are required for everyday use.

## Step 1 -- install SkillEvaluator itself

`skillevaluator` has no pinned PyPI release, so this pins a specific
verified commit rather than tracking whatever is on the upstream default
branch today:

```shell
uv tool install --python 3.13 "skillevaluator[all] @ git+https://github.com/NVIDIA/SkillEvaluator.git@e70f0e3ee68bb72d8cf68178a7d4fa2052bc1433"
```

Verify:

```shell
skillevaluator --version
# skillevaluator, version 0.2.0
```

## Step 2 -- a Tier 1 baseline, before any extra scanners

```shell
mkdir -p ../skill-evidence/step2-baseline
codev eval nvidia validate .agents/skills/audit-google-python-style \
  --output ../skill-evidence/step2-baseline
```

With nothing else installed or configured, this is the real result:

```text
╭─ Tier 1 · Static & Security ─────────────────────────────────────────────╮
│  summary   7/11 passed  ·  4 failed  ·  5 warnings                       │
│  ✗ failed  Schema & Repository Governance — Author not specified        │
│  ✗ failed  Security Scan                                                │
│  ✗ failed  Code Risk Analysis                                           │
│  ✗ failed  Secrets Detection                                            │
│  quality   B  81.5 / 100                                                │
╰─────────────────────────────────────────────────────────── ✗ fail · 0.5s─╯
```

Only "Schema & Repository Governance" (missing `metadata.author`) is a real
finding. The other three are `status: "incomplete"` -- each depends on a
scanner not yet installed. That is exactly what Step 3 fixes.

## Step 3 -- install the three scanners Tier 1 needs to fully complete

Three of Tier 1's eleven checks depend on a separate tool SkillEvaluator
does not bundle. None of the three need any credential -- they are all
local, static analysis.

| Check | Tool | Install |
|---|---|---|
| Security Scan | NVIDIA SkillSpector | `uv tool install git+https://github.com/NVIDIA/SkillSpector.git` |
| Code Risk Analysis | Semgrep | `uv tool install semgrep` (or your package manager's `semgrep`) |
| Secrets Detection | Gitleaks | your package manager's `gitleaks` (no PyPI package exists, so there is no `uv tool install` option for this one -- e.g. `go install github.com/gitleaks/gitleaks/v8@latest`, a Homebrew/apt/nix package, or a downloaded release binary) |

```shell
uv tool install git+https://github.com/NVIDIA/SkillSpector.git
uv tool install semgrep
# then gitleaks, via whatever your system uses to install a Go-built CLI binary
```

Verify each landed on `PATH`:

```shell
skillspector --version   # (or: uv tool list | grep skillspector)
semgrep --version
gitleaks version
```

### Re-run the baseline

With SkillSpector and Semgrep installed (Gitleaks intentionally left out for
this example, to show a real partial-progress state rather than an
all-or-nothing jump):

```shell
codev eval nvidia validate .agents/skills/audit-google-python-style \
  --output ../skill-evidence/step3-two-scanners
```

Real result:

```text
╭─ Tier 1 · Static & Security ─────────────────────────────────────────────╮
│  summary   8/11 passed  ·  3 failed  ·  3 warnings                       │
│  ✗ failed  Schema & Repository Governance — Author not specified        │
│  ✗ failed  Security Scan — skillspector JSON field                      │
│  'risk_assessment.recommendation' does not match the risk severity;     │
│  security scan did not complete                                         │
│  ✗ failed  Secrets Detection                                            │
│  quality   B  81.5 / 100                                                │
╰─────────────────────────────────────────────────────────── ✗ fail · 7.9s─╯
```

Two real, concrete things changed, both worth knowing before you rely on
this:

- **Code Risk Analysis (Semgrep) now genuinely passes** -- it dropped off the
  failure list entirely once Semgrep was installed. No credential was
  needed for this one.
- **Security Scan (SkillSpector) still fails, but for a new, different
  reason.** It went from `"incomplete"` (tool missing) to a genuine runtime
  error: *"skillspector JSON field `risk_assessment.recommendation` does not
  match the risk severity; security scan did not complete"* -- a
  compatibility mismatch between this SkillEvaluator version (0.2.0) and
  whatever SkillSpector version `uv tool install` resolved at the time this
  was written. **Installing the tool does not automatically mean the check
  completes cleanly** -- if you hit this, it is a version-pinning problem
  between the two NVIDIA projects, not something wrong with the skill being
  audited or with CoDev's wrapper.
- Secrets Detection (Gitleaks) is still `"incomplete"` here, exactly as
  expected, since it was deliberately left uninstalled for this walkthrough.

Once all three genuinely complete, the only remaining failure on this
particular skill should be the one real, fixable metadata gap.

## Step 4 -- Tier 2: configure an embeddings credential

Tier 2 (deduplication) needs one configured embeddings provider. Pick one:

| Provider | Env vars |
|---|---|
| NVIDIA Build | `NVIDIA_API_KEY` |
| OpenAI (auto-detected) | `OPENAI_API_KEY` |
| Explicit / openai-compatible | `SKILL_EVAL_EMBEDDING_PROVIDER=openai\|nv_build\|openai-compatible`, plus (for `openai-compatible`) `SKILL_EVAL_EMBEDDING_BASE_URL`, `SKILL_EVAL_EMBEDDING_API_KEY`, `SKILL_EVAL_EMBEDDING_MODEL` |

```shell
export NVIDIA_API_KEY=...   # or OPENAI_API_KEY, or the SKILL_EVAL_EMBEDDING_* trio
```

CoDev forwards these into the subprocess automatically once they exist in
your shell -- `eval_nvidia.py`'s environment allowlist passes through every
`SKILL_EVAL_*`/`SKILLEVALUATOR_*` variable plus the two named provider keys,
never anything else from your environment. Then:

```shell
codev eval nvidia context-optimization-check .agents/skills/audit-google-python-style \
  --output ../skill-evidence/step4-tier2
```

**This step was not executed end-to-end while writing this guide** -- doing
so needs a real API credential, which was intentionally not entered here.
What *is* real and already confirmed (see the walkthrough) is the failure
mode without one: this exact command fails fast in well under a second with
`"No provider is configured..."`, never hangs, and (inside `validate`'s
embedded Tier 2 instead) skips gracefully rather than failing at all. Once a
credential is set, expect it to actually run the embedding + similarity
comparison instead of stopping at that message.

## Step 5 -- Tier 3: live agent evaluation

Tier 3 needs three things simultaneously: a sandbox, an agent CLI, and a
public LLM credential.

### 5a. A sandbox

`--env-mode` accepts `docker`, `daytona`, `e2b`, `modal`, `runloop`,
`langsmith`, `gke`, `novita`, or `apple-container`. Docker is the default and
the one CoDev's own wrapper specifically preflights (see below); the other
eight are cloud/remote backends with their own separate account setup this
guide does not cover.

For Docker mode specifically, SkillEvaluator's own `doctor` check wants
**Docker Compose v2**, not merely a `docker` binary -- install however you
normally install Docker on your system (Docker Desktop, `nix-darwin`'s
`virtualisation.docker`, a Linux package, colima, etc.) and confirm:

```shell
docker compose version
```

CoDev's own `--env-mode docker` precondition check (inside `codev eval
nvidia`) only verifies a `docker` executable resolves on `PATH` -- coarser
than what `doctor` actually wants. Treat `codev eval nvidia doctor` (Step
5d) as the authoritative readiness signal, not CoDev's own check alone.

### 5b. An agent CLI

Pick one supported by `-a/--agents` (e.g. `codex`) and make sure it is
genuinely installed and authenticated -- not just that a leftover config
directory exists for it (see the caveat in Step 5d).

### 5c. A public LLM credential

Same shape as Tier 2's embeddings credential, but a **separate**,
parallel environment-variable namespace -- do not confuse the two:

| Provider | Env vars |
|---|---|
| NVIDIA Build | `NVIDIA_API_KEY` |
| OpenAI (auto-detected) | `OPENAI_API_KEY` |
| Anthropic (auto-detected) | `ANTHROPIC_API_KEY` |
| Explicit / openai-compatible | `SKILL_EVAL_LLM_PROVIDER=openai\|anthropic\|nv_build\|bedrock\|openai-compatible`, plus (for `openai-compatible`) `SKILL_EVAL_LLM_BASE_URL`, `SKILL_EVAL_LLM_API_KEY`, `SKILL_EVAL_LLM_MODEL` |

```shell
export ANTHROPIC_API_KEY=...   # or NVIDIA_API_KEY / OPENAI_API_KEY / SKILL_EVAL_LLM_* trio
```

### 5d. Check readiness before attempting a live run

```shell
mkdir -p ../skill-evidence/step5-doctor
codev eval nvidia doctor --output ../skill-evidence/step5-doctor
```

This is the real report with nothing from Step 5 configured yet:

```text
                             SkillEvaluator Doctor
 Check                 Status   Details
────────────────────────────────────────────────────────────────────────────
 CLI package           pass     skillevaluator 0.2.0
 Public LLM provider   fail     No provider is configured...
 Harbor agents         pass     codex
 docker prerequisite   fail     Docker Compose v2 is required for Tier 3
                                Docker mode: [Errno 2] No such file or
                                directory: 'docker'
```

**Caveat, confirmed real:** this row does validate the agent name against a
real, known roster -- a made-up name correctly reports `fail: Unknown: ...`,
and `opencode` is likewise a genuine, if publicly undocumented, recognized
option (see [how-to.md](how-to.md)). But "Harbor agents: pass — codex"
showed here even though no `codex` executable resolved on `PATH` in that
environment -- a leftover config/auth directory for it was apparently
enough to satisfy this specific check. Do not treat a "pass" here as proof
the agent is actually invokable; separately confirm the agent CLI itself
runs and is authenticated.

Fix each `fail` line in turn, re-running `doctor` after each, until all four
rows read `pass`.

**Docker via OrbStack, confirmed real:** installing Docker through OrbStack
(itself declared in a nix flake, i.e. no Homebrew involved) and re-running
`doctor` genuinely flips that row:

```text
 docker prerequisite   pass     ready
```

`docker compose version` on that same machine reported `Docker version
29.4.0` / `Docker Compose version v5.1.2` via OrbStack's context. This
confirms Docker Desktop is not the only real path -- OrbStack (or Colima)
satisfies the same "Docker Compose v2" requirement `doctor` checks for. At
that point the only remaining row was "Public LLM provider" -- i.e. Docker
and the agent name were both genuinely ready; only a credential was left.

### 5e. Run it

```shell
mkdir -p ../skill-evidence/step5-tier3
codev eval nvidia tier3 evaluate .agents/skills/audit-google-python-style \
  --output ../skill-evidence/step5-tier3 \
  --extra=--agents=codex --extra=--env-mode=docker
```

Remember `--extra=VALUE` (with `=`, not a space) whenever `VALUE` itself
starts with `-`; CoDev checks for both the split (`--extra=--env-mode
--extra=docker`) and glued (`--extra=--env-mode=docker`) forms of this
specific flag before deciding whether its own Docker precondition applies,
so either works.

**This exact live command was still not run to completion while writing
this guide** -- Docker did become genuinely available (via OrbStack, above),
but no LLM credential was configured for it, by choice: supplying one would
have meant either pasting a real API key into this conversation, or trusting
a second party to run the command with their own credential neither of
which was the right tradeoff for this particular verification. What *is*
real and already confirmed, in both directions: with Docker genuinely
absent, CoDev's own precondition fires first, before SkillEvaluator is even
invoked, with a friendly message. With Docker present but the LLM credential
missing, SkillEvaluator's own configuration check fails in a fraction of a
second, before touching Docker or an agent -- see the walkthrough document
for the exact captured text of both. Every other precondition for this
command -- the executable, the target, the agent name, and Docker itself --
was independently confirmed ready; only the credential remains, and setting
one (Step 5c above, or the OpenRouter recipe in how-to.md) is the only thing
left before this specific command can run to a real result.

## Full verification checklist

```shell
skillevaluator --version                        # Step 1
codev eval nvidia validate <skill> --output DIR  # Step 2/3: check the panel, not just the exit code
skillspector --version && semgrep --version && gitleaks version   # Step 3
codev eval nvidia doctor --output DIR            # Steps 4/5 readiness in one shot for Tier 3;
                                                  # for Tier 2 specifically, run a Tier 2 verb directly
                                                  # since doctor does not report embeddings readiness
```

`doctor`'s four rows only cover Tier 3 readiness (CLI package, LLM provider,
agents, sandbox) -- it does not have a row for the embeddings provider Tier 2
needs. Confirm Tier 2 readiness by actually running a Tier 2 verb (Step 4)
and checking whether it reports "skipped"/"no provider configured" or
actually produces similarity findings.

## Troubleshooting

- **A Tier 1 check still says `"incomplete"` after installing its tool:**
  confirm the tool resolves on the *same* `PATH` `codev`/`skillevaluator`
  runs with, not just in a different shell profile.
- **Security Scan fails with a SkillSpector JSON-field error even though
  SkillSpector is installed:** this is a version-compatibility mismatch
  between the installed SkillEvaluator and SkillSpector releases (confirmed
  real above, in Step 3), not a CoDev wrapper bug or a real security
  finding -- check both projects' release notes for a matching pair.
- **`codev eval nvidia doctor` says an agent "pass" but a live run still
  can't invoke it:** confirmed real above -- `doctor`'s agent check can be
  satisfied by leftover config alone; separately verify the agent CLI
  itself runs.
- **A `--extra` value starting with `-` gets rejected by argparse:** use
  `--extra=VALUE`, not a space, for that one value.
