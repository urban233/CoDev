# Native skill-eval harness: developer ergonomics and terminology

**Status:** Accepted
**Owner:** CoDev maintainers

## Problem

The native skill-evaluation harness (`docs/features/skill-eval/`) works, but writing
a new test for a skill is unpleasant, slow, and inconsistent:

- **No shared verifier code.** Every committed fixture's `repository/check_*.py`
  independently reimplements the same JSON-loading, keyword-matching, and
  file-purity-checking boilerplate from scratch. Measured directly: the three
  existing verifier scripts (`check_review.py`, `check_test_double.py`,
  `check_audit_plan.py`) total 277 lines with near-identical
  `json.load`/`except (OSError, json.JSONDecodeError)` blocks and three
  independently hand-rolled "does this finding mention the right keywords"
  matchers -- and three *different*, incompatible ways of checking whether the
  actor touched only the files it was allowed to.
- **No fast iteration loop.** A typo in a verifier script is only discoverable
  after a full ~10-minute real OpenCode actor run. There is no dry-run and no
  developer-facing way to test verifier logic against a synthetic response --
  even though this exact pattern (a fake-executable stub standing in for
  OpenCode) already exists internally in `tests/test_eval.py` and is simply
  never exposed to the person writing a new fixture.
- **No human-readable report.** Every result is a directory of raw JSON/text
  files; reading one means `cat`-ing files and manually cross-referencing
  `result.json` against `actor-output.txt`.
- **One scoring dimension.** The harness only has `passed|failed|error` plus one
  prose rubric reviewed by a judge. There is no way to see "security was fine
  but efficiency wasn't" without writing free text and hoping the judge
  addresses it.
- **The vocabulary doesn't help.** "Fixture" does not communicate what the
  directory actually is (a defined unit of work an agent attempts, with
  expected behavior and a verification method). This is confirmed as a real,
  fixable gap, not a bikeshed: the vocabulary this problem space actually uses
  -- **task**, **trial**, **trajectory**, **baseline**, **verifier** -- is a
  broadly shared standard across DeepMind's own public agent-evaluation work
  (SIMA/SIMA 2's task/episode/environment/trajectory framing), Google Cloud's
  agent-evaluation guidance (task/trial/trajectory), and NVIDIA SkillEvaluator's
  own code and file names, observed directly while building
  [`../nvidia-skill-evaluator/`](../nvidia-skill-evaluator/) this cycle:
  `trajectory.json`, `reward.json`, `trial_name`/`trial_id`,
  `task_name`/`task_id`, a Docker environment class literally named
  `...SecureDockerEnvironment`, and `--skip-baseline`/`"source": "with"` vs.
  `"without"` for the with/without-skill comparison. `verifier.json` and
  `result.json` are already exact matches to SkillEvaluator's own naming --
  nothing to change there.

## Outcome

Writing a new skill test should mean: create a task, write its prompt and a
short list of expected-behavior assertions, run it against a fake response
locally in seconds to check the logic, then run it for real -- reusing a
shared library for the common assertion shapes instead of writing a Python
script from scratch every time. Terminology throughout matches the field's
actual vocabulary for this problem, scoped so it never collides with CoDev's
existing, unrelated `codev task` (development work-item) command group.

## First-release scope

1. **Terminology rename**, CLI-surface only under the existing `codev eval`
   namespace (never a bare `codev task`, which already means something
   different -- development work-item tracking, per
   `docs/adr/0023-work-item-renamed-to-task.md`):
   - `codev eval fixture create` -> **`codev eval task create`**
   - `codev eval run <name>` -> **`codev eval task run <name>`**
   - `--without-skill` -> **`--baseline`** (matches SkillEvaluator's own term
     for the without-skill condition)
   - `codev eval snapshot run <skill>` -> **`codev eval benchmark run <skill>`**
   - `actor-events.jsonl`/`actor-output.txt` -> **`trajectory.json`**
   - one actor+verifier+judge execution attempt is named a **trial**
     internally and in docs
   - `verifier`/`verifier.json`/`result.json` unchanged -- already correct
   - **Clean break, no deprecated aliases:** CoDev is still Alpha, so
     `fixture`/`eval run`/`eval snapshot run` are removed outright rather than
     kept working via `_apply_deprecated_aliases`. Every existing committed
     fixture is migrated to the new format and location as part of this
     work, not left running on a compatibility shim.
2. **A shared verifier-helpers module** fixture-turned-task verifier scripts
   can import, covering the patterns duplicated three times today: load and
   validate a structured JSON output file, match a finding against expected
   keywords/location, and check that only explicitly allowed files changed
   since the seed commit.
3. **A declarative-checks escape hatch**: express the common
   assertion/expected-behavior shapes as data (mirroring SkillEvaluator's own
   `assertions`/`expected_behavior` lists) with a shared runner, while keeping
   a full custom Python verifier available for anything that doesn't fit --
   this is not a replacement for `verifier.json`, it's an alternative to
   writing one from scratch for the common cases.
4. **`codev eval doctor`**: a fast, zero-cost readiness check (git present,
   OpenCode present and reachable) before a real trial run, mirroring
   SkillEvaluator's own `doctor`.
5. **A local dry-run / fake-agent mode** exposing the existing internal
   fake-executable test pattern to task authors, so verifier logic can be
   checked in seconds instead of minutes.
6. **A human-readable report renderer** for a trial's or benchmark's output
   directory, so reading a result doesn't mean manually `cat`-ing JSON files.
7. **An opt-in Docker sandbox backend** for a trial's environment, alongside
   the existing git-worktree isolation -- additive, off by default, a real,
   explicitly flagged exception to the existing "no containers" non-goal, not
   a silent departure from it. Same task format, same
   prompt/verifier/judge flow; only where the actor actually executes changes.

## Non-goals

- Renaming or restructuring `codev task` (the development work-item tracker) --
  it is unrelated and unaffected; this rename is scoped entirely under
  `codev eval`.
- Replacing the OpenCode actor/judge driver or its isolation model by default --
  Docker is opt-in, worktree isolation stays the default.
- A full declarative-only verifier system -- custom Python verifiers remain a
  first-class option for anything the declarative layer can't express.
- Adopting SkillEvaluator's multi-tier (Tier 1/2/3) structure wholesale -- the
  native harness's actor/verifier/judge shape is being kept; only its
  ergonomics and vocabulary are changing.

## Evidence of value

- The 277 lines of measured, near-duplicate verifier boilerplate across the
  three existing fixtures collapse to a handful of import lines plus whatever
  is genuinely task-specific.
- "Fixture" -> "task" directly answers the stated complaint ("the word
  fixture says nothing") with a term independently confirmed, not invented,
  across three separate sources this session.
- A `--baseline` flag and `codev eval benchmark run` read correctly on first
  encounter to anyone who has used SkillEvaluator, Google Cloud's agent-eval
  tooling, or DeepMind's own public agent work -- the opposite of today's
  `snapshot`/`without-skill`, which mean nothing outside this codebase.

## Constraints

- **No backward compatibility required.** CoDev is Alpha; `fixture`,
  `eval run`, and `eval snapshot run` are removed, not aliased. Every
  existing committed fixture under `.codev/fixtures/*` (including
  `audit-google-python-style-demo`) is migrated -- moved and reformatted --
  to the new task layout as part of implementing this brief, in one pass,
  rather than supported in both shapes indefinitely.
- The on-disk directory for renamed tasks must not visually or path-collide
  with `.codev/task/` (development work-item state, singular, pre-existing).
  Exact layout is a design-phase decision, not a brief-phase one, precisely
  because of this collision risk -- flagged here so it is not missed later.
- Docker remains strictly opt-in; the deterministic-checks-without-network
  invariant (`docs/architecture.md`) is not weakened for the default path.
- Follows this project's own process: this brief precedes a design doc and,
  if the Docker sandbox addition is accepted, a short ADR recording it as a
  deliberate, scoped exception -- the same pattern already used for
  [`../../adr/0026-external-evaluation-engines-are-thin-subprocess-wrappers.md`](../../adr/0026-external-evaluation-engines-are-thin-subprocess-wrappers.md).
