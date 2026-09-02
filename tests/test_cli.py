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
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from codev_workflow.cli import (
    _apply_deprecated_aliases,
    _format_benchmark_report,
    _skill_name,
    main,
)
from codev_workflow.git_ops import GitOpsError, TaskSize
from codev_workflow.installer import Resolution
from codev_workflow.task import CheckResult


class CliTests(unittest.TestCase):
    def test_open_pr_uses_template_only_for_automatic_bodies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            body_file = target / "body.md"
            body_file.write_text("from file", encoding="utf-8")
            cases: tuple[tuple[list[str], str, bool], ...] = (
                ([], "generated", True),
                (["--body", "literal"], "literal", False),
                (["--body-file", str(body_file)], "from file", False),
            )
            with (
                patch(
                    "codev_workflow.cli.task_module.pr_description",
                    return_value="generated",
                ),
                patch(
                    "codev_workflow.cli.git_ops_module.open_pr",
                    return_value="https://github.com/o/r/pull/1",
                ) as open_pr,
            ):
                for extra_args, expected_body, expected_template in cases:
                    with self.subTest(extra_args=extra_args):
                        with redirect_stdout(StringIO()):
                            result = main(
                                [
                                    "git",
                                    "open-pr",
                                    "--id",
                                    "item-1",
                                    "--title",
                                    "title",
                                    "--target",
                                    str(target),
                                    *extra_args,
                                ]
                            )
                        self.assertEqual(0, result)
                        self.assertEqual(expected_body, open_pr.call_args.args[2])
                        self.assertEqual(
                            expected_template,
                            open_pr.call_args.kwargs["use_template"],
                        )
                        open_pr.reset_mock()

    def test_git_branch_defaults_base_to_none_and_wires_allow_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with patch(
                "codev_workflow.cli.git_ops_module.create_branch",
                return_value="codev/item-1",
            ) as create_branch:
                output = StringIO()
                with redirect_stdout(output):
                    code = main(
                        [
                            "git",
                            "branch",
                            "--id",
                            "item-1",
                            "--allow-dirty",
                            "--target",
                            str(target),
                        ]
                    )
            self.assertEqual(0, code)
            self.assertIn("Created branch codev/item-1", output.getvalue())
            create_branch.assert_called_once_with(
                "item-1", None, target=target.resolve(), allow_dirty=True, stack_on=None
            )

    def test_git_branch_passes_explicit_base_through(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with (
                patch(
                    "codev_workflow.cli.git_ops_module.create_branch",
                    return_value="codev/item-1",
                ) as create_branch,
                redirect_stdout(StringIO()),
            ):
                main(
                    [
                        "git",
                        "branch",
                        "--id",
                        "item-1",
                        "--base",
                        "develop",
                        "--target",
                        str(target),
                    ]
                )
            create_branch.assert_called_once_with(
                "item-1",
                "develop",
                target=target.resolve(),
                allow_dirty=False,
                stack_on=None,
            )

    def test_git_commit_and_open_pr_print_the_running_size(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with (
                patch(
                    "codev_workflow.cli.git_ops_module.commit", return_value="head-sha"
                ),
                patch(
                    "codev_workflow.cli.git_ops_module.open_pr",
                    return_value="https://github.com/o/r/pull/1",
                ),
                patch(
                    "codev_workflow.cli.task_module.pr_description",
                    return_value="generated",
                ),
                patch(
                    "codev_workflow.cli.git_ops_module.task_size",
                    return_value=TaskSize(410, 3, 400, 8),
                ),
            ):
                commit_output = StringIO()
                with redirect_stdout(commit_output):
                    main(
                        [
                            "git",
                            "commit",
                            "--id",
                            "item-1",
                            "--message",
                            "msg",
                            "--target",
                            str(target),
                        ]
                    )
                open_pr_output = StringIO()
                with redirect_stdout(open_pr_output):
                    main(
                        [
                            "git",
                            "open-pr",
                            "--id",
                            "item-1",
                            "--title",
                            "title",
                            "--target",
                            str(target),
                        ]
                    )
            for output in (commit_output.getvalue(), open_pr_output.getvalue()):
                self.assertIn("Size: 410 line(s)", output)
                self.assertIn("over budget", output)

    def test_size_report_failure_never_blocks_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with (
                patch(
                    "codev_workflow.cli.git_ops_module.commit", return_value="head-sha"
                ),
                patch(
                    "codev_workflow.cli.git_ops_module.task_size",
                    side_effect=GitOpsError("boom"),
                ),
            ):
                output = StringIO()
                with redirect_stdout(output):
                    code = main(
                        [
                            "git",
                            "commit",
                            "--id",
                            "item-1",
                            "--message",
                            "msg",
                            "--target",
                            str(target),
                        ]
                    )
            self.assertEqual(0, code)
            self.assertIn("Committed head-sha", output.getvalue())
            self.assertNotIn("Size:", output.getvalue())

    def test_init_check_diff_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(
                    0,
                    main(
                        [
                            "init",
                            "--target",
                            str(target),
                            "--agent-platform",
                            "opencode",
                        ]
                    ),
                )
                self.assertEqual(0, main(["check", "--target", str(target)]))
                self.assertEqual(0, main(["diff", "--target", str(target)]))

    def test_missing_install_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            errors = StringIO()
            with redirect_stderr(errors):
                code = main(["check", "--target", directory])
            self.assertEqual(2, code)
            self.assertIn("not installed", errors.getvalue())

    def test_remove_dry_run_and_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                self.assertEqual(
                    0,
                    main(
                        [
                            "init",
                            "--target",
                            str(target),
                            "--agent-platform",
                            "opencode",
                        ]
                    ),
                )
                self.assertEqual(
                    0, main(["remove", "--target", str(target), "--dry-run"])
                )
                self.assertTrue((target / ".codev" / "lock.json").exists())
                self.assertEqual(0, main(["remove", "--target", str(target)]))
                self.assertFalse((target / ".codev" / "lock.json").exists())

    def test_update_can_add_a_platform_to_an_existing_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                self.assertEqual(
                    0,
                    main(
                        [
                            "init",
                            "--target",
                            str(target),
                            "--agent-platform",
                            "opencode",
                        ]
                    ),
                )
                self.assertEqual(
                    0,
                    main(
                        [
                            "update",
                            "--target",
                            str(target),
                            "--agent-platform",
                            "antigravity",
                        ]
                    ),
                )
            self.assertTrue((target / ".agents/agents/assistant.md").is_file())
            self.assertTrue(
                (target / ".agents/skills/review-change/SKILL.md").is_file()
            )
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(0, main(["check", "--target", str(target)]))

    def test_programming_language_flag_selects_audit_skill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                self.assertEqual(
                    0,
                    main(
                        [
                            "init",
                            "--target",
                            str(target),
                            "--agent-platform",
                            "opencode",
                            "--programming-language",
                            "typescript",
                        ]
                    ),
                )

            self.assertFalse(
                (target / ".agents/skills/audit-google-python-style").exists()
            )
            self.assertTrue(
                (
                    target / ".agents/skills/audit-google-typescript-style/SKILL.md"
                ).is_file()
            )

    def test_init_without_programming_language_installs_no_audit_skills(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                self.assertEqual(
                    0,
                    main(
                        [
                            "init",
                            "--target",
                            str(target),
                            "--agent-platform",
                            "opencode",
                        ]
                    ),
                )

            self.assertFalse(
                (target / ".agents/skills/audit-google-python-style").exists()
            )
            self.assertFalse(
                (target / ".agents/skills/audit-google-typescript-style").exists()
            )
            audit_agent = (target / ".opencode" / "agents" / "code-audit.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("language-agnostic", audit_agent)
            self.assertNotIn("audit-google-python-style", audit_agent)
            self.assertNotIn("audit-google-typescript-style", audit_agent)

    def _make_update_conflict(self, target: Path) -> tuple[str, bytes]:
        """init, then arrange exactly one conflict for the next `update`:
        `.opencode/agents/code-audit.md` both changes upstream (via a patched
        `installer._bundle_files`, left active on the test) and picks up a
        local edit."""
        with redirect_stdout(StringIO()):
            self.assertEqual(
                0,
                main(["init", "--target", str(target), "--agent-platform", "opencode"]),
            )
        from codev_workflow import installer as installer_module

        relative = ".opencode/agents/code-audit.md"
        current_bundle = installer_module._bundle_files(("opencode",))
        changed_bundle = dict(current_bundle)
        upstream = current_bundle[relative] + b"\n# upstream change\n"
        changed_bundle[relative] = upstream
        destination = target / Path(relative)
        destination.write_bytes(destination.read_bytes() + b"\n# local edit\n")
        patcher = patch.object(
            installer_module, "_bundle_files", return_value=changed_bundle
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return relative, upstream

    def test_update_aborts_on_conflict_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._make_update_conflict(target)
            with redirect_stdout(StringIO()) as out:
                code = main(["update", "--target", str(target)])
            self.assertEqual(2, code)
            self.assertIn("conflict", out.getvalue().lower())

    def test_update_on_conflict_keep_resolves_and_applies_the_rest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            relative, _upstream = self._make_update_conflict(target)
            local_before = (target / Path(relative)).read_bytes()
            with redirect_stdout(StringIO()):
                code = main(
                    [
                        "update",
                        "--target",
                        str(target),
                        "--on-conflict",
                        "keep",
                    ]
                )
            self.assertEqual(0, code)
            self.assertEqual(local_before, (target / Path(relative)).read_bytes())
            with redirect_stdout(StringIO()):
                self.assertEqual(0, main(["diff", "--target", str(target)]))

    def test_update_on_conflict_override_adopts_upstream(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            relative, upstream = self._make_update_conflict(target)
            with redirect_stdout(StringIO()):
                code = main(
                    [
                        "update",
                        "--target",
                        str(target),
                        "--on-conflict",
                        "override",
                    ]
                )
            self.assertEqual(0, code)
            self.assertEqual(upstream, (target / Path(relative)).read_bytes())

    def test_update_resolve_and_on_conflict_together_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._make_update_conflict(target)
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()) as err:
                code = main(
                    [
                        "update",
                        "--target",
                        str(target),
                        "--resolve",
                        "--on-conflict",
                        "keep",
                    ]
                )
            self.assertEqual(2, code)
            self.assertIn("either --resolve or --on-conflict", err.getvalue())

    def test_update_resolve_flag_runs_the_wizard_and_applies_its_choices(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            relative, upstream = self._make_update_conflict(target)
            with (
                redirect_stdout(StringIO()),
                patch(
                    "codev_workflow.cli.run_wizard",
                    return_value={relative: Resolution.OVERRIDE},
                ) as wizard,
            ):
                code = main(["update", "--target", str(target), "--resolve"])
            self.assertEqual(0, code)
            wizard.assert_called_once()
            self.assertEqual(upstream, (target / Path(relative)).read_bytes())

    def test_task_lifecycle_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            findings_path = target / "findings.json"
            findings_path.write_text(
                json.dumps(
                    [
                        {
                            "id": "f1",
                            "location": "a.py:1",
                            "category": "correctness",
                            "blocking": True,
                            "rank": 1,
                            "summary": "off-by-one",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            evidence_path = target / "evidence.json"
            evidence_path.write_text(
                json.dumps({"delivered": "fixed the off-by-one"}), encoding="utf-8"
            )

            with redirect_stdout(StringIO()):
                self.assertEqual(
                    0,
                    main(
                        [
                            "task",
                            "start",
                            "--id",
                            "item-1",
                            "--base",
                            "base-sha",
                            "--owner",
                            "test-owner",
                            "--target",
                            str(target),
                        ]
                    ),
                )
                self.assertEqual(
                    0,
                    main(
                        [
                            "task",
                            "record",
                            "--id",
                            "item-1",
                            "--round",
                            "1",
                            "--role",
                            "reviewer",
                            "--head",
                            "base-sha",
                            "--findings",
                            str(findings_path),
                            "--decision",
                            "CHANGES_REQUIRED",
                            "--target",
                            str(target),
                        ]
                    ),
                )
                self.assertEqual(
                    0,
                    main(
                        [
                            "task",
                            "check",
                            "--id",
                            "item-1",
                            "--head",
                            "base-sha",
                            "--target",
                            str(target),
                        ]
                    ),
                )
                self.assertEqual(
                    0,
                    main(
                        [
                            "task",
                            "record",
                            "--id",
                            "item-1",
                            "--round",
                            "2",
                            "--role",
                            "builder",
                            "--head",
                            "head-2",
                            "--evidence",
                            str(evidence_path),
                            "--target",
                            str(target),
                        ]
                    ),
                )
                self.assertEqual(
                    0,
                    main(["task", "status", "--id", "item-1", "--target", str(target)]),
                )
                self.assertEqual(
                    0, main(["task", "log", "--id", "item-1", "--target", str(target)])
                )
                self.assertEqual(
                    0,
                    main(
                        [
                            "task",
                            "close",
                            "--id",
                            "item-1",
                            "--outcome",
                            "escalated",
                            "--target",
                            str(target),
                        ]
                    ),
                )

    def test_task_record_reviewer_accepts_specialist_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            empty_findings_path = target / "empty-findings.json"
            empty_findings_path.write_text("[]", encoding="utf-8")
            empty_evidence_path = target / "empty-evidence.json"
            empty_evidence_path.write_text("{}", encoding="utf-8")
            selection_path = target / "selection.json"
            selection_path.write_text(
                json.dumps({"specialists": ["rollout-specialist"]}),
                encoding="utf-8",
            )
            with redirect_stdout(StringIO()):
                main(
                    [
                        "task",
                        "start",
                        "--id",
                        "item-1",
                        "--base",
                        "base-sha",
                        "--target",
                        str(target),
                    ]
                )
                main(
                    [
                        "task",
                        "record",
                        "--id",
                        "item-1",
                        "--round",
                        "1",
                        "--role",
                        "reviewer",
                        "--head",
                        "base-sha",
                        "--findings",
                        str(empty_findings_path),
                        "--decision",
                        "READY_FOR_OUTER_LOOP",
                        "--target",
                        str(target),
                    ]
                )
                main(
                    [
                        "task",
                        "record",
                        "--id",
                        "item-1",
                        "--round",
                        "2",
                        "--role",
                        "builder",
                        "--head",
                        "head-2",
                        "--evidence",
                        str(empty_evidence_path),
                        "--target",
                        str(target),
                    ]
                )
                self.assertEqual(
                    0,
                    main(
                        [
                            "task",
                            "record",
                            "--id",
                            "item-1",
                            "--round",
                            "2",
                            "--role",
                            "reviewer",
                            "--head",
                            "head-2",
                            "--findings",
                            str(empty_findings_path),
                            "--selection",
                            str(selection_path),
                            "--decision",
                            "READY_FOR_HUMAN_APPROVAL",
                            "--target",
                            str(target),
                        ]
                    ),
                )
                log = StringIO()
                with redirect_stdout(log):
                    main(["task", "log", "--id", "item-1", "--target", str(target)])
        self.assertIn("specialists: rollout-specialist", log.getvalue())

    def test_task_reopen_after_close_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                self.assertEqual(
                    0,
                    main(
                        [
                            "task",
                            "start",
                            "--id",
                            "item-1",
                            "--base",
                            "base-sha",
                            "--target",
                            str(target),
                        ]
                    ),
                )
                self.assertEqual(
                    0,
                    main(
                        [
                            "task",
                            "close",
                            "--id",
                            "item-1",
                            "--outcome",
                            "escalated",
                            "--target",
                            str(target),
                        ]
                    ),
                )

            errors = StringIO()
            with redirect_stderr(errors):
                code = main(
                    [
                        "task",
                        "start",
                        "--id",
                        "item-1",
                        "--base",
                        "base-sha",
                        "--target",
                        str(target),
                    ]
                )
            self.assertEqual(2, code)
            self.assertIn("codev task reopen", errors.getvalue())

            out = StringIO()
            with redirect_stdout(out):
                self.assertEqual(
                    0,
                    main(
                        [
                            "task",
                            "reopen",
                            "--id",
                            "item-1",
                            "--head",
                            "new-head",
                            "--reason",
                            "human approved continuing after escalation",
                            "--by",
                            "octocat",
                            "--target",
                            str(target),
                        ]
                    ),
                )
                self.assertEqual(
                    0,
                    main(
                        [
                            "task",
                            "check",
                            "--id",
                            "item-1",
                            "--head",
                            "new-head",
                            "--target",
                            str(target),
                        ]
                    ),
                )
            self.assertIn("Reopened task item-1", out.getvalue())

    def test_task_start_github_issue_populates_link_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            issue = {"title": "Fix the thing", "url": "https://github.com/o/r/issues/7"}
            with (
                patch(
                    "codev_workflow.cli.git_ops_module.fetch_issue", return_value=issue
                ) as fetch_issue,
                patch(
                    "codev_workflow.cli.git_ops_module.detect_identity",
                    return_value=None,
                ),
                redirect_stdout(StringIO()),
            ):
                code = main(
                    [
                        "task",
                        "start",
                        "--id",
                        "item-1",
                        "--base",
                        "base-sha",
                        "--github-issue",
                        "7",
                        "--target",
                        str(target),
                    ]
                )
            self.assertEqual(0, code)
            fetch_issue.assert_called_once_with(7, target=target.resolve())
            state_path = target / ".codev" / "task" / "item-1" / "round-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual("https://github.com/o/r/issues/7", state["link_ref"])
            self.assertEqual("Fix the thing", state["summary"])

    def test_task_start_explicit_summary_wins_over_github_issue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            issue = {"title": "Issue title", "url": "https://github.com/o/r/issues/7"}
            with (
                patch(
                    "codev_workflow.cli.git_ops_module.fetch_issue", return_value=issue
                ),
                patch(
                    "codev_workflow.cli.git_ops_module.detect_identity",
                    return_value=None,
                ),
                redirect_stdout(StringIO()),
            ):
                main(
                    [
                        "task",
                        "start",
                        "--id",
                        "item-1",
                        "--base",
                        "base-sha",
                        "--github-issue",
                        "7",
                        "--summary",
                        "My own summary",
                        "--target",
                        str(target),
                    ]
                )
            state_path = target / ".codev" / "task" / "item-1" / "round-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual("My own summary", state["summary"])

    def test_task_start_owner_defaults_to_detected_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with (
                patch(
                    "codev_workflow.cli.git_ops_module.detect_identity",
                    return_value="octocat",
                ) as detect_identity,
                redirect_stdout(StringIO()),
            ):
                main(
                    [
                        "task",
                        "start",
                        "--id",
                        "item-1",
                        "--base",
                        "base-sha",
                        "--target",
                        str(target),
                    ]
                )
            detect_identity.assert_called_once_with(target=target.resolve())
            state_path = target / ".codev" / "task" / "item-1" / "round-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual("octocat", state["owner"])

    def test_task_start_entry_takeover_stays_in_inner_phase(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with (
                patch(
                    "codev_workflow.cli.git_ops_module.detect_identity",
                    return_value=None,
                ),
                redirect_stdout(StringIO()),
            ):
                code = main(
                    [
                        "task",
                        "start",
                        "--id",
                        "item-1",
                        "--base",
                        "base-sha",
                        "--entry",
                        "takeover",
                        "--target",
                        str(target),
                    ]
                )
            self.assertEqual(0, code)
            state_path = target / ".codev" / "task" / "item-1" / "round-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual("takeover", state["entry"])
            self.assertEqual("inner", state["rounds"][0]["phase"])

    def test_task_start_entry_direct_review_opens_outer_phase(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with (
                patch(
                    "codev_workflow.cli.git_ops_module.detect_identity",
                    return_value=None,
                ),
                redirect_stdout(StringIO()),
            ):
                code = main(
                    [
                        "task",
                        "start",
                        "--id",
                        "item-1",
                        "--base",
                        "base-sha",
                        "--entry",
                        "direct-review",
                        "--target",
                        str(target),
                    ]
                )
            self.assertEqual(0, code)
            state_path = target / ".codev" / "task" / "item-1" / "round-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual("direct-review", state["entry"])
            self.assertEqual("outer", state["rounds"][0]["phase"])

    def test_task_start_rejects_unknown_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                main(
                    [
                        "task",
                        "start",
                        "--id",
                        "item-1",
                        "--base",
                        "base-sha",
                        "--entry",
                        "bogus",
                        "--target",
                        str(target),
                    ]
                )

    def test_task_start_refuses_without_issue_linkage_when_repo_has_github(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            errors = StringIO()
            with (
                patch(
                    "codev_workflow.cli.git_ops_module.has_github_remote",
                    return_value=True,
                ),
                redirect_stderr(errors),
            ):
                code = main(
                    [
                        "task",
                        "start",
                        "--id",
                        "item-1",
                        "--base",
                        "base-sha",
                        "--target",
                        str(target),
                    ]
                )
            self.assertEqual(2, code)
            self.assertIn("--no-github-issue", errors.getvalue())
            self.assertFalse(
                (target / ".codev" / "task" / "item-1" / "round-state.json").exists()
            )

    def test_task_start_no_github_issue_flag_bypasses_the_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with (
                patch(
                    "codev_workflow.cli.git_ops_module.has_github_remote",
                    return_value=True,
                ),
                patch(
                    "codev_workflow.cli.git_ops_module.detect_identity",
                    return_value=None,
                ),
                redirect_stdout(StringIO()),
            ):
                code = main(
                    [
                        "task",
                        "start",
                        "--id",
                        "item-1",
                        "--base",
                        "base-sha",
                        "--no-github-issue",
                        "--target",
                        str(target),
                    ]
                )
            self.assertEqual(0, code)

    def test_task_start_link_flag_bypasses_the_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with (
                patch(
                    "codev_workflow.cli.git_ops_module.has_github_remote",
                    return_value=True,
                ),
                patch(
                    "codev_workflow.cli.git_ops_module.detect_identity",
                    return_value=None,
                ),
                redirect_stdout(StringIO()),
            ):
                code = main(
                    [
                        "task",
                        "start",
                        "--id",
                        "item-1",
                        "--base",
                        "base-sha",
                        "--link",
                        "docs/codev/work/item-1/implementation-plan.md",
                        "--target",
                        str(target),
                    ]
                )
            self.assertEqual(0, code)

    def test_task_start_allowed_without_a_gate_check_when_repo_has_no_github(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with (
                patch(
                    "codev_workflow.cli.git_ops_module.has_github_remote",
                    return_value=False,
                ),
                patch(
                    "codev_workflow.cli.git_ops_module.detect_identity",
                    return_value=None,
                ),
                redirect_stdout(StringIO()),
            ):
                code = main(
                    [
                        "task",
                        "start",
                        "--id",
                        "item-1",
                        "--base",
                        "base-sha",
                        "--target",
                        str(target),
                    ]
                )
            self.assertEqual(0, code)

    def test_git_relink_by_github_issue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            issue = {"title": "Fix the thing", "url": "https://github.com/o/r/issues/7"}
            with (
                patch(
                    "codev_workflow.cli.git_ops_module.has_github_remote",
                    return_value=False,
                ),
                patch(
                    "codev_workflow.cli.git_ops_module.detect_identity",
                    return_value=None,
                ),
                redirect_stdout(StringIO()),
            ):
                main(
                    [
                        "task",
                        "start",
                        "--id",
                        "item-1",
                        "--base",
                        "base-sha",
                        "--target",
                        str(target),
                    ]
                )
            with (
                patch(
                    "codev_workflow.cli.git_ops_module.fetch_issue",
                    return_value=issue,
                ) as fetch_issue,
                redirect_stdout(StringIO()) as out,
            ):
                code = main(
                    [
                        "task",
                        "relink",
                        "--id",
                        "item-1",
                        "--github-issue",
                        "7",
                        "--by",
                        "octocat",
                        "--target",
                        str(target),
                    ]
                )
            self.assertEqual(0, code)
            fetch_issue.assert_called_once_with(7, target=target.resolve())
            self.assertIn("Relinked task item-1", out.getvalue())
            state_path = target / ".codev" / "task" / "item-1" / "round-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual("https://github.com/o/r/issues/7", state["link_ref"])
            self.assertEqual(1, len(state["link_ref_updates"]))
            self.assertEqual("octocat", state["link_ref_updates"][0]["by"])

    def test_task_triage_by_defaults_to_detected_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            triage_path = target / "triage.json"
            triage_path.write_text(json.dumps({"dispositions": {}}), encoding="utf-8")
            with (
                patch(
                    "codev_workflow.cli.git_ops_module.detect_identity",
                    return_value="octocat",
                ) as detect_identity,
                patch("codev_workflow.cli.task_module.record_triage") as record_triage,
                redirect_stdout(StringIO()),
            ):
                main(
                    [
                        "task",
                        "triage",
                        "--id",
                        "item-1",
                        "--round",
                        "2",
                        "--triage",
                        str(triage_path),
                        "--target",
                        str(target),
                    ]
                )
            detect_identity.assert_called_once_with(target=target.resolve())
            record_triage.assert_called_once_with(
                "item-1",
                2,
                {"dispositions": {}},
                target=target.resolve(),
                by="octocat",
            )

    def test_task_triage_explicit_by_skips_detection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            triage_path = target / "triage.json"
            triage_path.write_text(json.dumps({"dispositions": {}}), encoding="utf-8")
            with (
                patch(
                    "codev_workflow.cli.git_ops_module.detect_identity"
                ) as detect_identity,
                patch("codev_workflow.cli.task_module.record_triage") as record_triage,
                redirect_stdout(StringIO()),
            ):
                main(
                    [
                        "task",
                        "triage",
                        "--id",
                        "item-1",
                        "--round",
                        "2",
                        "--triage",
                        str(triage_path),
                        "--by",
                        "explicit-triager",
                        "--target",
                        str(target),
                    ]
                )
            detect_identity.assert_not_called()
            record_triage.assert_called_once_with(
                "item-1",
                2,
                {"dispositions": {}},
                target=target.resolve(),
                by="explicit-triager",
            )

    def test_task_check_prints_triage_note(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with (
                patch(
                    "codev_workflow.cli.task_module.check",
                    return_value=CheckResult(True, "ok_continue", "proceed"),
                ),
                patch(
                    "codev_workflow.cli.task_module.triage_note",
                    return_value=(
                        "note: octocat both owns this task and triaged this round"
                    ),
                ),
            ):
                output = StringIO()
                with redirect_stdout(output):
                    code = main(
                        [
                            "task",
                            "check",
                            "--id",
                            "item-1",
                            "--head",
                            "head-sha",
                            "--target",
                            str(target),
                        ]
                    )
            self.assertEqual(0, code)
            self.assertIn("note: octocat", output.getvalue())

    def test_task_check_omits_note_when_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with (
                patch(
                    "codev_workflow.cli.task_module.check",
                    return_value=CheckResult(True, "ok_continue", "proceed"),
                ),
                patch("codev_workflow.cli.task_module.triage_note", return_value=None),
                redirect_stdout(StringIO()) as output,
            ):
                main(
                    [
                        "task",
                        "check",
                        "--id",
                        "item-1",
                        "--head",
                        "head-sha",
                        "--target",
                        str(target),
                    ]
                )
            self.assertNotIn("note:", output.getvalue())

    def test_git_issue_create_prints_codeowners_suggestion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with (
                patch(
                    "codev_workflow.cli.git_ops_module.suggest_owners",
                    return_value=["@pydev"],
                ) as suggest_owners,
                patch(
                    "codev_workflow.cli.git_ops_module.create_issue",
                    return_value="https://github.com/o/r/issues/9",
                ) as create_issue,
                redirect_stdout(StringIO()) as output,
            ):
                code = main(
                    [
                        "git",
                        "issue-create",
                        "--title",
                        "Fix the thing",
                        "--body",
                        "details",
                        "--path",
                        "src/app.py",
                        "--target",
                        str(target),
                    ]
                )
            self.assertEqual(0, code)
            suggest_owners.assert_called_once_with(
                ["src/app.py"], target=target.resolve()
            )
            create_issue.assert_called_once_with(
                "Fix the thing", "details", target=target.resolve(), assignees=[]
            )
            self.assertIn("@pydev", output.getvalue())
            self.assertIn("https://github.com/o/r/issues/9", output.getvalue())

    def test_git_issue_create_forwards_assignees_and_skips_suggestion_lookup(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with (
                patch(
                    "codev_workflow.cli.git_ops_module.suggest_owners"
                ) as suggest_owners,
                patch(
                    "codev_workflow.cli.git_ops_module.create_issue",
                    return_value="https://github.com/o/r/issues/9",
                ) as create_issue,
                redirect_stdout(StringIO()),
            ):
                main(
                    [
                        "git",
                        "issue-create",
                        "--title",
                        "Fix the thing",
                        "--body",
                        "details",
                        "--assignee",
                        "alice",
                        "--target",
                        str(target),
                    ]
                )
            suggest_owners.assert_not_called()
            create_issue.assert_called_once_with(
                "Fix the thing",
                "details",
                target=target.resolve(),
                assignees=["alice"],
            )

    def test_git_issue_create_requires_body_or_body_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            errors = StringIO()
            with redirect_stderr(errors):
                code = main(
                    [
                        "git",
                        "issue-create",
                        "--title",
                        "Fix the thing",
                        "--target",
                        str(target),
                    ]
                )
            self.assertEqual(2, code)
            self.assertIn("--body", errors.getvalue())

    def test_git_issue_view_prints_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            payload = {
                "number": 7,
                "title": "Fix the thing",
                "url": "https://github.com/o/r/issues/7",
                "body": "details",
                "comments": [{"author": {"login": "alice"}, "body": "looks good"}],
            }
            with (
                patch(
                    "codev_workflow.cli.git_ops_module.view_issue",
                    return_value=payload,
                ) as view_issue,
                redirect_stdout(StringIO()) as output,
            ):
                code = main(
                    ["git", "issue-view", "--number", "7", "--target", str(target)]
                )
            self.assertEqual(0, code)
            view_issue.assert_called_once_with(7, target=target.resolve())
            self.assertEqual(payload, json.loads(output.getvalue()))

    def test_git_issue_view_propagates_gh_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            errors = StringIO()
            with (
                patch(
                    "codev_workflow.cli.git_ops_module.view_issue",
                    side_effect=GitOpsError("not found"),
                ),
                redirect_stderr(errors),
            ):
                code = main(
                    ["git", "issue-view", "--number", "999", "--target", str(target)]
                )
            self.assertEqual(2, code)
            self.assertIn("not found", errors.getvalue())

    def test_codeowners_init_writes_and_reports_the_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            output = StringIO()
            with redirect_stdout(output):
                code = main(["codeowners", "init", "--target", str(target)])
            self.assertEqual(0, code)
            self.assertTrue((target / ".github" / "CODEOWNERS").is_file())
            self.assertIn(".github", output.getvalue())
            self.assertIn("CODEOWNERS", output.getvalue())

    def test_codeowners_init_refuses_when_one_already_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / "CODEOWNERS").write_text("* @someone\n", encoding="utf-8")
            errors = StringIO()
            with redirect_stderr(errors):
                code = main(["codeowners", "init", "--target", str(target)])
            self.assertEqual(2, code)
            self.assertIn("already exists", errors.getvalue())

    def test_task_escalate_and_escalations_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                self.assertEqual(
                    0,
                    main(
                        [
                            "task",
                            "escalate",
                            "--id",
                            "item-1",
                            "--trigger",
                            "stop_round_cap",
                            "--cause",
                            "round 2 of 2 for phase 'inner'",
                            "--phase",
                            "inner",
                            "--round",
                            "2",
                            "--target",
                            str(target),
                        ]
                    ),
                )
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    0, main(["task", "escalations", "--target", str(target)])
                )
        self.assertIn("item-1", output.getvalue())
        self.assertIn("stop_round_cap", output.getvalue())

    def test_task_check_repeated_finding_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            finding = [
                {
                    "id": "f1",
                    "location": "a.py:1",
                    "category": "correctness",
                    "blocking": True,
                    "rank": 1,
                    "summary": "off-by-one",
                }
            ]
            findings_path = target / "findings.json"
            findings_path.write_text(json.dumps(finding), encoding="utf-8")
            evidence_path = target / "evidence.json"
            evidence_path.write_text(
                json.dumps({"delivered": "attempted a fix"}), encoding="utf-8"
            )

            with redirect_stdout(StringIO()):
                main(
                    [
                        "task",
                        "start",
                        "--id",
                        "item-1",
                        "--base",
                        "base-sha",
                        "--max-rounds",
                        "5",
                        "--owner",
                        "test-owner",
                        "--target",
                        str(target),
                    ]
                )
                for round_number in (1, 2):
                    if round_number > 1:
                        main(
                            [
                                "task",
                                "record",
                                "--id",
                                "item-1",
                                "--round",
                                str(round_number),
                                "--role",
                                "builder",
                                "--head",
                                "base-sha",
                                "--evidence",
                                str(evidence_path),
                                "--target",
                                str(target),
                            ]
                        )
                    main(
                        [
                            "task",
                            "record",
                            "--id",
                            "item-1",
                            "--round",
                            str(round_number),
                            "--role",
                            "reviewer",
                            "--head",
                            "base-sha",
                            "--findings",
                            str(findings_path),
                            "--decision",
                            "CHANGES_REQUIRED",
                            "--target",
                            str(target),
                        ]
                    )
                errors = StringIO()
                with redirect_stderr(errors):
                    code = main(
                        [
                            "task",
                            "check",
                            "--id",
                            "item-1",
                            "--head",
                            "base-sha",
                            "--target",
                            str(target),
                        ]
                    )
            self.assertEqual(1, code)

    def test_status_reports_bundle_health_adapters_and_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                main(
                    [
                        "init",
                        "--target",
                        str(target),
                        "--agent-platform",
                        "opencode",
                    ]
                )
                main(
                    [
                        "task",
                        "start",
                        "--id",
                        "item-1",
                        "--base",
                        "base-sha",
                        "--owner",
                        "test-owner",
                        "--target",
                        str(target),
                    ]
                )
                output = StringIO()
                with redirect_stdout(output):
                    code = main(["status", "--target", str(target), "--json"])
            self.assertEqual(0, code)
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["healthy"])
            self.assertEqual(["opencode"], payload["adapters"])
            self.assertEqual(1, payload["tasks_in_progress"])
            self.assertNotIn("python_version", payload)

    def test_status_verbose_adds_environment_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                main(["init", "--target", str(target), "--agent-platform", "opencode"])
                output = StringIO()
                with redirect_stdout(output):
                    code = main(
                        ["status", "--target", str(target), "--verbose", "--json"]
                    )
            self.assertEqual(0, code)
            payload = json.loads(output.getvalue())
            self.assertIn("python_version", payload)
            self.assertIn("system", payload)

    def test_status_verbose_reports_owner_wip_and_changed_file_overlaps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                main(["init", "--target", str(target), "--agent-platform", "opencode"])
                main(
                    [
                        "task",
                        "start",
                        "--id",
                        "item-1",
                        "--base",
                        "base-sha",
                        "--owner",
                        "alice",
                        "--target",
                        str(target),
                    ]
                )
                main(
                    [
                        "task",
                        "start",
                        "--id",
                        "item-2",
                        "--base",
                        "base-sha",
                        "--owner",
                        "bob",
                        "--target",
                        str(target),
                    ]
                )
            with patch(
                "codev_workflow.cli.git_ops_module.changed_files",
                side_effect=lambda task_id, target: ["shared.py"],
            ):
                output = StringIO()
                with redirect_stdout(output):
                    code = main(["status", "--target", str(target), "--verbose"])
            self.assertEqual(0, code)
            text = output.getvalue()
            self.assertIn("Work in progress by owner:", text)
            self.assertIn("alice: 1", text)
            self.assertIn("bob: 1", text)
            self.assertIn("Changed-file overlaps", text)
            self.assertIn("item-1 & item-2", text)
            self.assertIn("shared.py", text)

    def test_status_verbose_json_includes_owner_and_overlap_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                main(["init", "--target", str(target), "--agent-platform", "opencode"])
                main(
                    [
                        "task",
                        "start",
                        "--id",
                        "item-1",
                        "--base",
                        "base-sha",
                        "--owner",
                        "alice",
                        "--target",
                        str(target),
                    ]
                )
            with patch(
                "codev_workflow.cli.git_ops_module.changed_files", return_value=[]
            ):
                output = StringIO()
                with redirect_stdout(output):
                    main(["status", "--target", str(target), "--verbose", "--json"])
            payload = json.loads(output.getvalue())
            self.assertEqual({"alice": 1}, payload["tasks_in_progress_by_owner"])
            self.assertEqual([], payload["changed_file_overlaps"])

    def test_status_verbose_reports_task_sizes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                main(["init", "--target", str(target), "--agent-platform", "opencode"])
                main(
                    [
                        "task",
                        "start",
                        "--id",
                        "item-1",
                        "--base",
                        "base-sha",
                        "--owner",
                        "alice",
                        "--target",
                        str(target),
                    ]
                )
            with (
                patch(
                    "codev_workflow.cli.git_ops_module.changed_files", return_value=[]
                ),
                patch(
                    "codev_workflow.cli.git_ops_module.task_size",
                    return_value=TaskSize(450, 3, 400, 8),
                ),
            ):
                output = StringIO()
                with redirect_stdout(output):
                    code = main(["status", "--target", str(target), "--verbose"])
                json_output = StringIO()
                with redirect_stdout(json_output):
                    main(["status", "--target", str(target), "--verbose", "--json"])
            self.assertEqual(0, code)
            text = output.getvalue()
            self.assertIn("Task sizes", text)
            self.assertIn("item-1: 450/400 lines, 3/8 files (over budget)", text)
            payload = json.loads(json_output.getvalue())
            self.assertEqual(
                {
                    "lines_changed": 450,
                    "files_changed": 3,
                    "max_lines": 400,
                    "max_files": 8,
                    "over_budget": True,
                },
                payload["task_sizes"]["item-1"],
            )

    def test_task_size_command_reports_measurement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with (
                redirect_stdout(StringIO()),
                patch(
                    "codev_workflow.cli.git_ops_module.task_size",
                    return_value=TaskSize(120, 3, 400, 8),
                ),
            ):
                main(["init", "--target", str(target), "--agent-platform", "opencode"])
                text_output = StringIO()
                with redirect_stdout(text_output):
                    code = main(
                        ["task", "size", "--id", "item-1", "--target", str(target)]
                    )
                json_output = StringIO()
                with redirect_stdout(json_output):
                    main(
                        [
                            "task",
                            "size",
                            "--id",
                            "item-1",
                            "--target",
                            str(target),
                            "--json",
                        ]
                    )
            self.assertEqual(0, code)
            self.assertIn("120 line(s) changed (budget 400)", text_output.getvalue())
            self.assertIn("within budget", text_output.getvalue())
            self.assertEqual(
                {
                    "task_id": "item-1",
                    "lines_changed": 120,
                    "files_changed": 3,
                    "max_lines": 400,
                    "max_files": 8,
                    "over_budget": False,
                },
                json.loads(json_output.getvalue()),
            )

    def test_task_size_command_reports_over_budget_but_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with (
                redirect_stdout(StringIO()),
                patch(
                    "codev_workflow.cli.git_ops_module.task_size",
                    return_value=TaskSize(500, 9, 400, 8),
                ),
            ):
                main(["init", "--target", str(target), "--agent-platform", "opencode"])
                output = StringIO()
                with redirect_stdout(output):
                    code = main(
                        ["task", "size", "--id", "item-1", "--target", str(target)]
                    )
            self.assertEqual(0, code)
            self.assertIn("over budget", output.getvalue())

    def test_status_without_verbose_omits_owner_and_overlap_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                main(["init", "--target", str(target), "--agent-platform", "opencode"])
                output = StringIO()
                with redirect_stdout(output):
                    main(["status", "--target", str(target), "--json"])
            payload = json.loads(output.getvalue())
            self.assertNotIn("tasks_in_progress_by_owner", payload)
            self.assertNotIn("changed_file_overlaps", payload)
            self.assertNotIn("gate_decisions", payload)

    def test_status_verbose_summarizes_gate_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                main(["init", "--target", str(target), "--agent-platform", "opencode"])
            log_path = target / ".codev" / "hooks" / "decisions.jsonl"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(
                '{"timestamp": "2026-08-31T10:00:00Z", "hook": "require_plan.py", '
                '"decision": "ask"}\n'
                '{"timestamp": "2026-08-31T11:00:00Z", "hook": "require_plan.py", '
                '"decision": "allow"}\n',
                encoding="utf-8",
            )
            output = StringIO()
            with redirect_stdout(output):
                main(["status", "--target", str(target), "--verbose", "--json"])
            payload = json.loads(output.getvalue())
            self.assertEqual(
                {"require_plan.py": {"ask": 1, "allow": 1}},
                payload["gate_decisions"],
            )

    def test_status_verbose_since_filters_gate_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                main(["init", "--target", str(target), "--agent-platform", "opencode"])
            log_path = target / ".codev" / "hooks" / "decisions.jsonl"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(
                '{"timestamp": "2026-08-30T10:00:00Z", "hook": "require_plan.py", '
                '"decision": "ask"}\n'
                '{"timestamp": "2026-08-31T11:00:00Z", "hook": "require_plan.py", '
                '"decision": "allow"}\n',
                encoding="utf-8",
            )
            output = StringIO()
            with redirect_stdout(output):
                main(
                    [
                        "status",
                        "--target",
                        str(target),
                        "--verbose",
                        "--json",
                        "--since",
                        "2026-08-31T00:00:00Z",
                    ]
                )
            payload = json.loads(output.getvalue())
            self.assertEqual(
                {"require_plan.py": {"allow": 1}}, payload["gate_decisions"]
            )

    def test_doctor_alias_forwards_to_verbose_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                main(["init", "--target", str(target), "--agent-platform", "opencode"])
                output = StringIO()
                with redirect_stdout(output), redirect_stderr(StringIO()):
                    code = main(["doctor", "--target", str(target)])
            self.assertEqual(0, code)
            self.assertIn("Python", output.getvalue())

    def test_adapter_list_and_add_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                main(["init", "--target", str(target), "--agent-platform", "opencode"])
                listing = StringIO()
                with redirect_stdout(listing):
                    main(["adapter", "list", "--target", str(target), "--json"])
                self.assertEqual(["opencode"], json.loads(listing.getvalue()))

                self.assertEqual(
                    0,
                    main(
                        [
                            "adapter",
                            "add",
                            "antigravity",
                            "--target",
                            str(target),
                        ]
                    ),
                )
                listing_after = StringIO()
                with redirect_stdout(listing_after):
                    main(["adapter", "list", "--target", str(target), "--json"])
            self.assertEqual(
                ["antigravity", "opencode"],
                sorted(json.loads(listing_after.getvalue())),
            )
            self.assertTrue((target / ".agents/agents/assistant.md").is_file())

    def test_adapter_verify_passes_on_a_fresh_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                main(["init", "--target", str(target), "--agent-platform", "opencode"])
                output = StringIO()
                with redirect_stdout(output):
                    code = main(
                        [
                            "adapter",
                            "verify",
                            "opencode",
                            "--target",
                            str(target),
                            "--json",
                        ]
                    )
            self.assertEqual(0, code)
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(11, len(payload["findings"]))

    def test_adapter_verify_passes_for_claude_on_a_fresh_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                main(["init", "--target", str(target), "--agent-platform", "claude"])
                output = StringIO()
                with redirect_stdout(output):
                    code = main(
                        [
                            "adapter",
                            "verify",
                            "claude",
                            "--target",
                            str(target),
                            "--json",
                        ]
                    )
            self.assertEqual(0, code)
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(11, len(payload["findings"]))

    def test_adapter_verify_fails_when_lifecycle_wiring_is_stripped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                main(["init", "--target", str(target), "--agent-platform", "opencode"])
            (target / ".opencode/agents/orchestrator.md").write_text(
                "# orchestrator\n", encoding="utf-8"
            )
            output = StringIO()
            with redirect_stdout(output):
                code = main(["adapter", "verify", "opencode", "--target", str(target)])
            self.assertEqual(1, code)
            self.assertIn("FAILED", output.getvalue())

    def test_adapter_remove_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                main(["init", "--target", str(target), "--agent-platform", "claude"])
                main(
                    [
                        "adapter",
                        "add",
                        "opencode",
                        "--target",
                        str(target),
                    ]
                )
            self.assertTrue((target / ".opencode" / "agents" / "builder.md").is_file())
            self.assertTrue((target / ".claude" / "agents" / "builder.md").is_file())

            self.assertEqual(
                0,
                main(
                    [
                        "adapter",
                        "remove",
                        "opencode",
                        "--target",
                        str(target),
                    ]
                ),
            )
            self.assertFalse((target / ".opencode").exists())
            self.assertTrue((target / ".claude" / "agents" / "builder.md").is_file())
            listing = StringIO()
            with redirect_stdout(listing):
                main(["adapter", "list", "--target", str(target), "--json"])
            self.assertEqual(["claude"], json.loads(listing.getvalue()))

    def test_adapter_remove_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                main(["init", "--target", str(target), "--agent-platform", "claude"])
                main(
                    [
                        "adapter",
                        "add",
                        "opencode",
                        "--target",
                        str(target),
                    ]
                )
            output = StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "adapter",
                        "remove",
                        "opencode",
                        "--target",
                        str(target),
                        "--dry-run",
                    ]
                )
            self.assertEqual(0, code)
            self.assertIn("Dry run", output.getvalue())
            self.assertTrue((target / ".opencode" / "agents" / "builder.md").is_file())

    def test_adapter_remove_single_platform_shows_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                main(["init", "--target", str(target), "--agent-platform", "opencode"])
            with redirect_stderr(StringIO()):
                code = main(
                    [
                        "adapter",
                        "remove",
                        "opencode",
                        "--target",
                        str(target),
                    ]
                )
            self.assertEqual(2, code)

    def test_adapter_remove_not_installed_shows_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                main(["init", "--target", str(target), "--agent-platform", "opencode"])
            with redirect_stderr(StringIO()):
                code = main(
                    [
                        "adapter",
                        "remove",
                        "junie",
                        "--target",
                        str(target),
                    ]
                )
            self.assertEqual(2, code)

    def test_adapter_remove_accepts_a_platform_no_longer_valid(self) -> None:
        # `adapter remove`'s `platform` argument deliberately has no
        # argparse `choices=` restriction (unlike `add`/`verify`): a lock
        # file can record a platform an earlier CoDev version installed
        # that the current one no longer recognizes (e.g. Codex,
        # ADR-0031), and this is the one supported way off of it.
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                main(["init", "--target", str(target), "--agent-platform", "opencode"])
            lock_path = target / ".codev" / "lock.json"
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["platforms"].append("dropped-platform")
            lock_path.write_text(json.dumps(lock), encoding="utf-8")

            with redirect_stdout(StringIO()):
                code = main(
                    [
                        "adapter",
                        "remove",
                        "dropped-platform",
                        "--target",
                        str(target),
                    ]
                )
            self.assertEqual(0, code)
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            self.assertEqual(["opencode"], lock["platforms"])

    def test_config_set_get_list_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                self.assertEqual(
                    0,
                    main(
                        [
                            "config",
                            "set",
                            "model",
                            "anthropic/claude",
                            "--target",
                            str(target),
                        ]
                    ),
                )
                get_output = StringIO()
                with redirect_stdout(get_output):
                    code = main(
                        ["config", "get", "model", "--target", str(target), "--json"]
                    )
                self.assertEqual(0, code)
                self.assertEqual(
                    {"value": "anthropic/claude", "source": "project"},
                    json.loads(get_output.getvalue()),
                )

                list_output = StringIO()
                with redirect_stdout(list_output):
                    main(["config", "list", "--target", str(target), "--json"])
            self.assertEqual(
                {
                    "model": {"value": "anthropic/claude", "source": "project"},
                    "git.workflow": {"value": "trunk", "source": "default"},
                    "review.max_lines": {"value": "400", "source": "default"},
                    "review.max_files": {"value": "8", "source": "default"},
                },
                json.loads(list_output.getvalue()),
            )

    def test_config_get_missing_key_returns_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with redirect_stdout(StringIO()):
                code = main(
                    ["config", "get", "missing", "--target", directory, "--json"]
                )
            self.assertEqual(1, code)

    def test_self_version_and_update(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(0, main(["self", "version"]))
            self.assertEqual(0, main(["self", "update"]))
        self.assertIn("CoDev", output.getvalue())
        self.assertIn("upgrade", output.getvalue().lower())

    def test_deprecated_aliases_rewrite_to_new_command_forms(self) -> None:
        # CoDev is Alpha: eval's old command forms (fixture/run/snapshot) were
        # removed outright rather than aliased. Only the unrelated
        # check/doctor top-level aliases remain.
        self.assertEqual(
            ["status", "--target", "T"],
            _apply_deprecated_aliases(["check", "--target", "T"]),
        )
        self.assertEqual(
            ["status", "--verbose", "--target", "T"],
            _apply_deprecated_aliases(["doctor", "--target", "T"]),
        )

    def test_new_command_forms_pass_through_unchanged(self) -> None:
        self.assertEqual(
            ["eval", "task", "run", "name"],
            _apply_deprecated_aliases(["eval", "task", "run", "name"]),
        )
        self.assertEqual(
            ["eval", "task", "create", "name"],
            _apply_deprecated_aliases(["eval", "task", "create", "name"]),
        )
        self.assertEqual(["status"], _apply_deprecated_aliases(["status"]))
        self.assertEqual([], _apply_deprecated_aliases([]))

    def test_eval_task_run_baseline_flag_maps_to_with_skill_false(self) -> None:
        with (
            patch("codev_workflow.cli.evaluate", return_value=True) as evaluate_mock,
            redirect_stdout(StringIO()),
        ):
            code = main(
                [
                    "eval",
                    "task",
                    "run",
                    "name",
                    "--target",
                    "T",
                    "--output",
                    "O",
                    "--baseline",
                ]
            )
        self.assertEqual(0, code)
        self.assertFalse(evaluate_mock.call_args.kwargs["with_skill"])

    def test_eval_task_run_defaults_to_with_skill(self) -> None:
        with (
            patch("codev_workflow.cli.evaluate", return_value=True) as evaluate_mock,
            redirect_stdout(StringIO()),
        ):
            main(["eval", "task", "run", "name", "--target", "T", "--output", "O"])
        self.assertTrue(evaluate_mock.call_args.kwargs["with_skill"])

    def test_eval_task_run_agent_flag_overrides_opencode_executable(self) -> None:
        with (
            patch("codev_workflow.cli.evaluate", return_value=True) as evaluate_mock,
            redirect_stdout(StringIO()),
        ):
            main(
                [
                    "eval",
                    "task",
                    "run",
                    "name",
                    "--target",
                    "T",
                    "--output",
                    "O",
                    "--agent",
                    "/path/to/fake-agent.py",
                ]
            )
        self.assertEqual(
            "/path/to/fake-agent.py", evaluate_mock.call_args.kwargs["opencode"]
        )

    def test_eval_task_run_without_agent_flag_omits_opencode_kwarg(self) -> None:
        with (
            patch("codev_workflow.cli.evaluate", return_value=True) as evaluate_mock,
            redirect_stdout(StringIO()),
        ):
            main(["eval", "task", "run", "name", "--target", "T", "--output", "O"])
        self.assertNotIn("opencode", evaluate_mock.call_args.kwargs)

    def test_eval_task_run_defaults_sandbox_to_worktree(self) -> None:
        with (
            patch("codev_workflow.cli.evaluate", return_value=True) as evaluate_mock,
            redirect_stdout(StringIO()),
        ):
            main(["eval", "task", "run", "name", "--target", "T", "--output", "O"])
        self.assertEqual("worktree", evaluate_mock.call_args.kwargs["sandbox"])

    def test_eval_task_run_sandbox_docker_flag_is_forwarded(self) -> None:
        with (
            patch("codev_workflow.cli.evaluate", return_value=True) as evaluate_mock,
            redirect_stdout(StringIO()),
        ):
            main(
                [
                    "eval",
                    "task",
                    "run",
                    "name",
                    "--target",
                    "T",
                    "--output",
                    "O",
                    "--sandbox",
                    "docker",
                ]
            )
        self.assertEqual("docker", evaluate_mock.call_args.kwargs["sandbox"])

    def test_eval_benchmark_run_prints_category_matrix(self) -> None:
        report = {
            "skill": "review-change",
            "repetitions": 5,
            "categories": {
                "security": {
                    "with_skill_percentage": 100.0,
                    "baseline_percentage": 50.0,
                    "delta": 50.0,
                }
            },
            "overall": {
                "with_skill_percentage": 100.0,
                "baseline_percentage": 50.0,
                "delta": 50.0,
            },
        }
        with patch(
            "codev_workflow.cli.run_benchmark", return_value=report
        ) as benchmark_mock:
            output = StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "eval",
                        "benchmark",
                        "run",
                        "review-change",
                        "--target",
                        "T",
                        "--output",
                        "O",
                        "--repetitions",
                        "5",
                    ]
                )
        self.assertEqual(0, code)
        benchmark_mock.assert_called_once()
        self.assertEqual(5, benchmark_mock.call_args.kwargs["repetitions"])
        printed = output.getvalue()
        self.assertIn("Skill: review-change (5 repetitions)", printed)
        self.assertIn("security", printed)
        self.assertIn("Overall", printed)
        self.assertIn("+50.0pp", printed)
        self.assertIn("Full report:", printed)

    def test_eval_benchmark_run_forwards_repeated_category_flags(self) -> None:
        report = {
            "skill": "review-change",
            "repetitions": 1,
            "categories": {},
            "overall": {
                "with_skill_percentage": 0.0,
                "baseline_percentage": 0.0,
                "delta": 0.0,
            },
        }
        with (
            patch(
                "codev_workflow.cli.run_benchmark", return_value=report
            ) as benchmark_mock,
            redirect_stdout(StringIO()),
        ):
            main(
                [
                    "eval",
                    "benchmark",
                    "run",
                    "review-change",
                    "--target",
                    "T",
                    "--output",
                    "O",
                    "--category",
                    "security",
                    "--category",
                    "correctness",
                ]
            )
        self.assertEqual(
            ["security", "correctness"],
            benchmark_mock.call_args.kwargs["only_categories"],
        )

    def test_eval_benchmark_run_defaults_categories_to_none(self) -> None:
        report = {
            "skill": "review-change",
            "repetitions": 1,
            "categories": {},
            "overall": {
                "with_skill_percentage": 0.0,
                "baseline_percentage": 0.0,
                "delta": 0.0,
            },
        }
        with (
            patch(
                "codev_workflow.cli.run_benchmark", return_value=report
            ) as benchmark_mock,
            redirect_stdout(StringIO()),
        ):
            main(
                [
                    "eval",
                    "benchmark",
                    "run",
                    "review-change",
                    "--target",
                    "T",
                    "--output",
                    "O",
                ]
            )
        self.assertIsNone(benchmark_mock.call_args.kwargs["only_categories"])

    def test_eval_benchmark_run_packages_by_default(self) -> None:
        report = {
            "skill": "review-change",
            "repetitions": 1,
            "categories": {},
            "overall": {
                "with_skill_percentage": 0.0,
                "baseline_percentage": 0.0,
                "delta": 0.0,
            },
        }
        with (
            patch(
                "codev_workflow.cli.run_benchmark", return_value=report
            ) as benchmark_mock,
            redirect_stdout(StringIO()),
        ):
            main(
                [
                    "eval",
                    "benchmark",
                    "run",
                    "review-change",
                    "--target",
                    "T",
                    "--output",
                    "O",
                ]
            )
        self.assertTrue(benchmark_mock.call_args.kwargs["package"])

    def test_eval_benchmark_run_no_package_flag_forwards_false(self) -> None:
        report = {
            "skill": "review-change",
            "repetitions": 1,
            "categories": {},
            "overall": {
                "with_skill_percentage": 0.0,
                "baseline_percentage": 0.0,
                "delta": 0.0,
            },
        }
        with (
            patch(
                "codev_workflow.cli.run_benchmark", return_value=report
            ) as benchmark_mock,
            redirect_stdout(StringIO()),
        ):
            main(
                [
                    "eval",
                    "benchmark",
                    "run",
                    "review-change",
                    "--target",
                    "T",
                    "--output",
                    "O",
                    "--no-package",
                ]
            )
        self.assertFalse(benchmark_mock.call_args.kwargs["package"])

    def test_eval_benchmark_run_agent_flag_overrides_opencode(self) -> None:
        report = {
            "skill": "review-change",
            "repetitions": 1,
            "categories": {},
            "overall": {
                "with_skill_percentage": 0.0,
                "baseline_percentage": 0.0,
                "delta": 0.0,
            },
        }
        with (
            patch(
                "codev_workflow.cli.run_benchmark", return_value=report
            ) as benchmark_mock,
            redirect_stdout(StringIO()),
        ):
            main(
                [
                    "eval",
                    "benchmark",
                    "run",
                    "review-change",
                    "--target",
                    "T",
                    "--output",
                    "O",
                    "--agent",
                    "./fake-agent.py",
                ]
            )
        self.assertEqual("./fake-agent.py", benchmark_mock.call_args.kwargs["opencode"])

    def test_eval_benchmark_run_omits_opencode_kwarg_without_agent_flag(self) -> None:
        report = {
            "skill": "review-change",
            "repetitions": 1,
            "categories": {},
            "overall": {
                "with_skill_percentage": 0.0,
                "baseline_percentage": 0.0,
                "delta": 0.0,
            },
        }
        with (
            patch(
                "codev_workflow.cli.run_benchmark", return_value=report
            ) as benchmark_mock,
            redirect_stdout(StringIO()),
        ):
            main(
                [
                    "eval",
                    "benchmark",
                    "run",
                    "review-change",
                    "--target",
                    "T",
                    "--output",
                    "O",
                ]
            )
        self.assertNotIn("opencode", benchmark_mock.call_args.kwargs)

    def test_eval_benchmark_run_defaults_sandbox_to_worktree(self) -> None:
        report = {
            "skill": "review-change",
            "repetitions": 1,
            "categories": {},
            "overall": {
                "with_skill_percentage": 0.0,
                "baseline_percentage": 0.0,
                "delta": 0.0,
            },
        }
        with (
            patch(
                "codev_workflow.cli.run_benchmark", return_value=report
            ) as benchmark_mock,
            redirect_stdout(StringIO()),
        ):
            main(
                [
                    "eval",
                    "benchmark",
                    "run",
                    "review-change",
                    "--target",
                    "T",
                    "--output",
                    "O",
                ]
            )
        self.assertEqual("worktree", benchmark_mock.call_args.kwargs["sandbox"])

    def test_eval_benchmark_run_sandbox_flag_forwards_docker(self) -> None:
        report = {
            "skill": "review-change",
            "repetitions": 1,
            "categories": {},
            "overall": {
                "with_skill_percentage": 0.0,
                "baseline_percentage": 0.0,
                "delta": 0.0,
            },
        }
        with (
            patch(
                "codev_workflow.cli.run_benchmark", return_value=report
            ) as benchmark_mock,
            redirect_stdout(StringIO()),
        ):
            main(
                [
                    "eval",
                    "benchmark",
                    "run",
                    "review-change",
                    "--target",
                    "T",
                    "--output",
                    "O",
                    "--sandbox",
                    "docker",
                ]
            )
        self.assertEqual("docker", benchmark_mock.call_args.kwargs["sandbox"])

    def test_eval_show_prints_packaged_trace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evals_dir = root / ".agents" / "skills" / "review-change" / "evals"
            evals_dir.mkdir(parents=True)
            trace = {
                "skill": "review-change",
                "repetitions": 3,
                "generated_at": "2026-08-22T00:00:00+00:00",
                "categories": {
                    "security": {
                        "with_skill_percentage": 100.0,
                        "baseline_percentage": 50.0,
                        "delta": 50.0,
                    }
                },
                "overall": {
                    "with_skill_percentage": 100.0,
                    "baseline_percentage": 50.0,
                    "delta": 50.0,
                },
            }
            (evals_dir / "benchmark.json").write_text(json.dumps(trace))

            output = StringIO()
            with redirect_stdout(output):
                code = main(["eval", "show", "review-change", "--target", str(root)])
        self.assertEqual(0, code)
        printed = output.getvalue()
        self.assertIn("Skill: review-change (3 repetitions)", printed)
        self.assertIn("security", printed)
        self.assertIn("Generated: 2026-08-22T00:00:00+00:00", printed)
        self.assertIn("Trace file:", printed)

    def test_eval_show_reports_missing_trace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = StringIO()
            errors = StringIO()
            with redirect_stdout(output), redirect_stderr(errors):
                code = main(["eval", "show", "never-evaluated", "--target", str(root)])
        self.assertEqual(1, code)
        self.assertIn("no eval trace found", errors.getvalue())
        self.assertIn("codev eval benchmark run never-evaluated", errors.getvalue())

    def test_skill_name_strips_a_pasted_agents_skills_path(self) -> None:
        self.assertEqual(
            "audit-google-python-style",
            _skill_name(".agents/skills/audit-google-python-style"),
        )
        self.assertEqual(
            "audit-google-python-style",
            _skill_name(".agents/skills/audit-google-python-style/"),
        )
        self.assertEqual(
            "audit-google-python-style",
            _skill_name("./.agents/skills/audit-google-python-style"),
        )
        self.assertEqual(
            "audit-google-python-style",
            _skill_name(
                "/Users/rootm/github_repos/CoDev/.agents/skills/"
                "audit-google-python-style"
            ),
        )

    def test_skill_name_leaves_a_bare_name_unchanged(self) -> None:
        self.assertEqual("review-change", _skill_name("review-change"))

    def test_eval_show_accepts_a_pasted_agents_skills_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evals_dir = root / ".agents" / "skills" / "review-change" / "evals"
            evals_dir.mkdir(parents=True)
            trace = {
                "skill": "review-change",
                "repetitions": 1,
                "categories": {},
                "overall": {
                    "with_skill_percentage": 100.0,
                    "baseline_percentage": 0.0,
                    "delta": 100.0,
                },
            }
            (evals_dir / "benchmark.json").write_text(json.dumps(trace))

            output = StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "eval",
                        "show",
                        ".agents/skills/review-change",
                        "--target",
                        str(root),
                    ]
                )
        self.assertEqual(0, code)
        self.assertIn("Skill: review-change", output.getvalue())

    def test_eval_nvidia_validate_forwards_target_output_and_extra(self) -> None:
        with (
            patch(
                "codev_workflow.cli._run_nvidia_verb", return_value=True
            ) as verb_mock,
            redirect_stdout(StringIO()) as output,
        ):
            code = main(
                [
                    "eval",
                    "nvidia",
                    "validate",
                    "SKILL",
                    "--output",
                    "O",
                    "--extra=--llm",
                ]
            )
        self.assertEqual(0, code)
        verb_mock.assert_called_once()
        args, kwargs = verb_mock.call_args
        self.assertEqual("validate", args[0])
        self.assertEqual(Path("SKILL"), kwargs["target"])
        self.assertEqual(Path("O"), kwargs["output"])
        self.assertEqual(["--llm"], kwargs["extra_flags"])
        self.assertEqual(900, kwargs["timeout_seconds"])
        self.assertIn("Evaluation passed: O", output.getvalue())

    def test_eval_nvidia_verb_without_target_requirement_omits_skill_path(
        self,
    ) -> None:
        with (
            patch(
                "codev_workflow.cli._run_nvidia_verb", return_value=True
            ) as verb_mock,
            redirect_stdout(StringIO()),
        ):
            main(["eval", "nvidia", "models", "--output", "O"])
        self.assertIsNone(verb_mock.call_args.kwargs["target"])

    def test_eval_nvidia_tier3_evaluate_is_a_nested_subcommand(self) -> None:
        with (
            patch(
                "codev_workflow.cli._run_nvidia_verb", return_value=False
            ) as verb_mock,
            redirect_stdout(StringIO()),
        ):
            code = main(
                [
                    "eval",
                    "nvidia",
                    "tier3",
                    "evaluate",
                    "SKILL",
                    "--output",
                    "O",
                    "--timeout",
                    "60",
                ]
            )
        self.assertEqual(1, code)
        self.assertEqual("tier3-evaluate", verb_mock.call_args.args[0])
        self.assertEqual(60, verb_mock.call_args.kwargs["timeout_seconds"])

    def test_eval_nvidia_is_not_rewritten_by_deprecated_alias_handling(self) -> None:
        self.assertEqual(
            ["eval", "nvidia", "validate", "SKILL"],
            _apply_deprecated_aliases(["eval", "nvidia", "validate", "SKILL"]),
        )

    def test_format_benchmark_report_aligns_columns_and_sorts_categories(self) -> None:
        report = {
            "skill": "review-change",
            "repetitions": 3,
            "categories": {
                "security": {
                    "with_skill_percentage": 100.0,
                    "baseline_percentage": 66.7,
                    "delta": 33.3,
                },
                "architecture_scope": {
                    "with_skill_percentage": 50.0,
                    "baseline_percentage": 50.0,
                    "delta": 0.0,
                },
            },
            "overall": {
                "with_skill_percentage": 75.0,
                "baseline_percentage": 58.4,
                "delta": 16.7,
            },
        }
        table = _format_benchmark_report(report)
        lines = table.splitlines()
        # Category rows are sorted alphabetically; Overall always comes last,
        # set off by its own separator line, regardless of category order.
        architecture_index = next(
            i for i, line in enumerate(lines) if line.startswith("architecture_scope")
        )
        security_index = next(
            i for i, line in enumerate(lines) if line.startswith("security")
        )
        overall_index = next(
            i for i, line in enumerate(lines) if line.startswith("Overall")
        )
        self.assertLess(architecture_index, security_index)
        self.assertLess(security_index, overall_index)
        self.assertTrue(lines[overall_index - 1].startswith("---"))
        # Every data row (header excluded) has the same length once padded.
        data_rows = [line for line in lines if not line.startswith("-") and "%" in line]
        self.assertEqual(1, len({len(row) for row in data_rows}))


if __name__ == "__main__":
    unittest.main()
