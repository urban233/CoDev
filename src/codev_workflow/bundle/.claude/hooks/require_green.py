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
import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_HOOK_NAME = "require_green.py"
_DECISIONS_LOG_RELATIVE = ".codev/hooks/decisions.jsonl"
_CHECK_TIMEOUT_SECONDS = 120
_GIT_TIMEOUT_SECONDS = 20
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


def _checks(repo_root: Path) -> list[tuple[str, list[str]]]:
    """The repository's own checks, discovered rather than configured.

    `just` recipes win where they exist, because a repository that has them
    has already declared what its checks are. The direct fallbacks let this
    hook still do its job in a repository that does not use `just` at all --
    the alternative would be hard-coding one project's toolchain into a
    bundle that installs everywhere.
    """
    just = _just_argv(repo_root)
    recipes = _just_recipes(repo_root) if just else set()
    found: list[tuple[str, list[str]]] = []

    def add(name: str, recipe: str, fallback: list[str] | None) -> None:
        if just is not None and recipe in recipes:
            found.append((name, [*just, recipe]))
        elif fallback is not None:
            found.append((name, fallback))

    add(
        "lint",
        "lint",
        [sys.executable, "-m", "ruff", "check", "."] if _module("ruff") else None,
    )
    add(
        "typecheck",
        "typecheck",
        [sys.executable, "-m", "mypy", "."] if _module("mypy") else None,
    )
    if _module("pytest"):
        test_fallback = [sys.executable, "-m", "pytest", "-q"]
    elif (repo_root / "tests").is_dir():
        test_fallback = [sys.executable, "-m", "unittest", "discover", "-s", "tests"]
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


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        _allow()
        return
    if not isinstance(payload, dict):
        _allow()
        return
    # A hook that blocked and is being re-entered must not block again on the
    # same grounds; the host sets this once it has already stopped for us.
    if payload.get("stop_hook_active"):
        _allow()
        return

    repo_root = Path(payload.get("cwd") or Path.cwd())
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
        _block(
            "These tests would pass against the pre-change code, so they "
            "cannot be evidence the change works:\n  - "
            + "\n  - ".join(toothless)
            + "\nGive each one an assertion that fails without this change, "
            "or say explicitly why it is a non-behavioral test."
        )
        return

    checks = _checks(repo_root)
    if not checks:
        _log(repo_root, "degraded", reason="no checks reachable in this repository")
        _allow()
        return

    for name, argv in checks:
        try:
            completed = subprocess.run(
                argv,
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=_CHECK_TIMEOUT_SECONDS,
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
            _block(
                f"`{' '.join(argv)}` failed, so this turn's work is not "
                f"verified:\n\n{detail[-2000:]}"
            )
            return
        _log(repo_root, "pass", check=name)
    _allow()


if __name__ == "__main__":
    main()
