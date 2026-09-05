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
    # With auto-gc off nothing repacks in the background, so a temporary
    # directory's teardown cannot race git still writing into it. That race
    # failed a build on ubuntu/3.11 with "Directory not empty" while every
    # assertion in the test had passed.
    _run(["config", "gc.auto", "0"], cwd=target)
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

    def test_round_and_evidence_does_not_fire_a_second_bookkeeping_commit(
        self,
    ) -> None:
        """ADR-0045, Slice 3: `record_builder`'s round-state write here must
        ride along on the commit `commit()` just made, not fire a second,
        separate `chore(codev-bookkeeping)` commit right after it -- `commit`
        hardcodes `defer=True` for this one internal call specifically
        because of it."""
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
            self.assertEqual(head, git_ops.current_head(target))

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


class MaybeCommitBookkeepingTests(unittest.TestCase):
    """ADR-0045, Slice 3: the shared auto-commit primitive every
    state-mutating `task.py` function routes through."""

    def test_auto_commit_true_commits_everything_dirty_with_the_mandatory_prefix(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            (target / ".codev" / "task" / "item-1").mkdir(parents=True)
            (target / ".codev" / "task" / "item-1" / "round-state.json").write_text(
                "{}\n", encoding="utf-8"
            )
            head = git_ops._maybe_commit_bookkeeping(
                "item-1", target=target, defer=False
            )
            self.assertIsNotNone(head)
            self.assertNotEqual(base, head)
            self.assertEqual(head, git_ops.current_head(target))
            message = _run_capture(["log", "-1", "--pretty=%B"], cwd=target)
        self.assertTrue(message.startswith("chore(codev-bookkeeping): "))

    def test_auto_commit_false_is_a_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            config.set_value("git.auto_commit", "false", target=target)
            (target / ".codev" / "task" / "item-1").mkdir(parents=True)
            (target / ".codev" / "task" / "item-1" / "round-state.json").write_text(
                "{}\n", encoding="utf-8"
            )
            result = git_ops._maybe_commit_bookkeeping(
                "item-1", target=target, defer=False
            )
            self.assertIsNone(result)
            self.assertEqual(base, git_ops.current_head(target))

    def test_defer_true_never_commits_regardless_of_the_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            # auto_commit stays at its default (true): defer must win anyway.
            (target / ".codev" / "task" / "item-1").mkdir(parents=True)
            (target / ".codev" / "task" / "item-1" / "round-state.json").write_text(
                "{}\n", encoding="utf-8"
            )
            result = git_ops._maybe_commit_bookkeeping(
                "item-1", target=target, defer=True
            )
            self.assertIsNone(result)
            self.assertEqual(base, git_ops.current_head(target))

    def test_dirty_path_outside_this_tasks_own_directory_is_a_no_op(self) -> None:
        """Found live: an editable install picks up in-progress source edits
        immediately, so a builder-round recording auto-fired mid-implementation
        and swept real feature code into a commit labelled
        chore(codev-bookkeeping) alongside the actual bookkeeping write. Only
        ever commit when every dirty path is confined to this task's own
        directory; anything else dirty means a human or agent is mid-edit."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            (target / ".codev" / "task" / "item-1").mkdir(parents=True)
            (target / ".codev" / "task" / "item-1" / "round-state.json").write_text(
                "{}\n", encoding="utf-8"
            )
            (target / "unrelated_feature.py").write_text(
                "value = 1\n", encoding="utf-8"
            )
            result = git_ops._maybe_commit_bookkeeping(
                "item-1", target=target, defer=False
            )
            self.assertIsNone(result)
            self.assertEqual(base, git_ops.current_head(target))
            status = _run_capture(["status", "--porcelain", "-uall"], cwd=target)
        self.assertIn("unrelated_feature.py", status)
        self.assertIn("round-state.json", status)

    def test_nothing_dirty_is_a_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            result = git_ops._maybe_commit_bookkeeping(
                "item-1", target=target, defer=False
            )
            self.assertIsNone(result)
            self.assertEqual(base, git_ops.current_head(target))

    def test_not_a_git_repository_is_a_no_op_not_an_error(self) -> None:
        """`task.py`'s own bare-tempdir tests must keep passing unmodified --
        this is a best-effort convenience on top of an already-durable write,
        not a new hard requirement those callers must now satisfy."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / "state.json").write_text("{}\n", encoding="utf-8")
            result = git_ops._maybe_commit_bookkeeping(
                "item-1", target=target, defer=False
            )
        self.assertIsNone(result)

    def test_mixed_managed_and_product_dirty_paths_is_a_no_op_not_a_raise(
        self,
    ) -> None:
        """Neither path here is under this task's own directory at all, so
        the task-directory scoping check above short-circuits first: this is
        a no-op, the same as any other unrelated dirty content, not a raise.
        `_refuse_if_mixed_dirty_paths` keeps its own teeth fully intact for
        its original caller, `codev git commit` -- an explicit, human/agent-
        invoked command that always attempts to stage and commit everything
        dirty and so must surface this loudly. This automatic, best-effort
        path never even attempts to stage in this situation, so there is
        nothing here for it to raise about."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            _write_lock(target, [".codev/for-ai/ai-agent-guidelines.md"])
            (target / ".codev" / "for-ai").mkdir(parents=True, exist_ok=True)
            (target / ".codev" / "for-ai" / "ai-agent-guidelines.md").write_text(
                "updated\n", encoding="utf-8"
            )
            (target / "product.py").write_text("code\n", encoding="utf-8")
            result = git_ops._maybe_commit_bookkeeping(
                "item-1", target=target, defer=False
            )
            self.assertIsNone(result)
            self.assertEqual(base, git_ops.current_head(target))


class TaskFunctionAutoCommitTests(unittest.TestCase):
    """ADR-0045, Slice 3, end-to-end: two of the seven now-wired `task.py`
    functions, exercised against a real repository -- where the equivalent
    tests in test_task.py only ever check the state file's own content,
    against a bare, non-git temporary directory."""

    def test_waive_review_auto_commits_the_state_write_when_auto_commit_is_true(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            task.start("item-1", base, target=target)
            git_ops.create_branch("item-1", base, target=target)
            path = task.waive_review(
                "item-1", "solo maintainer", target=target, by="@alice"
            )
            head = git_ops.current_head(target)
            message = _run_capture(["log", "-1", "--pretty=%B"], cwd=target)
            committed = _run_capture(
                ["show", f"{head}:.codev/task/item-1/round-state.json"], cwd=target
            )
            # The file write itself, same as today's test_task.py coverage.
            self.assertIn("solo maintainer", path.read_text(encoding="utf-8"))
        # Now also actually committed, under the mandatory prefix.
        self.assertNotEqual(base, head)
        self.assertTrue(message.startswith("chore(codev-bookkeeping): "))
        self.assertIn("solo maintainer", committed)
        self.assertIn("@alice", committed)

    def test_close_auto_commits_the_state_write_when_auto_commit_is_true(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            task.start("item-1", base, target=target)
            git_ops.create_branch("item-1", base, target=target)
            task.close("item-1", "approved", target=target)
            head = git_ops.current_head(target)
            message = _run_capture(["log", "-1", "--pretty=%B"], cwd=target)
            committed = _run_capture(
                ["show", f"{head}:.codev/task/item-1/round-state.json"], cwd=target
            )
            # The file write itself, same as today's test_task.py coverage.
            self.assertEqual(
                "closed", task.describe("item-1", target=target)["status"]
            )
        # Now also actually committed, under the mandatory prefix.
        self.assertNotEqual(base, head)
        self.assertTrue(message.startswith("chore(codev-bookkeeping): "))
        self.assertIn('"status": "closed"', committed)
        self.assertIn('"outcome": "approved"', committed)


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
            _run(["config", "gc.auto", "0"], cwd=origin)
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
            _run(["config", "gc.auto", "0"], cwd=origin)
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


class SliceBranchTests(unittest.TestCase):
    """ADR-0035: a slice owns its branch and one pull request."""

    def test_a_one_slice_task_keeps_the_branch_name_it_always_had(self) -> None:
        self.assertEqual("codev/auth", git_ops.branch_name_for_slice("auth", "auth"))

    def test_a_slice_branch_uses_a_flat_separator_not_a_path_segment(self) -> None:
        """git stores refs as files, so codev/auth and codev/auth/schema
        cannot coexist -- which would break the one-slice-then-many case."""
        self.assertEqual(
            "codev/auth--schema", git_ops.branch_name_for_slice("auth", "schema")
        )

    def test_a_declared_stack_produces_one_branch_per_slice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            task.start(
                "feat", base, target=target, link_ref="x", slices=["a", "b", "c"]
            )
            git_ops.create_branch("feat", base, target=target)
            (target / "one.py").write_text("x = 1\n", encoding="utf-8")
            first = git_ops.commit("feat", "slice a", target=target)

            task.advance_slice("feat", first, target=target)
            second_branch = git_ops.start_slice_branch("feat", "b", target=target)
            recorded = git_ops.slice_branches("feat", target=target)

        self.assertEqual("codev/feat--b", second_branch)
        self.assertEqual({"a", "b"}, set(recorded))
        # The second slice is cut from where the first currently sits, not
        # from the trunk -- that is what makes a stack a stack.
        self.assertEqual(first, recorded["b"]["base_snapshot"])

    def test_own_branch_follows_the_slice_being_worked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            task.start("feat", base, target=target, link_ref="x", slices=["a", "b"])
            git_ops.create_branch("feat", base, target=target)
            (target / "one.py").write_text("x = 1\n", encoding="utf-8")
            head = git_ops.commit("feat", "slice a", target=target)
            self.assertEqual("codev/feat--a", git_ops.own_branch("feat", target=target))
            task.advance_slice("feat", head, target=target)
            git_ops.start_slice_branch("feat", "b", target=target)
            self.assertEqual("codev/feat--b", git_ops.own_branch("feat", target=target))

    def test_starting_a_slice_twice_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            task.start("feat", base, target=target, link_ref="x", slices=["a", "b"])
            git_ops.create_branch("feat", base, target=target)
            with self.assertRaises(git_ops.GitOpsError):
                git_ops.start_slice_branch("feat", "a", target=target)

    def test_a_slice_with_no_earlier_branch_has_nothing_to_stack_on(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            task.start("feat", base, target=target, link_ref="x", slices=["a", "b"])
            with self.assertRaises(git_ops.GitOpsError):
                git_ops.start_slice_branch("feat", "b", target=target)


class DirtyPathParsingTests(unittest.TestCase):
    """Regression: porcelain's status field is two columns wide with a
    leading space for a modified-but-unstaged file, and stripping the git
    output ate it -- so the first path lost its first character and every
    prefix check against it silently failed."""

    def test_a_modified_unstaged_dotfile_keeps_its_leading_dot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            _init_repo(target)
            tracked = target / ".codev" / "task" / "x" / "round-state.json"
            tracked.parent.mkdir(parents=True)
            tracked.write_text("{}\n", encoding="utf-8")
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
                    "add",
                ],
                cwd=target,
                check=True,
            )
            tracked.write_text('{"changed": true}\n', encoding="utf-8")
            dirty = git_ops._dirty_paths(target)
            product = git_ops._dirty_product_paths(target)
        self.assertEqual([".codev/task/x/round-state.json"], dirty)
        # ...and therefore it is excluded as the task's own bookkeeping.
        self.assertEqual([], product)


class SliceSizeTests(unittest.TestCase):
    """ADR-0035, slice D4: the budget bounds one reviewer's reading, and a
    reviewer reads one pull request -- so it applies per slice."""

    def test_slice_and_task_size_agree_before_any_slice_advances(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            task.start("item-1", base, target=target, link_ref="x")
            git_ops.create_branch("item-1", base, target=target)
            (target / "a.py").write_text("x = 1\n", encoding="utf-8")
            git_ops.commit("item-1", "first slice", target=target)
            self.assertEqual(
                git_ops.task_size("item-1", target=target).lines_changed,
                git_ops.slice_size("item-1", target=target).lines_changed,
            )

    def test_advancing_narrows_the_slice_measurement_but_not_the_total(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            task.start("item-1", base, target=target, link_ref="x", slices=["a", "b"])
            git_ops.create_branch("item-1", base, target=target)
            (target / "a.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
            first_head = git_ops.commit("item-1", "slice a", target=target)
            task.advance_slice("item-1", first_head, target=target)
            (target / "b.py").write_text("z = 3\n", encoding="utf-8")
            git_ops.commit("item-1", "slice b", target=target)

            sliced = git_ops.slice_size("item-1", target=target)
            total = git_ops.task_size("item-1", target=target)
        # The second slice added one file; the task has landed two.
        self.assertEqual(1, sliced.files_changed)
        self.assertEqual(2, total.files_changed)
        self.assertLess(sliced.lines_changed, total.lines_changed)

    def test_slice_size_falls_back_to_the_task_without_round_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            (target / "a.py").write_text("x = 1\n", encoding="utf-8")
            git_ops.commit("item-1", "no round state", target=target)
            self.assertEqual(
                git_ops.task_size("item-1", target=target),
                git_ops.slice_size("item-1", target=target),
            )


class ClosingLineFromSliceListTests(unittest.TestCase):
    """ADR-0035, slice D2: the issue belongs to the task, so only the task's
    final slice closes it. The sibling-stack form (ADR-0034) still counts."""

    def test_a_single_slice_task_closes_its_issue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            task.start("item-1", base, target=target, link_ref="x")
            self.assertEqual(
                "Closes #7",
                git_ops._closing_line(7, task_id="item-1", target=target),
            )

    def test_a_task_with_a_later_slice_only_says_part_of(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            task.start("item-1", base, target=target, link_ref="x", slices=["a", "b"])
            self.assertEqual(
                "Part of #7",
                git_ops._closing_line(7, task_id="item-1", target=target),
            )

    def test_the_final_slice_of_a_sliced_task_closes_it(self) -> None:
        """Advancing onto the last slice is what earns the closing line."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            task.start("item-1", base, target=target, link_ref="x", slices=["a", "b"])
            task.advance_slice("item-1", base, target=target)
            self.assertEqual(
                "Closes #7",
                git_ops._closing_line(7, task_id="item-1", target=target),
            )

    def test_a_task_with_no_round_state_still_falls_back_to_closes(self) -> None:
        """Unreadable round state means "cannot tell", never an exception --
        this backs pull-request body text."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            _init_repo(target)
            self.assertEqual(
                "Closes #7",
                git_ops._closing_line(7, task_id="never-started", target=target),
            )


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
            self.assertEqual(600, size.max_lines)
            self.assertEqual(12, size.max_files)
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
            self.assertEqual(12, size.max_files)


class PushTests(unittest.TestCase):
    def test_push_sends_the_own_branch_to_origin(self) -> None:
        with (
            tempfile.TemporaryDirectory() as origin_dir,
            tempfile.TemporaryDirectory() as work_dir,
        ):
            origin = Path(origin_dir)
            target = Path(work_dir)
            _run(["init", "--bare", "-b", "main"], cwd=origin)
            _run(["config", "gc.auto", "0"], cwd=origin)
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
            _run(["config", "gc.auto", "0"], cwd=origin)
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
        """One task, two slices -- the only stacking form (ADR-0039)."""
        base = _init_repo(target)
        task.start("item-1", base, target=target, slices=["a", "b"])
        git_ops.create_branch("item-1", base, target=target)
        head = git_ops.current_head(target)
        task.advance_slice("item-1", head, target=target)
        git_ops.start_slice_branch("item-1", "b", target=target)
        task.record_reviewer(
            "item-1", 2, head, [], {}, "READY_FOR_OUTER_LOOP", target=target
        )

    @staticmethod
    def _fake_gh_with_parent_pr_state(state: str) -> Callable[..., str]:
        def fake(args: list[str], *, cwd: Path) -> str:
            if args[:2] == ["pr", "view"]:
                branch = args[2]
                if "state" in args:
                    # The predecessor slice's branch carries the state under
                    # test; the child's own branch must look un-opened.
                    return state if branch == "codev/item-1--a" else "MERGED"
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
                git_ops.open_pr("item-1", "title", "body", target=target)
            create_call = next(
                call
                for call in run_gh.call_args_list
                if call.args[0][:2] == ["pr", "create"]
            )
        self.assertIn("codev/item-1--a", create_call.args[0])

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
                git_ops.open_pr("item-1", "title", "body", target=target, base="main")
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
                "item-1",
                1,
                base,
                [],
                {},
                "READY_FOR_OUTER_LOOP",
                target=target,
                defer=True,
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
    """ADR-0039: restack cascades across a task's own slices."""

    def _three_slice_stack(self, target: Path) -> str:
        base = _init_repo(target)
        task.start("feat", base, target=target, slices=["a", "b", "c"])
        git_ops.create_branch("feat", base, target=target)
        (target / "a.py").write_text("a = 1\n", encoding="utf-8")
        head = git_ops.commit("feat", "slice a", target=target)
        task.advance_slice("feat", head, target=target)
        git_ops.start_slice_branch("feat", "b", target=target)
        (target / "b.py").write_text("b = 1\n", encoding="utf-8")
        head = git_ops.commit("feat", "slice b", target=target)
        task.advance_slice("feat", head, target=target)
        git_ops.start_slice_branch("feat", "c", target=target)
        (target / "c.py").write_text("c = 1\n", encoding="utf-8")
        git_ops.commit("feat", "slice c", target=target)
        return base

    def test_refuses_when_the_current_slice_has_no_later_slice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._three_slice_stack(target)
            # The stack ends on 'c'; nothing follows it to rebase.
            with self.assertRaises(git_ops.GitOpsError) as caught:
                git_ops.restack("feat", target=target)
            self.assertIn("no later slice", str(caught.exception))

    def test_refuses_once_the_predecessors_pr_has_merged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._three_slice_stack(target)
            state_path = target / ".codev/task/feat/round-state.json"
            state = json.loads(state_path.read_text("utf-8"))
            state["current_slice"] = "a"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            # The cascade checks out each slice, so the worktree must be
            # clean before it starts -- committing the edit is what a real
            # caller would have done.
            _run(["add", "-A"], cwd=target)
            _run(["commit", "-qm", "pin slice"], cwd=target)
            with (
                patch.object(git_ops, "_run_gh", return_value="MERGED"),
                self.assertRaises(git_ops.GitOpsError) as caught,
            ):
                git_ops.restack("feat", target=target)
            self.assertIn("already merged", str(caught.exception))


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


class HeadForCheckTests(unittest.TestCase):
    """Recording a round's outcome is a commit under the task's own
    `.codev/task/<task_id>/` directory, and that commit moves HEAD. Without
    `head_for_check`, `codev task check` compares raw git heads and reports
    the commit that persisted a verdict as drift against the verdict it just
    persisted -- a loop with no exit, since re-recording a round is refused
    and every recovery path is itself a further commit under the same
    directory. These reproduce the exact shape of a deadlock hit live.
    """

    def _open(self, target: Path) -> str:
        base = _init_repo(target)
        task.start("probe", base, target=target, link_ref="local")
        git_ops.create_branch("probe", base, target=target)
        _run(["add", "-A"], cwd=target)
        _run(["commit", "-qm", "open round state"], cwd=target)
        return git_ops.current_head(target)

    def _commit_round_state(self, target: Path, message: str) -> str:
        """A commit touching only this task's round-state.json -- exactly
        the shape `codev git commit`'s recording writes."""
        _run(["add", ".codev/task/probe/round-state.json"], cwd=target)
        _run(["commit", "-qm", message], cwd=target)
        return git_ops.current_head(target)

    def test_a_bookkeeping_commit_does_not_read_as_drift_against_its_own_round(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._open(target)
            (target / "feature.py").write_text("value = 1\n", encoding="utf-8")
            _run(["add", "-A"], cwd=target)
            _run(["commit", "-qm", "code"], cwd=target)
            code_head = git_ops.current_head(target)

            # defer=True: this test controls the commit itself via
            # _commit_round_state below, to reproduce the exact two-step
            # shape (write, then a later separate commit) that produced the
            # deadlock live -- auto-commit firing inline would collapse that
            # into one atomic step and test something else.
            task.record_builder(
                "probe",
                1,
                code_head,
                {"validation": "ran"},
                target=target,
                defer=True,
            )
            recorded_head = self._commit_round_state(target, "record builder round")
            self.assertNotEqual(code_head, recorded_head)

            # The naive current head is the very commit that persisted the
            # round -- exactly what used to report stop_drift.
            self.assertEqual(
                "stop_drift",
                task.check("probe", recorded_head, target=target).reason,
            )

            resolved = git_ops.head_for_check("probe", target=target)
            self.assertEqual(code_head, resolved)
            self.assertNotEqual(
                "stop_drift", task.check("probe", resolved, target=target).reason
            )

    def test_walks_back_through_more_than_one_trailing_bookkeeping_commit(
        self,
    ) -> None:
        """The shape actually hit: the round's own recorded head_snapshot was
        itself one bookkeeping commit away from the true code snapshot,
        because a second bookkeeping commit (recording the round) landed
        after the first (an unrelated note, like a pause/resume record)."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._open(target)
            (target / "feature.py").write_text("value = 1\n", encoding="utf-8")
            _run(["add", "-A"], cwd=target)
            _run(["commit", "-qm", "code"], cwd=target)
            code_head = git_ops.current_head(target)

            # An unrelated bookkeeping commit lands first, before anything is
            # recorded against it -- a work-style change, mid-slice
            # (ADR-0038), the same shape as the pause/resume record that
            # produced this live: a mutation to round-state.json unrelated to
            # recording any round.
            task.set_work_style("probe", None, "pair", target=target)
            unrelated_note = self._commit_round_state(target, "an unrelated note")
            self.assertNotEqual(code_head, unrelated_note)

            # The round is recorded against whatever head was current when it
            # ran -- the bookkeeping commit above, not the code commit -- which
            # is exactly what happened live: a subagent computed `git
            # rev-parse HEAD` only after an earlier bookkeeping commit had
            # already landed, and recorded its round against that.
            task.record_builder(
                "probe",
                1,
                unrelated_note,
                {"validation": "ran"},
                target=target,
                defer=True,
            )
            recorded_head = self._commit_round_state(target, "record builder round")
            self.assertNotEqual(unrelated_note, recorded_head)

            resolved = git_ops.head_for_check("probe", target=target)
            self.assertEqual(unrelated_note, resolved)
            self.assertNotEqual(
                "stop_drift", task.check("probe", resolved, target=target).reason
            )

    def test_a_commit_mixing_bookkeeping_with_product_code_is_genuine_drift(
        self,
    ) -> None:
        """The heuristic must not walk past a commit that also touches
        product code -- that is real drift, not recording overhead."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._open(target)
            (target / "feature.py").write_text("value = 1\n", encoding="utf-8")
            _run(["add", "-A"], cwd=target)
            _run(["commit", "-qm", "code"], cwd=target)
            code_head = git_ops.current_head(target)

            task.record_builder(
                "probe",
                1,
                code_head,
                {"validation": "ran"},
                target=target,
                defer=True,
            )
            self._commit_round_state(target, "record builder round")

            (target / "surprise.py").write_text("value = 2\n", encoding="utf-8")
            _run(["add", "-A"], cwd=target)
            _run(["commit", "-qm", "unrelated product edit"], cwd=target)
            drifted_head = git_ops.current_head(target)

            resolved = git_ops.head_for_check("probe", target=target)
            self.assertEqual(drifted_head, resolved)
            self.assertEqual(
                "stop_drift", task.check("probe", resolved, target=target).reason
            )

    def test_open_pr_succeeds_immediately_after_recording_a_ready_round(
        self,
    ) -> None:
        """The end-to-end path this was actually found through: publish a
        slice whose reviewer round was recorded and then persisted by a
        commit, with nothing else following it."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._open(target)
            (target / "feature.py").write_text("value = 1\n", encoding="utf-8")
            _run(["add", "-A"], cwd=target)
            _run(["commit", "-qm", "code"], cwd=target)
            code_head = git_ops.current_head(target)

            task.record_reviewer(
                "probe",
                1,
                code_head,
                [],
                {},
                "READY_FOR_OUTER_LOOP",
                target=target,
                defer=True,
            )
            self._commit_round_state(target, "record reviewer round")

            with patch.object(
                git_ops, "_run_gh", side_effect=_gh_no_existing_pr()
            ) as run_gh:
                url = git_ops.open_pr(
                    "probe",
                    "title",
                    "body",
                    target=target,
                    base="main",
                    use_template=False,
                )
            self.assertTrue(url)
            self.assertTrue(run_gh.called)


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
            self.assertTrue(
                body.startswith(task.pr_description("item-1", target=target))
            )
            self.assertIn("I directed this change and I own it", body)
            self.assertIn("not an approval", body)
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
