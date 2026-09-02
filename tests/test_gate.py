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

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from codev_workflow.gate import GATES, check


def _repo(target: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=target, check=True)


class RiskTieredPlanGateTests(unittest.TestCase):
    """The plan gate stops asking about changes that are small and ordinary,
    and keeps asking about everything else."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.target = Path(self._temporary.name)
        _repo(self.target)
        self._git("commit", "-q", "--allow-empty", "-m", "seed")
        self._git("checkout", "-q", "-b", "codev/a-task")

    def _git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.target, check=True)

    def _open_round_state(self) -> None:
        """Enough round state for the gate to believe a task exists. The
        cases here never reach a measurement -- the ones that do live in the
        integration tier, against a real task."""
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.target,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        state = self.target / ".codev" / "task" / "a-task"
        state.mkdir(parents=True)
        (state / "round-state.json").write_text(
            json.dumps({"base_snapshot": head}), encoding="utf-8"
        )

    def _edit(self, file_path: str) -> str:
        return check(
            "plan",
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": file_path},
                "cwd": str(self.target),
            },
            target=self.target,
        ).decision

    def test_a_branch_named_like_a_task_but_tracking_none_still_asks(self) -> None:
        """`codev task size` answers with zeros for a task that does not
        exist. Treating that as "small" would let any branch called
        codev/anything skip the gate, which is a hole, not a tier.
        """
        self.assertEqual("ask", self._edit("src/foo.py"))

    def test_a_dependency_manifest_asks_however_small_the_change(self) -> None:
        """Size is the wrong question for a file where one line changes what
        the code computes."""
        self._open_round_state()
        for path in ("pyproject.toml", "uv.lock", "requirements-dev.txt"):
            with self.subTest(path=path):
                self.assertEqual("ask", self._edit(path))

    def test_ci_definitions_and_migrations_ask_too(self) -> None:
        self._open_round_state()
        self.assertEqual("ask", self._edit(".github/workflows/ci.yml"))
        self.assertEqual("ask", self._edit("app/migrations/0002_add.py"))

    def test_a_repository_mutating_command_is_never_tiered_by_size(self) -> None:
        """A git command is not made safe by the change being small."""
        self._open_round_state()
        decision = check(
            "plan",
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git push"},
                "cwd": str(self.target),
            },
            target=self.target,
        )
        self.assertEqual("ask", decision.decision)

    def test_an_accepted_plan_under_docs_plans_satisfies_the_gate(self) -> None:
        """The glob that did not cover where this repository keeps plans."""
        plans = self.target / "docs" / "plans"
        plans.mkdir(parents=True)
        (plans / "a-task.md").write_text("# a-task\n", encoding="utf-8")
        self.assertEqual("allow", self._edit("src/foo.py"))


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
