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
"""Task G: the gate decisions are CoDev's, not one adapter's."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from codev_workflow.gate import GATES, check


def _repo(target: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=target, check=True)


class GateDispatchTests(unittest.TestCase):
    def test_every_named_gate_is_callable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            _repo(target)
            for gate in GATES:
                with self.subTest(gate=gate):
                    decision = check(gate, {"cwd": str(target)}, target=target)
                    self.assertIn(decision.decision, ("allow", "ask"))
        self.assertEqual(("plan", "wave-shape", "small-change"), GATES)

    def test_an_unknown_gate_is_a_programming_error(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(ValueError),
        ):
            check("nope", {}, target=Path(directory))

    def test_an_unreadable_payload_allows_without_recording(self) -> None:
        """A non-decision must not reach the decision log, or status would
        count every unrelated tool call as a guardrail allow."""
        with tempfile.TemporaryDirectory() as directory:
            decision = check("plan", None, target=Path(directory))
        self.assertEqual("allow", decision.decision)
        self.assertFalse(decision.recorded)

    def test_an_unwatched_tool_allows_without_recording(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            _repo(target)
            decision = check(
                "plan", {"tool_name": "Read", "cwd": str(target)}, target=target
            )
        self.assertEqual("allow", decision.decision)
        self.assertFalse(decision.recorded)

    def test_a_gate_fails_open_on_an_internal_error(self) -> None:
        """A guardrail that errors must never block work."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            _repo(target)
            decision = check(
                "plan",
                {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": 12345},
                    "cwd": str(target),
                },
                target=target,
            )
        self.assertEqual("allow", decision.decision)

    def test_the_plan_gate_asks_on_a_feature_branch_with_no_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            _repo(target)
            (target / "seed.txt").write_text("x\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=target, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.email=t@e.com",
                    "-c",
                    "user.name=T",
                    "commit",
                    "-qm",
                    "seed",
                ],
                cwd=target,
                check=True,
            )
            subprocess.run(
                ["git", "checkout", "-q", "-b", "feature"], cwd=target, check=True
            )
            decision = check(
                "plan",
                {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "src/x.py"},
                    "cwd": str(target),
                },
                target=target,
            )
        self.assertTrue(decision.asks)
        self.assertTrue(decision.recorded)


if __name__ == "__main__":
    unittest.main()
