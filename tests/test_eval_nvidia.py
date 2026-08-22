from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

from codev_workflow.eval import EvaluationError, _validate_bundle
from codev_workflow.eval_nvidia import available, run_verb

_TRACKED_ENV = (
    "SKILL_EVAL_LLM_PROVIDER",
    "OPENAI_API_KEY",
    "OPENCODE_API_KEY",
    "CODEV_TEST_DISALLOWED_SECRET",
)


class NvidiaEngineTests(unittest.TestCase):
    def _fake_skillevaluator(
        self,
        root: Path,
        *,
        exit_code: int = 0,
        stdout: str = "",
        stderr: str = "",
        sleep_seconds: float = 0.0,
        write_report: bool = True,
    ) -> tuple[Path, Path]:
        executable = root / "fake-skillevaluator.py"
        log = root / "calls.jsonl"
        script = (
            "#!/usr/bin/env python3\n"
            "import json, os, pathlib, sys, time\n"
            f"log = pathlib.Path({str(log)!r})\n"
            f"tracked = {_TRACKED_ENV!r}\n"
            "entry = {'argv': sys.argv[1:], "
            "'env': {k: os.environ[k] for k in tracked if k in os.environ}}\n"
            "log.open('a').write(json.dumps(entry) + '\\n')\n"
            f"if {sleep_seconds!r}:\n"
            f"    time.sleep({sleep_seconds!r})\n"
            "report_dir = None\n"
            "for flag in ('-o', '--results-dir'):\n"
            "    if flag in sys.argv:\n"
            "        report_dir = sys.argv[sys.argv.index(flag) + 1]\n"
            "        break\n"
            f"if report_dir and {write_report!r}:\n"
            "    pathlib.Path(report_dir).mkdir(parents=True, exist_ok=True)\n"
            "    (pathlib.Path(report_dir) / 'skillevaluator-output-fake.json')"
            ".write_text(json.dumps({'ok': True}))\n"
            f"sys.stdout.write({stdout!r})\n"
            f"sys.stderr.write({stderr!r})\n"
            f"sys.exit({exit_code!r})\n"
        )
        executable.write_text(script, encoding="utf-8")
        executable.chmod(executable.stat().st_mode | 0o111)
        return executable, log

    def _calls(self, log: Path) -> list[dict[str, Any]]:
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text().splitlines()]

    def test_unknown_verb_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with self.assertRaises(EvaluationError):
                run_verb("not-a-real-verb", output=output)

    def test_verb_requiring_target_without_one_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with self.assertRaises(EvaluationError):
                run_verb("validate", output=output)

    def test_missing_executable_raises_and_publishes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            with (
                patch(
                    "codev_workflow.eval_nvidia.EXECUTABLE",
                    "definitely-not-installed-xyz",
                ),
                self.assertRaises(EvaluationError),
            ):
                run_verb("quality-check", target=root, output=output)
            self.assertEqual([], list(output.iterdir()))

    def test_available_raises_with_install_hint(self) -> None:
        with patch(
            "codev_workflow.eval_nvidia.EXECUTABLE", "definitely-not-installed-xyz"
        ):
            with self.assertRaises(EvaluationError) as context:
                available()
            self.assertIn("uv tool install", str(context.exception))

    def test_output_must_be_existing_and_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable, _ = self._fake_skillevaluator(root)
            missing_output = root / "does-not-exist"
            with (
                patch("codev_workflow.eval_nvidia.EXECUTABLE", str(executable)),
                self.assertRaises(EvaluationError),
            ):
                run_verb("quality-check", target=root, output=missing_output)

            nonempty_output = root / "nonempty"
            nonempty_output.mkdir()
            (nonempty_output / "existing.txt").write_text("x", encoding="utf-8")
            with (
                patch("codev_workflow.eval_nvidia.EXECUTABLE", str(executable)),
                self.assertRaises(EvaluationError),
            ):
                run_verb("quality-check", target=root, output=nonempty_output)

    def test_docker_precondition_blocks_missing_docker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            executable, log = self._fake_skillevaluator(root)
            with (
                patch("codev_workflow.eval_nvidia.EXECUTABLE", str(executable)),
                patch("codev_workflow.eval_nvidia.shutil.which") as which,
            ):
                which.side_effect = lambda name: (
                    str(executable) if name == str(executable) else None
                )
                with (
                    redirect_stderr(StringIO()),
                    self.assertRaises(EvaluationError) as context,
                ):
                    run_verb(
                        "tier3-evaluate",
                        target=root,
                        output=output,
                        extra_flags=["--env-mode", "docker"],
                    )
            self.assertIn("docker", str(context.exception))
            self.assertEqual([], self._calls(log))

    def test_docker_precondition_also_blocks_the_glued_extra_form(self) -> None:
        # A user following this project's own "--extra=VALUE, not a space,
        # when VALUE starts with '-'" guidance could reasonably glue the
        # value on too (--extra=--env-mode=docker, one token) rather than
        # splitting it across two --extra flags. Both forms must be caught.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            executable, log = self._fake_skillevaluator(root)
            with (
                patch("codev_workflow.eval_nvidia.EXECUTABLE", str(executable)),
                patch("codev_workflow.eval_nvidia.shutil.which") as which,
            ):
                which.side_effect = lambda name: (
                    str(executable) if name == str(executable) else None
                )
                with (
                    redirect_stderr(StringIO()),
                    self.assertRaises(EvaluationError) as context,
                ):
                    run_verb(
                        "tier3-evaluate",
                        target=root,
                        output=output,
                        extra_flags=["--env-mode=docker"],
                    )
            self.assertIn("docker", str(context.exception))
            self.assertEqual([], self._calls(log))

    def test_env_allowlist_is_curated_not_passthrough(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            executable, log = self._fake_skillevaluator(root)
            with (
                patch("codev_workflow.eval_nvidia.EXECUTABLE", str(executable)),
                patch.dict(
                    "os.environ",
                    {
                        "SKILL_EVAL_LLM_PROVIDER": "nv_build",
                        "CODEV_TEST_DISALLOWED_SECRET": "must-not-leak",
                    },
                ),
            ):
                run_verb("quality-check", target=root, output=output)
            calls = self._calls(log)
            self.assertEqual(1, len(calls))
            self.assertEqual("nv_build", calls[0]["env"].get("SKILL_EVAL_LLM_PROVIDER"))
            self.assertNotIn("CODEV_TEST_DISALLOWED_SECRET", calls[0]["env"])

    def test_opencode_credentials_are_already_forwarded_by_the_shared_base(
        self,
    ) -> None:
        # isolated_subprocess_env's shared base (eval.py's _isolated_env)
        # already unconditionally allows OPENCODE_API_KEY -- the same
        # variable the native OpenCode-based harness forwards to its own
        # actor/judge -- so a Tier 3 run naming "opencode" as an agent can
        # pick up a user's existing OpenCode authentication with no
        # eval_nvidia-specific allowlist entry needed. This is true for
        # every verb, not only ones that name opencode as an agent.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            executable, log = self._fake_skillevaluator(root)
            with (
                patch("codev_workflow.eval_nvidia.EXECUTABLE", str(executable)),
                patch.dict("os.environ", {"OPENCODE_API_KEY": "secret-token"}),
            ):
                run_verb("quality-check", target=root, output=output)
            self.assertEqual(
                "secret-token", self._calls(log)[0]["env"].get("OPENCODE_API_KEY")
            )

    def test_exit_code_zero_maps_to_passed_and_publishes_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            executable, _ = self._fake_skillevaluator(root, exit_code=0)
            with patch("codev_workflow.eval_nvidia.EXECUTABLE", str(executable)):
                passed = run_verb("quality-check", target=root, output=output)
            self.assertTrue(passed)
            envelope = json.loads((output / "engine-result.json").read_text())
            self.assertEqual("passed", envelope["outcome"])
            self.assertEqual(0, envelope["process"]["exit_code"])
            _validate_bundle(output)

    def test_exit_code_nonzero_maps_to_failed_and_still_publishes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            executable, _ = self._fake_skillevaluator(root, exit_code=1)
            with patch("codev_workflow.eval_nvidia.EXECUTABLE", str(executable)):
                passed = run_verb("quality-check", target=root, output=output)
            self.assertFalse(passed)
            envelope = json.loads((output / "engine-result.json").read_text())
            self.assertEqual("failed", envelope["outcome"])
            self.assertEqual(1, envelope["process"]["exit_code"])
            _validate_bundle(output)

    def test_timeout_raises_and_publishes_error_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            executable, _ = self._fake_skillevaluator(root, sleep_seconds=2.0)
            with (
                patch("codev_workflow.eval_nvidia.EXECUTABLE", str(executable)),
                self.assertRaises(EvaluationError) as context,
            ):
                run_verb("quality-check", target=root, output=output, timeout_seconds=1)
            self.assertIn("timed out", str(context.exception))
            envelope = json.loads((output / "engine-result.json").read_text())
            self.assertEqual("error", envelope["outcome"])
            self.assertTrue(envelope["process"]["timeout"])
            _validate_bundle(output)

    def test_native_report_is_captured_and_flattened(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            executable, _ = self._fake_skillevaluator(root, write_report=True)
            with patch("codev_workflow.eval_nvidia.EXECUTABLE", str(executable)):
                run_verb("quality-check", target=root, output=output)
            captured = output / "native-report__skillevaluator-output-fake.json"
            self.assertTrue(captured.is_file())
            envelope = json.loads((output / "engine-result.json").read_text())
            self.assertIn(
                "report:skillevaluator-output-fake.json", envelope["artifacts"]
            )

    def test_stdout_secret_is_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            executable, _ = self._fake_skillevaluator(
                root, stdout="api_key=super-secret-value\n"
            )
            with patch("codev_workflow.eval_nvidia.EXECUTABLE", str(executable)):
                run_verb("quality-check", target=root, output=output)
            captured = (output / "nvidia-stdout.txt").read_text()
            self.assertNotIn("super-secret-value", captured)

    def test_tier3_verb_prints_notice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            executable, _ = self._fake_skillevaluator(root)
            with (
                patch("codev_workflow.eval_nvidia.EXECUTABLE", str(executable)),
                patch("codev_workflow.eval_nvidia.sys.stderr") as stderr,
            ):
                run_verb("validate", target=root, output=output)
            printed = "".join(call.args[0] for call in stderr.write.call_args_list)
            self.assertIn("Tier 3", printed)

    def test_verb_without_report_flag_never_passes_output_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            executable, log = self._fake_skillevaluator(root)
            with patch("codev_workflow.eval_nvidia.EXECUTABLE", str(executable)):
                run_verb("models", output=output)
            calls = self._calls(log)
            self.assertNotIn("-o", calls[0]["argv"])
            self.assertNotIn("--results-dir", calls[0]["argv"])

    def test_default_report_format_json_added_unless_overridden(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            executable, log = self._fake_skillevaluator(root)
            with patch("codev_workflow.eval_nvidia.EXECUTABLE", str(executable)):
                run_verb("quality-check", target=root, output=output)
            self.assertIn("json", self._calls(log)[0]["argv"])

            output2 = root / "output2"
            output2.mkdir()
            with patch("codev_workflow.eval_nvidia.EXECUTABLE", str(executable)):
                run_verb(
                    "quality-check",
                    target=root,
                    output=output2,
                    extra_flags=["-r", "cli"],
                )
            second_call = self._calls(log)[1]
            self.assertEqual(1, second_call["argv"].count("-r"))


if __name__ == "__main__":
    unittest.main()
