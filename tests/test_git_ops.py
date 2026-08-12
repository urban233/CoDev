from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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
):
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
            work.start("item-1", base, target=target)
            git_ops.create_branch("item-1", base, target=target)
            work.record_reviewer(
                "item-1", 1, base, [], {}, "READY_FOR_OUTER_LOOP", target=target
            )
            work.reopen(
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
            work.start("item-1", base, target=target)
            git_ops.create_branch("item-1", base, target=target)
            work.record_reviewer(
                "item-1", 1, base, [], {}, "READY_FOR_OUTER_LOOP", target=target
            )
            work.reopen("item-1", base, "recovered into the outer phase", target=target)
            work.record_reviewer(
                "item-1",
                2,
                base,
                [],
                FULL_COVERAGE,
                "READY_FOR_HUMAN_APPROVAL",
                target=target,
            )
            self.assertEqual(
                "ok_approve", work.check("item-1", base, target=target).reason
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
            work.start(
                "item-1",
                base,
                target=target,
                link_ref="https://github.com/o/r/issues/7",
            )
            git_ops.create_branch("item-1", base, target=target)
            work.record_reviewer(
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
        self.assertIn("Closes #7", pr_create_call.args[0][body_index])

    def test_does_not_append_closes_issue_for_a_different_repo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            work.start(
                "item-1",
                base,
                target=target,
                link_ref="https://github.com/other/repo/issues/7",
            )
            git_ops.create_branch("item-1", base, target=target)
            work.record_reviewer(
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
            work.start(
                "item-1",
                base,
                target=target,
                link_ref="docs/codev/work/item-1/implementation-plan.md",
            )
            git_ops.create_branch("item-1", base, target=target)
            work.record_reviewer(
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


if __name__ == "__main__":
    unittest.main()
