from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import codev_workflow.installer as installer
from codev_workflow.conflict_wizard import (
    SPECIAL_INTEGRATION_PATHS,
    render_diff,
    resolve_non_interactive,
    run_wizard,
)


class RenderDiffTests(unittest.TestCase):
    def test_textual_content_produces_a_unified_diff(self) -> None:
        diff = render_diff("a.md", b"one\ntwo\n", b"one\nthree\n")
        self.assertIn("-two", diff)
        self.assertIn("+three", diff)

    def test_identical_content_reports_no_difference(self) -> None:
        self.assertEqual(
            "(no textual difference)", render_diff("a.md", b"same\n", b"same\n")
        )

    def test_non_utf8_content_reports_binary_note(self) -> None:
        diff = render_diff("a.bin", b"\xff\xfe", b"\x00\x01")
        self.assertIn("binary", diff)


class ResolveNonInteractiveTests(unittest.TestCase):
    def test_policy_applies_to_every_plain_conflict(self) -> None:
        plan = installer.Plan(
            operations=[
                installer.Operation("conflict", "a.md", "x", new_content=b"upstream"),
                installer.Operation("conflict", "b.md", "y", new_content=b"upstream"),
            ]
        )
        resolutions = resolve_non_interactive(plan, installer.Resolution.KEEP)
        self.assertEqual(
            {"a.md": installer.Resolution.KEEP, "b.md": installer.Resolution.KEEP},
            resolutions,
        )

    def test_special_integration_paths_are_never_resolved(self) -> None:
        plan = installer.Plan(
            operations=[
                installer.Operation("conflict", "AGENTS.md", "x"),
                installer.Operation("conflict", ".gitignore", "y"),
                installer.Operation("conflict", ".opencode/opencode.json", "z"),
            ]
        )
        resolutions = resolve_non_interactive(plan, installer.Resolution.KEEP)
        self.assertEqual({}, resolutions)
        self.assertTrue(
            SPECIAL_INTEGRATION_PATHS.issuperset(item.path for item in plan.operations)
        )

    def test_override_falls_back_to_skip_when_upstream_has_nothing_to_offer(
        self,
    ) -> None:
        plan = installer.Plan(
            operations=[
                installer.Operation("conflict", "a.md", "no upstream content"),
            ]
        )
        resolutions = resolve_non_interactive(plan, installer.Resolution.OVERRIDE)
        self.assertEqual({"a.md": installer.Resolution.SKIP}, resolutions)

    def test_copy_falls_back_to_skip_when_upstream_has_nothing_to_offer(self) -> None:
        plan = installer.Plan(
            operations=[
                installer.Operation("conflict", "a.md", "no upstream content"),
            ]
        )
        resolutions = resolve_non_interactive(plan, installer.Resolution.COPY)
        self.assertEqual({"a.md": installer.Resolution.SKIP}, resolutions)

    def test_delete_is_allowed_even_with_no_upstream_content(self) -> None:
        plan = installer.Plan(
            operations=[
                installer.Operation("conflict", "a.md", "no upstream content"),
            ]
        )
        resolutions = resolve_non_interactive(plan, installer.Resolution.DELETE)
        self.assertEqual({"a.md": installer.Resolution.DELETE}, resolutions)


class RunWizardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.target = Path(self.temporary.name)

    def _plan(self, *operations: installer.Operation) -> installer.Plan:
        return installer.Plan(operations=list(operations))

    def test_requires_an_interactive_terminal(self) -> None:
        plan = self._plan(
            installer.Operation("conflict", "a.md", "x", new_content=b"upstream")
        )
        with (
            patch("sys.stdin.isatty", return_value=False),
            self.assertRaises(installer.CoDevError),
        ):
            run_wizard(self.target, plan)

    def test_walks_each_conflict_and_records_the_chosen_resolution(self) -> None:
        (self.target / "a.md").write_text("local", encoding="utf-8")
        plan = self._plan(
            installer.Operation("conflict", "a.md", "x", new_content=b"upstream"),
            installer.Operation("conflict", "b.md", "y", new_content=b"upstream"),
        )
        answers = iter(["o", "k"])
        with patch("sys.stdin.isatty", return_value=True):
            resolutions = run_wizard(
                self.target,
                plan,
                input_fn=lambda _prompt: next(answers),
                output=lambda *_args: None,
            )
        self.assertEqual(
            {
                "a.md": installer.Resolution.OVERRIDE,
                "b.md": installer.Resolution.KEEP,
            },
            resolutions,
        )

    def test_quit_stops_early_and_keeps_prior_answers(self) -> None:
        plan = self._plan(
            installer.Operation("conflict", "a.md", "x", new_content=b"upstream"),
            installer.Operation("conflict", "b.md", "y", new_content=b"upstream"),
        )
        answers = iter(["k", "q"])
        with patch("sys.stdin.isatty", return_value=True):
            resolutions = run_wizard(
                self.target,
                plan,
                input_fn=lambda _prompt: next(answers),
                output=lambda *_args: None,
            )
        self.assertEqual({"a.md": installer.Resolution.KEEP}, resolutions)

    def test_unrecognized_answer_reprompts(self) -> None:
        plan = self._plan(
            installer.Operation("conflict", "a.md", "x", new_content=b"upstream")
        )
        answers = iter(["nonsense", "s"])
        with patch("sys.stdin.isatty", return_value=True):
            resolutions = run_wizard(
                self.target,
                plan,
                input_fn=lambda _prompt: next(answers),
                output=lambda *_args: None,
            )
        self.assertEqual({"a.md": installer.Resolution.SKIP}, resolutions)

    def test_conflict_with_no_upstream_content_does_not_offer_override_or_copy(
        self,
    ) -> None:
        plan = self._plan(
            installer.Operation("conflict", "a.md", "upstream removed this file")
        )
        seen_prompts: list[str] = []

        def fake_input(prompt: str) -> str:
            seen_prompts.append(prompt)
            return "k"

        with patch("sys.stdin.isatty", return_value=True):
            resolutions = run_wizard(
                self.target,
                plan,
                input_fn=fake_input,
                output=lambda *_args: None,
            )
        self.assertEqual({"a.md": installer.Resolution.KEEP}, resolutions)
        self.assertNotIn("o", seen_prompts[0].split())

    def test_special_integration_conflicts_are_reported_but_not_resolved(
        self,
    ) -> None:
        plan = self._plan(installer.Operation("conflict", "AGENTS.md", "modified"))
        with patch("sys.stdin.isatty", return_value=True):
            resolutions = run_wizard(
                self.target,
                plan,
                input_fn=lambda _prompt: self.fail("should not prompt"),
                output=lambda *_args: None,
            )
        self.assertEqual({}, resolutions)


if __name__ == "__main__":
    unittest.main()
