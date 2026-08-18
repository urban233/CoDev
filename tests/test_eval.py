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

import errno
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from codev_workflow.eval import (
    _COMMIT_MARKER,
    _PRIVATE_OWNER_MARKER,
    _PRIVATE_TRANSACTION_MARKER,
    _PRIVATE_TRANSACTIONS,
    _TRANSACTION_MARKER,
    EvaluationError,
    Run,
    _actor_artifacts,
    _capture_diff,
    _copy_seed_tree,
    _isolated_env,
    _judge_json,
    _manifest,
    _publish_artifact,
    _recover_output,
    _redact_text,
    _safe_process_output,
    _stage_skill,
    _sync_directory,
    _validate_bundle,
    _write_output,
    create_fixture,
    evaluate,
    run_snapshot,
    validate_fixture,
)
from codev_workflow.eval import (
    _copy_seed_tree as real_copy_seed_tree,
)
from codev_workflow.eval import (
    _git as eval_git,
)
from codev_workflow.eval import (
    _git as real_git,
)
from codev_workflow.eval import (
    _read_fixture_source as real_read_fixture_source,
)
from codev_workflow.eval import (
    _remove as real_remove,
)
from codev_workflow.eval import (
    _run as real_run,
)
from codev_workflow.eval import (
    _write_fixture_file as real_write_fixture_file,
)


class FixtureContractTests(unittest.TestCase):
    def _repo(self, root: Path) -> None:
        subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
        (root / "source.txt").write_text("seed", encoding="utf-8")
        # Matches create_fixture()'s starter "skill" placeholder, so
        # evaluate()'s default with_skill=True has something to stage
        # without every test needing to opt out or set up its own skill.
        skill_dir = root / ".agents" / "skills" / "replace-with-skill-name"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text("# Test skill\n", encoding="utf-8")

    def test_windows_directory_sync_uses_flush_file_buffers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kernel32 = Mock()
            kernel32.CreateFileW.return_value = 123
            kernel32.FlushFileBuffers.return_value = True
            with (
                patch("codev_workflow.eval.sys.platform", "win32"),
                patch(
                    "codev_workflow.eval.ctypes.WinDLL",
                    return_value=kernel32,
                    create=True,
                ),
            ):
                _sync_directory(Path(directory))
            kernel32.CreateFileW.assert_called_once()
            self.assertEqual(0xC0000000, kernel32.CreateFileW.call_args.args[1])
            kernel32.FlushFileBuffers.assert_called_once_with(123)
            kernel32.CloseHandle.assert_called_once_with(123)

    def test_create_writes_selected_seed_and_strict_starter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            self.assertEqual("seed", (fixture / "repository/source.txt").read_text())
            self.assertEqual("sample", validate_fixture(fixture).name)

    def test_create_preserves_binary_regular_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            binary = root / "image.bin"
            contents = bytes([0, 159, 255, 1, 2])
            binary.write_bytes(contents)
            fixture = create_fixture("binary", root, ["image.bin"])
            self.assertEqual(contents, (fixture / "repository/image.bin").read_bytes())
            self.assertEqual("binary", validate_fixture(fixture).name)

    def test_seed_copy_rejects_external_symlink_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "repository"
            source.mkdir()
            original = source / "source.txt"
            original.write_text("seed", encoding="utf-8")
            external = root / "external.txt"
            external.write_text("external", encoding="utf-8")
            destination = root / "seed"
            calls = 0

            def replace_on_copy(
                path: Path, expected_identity: tuple[int, int], expected_digest: str
            ) -> bytes:
                nonlocal calls
                calls += 1
                if calls == 2:
                    original.unlink()
                    original.symlink_to(external)
                return real_read_fixture_source(
                    path, expected_identity, expected_digest
                )

            with (
                patch(
                    "codev_workflow.eval._read_fixture_source",
                    side_effect=replace_on_copy,
                ),
                self.assertRaises(EvaluationError),
            ):
                _copy_seed_tree(source, destination)

    def test_evaluation_rejects_prompt_mutation_before_actor_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            output = root.parent / f"evidence-{root.name}"
            output.mkdir()
            sentinel = root / "actor-ran"
            actor = root / "actor.py"
            actor.write_text(
                "#!/usr/bin/env python3\n"
                "from pathlib import Path\n"
                f"Path({str(sentinel)!r}).write_text('ran')\n"
                "print('{}')\n",
                encoding="utf-8",
            )
            actor.chmod(actor.stat().st_mode | 0o111)
            real_prompt = fixture / "prompt.md"

            def mutate_after_seed(source: Path, destination: Path) -> None:
                real_copy_seed_tree(source, destination)
                original_stat = real_prompt.stat()
                real_prompt.write_text("x" * original_stat.st_size, encoding="utf-8")
                os.utime(
                    real_prompt,
                    ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
                )

            with (
                patch(
                    "codev_workflow.eval._copy_seed_tree", side_effect=mutate_after_seed
                ),
                self.assertRaises(EvaluationError),
            ):
                evaluate("sample", root, output, opencode=str(actor))
            self.assertFalse(sentinel.exists())
            self.assertEqual(
                "error", json.loads((output / "result.json").read_text())["outcome"]
            )

    def test_windows_fixture_branch_is_portable_when_mocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            with (
                patch("codev_workflow.eval.sys.platform", "win32"),
                patch(
                    "codev_workflow.eval._read_windows_source",
                    return_value=(
                        b"seed",
                        (
                            os.stat(root / "source.txt").st_dev,
                            os.stat(root / "source.txt").st_ino,
                        ),
                    ),
                ),
                patch("codev_workflow.eval._windows_reparse_safe"),
            ):
                fixture = create_fixture("windows-branch", root, ["source.txt"])
            self.assertEqual("seed", (fixture / "repository/source.txt").read_text())

    def test_execution_environment_is_allowlisted(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PATH": "/safe/bin",
                "HOME": "/safe/home",
                "OPENCODE_API_KEY": "secret",
                "HOST_SECRET": "must-not-leak",
            },
            clear=True,
        ):
            environment = _isolated_env()
        # PATH is prepended with sys.executable's own directory (guarantees a
        # working "python"/"python3" for fixture verifiers), so it no longer
        # equals the original value verbatim -- it must still end with it.
        self.assertTrue(environment["PATH"].endswith(os.pathsep + "/safe/bin"))
        self.assertIn(str(Path(sys.executable).resolve().parent), environment["PATH"])
        self.assertEqual("/safe/home", environment["HOME"])
        self.assertEqual("secret", environment["OPENCODE_API_KEY"])
        self.assertNotIn("HOST_SECRET", environment)

    def test_windows_source_reparse_replacement_fails_safely(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            with (
                patch("codev_workflow.eval.sys.platform", "win32"),
                patch(
                    "codev_workflow.eval._read_windows_source",
                    side_effect=EvaluationError("reparse point rejected"),
                ),
                patch("codev_workflow.eval._windows_reparse_safe"),
                self.assertRaises(EvaluationError),
            ):
                create_fixture("windows-reparse", root, ["source.txt"])
            self.assertFalse((root / ".codev/fixtures/windows-reparse").exists())

    def test_create_rejects_traversal_symlink_exclusion_and_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            outside = root.parent / "outside.txt"
            outside.write_text("outside", encoding="utf-8")
            for include in ["../outside.txt", ".git"]:
                with self.assertRaises(EvaluationError):
                    create_fixture("unsafe", root, [include])
            (root / "link").symlink_to(outside)
            with self.assertRaises(EvaluationError):
                create_fixture("linked", root, ["link"])
            inside = root / "inside"
            inside.mkdir()
            (inside / "file.txt").write_text("inside", encoding="utf-8")
            (root / "inside-file-link").symlink_to(inside / "file.txt")
            (root / "inside-dir-link").symlink_to(inside, target_is_directory=True)
            for name in ["inside-file-link", "inside-dir-link"]:
                with self.assertRaises(EvaluationError):
                    create_fixture(f"linked-{name}", root, [name])
            create_fixture("same", root, ["source.txt"])
            with self.assertRaises(EvaluationError):
                create_fixture("same", root, ["source.txt"])

    def test_create_rejects_recursive_destination_self_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            (root / ".codev/fixtures").mkdir(parents=True)
            with self.assertRaises(EvaluationError):
                create_fixture("recursive", root, [".codev"])

    def test_create_rejects_duplicate_directory_and_nested_file_includes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            (root / "src").mkdir()
            (root / "src/file.txt").write_text("file", encoding="utf-8")
            with self.assertRaises(EvaluationError):
                create_fixture("duplicate-dir", root, ["src", "src"])
            with self.assertRaises(EvaluationError):
                create_fixture("duplicate-nested", root, ["src", "src/file.txt"])

    def test_create_case_variant_destinations_follow_filesystem_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            (root / "Case.txt").write_text("upper", encoding="utf-8")
            (root / "case.txt").write_text("lower", encoding="utf-8")
            with self.assertRaises(EvaluationError):
                create_fixture("case-variant", root, ["Case.txt", "case.txt"])

    def test_create_rejects_case_variant_fixture_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            create_fixture("Foo", root, ["source.txt"])
            with self.assertRaises(EvaluationError):
                create_fixture("foo", root, ["source.txt"])

    def test_validation_rejects_unknown_fields_and_invalid_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            metadata = json.loads((fixture / "fixture.json").read_text())
            metadata["unexpected"] = True
            (fixture / "fixture.json").write_text(json.dumps(metadata))
            with self.assertRaises(EvaluationError):
                validate_fixture(fixture)

    def test_schema_versions_reject_boolean_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            identity = json.loads((fixture / "fixture.json").read_text())
            identity["schema_version"] = True
            (fixture / "fixture.json").write_text(json.dumps(identity))
            with self.assertRaises(EvaluationError):
                validate_fixture(fixture)
            identity["schema_version"] = 1
            (fixture / "fixture.json").write_text(json.dumps(identity))
            verifier = json.loads((fixture / "verifier.json").read_text())
            verifier["schema_version"] = True
            (fixture / "verifier.json").write_text(json.dumps(verifier))
            with self.assertRaises(EvaluationError):
                validate_fixture(fixture)

    def test_verifier_rejects_nul_argument(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            verifier = json.loads((fixture / "verifier.json").read_text())
            verifier["command"] = ["python\x00bad"]
            (fixture / "verifier.json").write_text(json.dumps(verifier))
            with self.assertRaises(EvaluationError):
                validate_fixture(fixture)

    def test_persisted_evidence_redacts_process_and_json_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            verifier_code = (
                "import sys; "
                "print('{'+chr(34)+'client_token_value'+chr(34)+':'+chr(34)"
                "+'verifier-compound'+chr(34)+','+chr(34)+'ordinary'+chr(34)"
                "+':'+chr(34)+'keep'+chr(34)+'}'); "
                "print('{'+chr(34)+'secret_value'+chr(34)+':'+chr(34)"
                "+'verifier-error'+chr(34)+'}', file=sys.stderr)"
            )
            (fixture / "verifier.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "command": [sys.executable, "-c", verifier_code],
                        "timeout_seconds": 5,
                    }
                )
            )
            output = root.parent / f"evidence-{root.name}"
            output.mkdir()
            actor = root / "secret-actor.py"
            judge = json.dumps(
                {
                    "schema_version": 1,
                    "verdict": "pass",
                    "summary": '{"passwordHint":"judge-compound","ordinary":"keep"}',
                    "findings": [
                        {
                            "criterion": "C1",
                            "verdict": "pass",
                            "evidence": "credential=judge-secret",
                        }
                    ],
                }
            )
            actor.write_text(
                "#!/usr/bin/env python3\n"
                "import json, pathlib, sys\n"
                "if 'Review rubric' in sys.argv[-1]:\n"
                "    secrets = ('actor-secret', 'verifier-secret')\n"
                "    if any(\n"
                "        secret in p.read_text(errors='ignore')\n"
                "        for p in pathlib.Path.cwd().rglob('*')\n"
                "        if p.is_file()\n"
                "        for secret in secrets\n"
                "    ):\n"
                "        raise SystemExit(9)\n"
                f"    print({judge!r})\n"
                "else:\n"
                "    payload = {'privateKeyMaterial': 'actor-compound', "
                "'ordinary': 'keep'}\n"
                "    inner = json.dumps(payload, separators=(',', ':'))\n"
                "    print(json.dumps({'type': 'text', 'part': {'text': inner}}))\n"
                "    print('Bearer actor-bearer', file=sys.stderr)\n"
                "    print('{}')\n",
                encoding="utf-8",
            )
            actor.chmod(actor.stat().st_mode | 0o111)
            self.assertTrue(evaluate("sample", root, output, opencode=str(actor)))
            actor_output = (output / "actor-output.txt").read_text(encoding="utf-8")
            self.assertIn("keep", actor_output)
            self.assertNotIn("actor-compound", actor_output)
            for path in output.iterdir():
                if path.is_file():
                    content = path.read_text(encoding="utf-8")
                    self.assertNotIn("actor-secret", content)
                    self.assertNotIn("verifier-secret", content)
                    self.assertNotIn("judge-secret", content)
                    self.assertNotIn("actor-json-secret", content)
                    self.assertNotIn("verifier-json-secret", content)
                    self.assertNotIn("judge-json-secret", content)
                    self.assertNotIn("actor-compound", content)
                    self.assertNotIn("verifier-compound", content)
                    self.assertNotIn("judge-compound", content)
                    self.assertNotIn("actor-bearer", content)
                    if path.name not in {
                        "result.json",
                        "diff.patch",
                        ".codev-eval-commit.json",
                        "verifier-stderr.txt",
                        "actor-output.txt",
                    }:
                        self.assertIn("keep", content)

    def test_parser_sanitizes_compound_json_secret_keys_and_types(self) -> None:
        payload = json.dumps(
            {
                "PASSWORD_HINT": 42,
                "client_token_value": True,
                "secret-value": None,
                "privateKeyMaterial": ["private-material-secret", 7],
                "AWS_SECRET_ACCESS_KEY": {"nested": "aws-secret"},
                "ordinary": {"key": "keep", "monkey": "keep"},
                "escaped": '{"accessToken":"escaped-json-secret"}',
            }
        )
        sanitized = _redact_text(payload)
        for secret in (
            "42",
            "true",
            "null",
            "private-material-secret",
            "7",
            "escaped-json-secret",
            "aws-secret",
        ):
            self.assertNotIn(secret, sanitized)
        self.assertIn('"ordinary": {"key": "keep", "monkey": "keep"}', sanitized)

    def test_actor_verifier_and_judge_receive_isolated_git_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            protected = root / "protected.txt"
            protected.write_text("local change", encoding="utf-8")
            fixture = create_fixture("sample", root, ["source.txt"])
            phase = root / "phase.py"
            verdict = json.dumps(
                {
                    "schema_version": 1,
                    "verdict": "pass",
                    "summary": "ok",
                    "findings": [
                        {"criterion": "C1", "verdict": "pass", "evidence": "ok"}
                    ],
                }
            )
            phase.write_text(
                "#!/usr/bin/env python3\n"
                "import json, pathlib, subprocess, sys\n"
                "phase = (\n"
                "    'judge'\n"
                "    if 'Review rubric' in sys.argv[-1]\n"
                "    else ('verifier' if 'verifier' in sys.argv[1:] else 'actor')\n"
                ")\n"
                "top = subprocess.run(\n"
                "    ['git', 'rev-parse', '--show-toplevel'],\n"
                "    capture_output=True,\n"
                "    text=True,\n"
                ")\n"
                "log = {\n"
                "    'phase': phase,\n"
                "    'git': top.stdout.strip(),\n"
                "    'git_dir': 'GIT_DIR' in __import__('os').environ,\n"
                "}\n"
                "pathlib.Path('phase-log.txt').write_text(json.dumps(log))\n"
                "subprocess.run(\n"
                "    ['git', 'reset', '--hard'], check=False, capture_output=True\n"
                ")\n"
                "if phase == 'judge':\n"
                f"    print({verdict!r})\n"
                "elif phase == 'actor':\n"
                "    print(json.dumps({'type': 'text', 'part': {'text': 'ok'}}))\n"
                "else:\n"
                "    print('verifier')\n",
                encoding="utf-8",
            )
            phase.chmod(phase.stat().st_mode | 0o111)
            (fixture / "verifier.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "command": [str(phase), "verifier"],
                        "timeout_seconds": 5,
                    }
                )
            )
            output = root.parent / f"evidence-{root.name}"
            output.mkdir()
            with patch.dict(
                os.environ,
                {
                    "GIT_DIR": str(root / ".git"),
                    "GIT_WORK_TREE": str(root),
                    "GIT_INDEX_FILE": str(root / ".git/index"),
                },
            ):
                self.assertTrue(evaluate("sample", root, output, opencode=str(phase)))
            self.assertEqual("local change", protected.read_text())

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_successful_phase_cleanup_terminates_child_processes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            (fixture / "verifier.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "command": [sys.executable, "-c", "pass"],
                        "timeout_seconds": 5,
                    }
                )
            )
            output = root.parent / f"evidence-{root.name}"
            output.mkdir()
            late = root / "late-child-output.txt"
            actor = root / "actor.py"
            verdict = json.dumps(
                {
                    "schema_version": 1,
                    "verdict": "pass",
                    "summary": "ok",
                    "findings": [
                        {"criterion": "C1", "verdict": "pass", "evidence": "ok"}
                    ],
                }
            )
            actor.write_text(
                "#!/usr/bin/env python3\n"
                "import pathlib, subprocess, sys, time\n"
                "if 'Review rubric' in sys.argv[-1]:\n"
                "    if any(\n"
                "        p.name == 'unknown-secret.blob'\n"
                "        for p in pathlib.Path.cwd().rglob('*')\n"
                "    ):\n"
                "        raise SystemExit(9)\n"
                f"    print({verdict!r})\n"
                "else:\n"
                "    child = pathlib.Path('child.py')\n"
                "    child.write_text(\n"
                "        'import pathlib, sys, time; time.sleep(2); '\n"
                "        'pathlib.Path(sys.argv[1]).write_text(\"late\")'\n"
                "    )\n"
                "    subprocess.Popen(\n"
                f"        [sys.executable, str(child), {str(late)!r}],\n"
                "        stdout=subprocess.DEVNULL,\n"
                "        stderr=subprocess.DEVNULL,\n"
                "    )\n"
                "    print('{}')\n",
                encoding="utf-8",
            )
            actor.chmod(actor.stat().st_mode | 0o111)
            self.assertTrue(evaluate("sample", root, output, opencode=str(actor)))
            time.sleep(0.2)
            self.assertFalse(late.exists())

    def test_judge_rejects_false_pass_from_unrelated_or_extra_output(self) -> None:
        valid = json.dumps(
            {
                "schema_version": 1,
                "verdict": "pass",
                "summary": "complete",
                "findings": [
                    {"criterion": "C1", "verdict": "pass", "evidence": "diff"}
                ],
            }
        )
        for output in (f"noise\n{valid}", f"{valid}\nnoise", f"{{}}\n{valid}"):
            with self.assertRaises(EvaluationError):
                _judge_json(output)

    def test_judge_accepts_one_explicit_text_event(self) -> None:
        valid = json.dumps(
            {
                "schema_version": 1,
                "verdict": "fail",
                "summary": "defect",
                "findings": [
                    {"criterion": "C1", "verdict": "fail", "evidence": "missing"}
                ],
            }
        )
        event = json.dumps({"type": "text", "part": {"text": valid}})
        self.assertEqual("fail", _judge_json(event)["verdict"])

    def test_judge_rejects_boolean_schema_version(self) -> None:
        value = {
            "schema_version": True,
            "verdict": "pass",
            "summary": "complete",
            "findings": [
                {"criterion": "C1", "verdict": "pass", "evidence": "observed"}
            ],
        }
        with self.assertRaises(EvaluationError):
            _judge_json(json.dumps(value))

    def test_judge_rejects_non_string_verdict_values(self) -> None:
        for top_level in (["pass"], {"verdict": "pass"}):
            value = {
                "schema_version": 1,
                "verdict": top_level,
                "summary": "complete",
                "findings": [
                    {"criterion": "C1", "verdict": "pass", "evidence": "observed"}
                ],
            }
            with self.assertRaises(EvaluationError):
                _judge_json(json.dumps(value))
        for finding_verdict in (["pass"], {"verdict": "pass"}):
            finding_value: dict[str, object] = {
                "schema_version": 1,
                "verdict": "pass",
                "summary": "complete",
                "findings": [
                    {
                        "criterion": "C1",
                        "verdict": finding_verdict,
                        "evidence": "observed",
                    }
                ],
            }
            with self.assertRaises(EvaluationError):
                _judge_json(json.dumps(finding_value))

    def test_judge_rejects_non_string_event_type(self) -> None:
        event_types: tuple[list[object], dict[str, object]] = ([], {})
        for event_type in event_types:
            with self.assertRaises(EvaluationError):
                _judge_json(json.dumps({"type": event_type}))

    def test_actor_events_and_final_output_are_separate(self) -> None:
        raw = "\n".join(
            [
                json.dumps({"type": "step_start"}),
                json.dumps({"type": "text", "part": {"text": "final answer"}}),
                json.dumps({"type": "step_finish"}),
            ]
        )
        events, output = _actor_artifacts(raw)
        self.assertTrue(events.endswith("\n"))
        self.assertIn('"step_start"', events)
        self.assertEqual("final answer", output)

    def test_structured_artifacts_sanitize_nested_urls_and_escaped_values(self) -> None:
        raw = json.dumps(
            {
                "type": "text",
                "part": {
                    "text": json.dumps(
                        {
                            "nested": {"accessToken": "secret-token"},
                            "url": "https://user:password@example.test/api?api_key=secret-key&ok=yes",
                        }
                    )
                },
            }
        )
        events, _ = _actor_artifacts(raw)
        self.assertNotIn("secret-token", events)
        self.assertNotIn("password@example.test", events)
        self.assertNotIn("secret-key", events)
        self.assertIn("[REDACTED_SECRET]", events)

    def test_unstructured_process_output_preserves_safe_diagnostics_and_redacts_secrets(
        self,
    ) -> None:
        safe = _safe_process_output("plain diagnostic\nBearer secret-token\n")
        self.assertIn("plain diagnostic", safe)
        self.assertNotIn("secret-token", safe)
        self.assertIn("[REDACTED]", safe)
        url_diagnostic = _safe_process_output(
            "url=https://user:secret-password@example.test/path?token=secret-token&safe=yes&clientKey=secret-key"
        )
        self.assertIn(
            "https://user:[REDACTED_SECRET]@example.test/path", url_diagnostic
        )
        self.assertIn("safe=yes", url_diagnostic)
        self.assertNotIn("secret-password", url_diagnostic)
        self.assertNotIn("secret-token", url_diagnostic)
        self.assertNotIn("secret-key", url_diagnostic)
        malformed = _safe_process_output('{"password":"secret-password"\n')
        self.assertIn("{", malformed)
        self.assertNotIn("secret-password", malformed)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires os.mkfifo")
    def test_validation_rejects_special_repository_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            fifo = fixture / "repository/fifo"
            getattr(os, "mkfifo")(fifo)  # noqa: B009 -- not in stubs on all platforms
            with self.assertRaises(EvaluationError):
                validate_fixture(fixture)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires os.mkfifo")
    def test_validation_rejects_special_contract_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            prompt = fixture / "prompt.md"
            prompt.unlink()
            getattr(os, "mkfifo")(prompt)  # noqa: B009 -- not in stubs on all platforms
            with self.assertRaises(EvaluationError):
                validate_fixture(fixture)

    def test_recovery_rejects_traversal_and_symlink_manifest_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            outside = output.parent / "outside-evidence.txt"
            outside.write_text("keep", encoding="utf-8")
            marker = output / ".codev-eval-transaction.json"
            marker.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "bundle_id": "x",
                        "artifacts": [
                            {
                                "path": "../outside-evidence.txt",
                                "size": 4,
                                "sha256": "x",
                            }
                        ],
                    }
                )
            )
            with self.assertRaises(EvaluationError):
                _recover_output(output)
            marker.unlink()
            (output / "link").symlink_to(outside)
            marker.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "bundle_id": "x",
                        "artifacts": [{"path": "link", "size": 4, "sha256": "x"}],
                    }
                )
            )
            with self.assertRaises(EvaluationError):
                _recover_output(output)
            self.assertEqual("keep", outside.read_text())

    def test_recovery_preserves_unowned_staging_prefix_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            owned_looking = output / ".codev-eval-stage-preexisting"
            owned_looking.mkdir()
            payload = owned_looking / "keep.txt"
            payload.write_text("keep", encoding="utf-8")
            _recover_output(output)
            self.assertEqual("keep", payload.read_text())

    def test_recovery_rejects_unowned_output_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            stage = output / ".codev-eval-stage-owned"
            stage.mkdir()
            data = {
                "schema_version": 1,
                "bundle_id": "x",
                "stage_id": stage.name,
                "artifacts": [{"path": "owned.txt", "size": 0, "sha256": "0" * 64}],
            }
            (stage / ".codev-eval-transaction.json").write_text(json.dumps(data))
            (output / ".codev-eval-transaction.json").write_text(json.dumps(data))
            keep = output / "caller-owned.txt"
            keep.write_text("keep", encoding="utf-8")
            with self.assertRaises(EvaluationError):
                _recover_output(output)
            self.assertEqual("keep", keep.read_text())

    def test_recovery_preserves_complete_committed_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            _write_output(output, {"result.json": "complete"})
            marker = json.loads((output / ".codev-eval-commit.json").read_text())
            stage = output / ".codev-eval-stage-crash"
            stage.mkdir()
            transaction = {
                "schema_version": 1,
                "bundle_id": marker["bundle_id"],
                "stage_id": stage.name,
                "artifacts": marker["artifacts"],
            }
            (stage / ".codev-eval-transaction.json").write_text(json.dumps(transaction))
            (output / ".codev-eval-transaction.json").write_text(
                json.dumps(transaction)
            )
            with self.assertRaises(EvaluationError):
                _recover_output(output)
            self.assertEqual("complete", (output / "result.json").read_text())
            self.assertTrue(stage.exists())
            self.assertTrue((output / ".codev-eval-transaction.json").exists())

    def test_recovery_rejects_mismatched_transaction_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            _write_output(output, {"result.json": "complete"})
            marker = json.loads((output / ".codev-eval-commit.json").read_text())
            stage = output / ".codev-eval-stage-crash"
            stage.mkdir()
            transaction = {
                "schema_version": 1,
                "bundle_id": "different-bundle",
                "stage_id": stage.name,
                "artifacts": marker["artifacts"],
            }
            (stage / ".codev-eval-transaction.json").write_text(json.dumps(transaction))
            (output / ".codev-eval-transaction.json").write_text(
                json.dumps(transaction)
            )
            with self.assertRaises(EvaluationError):
                _recover_output(output)
            self.assertEqual("complete", (output / "result.json").read_text())
            self.assertTrue((output / ".codev-eval-commit.json").exists())
            self.assertTrue((output / ".codev-eval-transaction.json").exists())
            self.assertTrue(stage.exists())

    def test_recovery_ignores_forged_output_markers_and_preserves_caller_files(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            caller_file = output / "caller-owned.txt"
            caller_file.write_text("do not delete", encoding="utf-8")
            digest = hashlib.sha256(caller_file.read_bytes()).hexdigest()
            transaction = {
                "schema_version": 1,
                "bundle_id": "forged",
                "stage_id": ".codev-eval-stage-forged",
                "artifacts": [
                    {
                        "path": caller_file.name,
                        "size": caller_file.stat().st_size,
                        "sha256": digest,
                    }
                ],
            }
            (output / _TRANSACTION_MARKER).write_text(json.dumps(transaction))
            (output / _COMMIT_MARKER).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "bundle_id": "forged",
                        "artifacts": transaction["artifacts"],
                    }
                )
            )
            with self.assertRaises(EvaluationError):
                _recover_output(output)
            self.assertEqual("do not delete", caller_file.read_text())
            self.assertEqual(3, len(list(output.iterdir())))

    def test_recovery_ignores_foreign_and_stale_private_markers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            foreign = Path(tempfile.mkdtemp(prefix=".codev-eval-private-"))
            stale = Path(tempfile.mkdtemp(prefix=".codev-eval-private-"))
            try:
                (foreign / _PRIVATE_OWNER_MARKER).write_text("not valid metadata")
                _PRIVATE_TRANSACTIONS[str(output.resolve())] = (stale, "stale-token")
                (stale / _PRIVATE_OWNER_MARKER).write_text("malformed stale marker")
                _recover_output(output)
                self.assertTrue(foreign.exists())
                self.assertTrue(stale.exists())
            finally:
                _PRIVATE_TRANSACTIONS.pop(str(output.resolve()), None)
                shutil.rmtree(foreign, ignore_errors=True)
                shutil.rmtree(stale, ignore_errors=True)

    def test_recovery_finds_authenticated_orphan_after_registry_reset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            private = Path(tempfile.mkdtemp(prefix=".codev-eval-private-"))
            stage = private / "stage"
            stage.mkdir()
            manifest = _manifest({"result.json": "orphan"})
            data = {
                "schema_version": 1,
                "bundle_id": "orphan-bundle",
                "transaction_id": "orphan-transaction",
                "stage_id": "stage",
                "output": str(output.resolve()),
                "artifacts": manifest,
                "owned_artifacts": manifest,
            }
            (stage / "result.json").write_text("orphan")
            owner = private / _PRIVATE_OWNER_MARKER
            owner.write_text(json.dumps(data))
            owner.chmod(0o600)
            transaction = private / _PRIVATE_TRANSACTION_MARKER
            transaction.write_text(json.dumps(data))
            transaction.chmod(0o600)
            _PRIVATE_TRANSACTIONS.clear()
            _recover_output(output)
            self.assertFalse(private.exists())

    def test_recovery_removes_authenticated_partially_published_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            output.mkdir(exist_ok=True)
            private = Path(tempfile.mkdtemp(prefix=".codev-eval-private-"))
            stage = private / "stage"
            stage.mkdir()
            manifest = _manifest({"result.json": "published", "second.json": "staged"})
            (output / "result.json").write_text("published")
            (stage / "second.json").write_text("staged")
            data = {
                "schema_version": 1,
                "bundle_id": "partial-bundle",
                "transaction_id": "partial-transaction",
                "stage_id": "stage",
                "output": str(output.resolve()),
                "artifacts": manifest,
                "owned_artifacts": manifest,
            }
            owner = private / _PRIVATE_OWNER_MARKER
            owner.write_text(json.dumps(data))
            owner.chmod(0o600)
            transaction = private / _PRIVATE_TRANSACTION_MARKER
            transaction.write_text(json.dumps(data))
            transaction.chmod(0o600)
            _recover_output(output)
            self.assertFalse((output / "result.json").exists())
            self.assertFalse(private.exists())

    def test_recovery_ignores_authenticated_marker_with_malformed_manifest_entry(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            private = Path(tempfile.mkdtemp(prefix=".codev-eval-private-"))
            stage = private / "stage"
            stage.mkdir()
            malformed = [
                {"path": "result.json", "size": "not-an-int", "sha256": "0" * 64}
            ]
            data = {
                "schema_version": 1,
                "bundle_id": "malformed-bundle",
                "transaction_id": "malformed-transaction",
                "stage_id": "stage",
                "output": str(output.resolve()),
                "artifacts": malformed,
                "owned_artifacts": malformed,
            }
            owner = private / _PRIVATE_OWNER_MARKER
            owner.write_text(json.dumps(data))
            owner.chmod(0o600)
            transaction = private / _PRIVATE_TRANSACTION_MARKER
            transaction.write_text(json.dumps(data))
            transaction.chmod(0o600)
            _recover_output(output)
            self.assertTrue(private.exists())
            shutil.rmtree(private)

    def test_marker_rejects_invalid_size_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "result.json").write_text("x", encoding="utf-8")
            for size, digest in ((True, "0" * 64), (1, "bad")):
                marker = {
                    "schema_version": 1,
                    "bundle_id": "x",
                    "artifacts": [
                        {"path": "result.json", "size": size, "sha256": digest}
                    ],
                }
                (output / ".codev-eval-commit.json").write_text(json.dumps(marker))
                with self.assertRaises(EvaluationError):
                    _validate_bundle(output)

    def test_git_commands_ignore_active_repository_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            sandbox = root / "sandbox"
            subprocess.run(
                ["git", "init", str(sandbox)], check=True, capture_output=True
            )
            with patch.dict(
                os.environ, {"GIT_DIR": str(root / ".git"), "GIT_WORK_TREE": str(root)}
            ):
                result = eval_git("git", ["rev-parse", "--show-toplevel"], sandbox)
            self.assertEqual(0, result.code)
            self.assertEqual(sandbox.resolve(), Path(result.stdout.strip()).resolve())

    def test_git_commands_ignore_hostile_global_hook_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            sandbox = root / "sandbox"
            hook_dir = root / "hooks"
            hook_dir.mkdir()
            hook = hook_dir / "pre-commit"
            hook.write_text(f"#!/bin/sh\ntouch {root / 'hook-ran'}\n", encoding="utf-8")
            hook.chmod(hook.stat().st_mode | 0o111)
            global_config = root / "global.gitconfig"
            global_config.write_text(
                f"[core]\n\thooksPath = {hook_dir}\n", encoding="utf-8"
            )
            subprocess.run(
                ["git", "init", str(sandbox)], check=True, capture_output=True
            )
            (sandbox / "file.txt").write_text("file", encoding="utf-8")
            with patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(global_config)}):
                self.assertEqual(
                    0,
                    eval_git(
                        "git", ["config", "user.email", "test@example.invalid"], sandbox
                    ).code,
                )
                self.assertEqual(
                    0, eval_git("git", ["config", "user.name", "Test"], sandbox).code
                )
                self.assertEqual(0, eval_git("git", ["add", "."], sandbox).code)
                self.assertEqual(
                    0, eval_git("git", ["commit", "-m", "test"], sandbox).code
                )
            self.assertFalse((root / "hook-ran").exists())

    def test_diff_capture_disables_local_external_diff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            sentinel = root / "diff-external-sentinel"
            external = root / "external-diff.py"
            external.write_text(
                "#!/usr/bin/env python3\n"
                "from pathlib import Path\n"
                f"Path({str(sentinel)!r}).write_text('executed')\n",
                encoding="utf-8",
            )
            external.chmod(external.stat().st_mode | 0o111)
            subprocess.run(
                ["git", "-C", str(root), "config", "diff.external", str(external)],
                check=True,
            )
            subprocess.run(["git", "-C", str(root), "add", "source.txt"], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "-c",
                    "user.email=test@example.invalid",
                    "-c",
                    "user.name=Test",
                    "commit",
                    "-m",
                    "seed",
                ],
                check=True,
                capture_output=True,
            )
            (root / "source.txt").write_text("changed", encoding="utf-8")
            _capture_diff("git", root, "HEAD")
            self.assertFalse(sentinel.exists())

    def test_validation_rejects_symlinked_contract_file_and_repository_entry(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            prompt = fixture / "prompt.md"
            prompt.unlink()
            prompt.symlink_to(root / "source.txt")
            with self.assertRaises(EvaluationError):
                validate_fixture(fixture)

    def test_validation_rejects_symlinked_repository_directory_inside_target(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            inside = root / "inside-directory"
            inside.mkdir()
            (inside / "file.txt").write_text("inside", encoding="utf-8")
            link = fixture / "repository/inside-link"
            link.symlink_to(inside, target_is_directory=True)
            with self.assertRaises(EvaluationError):
                validate_fixture(fixture)

    def test_output_must_be_existing_and_empty_is_checked_by_eval_boundary(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            create_fixture("sample", root, ["source.txt"])
            # This contract is checked before any temporary sandbox is made.
            output = root / "output"
            self.assertFalse(output.exists())

    def test_recovery_never_mutates_output_inside_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            (fixture / "verifier.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "command": [sys.executable, "-c", "pass"],
                        "timeout_seconds": 5,
                    }
                )
            )
            output = root / ".codev/evidence"
            output.mkdir()
            marker = output / ".codev-eval-transaction.json"
            marker.write_text("do not remove", encoding="utf-8")
            with self.assertRaises(EvaluationError):
                evaluate("sample", root, output, opencode="missing-opencode")
            self.assertEqual("do not remove", marker.read_text())

    def _opencode(self, root: Path, judge: bool = True) -> Path:
        executable = root / "fake-opencode.py"
        verdict = json.dumps(
            {
                "schema_version": 1,
                "verdict": "pass",
                "summary": "complete",
                "findings": [
                    {"criterion": "C1", "verdict": "pass", "evidence": "observed"}
                ],
            }
        )
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import json, pathlib, sys\n"
            "log = pathlib.Path(sys.argv[1])\n"
            "entry = {'argv': sys.argv[1:], 'cwd': str(pathlib.Path.cwd())}\n"
            "log.open('a').write(json.dumps(entry) + '\\n')\n"
            "is_judge = 'Review rubric' in sys.argv[-1]\n"
            f"print({verdict!r} if {judge!r} and is_judge else '{{}}')\n",
            encoding="utf-8",
        )
        executable.chmod(executable.stat().st_mode | 0o111)
        return executable

    def test_evaluate_passes_with_exact_adapter_argv_and_isolated_judge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            (fixture / "verifier.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "command": [sys.executable, "-c", "pass"],
                        "timeout_seconds": 5,
                    }
                )
            )
            output = root.parent / f"evidence-{root.name}"
            output.mkdir()
            log = root / "calls.jsonl"
            opencode = self._opencode(root)
            opencode_with_log = root / "runner.py"
            opencode_with_log.write_text(
                opencode.read_text().replace("sys.argv[1]", repr(str(log)), 1),
                encoding="utf-8",
            )
            opencode_with_log.chmod(opencode_with_log.stat().st_mode | 0o111)
            before = (root / "source.txt").read_bytes()
            self.assertTrue(
                evaluate("sample", root, output, opencode=str(opencode_with_log))
            )
            self.assertEqual(before, (root / "source.txt").read_bytes())
            self.assertTrue((output / "result.json").is_file())
            self.assertTrue((output / "diff.patch").is_file())
            marker = json.loads((output / ".codev-eval-commit.json").read_text())
            self.assertEqual(1, marker["schema_version"])
            judge_output = json.loads((output / "judge-output.json").read_text())
            self.assertEqual("pass", judge_output["verdict"])
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(2, len(calls))
            self.assertEqual(["run", "--format", "json"], calls[0]["argv"][:3])
            self.assertNotIn(str(root), calls[1]["cwd"])

    @unittest.skipUnless(os.name == "posix", "uses POSIX-only pathspec syntax")
    def test_diff_evidence_includes_actor_commit_and_untracked_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            (fixture / "verifier.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "command": [sys.executable, "-c", "pass"],
                        "timeout_seconds": 5,
                    }
                )
            )
            output = root.parent / f"evidence-{root.name}"
            output.mkdir()
            actor = root / "actor.py"
            verdict = json.dumps(
                {
                    "schema_version": 1,
                    "verdict": "pass",
                    "summary": "ok",
                    "findings": [
                        {"criterion": "C1", "verdict": "pass", "evidence": "seen"}
                    ],
                }
            )
            actor.write_text(
                "#!/usr/bin/env python3\n"
                "import os, pathlib, subprocess, sys\n"
                "if 'Review rubric' in sys.argv[-1]:\n"
                f"    print({verdict!r})\n"
                "else:\n"
                "    pathlib.Path('PRIVATE.PEM').write_text('secret')\n"
                "    pathlib.Path(':(exclude)magic.txt').write_text('safe magic')\n"
                "    pathlib.Path('.VENV').mkdir()\n"
                "    pathlib.Path('.VENV/secret').write_text('secret')\n"
                "    pathlib.Path('Node_Modules').mkdir()\n"
                "    pathlib.Path('Node_Modules/secret').write_text('secret')\n"
                "    pathlib.Path('committed.txt').write_text('commit')\n"
                "    run = subprocess.run\n"
                "    ck = dict(check=True)\n"
                "    cko = dict(check=True, capture_output=True)\n"
                "    run(\n"
                "        ['git', 'config', 'user.name', 'secret-token-author'], **ck\n"
                "    )\n"
                "    run(\n"
                "        ['git', 'config', 'user.email', 'secret@example.test'], **ck\n"
                "    )\n"
                "    pathlib.Path('binary.bin').write_bytes(\n"
                "        b'\\x00password=binary-secret\\xff'\n"
                "    )\n"
                "    add_paths = ['committed.txt', 'PRIVATE.PEM',"
                " ':(exclude)magic.txt']\n"
                "    run(['git', 'add', *add_paths], **cko)\n"
                "    run(['git', 'commit', '-m', 'actor'], **cko)\n"
                "    run(['git', 'add', 'binary.bin'], **cko)\n"
                "    run(['git', 'commit', '-m', 'binary'], **cko)\n"
                "    subject = 'subject\\x1econtains-delimiter'\n"
                "    run(['git', 'commit', '--allow-empty', '-m', subject], **cko)\n"
                "    pathlib.Path('.gitignore').write_text(\n"
                "        'ignored.txt\\nunknown-secret.blob\\n'\n"
                "    )\n"
                "    pathlib.Path('untracked.txt').write_text(\n"
                "        'password=untracked-secret'\n"
                "    )\n"
                "    pathlib.Path('ignored.txt').write_text('ignored')\n"
                "    blob = b'\\x00proprietary-secret-format\\xff'\n"
                "    pathlib.Path('unknown-secret.blob').write_bytes(blob)\n"
                "    pathlib.Path('.env.local').write_text('secret')\n"
                "    pathlib.Path('.aws').mkdir()\n"
                "    pathlib.Path('.aws/credentials').write_text('secret')\n"
                "    pathlib.Path('private.pem').write_text('secret')\n"
                "    pathlib.Path('linkdir').symlink_to('/tmp')\n"
                "    print('{}')\n",
                encoding="utf-8",
            )
            actor.chmod(actor.stat().st_mode | 0o111)
            passed = evaluate("sample", root, output, opencode=str(actor))
            if not passed:
                print((output / "result.json").read_text())
            self.assertTrue(passed)
            evidence = (output / "diff.patch").read_text()
            self.assertIn("committed.txt", evidence)
            self.assertIn("subject\\u001econtains-delimiter", evidence)
            self.assertIn(":(exclude)magic.txt", evidence)
            self.assertIn("untracked.txt", evidence)
            self.assertNotIn("untracked-secret", evidence)
            self.assertNotIn("secret-token-author", evidence)
            self.assertNotIn("secret@example.test", evidence)
            self.assertNotIn("binary-secret", evidence)
            self.assertNotIn("ignored.txt", evidence)
            self.assertNotIn("unknown-secret.blob", evidence)
            self.assertNotIn("proprietary-secret-format", evidence)
            self.assertNotIn(".env.local", evidence)
            self.assertNotIn("credentials", evidence)
            self.assertNotIn("private.pem", evidence)
            self.assertNotIn("PRIVATE.PEM", evidence)
            self.assertNotIn(".VENV", evidence)
            self.assertNotIn("Node_Modules", evidence)
            self.assertNotIn("linkdir", evidence)

    def test_diff_with_only_secret_changed_paths_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            (fixture / "verifier.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "command": [sys.executable, "-c", "pass"],
                        "timeout_seconds": 5,
                    }
                )
            )
            output = root.parent / f"evidence-{root.name}"
            output.mkdir()
            actor = root / "actor.py"
            verdict = json.dumps(
                {
                    "schema_version": 1,
                    "verdict": "pass",
                    "summary": "ok",
                    "findings": [
                        {"criterion": "C1", "verdict": "pass", "evidence": "ok"}
                    ],
                }
            )
            actor.write_text(
                "#!/usr/bin/env python3\n"
                "import pathlib, subprocess, sys\n"
                "if 'Review rubric' in sys.argv[-1]:\n"
                f"    print({verdict!r})\n"
                "else:\n"
                "    pathlib.Path('credential.txt').write_text('private material')\n"
                "    run = subprocess.run\n"
                "    ck = dict(check=True, capture_output=True)\n"
                "    run(['git', 'add', 'credential.txt'], **ck)\n"
                "    run(['git', 'commit', '-m', 'credential'], **ck)\n"
                "    print('{}')\n",
                encoding="utf-8",
            )
            actor.chmod(actor.stat().st_mode | 0o111)
            self.assertTrue(evaluate("sample", root, output, opencode=str(actor)))
            evidence = (output / "diff.patch").read_text()
            self.assertNotIn("credential.txt", evidence)
            self.assertNotIn("private material", evidence)

    def test_diff_preserves_non_utf8_filename_for_literal_pathspec(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = "nonutf-\udcff.txt"
            calls: list[list[str]] = []

            def fake_git(
                git: str, args: list[str], cwd: Path, timeout: int = 60
            ) -> Run:
                calls.append(args)
                if args[:3] == ["diff", "--name-only", "-z"]:
                    return Run(path + "\x00", "", 0, False, 0.0)
                if args[:2] == ["diff", "--binary"]:
                    self.assertIn(f":(literal){path}", args)
                    return Run(f"diff --git a/{path} b/{path}\n", "", 0, False, 0.0)
                return Run("", "", 0, False, 0.0)

            with patch("codev_workflow.eval._git", side_effect=fake_git):
                evidence = _capture_diff("git", Path(directory), "seed")
            self.assertIn(path, evidence)
            self.assertTrue(any(f":(literal){path}" in call for call in calls))

    def test_publication_failure_rolls_back_all_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            calls = 0

            def fail_second(source: Path, destination: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected publication failure")
                os.link(source, destination)
                source.unlink()

            with (
                patch("codev_workflow.eval.os.link", side_effect=fail_second),
                self.assertRaises(OSError),
            ):
                _write_output(output, {"one.txt": "1", "two.txt": "2"})
            self.assertEqual([], list(output.iterdir()))

    def test_publication_falls_back_when_link_crosses_filesystems(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "stage.txt"
            destination = root / "published.txt"
            source.write_text("safe publication", encoding="utf-8")

            with patch(
                "codev_workflow.eval.os.link",
                side_effect=OSError(errno.EXDEV, "cross-device link"),
            ):
                _publish_artifact(source, destination)
            self.assertEqual(
                "safe publication", destination.read_text(encoding="utf-8")
            )

    def test_publication_failure_preserves_caller_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            first_destination = output / "one.txt"
            calls = 0
            real_link = os.link

            def race_link(source: Path, destination: Path) -> None:
                nonlocal calls
                calls += 1
                real_link(source, destination)
                source.unlink()
                first_destination.unlink()
                first_destination.write_text("caller replacement", encoding="utf-8")
                raise OSError("injected publication failure")

            with (
                patch("codev_workflow.eval.os.link", side_effect=race_link),
                self.assertRaises(OSError),
            ):
                _write_output(output, {"one.txt": "one", "two.txt": "two"})
            self.assertEqual("caller replacement", first_destination.read_text())

    def test_fixture_failure_preserves_caller_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            (root / "second.txt").write_text("second", encoding="utf-8")
            destination = root / ".codev/fixtures/race"
            calls = 0

            def race_copy(
                source: Path,
                repository_fd: int,
                relative: Path,
                expected_identity: tuple[int, int],
                expected_digest: str,
            ) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    shutil.rmtree(destination)
                    destination.mkdir()
                    (destination / "caller.txt").write_text("caller", encoding="utf-8")
                    raise OSError("injected fixture failure")
                real_write_fixture_file(
                    source, repository_fd, relative, expected_identity, expected_digest
                )

            with (
                patch("codev_workflow.eval._write_fixture_file", side_effect=race_copy),
                self.assertRaises(OSError),
            ):
                create_fixture("race", root, ["source.txt", "second.txt"])
            self.assertEqual("caller", (destination / "caller.txt").read_text())

    def test_fixture_source_replacement_cannot_copy_external_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            external = root.parent / "external-secret.txt"
            external.write_text("external content", encoding="utf-8")

            def replace_source(
                source_path: Path,
                repository_fd: int,
                relative: Path,
                expected_identity: tuple[int, int],
                expected_digest: str,
            ) -> None:
                source_path.unlink()
                source_path.symlink_to(external)
                real_write_fixture_file(
                    source_path,
                    repository_fd,
                    relative,
                    expected_identity,
                    expected_digest,
                )

            with (
                patch(
                    "codev_workflow.eval._write_fixture_file",
                    side_effect=replace_source,
                ),
                self.assertRaises(EvaluationError),
            ):
                create_fixture("source-race", root, ["source.txt"])
            self.assertEqual("external content", external.read_text())
            self.assertFalse((root / ".codev/fixtures/source-race").exists())

    def test_directory_include_candidate_mutation_fails_without_partial_fixture(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            source_dir = root / "source-dir"
            source_dir.mkdir()
            first = source_dir / "first.txt"
            second = source_dir / "second.txt"
            first.write_text("first", encoding="utf-8")
            second.write_text("second", encoding="utf-8")
            for name, mutate in (
                ("add-race", lambda: (source_dir / "added.txt").write_text("added")),
                ("delete-race", second.unlink),
            ):
                calls = 0

                def mutate_copy(
                    source: Path,
                    repository_fd: int | Path,
                    relative: Path,
                    expected_identity: tuple[int, int],
                    expected_digest: str,
                    _mutate: Callable[[], object] = mutate,
                ) -> None:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        _mutate()
                    real_write_fixture_file(
                        source,
                        repository_fd,
                        relative,
                        expected_identity,
                        expected_digest,
                    )

                with (
                    patch(
                        "codev_workflow.eval._write_fixture_file",
                        side_effect=mutate_copy,
                    ),
                    self.assertRaises(EvaluationError),
                ):
                    create_fixture(name, root, ["source-dir"])
                self.assertFalse((root / ".codev/fixtures" / name).exists())
                if name == "add-race":
                    (source_dir / "added.txt").unlink()
                else:
                    second.write_text("second", encoding="utf-8")

    def test_cleanup_failure_writes_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            (fixture / "verifier.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "command": [sys.executable, "-c", "pass"],
                        "timeout_seconds": 5,
                    }
                )
            )
            output = root.parent / f"evidence-{root.name}"
            output.mkdir()
            opencode = self._opencode(root)
            runner = root / "runner.py"
            log = root / "calls.jsonl"
            runner.write_text(
                opencode.read_text().replace("sys.argv[1]", repr(str(log)), 1),
                encoding="utf-8",
            )
            runner.chmod(runner.stat().st_mode | 0o111)

            def fail_judge_cleanup(path: Path) -> None:
                if path.name == "judge":
                    raise OSError("injected cleanup failure")
                real_remove(path)

            with (
                patch("codev_workflow.eval._remove", side_effect=fail_judge_cleanup),
                self.assertRaises(EvaluationError),
            ):
                evaluate("sample", root, output, opencode=str(runner))
            result = json.loads((output / "result.json").read_text())
            self.assertEqual("error", result["outcome"])

    def test_failed_verifier_skips_judge_and_evaluation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            (fixture / "verifier.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "command": [sys.executable, "-c", "raise SystemExit(1)"],
                        "timeout_seconds": 5,
                    }
                )
            )
            output = root.parent / f"evidence-{root.name}"
            output.mkdir()
            log = root / "calls.jsonl"
            opencode = self._opencode(root)
            runner = root / "runner.py"
            runner.write_text(
                opencode.read_text().replace("sys.argv[1]", repr(str(log)), 1),
                encoding="utf-8",
            )
            runner.chmod(runner.stat().st_mode | 0o111)
            self.assertFalse(evaluate("sample", root, output, opencode=str(runner)))
            self.assertEqual(1, len(log.read_text().splitlines()))
            result = json.loads((output / "result.json").read_text())
            self.assertEqual("skipped", result["judge"]["status"])

    def test_actor_launch_failure_publishes_phase_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            create_fixture("sample", root, ["source.txt"])
            output = root.parent / f"evidence-{root.name}"
            output.mkdir()
            actor = root / "actor.py"
            actor.write_text("#!/usr/bin/env python3\nprint('{}')\n", encoding="utf-8")
            actor.chmod(actor.stat().st_mode | 0o111)

            def fail_actor(
                argv: list[str],
                cwd: Path,
                timeout: int,
                env: dict[str, str] | None = None,
                **kwargs: Any,
            ) -> Any:
                if Path(argv[0]).resolve() == actor.resolve():
                    raise EvaluationError("actor launch failed")
                return real_run(argv, cwd, timeout, env)

            with (
                patch("codev_workflow.eval._run", side_effect=fail_actor),
                self.assertRaises(EvaluationError),
            ):
                evaluate("sample", root, output, opencode=str(actor))
            result = json.loads((output / "result.json").read_text())
            self.assertEqual("error", result["actor"]["status"])
            for name in ("actor-events.jsonl", "actor-output.txt"):
                self.assertTrue((output / name).is_file())
                self.assertIn(name, result["artifacts"].values())

    def test_verifier_launch_failure_publishes_phase_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            command = [sys.executable, "-c", "pass"]
            (fixture / "verifier.json").write_text(
                json.dumps(
                    {"schema_version": 1, "command": command, "timeout_seconds": 5}
                )
            )
            output = root.parent / f"evidence-{root.name}"
            output.mkdir()
            actor = root / "actor.py"
            actor.write_text("#!/usr/bin/env python3\nprint('{}')\n", encoding="utf-8")
            actor.chmod(actor.stat().st_mode | 0o111)

            def fail_verifier(
                argv: list[str],
                cwd: Path,
                timeout: int,
                env: dict[str, str] | None = None,
                **kwargs: Any,
            ) -> Any:
                if argv == command:
                    raise EvaluationError("verifier launch failed")
                return real_run(argv, cwd, timeout, env)

            with (
                patch("codev_workflow.eval._run", side_effect=fail_verifier),
                self.assertRaises(EvaluationError),
            ):
                evaluate("sample", root, output, opencode=str(actor))
            result = json.loads((output / "result.json").read_text())
            self.assertEqual("error", result["verifier"]["status"])
            for name in (
                "actor-events.jsonl",
                "actor-output.txt",
                "verifier-stdout.txt",
                "verifier-stderr.txt",
            ):
                self.assertTrue((output / name).is_file())
                self.assertIn(name, result["artifacts"].values())

    def test_judge_launch_failure_publishes_phase_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            (fixture / "verifier.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "command": [sys.executable, "-c", "pass"],
                        "timeout_seconds": 5,
                    }
                )
            )
            output = root.parent / f"evidence-{root.name}"
            output.mkdir()
            actor = root / "actor.py"
            actor.write_text("#!/usr/bin/env python3\nprint('{}')\n", encoding="utf-8")
            actor.chmod(actor.stat().st_mode | 0o111)

            def fail_judge(
                argv: list[str],
                cwd: Path,
                timeout: int,
                env: dict[str, str] | None = None,
                **kwargs: Any,
            ) -> Any:
                if (
                    Path(argv[0]).resolve() == actor.resolve()
                    and "Review rubric" in argv[-1]
                ):
                    raise EvaluationError("judge launch failed")
                return real_run(argv, cwd, timeout, env)

            with (
                patch("codev_workflow.eval._run", side_effect=fail_judge),
                self.assertRaises(EvaluationError),
            ):
                evaluate("sample", root, output, opencode=str(actor))
            result = json.loads((output / "result.json").read_text())
            self.assertEqual("error", result["judge"]["status"])
            for name in ("judge-events.jsonl", "judge-output.json"):
                self.assertTrue((output / name).is_file())
                self.assertIn(name, result["artifacts"].values())

    def test_nonzero_actor_with_partial_output_is_completed_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            create_fixture("sample", root, ["source.txt"])
            output = root.parent / f"evidence-{root.name}"
            output.mkdir()
            actor = root / "actor-fail.py"
            actor.write_text(
                "#!/usr/bin/env python3\nprint('partial')\nraise SystemExit(3)\n",
                encoding="utf-8",
            )
            actor.chmod(actor.stat().st_mode | 0o111)
            self.assertFalse(evaluate("sample", root, output, opencode=str(actor)))
            result = json.loads((output / "result.json").read_text())
            self.assertEqual("failed", result["actor"]["status"])
            self.assertEqual(3, result["actor"]["exit_code"])
            self.assertEqual("skipped", result["verifier"]["status"])
            self.assertEqual("", (output / "actor-events.jsonl").read_text())
            self.assertEqual("", (output / "actor-output.txt").read_text())

    def test_invalid_utf8_actor_output_is_structured_and_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            create_fixture("sample", root, ["source.txt"])
            output = root.parent / f"evidence-{root.name}"
            output.mkdir()
            actor = root / "invalid-actor.py"
            actor.write_bytes(
                b"#!/usr/bin/env python3\n"
                b"import sys\n"
                b"sys.stdout.buffer.write(b'\\xff\\n')\n"
            )
            actor.chmod(actor.stat().st_mode | 0o111)
            with self.assertRaises(EvaluationError):
                evaluate("sample", root, output, opencode=str(actor))
            result = json.loads((output / "result.json").read_text())
            self.assertEqual("error", result["outcome"])
            self.assertEqual("", (output / "actor-events.jsonl").read_text())

    def test_invalid_utf8_verifier_output_is_persisted_safely(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            verifier = (
                "import sys; sys.stdout.buffer.write(b'\\xff\\n'); "
                "sys.stderr.buffer.write(b'\\xfe\\n')"
            )
            (fixture / "verifier.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "command": [sys.executable, "-c", verifier],
                        "timeout_seconds": 5,
                    }
                )
            )
            output = root.parent / f"evidence-{root.name}"
            output.mkdir()
            actor = root / "actor.py"
            verdict = json.dumps(
                {
                    "schema_version": 1,
                    "verdict": "pass",
                    "summary": "ok",
                    "findings": [
                        {"criterion": "C1", "verdict": "pass", "evidence": "ok"}
                    ],
                }
            )
            actor.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                "if 'Review rubric' in sys.argv[-1]:\n"
                f"    print({verdict!r})\n"
                "else:\n"
                "    print('{}')\n",
                encoding="utf-8",
            )
            actor.chmod(actor.stat().st_mode | 0o111)
            self.assertTrue(evaluate("sample", root, output, opencode=str(actor)))
            self.assertIn(
                "\ufffd", (output / "verifier-stdout.txt").read_text(encoding="utf-8")
            )
            self.assertIn(
                "\ufffd", (output / "verifier-stderr.txt").read_text(encoding="utf-8")
            )

    def test_invalid_utf8_judge_output_is_structured_and_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            (fixture / "verifier.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "command": [sys.executable, "-c", "pass"],
                        "timeout_seconds": 5,
                    }
                )
            )
            output = root.parent / f"evidence-{root.name}"
            output.mkdir()
            actor = root / "invalid-judge.py"
            actor.write_bytes(
                b"#!/usr/bin/env python3\n"
                b"import sys\n"
                b"if 'Review rubric' in sys.argv[-1]:\n"
                b"    sys.stdout.buffer.write(b'\\xff\\n')\n"
                b"else:\n"
                b"    print('{}')\n"
            )
            actor.chmod(actor.stat().st_mode | 0o111)
            with self.assertRaises(EvaluationError):
                evaluate("sample", root, output, opencode=str(actor))
            result = json.loads((output / "result.json").read_text())
            self.assertEqual("malformed", result["judge"]["status"])
            self.assertIn(
                "\ufffd", (output / "judge-events.jsonl").read_text(encoding="utf-8")
            )

    def test_timed_out_actor_with_partial_output_is_completed_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            metadata = json.loads((fixture / "fixture.json").read_text())
            metadata["actor_timeout_seconds"] = 1
            (fixture / "fixture.json").write_text(json.dumps(metadata))
            output = root.parent / f"evidence-{root.name}"
            output.mkdir()
            actor = root / "actor-timeout.py"
            actor.write_text(
                "#!/usr/bin/env python3\n"
                "print('partial', flush=True)\n"
                "import time; time.sleep(3)\n",
                encoding="utf-8",
            )
            actor.chmod(actor.stat().st_mode | 0o111)
            self.assertFalse(evaluate("sample", root, output, opencode=str(actor)))
            result = json.loads((output / "result.json").read_text())
            self.assertEqual("timeout", result["actor"]["status"])
            self.assertTrue(result["actor"]["timeout"])
            self.assertEqual("skipped", result["judge"]["status"])
            self.assertEqual("", (output / "actor-events.jsonl").read_text())
            self.assertEqual("", (output / "actor-output.txt").read_text())

    def test_malformed_judge_records_launched_status_and_duration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            (fixture / "verifier.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "command": [sys.executable, "-c", "pass"],
                        "timeout_seconds": 5,
                    }
                )
            )
            output = root.parent / f"evidence-{root.name}"
            output.mkdir()
            runner = root / "runner.py"
            log = root / "calls.jsonl"
            malformed = self._opencode(root, judge=False)
            runner.write_text(
                malformed.read_text().replace("sys.argv[1]", repr(str(log)), 1),
                encoding="utf-8",
            )
            runner.chmod(runner.stat().st_mode | 0o111)
            with self.assertRaises(EvaluationError):
                evaluate("sample", root, output, opencode=str(runner))
            judge = json.loads((output / "result.json").read_text())["judge"]
            self.assertEqual("malformed", judge["status"])
            self.assertIn("exit_code", judge)
            self.assertIn("duration_seconds", judge)
            self.assertIn("timeout", judge)

    def test_git_diff_failure_is_structured_and_skips_judge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            (fixture / "verifier.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "command": [sys.executable, "-c", "pass"],
                        "timeout_seconds": 5,
                    }
                )
            )
            output = root.parent / f"evidence-{root.name}"
            output.mkdir()
            log = root / "calls.jsonl"
            opencode = self._opencode(root)
            runner = root / "runner.py"
            runner.write_text(
                opencode.read_text().replace("sys.argv[1]", repr(str(log)), 1),
                encoding="utf-8",
            )
            runner.chmod(runner.stat().st_mode | 0o111)

            def fake_git(
                git: str, args: list[str], cwd: Path, timeout: int = 60
            ) -> Run:
                if args and args[0] == "diff":
                    return Run("", "diff unavailable", 1, False, 0.0)
                return real_git(git, args, cwd, timeout)

            with (
                patch("codev_workflow.eval._git", side_effect=fake_git),
                self.assertRaises(EvaluationError),
            ):
                evaluate("sample", root, output, opencode=str(runner))
            result = json.loads((output / "result.json").read_text())
            self.assertEqual("error", result["outcome"])
            self.assertEqual("skipped", result["judge"]["status"])
            self.assertNotIn("diff.patch", result["artifacts"].values())


class SkillSnapshotTests(unittest.TestCase):
    def _repo(self, root: Path) -> None:
        subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
        (root / "source.txt").write_text("seed", encoding="utf-8")

    def _install_skill(self, root: Path, skill: str, agents_md: bool = True) -> None:
        skill_dir = root / ".agents" / "skills" / skill
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(f"# {skill}\n", encoding="utf-8")
        if agents_md:
            (root / "AGENTS.md").write_text(
                "Local project notes.\n"
                "<!-- codev:start -->\n"
                f"Route to the {skill} skill.\n"
                "<!-- codev:end -->\n"
                "More local notes.\n",
                encoding="utf-8",
            )

    def _tag_fixture(self, fixture: Path, skill: str, category: str) -> None:
        identity = json.loads((fixture / "fixture.json").read_text())
        identity["skill"] = skill
        identity["category"] = category
        (fixture / "fixture.json").write_text(json.dumps(identity), encoding="utf-8")

    def test_validate_fixture_rejects_missing_skill_or_category(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            identity = json.loads((fixture / "fixture.json").read_text())
            del identity["skill"]
            (fixture / "fixture.json").write_text(json.dumps(identity))
            with self.assertRaises(EvaluationError):
                validate_fixture(fixture)

    def test_validate_fixture_rejects_empty_category(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            self._tag_fixture(fixture, "review-change", "")
            with self.assertRaises(EvaluationError):
                validate_fixture(fixture)

    def test_stage_skill_copies_skill_and_agents_md_block_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._install_skill(root, "review-change")
            seed = root / "seed"
            seed.mkdir()
            _stage_skill(seed, root, "review-change")
            staged_skill = seed / ".agents" / "skills" / "review-change" / "SKILL.md"
            self.assertTrue(staged_skill.is_file())
            self.assertEqual("# review-change\n", staged_skill.read_text())
            staged_agents = (seed / "AGENTS.md").read_text()
            self.assertIn("<!-- codev:start -->", staged_agents)
            self.assertIn("Route to the review-change skill.", staged_agents)
            # Only the marked block is carried over, not surrounding local notes.
            self.assertNotIn("Local project notes.", staged_agents)
            self.assertNotIn("More local notes.", staged_agents)

    def test_stage_skill_raises_when_skill_is_not_installed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.joinpath(".git").mkdir()
            seed = root / "seed"
            seed.mkdir()
            with self.assertRaises(EvaluationError):
                _stage_skill(seed, root, "never-installed")

    def test_evaluate_calls_stage_skill_only_when_with_skill_is_true(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            fixture = create_fixture("sample", root, ["source.txt"])
            self._tag_fixture(fixture, "sample-skill", "example")
            # sys.executable is a real, resolvable executable, so evaluate()
            # gets past its git/opencode availability check and reaches the
            # staging decision point for both conditions; it then fails for
            # unrelated reasons (nonsense args to the interpreter), which is
            # fine here -- only whether _stage_skill was called matters.
            with patch("codev_workflow.eval._stage_skill") as stage_skill:
                without_output = root.parent / f"without-skill-{root.name}"
                without_output.mkdir()
                evaluate(
                    "sample",
                    root,
                    without_output,
                    opencode=sys.executable,
                    with_skill=False,
                )
                stage_skill.assert_not_called()

                with_output = root.parent / f"with-skill-{root.name}"
                with_output.mkdir()
                evaluate(
                    "sample",
                    root,
                    with_output,
                    opencode=sys.executable,
                    with_skill=True,
                )
                stage_skill.assert_called_once()
                self.assertEqual(root.resolve(), stage_skill.call_args.args[1])
                self.assertEqual("sample-skill", stage_skill.call_args.args[2])

    def test_run_snapshot_reports_percentage_and_delta_per_category(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            self._install_skill(root, "sample-skill")
            first = create_fixture("first", root, ["source.txt"])
            self._tag_fixture(first, "sample-skill", "alpha")
            second = create_fixture("second", root, ["source.txt"])
            self._tag_fixture(second, "sample-skill", "alpha")
            third = create_fixture("third", root, ["source.txt"])
            self._tag_fixture(third, "sample-skill", "beta")
            output = root.parent / f"snapshot-{root.name}"
            output.mkdir()

            def fake_evaluate(
                name: str,
                target: Path,
                run_output: Path,
                git: str = "git",
                opencode: str = "opencode",
                with_skill: bool = True,
            ) -> bool:
                (run_output / "result.json").write_text("{}", encoding="utf-8")
                return with_skill

            with patch("codev_workflow.eval.evaluate", side_effect=fake_evaluate):
                report = run_snapshot("sample-skill", root, output, repetitions=2)

            self.assertEqual({"alpha", "beta"}, set(report["categories"]))
            alpha = report["categories"]["alpha"]
            self.assertEqual(100.0, alpha["with_skill_percentage"])
            self.assertEqual(0.0, alpha["without_skill_percentage"])
            self.assertEqual(100.0, alpha["delta"])
            self.assertEqual(
                {"passed": 2, "total": 2}, alpha["fixtures"]["first"]["with_skill"]
            )
            self.assertEqual(
                {"passed": 0, "total": 2}, alpha["fixtures"]["first"]["without_skill"]
            )
            beta = report["categories"]["beta"]
            self.assertEqual(100.0, beta["delta"])
            self.assertTrue((output / "snapshot.json").is_file())
            on_disk = json.loads((output / "snapshot.json").read_text())
            self.assertEqual(report, on_disk)

    def test_run_snapshot_records_infrastructure_errors_as_failed_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            self._install_skill(root, "sample-skill")
            fixture = create_fixture("first", root, ["source.txt"])
            self._tag_fixture(fixture, "sample-skill", "alpha")
            output = root.parent / f"snapshot-{root.name}"
            output.mkdir()

            with patch(
                "codev_workflow.eval.evaluate",
                side_effect=EvaluationError("actor launch failed"),
            ):
                report = run_snapshot("sample-skill", root, output, repetitions=1)

            alpha = report["categories"]["alpha"]
            self.assertEqual(0.0, alpha["with_skill_percentage"])
            self.assertEqual(0.0, alpha["without_skill_percentage"])
            error_file = (
                output
                / "sample-skill"
                / "alpha"
                / "first"
                / "with_skill"
                / "1"
                / "snapshot-error.txt"
            )
            self.assertIn("actor launch failed", error_file.read_text())

    def test_run_snapshot_rejects_zero_repetitions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            output = root.parent / f"snapshot-{root.name}"
            output.mkdir()
            with self.assertRaises(EvaluationError):
                run_snapshot("any-skill", root, output, repetitions=0)

    def test_run_snapshot_rejects_skill_with_no_matching_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            create_fixture("first", root, ["source.txt"])
            output = root.parent / f"snapshot-{root.name}"
            output.mkdir()
            with self.assertRaises(EvaluationError):
                run_snapshot("no-such-skill", root, output)

    def test_run_snapshot_only_categories_restricts_which_fixtures_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            self._install_skill(root, "sample-skill")
            first = create_fixture("first", root, ["source.txt"])
            self._tag_fixture(first, "sample-skill", "alpha")
            second = create_fixture("second", root, ["source.txt"])
            self._tag_fixture(second, "sample-skill", "beta")
            output = root.parent / f"snapshot-{root.name}"
            output.mkdir()

            with patch("codev_workflow.eval.evaluate", return_value=True):
                report = run_snapshot(
                    "sample-skill",
                    root,
                    output,
                    repetitions=1,
                    only_categories=["beta"],
                )

            self.assertEqual({"beta"}, set(report["categories"]))
            self.assertNotIn("first", report["categories"]["beta"]["fixtures"])
            self.assertIn("second", report["categories"]["beta"]["fixtures"])

    def test_run_snapshot_rejects_unknown_category(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            self._install_skill(root, "sample-skill")
            fixture = create_fixture("first", root, ["source.txt"])
            self._tag_fixture(fixture, "sample-skill", "alpha")
            output = root.parent / f"snapshot-{root.name}"
            output.mkdir()
            with self.assertRaises(EvaluationError):
                run_snapshot(
                    "sample-skill",
                    root,
                    output,
                    only_categories=["no-such-category"],
                )


if __name__ == "__main__":
    unittest.main()
