"""End-to-end coverage for the packaged eval trace ("Recommended Artifact
Set", see docs/adr/0028-skill-packages-carry-their-own-eval-trace.md)
against a real, already-committed skill and task -- audit-google-python-style
and its audit-google-python-style-phase-a task -- rather than a synthetic
stand-in built just for the test.

Both are copied into an isolated temporary repository first: nothing here
ever writes into the actual project's own .agents/skills/ directory. A
fake-agent stub (no network, no credentials, no real model call) stands in
for OpenCode, so this runs at unit-test speed and cost.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from codev_workflow.cli import main

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SKILL_NAME = "audit-google-python-style"
_TASK_NAME = "audit-google-python-style-phase-a"
_REAL_SKILL_DIR = _REPO_ROOT / ".agents" / "skills" / _SKILL_NAME
_REAL_TASK_DIR = _REPO_ROOT / ".codev" / "eval" / "tasks" / _TASK_NAME

# Mirrors the real task's own prompt.md/checks.json contract:
# - actor writes audit-plan.json with "decision" and "findings"
# - checks.json requires decision == APPROVAL_REQUIRED and findings that
#   flag the wildcard import, the illegal tmp_ binding, the non-PascalCase
#   class name, the non-snake_case method name, the missing get_view
#   docstring, and the missing a_parent Args entry
# - judge only runs once the checks above already passed
_FAKE_AGENT = f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

argv = sys.argv[1:]
prompt = argv[-1] if argv else ""

if "Review rubric" in prompt:
    verdict = {{
        "schema_version": 1,
        "verdict": "pass",
        "summary": "Plan flags the planted violations and requests approval.",
        "findings": [
            {{"criterion": "R1", "verdict": "pass", "evidence": "audit-plan.json"}}
        ],
    }}
    print(json.dumps(verdict))
    sys.exit(0)

worktree = Path(argv[argv.index("--dir") + 1])
skill_present = (worktree / ".agents" / "skills" / "{_SKILL_NAME}").is_dir()

if skill_present:
    plan = {{
        "decision": "APPROVAL_REQUIRED",
        "findings": [
            {{
                "id": "f1",
                "location": "src/pyssa/controllers/delete_project_controller.py",
                "category": "imports",
                "summary": "Replace the wildcard `from math import *` with explicit named imports.",
            }},
            {{
                "id": "f2",
                "location": "src/pyssa/controllers/delete_project_controller.py tmp_dialog",
                "category": "naming",
                "summary": "Rename the illegal tmp_ binding tmp_dialog to a descriptive name.",
            }},
            {{
                "id": "f3",
                "location": "src/pyssa/controllers/delete_project_controller.py helper_panel",
                "category": "naming",
                "summary": "Rename class helper_panel to PascalCase HelperPanel.",
            }},
            {{
                "id": "f4",
                "location": "src/pyssa/controllers/delete_project_controller.py FormatData",
                "category": "naming",
                "summary": "Rename method FormatData to snake_case format_data.",
            }},
            {{
                "id": "f5",
                "location": "src/pyssa/controllers/delete_project_controller.py get_view",
                "category": "documentation",
                "summary": "Add a missing docstring to method get_view.",
            }},
            {{
                "id": "f6",
                "location": "src/pyssa/controllers/delete_project_controller.py __init__ a_parent",
                "category": "documentation",
                "summary": "Document the missing Args entry for parameter a_parent.",
            }},
        ],
    }}
else:
    # A generic reviewer with no Google-style-specific skill doesn't
    # necessarily flag these skill-specific violations.
    plan = {{"decision": "NO_CHANGES_NEEDED", "findings": []}}

(worktree / "audit-plan.json").write_text(json.dumps(plan), encoding="utf-8")
print(json.dumps({{"type": "text", "part": {{"text": "Wrote audit-plan.json."}}}}))
"""


class ArtifactSetRealSkillTests(unittest.TestCase):
    """`codev eval benchmark run` + `codev eval show`, driven through the
    real CLI dispatch, against real committed skill/task content copied into
    an isolated repository."""

    def setUp(self) -> None:
        self.assertTrue(
            _REAL_SKILL_DIR.is_dir(), f"fixture skill missing: {_REAL_SKILL_DIR}"
        )
        self.assertTrue(
            _REAL_TASK_DIR.is_dir(), f"fixture task missing: {_REAL_TASK_DIR}"
        )

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "repo"
        self.root.mkdir()

        def git(*args: str) -> None:
            subprocess.run(
                ["git", *args], cwd=self.root, check=True, capture_output=True
            )

        git("init", "-q")
        git("config", "user.email", "artifact-set-test@example.com")
        git("config", "user.name", "Artifact Set Test")

        skill_dest = self.root / ".agents" / "skills" / _SKILL_NAME
        skill_dest.parent.mkdir(parents=True)
        shutil.copytree(_REAL_SKILL_DIR, skill_dest)

        task_dest = self.root / ".codev" / "eval" / "tasks" / _TASK_NAME
        task_dest.parent.mkdir(parents=True)
        shutil.copytree(_REAL_TASK_DIR, task_dest)

        git("add", "-A")
        git("commit", "-q", "-m", "seed real skill and task")

        self.agent = self.root / "fake-agent.py"
        self.agent.write_text(_FAKE_AGENT, encoding="utf-8")
        self.agent.chmod(self.agent.stat().st_mode | 0o111)

        # Reset evals/ to one known, controlled file rather than trusting
        # whatever the live repo's own evals/ happens to contain right now
        # (it can and does accumulate real artifacts over time, e.g. from a
        # real `codev eval benchmark run` or `codev eval nvidia` invocation
        # against the actual skill) -- this test must stay deterministic
        # regardless of that. The point being checked -- packaging adds
        # alongside a different engine's pre-existing artifact, never
        # clobbers it -- only needs one such file to exist, not any
        # particular real one.
        self.evals_dir = skill_dest / "evals"
        if self.evals_dir.exists():
            shutil.rmtree(self.evals_dir)
        self.evals_dir.mkdir()
        (self.evals_dir / "evals.json").write_text(
            json.dumps({"synthetic": "pre-existing artifact from a different engine"}),
            encoding="utf-8",
        )

    def _run(self, argv: list[str]) -> tuple[int, str]:
        output = StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, output.getvalue()

    def test_full_benchmark_run_packages_a_real_trace_and_show_reads_it_back(
        self,
    ) -> None:
        output_dir = self.root.parent / "evidence"
        output_dir.mkdir()

        code, printed = self._run(
            [
                "eval",
                "benchmark",
                "run",
                _SKILL_NAME,
                "--target",
                str(self.root),
                "--output",
                str(output_dir),
                "--repetitions",
                "1",
                "--agent",
                str(self.agent),
            ]
        )
        self.assertEqual(0, code, printed)
        self.assertIn("phase-a-planning", printed)

        trace_path = self.evals_dir / "benchmark.json"
        self.assertTrue(trace_path.is_file())
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        self.assertEqual(_SKILL_NAME, trace["skill"])
        self.assertIn("generated_at", trace)
        category = trace["categories"]["phase-a-planning"]
        self.assertEqual(100.0, category["with_skill_percentage"])
        self.assertEqual(0.0, category["baseline_percentage"])
        self.assertEqual(100.0, category["delta"])

        markdown = (self.evals_dir / "BENCHMARK.md").read_text(encoding="utf-8")
        self.assertIn(_SKILL_NAME, markdown)
        self.assertIn("phase-a-planning", markdown)
        self.assertIn("+100.0pp", markdown)

        # A different engine's own artifact must survive packaging untouched.
        self.assertTrue((self.evals_dir / "evals.json").is_file())
        # The skill's own instructions are never modified by any of this.
        self.assertTrue(
            (self.root / ".agents" / "skills" / _SKILL_NAME / "SKILL.md").is_file()
        )

        show_code, show_printed = self._run(
            ["eval", "show", _SKILL_NAME, "--target", str(self.root)]
        )
        self.assertEqual(0, show_code)
        self.assertIn(f"Skill: {_SKILL_NAME}", show_printed)
        self.assertIn("phase-a-planning", show_printed)
        self.assertIn("+100.0pp", show_printed)
        # `codev eval show` resolves --target before building this path
        # (cli.py's _run_eval_show_command), which on Windows can expand an
        # 8.3 short alias (e.g. RUNNER~1) in the temp-dir prefix to its long
        # form -- resolve the same way here so the comparison isn't
        # comparing two spellings of the identical path.
        self.assertIn(str(trace_path.resolve()), show_printed)
        self.assertIn(trace["generated_at"], show_printed)

    def test_category_restricted_run_never_packages_and_show_reports_that(
        self,
    ) -> None:
        output_dir = self.root.parent / "evidence-scoped"
        output_dir.mkdir()

        code, _ = self._run(
            [
                "eval",
                "benchmark",
                "run",
                _SKILL_NAME,
                "--target",
                str(self.root),
                "--output",
                str(output_dir),
                "--repetitions",
                "1",
                "--category",
                "phase-a-planning",
                "--agent",
                str(self.agent),
            ]
        )
        self.assertEqual(0, code)
        # No benchmark.json/BENCHMARK.md written -- only evals.json (real,
        # pre-existing) is present.
        self.assertEqual(["evals.json"], [p.name for p in self.evals_dir.iterdir()])

        show_code, _ = self._run(
            ["eval", "show", _SKILL_NAME, "--target", str(self.root)]
        )
        self.assertEqual(1, show_code)

    def test_no_package_flag_skips_packaging_on_an_unrestricted_run(self) -> None:
        output_dir = self.root.parent / "evidence-no-package"
        output_dir.mkdir()

        code, _ = self._run(
            [
                "eval",
                "benchmark",
                "run",
                _SKILL_NAME,
                "--target",
                str(self.root),
                "--output",
                str(output_dir),
                "--repetitions",
                "1",
                "--no-package",
                "--agent",
                str(self.agent),
            ]
        )
        self.assertEqual(0, code)
        self.assertEqual(["evals.json"], [p.name for p in self.evals_dir.iterdir()])
        # The full report still landed in --output regardless.
        self.assertTrue((output_dir / "benchmark.json").is_file())


if __name__ == "__main__":
    unittest.main()
