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
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from codev_workflow import config, git_ops, task

FULL_COVERAGE = {
    dimension: {"passed": True, "evidence": f"checked {dimension}"}
    for dimension in task.REQUIRED_COVERAGE_DIMENSIONS
}
_BUNDLE_PR_TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "codev_workflow"
    / "bundle"
    / ".github"
    / "pull_request_template.md"
)


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


def _write_lock(target: Path, managed_paths: list[str]) -> None:
    lock_dir = target / ".codev"
    lock_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 2,
        "bundle_version": "0.0.0",
        "platforms": [],
        "programming_language": None,
        "files": {path: "deadbeef" for path in managed_paths},
        "integrations": {},
    }
    (lock_dir / "lock.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_pr_template(target: Path) -> None:
    template = target / git_ops.PR_TEMPLATE_PATH
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_text(
        _BUNDLE_PR_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8"
    )


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

    def test_paths_and_staged_are_mutually_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            with self.assertRaises(git_ops.GitOpsError):
                git_ops.commit(
                    "item-1", "a change", target=target, paths=["a.txt"], staged=True
                )

    def test_round_and_evidence_must_be_given_together(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            (target / "changed.txt").write_text("content\n", encoding="utf-8")
            with self.assertRaises(git_ops.GitOpsError):
                git_ops.commit("item-1", "a change", target=target, round_number=1)

    def test_paths_commits_only_the_named_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            (target / "in-scope.txt").write_text("scoped\n", encoding="utf-8")
            (target / "unrelated.txt").write_text("unrelated\n", encoding="utf-8")
            git_ops.commit(
                "item-1", "scoped change", target=target, paths=["in-scope.txt"]
            )
            changed = git_ops.changed_files("item-1", target=target)
            self.assertIn("in-scope.txt", changed)
            self.assertNotIn("unrelated.txt", changed)
            status = _run_capture(["status", "--porcelain"], cwd=target)
            self.assertIn("unrelated.txt", status)

    def test_staged_commits_only_the_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            (target / "staged.txt").write_text("staged\n", encoding="utf-8")
            (target / "unstaged.txt").write_text("unstaged\n", encoding="utf-8")
            _run(["add", "staged.txt"], cwd=target)
            git_ops.commit("item-1", "staged only", target=target, staged=True)
            self.assertIn("staged.txt", git_ops.changed_files("item-1", target=target))
            self.assertNotIn(
                "unstaged.txt", git_ops.changed_files("item-1", target=target)
            )

    def test_round_and_evidence_records_builder_receipt_on_resulting_head(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            task.start("item-1", base, target=target)
            git_ops.create_branch("item-1", base, target=target)
            (target / "changed.txt").write_text("content\n", encoding="utf-8")
            head = git_ops.commit(
                "item-1",
                "builder change",
                target=target,
                round_number=1,
                evidence={"validation": "pytest passed"},
            )
            # If record_builder had been called against a stale head, check()
            # would report stop_drift instead of waiting on the reviewer.
            result = task.check("item-1", head, target=target)
            self.assertTrue(result.ok)
            self.assertEqual("ok_waiting_on_reviewer", result.reason)

    def test_refuses_mixed_managed_and_product_changes_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            _write_lock(target, [".codev/for-ai/ai-agent-guidelines.md"])
            (target / ".codev").mkdir(exist_ok=True)
            (target / ".codev" / "for-ai").mkdir(exist_ok=True)
            (target / ".codev" / "for-ai" / "ai-agent-guidelines.md").write_text(
                "updated\n", encoding="utf-8"
            )
            (target / "product.py").write_text("code\n", encoding="utf-8")
            with self.assertRaises(git_ops.GitOpsError):
                git_ops.commit("item-1", "mixed change", target=target)

    def test_allows_homogeneous_dirty_paths_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            _write_lock(target, [".codev/for-ai/ai-agent-guidelines.md"])
            (target / "product.py").write_text("code\n", encoding="utf-8")
            head = git_ops.commit("item-1", "product only", target=target)
            self.assertEqual(head, git_ops.current_head(target))

    def test_mixed_changes_allowed_with_explicit_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            _write_lock(target, [".codev/for-ai/ai-agent-guidelines.md"])
            (target / ".codev").mkdir(exist_ok=True)
            (target / ".codev" / "for-ai").mkdir(exist_ok=True)
            (target / ".codev" / "for-ai" / "ai-agent-guidelines.md").write_text(
                "updated\n", encoding="utf-8"
            )
            (target / "product.py").write_text("code\n", encoding="utf-8")
            git_ops.commit(
                "item-1", "product only", target=target, paths=["product.py"]
            )
            self.assertIn("product.py", git_ops.changed_files("item-1", target=target))


class CreateBranchGuardTests(unittest.TestCase):
    def test_dirty_worktree_is_refused_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            (target / "uncommitted.txt").write_text("wip\n", encoding="utf-8")
            with self.assertRaises(git_ops.GitOpsError):
                git_ops.create_branch("item-1", base, target=target)

    def test_allow_dirty_permits_branching_with_uncommitted_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            (target / "uncommitted.txt").write_text("wip\n", encoding="utf-8")
            branch = git_ops.create_branch(
                "item-1", base, target=target, allow_dirty=True
            )
            self.assertEqual("codev/item-1", branch)
            self.assertEqual("codev/item-1", git_ops.current_branch(target))

    def test_refuses_to_branch_from_another_tasks_branch_with_unmerged_commits(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            (target / "one.txt").write_text("a\n", encoding="utf-8")
            git_ops.commit("item-1", "item-1's own change", target=target)
            with self.assertRaises(git_ops.GitOpsError) as caught:
                git_ops.create_branch("item-2", base, target=target)
            self.assertIn("item-1", str(caught.exception))

    def test_allows_branching_from_another_tasks_branch_with_no_commits_yet(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            branch = git_ops.create_branch("item-2", base, target=target)
            self.assertEqual("codev/item-2", branch)

    def test_base_defaults_to_the_repository_default_branch(self) -> None:
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

            branch = git_ops.create_branch("item-1", target=target)
            self.assertEqual("codev/item-1", branch)
            state = json.loads(
                (target / ".codev/task/item-1/git-state.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(base, state["base_snapshot"])

    def test_base_defaults_to_configured_pr_base(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            _run(["checkout", "-q", "-b", "develop"], cwd=target)
            (target / "develop-only.txt").write_text("d\n", encoding="utf-8")
            _run(["add", "-A"], cwd=target)
            _run(["commit", "-q", "-m", "develop commit"], cwd=target)
            develop_head = git_ops.current_head(target)
            _run(["checkout", "-q", "main"], cwd=target)
            config.set_value("git.pr_base", "develop", target=target)
            _run(["add", "-A"], cwd=target)
            _run(["commit", "-q", "-m", "configure pr_base"], cwd=target)

            git_ops.create_branch("item-1", target=target)
            state = json.loads(
                (target / ".codev/task/item-1/git-state.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(develop_head, state["base_snapshot"])
            self.assertNotEqual(base, state["base_snapshot"])

    def test_defaulted_base_is_pinned_to_a_commit_not_a_floating_branch_name(
        self,
    ) -> None:
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

            git_ops.create_branch("item-1", target=target)
            _run(["checkout", "-q", "main"], cwd=target)
            (target / "later.txt").write_text("later\n", encoding="utf-8")
            # Scoped add, not -A: item-1's still-uncommitted git-state.json
            # is also untracked right now, and -A would sweep it onto main
            # too, which then vanishes on checkout back to codev/item-1.
            _run(["add", "later.txt"], cwd=target)
            _run(["commit", "-q", "-m", "a later main commit"], cwd=target)
            _run(["checkout", "-q", "codev/item-1"], cwd=target)
            # If base_snapshot had been left as the floating name "main"
            # instead of pinned to a sha, this diff would now pick up
            # later.txt even though item-1 never touched it.
            self.assertNotIn(
                "later.txt", git_ops.changed_files("item-1", target=target)
            )
            state = json.loads(
                (target / ".codev/task/item-1/git-state.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(base, state["base_snapshot"])


class StackOnTests(unittest.TestCase):
    def test_child_branches_from_the_parents_current_head(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            (target / "parent-only.txt").write_text("p\n", encoding="utf-8")
            parent_head = git_ops.commit("item-1", "parent change", target=target)

            git_ops.create_branch("item-2", target=target, stack_on="item-1")
            self.assertEqual("codev/item-2", git_ops.current_branch(target))
            self.assertEqual(parent_head, git_ops.current_head(target))

            state = json.loads(
                (target / ".codev/task/item-2/git-state.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual("item-1", state["parent_task"])
            self.assertEqual(parent_head, state["base_snapshot"])

    def test_child_sees_parents_changes_as_already_merged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            (target / "parent-only.txt").write_text("p\n", encoding="utf-8")
            git_ops.commit("item-1", "parent change", target=target)

            git_ops.create_branch("item-2", target=target, stack_on="item-1")
            self.assertEqual([], git_ops.changed_files("item-2", target=target))

    def test_foreign_branch_guard_does_not_fire_when_stacking_on_purpose(
        self,
    ) -> None:
        # HEAD is on item-1's own branch, with real unmerged commits -- the
        # ordinary create_branch guard would refuse this. --stack-on names
        # the parent explicitly, so it should not.
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            (target / "parent-only.txt").write_text("p\n", encoding="utf-8")
            git_ops.commit("item-1", "parent change", target=target)

            branch = git_ops.create_branch("item-2", target=target, stack_on="item-1")
            self.assertEqual("codev/item-2", branch)

    def test_refuses_to_stack_on_a_task_with_no_recorded_branch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            _init_repo(target)
            with self.assertRaises(git_ops.GitOpsError) as caught:
                git_ops.create_branch("item-2", target=target, stack_on="item-1")
            self.assertIn("item-1", str(caught.exception))

    def test_refuses_to_stack_under_feature_branch_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            config.set_value("git.workflow", "feature-branch", target=target)
            _run(["add", "-A"], cwd=target)
            _run(["commit", "-q", "-m", "configure feature-branch"], cwd=target)
            with self.assertRaises(git_ops.GitOpsError) as caught:
                git_ops.create_branch("item-2", target=target, stack_on="item-1")
            self.assertIn("feature-branch", str(caught.exception))

    def test_parent_task_id_is_none_for_a_standalone_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            self.assertIsNone(git_ops.parent_task_id("item-1", target=target))

    def test_parent_task_id_is_none_for_an_unknown_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            _init_repo(target)
            self.assertIsNone(git_ops.parent_task_id("unknown", target=target))

    def test_parent_task_id_reads_the_recorded_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            git_ops.create_branch("item-2", target=target, stack_on="item-1")
            self.assertEqual("item-1", git_ops.parent_task_id("item-2", target=target))

    def test_stack_depth_is_one_for_a_standalone_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            self.assertEqual(1, git_ops.stack_depth("item-1", target=target))

    def test_stack_depth_counts_the_full_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            git_ops.create_branch("item-2", target=target, stack_on="item-1")
            git_ops.create_branch("item-3", target=target, stack_on="item-2")
            self.assertEqual(1, git_ops.stack_depth("item-1", target=target))
            self.assertEqual(2, git_ops.stack_depth("item-2", target=target))
            self.assertEqual(3, git_ops.stack_depth("item-3", target=target))

    def test_has_recorded_child_false_for_a_standalone_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            self.assertFalse(git_ops._has_recorded_child("item-1", target=target))

    def test_has_recorded_child_true_once_a_child_is_created(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            git_ops.create_branch("item-2", target=target, stack_on="item-1")
            self.assertTrue(git_ops._has_recorded_child("item-1", target=target))
            # item-2 itself has no child yet.
            self.assertFalse(git_ops._has_recorded_child("item-2", target=target))


class ChangedFilesTests(unittest.TestCase):
    def test_returns_empty_list_when_no_branch_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            _init_repo(target)
            self.assertEqual([], git_ops.changed_files("item-1", target=target))

    def test_lists_paths_changed_since_the_base_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            (target / "changed.txt").write_text("content\n", encoding="utf-8")
            git_ops.commit("item-1", "add changed.txt", target=target)
            self.assertIn("changed.txt", git_ops.changed_files("item-1", target=target))

    def test_empty_list_when_nothing_changed_yet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            self.assertEqual([], git_ops.changed_files("item-1", target=target))


class TaskSizeTests(unittest.TestCase):
    def test_zero_counts_when_no_branch_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            _init_repo(target)
            size = git_ops.task_size("item-1", target=target)
            self.assertEqual(0, size.lines_changed)
            self.assertEqual(0, size.files_changed)
            self.assertEqual(400, size.max_lines)
            self.assertEqual(8, size.max_files)
            self.assertFalse(size.over_budget)

    def test_counts_lines_and_files_changed_since_base(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            (target / "one.txt").write_text("a\nb\nc\n", encoding="utf-8")
            (target / "two.txt").write_text("d\ne\n", encoding="utf-8")
            git_ops.commit("item-1", "add two files", target=target)
            size = git_ops.task_size("item-1", target=target)
            self.assertEqual(5, size.lines_changed)
            self.assertEqual(2, size.files_changed)

    def test_linguist_generated_paths_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            (target / ".gitattributes").write_text(
                "generated.txt linguist-generated=true\n", encoding="utf-8"
            )
            (target / "generated.txt").write_text("x\n" * 10, encoding="utf-8")
            (target / "real.txt").write_text("y\n", encoding="utf-8")
            git_ops.commit("item-1", "add generated and real files", target=target)
            size = git_ops.task_size("item-1", target=target)
            # .gitattributes itself is not marked generated, so it counts too.
            self.assertEqual(2, size.lines_changed)
            self.assertEqual(2, size.files_changed)

    def test_configured_budget_overrides_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            config.set_value("review.max_lines", "1", target=target)
            (target / "one.txt").write_text("a\nb\n", encoding="utf-8")
            git_ops.commit("item-1", "add one.txt", target=target)
            size = git_ops.task_size("item-1", target=target)
            self.assertEqual(1, size.max_lines)
            self.assertTrue(size.over_budget)

    def test_own_task_bookkeeping_is_excluded_from_the_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            # create_branch already committed nothing; git-state.json rides
            # along on the next commit's `git add -A` alongside real content.
            (target / "one.txt").write_text("a\n", encoding="utf-8")
            git_ops.commit("item-1", "add one.txt", target=target)
            output = subprocess.run(
                ["git", "diff", "--numstat", base, "codev/item-1"],
                cwd=target,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            self.assertIn(".codev/task/item-1/git-state.json", output)
            size = git_ops.task_size("item-1", target=target)
            self.assertEqual(1, size.lines_changed)
            self.assertEqual(1, size.files_changed)

    def test_non_integer_configured_budget_falls_back_to_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            _init_repo(target)
            config.set_value("review.max_files", "not-a-number", target=target)
            with self.assertWarns(UserWarning):
                size = git_ops.task_size("item-1", target=target)
            self.assertEqual(8, size.max_files)


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


def _gh_no_existing_pr(
    pr_create_url: str = "https://github.com/o/r/pull/1",
    repo_view: str | None = None,
) -> Callable[..., str]:
    """A `_run_gh` side_effect: no PR exists yet for any branch queried."""

    def fake(args: list[str], *, cwd: Path) -> str:
        if args[:2] == ["pr", "view"]:
            raise git_ops.GitOpsError("no pull requests found")
        if args[:2] == ["repo", "view"]:
            if repo_view is None:
                raise AssertionError("unexpected repo view call")
            return repo_view
        return pr_create_url

    return fake


class OpenPrTests(unittest.TestCase):
    def _repo_ready_for_pr(self, target: Path) -> str:
        base = _init_repo(target)
        task.start("item-1", base, target=target)
        git_ops.create_branch("item-1", base, target=target)
        task.record_reviewer(
            "item-1", 1, base, [], {}, "READY_FOR_OUTER_LOOP", target=target
        )
        return base

    def test_refuses_when_check_is_not_ready_for_pr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            task.start("item-1", base, target=target)
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
                git_ops, "_run_gh", side_effect=_gh_no_existing_pr()
            ) as run_gh:
                url = git_ops.open_pr(
                    "item-1", "title", "body", target=target, base="main"
                )
            create_call = next(
                call
                for call in run_gh.call_args_list
                if call.args[0][:2] == ["pr", "create"]
            )
            command = create_call.args[0]
        self.assertEqual("https://github.com/o/r/pull/1", url)
        self.assertIn("--draft", command)
        self.assertNotIn("--force", command)
        self.assertNotIn("-f", command)
        self.assertIn("codev/item-1", command)

    def test_renders_the_repository_pr_template_for_an_automatic_body(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._repo_ready_for_pr(target)
            _write_pr_template(target)
            with patch.object(
                git_ops, "_run_gh", side_effect=_gh_no_existing_pr()
            ) as run_gh:
                git_ops.open_pr(
                    "item-1",
                    "title",
                    task.pr_description("item-1", target=target),
                    target=target,
                    base="main",
                    use_template=True,
                )
            create_call = next(
                call
                for call in run_gh.call_args_list
                if call.args[0][:2] == ["pr", "create"]
            )
            body = create_call.args[0][create_call.args[0].index("--body") + 1]
        self.assertIn("## Summary", body)
        self.assertIn("## Test plan", body)
        self.assertIn("Task item-1.", body)
        self.assertNotIn("<!-- codev:", body)

    def test_falls_back_when_the_repository_template_is_incompatible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._repo_ready_for_pr(target)
            template = target / git_ops.PR_TEMPLATE_PATH
            template.parent.mkdir(parents=True, exist_ok=True)
            template.write_text("## Summary\n", encoding="utf-8")
            with (
                self.assertWarnsRegex(UserWarning, "not CoDev-compatible"),
                patch.object(
                    git_ops, "_run_gh", side_effect=_gh_no_existing_pr()
                ) as run_gh,
            ):
                git_ops.open_pr(
                    "item-1",
                    "title",
                    task.pr_description("item-1", target=target),
                    target=target,
                    base="main",
                    use_template=True,
                )
            create_call = next(
                call
                for call in run_gh.call_args_list
                if call.args[0][:2] == ["pr", "create"]
            )
            body = create_call.args[0][create_call.args[0].index("--body") + 1]
            expected = task.pr_description("item-1", target=target)
        self.assertEqual(expected, body)

    def test_uses_configured_pr_base_when_none_given(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._repo_ready_for_pr(target)
            config.set_value("git.pr_base", "develop", target=target)
            with (
                patch.object(
                    git_ops, "_run_gh", side_effect=_gh_no_existing_pr()
                ) as run_gh,
                patch.object(git_ops, "default_branch") as default_branch,
            ):
                git_ops.open_pr("item-1", "title", "body", target=target)
            default_branch.assert_not_called()
            create_call = next(
                call
                for call in run_gh.call_args_list
                if call.args[0][:2] == ["pr", "create"]
            )
        self.assertIn("develop", create_call.args[0])

    def test_explicit_base_overrides_configured_pr_base(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._repo_ready_for_pr(target)
            config.set_value("git.pr_base", "develop", target=target)
            with patch.object(
                git_ops, "_run_gh", side_effect=_gh_no_existing_pr()
            ) as run_gh:
                git_ops.open_pr(
                    "item-1", "title", "body", target=target, base="release"
                )
            create_call = next(
                call
                for call in run_gh.call_args_list
                if call.args[0][:2] == ["pr", "create"]
            )
            command = create_call.args[0]
        self.assertIn("release", command)
        self.assertNotIn("develop", command)

    def _stacked_child_ready_for_pr(self, target: Path) -> None:
        base = _init_repo(target)
        task.start("item-1", base, target=target)
        git_ops.create_branch("item-1", base, target=target)
        task.record_reviewer(
            "item-1", 1, base, [], {}, "READY_FOR_OUTER_LOOP", target=target
        )
        parent_head = git_ops.current_head(target)
        task.start("item-2", parent_head, target=target)
        git_ops.create_branch("item-2", target=target, stack_on="item-1")
        task.record_reviewer(
            "item-2", 1, parent_head, [], {}, "READY_FOR_OUTER_LOOP", target=target
        )

    @staticmethod
    def _fake_gh_with_parent_pr_state(state: str) -> Callable[..., str]:
        def fake(args: list[str], *, cwd: Path) -> str:
            if args[:2] == ["pr", "view"]:
                branch = args[2]
                if "state" in args:
                    return state if branch == "codev/item-1" else "MERGED"
                raise git_ops.GitOpsError("no pull requests found")
            return "https://github.com/o/r/pull/2"

        return fake

    def test_stacked_task_targets_the_parents_branch_while_its_pr_is_open(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._stacked_child_ready_for_pr(target)
            with patch.object(
                git_ops,
                "_run_gh",
                side_effect=self._fake_gh_with_parent_pr_state("OPEN"),
            ) as run_gh:
                git_ops.open_pr("item-2", "title", "body", target=target)
            create_call = next(
                call
                for call in run_gh.call_args_list
                if call.args[0][:2] == ["pr", "create"]
            )
        self.assertIn("codev/item-1", create_call.args[0])

    def test_stacked_task_falls_back_to_default_base_once_parent_pr_is_merged(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._stacked_child_ready_for_pr(target)
            with patch.object(
                git_ops,
                "_run_gh",
                side_effect=self._fake_gh_with_parent_pr_state("MERGED"),
            ) as run_gh:
                git_ops.open_pr("item-2", "title", "body", target=target, base="main")
            create_call = next(
                call
                for call in run_gh.call_args_list
                if call.args[0][:2] == ["pr", "create"]
            )
            command = create_call.args[0]
        self.assertIn("main", command)
        self.assertNotIn("codev/item-1", command)

    def test_falls_back_to_repository_default_branch_when_unconfigured(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._repo_ready_for_pr(target)
            with (
                patch.object(git_ops, "_run_gh", side_effect=_gh_no_existing_pr()),
                patch.object(
                    git_ops, "default_branch", return_value="main"
                ) as default_branch,
            ):
                git_ops.open_pr("item-1", "title", "body", target=target)
            default_branch.assert_called_once()

    def test_refuses_when_a_pr_already_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._repo_ready_for_pr(target)

            def fake_run_gh(args: list[str], *, cwd: Path) -> str:
                if args[:2] == ["pr", "view"]:
                    return "https://github.com/o/r/pull/9"
                raise AssertionError(f"unexpected call: {args}")

            with (
                patch.object(git_ops, "_run_gh", side_effect=fake_run_gh) as run_gh,
                self.assertRaises(git_ops.GitOpsError) as context,
            ):
                git_ops.open_pr("item-1", "title", "body", target=target, base="main")
            self.assertIn("already has one open", str(context.exception))
            self.assertIn("mark-ready", str(context.exception))
            self.assertFalse(
                any(
                    call.args[0][:2] == ["pr", "create"]
                    for call in run_gh.call_args_list
                )
            )

    def test_refuses_on_a_hard_stop_even_in_the_outer_phase(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            task.start("item-1", base, target=target)
            git_ops.create_branch("item-1", base, target=target)
            task.record_reviewer(
                "item-1", 1, base, [], {}, "READY_FOR_OUTER_LOOP", target=target
            )
            task.reopen(
                "item-1", "some-head-not-matching-real-git", "recovered", target=target
            )
            with (
                patch.object(git_ops, "_run_gh") as run_gh,
                self.assertRaises(git_ops.GitOpsError),
            ):
                git_ops.open_pr("item-1", "title", "body", target=target, base="main")
            run_gh.assert_not_called()

    def test_opens_a_pr_for_an_outer_phase_item_with_none_yet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            task.start("item-1", base, target=target)
            git_ops.create_branch("item-1", base, target=target)
            task.record_reviewer(
                "item-1", 1, base, [], {}, "READY_FOR_OUTER_LOOP", target=target
            )
            task.reopen("item-1", base, "recovered into the outer phase", target=target)
            task.record_reviewer(
                "item-1",
                2,
                base,
                [],
                FULL_COVERAGE,
                "READY_FOR_HUMAN_APPROVAL",
                target=target,
            )
            self.assertEqual(
                "ok_machine_review_complete",
                task.check("item-1", base, target=target).reason,
            )

            with patch.object(
                git_ops, "_run_gh", side_effect=_gh_no_existing_pr()
            ) as run_gh:
                url = git_ops.open_pr(
                    "item-1", "title", "body", target=target, base="main"
                )
            self.assertEqual("https://github.com/o/r/pull/1", url)
            pr_view_call = next(
                call
                for call in run_gh.call_args_list
                if call.args[0][:2] == ["pr", "view"]
            )
        self.assertEqual("codev/item-1", pr_view_call.args[0][2])

    def test_appends_closes_issue_when_link_ref_matches_same_repo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            task.start(
                "item-1",
                base,
                target=target,
                link_ref="https://github.com/o/r/issues/7",
            )
            git_ops.create_branch("item-1", base, target=target)
            _write_pr_template(target)
            task.record_reviewer(
                "item-1", 1, base, [], {}, "READY_FOR_OUTER_LOOP", target=target
            )

            with patch.object(
                git_ops, "_run_gh", side_effect=_gh_no_existing_pr(repo_view="o/r")
            ) as run_gh:
                git_ops.open_pr(
                    "item-1",
                    "title",
                    task.pr_description("item-1", target=target),
                    target=target,
                    base="main",
                    use_template=True,
                )
            pr_create_call = next(
                call
                for call in run_gh.call_args_list
                if call.args[0][:2] == ["pr", "create"]
            )
            body_index = pr_create_call.args[0].index("--body") + 1
        self.assertIn("Closes #7", pr_create_call.args[0][body_index])

    def test_writes_part_of_instead_of_closes_when_a_child_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            task.start(
                "item-1",
                base,
                target=target,
                link_ref="https://github.com/o/r/issues/7",
            )
            git_ops.create_branch("item-1", base, target=target)
            task.record_reviewer(
                "item-1", 1, base, [], {}, "READY_FOR_OUTER_LOOP", target=target
            )
            # item-2 stacks on item-1, recording item-1 as its parent --
            # item-1 now has a child and should no longer close the issue.
            git_ops.create_branch("item-2", target=target, stack_on="item-1")
            _run(["checkout", "-q", "codev/item-1"], cwd=target)
            _write_pr_template(target)

            with patch.object(
                git_ops, "_run_gh", side_effect=_gh_no_existing_pr(repo_view="o/r")
            ) as run_gh:
                git_ops.open_pr(
                    "item-1",
                    "title",
                    task.pr_description("item-1", target=target),
                    target=target,
                    base="main",
                    use_template=True,
                )
            pr_create_call = next(
                call
                for call in run_gh.call_args_list
                if call.args[0][:2] == ["pr", "create"]
            )
            body_index = pr_create_call.args[0].index("--body") + 1
            body = pr_create_call.args[0][body_index]
        self.assertIn("Part of #7", body)
        self.assertNotIn("Closes #7", body)

    def test_does_not_append_closes_issue_for_a_different_repo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            task.start(
                "item-1",
                base,
                target=target,
                link_ref="https://github.com/other/repo/issues/7",
            )
            git_ops.create_branch("item-1", base, target=target)
            task.record_reviewer(
                "item-1", 1, base, [], {}, "READY_FOR_OUTER_LOOP", target=target
            )

            with patch.object(
                git_ops, "_run_gh", side_effect=_gh_no_existing_pr(repo_view="o/r")
            ) as run_gh:
                git_ops.open_pr("item-1", "title", "body", target=target, base="main")
            pr_create_call = next(
                call
                for call in run_gh.call_args_list
                if call.args[0][:2] == ["pr", "create"]
            )
            body_index = pr_create_call.args[0].index("--body") + 1
        self.assertNotIn("Closes", pr_create_call.args[0][body_index])

    def test_does_not_append_closes_issue_when_link_ref_is_not_an_issue_url(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            task.start(
                "item-1",
                base,
                target=target,
                link_ref="docs/codev/work/item-1/implementation-plan.md",
            )
            git_ops.create_branch("item-1", base, target=target)
            task.record_reviewer(
                "item-1", 1, base, [], {}, "READY_FOR_OUTER_LOOP", target=target
            )
            with patch.object(
                git_ops, "_run_gh", side_effect=_gh_no_existing_pr()
            ) as run_gh:
                git_ops.open_pr("item-1", "title", "body", target=target, base="main")
            pr_create_call = next(
                call
                for call in run_gh.call_args_list
                if call.args[0][:2] == ["pr", "create"]
            )
            body_index = pr_create_call.args[0].index("--body") + 1
        self.assertEqual("body", pr_create_call.args[0][body_index])


class RestackTests(unittest.TestCase):
    def _stacked_pair(self, target: Path) -> str:
        base = _init_repo(target)
        task.start("item-1", base, target=target)
        git_ops.create_branch("item-1", base, target=target)
        task.start("item-2", base, target=target)
        git_ops.create_branch("item-2", target=target, stack_on="item-1")
        return base

    def test_refuses_when_not_on_the_own_branch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._stacked_pair(target)
            _run(["checkout", "-q", "codev/item-1"], cwd=target)
            with self.assertRaises(git_ops.GitOpsError):
                git_ops.restack("item-2", target=target)

    def test_refuses_for_a_task_with_no_recorded_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            with self.assertRaises(git_ops.GitOpsError) as caught:
                git_ops.restack("item-1", target=target)
            self.assertIn("no recorded parent", str(caught.exception))

    def test_refuses_once_the_parents_pr_has_merged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._stacked_pair(target)
            with (
                patch.object(git_ops, "_run_gh", return_value="MERGED"),
                self.assertRaises(git_ops.GitOpsError) as caught,
            ):
                git_ops.restack("item-2", target=target)
            self.assertIn("already merged", str(caught.exception))

    def test_rebases_onto_the_parents_new_head_and_force_pushes(self) -> None:
        with (
            tempfile.TemporaryDirectory() as origin_dir,
            tempfile.TemporaryDirectory() as work_dir,
        ):
            origin = Path(origin_dir)
            target = Path(work_dir)
            _run(["init", "--bare", "-b", "main"], cwd=origin)
            self._stacked_pair(target)
            _run(["remote", "add", "origin", str(origin)], cwd=target)
            _run(["push", "-q", "origin", "codev/item-2"], cwd=target)

            _run(["checkout", "-q", "codev/item-1"], cwd=target)
            (target / "parent-later.txt").write_text("p\n", encoding="utf-8")
            git_ops.commit(
                "item-1",
                "a later parent commit",
                target=target,
                paths=["parent-later.txt"],
            )
            _run(["checkout", "-q", "codev/item-2"], cwd=target)

            with patch.object(git_ops, "_run_gh", side_effect=_gh_no_existing_pr()):
                new_head = git_ops.restack("item-2", target=target)

            self.assertEqual(new_head, git_ops.current_head(target))
            self.assertIn(
                "parent-later.txt", git_ops.changed_files("item-1", target=target)
            )
            # item-2's own diff against its (now-advanced) base must not
            # pick up item-1's content as if item-2 had authored it.
            self.assertNotIn(
                "parent-later.txt", git_ops.changed_files("item-2", target=target)
            )
            remote_log = _run_capture(["log", "--oneline", "codev/item-2"], cwd=origin)
        self.assertIn("a later parent commit", remote_log)

    def test_uses_force_with_lease_never_a_bare_force(self) -> None:
        with (
            tempfile.TemporaryDirectory() as origin_dir,
            tempfile.TemporaryDirectory() as work_dir,
        ):
            origin = Path(origin_dir)
            target = Path(work_dir)
            _run(["init", "--bare", "-b", "main"], cwd=origin)
            self._stacked_pair(target)
            _run(["remote", "add", "origin", str(origin)], cwd=target)
            _run(["push", "-q", "origin", "codev/item-2"], cwd=target)

            real_run = subprocess.run
            captured: list[list[str]] = []

            def spy(args: list[str], **kwargs: Any) -> Any:
                if args[:1] == ["git"]:
                    captured.append(args)
                return real_run(args, **kwargs)

            with (
                patch.object(git_ops, "_run_gh", side_effect=_gh_no_existing_pr()),
                patch("subprocess.run", side_effect=spy),
            ):
                git_ops.restack("item-2", target=target)

            push_calls = [args for args in captured if "push" in args]
        self.assertTrue(push_calls)
        for call in push_calls:
            self.assertIn("--force-with-lease", call)
            self.assertNotIn("--force", call)

    def test_re_baselines_git_state_base_snapshot(self) -> None:
        with (
            tempfile.TemporaryDirectory() as origin_dir,
            tempfile.TemporaryDirectory() as work_dir,
        ):
            origin = Path(origin_dir)
            target = Path(work_dir)
            _run(["init", "--bare", "-b", "main"], cwd=origin)
            self._stacked_pair(target)
            _run(["remote", "add", "origin", str(origin)], cwd=target)
            _run(["push", "-q", "origin", "codev/item-2"], cwd=target)
            _run(["checkout", "-q", "codev/item-1"], cwd=target)
            (target / "parent-later.txt").write_text("p\n", encoding="utf-8")
            git_ops.commit(
                "item-1",
                "a later parent commit",
                target=target,
                paths=["parent-later.txt"],
            )
            new_parent_head = git_ops.current_head(target)
            _run(["checkout", "-q", "codev/item-2"], cwd=target)

            with patch.object(git_ops, "_run_gh", side_effect=_gh_no_existing_pr()):
                git_ops.restack("item-2", target=target)

            state = json.loads(
                (target / ".codev/task/item-2/git-state.json").read_text(
                    encoding="utf-8"
                )
            )
        self.assertEqual(new_parent_head, state["base_snapshot"])

    def test_clears_task_check_drift_after_restacking(self) -> None:
        with (
            tempfile.TemporaryDirectory() as origin_dir,
            tempfile.TemporaryDirectory() as work_dir,
        ):
            origin = Path(origin_dir)
            target = Path(work_dir)
            _run(["init", "--bare", "-b", "main"], cwd=origin)
            self._stacked_pair(target)
            _run(["remote", "add", "origin", str(origin)], cwd=target)
            _run(["push", "-q", "origin", "codev/item-2"], cwd=target)
            _run(["checkout", "-q", "codev/item-2"], cwd=target)
            (target / "child.txt").write_text("c\n", encoding="utf-8")
            head = git_ops.commit(
                "item-2",
                "child change",
                target=target,
                paths=["child.txt"],
                round_number=1,
                evidence={"validation": "pytest passed"},
            )
            task.record_reviewer(
                "item-2", 1, head, [], {}, "READY_FOR_OUTER_LOOP", target=target
            )

            _run(["checkout", "-q", "codev/item-1"], cwd=target)
            (target / "parent-later.txt").write_text("p\n", encoding="utf-8")
            git_ops.commit(
                "item-1",
                "a later parent commit",
                target=target,
                paths=["parent-later.txt"],
            )
            _run(["checkout", "-q", "codev/item-2"], cwd=target)

            with patch.object(git_ops, "_run_gh", side_effect=_gh_no_existing_pr()):
                new_head = git_ops.restack("item-2", target=target)

            result = task.check("item-2", new_head, target=target)
        self.assertTrue(result.ok)
        self.assertNotEqual(head, new_head)

    def test_conflict_leaves_the_repository_mid_rebase_for_a_human(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._stacked_pair(target)
            _run(["checkout", "-q", "codev/item-2"], cwd=target)
            (target / "README.md").write_text("child version\n", encoding="utf-8")
            git_ops.commit(
                "item-2",
                "child conflicting change",
                target=target,
                paths=["README.md"],
            )

            _run(["checkout", "-q", "codev/item-1"], cwd=target)
            (target / "README.md").write_text("parent version\n", encoding="utf-8")
            git_ops.commit(
                "item-1",
                "parent conflicting change",
                target=target,
                paths=["README.md"],
            )
            _run(["checkout", "-q", "codev/item-2"], cwd=target)

            with (
                patch.object(git_ops, "_run_gh", side_effect=_gh_no_existing_pr()),
                self.assertRaises(git_ops.GitOpsError),
            ):
                git_ops.restack("item-2", target=target)

            status = _run_capture(["status"], cwd=target)
        self.assertIn("rebas", status.lower())


class CreateIssueTests(unittest.TestCase):
    def test_creates_an_issue_with_no_work_item_precondition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with patch.object(
                git_ops, "_run_gh", return_value="https://github.com/o/r/issues/9"
            ) as run_gh:
                url = git_ops.create_issue("Fix the thing", "details", target=target)
            command = run_gh.call_args.args[0]
        self.assertEqual("https://github.com/o/r/issues/9", url)
        self.assertIn("Fix the thing", command)

    def test_forwards_repeated_assignee_flags(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with patch.object(
                git_ops, "_run_gh", return_value="https://github.com/o/r/issues/9"
            ) as run_gh:
                git_ops.create_issue(
                    "title",
                    "body",
                    target=target,
                    assignees=["alice", "bob"],
                )
            command = run_gh.call_args.args[0]
        self.assertEqual(2, command.count("--assignee"))
        self.assertIn("alice", command)
        self.assertIn("bob", command)


class SuggestOwnersTests(unittest.TestCase):
    def test_returns_empty_list_when_no_codeowners_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self.assertEqual([], git_ops.suggest_owners(["src/app.py"], target=target))

    def test_matches_a_glob_pattern(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / ".github").mkdir()
            (target / ".github" / "CODEOWNERS").write_text(
                "*.py @pydev\n", encoding="utf-8"
            )
            self.assertEqual(
                ["@pydev"], git_ops.suggest_owners(["src/app.py"], target=target)
            )

    def test_last_match_wins(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / "CODEOWNERS").write_text(
                "*.py @pydev\nsrc/app.py @specific-owner\n", encoding="utf-8"
            )
            self.assertEqual(
                ["@specific-owner"],
                git_ops.suggest_owners(["src/app.py"], target=target),
            )

    def test_matches_a_directory_pattern(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / "CODEOWNERS").write_text("docs/ @docwriter\n", encoding="utf-8")
            self.assertEqual(
                ["@docwriter"],
                git_ops.suggest_owners(["docs/readme.md"], target=target),
            )

    def test_no_match_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / "CODEOWNERS").write_text("*.py @pydev\n", encoding="utf-8")
            self.assertEqual([], git_ops.suggest_owners(["README.md"], target=target))

    def test_ignores_comments_and_blank_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / "CODEOWNERS").write_text(
                "# comment\n\n*.py @pydev\n", encoding="utf-8"
            )
            self.assertEqual(
                ["@pydev"], git_ops.suggest_owners(["app.py"], target=target)
            )


class MarkReadyTests(unittest.TestCase):
    def _repo_ready_for_approval(self, target: Path) -> None:
        base = _init_repo(target)
        task.start("item-1", base, target=target)
        git_ops.create_branch("item-1", base, target=target)
        task.record_reviewer(
            "item-1", 1, base, [], {}, "READY_FOR_OUTER_LOOP", target=target
        )
        task.record_builder(
            "item-1", 2, base, {"delivered": "opened pr"}, target=target
        )
        task.record_reviewer(
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
            task.start("item-1", base, target=target)
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

    def test_regenerated_body_is_the_pr_description_not_the_evidence_log(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._repo_ready_for_approval(target)
            with patch.object(git_ops, "_run_gh", return_value="") as run_gh:
                git_ops.mark_ready("item-1", target=target)
            edit_call = next(
                call for call in run_gh.call_args_list if "edit" in call.args[0]
            )
            body = edit_call.args[0][edit_call.args[0].index("--body") + 1]
            self.assertEqual(task.pr_description("item-1", target=target), body)
            self.assertNotEqual(task.log_text("item-1", target=target), body)
        self.assertNotIn("round 1:", body)

    def test_regenerated_body_preserves_the_repository_pr_template(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._repo_ready_for_approval(target)
            _write_pr_template(target)
            with patch.object(git_ops, "_run_gh", return_value="") as run_gh:
                git_ops.mark_ready("item-1", target=target)
            edit_call = next(
                call for call in run_gh.call_args_list if "edit" in call.args[0]
            )
            body = edit_call.args[0][edit_call.args[0].index("--body") + 1]
        self.assertIn("## Summary", body)
        self.assertIn("## Review", body)
        self.assertIn("Latest task review: READY_FOR_HUMAN_APPROVAL.", body)
        self.assertNotIn("<!-- codev:", body)

    def test_appends_closes_issue_when_link_ref_matches_same_repo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            task.start(
                "item-1",
                base,
                target=target,
                link_ref="https://github.com/o/r/issues/7",
            )
            git_ops.create_branch("item-1", base, target=target)
            task.record_reviewer(
                "item-1", 1, base, [], {}, "READY_FOR_OUTER_LOOP", target=target
            )
            task.record_builder(
                "item-1", 2, base, {"delivered": "opened pr"}, target=target
            )
            task.record_reviewer(
                "item-1",
                2,
                base,
                [],
                FULL_COVERAGE,
                "READY_FOR_HUMAN_APPROVAL",
                target=target,
            )

            def fake_run_gh(args: list[str], *, cwd: Path) -> str:
                if args[:2] == ["repo", "view"]:
                    return "o/r"
                return ""

            with patch.object(git_ops, "_run_gh", side_effect=fake_run_gh) as run_gh:
                git_ops.mark_ready("item-1", target=target)
            edit_call = next(
                call for call in run_gh.call_args_list if "edit" in call.args[0]
            )
            body = edit_call.args[0][edit_call.args[0].index("--body") + 1]
        self.assertIn("Closes #7", body)

    def test_does_not_append_closes_issue_when_link_ref_is_not_an_issue_url(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._repo_ready_for_approval(target)
            with patch.object(git_ops, "_run_gh", return_value="") as run_gh:
                git_ops.mark_ready("item-1", target=target)
            edit_call = next(
                call for call in run_gh.call_args_list if "edit" in call.args[0]
            )
            body = edit_call.args[0][edit_call.args[0].index("--body") + 1]
        self.assertNotIn("Closes", body)

    def test_readies_when_approved_with_deferrals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            task.start("item-1", base, target=target)
            git_ops.create_branch("item-1", base, target=target)
            task.record_reviewer(
                "item-1", 1, base, [], {}, "READY_FOR_OUTER_LOOP", target=target
            )
            task.record_builder("item-1", 2, base, {}, target=target)
            finding = {
                "id": "f1",
                "location": "a.py:1",
                "category": "error_handling",
                "blocking": True,
                "rank": 1,
                "summary": "leaks a raw OSError",
            }
            task.record_reviewer(
                "item-1",
                2,
                base,
                [finding],
                FULL_COVERAGE,
                "CHANGES_REQUIRED",
                target=target,
            )
            task.record_triage(
                "item-1",
                2,
                {
                    "dispositions": {
                        "f1": {
                            "disposition": "defer",
                            "override_reason": "tracked in issue #42",
                        }
                    }
                },
                target=target,
            )
            self.assertEqual(
                "ok_machine_review_complete_with_deferrals",
                task.check("item-1", base, target=target).reason,
            )

            with patch.object(git_ops, "_run_gh", return_value="") as run_gh:
                git_ops.mark_ready("item-1", target=target)
            commands = [call.args[0] for call in run_gh.call_args_list]
        self.assertEqual(2, len(commands))
        self.assertIn("edit", commands[0])
        self.assertIn("ready", commands[1])


class DetectIdentityTests(unittest.TestCase):
    def test_prefers_the_authenticated_gh_login(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with (
                patch.object(git_ops, "_gh_executable", return_value="/usr/bin/gh"),
                patch(
                    "codev_workflow.git_ops.subprocess.run",
                    return_value=SimpleNamespace(returncode=0, stdout="octocat\n"),
                ) as run,
            ):
                identity = git_ops.detect_identity(target=target)
            self.assertEqual("octocat", identity)
            self.assertIn("user", run.call_args.args[0])

    def test_falls_back_to_git_config_when_gh_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with (
                patch.object(git_ops, "_gh_executable", return_value=None),
                patch(
                    "codev_workflow.git_ops.subprocess.run",
                    return_value=SimpleNamespace(returncode=0, stdout="Jane Dev\n"),
                ),
            ):
                identity = git_ops.detect_identity(target=target)
            self.assertEqual("Jane Dev", identity)

    def test_falls_back_to_git_config_when_gh_login_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            responses = iter(
                [
                    SimpleNamespace(returncode=1, stdout=""),
                    SimpleNamespace(returncode=0, stdout="Jane Dev\n"),
                ]
            )
            with (
                patch.object(git_ops, "_gh_executable", return_value="/usr/bin/gh"),
                patch(
                    "codev_workflow.git_ops.subprocess.run",
                    side_effect=lambda *a, **k: next(responses),
                ),
            ):
                identity = git_ops.detect_identity(target=target)
            self.assertEqual("Jane Dev", identity)

    def test_returns_none_when_nothing_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with (
                patch.object(git_ops, "_gh_executable", return_value=None),
                patch(
                    "codev_workflow.git_ops.subprocess.run",
                    return_value=SimpleNamespace(returncode=1, stdout=""),
                ),
            ):
                identity = git_ops.detect_identity(target=target)
            self.assertIsNone(identity)

    def test_never_raises_when_subprocess_fails_outright(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with (
                patch.object(git_ops, "_gh_executable", return_value=None),
                patch(
                    "codev_workflow.git_ops.subprocess.run",
                    side_effect=OSError("no git"),
                ),
            ):
                identity = git_ops.detect_identity(target=target)
            self.assertIsNone(identity)


class HasGithubRemoteTests(unittest.TestCase):
    def test_true_when_repo_view_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with patch.object(
                git_ops, "_run_gh", return_value="https://github.com/o/r"
            ):
                self.assertTrue(git_ops.has_github_remote(target=target))

    def test_false_when_gh_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with patch.object(
                git_ops, "_run_gh", side_effect=git_ops.GitOpsError("no remote")
            ):
                self.assertFalse(git_ops.has_github_remote(target=target))


class FetchIssueTests(unittest.TestCase):
    def test_returns_title_and_url(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            payload = (
                '{"title": "Fix the thing", "url": "https://github.com/o/r/issues/7"}'
            )
            with patch.object(git_ops, "_run_gh", return_value=payload):
                issue = git_ops.fetch_issue(7, target=target)
            self.assertEqual(
                {"title": "Fix the thing", "url": "https://github.com/o/r/issues/7"},
                issue,
            )

    def test_raises_when_gh_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with (
                patch.object(
                    git_ops, "_run_gh", side_effect=git_ops.GitOpsError("not found")
                ),
                self.assertRaises(git_ops.GitOpsError),
            ):
                git_ops.fetch_issue(999, target=target)

    def test_raises_on_malformed_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with (
                patch.object(git_ops, "_run_gh", return_value="not json"),
                self.assertRaises(git_ops.GitOpsError),
            ):
                git_ops.fetch_issue(7, target=target)


class ViewIssueTests(unittest.TestCase):
    def test_returns_full_payload_including_comments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            payload = (
                '{"number": 7, "title": "Fix the thing", '
                '"url": "https://github.com/o/r/issues/7", "state": "OPEN", '
                '"body": "details", "comments": ['
                '{"author": {"login": "alice"}, "body": "looks good", '
                '"createdAt": "2026-01-01T00:00:00Z"}]}'
            )
            with patch.object(git_ops, "_run_gh", return_value=payload) as run_gh:
                issue = git_ops.view_issue(7, target=target)
            command = run_gh.call_args.args[0]
        self.assertEqual(7, issue["number"])
        self.assertEqual(1, len(issue["comments"]))
        self.assertEqual("looks good", issue["comments"][0]["body"])
        self.assertIn("issue", command)
        self.assertIn("view", command)
        self.assertIn("7", command)
        self.assertIn("comments", command[-1])

    def test_raises_when_gh_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with (
                patch.object(
                    git_ops, "_run_gh", side_effect=git_ops.GitOpsError("not found")
                ),
                self.assertRaises(git_ops.GitOpsError),
            ):
                git_ops.view_issue(999, target=target)

    def test_raises_on_malformed_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with (
                patch.object(git_ops, "_run_gh", return_value="not json"),
                self.assertRaises(git_ops.GitOpsError),
            ):
                git_ops.view_issue(7, target=target)


if __name__ == "__main__":
    unittest.main()
