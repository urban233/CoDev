# Local OpenCode Skill Evaluation Harness Design

**Status:** Draft
**Owner:** CoDev maintainers
**Reviewers:** Python maintainer; OpenCode CLI domain reviewer
**Brief:** [brief.md](brief.md)
**Last reviewed:** 2026-08-09

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
7. On verifier success, a fresh judge process receives `rubric.md`, the actor
   transcript, the `git diff` from the worktree, and verifier evidence. It must
   return JSON matching the judge-result contract.
8. The harness writes `result.json` and captured text/JSON artifacts to the
   caller's output directory, then removes the worktree and temporary seed.
   Cleanup failure marks the result failed when it can still be written.

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
v1 contract is a fresh `opencode run --format json --dir <worktree>` process for
both actor and judge. The judge prompt is read-only and rubric-constrained; it
must return the judge-result JSON and has no authority to override deterministic
failures. The driver pins those supported flags in tests using a fake executable;
the user-facing CoDev contract above remains stable if OpenCode changes.

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
- **Reliability and concurrency:** Use a unique OS temporary directory per run.
  Run subprocesses in new process groups and terminate their process trees on
  timeout. Cleanup is attempted in `finally` regardless of earlier failure.
  Concurrent runs are safe because output directories must differ.
- **Observability and cost:** Print phase transitions and the final output path.
  Record duration and status for each phase. There is no CoDev-side model cost;
  the user controls their authenticated OpenCode subscription and configuration.
- **Compatibility:** The fixture and result schemas are versioned. V1 rejects
  unsupported versions and unknown fields rather than guessing migrations.
- **Accessibility and internationalization:** CLI messages are concise UTF-8
  plain text; v1 does not introduce a graphical interface.

## Implementation Plan

1. Confirm the supported OpenCode CLI JSON actor and fresh read-only judge
   contracts with a documented compatibility spike. Stop if the installed CLI
   cannot supply isolated noninteractive runs or machine-readable output.
2. Add a standard-library `codev_workflow.eval` boundary for strict fixture and
   result validation, selected-path creation, and atomic evidence writing.
   Unit-test valid data, schema rejection, path traversal, symlink rejection,
   excluded paths, and no-overwrite preflight.
3. Add the sandbox and subprocess boundary. Test temporary Git initialization,
   detached-worktree removal after success and failure, timeout termination,
   and active-target non-mutation using fake `git` and OpenCode executables.
4. Add the verifier and actor/judge orchestration. Test phase ordering,
   artifact capture, verifier-gated judge skipping, malformed judge JSON, and
   the result outcome matrix without calling real OpenCode.
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
Every run removes only its uniquely owned temporary seed and worktree; it never
calls destructive Git commands against the target repository.

## Open Questions

| Question | Owner | Evidence needed | Blocking? |
|---|---|---|---|
| Does the current OpenCode JSON runner preserve the required read-only judge prompt boundary without provider overrides? | OpenCode CLI domain reviewer | Compatibility spike on supported Windows and Linux installations | Yes |
| Does OpenCode inherit project-local configuration from a temporary worktree without an explicit config path? | OpenCode CLI domain reviewer | Compatibility fixture with an installed CoDev project | Yes |
| What output schema can the judge reliably produce for a rubric verdict? | CoDev maintainers | Prompt prototype and malformed-output handling test | Yes |

## Acceptance

- [x] V1 outcome, local-only boundary, and selected-path fixture model are accepted in [brief.md](brief.md).
- [ ] OpenCode compatibility spike resolves the three blocking contracts.
- [ ] Python maintainer and OpenCode CLI domain reviewer approve the design.
- [ ] Accountable human accepts implementation planning against this design.
