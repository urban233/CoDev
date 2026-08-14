from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codev_workflow.adapter import (
    ADAPTER_ROLE_PATHS,
    AdapterVerificationError,
    verify_adapter,
)

_BUNDLE_ROOT = Path(__file__).resolve().parents[1] / "src" / "codev_workflow" / "bundle"


class BundleParityTests(unittest.TestCase):
    """Cross-adapter parity: every platform's bundle files stay in sync."""

    def test_every_platform_conforms_in_the_shipped_bundle(self) -> None:
        for platform in ADAPTER_ROLE_PATHS:
            with self.subTest(platform=platform):
                result = verify_adapter(platform, target=_BUNDLE_ROOT)
                problems = [
                    f"{finding.role} ({finding.path}): {finding.problems}"
                    for finding in result.findings
                    if not finding.ok
                ]
                self.assertTrue(result.ok, "\n".join(problems))


class VerifyAdapterTests(unittest.TestCase):
    def test_unknown_platform_raises(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(AdapterVerificationError),
        ):
            verify_adapter("not-a-real-platform", target=Path(directory))

    def test_missing_role_file_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = verify_adapter("opencode", target=Path(directory))
        self.assertFalse(result.ok)
        by_role = {finding.role: finding for finding in result.findings}
        self.assertIn("missing file", by_role["orchestrator"].problems)

    def test_missing_work_reference_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for role, relative in ADAPTER_ROLE_PATHS["opencode"].items():
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    f"# {role}, no lifecycle wiring here\n", encoding="utf-8"
                )
            result = verify_adapter("opencode", target=target)
        self.assertFalse(result.ok)
        by_role = {finding.role: finding for finding in result.findings}
        self.assertTrue(
            any("missing required reference" in p for p in by_role["builder"].problems)
        )

    def test_retired_severity_scale_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for role, relative in ADAPTER_ROLE_PATHS["opencode"].items():
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                content = "codev work start codev work check codev work record"
                if role == "reviewer":
                    content += " Lead with findings ordered P0 through P3."
                path.write_text(content, encoding="utf-8")
            result = verify_adapter("opencode", target=target)
        reviewer = {f.role: f for f in result.findings}["reviewer"]
        self.assertFalse(reviewer.ok)
        self.assertTrue(any("retired pattern" in p for p in reviewer.problems))

    def test_unrestricted_bash_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for role, relative in ADAPTER_ROLE_PATHS["opencode"].items():
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                content = "codev work start codev work check codev work record"
                if role == "orchestrator":
                    content += '\nbash:\n  "*": allow\n'
                path.write_text(content, encoding="utf-8")
            result = verify_adapter("opencode", target=target)
        orchestrator = {f.role: f for f in result.findings}["orchestrator"]
        self.assertFalse(orchestrator.ok)
        self.assertTrue(
            any("unrestricted shell execution" in p for p in orchestrator.problems)
        )

    def test_raw_git_push_permission_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for role, relative in ADAPTER_ROLE_PATHS["opencode"].items():
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                content = (
                    "codev work start codev work check codev work record "
                    "codev git open-pr"
                )
                if role == "orchestrator":
                    content += '\nbash:\n  "git push*": allow\n'
                path.write_text(content, encoding="utf-8")
            result = verify_adapter("opencode", target=target)
        orchestrator = {f.role: f for f in result.findings}["orchestrator"]
        self.assertFalse(orchestrator.ok)
        self.assertTrue(
            any("guarded `codev git` surface" in p for p in orchestrator.problems)
        )

    def test_handwritten_pr_body_placeholder_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for role, relative in ADAPTER_ROLE_PATHS["opencode"].items():
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                content = (
                    "codev work start codev work check codev work record "
                    "codev git open-pr"
                )
                if role == "orchestrator":
                    content += (
                        " -- open-pr --id <work-item-id> --title <title> --body <body>"
                    )
                path.write_text(content, encoding="utf-8")
            result = verify_adapter("opencode", target=target)
        orchestrator = {f.role: f for f in result.findings}["orchestrator"]
        self.assertFalse(orchestrator.ok)
        self.assertTrue(any("PR body placeholder" in p for p in orchestrator.problems))

    def test_specialist_permission_reverted_to_allow_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for role, relative in ADAPTER_ROLE_PATHS["opencode"].items():
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                content = (
                    "codev work start codev work check codev work record "
                    "codev git open-pr"
                )
                if role == "outer-loop-runner":
                    content += (
                        "\ntask:\n"
                        "  correctness-tests-specialist: allow\n"
                        "  security-data-specialist: ask\n"
                    )
                path.write_text(content, encoding="utf-8")
            result = verify_adapter("opencode", target=target)
        outer_loop_runner = {f.role: f for f in result.findings}["outer-loop-runner"]
        self.assertFalse(outer_loop_runner.ok)
        self.assertTrue(
            any("ADR-0021 permission gate" in p for p in outer_loop_runner.problems)
        )

    def test_specialist_permission_ask_is_not_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for role, relative in ADAPTER_ROLE_PATHS["opencode"].items():
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                content = (
                    "codev work start codev work check codev work record "
                    "codev git open-pr"
                )
                if role == "outer-loop-runner":
                    content += "\ntask:\n  correctness-tests-specialist: ask\n"
                path.write_text(content, encoding="utf-8")
            result = verify_adapter("opencode", target=target)
        outer_loop_runner = {f.role: f for f in result.findings}["outer-loop-runner"]
        self.assertFalse(
            any("ADR-0021 permission gate" in p for p in outer_loop_runner.problems)
        )

    def test_lightweight_reviewer_role_is_verified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for role, relative in ADAPTER_ROLE_PATHS["opencode"].items():
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                content = "codev work start codev work check codev git open-pr"
                if role != "lightweight-reviewer":
                    content += " codev work record"
                path.write_text(content, encoding="utf-8")
            result = verify_adapter("opencode", target=target)
        by_role = {finding.role: finding for finding in result.findings}
        self.assertFalse(by_role["lightweight-reviewer"].ok)
        self.assertTrue(
            any(
                "missing required reference" in p
                for p in by_role["lightweight-reviewer"].problems
            )
        )

    def test_invalid_toml_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for role, relative in ADAPTER_ROLE_PATHS["codex"].items():
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                content = "codev work start codev work check codev work record"
                if role == "orchestrator":
                    content = "not [ valid toml"
                path.write_text(content, encoding="utf-8")
            result = verify_adapter("codex", target=target)
        orchestrator = {f.role: f for f in result.findings}["orchestrator"]
        self.assertFalse(orchestrator.ok)
        self.assertTrue(any("invalid TOML" in p for p in orchestrator.problems))


if __name__ == "__main__":
    unittest.main()
