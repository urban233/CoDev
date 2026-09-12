# BSD 3-Clause License
#
# Copyright (c) 2026, Martin Urban, Hannah Kullik
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""Refuse to end a turn that changed source while the repository's own
checks fail, and flag a new test that could not have failed.

This is the deterministic half of CoDev's evidence story. Instructions
asking an agent to run the tests are advisory; a `Stop` hook is not, which
is why the prose those instructions occupied is retired in the same change
that adds this file.

Two things bound the cost. Most turns change no source at all and skip
every check. A turn that did change source pays for lint and type checking
unconditionally -- together about a second on this repository -- and for the
test suite, which is the only genuinely expensive check and the one the
guarantee is actually about.

Fails open on everything: unreachable tooling, a timeout, an unreadable
payload. A timeout is recorded as `unverified` rather than as a pass, so a
check that did not finish can never be mistaken for one that succeeded.
The host force-overrides a `Stop` hook after 8 consecutive blocks, so this
cannot deadlock a session.
"""

from __future__ import annotations

import ast
import difflib
import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path

_HOOK_NAME = "require_green.py"
_DECISIONS_LOG_RELATIVE = ".codev/hooks/decisions.jsonl"
_BLOCKS_STATE_RELATIVE = ".codev/hooks/require_green_blocks.json"
# A whole-invocation wall-clock budget, not a per-check one. The settings
# entry gives this hook 180s, while three independent 120s check timeouts
# could reach 360s -- the host would kill the process before any
# `unverified` record was written, so a check that never finished would look
# exactly like one that passed. 150s leaves headroom under the host's limit.
_TOTAL_BUDGET_SECONDS = 150
_GIT_TIMEOUT_SECONDS = 20
# How many times in a row this hook may refuse the same turn before standing
# down. The host force-overrides after 8; standing down earlier, loudly and
# on the record, beats being overridden silently.
_MAX_CONSECUTIVE_BLOCKS = 3
_SOURCE_SUFFIXES = frozenset({".py", ".pyi"})


def _log(repo_root: Path, decision: str, *, reason: str = "", check: str = "") -> None:
    """Appends one local, gitignored record. Never raises."""
    try:
        record = {
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "hook": _HOOK_NAME,
            "decision": decision,
            "reason": reason,
            "check": check,
        }
        path = repo_root / _DECISIONS_LOG_RELATIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    except Exception:  # noqa: BLE001 - logging must never affect the hook
        pass


def _consecutive_blocks(repo_root: Path) -> int:
    """How many times in a row this hook has refused, across invocations.

    Each `Stop` firing is a fresh process, so the count has to live on disk.
    A missing or unreadable file reads as zero, which errs toward checking
    rather than toward standing down.
    """
    try:
        raw = (repo_root / _BLOCKS_STATE_RELATIVE).read_text(encoding="utf-8")
        value = json.loads(raw).get("consecutive")
        return int(value) if isinstance(value, int) else 0
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return 0


def _set_blocks(repo_root: Path, value: int) -> None:
    """Persist the consecutive-refusal count. Never raises."""
    try:
        path = repo_root / _BLOCKS_STATE_RELATIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"consecutive": value}), encoding="utf-8")
    except OSError:
        pass


def _reset_blocks(repo_root: Path) -> None:
    _set_blocks(repo_root, 0)


def _allow() -> None:
    sys.exit(0)


def _block(reason: str) -> None:
    json.dump({"decision": "block", "reason": reason}, sys.stdout)
    sys.exit(0)


def _git(repo_root: Path, *args: str) -> str | None:
    """Stdout of one git call, or None if it could not be made."""
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.stdout if completed.returncode == 0 else None


def _changed_source(repo_root: Path) -> list[Path] | None:
    """Uncommitted source files, or None when git could not be consulted.

    Uncommitted rather than "changed this turn": the hook has no record of
    the turn, and leaving the tree with broken uncommitted source is the
    condition worth refusing anyway.
    """
    porcelain = _git(repo_root, "status", "--porcelain", "--untracked-files=all")
    if porcelain is None:
        return None
    changed: list[Path] = []
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        raw = line[3:].strip()
        # A rename reads "old -> new"; only the destination still exists.
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1]
        candidate = Path(raw)
        if candidate.suffix in _SOURCE_SUFFIXES:
            changed.append(candidate)
    return changed


def _just_argv(repo_root: Path) -> list[str] | None:
    """A repository-local `just` if there is one, else whatever is on PATH.

    The local copy is checked with the platform's executable suffixes as
    well as the bare name: `.tools/just` is the Unix spelling, and Windows
    needs `just.exe` or `just.bat` to be runnable at all.
    """
    for suffix in ("", ".exe", ".bat", ".cmd"):
        local = repo_root / ".tools" / f"just{suffix}"
        if local.exists():
            return [str(local)]
    found = shutil.which("just")
    return [found] if found else None


def _just_recipes(repo_root: Path) -> set[str]:
    """Recipe names declared in a `Justfile`, read rather than executed."""
    for name in ("Justfile", "justfile", ".justfile"):
        path = repo_root / name
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return set()
        recipes = set()
        for line in text.splitlines():
            if not line or line[0].isspace() or line.startswith("#"):
                continue
            head = line.split(":", 1)
            if len(head) != 2:
                continue
            token = head[0].split()[0] if head[0].split() else ""
            if token and all(c.isalnum() or c in "-_" for c in token):
                recipes.add(token)
        return recipes
    return set()


def _module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _check_env(repo_root: Path, needs_import_path: bool) -> dict[str, str]:
    """The environment one discovered check runs under.

    Only the test runners need adjusting, and only because importability is
    their whole job: a flat-layout repository -- a package directory beside
    its tests -- is importable through the current directory, and that entry
    is suppressed by `-P` *and* by an inherited `PYTHONSAFEPATH`, which some
    build systems set for their own test actions. Relying on the implicit
    entry means the hook works locally and fails wherever the environment
    happens to carry that variable, which is the worst of both. Naming the
    path explicitly removes the dependency on either.

    The analyzers are left alone: they keep `-P` precisely so a module
    planted in the repository cannot decide their verdict. So is a check the
    repository declared itself -- a `just test` recipe may front any build
    system at all, and rewriting its import path is both unnecessary and
    broader than the reason given here.
    """
    env = dict(os.environ)
    if not needs_import_path:
        return env
    env.pop("PYTHONSAFEPATH", None)
    existing = env.get("PYTHONPATH", "")
    root = str(repo_root)
    env["PYTHONPATH"] = f"{root}{os.pathsep}{existing}" if existing else root
    return env


def _checks(repo_root: Path) -> list[tuple[str, list[str], bool]]:
    """The repository's own checks, discovered rather than configured.

    `just` recipes win where they exist, because a repository that has them
    has already declared what its checks are. The direct fallbacks let this
    hook still do its job in a repository that does not use `just` at all --
    the alternative would be hard-coding one project's toolchain into a
    bundle that installs everywhere.
    """
    just = _just_argv(repo_root)
    recipes = _just_recipes(repo_root) if just else set()
    found: list[tuple[str, list[str], bool]] = []

    def add(name: str, recipe: str, fallback: list[str] | None) -> None:
        """Record one check, and whether it is the fallback rather than a
        recipe the repository declared for itself."""
        if just is not None and recipe in recipes:
            found.append((name, [*just, recipe], False))
        elif fallback is not None:
            found.append((name, fallback, True))

    add(
        "lint",
        "lint",
        [sys.executable, "-P", "-m", "ruff", "check", "."] if _module("ruff") else None,
    )
    add(
        "typecheck",
        "typecheck",
        [sys.executable, "-P", "-m", "mypy", "."] if _module("mypy") else None,
    )
    # No -P on the test runners, deliberately, unlike the analyzers above.
    # -P suppresses the cwd entry on sys.path, and a flat-layout repository
    # -- a package directory sitting beside its tests, which is most
    # scientific Python -- needs exactly that entry to import the code under
    # test. With -P the runner cannot import it, so the hook would block on
    # a failure the agent has no way to fix and end up permanently
    # non-functional there. The analyzers need -P because a planted module
    # really does subvert their verdict; a test runner already executes the
    # repository's own code by definition, so shadowing `unittest` buys an
    # attacker nothing they do not already have.
    if _module("pytest"):
        test_fallback = [sys.executable, "-m", "pytest", "-q"]
    elif (repo_root / "tests").is_dir():
        # -t . makes the repository root the top-level directory, which is
        # what lets `import mypkg` resolve for a package sitting beside its
        # tests. Without it discovery roots itself at `tests`.
        test_fallback = [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-t",
            ".",
        ]
    else:
        test_fallback = None
    add("test", "test", test_fallback)
    return found


def _test_functions(source: str, path: Path) -> dict[str, tuple[str, list[str]]] | None:
    """Every `test_*` function, as (normalised body, sorted assertions).

    The body is carried alongside the assertions so an untouched function
    can be told apart from a touched one. Without that distinction, editing
    any part of a test file flags every other test in it -- every one of
    them does have the same assertions as HEAD, because nobody changed
    them.

    Returns None when the file does not parse, which is not a finding: a
    syntax error is the lint check's business, not this one's.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    out: dict[str, tuple[str, list[str]]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not node.name.startswith("test_"):
            continue
        lines: list[str] = []
        for inner in ast.walk(node):
            if isinstance(inner, ast.Assert):
                lines.append(ast.dump(inner.test))
            elif isinstance(inner, ast.Call):
                target = inner.func
                name = getattr(target, "attr", None) or getattr(target, "id", None)
                if isinstance(name, str) and (
                    name.startswith("assert") or name in {"fail", "raises"}
                ):
                    lines.append(ast.dump(inner))
        try:
            body = ast.unparse(node)
        except (AttributeError, ValueError):
            body = ""
        out[f"{path}::{node.name}"] = (body, sorted(lines))
    return out


def _toothless_tests(repo_root: Path, changed: list[Path]) -> list[str]:
    """Test functions that could not have failed against the pre-change code.

    Compares each changed test file against `HEAD` through git object
    storage -- never a checkout, a stash, or a worktree, so the developer's
    actual tree is untouched. This catches a test that asserts nothing and
    one whose assertions did not really change; it does not catch a test
    whose assertions changed and still pass against the old code. That
    stronger check needs to execute the old code, and is deliberately not
    in this slice.
    """
    findings: list[str] = []
    for path in changed:
        if "test" not in path.name:
            continue
        absolute = repo_root / path
        if not absolute.exists():
            continue
        try:
            current = _test_functions(absolute.read_text(encoding="utf-8"), path)
        except OSError:
            continue
        if current is None:
            continue
        previous_source = _git(repo_root, "show", f"HEAD:{path.as_posix()}")
        previous = _test_functions(previous_source, path) if previous_source else {}
        if previous is None:
            previous = {}
        for key, (body, lines) in current.items():
            before = previous.get(key)
            if before is not None and before[0] == body:
                # Untouched by this change. Adding a test to a file must not
                # put every pre-existing test in it on trial.
                continue
            if not lines:
                findings.append(f"{key} asserts nothing")
            elif before is not None and before[1] == lines:
                findings.append(f"{key} has the same assertions as HEAD")
    return findings


_RNG_CALL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Checked before the plain "random" pattern below: "np.random.rand(" and
    # "numpy.random.rand(" both contain "random.rand(" as a substring, so
    # checking the numpy-specific pattern first is what keeps a numpy call
    # labelled correctly instead of as a bare "random" one.
    ("numpy.random", re.compile(r"\b(?:numpy\.random|np\.random)\.\w+\(")),
    ("random", re.compile(r"random\.\w+\(")),
)
# "numpy.random.seed(" and "np.random.seed(" both contain this as a
# substring, so one check covers all three names Decision 3 lists.
_SEED_SUBSTRING = "random.seed("
_DEFAULT_RNG_PATTERN = re.compile(
    r"(?:numpy\.random|np\.random)\.default_rng\(([^)]*)\)"
)


def _added_lines(repo_root: Path, path: Path, current: str) -> list[str]:
    """Lines `current` has that the base commit's version did not.

    Reads the pre-change version through git object storage
    (`git show HEAD:<path>`), exactly like `_toothless_tests` reads its
    "previous" version, rather than shelling out to `git diff`: a file
    `_changed_source` reports that was never `git add`ed has no index entry
    at all, so a literal `git diff` invocation shows no differences for it
    and would silently miss every line of a brand-new script -- the single
    most common case this check exists for (Decision 2).
    """
    previous_source = _git(repo_root, "show", f"HEAD:{path.as_posix()}")
    previous_lines = previous_source.splitlines() if previous_source else []
    current_lines = current.splitlines()
    matcher = difflib.SequenceMatcher(a=previous_lines, b=current_lines, autojunk=False)
    added: list[str] = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("insert", "replace"):
            added.extend(current_lines[j1:j2])
    return added


def _file_is_seeded(content: str) -> bool:
    """Whether `content` already contains a qualifying seed call (Decision 3).

    Presence anywhere in the file's current content, not order- or
    reachability-checked -- confirming the seed call actually executes
    before the RNG call needs real execution, out of scope for a Stop hook.
    A bare `default_rng()` does not count: it is itself OS-entropy-seeded
    and non-reproducible, so only a call given at least one argument
    qualifies.
    """
    if _SEED_SUBSTRING in content:
        return True
    return any(
        match.group(1).strip() for match in _DEFAULT_RNG_PATTERN.finditer(content)
    )


def _unseeded_rng_findings(repo_root: Path, changed: list[Path]) -> list[str]:
    """Unreproducible randomness this turn's diff adds (Decisions 1-4).

    Scoped to lines a turn actually added, in non-test files: a call
    already present at the base commit is pre-existing debt this turn did
    not introduce (Decision 2), and a call inside a test file is a
    legitimate randomised- or property-based test, not the reproducibility
    concern this check targets (Decision 4).
    """
    findings: list[str] = []
    for path in changed:
        if "test" in path.name:
            continue
        absolute = repo_root / path
        if not absolute.exists():
            continue
        try:
            current = absolute.read_text(encoding="utf-8")
        except OSError:
            continue
        if _file_is_seeded(current):
            continue
        for line in _added_lines(repo_root, path, current):
            for label, pattern in _RNG_CALL_PATTERNS:
                if pattern.search(line):
                    findings.append(
                        f"{path.as_posix()}: {line.strip()!r} uses {label} "
                        "with no seed call in this file"
                    )
                    break
    return findings


_REQUIREMENT_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _normalize_distribution_name(name: str) -> str:
    """PEP 503 normalisation, so `PyYAML`, `pyyaml`, and `py_yaml` compare
    equal between a declared dependency and an installed distribution."""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def _requirement_name(entry: str) -> str | None:
    """The bare distribution name from one requirement line, or None.

    Handles a PEP 621 dependency string (`"pyyaml>=6.0"`), a
    `requirements.txt` line, one of its `--hash=...` continuation lines, an
    option line (`-r other.txt`), and a comment -- stopping at the first
    character a bare distribution name cannot contain.
    """
    line = entry.split("#", 1)[0].strip()
    if not line or line.startswith("-"):
        return None
    match = _REQUIREMENT_NAME_PATTERN.match(line)
    if not match:
        return None
    return _normalize_distribution_name(match.group(0))


def _declared_dependencies(repo_root: Path) -> set[str]:
    """Every distribution name this repository declares (Decision 5).

    `pyproject.toml`'s `[project.dependencies]` plus every group under
    `[project.optional-dependencies]`, and any `requirements*.txt` at the
    repository root -- together the most common declaration surface across
    Python projects generally, and the one this repository itself uses.
    """
    declared: set[str] = set()
    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data: object = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            data = {}
        project = data.get("project", {}) if isinstance(data, dict) else {}
        if isinstance(project, dict):
            for entry in project.get("dependencies") or []:
                name = _requirement_name(str(entry))
                if name:
                    declared.add(name)
            optional = project.get("optional-dependencies") or {}
            if isinstance(optional, dict):
                for group in optional.values():
                    for entry in group or []:
                        name = _requirement_name(str(entry))
                        if name:
                            declared.add(name)
    for requirements_file in sorted(repo_root.glob("requirements*.txt")):
        try:
            lines = requirements_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            name = _requirement_name(line)
            if name:
                declared.add(name)
    return declared


def _is_first_party(repo_root: Path, root_name: str, importer_dir: Path) -> bool:
    """Whether `root_name` is this repository's own code (Decision 6).

    Checked under the repository root, under `src/` if present, and beside
    the file doing the importing -- covering a flat-layout repository (a
    package directory beside its tests), the "src layout" this repository
    itself uses, and a module imported from its own sibling directory (e.g.
    this repository's own `require_plan.py` importing `_hook_common`, which
    lives right beside it rather than at the repository root or under
    `src/`).
    """
    bases = [repo_root, importer_dir]
    src_dir = repo_root / "src"
    if src_dir.is_dir():
        bases.append(src_dir)
    return any(
        (base / root_name).is_dir() or (base / f"{root_name}.py").is_file()
        for base in bases
    )


def _imported_root_names(source: str) -> set[str]:
    """Absolute top-level import names an already-parsed file uses.

    `level == 0` excludes a relative import (`from . import x`), which
    cannot be a missing external dependency by definition. Returns an empty
    set for a file that does not parse -- a syntax error is the lint
    check's finding, not this one's.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def _dependency_gap_findings(repo_root: Path, changed: list[Path]) -> list[str]:
    """Imports no declared dependency provides (Decisions 5-6).

    Applies to every changed file, test files included (Decision 4): a
    missing dependency breaks a test environment exactly as much as it
    breaks library code. `packages_distributions()` and the declared set
    are each computed at most once per hook invocation, only once at least
    one changed file has a candidate import left to check.
    """
    per_file: list[tuple[Path, set[str]]] = []
    for path in changed:
        absolute = repo_root / path
        if not absolute.exists():
            continue
        try:
            source = absolute.read_text(encoding="utf-8")
        except OSError:
            continue
        candidates = {
            root
            for root in _imported_root_names(source)
            if root not in sys.stdlib_module_names
            and not _is_first_party(repo_root, root, absolute.parent)
        }
        if candidates:
            per_file.append((path, candidates))
    if not per_file:
        return []

    declared = _declared_dependencies(repo_root)
    mapping = importlib.metadata.packages_distributions()
    findings: list[str] = []
    for path, roots in per_file:
        for root in sorted(roots):
            distributions = {
                _normalize_distribution_name(dist) for dist in mapping.get(root, [])
            }
            if not distributions or not (distributions & declared):
                findings.append(
                    f"{path.as_posix()}: import '{root}' has no declared "
                    "dependency providing it"
                )
    return findings


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        _allow()
        return
    if not isinstance(payload, dict):
        _allow()
        return
    repo_root = Path(payload.get("cwd") or Path.cwd())
    # `stop_hook_active` marks a turn this hook already stopped once. It is
    # deliberately NOT treated as a blanket allow: doing that made the whole
    # guarantee one-shot, so an agent whose checks still failed simply ended
    # the turn on its second attempt. Re-run them instead, and stand down
    # only after a bounded number of consecutive refusals.
    if (
        payload.get("stop_hook_active")
        and _consecutive_blocks(repo_root) >= _MAX_CONSECUTIVE_BLOCKS
    ):
        _log(
            repo_root,
            "unverified",
            reason=(
                f"stood down after {_MAX_CONSECUTIVE_BLOCKS} consecutive "
                "refusals; the checks were still failing when the turn ended"
            ),
        )
        _reset_blocks(repo_root)
        _allow()
        return
    changed = _changed_source(repo_root)
    if changed is None:
        _log(repo_root, "degraded", reason="git could not be consulted")
        _allow()
        return
    if not changed:
        _allow()
        return

    toothless = _toothless_tests(repo_root, changed)
    if toothless:
        _log(repo_root, "block", reason="; ".join(toothless), check="pre-change-test")
        _set_blocks(repo_root, _consecutive_blocks(repo_root) + 1)
        _block(
            "These tests would pass against the pre-change code, so they "
            "cannot be evidence the change works:\n  - "
            + "\n  - ".join(toothless)
            + "\nGive each one an assertion that fails without this change, "
            "or say explicitly why it is a non-behavioral test."
        )
        return

    scientific = [
        *_unseeded_rng_findings(repo_root, changed),
        *_dependency_gap_findings(repo_root, changed),
    ]
    if scientific:
        _log(repo_root, "block", reason="; ".join(scientific), check="scientific-gates")
        _set_blocks(repo_root, _consecutive_blocks(repo_root) + 1)
        _block(
            "This turn is not reproducible as written:\n  - "
            + "\n  - ".join(scientific)
            + "\nSeed every randomness-producing call this turn added (e.g. "
            "random.seed(...) or np.random.default_rng(<seed>)), and declare "
            "every third-party import this turn added in pyproject.toml or a "
            "requirements*.txt."
        )
        return

    checks = _checks(repo_root)
    if not checks:
        _log(repo_root, "degraded", reason="no checks reachable in this repository")
        _allow()
        return

    deadline = time.monotonic() + _TOTAL_BUDGET_SECONDS
    for name, argv, needs_import_path in checks:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _log(repo_root, "unverified", reason="budget exhausted", check=name)
            _allow()
            return
        try:
            completed = subprocess.run(
                argv,
                cwd=repo_root,
                env=_check_env(repo_root, needs_import_path),
                capture_output=True,
                text=True,
                timeout=remaining,
                check=False,
            )
        except subprocess.TimeoutExpired:
            _log(repo_root, "unverified", reason=f"{name} timed out", check=name)
            _allow()
            return
        except OSError:
            _log(repo_root, "degraded", reason=f"{name} could not be run", check=name)
            continue
        if completed.returncode != 0:
            detail = (completed.stdout + completed.stderr).strip()
            _log(repo_root, "block", reason=f"{name} failed", check=name)
            _set_blocks(repo_root, _consecutive_blocks(repo_root) + 1)
            _block(
                f"`{' '.join(argv)}` failed, so this turn's work is not "
                f"verified:\n\n{detail[-2000:]}"
            )
            return
        _log(repo_root, "pass", check=name)
    _reset_blocks(repo_root)
    _allow()


if __name__ == "__main__":
    main()
