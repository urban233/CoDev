# NVIDIA SkillEvaluator Engine Design

**Status:** Accepted
**Owner:** CoDev maintainers
**Brief:** [brief.md](brief.md)
**Last reviewed:** 2026-08-21
**Compatibility evidence:** skillevaluator 0.2.0, commit
`e70f0e3ee68bb72d8cf68178a7d4fa2052bc1433`, on macOS.

## Summary

Add `codev eval nvidia <verb>`, a thin subprocess wrapper around the
externally installed `skillevaluator` CLI (https://docs.nvidia.com/skills/skillevaluator).
Each verb mirrors one SkillEvaluator subcommand, runs it against a caller-given
target, and publishes a small `engine-result.json` process-outcome envelope
plus SkillEvaluator's own native report and captured stdout/stderr into the
caller's `--output` directory, using the same atomic commit-marker publication
already implemented for the native fixture harness.

This is a second, independent evaluation engine, not an extension of the
native OpenCode-based harness (`codev eval fixture|run|snapshot`,
[`../skill-eval/design.md`](../skill-eval/design.md)). The two score
fundamentally different things -- see Alternatives below -- so they share
infrastructure (subprocess execution, environment isolation, durable
publication, redaction, the `EvaluationError` type) rather than a behavioral
interface.

## Goals and Non-goals

### Goals

- Make every SkillEvaluator check that fits an isolated-output-directory
  model (Tier 1, Tier 2, introspection, Tier 3 evaluate/validate) reachable
  from `codev eval nvidia`, with durable, atomically published evidence.
- Never reimplement, re-score, or reinterpret a SkillEvaluator finding.
- Never silently attempt a credentialed or Docker-dependent path; fail fast
  with a clear, printed explanation instead.
- Keep the wrapper thin enough to survive SkillEvaluator's own fast-moving
  CLI surface (new verbs/flags appear between releases; confirmed by the
  compatibility spike finding several verbs -- `dedup-scan`, `health-check`,
  `models` -- not mentioned in SkillEvaluator's own public docs page at all).

### Non-goals

- A shared behavioral interface (e.g. one `run(request) -> result` contract)
  with the native harness.
- Wrapping `create-eval-dataset`, `init-custom-grader`, `init-harbor-task`
  (write into the target skill directory itself) or `view`/`harbor-view`
  (open an interactive HTML/browser viewer). See Alternatives.
- CoDev choosing, storing, or provisioning an LLM/embeddings credential,
  agent-CLI credential, or Docker/sandbox on the user's behalf.
- Pinning, vendoring, or auto-installing `skillevaluator`.

## Current System and Evidence

- `src/codev_workflow/eval.py` already contains tested, general-purpose
  subprocess execution (`_run`, line 1208), environment isolation
  (`_isolated_env`, line 392), atomic evidence publication (`_write_output`,
  line 1723, with the `.codev-eval-commit.json` commit-marker convention),
  and output redaction (`_safe_process_output`, line 198) -- all written for
  the OpenCode actor/judge, none of it OpenCode-specific in implementation.
- Four public wrappers were added to `eval.py` (this change) so a second
  engine can reuse this exact infrastructure without importing
  underscore-prefixed names: `run_process`, `isolated_subprocess_env`,
  `publish_result_bundle`, `redact_process_text`. All four existing call
  sites inside `eval.py` are unchanged; `tests/test_eval.py`'s 81
  pre-existing tests pass unmodified.
- `docs/architecture.md` (lines 74-86) states as invariants: "A target
  repository never imports CoDev as a runtime dependency," "Deterministic
  checks run without network access or model calls," and "Behavioral model
  evaluations remain externally observed and separately run." SkillEvaluator's
  Tier 1 deterministic subset satisfies the first two; its optional LLM/Tier
  2/Tier 3 paths satisfy the third exactly as OpenCode's actor/judge already
  do -- externally observed, separately run, never CoDev-hosted.
- `skillevaluator` has no pinned PyPI release; the only documented install
  path is `uv tool install "skillevaluator[all] @ git+https://github.com/NVIDIA/SkillEvaluator.git"`
  with no version ref. A `uv tool install ...@<commit-sha>` form does pin a
  specific commit, which this design uses (see Compatibility Evidence above).

### Compatibility spike findings

Run against the pinned commit (`skillevaluator --help` and per-verb
`--help`, plus real invocations against a small bundled skill,
`.agents/skills/design-skill-eval`):

- Every check-producing verb (`validate`, `quality-check`, `rubric-eval`,
  `security-scan`, `pii-scan`, `lint-scripts`, `similarity-check`,
  `context-optimization-check`, `dedup-scan`) accepts `-r/--report
  [cli|json|html|markdown]` and `-o/--output-dir DIRECTORY`; `compare` and
  `tier3 evaluate` instead accept `--results-dir DIRECTORY` with no `-r`;
  `doctor`, `health-check`, `models` accept neither -- there is nothing to
  auto-populate for them, only stdout/stderr are captured.
- `-r json -o DIR` reliably writes at least one JSON report file into `DIR`,
  but the **filename is verb-specific** and not documented as stable:
  observed `skillevaluator-output-<timestamp>.json` for `validate`,
  `skillevaluator-similarity.json` for `similarity-check`,
  `skillevaluator-context.json` for `context-optimization-check`,
  `skillevaluator-quality.json` for `quality-check`. `validate` additionally
  writes an unconditional `BENCHMARK.md` regardless of the requested `-r`
  formats. Because the exact set of filenames is not a stable contract, this
  wrapper never assumes a name -- it walks the entire scratch report
  directory after the subprocess exits and captures whatever is there (see
  Envelope Contract).
- Tier 1 gating is fast and fully local: a real run against
  `design-skill-eval` (no credentials configured anywhere in the
  environment) completed in well under a second, correctly found a real
  schema finding (missing `metadata.author`), and exited 1 -- no network
  attempt, no hang. **Correction from an earlier reading of this same run:**
  the "Security Scan," "Code Risk Analysis," and "Secrets Detection" checks
  that also showed as failed were not real findings -- their `status` is
  `"incomplete"` with an empty `findings` array, because they depend on
  three *separate* external scanners SkillEvaluator does not bundle
  (SkillSpector, Semgrep, Gitleaks); each printed its own "not installed"
  warning and skipped. SkillEvaluator's default gating treats an incomplete
  Tier 1 check as blocking, so **a stock `codev eval nvidia validate` run
  will exit 1 out of the box even on a skill with zero real security
  issues**, unless those three tools are also installed. Documented in
  [`README.md`](README.md)'s worked example rather than left as a surprise.
- Tier 2 embedded inside `validate` (the default `--dedup`/`--tier2`) skips
  **gracefully** without an embedding credential, printing a clear
  "configure a public embedding provider... or pass --no-dedup" message and
  not affecting `validate`'s own exit code beyond Tier 1's own result.
- Standalone Tier 2 verbs (`context-optimization-check`, presumably
  `dedup-scan`/`similarity-check` too) do **not** skip gracefully: run
  without a credential, `context-optimization-check` collected and chunked
  the skill's files, then failed fast (well under a second, no hang) with
  `[CONTENT_DEDUP-CRITICAL] Embedding provider error: No provider is
  configured...`, exit 1. This wrapper does not special-case this
  difference -- it is exactly what "run the verb, capture its own exit code
  and message" already does correctly, with no wrapper-side credential
  pre-check needed for Tier 1/2.
- Confirmed environment variable names (from `--help` text and the observed
  error message above): `SKILL_EVAL_LLM_PROVIDER`, `SKILL_EVAL_LLM_MODEL`,
  `SKILL_EVAL_EMBEDDING_PROVIDER`, `SKILL_EVAL_EMBEDDING_BASE_URL`,
  `SKILL_EVAL_EMBEDDING_API_KEY`, `SKILL_EVAL_EMBEDDING_MODEL`,
  `SKILLEVALUATOR_PROFILE`, `SKILLEVALUATOR_PREVIOUS_VERSION`, plus provider
  keys `NVIDIA_API_KEY`/`OPENAI_API_KEY`/`ANTHROPIC_API_KEY`.
  `--env-mode` accepts `docker|daytona|e2b|modal|runloop|langsmith|gke|novita|apple-container`
  (Tier 3 sandboxes); only Docker's own env vars
  (`DOCKER_HOST`/`DOCKER_CONFIG`/`DOCKER_CONTEXT`/`DOCKER_TLS_VERIFY`/`DOCKER_CERT_PATH`)
  are currently forwarded when `--env-mode docker` is requested. The other
  eight sandbox backends' credential env vars are not yet enumerated --
  documented below as a known V1 gap, not silently unsupported.
- `tier3 evaluate` was **not** run live (needs Docker + an agent CLI
  credential this environment does not have); only its `--help` flag surface
  was confirmed.

## Components and Ownership

| Component | Responsibility | Owner | State |
|---|---|---|---|
| CLI | Parse `eval nvidia <verb>` (+ nested `tier3 evaluate`/`tier3 validate`); map to `run_verb` | CoDev CLI | Extend |
| `eval_nvidia.VERBS` | One `VerbSpec` per supported SkillEvaluator subcommand: argv path, target requirement, report flag name, Tier 3 marker | Evaluation package | New |
| `eval_nvidia.run_verb` | Resolve executable, preflight output dir and Tier 3/Docker preconditions, run the subprocess, capture/redact output, build and publish the envelope | Evaluation package | New |
| `eval.py` public wrappers | Subprocess execution, curated env isolation, atomic publication, redaction -- reused unchanged | Evaluation package | Extend (additive only) |

## Data and Control Flow

1. `codev eval nvidia <verb> [SKILL_PATH] --output DIR [--extra FLAG]...`
   resolves to `eval_nvidia.run_verb(verb, target=..., output=DIR,
   extra_flags=[...])`.
2. `run_verb` resolves `skillevaluator` via `shutil.which`, raising
   `EvaluationError` with the pinned install command if absent; validates
   `output` is an existing, empty directory (same precondition the native
   harness's `evaluate()`/`run_snapshot()` already enforce); resolves a
   relative `target` to an absolute path (SkillEvaluator's subprocess does
   not share the caller's cwd, so a relative path would otherwise resolve
   against the wrong directory).
3. If the verb is Tier-3-capable, an explicit stderr notice is printed every
   time (never gated on "first run" -- that would require new persisted
   state this feature does not otherwise need). If `--env-mode docker` is
   present in `--extra`, a `docker` executable must be on PATH or
   `run_verb` fails fast before invoking anything.
4. SkillEvaluator runs as a subprocess with `cwd` set to a private scratch
   directory (not the caller's `--output`, and not the target skill
   directory), an isolated environment (base allowlist plus every
   `SKILL_EVAL_*`/`SKILLEVALUATOR_*` variable currently set, the three named
   provider keys, and Docker's variables when relevant), and the verb's
   report flag (`-o`/`--results-dir`) pointed at that same scratch
   directory. A verb without a report flag gets neither.
5. After the subprocess exits (or times out), every file the subprocess
   wrote into the scratch directory is read back, redacted, and folded --
   together with captured, redacted stdout/stderr -- into one `files: dict`
   published in a single `publish_result_bundle` call. SkillEvaluator's own
   report directory is never the caller's final `--output`, precisely so
   that publication stays one atomic operation rather than "SkillEvaluator
   writes some files directly, then CoDev writes more."
6. A subprocess launch failure publishes an `error`-outcome envelope (no
   native report, since none was produced) and re-raises. A timeout
   similarly publishes an `error`-outcome envelope and raises. Otherwise the
   envelope's `outcome` is `passed` (exit 0) or `failed` (nonzero), and
   `run_verb` returns that boolean without raising.

## Envelope Contract

Every publish writes at minimum:

```text
<output>/
  .codev-eval-commit.json     # existing durable completeness marker
  engine-result.json          # this engine's thin envelope
  nvidia-stdout.txt           # present only if stdout was non-empty
  nvidia-stderr.txt           # present only if stderr was non-empty
  native-report__<name>       # zero or more; flattened basenames of every
                              # file SkillEvaluator itself wrote (a nested
                              # path becomes name__with__double__underscores,
                              # since publish_result_bundle stages files by
                              # flat name only)
```

```json
{
  "schema_version": 1,
  "engine": "nvidia-skillevaluator",
  "verb": "quality-check",
  "target": {"kind": "skill_directory", "path": "/abs/path/to/skill"},
  "process": {"exit_code": 0, "duration_seconds": 0.4, "timeout": false},
  "outcome": "passed",
  "summary": "skillevaluator quality-check exited 0",
  "artifacts": {
    "stdout": "nvidia-stdout.txt",
    "report:skillevaluator-quality.json": "native-report__skillevaluator-quality.json"
  }
}
```

`outcome` is strictly the subprocess's own exit-code/timeout/launch signal --
never a reinterpretation of SkillEvaluator's dimensional scores, gating
results, or findings, which always live in the native report file(s) or
stdout, exactly as captured. The file is deliberately named
`engine-result.json`, not `result.json`, so it is never confused with the
native harness's differently-shaped, already-Accepted `result.json` contract
([`../skill-eval/design.md`](../skill-eval/design.md)); that contract is
unmodified by this change.

## CLI Behavior

| Command | Behavior | Success | Expected errors |
|---|---|---|---|
| `codev eval nvidia VERB [SKILL_PATH] --output DIR [--extra FLAG]...` | Runs one SkillEvaluator subcommand, publishes evidence | `0` if SkillEvaluator's own exit code was `0` | `1` for a completed nonzero exit; `2` for invalid input, unavailable `skillevaluator`, an unmet Tier 3/Docker precondition, or a timeout |
| `codev eval nvidia tier3 evaluate/validate ...` | Same, nested under `tier3` to mirror SkillEvaluator's own expert-alias grouping | as above | as above |

`VERB` is one of: `validate`, `quality-check`, `rubric-eval`, `security-scan`,
`pii-scan`, `lint-scripts`, `similarity-check`, `context-optimization-check`,
`dedup-scan`, `compare`, `doctor`, `health-check`, `models`, plus nested
`tier3 evaluate`/`tier3 validate`. `SKILL_PATH` is omitted for `doctor`,
`health-check`, and `models`, which take none. `--extra` is repeatable and
forwarded verbatim, in order, after CoDev's own flags -- the escape hatch
that keeps this wrapper thin against SkillEvaluator's flag surface, which is
externally owned and (per the spike) evolves between releases faster than a
hand-modeled flag set could track. Argparse's own value-parsing means a
flag-shaped value must use `--extra=--env-mode` (`=`, not a space) rather
than `--extra --env-mode`; this is documented in the flag's own `--help`
text after being found empirically during end-to-end verification.

## Alternatives and Trade-offs

| Option | Benefits | Costs/risks | Decision |
|---|---|---|---|
| One shared behavioral Protocol across both engines | Symmetric, discoverable | Forces SkillEvaluator's multi-dimensional, per-tier output into the native harness's fixed `passed/failed/error` + judge-verdict shape, or leaks SkillEvaluator vocabulary into a "thin" interface | Rejected |
| Shared infrastructure only (this design) | Each engine keeps its true native shape; no lowest-common-denominator flattening | Two independently-shaped result artifacts to know about | Chosen |
| Model every SkillEvaluator flag by name in argparse | Fully documented `--help` per flag | Upstream's flag/verb surface changed release-to-release during the spike itself (`dedup-scan`, `health-check`, `models` all undocumented publicly); a hand-modeled set would drift immediately | Rejected |
| `--extra` passthrough for anything beyond target/output/timeout | Thin, survives upstream churn | Slightly awkward `=` syntax for flag-shaped values | Chosen |
| Point SkillEvaluator's own `-o`/`--results-dir` straight at the caller's `--output` | One less scratch directory | Conflicts with `publish_result_bundle`'s "output must still be empty" precondition, since SkillEvaluator would have already written into it mid-run; breaks atomicity | Rejected |
| Wrap `create-eval-dataset`/`init-*-grader`/`init-harbor-task` | Completes SkillEvaluator's full surface | These intentionally mutate the *target skill directory* (`evals/...`), a genuinely different, mutating contract this design's "everything lands in --output, target is read-only" invariant does not fit | Deferred, undocumented as unimplemented |
| Wrap `view`/`harbor-view` | Completes the surface | Opens an interactive HTML/browser viewer; nothing to capture into an evidence bundle | Excluded |

## Quality and Risk

- **Security and privacy:** environment forwarding is a curated allowlist
  (SkillEvaluator's own `SKILL_EVAL_*`/`SKILLEVALUATOR_*` namespace, three
  named provider keys, Docker's variables when relevant), never a
  passthrough of the calling process's full environment. Captured
  stdout/stderr and every native report file are redacted through the same
  `redact_process_text` used for the native harness's actor/judge output
  before publication.
- **Supply chain:** `skillevaluator` has no pinned release; this design
  pins a specific verified commit (see header) in its own install guidance
  rather than tracking upstream's default branch. `available()` only
  asserts the executable resolves on PATH -- it does not and cannot assert a
  semver compatibility range, since none exists upstream.
- **Known V1 gap -- exotic Tier 3 sandbox backends:** `--env-mode` accepts
  eight backends beyond `docker`; only Docker's credential/env variables are
  currently curated into the allowlist. A user targeting `daytona`, `e2b`,
  `modal`, `runloop`, `langsmith`, `gke`, `novita`, or `apple-container` will
  find that backend's own credentials are not forwarded unless they already
  match the always-allowed `SKILL_EVAL_*` namespace. Documented here as a
  deferred gap, not silently unsupported; extending the allowlist is
  follow-up work once a concrete backend is in use.
- **Known V1 gap -- report filename instability:** SkillEvaluator's native
  report filenames are observed, not documented as a stable contract, and
  differ per verb and per run (timestamped for `validate`). This wrapper
  never depends on a specific name -- it captures whatever is present in the
  scratch directory after the run -- so an upstream rename cannot break
  evidence capture, only potentially change which flattened filename a
  consumer sees.
- **Operational gap -- three Tier 1 checks need scanners SkillEvaluator does
  not bundle:** Security Scan, Code Risk Analysis, and Secrets Detection each
  depend on a separate tool (SkillSpector, Semgrep, Gitleaks respectively).
  Without them, each check comes back `status: "incomplete"` with zero
  findings, and SkillEvaluator's own default gating still treats an
  incomplete Tier 1 check as blocking -- so `codev eval nvidia validate`
  exits 1 on a fresh install even for a skill with no real issues, purely
  because those three scanners are absent. This wrapper does not install
  them (consistent with never auto-installing anything for the user); see
  [`README.md`](README.md) for the exact install commands and for reading
  `native-report__*.json`'s `status` field to tell "incomplete" apart from
  a genuine failed finding.
- **Reliability:** the same process-tree termination, timeout handling, and
  atomic publish-or-nothing guarantee the native harness already provides
  (via the shared `run_process`/`publish_result_bundle` wrappers) applies
  here unchanged.
- **Compatibility:** V1 is macOS-verified against the pinned commit only.
  Windows/Linux support is deferred risk, matching the native harness's own
  V1 posture; `_windows_batch_safe_argv`'s npm-shim assumptions do not apply
  to a `uv tool install`ed executable and should not be relied on if Windows
  support is picked up later.

## Implementation Plan

1. Confirm the compatibility spike against a pinned commit; stop and revise
   the CLI surface if any assumption above does not hold. (Complete --
   see Compatibility spike findings.)
2. Add four public wrappers to `eval.py` with no behavior change to existing
   call sites; run the full existing `test_eval.py` suite to confirm zero
   regression. (Complete -- 81/81 pre-existing tests pass unmodified.)
3. Implement `codev_workflow/eval_nvidia.py` against the confirmed verb
   table. (Complete.)
4. Add `tests/test_eval_nvidia.py` against a fake `skillevaluator` executable
   stub, covering: unknown verb, missing target, missing executable, output
   directory precondition, Docker precondition, curated (non-passthrough)
   environment forwarding, exit-code-to-outcome mapping (both directions),
   timeout mapping, native report capture/flattening, stdout redaction, and
   the Tier 3 stderr notice. (Complete -- 15/15 passing.)
5. Wire `codev eval nvidia <verb>` (+ nested `tier3 evaluate`/`tier3
   validate`) into `cli.py`, generated from the same `VERBS` table so the
   CLI cannot drift from the wrapper's own verb list. (Complete.)
6. Add CLI-level tests (`tests/test_cli.py`) for argument forwarding, the
   target-less verb shape, nested `tier3` dispatch, and the deprecated-alias
   rewriter correctly leaving `eval nvidia ...` untouched. (Complete.)
7. Verify end-to-end against the real, pinned-commit `skillevaluator`
   install (not just the fake stub): a passing `quality-check` run, a
   failing `validate` run with real Tier 1 findings, and the Docker/target
   relative-path fixes this verification pass itself surfaced. (Complete.)

## Test Strategy

- `python -m unittest discover -s tests -v`: 460 tests pass, 0 regressions
  against the pre-existing 456.
- `python -m compileall -q src tests`.
- `python -m ruff check .`, `python -m ruff format --check .`, `python -m mypy`.
- One real, non-mocked smoke run against the pinned `skillevaluator` install
  is the only test in this feature that invokes the actual external tool,
  mirroring the native harness's own "fake executables in unit tests; one
  manually run compatibility fixture against the real tool" split.

## Migration, Rollout, Rollback, and Cleanup

Purely additive: no existing command, schema, or bundle file changes
behavior. `skillevaluator` remains an externally installed, externally
authenticated tool exactly like OpenCode; nothing in `pyproject.toml`
changes, since it is a subprocess dependency, never a Python import.
Removing this feature removes `codev eval nvidia` command access only; it
never touches evidence a developer has already published to their own
`--output` directories.

## Resolved Contracts and Deferred Risks

| Topic | Decision | Evidence or follow-up |
|---|---|---|
| SkillEvaluator CLI surface and report mechanism | Confirmed against pinned commit `e70f0e3ee68bb72d8cf68178a7d4fa2052bc1433` (v0.2.0) | See Compatibility spike findings above |
| Report filename stability | Not assumed; wrapper captures whatever the scratch directory contains after the run | Directory-diff-free `rglob` capture in `run_verb` |
| Env var allowlist for non-Docker Tier 3 sandboxes | Deferred; only `SKILL_EVAL_*`/`SKILLEVALUATOR_*`/three provider keys/Docker vars are curated today | Extend `_DOCKER_ALLOWED_NAMES`-equivalent sets once a concrete backend (daytona/e2b/modal/...) is actually used |
| Windows/Linux compatibility | Deferred risk, not a V1 acceptance requirement, matching the native harness | Qualify before adding either platform as supported |
| `create-eval-dataset`/`init-*-grader`/`init-harbor-task`/`view`/`harbor-view` | Excluded from v1 CLI surface; documented rationale, not silently omitted | Revisit as its own design if a mutating-scaffold or interactive-viewer contract is wanted from CoDev directly |

## Acceptance

- [x] Compatibility spike run against a pinned commit; findings recorded above.
- [x] Shared-infrastructure-not-shared-Protocol architecture accepted (see
  [`../../adr/0026-external-evaluation-engines-are-thin-subprocess-wrappers.md`](../../adr/0026-external-evaluation-engines-are-thin-subprocess-wrappers.md)).
- [x] Full existing test suite passes unmodified (456/456) after the four
  `eval.py` wrapper additions.
- [x] New `eval_nvidia` unit tests (15/15) and CLI tests pass against a fake
  executable stub.
- [x] End-to-end verification against the real, pinned `skillevaluator`
  install, including a genuine Tier 1 failure and a genuine pass.
