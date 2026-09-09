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

from codev_workflow import config, git_ops
from codev_workflow.gate import GATES, check


def _repo(target: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=target, check=True)
    # A CI runner has no global git identity, so a repository that intends to
    # commit must carry its own. Without this the commit fails with exit 128
    # and every test in the class errors in setUp -- invisible on a developer
    # machine, which has one configured.
    for key, value in (("user.email", "t@example.com"), ("user.name", "Test")):
        subprocess.run(["git", "config", key, value], cwd=target, check=True)


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

    def test_a_branch_codev_never_recorded_still_asks(self) -> None:
        """The third zero-measurement hole, found by the outer-loop review of
        the pull request that introduced this tier.

        `_measure` returns a size of zero when it cannot load
        `git-state.json`, which is indistinguishable from a genuinely small
        change. A branch merely *named* `codev/...`, given round state by hand
        without `codev git branch` ever recording it, therefore measured as
        zero and skipped the gate however large it grew -- reproduced with a
        500-line change scoring `within-budget-small-change`.
        """
        self._open_round_state()
        # Round state is valid and carries a real base; only the branch record
        # is missing, which is exactly the case that used to measure as zero.
        self.assertFalse((self.target / ".codev/task/a-task/git-state.json").exists())
        (self.target / "big.py").write_text(
            "\n".join(f"line_{n} = {n}" for n in range(500)), encoding="utf-8"
        )
        self._git("add", "-A")
        self._git("commit", "-qm", "500 lines")
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


class SlicePlanGateTests(unittest.TestCase):
    """The plan gate reads the branch's own slice, and reads acceptance.

    Both were silent failures: a slice branch resolved to a task that does not
    exist, so the precise check never matched past the first slice; and a plan
    file satisfied the gate whether or not anyone had accepted it, which is
    the one thing the gate exists to establish.
    """

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.target = Path(self._temporary.name)
        _repo(self.target)
        subprocess.run(
            ["git", "commit", "-q", "--allow-empty", "-m", "seed"],
            cwd=self.target,
            check=True,
        )

    def _on(self, branch: str) -> None:
        subprocess.run(
            ["git", "checkout", "-q", "-b", branch], cwd=self.target, check=True
        )

    def _plan(self, relative: str, status: str) -> None:
        path = self.target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# plan\n\n**Status:** {status}\n", encoding="utf-8")

    def _edit_decision(self) -> str:
        # A dependency manifest: always-planned, so the size tier cannot
        # allow it and the answer is the plan lookup alone.
        return check(
            "plan",
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "pyproject.toml"},
                "cwd": str(self.target),
            },
            target=self.target,
        ).decision

    def test_a_slice_branch_finds_its_own_accepted_plan(self) -> None:
        self._on("codev/auth--schema")
        self._plan("docs/codev/task/auth/schema-implementation-plan.md", "Accepted")
        self.assertEqual("allow", self._edit_decision())

    def test_a_slice_branch_is_not_satisfied_by_the_tasks_own_plan(self) -> None:
        """A task-level plan is the document the slice list came out of, not
        a plan for the slice being built (ADR-0035)."""
        self._on("codev/auth--schema")
        self._plan("docs/codev/task/auth/implementation-plan.md", "Accepted")
        self.assertEqual("ask", self._edit_decision())

    def test_a_drafted_plan_does_not_satisfy_the_gate(self) -> None:
        self._on("codev/auth")
        self._plan("docs/codev/task/auth/implementation-plan.md", "Draft")
        self.assertEqual("ask", self._edit_decision())

    def test_a_single_slice_task_keeps_the_filename_it_always_had(self) -> None:
        self._on("codev/auth")
        self._plan("docs/codev/task/auth/implementation-plan.md", "Accepted")
        self.assertEqual("allow", self._edit_decision())


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


class SubdirectoryCwdTests(unittest.TestCase):
    """A session's working directory is wherever the developer happens to be.

    The gates took it verbatim as the repository root, so every path
    comparison against it failed and the plan and wave-shape gates returned
    `degraded` -- which every hook shim allows. A repository whose gates all
    fail open looks exactly like one with no guardrails configured, so this
    is the case that must not regress.
    """

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.target = Path(self._temporary.name)
        _repo(self.target)
        self._git("commit", "-q", "--allow-empty", "-m", "seed")
        self._git("checkout", "-q", "-b", "codev/a-task")
        self.subdirectory = self.target / "src" / "nested"
        self.subdirectory.mkdir(parents=True)

    def _git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.target, check=True)

    def _edit_from(self, cwd: Path, gate: str = "plan") -> str:
        return check(
            gate,
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(self.target / "src" / "foo.py")},
                "cwd": str(cwd),
            },
            target=cwd,
        ).decision

    def _bash_from(self, cwd: Path) -> str:
        return check(
            "plan",
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m x"},
                "cwd": str(cwd),
            },
            target=cwd,
        ).decision

    def test_the_plan_gate_decides_an_edit_the_same_from_a_subdirectory(self) -> None:
        from_root = self._edit_from(self.target)
        self.assertNotEqual("degraded", from_root)
        self.assertEqual(from_root, self._edit_from(self.subdirectory))

    def test_the_wave_shape_gate_decides_an_edit_the_same_from_a_subdirectory(
        self,
    ) -> None:
        from_root = self._edit_from(self.target, gate="wave-shape")
        self.assertNotEqual("degraded", from_root)
        self.assertEqual(
            from_root, self._edit_from(self.subdirectory, gate="wave-shape")
        )

    def test_the_small_change_gate_decides_an_open_pr_the_same_from_a_subdirectory(
        self,
    ) -> None:
        """This gate never compares paths, but it does resolve the task's
        repository root to measure the slice's size -- the same unresolved
        `cwd` bug, one level removed. Pre-fix, an over-budget slice opened
        from a subdirectory was silently decided `allow "within-budget"`
        rather than `ask`: worse than the plan and wave-shape gates'
        `degraded`, because a `degraded` decision is at least visible as a
        gap, while a wrong `allow` looks like a working guardrail that
        happens to agree the change is fine.
        """
        base = git_ops.current_head(self.target)
        git_ops.create_branch("subdir-task", base, target=self.target)
        config.set_value("review.max_lines", "1", target=self.target)
        (self.target / "big.txt").write_text("a\nb\nc\n", encoding="utf-8")
        git_ops.commit("subdir-task", "big change", target=self.target)

        def _open_pr_from(cwd: Path) -> str:
            return check(
                "small-change",
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "codev git open-pr --id subdir-task --title x"
                    },
                    "cwd": str(cwd),
                },
                target=cwd,
            ).decision

        self.assertEqual("ask", _open_pr_from(self.target))
        self.assertEqual("ask", _open_pr_from(self.subdirectory))

    def test_a_repository_mutating_bash_command_is_still_gated(self) -> None:
        """Already correct before the root fix, because the Bash path never
        compares paths. Pinned so restoring the edit path cannot quietly
        break the half that was working."""
        self.assertEqual("ask", self._bash_from(self.target))
        self.assertEqual("ask", self._bash_from(self.subdirectory))

    def test_a_directory_that_is_not_a_repository_still_decides(self) -> None:
        """Root resolution falls back to the supplied path when git cannot
        answer. The wave-shape gate reads wave plans straight off the
        filesystem and needs no git, so a non-repository directory is a
        supported case -- degrading here would remove enforcement that
        worked before this change.
        """
        with tempfile.TemporaryDirectory() as outside:
            plans = Path(outside) / "docs" / "codev" / "wave"
            plans.mkdir(parents=True)
            (plans / "w.md").write_text(
                "## Later waves\n\n| Task | Owner |\n| --- | --- |\n| a | b |\n",
                encoding="utf-8",
            )
            decision = check(
                "wave-shape",
                {
                    "tool_name": "Write",
                    "tool_input": {
                        "file_path": str(plans / "w.md"),
                        "content": "## Later waves\n\n| Task | Owner |\n"
                        "| --- | --- |\n| a | b |\n",
                    },
                    "cwd": outside,
                },
                target=Path(outside),
            )
        self.assertEqual("ask", decision.decision)


if __name__ == "__main__":
    unittest.main()
