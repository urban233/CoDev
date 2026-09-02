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
"""Support for the integration tier: a real repository, a real remote, and
a `gh` stubbed at the process boundary.

The unit suites mock `git_ops._run_gh` with `patch.object`, which verifies
that the right Python function was called with the right arguments. It
cannot catch a defect in how the surrounding git commands interact -- and
two real ones reached `main` that way: a restack cascade that died partway
on a dirty worktree, and one that could not read its own branch records
because `git-state.json` is committed, so an earlier slice's branch predates
the later slices.

Both were found in minutes against a real repository. This module exists so
that finding them does not depend on someone thinking to try it by hand.

The `gh` stub is an executable on PATH, not a patched attribute, so the code
under test takes exactly the path it takes in production: build an argv, run
a subprocess, parse what comes back. It is installed as both `gh` and
`gh.cmd` so PATH lookup finds it on POSIX and on Windows.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_STUB = """import json, sys
from pathlib import Path

state_path = Path(__file__).with_name("gh-state.json")
state = json.loads(state_path.read_text("utf-8")) if state_path.exists() else {}
prs = state.setdefault("prs", {})
args = sys.argv[1:]

def fail(message):
    sys.stderr.write(message + "\\n")
    raise SystemExit(1)

if args[:2] == ["pr", "view"]:
    branch = args[2]
    record = prs.get(branch)
    if record is None:
        fail("no pull requests found for branch " + branch)
    if "url" in args:
        print(record["url"])
    elif "state" in args:
        print(record["state"])
    elif "reviews" in args:
        print(json.dumps(record.get("reviews", [])))
    else:
        print(json.dumps(record))
elif args[:2] == ["pr", "create"]:
    head = args[args.index("--head") + 1] if "--head" in args else "unknown"
    base = args[args.index("--base") + 1] if "--base" in args else "main"
    number = state.setdefault("next_number", 1)
    state["next_number"] = number + 1
    body = args[args.index("--body") + 1] if "--body" in args else ""
    prs[head] = {
        "url": "https://github.com/o/r/pull/%d" % number,
        "state": "OPEN",
        "base": base,
        "body": body,
        "draft": "--draft" in args,
        "reviews": [],
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")
    print(prs[head]["url"])
elif args[:2] == ["pr", "edit"]:
    branch = args[2]
    record = prs.setdefault(branch, {"url": "", "state": "OPEN", "reviews": []})
    if "--body" in args:
        record["body"] = args[args.index("--body") + 1]
    if "--add-reviewer" in args:
        record["reviewer"] = args[args.index("--add-reviewer") + 1]
    state_path.write_text(json.dumps(state), encoding="utf-8")
elif args[:2] == ["pr", "ready"]:
    prs.setdefault(args[2], {})["draft"] = False
    state_path.write_text(json.dumps(state), encoding="utf-8")
elif args[:2] == ["repo", "view"]:
    if "defaultBranchRef" in " ".join(args):
        print("main")
    elif "nameWithOwner" in " ".join(args):
        print("o/r")
    else:
        print(json.dumps({
            "nameWithOwner": "o/r",
            "defaultBranchRef": {"name": "main"},
        }))
elif args[:2] == ["issue", "view"]:
    print(json.dumps({"title": "t", "body": "b", "url": "https://github.com/o/r/issues/1"}))
else:
    fail("gh stub does not implement: " + " ".join(args))
"""


class GhStub:
    """A `gh` on PATH whose pull requests live in a JSON file the test can
    read and write."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        (directory / "gh_stub.py").write_text(_STUB, encoding="utf-8")
        launcher = directory / "gh"
        launcher.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{directory / "gh_stub.py"}" "$@"\n',
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        # Windows resolves `gh` through PATHEXT, which does not include an
        # extensionless shell script.
        (directory / "gh.cmd").write_text(
            f'@echo off\r\n"{sys.executable}" "{directory / "gh_stub.py"}" %*\r\n',
            encoding="utf-8",
        )

    @property
    def executable(self) -> Path:
        """The launcher to point `CODEV_GH_PATH` at.

        On Windows `shutil.which("gh")` can resolve the extensionless shell
        script rather than the `.cmd`, and Windows cannot execute the former
        -- so every `gh` call fails and the code under test silently takes
        its fail-open paths, which is the opposite of what this tier is for.
        `CODEV_GH_PATH` is git_ops's own documented override and removes the
        ambiguity on every platform.
        """
        return self.directory / ("gh.cmd" if os.name == "nt" else "gh")

    @property
    def state_path(self) -> Path:
        return self.directory / "gh-state.json"

    def read(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        loaded: dict[str, Any] = json.loads(self.state_path.read_text("utf-8"))
        return loaded

    def write(self, state: dict[str, Any]) -> None:
        self.state_path.write_text(json.dumps(state), encoding="utf-8")

    def set_pr_state(self, branch: str, value: str) -> None:
        state = self.read()
        state.setdefault("prs", {}).setdefault(branch, {"reviews": []})["state"] = value
        self.write(state)

    def approve(self, branch: str, login: str) -> None:
        state = self.read()
        record = state.setdefault("prs", {}).setdefault(branch, {"state": "OPEN"})
        record.setdefault("reviews", []).append(
            {"state": "APPROVED", "author": {"login": login}}
        )
        self.write(state)


def run_git(args: list[str], *, cwd: Path) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return completed.stdout.strip()


class Sandbox:
    """A work repository with a real bare origin, and `gh` on PATH."""

    def __init__(self) -> None:
        # ignore_cleanup_errors, because teardown removing a directory git is
        # still writing into is not a test result. A push into the bare origin
        # can leave git working in `origin/objects` after the push returns; on
        # a loaded runner that outlived cleanup and raised
        # "OSError: [Errno 39] Directory not empty", failing a test whose
        # assertions had all passed. A leaked temporary directory is harmless;
        # a red build that says nothing about the code is not.
        self._temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._temporary.name)
        self.origin = root / "origin"
        self.work = root / "work"
        self.origin.mkdir()
        self.work.mkdir()
        run_git(["init", "-q", "--bare"], cwd=self.origin)
        # And remove the cause as well as tolerating it: with auto-gc off,
        # nothing is repacking in the background for cleanup to race.
        run_git(["config", "gc.auto", "0"], cwd=self.origin)
        run_git(["init", "-q", "-b", "main"], cwd=self.work)
        run_git(["config", "gc.auto", "0"], cwd=self.work)
        run_git(["config", "user.email", "t@example.com"], cwd=self.work)
        run_git(["config", "user.name", "Test"], cwd=self.work)
        run_git(["remote", "add", "origin", str(self.origin)], cwd=self.work)
        (self.work / "seed.txt").write_text("seed\n", encoding="utf-8")
        run_git(["add", "-A"], cwd=self.work)
        run_git(["commit", "-qm", "seed"], cwd=self.work)
        run_git(["push", "-q", "-u", "origin", "main"], cwd=self.work)
        self.base = run_git(["rev-parse", "HEAD"], cwd=self.work)

        bin_dir = root / "bin"
        bin_dir.mkdir()
        self.gh = GhStub(bin_dir)
        self._previous_path = os.environ.get("PATH", "")
        self._previous_gh = os.environ.get("CODEV_GH_PATH")
        os.environ["PATH"] = str(bin_dir) + os.pathsep + self._previous_path
        os.environ["CODEV_GH_PATH"] = str(self.gh.executable)

    def head(self) -> str:
        return run_git(["rev-parse", "HEAD"], cwd=self.work)

    def branches(self) -> list[str]:
        listed = run_git(["branch", "--format=%(refname:short)"], cwd=self.work)
        return sorted(line for line in listed.splitlines() if line)

    def write(self, relative: str, content: str) -> None:
        path = self.work / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def file_on(self, branch: str, relative: str) -> str:
        return run_git(["show", f"{branch}:{relative}"], cwd=self.work)

    def close(self) -> None:
        os.environ["PATH"] = self._previous_path
        if self._previous_gh is None:
            os.environ.pop("CODEV_GH_PATH", None)
        else:
            os.environ["CODEV_GH_PATH"] = self._previous_gh
        self._temporary.cleanup()
