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
        self.assertIn("missing file", by_role["builder"].problems)

    def test_missing_task_reference_is_reported(self) -> None:
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
                content = "codev task start codev task check codev task record"
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
                content = "codev task start codev task check codev task record"
                if role == "builder":
                    content += '\nbash:\n  "*": allow\n'
                path.write_text(content, encoding="utf-8")
            result = verify_adapter("opencode", target=target)
        builder = {f.role: f for f in result.findings}["builder"]
        self.assertFalse(builder.ok)
        self.assertTrue(
            any("unrestricted shell execution" in p for p in builder.problems)
        )

    def test_raw_git_push_permission_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for role, relative in ADAPTER_ROLE_PATHS["opencode"].items():
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                content = (
                    "codev task start codev task check codev task record "
                    "codev git open-pr"
                )
                if role == "builder":
                    content += '\nbash:\n  "git push*": allow\n'
                path.write_text(content, encoding="utf-8")
            result = verify_adapter("opencode", target=target)
        builder = {f.role: f for f in result.findings}["builder"]
        self.assertFalse(builder.ok)
        self.assertTrue(
            any("guarded `codev git` surface" in p for p in builder.problems)
        )

    def test_handwritten_pr_body_placeholder_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for role, relative in ADAPTER_ROLE_PATHS["opencode"].items():
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                content = (
                    "codev task start codev task check codev task record "
                    "codev git open-pr"
                )
                if role == "builder":
                    content += (
                        " -- open-pr --id <task-id> --title <title> --body <body>"
                    )
                path.write_text(content, encoding="utf-8")
            result = verify_adapter("opencode", target=target)
        builder = {f.role: f for f in result.findings}["builder"]
        self.assertFalse(builder.ok)
        self.assertTrue(any("PR body placeholder" in p for p in builder.problems))

    def test_specialist_permission_reverted_to_allow_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for role, relative in ADAPTER_ROLE_PATHS["opencode"].items():
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                content = (
                    "codev task start codev task check codev task record "
                    "codev git open-pr"
                )
                if role == "builder":
                    content += (
                        "\ntask:\n"
                        "  correctness-tests-specialist: allow\n"
                        "  security-data-specialist: ask\n"
                    )
                path.write_text(content, encoding="utf-8")
            result = verify_adapter("opencode", target=target)
        builder = {f.role: f for f in result.findings}["builder"]
        self.assertFalse(builder.ok)
        self.assertTrue(any("ADR-0021 permission gate" in p for p in builder.problems))

    def test_specialist_permission_ask_is_not_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for role, relative in ADAPTER_ROLE_PATHS["opencode"].items():
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                content = (
                    "codev task start codev task check codev task record "
                    "codev git open-pr"
                )
                if role == "builder":
                    content += "\ntask:\n  correctness-tests-specialist: ask\n"
                path.write_text(content, encoding="utf-8")
            result = verify_adapter("opencode", target=target)
        builder = {f.role: f for f in result.findings}["builder"]
        self.assertFalse(any("ADR-0021 permission gate" in p for p in builder.problems))

    def test_lightweight_reviewer_role_is_verified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for role, relative in ADAPTER_ROLE_PATHS["opencode"].items():
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                content = "codev task start codev task check codev git open-pr"
                if role != "lightweight-reviewer":
                    content += " codev task record"
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

    def test_assistant_role_has_no_required_markers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for role, relative in ADAPTER_ROLE_PATHS["junie"].items():
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                content = f"# {role}, no task-lifecycle wiring\n"
                path.write_text(content, encoding="utf-8")
            result = verify_adapter("junie", target=target)
        self.assertTrue(result.ok, result.findings)

    def test_assistant_role_still_flags_unrestricted_bash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for _role, relative in ADAPTER_ROLE_PATHS["antigravity"].items():
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('bash:\n  "*": allow\n', encoding="utf-8")
            result = verify_adapter("antigravity", target=target)
        assistant = {f.role: f for f in result.findings}["assistant"]
        self.assertFalse(assistant.ok)
        self.assertTrue(
            any("unrestricted shell execution" in p for p in assistant.problems)
        )


if __name__ == "__main__":
    unittest.main()
