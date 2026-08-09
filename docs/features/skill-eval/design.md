# Local OpenCode Skill Evaluation Harness Design

**Status:** Accepted
**Owner:** CoDev maintainers
**Reviewers:** Python maintainer; OpenCode CLI domain reviewer
**Brief:** [brief.md](brief.md)
**Last reviewed:** 2026-08-09
**Compatibility evidence:** OpenCode 1.18.11 on macOS

## Summary

Add a local `codev fixture create` and `codev eval` capability to the package.
Fixtures are deliberately small repository seeds with a prompt, objective
verifier, and judge rubric. An evaluation copies that seed to a temporary Git
repository, creates a detached worktree, runs an OpenCode actor, runs the
verifier, then starts a fresh OpenCode judge only when the verifier succeeds.
The caller selects the result directory, so an evaluation never changes the
active repository.

This is separate from the installed behavioral scenario catalog and its manual
scorer. The harness evaluates observable local execution, not agent reasoning.

## Goals and Non-goals

### Goals

- Make a single, reviewable skill scenario reproducible locally.
- Produce both deterministic and qualitative evidence without an API-key
  provider integration.
- Contain actor changes and all subprocess effects to a temporary worktree.
- Fail safely on invalid fixtures, unavailable OpenCode, process timeouts, and
  cleanup failures.
- Treat macOS as the V1-supported platform. Windows and Linux compatibility is
  deferred risk, not a V1 acceptance requirement.

### Non-goals

- Support more than one actor, verifier command, or judge rubric per fixture.
- Select a model, inject an MCP server, or edit `.opencode/opencode.json`.
- Run in CI, cache dependency installation, or provision external services.
- Replace `scripts/evaluate-development-workflow.py`.

## Current System and Evidence

- `src/codev_workflow/cli.py` uses standard-library `argparse` and returns
  `0` for success and `2` for user, environment, or filesystem errors.
- `src/codev_workflow/installer.py` owns bundle installation and safely merges
  project OpenCode configuration. The harness must not reuse that mutation
  path.
- `scripts/evaluate-development-workflow.py` validates a JSON scenario catalog
  and manually observed results; it has no execution sandbox.
- `docs/architecture.md` requires deterministic checks without network or model
  calls and separately run behavioral model evaluations. The verifier satisfies
  the former; actor and judge are explicitly invoked local model evaluations.
- CoDev requires Python 3.11+ and currently has no runtime dependency beyond
  the standard library patterns used by the CLI and tests.

## Minimal V1 Scope

The initial demonstrable path is one fixture made from a selected subset of the
current repository, one actor execution, one command verifier, and one judge
review. `fixture create` writes a starter that a developer reviews and edits;
it does not infer a complete benchmark or silently overwrite an existing
fixture. `eval` accepts exactly one fixture and requires an output directory.

The actor works against the fixture seed, not the caller's working tree. The
fixture must contain the skills, instructions, and source files needed for its
scenario. This keeps the fixture portable and avoids copying the caller's
uncommitted changes, `.git` history, virtual environments, dependency caches,
or secrets.

## Components and Ownership

| Component | Responsibility | Owner | State |
|---|---|---|---|
| CLI | Parse explicit fixture and evaluation commands; map known failures to exit codes | CoDev CLI | Extend |
| Fixture service | Validate manifests and create selected-path fixture starters | Evaluation package | New |
| Sandbox service | Create a temporary seed repository, detached worktree, and guaranteed cleanup | Evaluation package | New |
| OpenCode driver | Locate OpenCode and start isolated actor and judge processes | Evaluation package | New |
| Verifier service | Execute the fixture's single argv command with a timeout and capture its evidence | Evaluation package | New |
| Result writer | Validate and atomically write a JSON result beneath the explicit output directory | Evaluation package | New |

## Data and Control Flow

1. `codev fixture create` validates the target repository and requested
   `--include` paths before writing anything. It refuses existing fixture names
   and excludes unsafe paths.
2. The command copies selected regular files into `repository/` and writes
   editable `fixture.json`, `prompt.md`, `rubric.md`, and `verifier.json`.
3. `codev eval <fixture> --output <directory>` validates all fixture files
   before creating a temporary directory.
4. The sandbox copies `repository/`, initializes a temporary Git repository,
   commits the seed, then creates a detached worktree from that commit.
5. The actor receives `prompt.md` in a fresh OpenCode process rooted at the
   worktree. Its JSON event stream and final output are captured as artifacts.
6. An actor launch error, nonzero exit, or timeout records a failed result and
   skips the verifier and judge. Otherwise, the verifier runs in the worktree.
   A nonzero verifier exit, timeout, or launch error records a failed result and
   skips the judge.
7. On verifier success, the harness captures the actor transcript, `git diff`,
   and verifier evidence, then removes the worktree and temporary seed before
   judging. A cleanup failure records an error and skips the judge.
8. A fresh judge process runs in a new temporary directory containing only
   copied `rubric.md` and the captured observable artifacts. It has no evaluated
   checkout to mutate and must return JSON matching the judge-result contract.
9. The harness writes `result.json` and captured text/JSON artifacts to the
   caller's output directory, then removes the judge directory. Cleanup failure
   marks the result as an error when it can still be written.

## Fixture Contract

Each fixture is a committed directory with this v1 layout:

```text
.codev/fixtures/<name>/
  fixture.json
  prompt.md
  rubric.md
  verifier.json
  repository/
```

`fixture.json` is the stable fixture identity contract:

```json
{
  "schema_version": 1,
  "name": "fix-parser-boundary",
  "description": "Repair a bounded parsing defect.",
  "actor_timeout_seconds": 600,
  "judge_timeout_seconds": 300
}
```

Requirements: `name` matches the directory name; descriptions are nonempty;
timeouts are positive integers; and unknown fields are rejected in v1. The
prompt and rubric are UTF-8 text. `repository/` is a selected, self-contained
seed and must not contain `.git`, `.env`, `.venv`, `node_modules`, or path
escapes.

`verifier.json` supports one deterministic command without shell parsing:

```json
{
  "schema_version": 1,
  "command": ["python", "-m", "unittest", "discover", "-s", "tests"],
  "timeout_seconds": 120
}
```

`command` is a nonempty array of nonempty strings. The process runs with the
worktree as its current directory, inherits only the ordinary execution
environment, and captures stdout, stderr, duration, exit code, and timeout
status. V1 does not install dependencies or invoke a shell.

## Result Contract

The caller supplies an empty, existing output directory. The harness atomically
writes each evidence file into it using a staging path and writes this layout:

```text
<output>/
  .codev-eval-commit.json # hidden durable completeness marker
  result.json
  actor-events.jsonl
  actor-output.txt
  verifier-stdout.txt
  verifier-stderr.txt
  judge-events.jsonl       # present only after verifier success
  judge-output.json        # present only after verifier success
  diff.patch
```

`result.json` is the stable machine-readable summary. Paths are relative to the
output directory so evidence can be relocated together.

Publication is a single result-bundle transaction. The harness stages every
evidence file, validates an expected-path and content manifest, flushes file and
directory data, and writes `.codev-eval-commit.json` last. The marker contains
the result schema version, bundle identifier, and expected artifact manifest.
Consumers must validate the marker and every listed file before treating the
output as a complete evaluation. An interrupted or invalid bundle is removed
or recovered before a subsequent read; it must never be reported as complete.
The marker is implementation metadata and is not included in the user-facing
artifact summary.

```json
{
  "schema_version": 1,
  "fixture": {"name": "fix-parser-boundary", "path": ".codev/fixtures/fix-parser-boundary"},
  "outcome": "passed",
  "actor": {"status": "completed", "duration_seconds": 42.1},
  "verifier": {"status": "passed", "exit_code": 0, "duration_seconds": 3.4},
  "judge": {"status": "passed", "verdict": "pass"},
  "artifacts": {"diff": "diff.patch", "actor_events": "actor-events.jsonl"}
}
```

Allowed top-level outcomes are `passed`, `failed`, and `error`. `failed` means
the actor, verifier, or judge completed with a negative evaluation. `error`
means fixture validation, process launch, malformed judge output, output write,
or cleanup prevented a valid evaluation. A verifier failure has
`judge.status: "skipped"`. No result may be `passed` unless actor, verifier,
and judge all pass.

### Judge-result Contract

The judge writes exactly one UTF-8 JSON object to standard output. Its complete
v1 schema is:

```json
{
  "schema_version": 1,
  "verdict": "pass",
  "summary": "Short rubric-based explanation.",
  "findings": [
    {
      "criterion": "rubric criterion identifier or text",
      "verdict": "pass",
      "evidence": "Observable artifact evidence."
    }
  ]
}
```

All fields are required. `schema_version` must be `1`; top-level `verdict` and
each finding `verdict` must be `pass` or `fail`; `summary`, `criterion`, and
`evidence` must be nonempty strings; `findings` must be nonempty; and unknown
fields are rejected. The judge prompt directs findings to the fixture rubric
only and supplies only the copied observable artifacts.

A valid top-level `pass` allows an evaluation to pass only after actor and
verifier success. A valid top-level `fail` produces a failed evaluation. Empty
output, malformed JSON, a schema violation, a judge launch error, or a judge
timeout produces an error. The harness retains the captured judge events and
raw output as evidence whenever the judge was launched.

## CLI Behavior

| Command | Behavior | Success | Expected errors |
|---|---|---|---|
| `codev fixture create NAME --target PATH --include PATH...` | Preflights paths, creates `.codev/fixtures/NAME`, copies selected files, and writes starter metadata | `0`; prints created paths and next edit steps | `2` for non-repository target, unsafe/missing include, invalid name, or existing fixture |
| `codev eval NAME --target PATH --output PATH` | Validates fixture, runs the isolated actor, verifier, and conditional judge, then writes evidence | `0` only for a passing evaluation | `1` for a completed failed evaluation; `2` for invalid input, unavailable OpenCode, infrastructure failure, or unwritable output |

`--include` is repeatable and relative to `--target`; directory inclusions copy
their contained regular files. The creator rejects symlinks, absolute paths,
paths outside the target, and `.env`, `.git`, `.venv`, `node_modules`, and
other configured exclusions. It must preflight every source and destination
before creating the fixture directory.

`eval` resolves `NAME` only below `--target/.codev/fixtures`. It requires an
empty, caller-created `--output` directory and never creates output in the
target repository. It verifies `git` and `opencode` before sandbox creation.
V1 uses the installed OpenCode executable and project-local configuration as
discovered from the worktree; it never writes a configuration file or supplies
a model/provider flag.

The exact OpenCode invocation is deliberately an adapter boundary. The supported
v1 contract is a fresh `opencode run --format json --dir <directory> <message>`
process, where `<message>` is the actor prompt or judge prompt. The actor runs
in the worktree; the judge runs in the separate evidence-only judge directory.
The judge is rubric-constrained, must return the judge-result JSON, and has no
authority to override deterministic failures. The driver pins those supported
flags and positional prompt transport in tests using a fake executable; the
user-facing CoDev contract above remains stable if OpenCode changes.

## Alternatives and Trade-offs

| Option | Benefits | Costs/risks | Decision |
|---|---|---|---|
| Selected-path fixture seed | Small, reviewable, portable; excludes active worktree and secrets | Fixture authors must include all needed files | Chosen |
| Sanitized full repository copy | More automatic fixture creation | Large, secret-prone, less reviewable, less reproducible | Rejected |
| Direct active-repository worktree | Uses existing dependencies | Couples evaluation to local state and risks developer files | Rejected |
| Judge after verifier success | Qualitative evidence cannot mask objective defects | No explanation from judge on verifier failures | Chosen |
| Judge on every run | More diagnostics | Spends model time on deterministically failed attempts | Rejected |

## Quality and Risk

- **Security and privacy:** Treat fixture contents, actor output, and diffs as
  potentially sensitive local data. Do not upload, log environment variables,
  or copy excluded paths. Do not accept arbitrary shell strings in a verifier.
- **Judge integrity:** The judge runs only after successful actor-worktree and
  seed cleanup, in a separate temporary directory containing copied evidence.
  It therefore cannot modify the evaluated checkout. It cannot turn an actor or
  verifier failure into a pass.
- **Known V1 publication issue:** Evidence files are published into the
  caller-provided output directory before the durable commit marker is final.
  A process interruption during that narrow window can leave partial evidence,
  and a concurrent replacement of the output directory can create a
  publication race. Normal completed runs validate the commit marker and
  manifest, but crash-consistent single-bundle publication is deferred and is
  not being fixed in V1. Callers should use a unique output directory and
  discard incomplete outputs that lack a valid commit marker.
- **Accepted V1 privacy risk:** Unstructured diagnostic text may contain
  credential-bearing URLs, including user-info or sensitive query parameters,
  that the conservative sanitizer does not reliably redact. Structured JSON
  secret fields are sanitized, but URL credential detection is deferred. V1
  users must avoid placing credentials in fixture/process diagnostics; a later
  hardening change should add URL-aware redaction.
- **Reliability and concurrency:** Use a unique OS temporary directory per run.
  Run subprocesses in new process groups and terminate their process trees on
  timeout. Cleanup is attempted in `finally` regardless of earlier failure.
  Concurrent runs are safe because output directories must differ. This behavior
  was exercised on macOS only for V1; Windows and Linux cleanup semantics remain
  deferred compatibility risk.
- **Observability and cost:** Print phase transitions and the final output path.
  Record duration and status for each phase. There is no CoDev-side model cost;
  the user controls their authenticated OpenCode subscription and configuration.
- **Compatibility:** The fixture and result schemas are versioned. V1 rejects
  unsupported versions and unknown fields rather than guessing migrations.
- **Accessibility and internationalization:** CLI messages are concise UTF-8
  plain text; v1 does not introduce a graphical interface.

## Implementation Plan

1. Confirm the supported OpenCode CLI JSON actor and separate evidence-only
   judge contracts with a documented compatibility spike. Stop if the installed
   CLI cannot supply isolated noninteractive runs or machine-readable output.
2. Add a standard-library `codev_workflow.eval` boundary for strict fixture and
   result validation, selected-path creation, and atomic evidence writing.
   Unit-test valid data, schema rejection, path traversal, symlink rejection,
   excluded paths, and no-overwrite preflight.
3. Add the sandbox and subprocess boundary. Test temporary Git initialization,
   detached-worktree removal after success and failure, timeout termination,
   and active-target non-mutation using fake `git` and OpenCode executables.
4. Add the verifier and actor/judge orchestration. Test phase ordering,
   artifact capture, verifier-gated judge skipping, cleanup-before-judge,
   malformed judge JSON, and the result outcome matrix without calling real
   OpenCode.
5. Register the two CLI commands and add integration tests for exit codes,
   required `--output`, output atomicity, and a complete passing evaluation
   driven by fake executables.
6. Add one bundled example fixture and human documentation after the harness
   behavior is stable. Update package data only for files intended to install
   into target repositories.

## Test Strategy

- Run `python -m unittest discover -s tests -v` for all additions.
- Run `python -m compileall -q src tests` for package and test syntax.
- Run `python -m ruff check .`, `python -m ruff format --check .`, and
  `python -m mypy` for repository static checks.
- Add contract fixtures for schema versions, result outcomes, and unsafe paths.
- Use fake executables in tests; a manually run compatibility fixture is the
  only v1 test that invokes the real authenticated OpenCode CLI.

## Migration, Rollout, Rollback, and Cleanup

This is additive: no existing command, managed bundle file, or workflow catalog
changes behavior. Ship the commands as experimental in the release notes with
one example fixture. Removing the package version removes command access but
does not delete developer-authored fixtures or caller-selected evidence output.
Every run removes only its uniquely owned temporary seed, worktree, and judge
directory; it never calls destructive Git commands against the target
repository.

## Resolved Contracts and Deferred Risks

| Topic | Decision | Evidence or follow-up |
|---|---|---|
| OpenCode actor, judge output, and project configuration | Supported for V1 on macOS with OpenCode 1.18.11. | Compatibility spike recorded an isolated actor edit, a fresh judge result of `{"verdict":"pass"}`, and temporary-worktree configuration discovery. |
| Judge isolation | Cleanup the actor worktree and seed before judge launch; run the judge only against copied observable artifacts in a separate temporary directory. | Test successful cleanup before judge launch and judge skipping after cleanup failure. |
| Judge-result schema | Use the strict v1 JSON contract above. | Test valid pass/fail responses plus malformed JSON, unknown fields, missing fields, and invalid values. |
| Windows and Linux compatibility | Deferred risk; not a V1 acceptance requirement. | Qualify cleanup and process-tree behavior before adding either platform as supported. |
| Crash-consistent publication | Known V1 issue; deferred. | A later hardening change should publish one atomic result bundle or otherwise eliminate partial-output and directory-replacement races. |
| URL credentials in unstructured diagnostics | Accepted P1 V1 risk; deferred. | A later hardening change should redact URL user-info and sensitive query parameters before persistence and judge staging. |

## Acceptance

- [x] V1 outcome, local-only boundary, and selected-path fixture model are accepted in [brief.md](brief.md).
- [x] Judge isolation and judge-result schema contracts are accepted for V1.
- [x] macOS OpenCode 1.18.11 compatibility spike supports actor execution,
  judge output, and temporary-worktree project configuration discovery.
- [x] V1 publication crash-consistency limitation is documented as a known issue
  and explicitly deferred.
- [x] URL-credential redaction gap is documented as an accepted P1 V1 risk and
  explicitly deferred.
- [ ] Python maintainer and OpenCode CLI domain reviewer approve the design.
- [x] Accountable human accepts implementation planning against this design,
  with Windows/Linux retained as deferred risk.
