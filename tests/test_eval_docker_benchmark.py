"""Real, live Docker end-to-end coverage for `codev eval benchmark run
--sandbox docker` (see docs/adr/0027-opt-in-docker-sandbox-for-the-native-
eval-harness.md), against the real bundled audit-google-python-style skill
and its real audit-google-python-style-demo task.

This builds and runs an actual local Docker image and actual containers --
not a fake `docker` executable stub (see tests/test_eval_environment.py for
that fast, no-Docker-required coverage of DockerEnvironment's own argv/mount
logic). It is the only place in this suite that needs a real, running
Docker; Docker support is explicitly opt-in, deferred-risk infrastructure
(ADR-0027), not a hard dependency of CoDev or of this test suite, so every
test here is skipped outright -- never failed -- when Docker isn't
available or isn't actually running where these tests execute.

Neither the real skill directory nor the real committed task is ever
mutated: both are copied into an isolated temporary repository, and only
that copy's task.json gains the environment block needed to opt into
Docker (the real, committed task intentionally has none).
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
_TASK_NAME = "audit-google-python-style-demo"
_REAL_SKILL_DIR = _REPO_ROOT / ".agents" / "skills" / _SKILL_NAME
_REAL_TASK_DIR = _REPO_ROOT / ".codev" / "eval" / "tasks" / _TASK_NAME
_BASE_IMAGE = "python:3.13-slim"
_IMAGE_TAG = "codev-eval-docker-benchmark-test:latest"

# Same fake-agent contract used elsewhere in this suite (actor vs. judge
# told apart by CoDev's own fixed judge prompt substring), except this one
# is baked into a real Docker image and genuinely executes inside a
# container for the actor call -- only the judge call (which always runs
# natively on the host; see ADR-0027's "actor-only" scoping) executes this
# same script directly.
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
        "summary": "Plan flags the private-helper docstring gap and requests approval.",
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
                "location": "pkg/reporter.py:_compute_average",
                "category": "documentation",
                "summary": "Private helper _compute_average has no docstring.",
            }}
        ],
    }}
else:
    plan = {{"decision": "NO_CHANGES_NEEDED", "findings": []}}

(worktree / "audit-plan.json").write_text(json.dumps(plan), encoding="utf-8")
print(json.dumps({{"type": "text", "part": {{"text": "Wrote audit-plan.json."}}}}))
"""


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


@unittest.skipUnless(
    _docker_available(),
    "real Docker not available/running -- Docker sandbox is opt-in "
    "infrastructure (ADR-0027), not a hard test dependency",
)
class DockerBenchmarkRealSkillTests(unittest.TestCase):
    """`codev eval benchmark run --sandbox docker`, driven through the real
    CLI dispatch, against real skill/task content and a real local
    container."""

    _build_tmp: tempfile.TemporaryDirectory[str]
    agent_script: Path

    @classmethod
    def setUpClass(cls) -> None:
        assert _REAL_SKILL_DIR.is_dir(), f"fixture skill missing: {_REAL_SKILL_DIR}"
        assert _REAL_TASK_DIR.is_dir(), f"fixture task missing: {_REAL_TASK_DIR}"

        cls._build_tmp = tempfile.TemporaryDirectory()
        build_context = Path(cls._build_tmp.name)
        cls.agent_script = build_context / "fake-agent.py"
        cls.agent_script.write_text(_FAKE_AGENT, encoding="utf-8")
        cls.agent_script.chmod(cls.agent_script.stat().st_mode | 0o111)

        # The image bakes a copy of the script in at the exact absolute
        # path it lives at on the host: DockerEnvironment.run only remaps
        # an argv element that is an *exact* match for the mounted
        # directory, never a subpath, so the actor executable name passed
        # to `docker run` must already resolve inside the image at
        # whatever literal path the host resolved it to.
        dockerfile = build_context / "Dockerfile"
        dockerfile.write_text(
            f"FROM {_BASE_IMAGE}\n"
            f"COPY fake-agent.py {cls.agent_script}\n"
            f"RUN chmod +x {cls.agent_script}\n",
            encoding="utf-8",
        )
        build = subprocess.run(
            [
                "docker",
                "build",
                "-t",
                _IMAGE_TAG,
                "-f",
                str(dockerfile),
                str(build_context),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if build.returncode != 0:
            cls._build_tmp.cleanup()
            raise RuntimeError(f"docker build failed:\n{build.stderr}")

    @classmethod
    def tearDownClass(cls) -> None:
        subprocess.run(
            ["docker", "rmi", "-f", _IMAGE_TAG], capture_output=True, timeout=60
        )
        cls._build_tmp.cleanup()

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "repo"
        self.root.mkdir()

        def git(*args: str) -> None:
            subprocess.run(
                ["git", *args], cwd=self.root, check=True, capture_output=True
            )

        git("init", "-q")
        git("config", "user.email", "docker-e2e-test@example.com")
        git("config", "user.name", "Docker E2E Test")

        skill_dest = self.root / ".agents" / "skills" / _SKILL_NAME
        skill_dest.parent.mkdir(parents=True)
        shutil.copytree(_REAL_SKILL_DIR, skill_dest)
        self.evals_dir = skill_dest / "evals"

        task_dest = self.root / ".codev" / "eval" / "tasks" / _TASK_NAME
        task_dest.parent.mkdir(parents=True)
        shutil.copytree(_REAL_TASK_DIR, task_dest)

        # Only the copy opts into Docker -- the real, committed task
        # intentionally declares no environment block.
        task_json_path = task_dest / "task.json"
        task_json = json.loads(task_json_path.read_text(encoding="utf-8"))
        task_json["environment"] = {"backend": "docker", "image": _IMAGE_TAG}
        task_json_path.write_text(json.dumps(task_json, indent=2), encoding="utf-8")

        git("add", "-A")
        git("commit", "-q", "-m", "seed real skill and docker-enabled task copy")

    def _run(self, argv: list[str]) -> tuple[int, str]:
        output = StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, output.getvalue()

    def test_benchmark_run_with_sandbox_docker_executes_real_containers(
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
                "--sandbox",
                "docker",
                "--agent",
                str(self.agent_script),
            ]
        )
        self.assertEqual(0, code, printed)

        category = "plan-phase-audit"
        with_skill_result = json.loads(
            (
                output_dir
                / _SKILL_NAME
                / category
                / _TASK_NAME
                / "with_skill"
                / "1"
                / "result.json"
            ).read_text(encoding="utf-8")
        )
        baseline_result = json.loads(
            (
                output_dir
                / _SKILL_NAME
                / category
                / _TASK_NAME
                / "baseline"
                / "1"
                / "result.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual("passed", with_skill_result["outcome"])
        self.assertEqual("failed", baseline_result["outcome"])
        # A real container invocation takes real wall-clock time to start --
        # this is not proof by itself, but it is corroborating evidence
        # that the actor call actually left the host process, rather than
        # the test accidentally falling back to running the script bare.
        self.assertGreater(with_skill_result["actor"]["duration_seconds"], 0.15)

        trace_path = self.evals_dir / "benchmark.json"
        self.assertTrue(trace_path.is_file())
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        self.assertEqual(100.0, trace["categories"][category]["with_skill_percentage"])
        self.assertEqual(0.0, trace["categories"][category]["baseline_percentage"])

        show_code, show_printed = self._run(
            ["eval", "show", _SKILL_NAME, "--target", str(self.root)]
        )
        self.assertEqual(0, show_code)
        self.assertIn("+100.0pp", show_printed)

    def test_benchmark_run_without_sandbox_flag_stays_on_the_host(self) -> None:
        """Same task, same image declared, but --sandbox defaults to
        worktree -- the environment block must never be used unless the
        caller explicitly opts in."""
        output_dir = self.root.parent / "evidence-worktree"
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
                str(self.agent_script),
            ]
        )
        self.assertEqual(0, code, printed)

        result = json.loads(
            (
                output_dir
                / _SKILL_NAME
                / "plan-phase-audit"
                / _TASK_NAME
                / "with_skill"
                / "1"
                / "result.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual("passed", result["outcome"])
        # Ran directly on the host (fast) rather than through `docker run`
        # (which needs real time to start a container).
        self.assertLess(result["actor"]["duration_seconds"], 0.3)


if __name__ == "__main__":
    unittest.main()
