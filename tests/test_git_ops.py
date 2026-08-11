from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codev_workflow import git_ops, work

FULL_COVERAGE = {
    dimension: {"passed": True, "evidence": f"checked {dimension}"}
    for dimension in work.REQUIRED_COVERAGE_DIMENSIONS
}


def _run(args: list[str], *, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(target: Path) -> str:
    _run(["init", "-b", "main"], cwd=target)
    _run(["config", "user.name", "Test User"], cwd=target)
    _run(["config", "user.email", "test@example.com"], cwd=target)
    (target / "README.md").write_text("hello\n", encoding="utf-8")
    _run(["add", "-A"], cwd=target)
    _run(["commit", "-m", "initial commit"], cwd=target)
    return git_ops.current_head(target)


class BranchAndCommitTests(unittest.TestCase):
    def test_create_branch_checks_out_a_new_branch_from_base(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            branch = git_ops.create_branch("item-1", base, target=target)
        self.assertEqual("codev/item-1", branch)

    def test_create_branch_actually_switches_the_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            self.assertEqual("codev/item-1", git_ops.current_branch(target))

    def test_create_branch_twice_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            with self.assertRaises(git_ops.GitOpsError):
                git_ops.create_branch("item-1", base, target=target)

    def test_commit_without_a_branch_recorded_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            _init_repo(target)
            with self.assertRaises(git_ops.GitOpsError):
                git_ops.commit("item-1", "a change", target=target)

    def test_commit_refuses_when_not_on_the_own_branch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            _run(["checkout", "main"], cwd=target)
            with self.assertRaises(git_ops.GitOpsError):
                git_ops.commit("item-1", "a change", target=target)

    def test_commit_rejects_an_empty_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            with self.assertRaises(git_ops.GitOpsError):
                git_ops.commit("item-1", "   ", target=target)

    def test_commit_records_a_new_head(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            (target / "changed.txt").write_text("new content\n", encoding="utf-8")
            new_head = git_ops.commit("item-1", "add changed.txt", target=target)
            self.assertNotEqual(base, new_head)
            self.assertEqual(new_head, git_ops.current_head(target))


class PushTests(unittest.TestCase):
    def test_push_sends_the_own_branch_to_origin(self) -> None:
        with (
            tempfile.TemporaryDirectory() as origin_dir,
            tempfile.TemporaryDirectory() as work_dir,
        ):
            origin = Path(origin_dir)
            target = Path(work_dir)
            _run(["init", "--bare", "-b", "main"], cwd=origin)
            base = _init_repo(target)
            _run(["remote", "add", "origin", str(origin)], cwd=target)
            _run(["push", "origin", "main"], cwd=target)
            _run(["remote", "set-head", "origin", "-a"], cwd=target)

            git_ops.create_branch("item-1", base, target=target)
            (target / "changed.txt").write_text("content\n", encoding="utf-8")
            git_ops.commit("item-1", "add changed.txt", target=target)
            git_ops.push("item-1", target=target)

            remote_branches = _run_capture(
                ["branch", "--list", "codev/item-1"], cwd=origin
            )
        self.assertIn("codev/item-1", remote_branches)

    def test_push_refuses_when_the_branch_resolves_to_default(self) -> None:
        with (
            tempfile.TemporaryDirectory() as origin_dir,
            tempfile.TemporaryDirectory() as work_dir,
        ):
            origin = Path(origin_dir)
            target = Path(work_dir)
            _run(["init", "--bare", "-b", "main"], cwd=origin)
            base = _init_repo(target)
            _run(["remote", "add", "origin", str(origin)], cwd=target)
            _run(["push", "origin", "main"], cwd=target)
            _run(["remote", "set-head", "origin", "-a"], cwd=target)
            git_ops.create_branch("item-1", base, target=target)

            with (
                patch.object(git_ops, "own_branch", return_value="main"),
                self.assertRaises(git_ops.GitOpsError),
            ):
                git_ops.push("item-1", target=target)


def _run_capture(args: list[str], *, cwd: Path) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return completed.stdout


class OpenPrTests(unittest.TestCase):
    def _repo_ready_for_pr(self, target: Path) -> str:
        base = _init_repo(target)
        work.start("item-1", base, target=target)
        git_ops.create_branch("item-1", base, target=target)
        work.record_reviewer(
            "item-1", 1, base, [], {}, "READY_FOR_OUTER_LOOP", target=target
        )
        return base

    def test_refuses_when_check_is_not_ready_for_pr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            work.start("item-1", base, target=target)
            git_ops.create_branch("item-1", base, target=target)
            with (
                patch.object(git_ops, "_run_gh") as run_gh,
                self.assertRaises(git_ops.GitOpsError),
            ):
                git_ops.open_pr("item-1", "title", "body", target=target)
        run_gh.assert_not_called()

    def test_opens_a_draft_pr_with_no_force_flag_when_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._repo_ready_for_pr(target)
            with patch.object(
                git_ops, "_run_gh", return_value="https://github.com/o/r/pull/1"
            ) as run_gh:
                url = git_ops.open_pr(
                    "item-1", "title", "body", target=target, base="main"
                )
            command = run_gh.call_args.args[0]
        self.assertEqual("https://github.com/o/r/pull/1", url)
        self.assertIn("--draft", command)
        self.assertNotIn("--force", command)
        self.assertNotIn("-f", command)
        self.assertIn("codev/item-1", command)


class MarkReadyTests(unittest.TestCase):
    def _repo_ready_for_approval(self, target: Path) -> None:
        base = _init_repo(target)
        work.start("item-1", base, target=target)
        git_ops.create_branch("item-1", base, target=target)
        work.record_reviewer(
            "item-1", 1, base, [], {}, "READY_FOR_OUTER_LOOP", target=target
        )
        work.record_builder(
            "item-1", 2, base, {"delivered": "opened pr"}, target=target
        )
        work.record_reviewer(
            "item-1",
            2,
            base,
            [],
            FULL_COVERAGE,
            "READY_FOR_HUMAN_APPROVAL",
            target=target,
        )

    def test_refuses_when_check_is_not_ok_approve(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            work.start("item-1", base, target=target)
            git_ops.create_branch("item-1", base, target=target)
            with (
                patch.object(git_ops, "_run_gh") as run_gh,
                self.assertRaises(git_ops.GitOpsError),
            ):
                git_ops.mark_ready("item-1", target=target)
        run_gh.assert_not_called()

    def test_edits_then_readies_when_approved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._repo_ready_for_approval(target)
            with patch.object(git_ops, "_run_gh", return_value="") as run_gh:
                git_ops.mark_ready("item-1", target=target)
            commands = [call.args[0] for call in run_gh.call_args_list]
        self.assertEqual(2, len(commands))
        self.assertIn("edit", commands[0])
        self.assertIn("ready", commands[1])


if __name__ == "__main__":
    unittest.main()
