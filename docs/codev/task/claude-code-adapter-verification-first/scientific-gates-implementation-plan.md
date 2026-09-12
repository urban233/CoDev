# Slice 4: Scientific Gates - Implementation Plan

**Status:** Draft
**Owner:** urban233
**Reviewer:** independent reviewer, to be named before the pull request is marked ready
**Risk:** normal. Both checks are additive, read-only static analysis inside
an existing Stop hook that already fails open on every infrastructure error;
the risk that matters here is false positives (blocking a turn for code that
is actually fine), not a safety-property regression like slice 3's.
**Containment:** both checks are pure functions over already-changed files
plus one in-process stdlib call (`importlib.metadata.packages_distributions`)
-- no new subprocess, no new hook registration, no new settings.json entry.
Rollback is reverting the two functions and their call sites out of
`require_green.py`; nothing else in the repository depends on them.
**Work style:** `delegate` (recorded, per the parent plan's own designation
-- mechanical and fully specified below, unlike slices 1/3/5's `pair`)
**Slices:** 5, per the parent plan
**Slice:** `scientific-gates` (5th and final slice of this task)
**Base commit:** `07549c5` (head of the merged `recovery-and-budget` branch;
this slice's branch is stacked on it per ADR-0035, not on `main`'s later
merge commit)
**Issue/work item:** [urban233/CoDev#47](https://github.com/urban233/CoDev/issues/47)
**Brief/design/API:** [docs/plans/claude-code-adapter-verification-first.md](../../../plans/claude-code-adapter-verification-first.md), Accepted 2026-09-08 -- D5; see also the 2026-09-11 "Reordering" and 2026-09-12 "Instruction budget" notes in that same document

## Focus card

- **Change:** add two static checks to the existing `require_green.py` Stop
  hook (built in slice 3, already shipped): an unseeded-RNG check and a
  dependency-gap check, both scoped to files a turn actually changed.
- **Success:** a turn that adds an unseeded `random`/`numpy.random` call to a
  non-test file is refused with the offending line named; a turn that adds an
  import no declared dependency provides is refused with the missing package
  named; neither check fires on a file the turn did not touch, on a seeded
  call, on a stdlib or first-party import, or inside a test file (RNG check
  only -- see Decision 3).
- **Non-goals:** framework-specific RNGs beyond `random`/`numpy.random`
  (`torch`, `tensorflow`, `jax` -- filed as follow-up, Decision 1);
  dependency declarations outside `pyproject.toml`/`requirements*.txt`
  (Pipenv, Poetry's own lock format, `setup.py`/`setup.cfg` -- Decision 5);
  data-flow or cross-file seeding (Decision 2); any change to
  `.claude/settings.json` (no new hook is registered -- both checks live
  inside the hook slice 3 already wired up).
- **Allowed scope:** `.claude/hooks/require_green.py` and its bundle mirror,
  one new test file under `tests/` (auto-discovered by `tests/BUILD.bazel`'s
  glob, no `BUILD.bazel` edit needed), `CHANGELOG.md`.
- **Validation:** new fixture-stdin subprocess tests for both checks (block
  and allow paths, the exclusions named in Decisions 3-4), full test suite,
  `verify_self_install.py`, manual confirmation against this repository's own
  tree (which has zero existing `random`/`numpy` usage, so a manual planted
  case is the only way to see either check fire here).
- **Stop if:** `importlib.metadata.packages_distributions()` turns out not to
  reliably reflect this repository's own dev environment (see Repository
  evidence) -- that would mean the dependency-gap check's core mechanism does
  not hold even on its own author's machine, which is a stop-and-revise
  condition, not something to route around.

## Repository evidence

- `.claude/hooks/require_green.py` already gates on `_changed_source()`
  (uncommitted `.py`/`.pyi` files, `require_green.py:152-173`) and already
  runs one static AST check before any subprocess -- `_toothless_tests`
  (`require_green.py:354-392`), which reads each changed file's current
  content plus `git show HEAD:<path>` for the pre-change version, entirely
  through git object storage, never the working tree of an unrelated file.
  Both new checks reuse this exact shape: same input (`_changed_source`'s
  list), same git-object-storage comparison technique, same place in
  `main()` (after the toothless-test check, before the expensive
  `_checks()`/subprocess loop, so both stay effectively free).
- `_hook_common.py` has nothing either check needs -- it is CLI-resolution
  and decision-logging plumbing for the gate/advisory hooks, and both new
  checks are pure static analysis with no `codev` invocation of their own.
- **Zero existing `random`/`numpy` usage anywhere in this repository's
  tracked source** (`grep -rn "^import random\|numpy" src/ tests/` --
  confirmed empty, 2026-09-12). CoDev's own tree cannot exercise a true
  positive without a deliberately planted test file; this is expected --
  CoDev itself is not a scientific-computing project, but the bundle these
  hooks ship in installs into repositories that are (the audience this
  entire task targets). The manual validation step below plants a case
  rather than relying on one already existing.
- **This repository declares exactly one runtime dependency**
  (`pyproject.toml`'s `[project.dependencies]`: `pre-commit>=4.6.1`) plus a
  `dev` extra (`build`, `mypy`, `ruff`, `twine`) and a Bazel-managed
  `requirements_lock.txt` (638 lines, `uv export` output, hash-pinned).
  `src/codev_workflow/*.py` imports nothing outside the standard library.
  This means the dependency-gap check's only chance to prove itself against
  a true positive in this repository is also a planted case.
- `sys.stdlib_module_names` (stdlib since 3.10, this project requires
  `>=3.11`) confirms `random` itself is standard library -- the RNG check is
  about non-determinism, not about a missing dependency, and the two checks
  share no logic beyond both reading `_changed_source()`.
- `importlib.metadata.packages_distributions()` (stdlib since 3.10) maps
  each importable top-level module name to the distribution package
  name(s) that provide it, based on what is actually installed in the
  interpreter that calls it. Confirmed available and non-empty in this
  repository's own `sys.executable` (2026-09-12) -- this is the mechanism
  that resolves an import name like `yaml` to a distribution name like
  `PyYAML`, without a hardcoded mapping table, and it runs in-process
  (no subprocess, unlike every check `_checks()` discovers).
- `[tool.setuptools.packages.find]` sets `where = ["src"]` -- this
  repository uses the "src layout." A flat-layout repository (a package
  directory beside its tests, `require_green.py`'s own test-runner comments
  call this "most scientific Python") is the other common shape. Both are
  handled identically by Decision 6 below.
- `tests/BUILD.bazel`'s `py_test` rule is generated by `glob(["test_*.py"], exclude = ["test_instruction_budget.py"])`
  -- a new `tests/test_scientific_gates_hook.py` needs no `BUILD.bazel` edit.
  `tests/test_require_green_hook.py` is the pattern to match: a real scratch
  git repository per test, the hook run as a subprocess against fixture
  stdin, asserting on the JSON `_block`/allow contract.

## Decisions, resolved

Both checks are static analysis with real design freedom in exactly how much
they try to prove; each choice below trades detection power for the false-
positive risk a Stop-hook block carries (E12: agents route around hooks that
block them for the wrong reasons). Accepting this plan accepts these six.

**1. RNG scope: `random` and `numpy.random`/`np.random` only.**
D5's own text names these two plus "framework RNGs" generically. `torch`,
`tensorflow`, and `jax` each have their own seeding call (`torch.manual_seed`,
`tf.random.set_seed`, `jax.random.PRNGKey`) and their own set of
randomness-producing entry points; adding all three to a `delegate`-style,
fully-specified slice roughly triples the surface this plan would need to
pin down precisely, for frameworks this repository cannot itself validate
against (no ML framework is a dependency here either). Filed as a follow-up
issue rather than smuggled in partially specified.

**2. Detection scope: newly-added lines only, not the whole file.**
A repository this bundle installs into may already contain unseeded RNG
calls unrelated to the current turn. Blocking a turn for pre-existing debt
the turn did not introduce is exactly the friction E12 documents -- an agent
whose Stop hook fires for a reason unrelated to its own edit is an agent
that starts looking for a way around the hook, not a more careful one. Both
checks therefore run `git diff -- <path>` (base commit vs. working tree, the
same git-object-storage technique `_toothless_tests` already uses) and scan
only lines the diff adds (`+` lines, excluding the `+++` file header) for
the RNG check's candidate patterns. This is a regex over each added line's
text, not full-file AST parsing: an added line is a text fragment, not
necessarily a standalone parseable statement (a call split across several
added lines, for instance), so AST parsing the fragment is not reliably
possible, while a line-based regex is. **Known, accepted false-negative
edge:** a call whose invocation token (`random.` / `np.random.`) is *not*
itself on an added line -- e.g. only an argument line changed -- is missed.
**Known, accepted false-positive edge:** the pattern text appearing inside a
comment or a string literal on an added line is flagged anyway. Both are the
same class of imprecision slice 3's pre-change-test check already accepts
and documents rather than papering over with a claim of exactness it cannot
back up with real data-flow analysis.

**3. "Seeded" is presence, not reachability, of a qualifying call --
anywhere in the file's current full content, not just added lines.**
A seed call earlier in a file legitimately covers RNG calls added later in
the same file; restricting the seed search to added lines only would flag
new RNG usage in a file that was already correctly seeded before this turn.
Qualifying seed calls: `random.seed(`, `numpy.random.seed(`,
`np.random.seed(`, and `numpy.random.default_rng(`/`np.random.default_rng(`
**only when given at least one argument** -- `default_rng()` with no
argument is itself OS-entropy-seeded and non-reproducible, so an empty call
does not count as seeding anything. This is presence-based, not order- or
reachability-checked (no confirmation the seed call actually executes before
the RNG call at runtime, and no following a `set_seed()`-style indirection
into another function) -- the same explicitly-weaker-than-execution
trade-off slice 3's own pre-change-test check makes and documents, for the
same reason: the rigorous version needs real execution, which is out of
scope for a Stop hook budget.

**4. Test files are excluded from the RNG check, not from the
dependency-gap check.** Identified the same way `_toothless_tests` already
does (`"test" not in path.name`) rather than a second definition of "test
file." Randomized and property-based tests are a legitimate, common pattern
or ADR-0038 (E9's own testing-craft evidence for the value of property-based
tests), and are not the reproducibility concern D5/E8 target -- that concern
is about scientific *results* (notebooks, analysis scripts), not test
suites. A missing dependency in a test file is just as much a broken,
unreproducible environment as one in library code, so the dependency-gap
check applies uniformly to every changed `.py`/`.pyi` file.

**5. Declared-dependency sources: `pyproject.toml`'s `[project.dependencies]`
plus every group under `[project.optional-dependencies]`, and any
`requirements*.txt` at the repository root.** These two cover this
repository's own declaration (PEP 621 plus a Bazel-generated lock file) and
are, together, the most common declaration surface across Python projects
generally -- this hook ships to every repository that installs this bundle,
not only this one. `Pipfile`, Poetry's `poetry.lock`, and `setup.py`/
`setup.cfg`'s `install_requires` are real formats this does not read; a
repository using only one of those and nothing this check recognizes would
see every third-party import flagged as an undeclared gap. Filed as a named
limitation (Known limitations below) and a follow-up, not silently assumed
away, because a `delegate` slice must not leave an unstated gap for the
builder to discover and improvise around.

**6. Import-name resolution via `importlib.metadata.packages_distributions()`,
called in-process under the same interpreter running the hook.** This is
what lets the check compare an *import* name (`yaml`) against a *declared
dependency* name (`PyYAML`) without a hand-maintained mapping table --
Python packaging already keeps this mapping, installed packages already
carry it in their metadata, and the stdlib already exposes it. It depends on
the repository's declared dependencies actually being installed in whatever
environment runs this hook, which holds for a working development checkout
(the same assumption `_checks()` already makes for `ruff`/`mypy`/`pytest`
via `_module()`) but not for a machine where dependencies are declared but
never installed -- named explicitly in "Stop if" above rather than assumed.
First-party imports (this repository's own code) are excluded by checking
whether the import's root name resolves to a directory or `<name>.py` file
directly under the repository root, or under `src/` if a `src/` directory
exists there -- covering both the flat layout and the "src layout" this
repository itself uses, per Repository evidence above. Stdlib modules are
excluded via `sys.stdlib_module_names`.

## Proposed change

1. **`_unseeded_rng_findings(repo_root, changed)` in `require_green.py`.**
   For each changed non-test `.py`/`.pyi` file: run
   `git diff -- <path>` against the base commit (same git-object-storage
   technique as `_toothless_tests`), collect added lines matching
   `random\.\w+\(` or `\b(numpy\.random|np\.random)\.\w+\(`; for each match,
   check whether the file's *current* full content contains a qualifying
   seed call per Decision 3. Return one finding per unseeded match, naming
   the file, line text, and which pattern matched.
2. **`_dependency_gap_findings(repo_root, changed)` in `require_green.py`.**
   For each changed `.py`/`.pyi` file (test files included, Decision 4):
   AST-parse the *current* content (reusing the same `ast` import
   `_test_functions` already uses) for top-level and nested `Import`/
   `ImportFrom` nodes with `level == 0` (absolute imports only -- a relative
   import cannot be a missing external dependency by definition); take each
   root module name (the first dotted component). Skip a root name in
   `sys.stdlib_module_names`, or resolving to a first-party path per
   Decision 6. For everything left, load the declared-dependency set once
   per hook invocation (`pyproject.toml` plus `requirements*.txt`, Decision
   5) and `importlib.metadata.packages_distributions()` once; flag a root
   name whose mapped distribution(s) do not intersect the declared set, or
   that maps to nothing at all. Return one finding per flagged import,
   naming the file and the import name.
3. **Wire both into `main()`**, immediately after the existing
   `_toothless_tests` block and before `_checks()`'s subprocess loop -- same
   "changed source" gate, same `_block()`/`_log()` contract, one combined
   message when both checks have findings rather than two separate blocks
   for the same turn.
4. **Tests** (`tests/test_scientific_gates_hook.py`, matching
   `test_require_green_hook.py`'s scratch-repo-plus-subprocess pattern):
   - RNG: an added unseeded `random.random()` call blocks; the same call
     with `random.seed(...)` present anywhere in the file allows; an added
     unseeded `np.random.rand()` call blocks; `np.random.default_rng()` with
     no argument still blocks (Decision 3); `np.random.default_rng(42)`
     allows; the identical unseeded call already present at the base commit
     (untouched by this diff) allows (Decision 2); the same call inside a
     `test_*.py` file allows (Decision 4).
   - Dependency gap: an import of a declared `[project.dependencies]`
     package allows; an import of a package present in
     `requirements*.txt` but not `pyproject.toml` allows; an import with no
     matching declared dependency and no installed distribution at all
     blocks; a stdlib import never flags; a first-party import (a module
     under the scratch repo's own `src/<pkg>` or flat-layout root) never
     flags.
   - Both checks confirmed to run only on files `_changed_source` reports,
     and to be skipped entirely on a turn that changed no source (the
     existing fast path, unchanged).

## Validation

- `just test` -> full suite green, including the new test file.
- `just lint`, `just typecheck`, `just fmt-check` -> clean.
- `bazel run //scripts:verify_self_install` -> clean (bundle mirror stays
  byte-identical to `.claude/hooks/require_green.py`).
- Manual, against this repository's own tree (which has no real positive
  case to observe passively, per Repository evidence): plant a scratch file
  with an unseeded `random.random()` call and confirm `Stop` refuses;
  add `random.seed(0)` to the same file and confirm it now allows; plant an
  import of a package genuinely absent from this repository's declared
  dependencies and confirm `Stop` refuses, naming it; remove the planted
  file before ending the session.
- Re-run `tests/test_instruction_budget.py` -> unaffected (no new hook
  registration, no new always-on prose; see Decision-adjacent scope note in
  Non-goals).

## Risks and rollout

- **False positives are the dominant risk**, not a safety-property gap like
  slice 3's -- E12's own evidence is that a hook blocking for the wrong
  reason teaches agents to route around hooks generally. Mitigation:
  Decisions 1-6 each narrow scope specifically to reduce false-positive
  surface (diff-added-lines only, test-file exclusion for RNG, stdlib/
  first-party exclusion for dependencies), each at the stated cost of a
  named, accepted false-negative.
- **The dependency-gap check's soundness depends on the hook's own
  interpreter having the repository's declared dependencies installed** --
  named as this plan's own "Stop if" condition, not discovered mid-build.
- **Both checks are pure functions with no new subprocess or settings.json
  entry** -- rollback is deleting the two functions and their two call
  sites in `require_green.py` (and the mirrored bundle copy), with nothing
  else in the repository depending on them.
- **Instruction budget: unaffected.** No new hook is registered (both
  checks live inside slice 3's existing `require_green.py`/`Stop` entry),
  and no new always-on prose is added, so this slice has nothing to ledger
  against the 33,100-byte figure the 2026-09-12 "Instruction budget" note in
  the parent plan names -- consistent with that note's own instruction not
  to re-litigate the ledger's running totals for this slice.

## Decisions needed

None. The six decisions the two checks' design freedom created are resolved
above; accepting this plan accepts those six. Two items are deliberately
deferred and need their own tasks, neither blocking this slice:

- framework-specific RNG detection (`torch`, `tensorflow`, `jax` --
  Decision 1); and
- dependency-declaration formats beyond `pyproject.toml`/`requirements*.txt`
  (`Pipfile`, Poetry's lock format, `setup.py`/`setup.cfg` -- Decision 5).

## Completion evidence

- [ ] Full suite green
- [ ] `verify_self_install.py` clean
- [ ] Both checks' block and allow paths covered by tests, including every
      exclusion named in Decisions 2-6
- [ ] Manual: a planted unseeded-RNG case refuses `Stop`, seeding it allows,
      a planted undeclared-dependency case refuses and names the package
- [ ] CHANGELOG entry
- [ ] `git diff` confirms no change outside the allowed scope
- [ ] This task's final slice: on merge, `codev task close` rather than
      `codev slice land`/`advance-slice`
