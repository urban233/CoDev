from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codev_workflow.eval import EvaluationError
from codev_workflow.eval_environment import DockerEnvironment, WorktreeEnvironment


def _seed(root: Path) -> Path:
    seed = root / "seed-source"
    seed.mkdir()
    (seed / "file.txt").write_text("hello", encoding="utf-8")
    return seed


class WorktreeEnvironmentTests(unittest.TestCase):
    def test_create_returns_a_real_git_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = WorktreeEnvironment()
            worktree = environment.create(_seed(root))
            try:
                self.assertTrue((worktree / "file.txt").is_file())
                status = subprocess.run(
                    ["git", "-C", str(worktree), "status", "--porcelain"],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(0, status.returncode)
                self.assertEqual("", status.stdout)
            finally:
                environment.cleanup()

    def test_run_executes_in_the_created_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = WorktreeEnvironment()
            worktree = environment.create(_seed(root))
            try:
                result = environment.run(
                    [sys.executable, "-c", "print('ok')"], worktree, 10
                )
                self.assertEqual(0, result.code)
                self.assertIn("ok", result.stdout)
            finally:
                environment.cleanup()

    def test_capture_diff_reflects_changes_since_seed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = WorktreeEnvironment()
            worktree = environment.create(_seed(root))
            try:
                seed_commit = subprocess.run(
                    ["git", "-C", str(worktree), "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                (worktree / "file.txt").write_text("changed", encoding="utf-8")
                diff = environment.capture_diff(seed_commit)
                self.assertIn("file.txt", diff)
            finally:
                environment.cleanup()

    def test_cleanup_removes_the_worktree_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = WorktreeEnvironment()
            worktree = environment.create(_seed(root))
            environment.cleanup()
            self.assertFalse(worktree.exists())
            environment.cleanup()  # must not raise


class DockerEnvironmentTests(unittest.TestCase):
    def _fake_docker(self, root: Path, *, exit_code: int = 0) -> Path:
        executable = root / "fake-docker.py"
        log = root / "docker-calls.jsonl"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys, pathlib\n"
            f"log = pathlib.Path({str(log)!r})\n"
            "entry = {'argv': sys.argv[1:]}\n"
            "log.open('a').write(json.dumps(entry) + '\\n')\n"
            "sys.stdout.write('container output\\n')\n"
            f"sys.exit({exit_code!r})\n",
            encoding="utf-8",
        )
        executable.chmod(executable.stat().st_mode | 0o111)
        return executable

    def test_create_raises_when_docker_is_not_on_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = DockerEnvironment(
                image="some-image", docker="definitely-not-a-real-docker-xyz"
            )
            with self.assertRaises(EvaluationError):
                environment.create(_seed(root))

    def test_create_returns_the_same_worktree_shape_as_worktree_environment(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docker = self._fake_docker(root)
            with patch(
                "codev_workflow.eval_environment.shutil.which",
                return_value=str(docker),
            ):
                environment = DockerEnvironment(image="some-image", docker=str(docker))
                worktree = environment.create(_seed(root))
            try:
                self.assertTrue((worktree / "file.txt").is_file())
            finally:
                environment.cleanup()

    def test_run_wraps_argv_in_docker_run_with_cwd_mounted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docker = self._fake_docker(root)
            environment = DockerEnvironment(image="my-image:latest", docker=str(docker))
            cwd = root / "worktree"
            cwd.mkdir()
            result = environment.run(["opencode", "--dir", str(cwd), "prompt"], cwd, 10)
            self.assertEqual(0, result.code)
            self.assertIn("container output", result.stdout)
            calls = [
                __import__("json").loads(line)
                for line in (root / "docker-calls.jsonl").read_text().splitlines()
            ]
            self.assertEqual(1, len(calls))
            argv = calls[0]["argv"]
            self.assertEqual("run", argv[0])
            self.assertIn("--rm", argv)
            self.assertIn(f"{cwd}:/workspace", argv)
            self.assertIn("my-image:latest", argv)
            # the cwd argument to opencode's own --dir flag is remapped to the
            # container mount point, not left as the host path
            self.assertIn("/workspace", argv)
            self.assertNotIn(str(cwd), argv[argv.index("my-image:latest") + 1 :])

    def test_capture_diff_and_cleanup_delegate_to_worktree_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docker = self._fake_docker(root)
            with patch(
                "codev_workflow.eval_environment.shutil.which",
                return_value=str(docker),
            ):
                environment = DockerEnvironment(image="some-image", docker=str(docker))
                worktree = environment.create(_seed(root))
            seed_commit = subprocess.run(
                ["git", "-C", str(worktree), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
            ).stdout.strip()
            (worktree / "file.txt").write_text("changed", encoding="utf-8")
            diff = environment.capture_diff(seed_commit)
            self.assertIn("file.txt", diff)
            environment.cleanup()
            self.assertFalse(worktree.exists())


if __name__ == "__main__":
    unittest.main()
