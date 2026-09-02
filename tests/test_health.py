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
"""Degradation must be legible: "checked and fine" and "could not check"
are different answers, and only one of them is reassuring."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from codev_workflow import gate, health


def _repo(target: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=target, check=True)


class GateDegradationTests(unittest.TestCase):
    def test_an_internal_error_is_degraded_not_an_allow(self) -> None:
        """It still allows -- a guardrail that errors must not block work --
        but the record must not claim the gate passed."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            _repo(target)

            def boom(payload: object, repo_root: object) -> object:
                raise RuntimeError("boom")

            # _GATES captures the functions at import, so the dispatch table
            # is what a test has to replace.
            with patch.dict(gate._GATES, {"plan": boom}):
                decision = gate.check(
                    "plan",
                    {"tool_name": "Edit", "tool_input": {"file_path": "x.py"}},
                    target=target,
                )
        self.assertEqual("degraded", decision.decision)
        self.assertTrue(decision.allows)
        self.assertFalse(decision.asks)
        self.assertTrue(decision.recorded, "a degraded gate must reach the log")

    def test_an_unmeasurable_slice_is_degraded_not_within_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            _repo(target)
            with patch.object(gate, "_slice_size", return_value=None):
                decision = gate.check(
                    "small-change",
                    {
                        "tool_name": "Bash",
                        "tool_input": {"command": "codev git open-pr --id x"},
                    },
                    target=target,
                )
        self.assertEqual("degraded", decision.decision)
        self.assertIn("could not be measured", decision.reason)

    def test_a_gate_that_does_not_apply_stays_unrecorded(self) -> None:
        """An unwatched tool is not a guardrail decision at all, and must not
        inflate the log either way."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            _repo(target)
            decision = gate.check("plan", {"tool_name": "Read"}, target=target)
        self.assertEqual("allow", decision.decision)
        self.assertFalse(decision.recorded)


class HealthTests(unittest.TestCase):
    def test_a_missing_codev_disables_every_guardrail_and_says_so(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("codev_workflow.health.shutil.which", return_value=None),
        ):
            finding = health._codev_usable(Path(directory))
        self.assertFalse(finding.ok)
        self.assertIn("every guardrail hook fails open", finding.impact)

    def test_a_codev_that_cannot_run_gate_check_is_not_healthy(self) -> None:
        """A binary being present is not the question. An older release on
        PATH shadows a checkout and answers `gate check` with an unknown
        command, and every guardrail fails open exactly as if nothing were
        installed."""
        completed = subprocess.CompletedProcess(
            args=[], returncode=2, stdout="", stderr="invalid choice: 'gate'"
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("codev_workflow.health.shutil.which", return_value="/x/codev"),
            patch("codev_workflow.health.subprocess.run", return_value=completed),
        ):
            finding = health._codev_usable(Path(directory))
        self.assertFalse(finding.ok)
        self.assertIn("cannot run `gate check`", finding.detail)
        self.assertIn("older release", finding.impact)

    def test_the_probe_does_not_inherit_pythonpath(self) -> None:
        """With a developer's PYTHONPATH set, the installed console script
        imports their checkout and looks healthier than it is."""
        seen: dict[str, str] = {}

        def fake_run(*args: Any, **kwargs: Any) -> object:
            seen.update(kwargs["env"])
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )

        with (
            tempfile.TemporaryDirectory() as directory,
            patch("codev_workflow.health.shutil.which", return_value="/x/codev"),
            patch("codev_workflow.health.subprocess.run", fake_run),
            patch.dict(os.environ, {"PYTHONPATH": "/somewhere/src"}),
        ):
            health._codev_usable(Path(directory))
        self.assertNotIn("PYTHONPATH", seen)

    def test_a_configured_hook_script_that_is_absent_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            settings = target / ".claude"
            settings.mkdir()
            (settings / "settings.json").write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [{"hooks": [{"command": "python3 gone.py"}]}]
                        }
                    }
                ),
                encoding="utf-8",
            )
            finding = health._hooks_wired(target)
        self.assertFalse(finding.ok)
        self.assertIn("gone.py", finding.detail)

    def test_degraded_gate_calls_are_counted_separately(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            log = target / ".codev" / "hooks"
            log.mkdir(parents=True)
            (log / "decisions.jsonl").write_text(
                json.dumps({"decision": "allow", "hook": "a.py"})
                + "\n"
                + json.dumps({"decision": "degraded", "hook": "b.py"})
                + "\n",
                encoding="utf-8",
            )
            finding = health._gates_failing_open(target)
        self.assertFalse(finding.ok)
        self.assertIn("1 gate call(s) failed open", finding.detail)
        self.assertIn("b.py", finding.detail)


if __name__ == "__main__":
    unittest.main()
