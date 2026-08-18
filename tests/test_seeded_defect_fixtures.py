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
"""Structural and verifier-logic coverage for the seeded-defect fixture corpus.

These fixtures measure whether a reviewer actually catches a known, planted
defect - the recall-calibration mechanism described in
docs/adr/0001-work-lifecycle-invariant.md's motivating context. Running them
end to end requires a live OpenCode actor (`codev eval <name> --target .
--output <dir>`), which spends real API budget, so it is not exercised here.
What *is* exercised, deterministically and for free: every fixture conforms
to the v1 schema, and every fixture's verifier script actually distinguishes
a review that caught the planted defect from one that missed it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from codev_workflow.eval import validate_fixture

_FIXTURES_ROOT = Path(__file__).resolve().parents[1] / ".codev" / "fixtures"
_SEEDED_DEFECT_NAMES = sorted(
    path.name
    for path in _FIXTURES_ROOT.iterdir()
    if path.is_dir() and path.name.startswith("seeded-defect-")
)

# One deterministic "review caught it" / "review missed it" pair per fixture,
# hand-written to match that fixture's planted defect and check_review.py.
_REVIEWS: dict[str, dict[str, dict[str, object]]] = {
    "seeded-defect-correctness": {
        "caught": {
            "decision": "CHANGES_REQUIRED",
            "findings": [
                {
                    "id": "f1",
                    "location": "changed/module.py:6",
                    "category": "correctness",
                    "blocking": True,
                    "rank": 1,
                    "summary": "last_n_items off-by-one: returns n+1 items.",
                }
            ],
        },
        "missed": {"decision": "READY_FOR_HUMAN_APPROVAL", "findings": []},
    },
    "seeded-defect-security": {
        "caught": {
            "decision": "CHANGES_REQUIRED",
            "findings": [
                {
                    "id": "f1",
                    "location": "changed/module.py:5",
                    "category": "security",
                    "blocking": True,
                    "rank": 1,
                    "summary": "find_user builds SQL via f-string: SQL injection risk.",
                }
            ],
        },
        "missed": {"decision": "READY_FOR_HUMAN_APPROVAL", "findings": []},
    },
    "seeded-defect-error-handling": {
        "caught": {
            "decision": "CHANGES_REQUIRED",
            "findings": [
                {
                    "id": "f1",
                    "location": "changed/module.py:9",
                    "category": "error_handling",
                    "blocking": True,
                    "rank": 1,
                    "summary": "load_config has a bare except that swallows errors.",
                }
            ],
        },
        "missed": {"decision": "READY_FOR_HUMAN_APPROVAL", "findings": []},
    },
    "seeded-defect-test-quality": {
        "caught": {
            "decision": "CHANGES_REQUIRED",
            "findings": [
                {
                    "id": "f1",
                    "location": "changed/test_module.py:7",
                    "category": "test_quality",
                    "blocking": True,
                    "rank": 1,
                    "summary": "test_divide asserts result == result: tautological.",
                }
            ],
        },
        "missed": {"decision": "READY_FOR_HUMAN_APPROVAL", "findings": []},
    },
    "seeded-defect-architecture-scope": {
        "caught": {
            "decision": "CHANGES_REQUIRED",
            "findings": [
                {
                    "id": "f1",
                    "location": "changed/module.py:5",
                    "category": "architecture_scope",
                    "blocking": True,
                    "rank": 1,
                    "summary": "get_active_users has an unrelated log side effect.",
                }
            ],
        },
        "missed": {"decision": "READY_FOR_HUMAN_APPROVAL", "findings": []},
    },
    "seeded-defect-maintainability": {
        "caught": {
            "decision": "READY_FOR_HUMAN_APPROVAL",
            "findings": [
                {
                    "id": "f1",
                    "location": "changed/module.py:4",
                    "category": "maintainability",
                    "blocking": False,
                    "rank": 3,
                    "summary": "validate_order is deeply nested; use guard clauses.",
                }
            ],
        },
        "missed": {"decision": "READY_FOR_HUMAN_APPROVAL", "findings": []},
    },
    "seeded-defect-rollout": {
        "caught": {
            "decision": "CHANGES_REQUIRED",
            "findings": [
                {
                    "id": "f1",
                    "location": "changed/module.py:8",
                    "category": "rollout",
                    "blocking": True,
                    "rank": 1,
                    "summary": "compute_total renamed with no deprecation alias.",
                }
            ],
        },
        "missed": {"decision": "READY_FOR_HUMAN_APPROVAL", "findings": []},
    },
}


class SeededDefectCorpusTests(unittest.TestCase):
    def test_corpus_covers_every_review_dimension(self) -> None:
        self.assertEqual(
            {
                "seeded-defect-architecture-scope",
                "seeded-defect-correctness",
                "seeded-defect-error-handling",
                "seeded-defect-maintainability",
                "seeded-defect-rollout",
                "seeded-defect-security",
                "seeded-defect-test-quality",
            },
            set(_SEEDED_DEFECT_NAMES),
        )

    def test_every_fixture_is_schema_valid(self) -> None:
        for name in _SEEDED_DEFECT_NAMES:
            with self.subTest(fixture=name):
                validate_fixture(_FIXTURES_ROOT / name)

    def test_every_fixture_has_a_hand_written_review_pair(self) -> None:
        self.assertEqual(set(_SEEDED_DEFECT_NAMES), set(_REVIEWS))


class VerifierLogicTests(unittest.TestCase):
    """Run each fixture's own check_review.py against a worktree-like directory."""

    def _run_verifier(
        self, name: str, review: dict[str, object]
    ) -> subprocess.CompletedProcess[str]:
        fixture_root = _FIXTURES_ROOT / name
        with tempfile.TemporaryDirectory() as directory:
            worktree = Path(directory)
            shutil.copytree(fixture_root / "repository", worktree, dirs_exist_ok=True)
            (worktree / "review.json").write_text(json.dumps(review), encoding="utf-8")
            return subprocess.run(
                [sys.executable, "check_review.py"],
                cwd=worktree,
                capture_output=True,
                text=True,
                timeout=30,
            )

    def test_verifier_passes_when_the_defect_is_caught(self) -> None:
        for name, pair in _REVIEWS.items():
            with self.subTest(fixture=name):
                result = self._run_verifier(name, pair["caught"])
                self.assertEqual(0, result.returncode, result.stderr)

    def test_verifier_fails_when_the_defect_is_missed(self) -> None:
        for name, pair in _REVIEWS.items():
            with self.subTest(fixture=name):
                result = self._run_verifier(name, pair["missed"])
                self.assertNotEqual(0, result.returncode)


if __name__ == "__main__":
    unittest.main()
