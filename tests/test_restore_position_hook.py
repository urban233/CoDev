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
"""Tests for the Claude Code `SessionStart` recovery hook.

Exercises the bundled .claude/hooks/restore_position.py directly, as an
independent subprocess given fixture stdin -- the same pattern as
tests/test_claude_hook.py. Helpers are duplicated rather than imported from
it: each Bazel test target only declares its own file as `srcs`, so a
cross-test-module import that works when run directly with `python3` would
fail under `bazel test`'s sandbox.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

_HOOK = (
    Path(__file__).resolve().parent.parent
    / "src/codev_workflow/bundle/.claude/hooks/restore_position.py"
)


def _path_without_codev() -> str:
    name = "codev.exe" if os.name == "nt" else "codev"
    kept = [
        entry
        for entry in os.environ.get("PATH", "").split(os.pathsep)
        if entry and not (Path(entry) / name).exists()
    ]
    return os.pathsep.join(kept)


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "README.md").write_text("test\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


def _run(payload: dict[str, Any], *, env: dict[str, str] | None = None) -> Any:
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
        env=env if env is not None else dict(os.environ),
    )


class RestorePositionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name)
        _init_repo(self.repo)
        self.scratchpad = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temporary.cleanup()
        self.scratchpad.cleanup()

    def test_fails_open_on_malformed_stdin(self) -> None:
        result = subprocess.run(
            [sys.executable, str(_HOOK)],
            input="not json",
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout.strip())

    def test_reports_the_position_as_a_system_message_at_startup(self) -> None:
        result = _run(
            {
                "cwd": str(self.repo),
                "source": "startup",
                "scratchpad_dir": self.scratchpad.name,
            }
        )
        self.assertEqual(0, result.returncode)
        payload = json.loads(result.stdout)
        output = payload["hookSpecificOutput"]
        self.assertEqual("SessionStart", output["hookEventName"])
        self.assertIn("CoDev position:", output["systemMessage"])

    def test_fails_open_silently_when_codev_is_unreachable(self) -> None:
        env = dict(os.environ)
        env["PATH"] = _path_without_codev()
        env["CODEV_CLI"] = "/nonexistent/codev"
        result = _run(
            {
                "cwd": str(self.repo),
                "source": "startup",
                "scratchpad_dir": self.scratchpad.name,
            },
            env=env,
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout.strip())

    def test_falls_back_to_the_checkpoint_after_a_compaction(self) -> None:
        """The one case codev-unreachable should not go silent: right after
        a compaction, where the checkpoint `checkpoint_state.py` wrote is a
        second, independent path to the same information."""
        checkpoint = Path(self.scratchpad.name) / "checkpoint.json"
        checkpoint.write_text(
            json.dumps({"position": "outer phase, round 3"}), encoding="utf-8"
        )
        env = dict(os.environ)
        env["PATH"] = _path_without_codev()
        env["CODEV_CLI"] = "/nonexistent/codev"
        result = _run(
            {
                "cwd": str(self.repo),
                "source": "compact",
                "scratchpad_dir": self.scratchpad.name,
            },
            env=env,
        )
        self.assertEqual(0, result.returncode)
        payload = json.loads(result.stdout)
        self.assertIn(
            "outer phase, round 3",
            payload["hookSpecificOutput"]["systemMessage"],
        )

    def test_does_not_use_the_checkpoint_outside_a_compaction(self) -> None:
        """A stale checkpoint from a previous compaction must not leak into
        an ordinary fresh startup that happens to share a scratchpad."""
        checkpoint = Path(self.scratchpad.name) / "checkpoint.json"
        checkpoint.write_text(
            json.dumps({"position": "stale checkpoint position"}), encoding="utf-8"
        )
        env = dict(os.environ)
        env["PATH"] = _path_without_codev()
        env["CODEV_CLI"] = "/nonexistent/codev"
        result = _run(
            {
                "cwd": str(self.repo),
                "source": "startup",
                "scratchpad_dir": self.scratchpad.name,
            },
            env=env,
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
