from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from codev_workflow.cli import _apply_deprecated_aliases, _format_snapshot_report, main


class CliTests(unittest.TestCase):
    def test_init_check_diff_round_trip(self) -> None:
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
                            "codex",
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
                            "codex",
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
                            "codex",
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
            self.assertTrue((target / ".agents/agents/reviewer.md").is_file())
            self.assertTrue(
                (target / ".agents/skills/review-change/SKILL.md").is_file()
            )
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
                            "codex",
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

    def test_update_can_add_codex_to_an_existing_install(self) -> None:
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
                            "codex",
                        ]
                    ),
                )
                self.assertEqual(0, main(["check", "--target", str(target)]))
            self.assertTrue((target / ".codex/agents/reviewer.toml").is_file())

    def test_work_lifecycle_round_trip(self) -> None:
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
                            "work",
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
                            "work",
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
                            "work",
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
                            "work",
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
                    main(["work", "status", "--id", "item-1", "--target", str(target)]),
                )
                self.assertEqual(
                    0, main(["work", "log", "--id", "item-1", "--target", str(target)])
                )
                self.assertEqual(
                    0,
                    main(
                        [
                            "work",
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

    def test_work_check_repeated_finding_exits_nonzero(self) -> None:
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
                        "work",
                        "start",
                        "--id",
                        "item-1",
                        "--base",
                        "base-sha",
                        "--max-rounds",
                        "5",
                        "--target",
                        str(target),
                    ]
                )
                for round_number in (1, 2):
                    if round_number > 1:
                        main(
                            [
                                "work",
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
                            "work",
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
                            "work",
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

    def test_status_reports_bundle_health_adapters_and_work_items(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                main(
                    [
                        "init",
                        "--target",
                        str(target),
                        "--agent-platform",
                        "codex",
                    ]
                )
                main(
                    [
                        "work",
                        "start",
                        "--id",
                        "item-1",
                        "--base",
                        "base-sha",
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
            self.assertEqual(["codex"], payload["adapters"])
            self.assertEqual(1, payload["work_items_in_progress"])
            self.assertNotIn("python_version", payload)

    def test_status_verbose_adds_environment_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                main(["init", "--target", str(target), "--agent-platform", "codex"])
                output = StringIO()
                with redirect_stdout(output):
                    code = main(
                        ["status", "--target", str(target), "--verbose", "--json"]
                    )
            self.assertEqual(0, code)
            payload = json.loads(output.getvalue())
            self.assertIn("python_version", payload)
            self.assertIn("system", payload)

    def test_doctor_alias_forwards_to_verbose_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                main(["init", "--target", str(target), "--agent-platform", "codex"])
                output = StringIO()
                with redirect_stdout(output), redirect_stderr(StringIO()):
                    code = main(["doctor", "--target", str(target)])
            self.assertEqual(0, code)
            self.assertIn("Python", output.getvalue())

    def test_adapter_list_and_add_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                main(["init", "--target", str(target), "--agent-platform", "codex"])
                listing = StringIO()
                with redirect_stdout(listing):
                    main(["adapter", "list", "--target", str(target), "--json"])
                self.assertEqual(["codex"], json.loads(listing.getvalue()))

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
                ["antigravity", "codex"], sorted(json.loads(listing_after.getvalue()))
            )
            self.assertTrue((target / ".agents/agents/reviewer.md").is_file())

    def test_adapter_verify_passes_on_a_fresh_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                main(["init", "--target", str(target), "--agent-platform", "codex"])
                output = StringIO()
                with redirect_stdout(output):
                    code = main(
                        [
                            "adapter",
                            "verify",
                            "codex",
                            "--target",
                            str(target),
                            "--json",
                        ]
                    )
            self.assertEqual(0, code)
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(3, len(payload["findings"]))

    def test_adapter_verify_fails_when_lifecycle_wiring_is_stripped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                main(["init", "--target", str(target), "--agent-platform", "codex"])
            (target / ".codex/agents/orchestrator.toml").write_text(
                'name = "orchestrator"\n', encoding="utf-8"
            )
            output = StringIO()
            with redirect_stdout(output):
                code = main(["adapter", "verify", "codex", "--target", str(target)])
            self.assertEqual(1, code)
            self.assertIn("FAILED", output.getvalue())

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
                {"model": {"value": "anthropic/claude", "source": "project"}},
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
        self.assertEqual(
            ["eval", "fixture", "create", "name", "--target", "T"],
            _apply_deprecated_aliases(["fixture", "create", "name", "--target", "T"]),
        )
        self.assertEqual(
            ["eval", "run", "name", "--target", "T"],
            _apply_deprecated_aliases(["eval", "name", "--target", "T"]),
        )
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
            ["eval", "run", "name"], _apply_deprecated_aliases(["eval", "run", "name"])
        )
        self.assertEqual(
            ["eval", "fixture", "create", "name"],
            _apply_deprecated_aliases(["eval", "fixture", "create", "name"]),
        )
        self.assertEqual(["status"], _apply_deprecated_aliases(["status"]))
        self.assertEqual([], _apply_deprecated_aliases([]))

    def test_eval_run_without_skill_flag_maps_to_with_skill_false(self) -> None:
        with patch("codev_workflow.cli.evaluate", return_value=True) as evaluate_mock:
            code = main(
                [
                    "eval",
                    "run",
                    "name",
                    "--target",
                    "T",
                    "--output",
                    "O",
                    "--without-skill",
                ]
            )
        self.assertEqual(0, code)
        self.assertFalse(evaluate_mock.call_args.kwargs["with_skill"])

    def test_eval_run_defaults_to_with_skill(self) -> None:
        with patch("codev_workflow.cli.evaluate", return_value=True) as evaluate_mock:
            main(["eval", "run", "name", "--target", "T", "--output", "O"])
        self.assertTrue(evaluate_mock.call_args.kwargs["with_skill"])

    def test_eval_snapshot_run_prints_category_matrix(self) -> None:
        report = {
            "skill": "review-change",
            "repetitions": 5,
            "categories": {
                "security": {
                    "with_skill_percentage": 100.0,
                    "without_skill_percentage": 50.0,
                    "delta": 50.0,
                }
            },
            "overall": {
                "with_skill_percentage": 100.0,
                "without_skill_percentage": 50.0,
                "delta": 50.0,
            },
        }
        with patch(
            "codev_workflow.cli.run_snapshot", return_value=report
        ) as snapshot_mock:
            output = StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "eval",
                        "snapshot",
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
        snapshot_mock.assert_called_once()
        self.assertEqual(5, snapshot_mock.call_args.kwargs["repetitions"])
        printed = output.getvalue()
        self.assertIn("Skill: review-change (5 repetitions)", printed)
        self.assertIn("security", printed)
        self.assertIn("Overall", printed)
        self.assertIn("+50.0pp", printed)
        self.assertIn("Full report:", printed)

    def test_eval_snapshot_run_forwards_repeated_category_flags(self) -> None:
        report = {
            "skill": "review-change",
            "repetitions": 1,
            "categories": {},
            "overall": {
                "with_skill_percentage": 0.0,
                "without_skill_percentage": 0.0,
                "delta": 0.0,
            },
        }
        with (
            patch(
                "codev_workflow.cli.run_snapshot", return_value=report
            ) as snapshot_mock,
            redirect_stdout(StringIO()),
        ):
            main(
                [
                    "eval",
                    "snapshot",
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
            snapshot_mock.call_args.kwargs["only_categories"],
        )

    def test_eval_snapshot_run_defaults_categories_to_none(self) -> None:
        report = {
            "skill": "review-change",
            "repetitions": 1,
            "categories": {},
            "overall": {
                "with_skill_percentage": 0.0,
                "without_skill_percentage": 0.0,
                "delta": 0.0,
            },
        }
        with (
            patch(
                "codev_workflow.cli.run_snapshot", return_value=report
            ) as snapshot_mock,
            redirect_stdout(StringIO()),
        ):
            main(
                [
                    "eval",
                    "snapshot",
                    "run",
                    "review-change",
                    "--target",
                    "T",
                    "--output",
                    "O",
                ]
            )
        self.assertIsNone(snapshot_mock.call_args.kwargs["only_categories"])

    def test_format_snapshot_report_aligns_columns_and_sorts_categories(self) -> None:
        report = {
            "skill": "review-change",
            "repetitions": 3,
            "categories": {
                "security": {
                    "with_skill_percentage": 100.0,
                    "without_skill_percentage": 66.7,
                    "delta": 33.3,
                },
                "architecture_scope": {
                    "with_skill_percentage": 50.0,
                    "without_skill_percentage": 50.0,
                    "delta": 0.0,
                },
            },
            "overall": {
                "with_skill_percentage": 75.0,
                "without_skill_percentage": 58.4,
                "delta": 16.7,
            },
        }
        table = _format_snapshot_report(report)
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
