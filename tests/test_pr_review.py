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

import argparse
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

SCRIPT = (
    Path(__file__).parents[1]
    / "src"
    / "codev_workflow"
    / "bundle"
    / ".agents"
    / "skills"
    / "pr-review"
    / "scripts"
    / "publish_review.py"
)
SPEC = importlib.util.spec_from_file_location("publish_review", SCRIPT)
assert SPEC and SPEC.loader
publish_review = importlib.util.module_from_spec(SPEC)
sys.modules["publish_review"] = publish_review
SPEC.loader.exec_module(publish_review)


DIFF = """diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -10,3 +10,4 @@ def run(value):
     if value is None:
         return 0
+    return value + 1
"""


class PullRequestReviewTests(unittest.TestCase):
    def test_fetch_collects_selected_pr_parts(self) -> None:
        args = argparse.Namespace(
            repo="owner/repo",
            pr=42,
            include=["metadata", "diff"],
            output_dir=None,
        )

        def request(_token: Any, _method: Any, _url: Any, **kwargs: Any) -> Any:
            if kwargs.get("decode_json") is False:
                return DIFF
            return {"head": {"sha": "abc123"}}

        with patch.object(publish_review, "_request", side_effect=request):
            data = publish_review._fetch_data(args, None, True)

        self.assertEqual({"metadata", "diff"}, set(data))
        self.assertEqual(DIFF, data["diff"])

    def test_gh_backend_does_not_put_credentials_in_command(self) -> None:
        completed = type(
            "Completed",
            (),
            {"returncode": 0, "stdout": '{"ok": true}', "stderr": ""},
        )()

        with (
            patch.object(publish_review, "_gh_executable", return_value="gh"),
            patch.object(
                publish_review.subprocess, "run", return_value=completed
            ) as run,
        ):
            result = publish_review._request(
                None,
                "GET",
                "https://api.github.com/repos/owner/repo/pulls/42",
                accept="application/vnd.github+json",
                use_gh=True,
            )

        self.assertEqual({"ok": True}, result)
        self.assertNotIn("Authorization", " ".join(run.call_args.args[0]))

    def test_validate_payload_accepts_changed_right_line(self) -> None:
        payload = {
            "head_sha": "abc123",
            "summary": "Review",
            "comments": [
                {
                    "finding_id": "P1-001",
                    "path": "src/app.py",
                    "line": 12,
                    "side": "RIGHT",
                    "body": "This can overflow.",
                }
            ],
        }

        comments = publish_review.validate_payload(payload, "abc123", DIFF)

        self.assertEqual("src/app.py", comments[0]["path"])
        self.assertIn("codev:pr-review:P1-001", comments[0]["body"])

    def test_validate_payload_rejects_unanchored_line(self) -> None:
        payload = {
            "head_sha": "abc123",
            "comments": [
                {
                    "finding_id": "P1-001",
                    "path": "src/app.py",
                    "line": 99,
                    "side": "RIGHT",
                    "body": "This is not in the diff.",
                }
            ],
        }

        with self.assertRaises(publish_review.ReviewError):
            publish_review.validate_payload(payload, "abc123", DIFF)

    def test_file_comment_has_no_line_coordinates(self) -> None:
        payload = {
            "head_sha": "abc123",
            "comments": [
                {
                    "finding_id": "P2-001",
                    "path": "src/app.py",
                    "subject_type": "file",
                    "body": "The migration evidence is missing.",
                }
            ],
        }

        comments = publish_review.validate_payload(payload, "abc123", DIFF)

        self.assertEqual("file", comments[0]["subject_type"])

    def test_cli_dry_run_still_requires_current_github_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            review = Path(directory) / "review.json"
            review.write_text(
                json.dumps({"head_sha": "abc123", "comments": []}),
                encoding="utf-8",
            )

            with (
                patch.object(publish_review, "_gh_executable", return_value=None),
                patch.dict(
                    publish_review.os.environ,
                    {"GITHUB_TOKEN": "", "GH_TOKEN": ""},
                ),
            ):
                result = publish_review.main(
                    ["--repo", "owner/repo", "--pr", "42", "--review", str(review)]
                )

        self.assertEqual(2, result)


if __name__ == "__main__":
    unittest.main()
