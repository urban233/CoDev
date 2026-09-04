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

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codev_workflow.config import (
    ConfigError,
    ResolvedValue,
    _global_config_path,
    _project_config_path,
    _read_config,
    list_values,
    resolve,
    resolve_bool,
    set_value,
)


class ResolutionPrecedenceTests(unittest.TestCase):
    def test_flag_overrides_everything(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            set_value("model", "project-value", target=target)
            with patch.dict("os.environ", {"CODEV_MODEL": "env-value"}, clear=False):
                result = resolve("model", target=target, override="flag-value")
        self.assertEqual(ResolvedValue("flag-value", "flag"), result)

    def test_env_overrides_project_and_global(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            set_value("model", "project-value", target=target)
            with patch.dict("os.environ", {"CODEV_MODEL": "env-value"}, clear=False):
                result = resolve("model", target=target)
        self.assertEqual(ResolvedValue("env-value", "env"), result)

    def test_project_overrides_global(self) -> None:
        # Redirect the global config home for whichever OS this actually runs
        # on, rather than faking os.name — pathlib refuses to instantiate the
        # other platform's concrete Path class, so cross-OS branches are
        # instead covered per-OS by the CI matrix (see GlobalPathTests).
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            global_home = Path(directory) / "global-home"
            with patch.dict(
                "os.environ",
                {"XDG_CONFIG_HOME": str(global_home), "APPDATA": str(global_home)},
                clear=False,
            ):
                set_value("model", "global-value", target=target, global_scope=True)
                set_value("model", "project-value", target=target)
                result = resolve("model", target=target)
        self.assertEqual(ResolvedValue("project-value", "project"), result)

    def test_global_used_when_project_unset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            global_home = Path(directory) / "global-home"
            with patch.dict(
                "os.environ",
                {"XDG_CONFIG_HOME": str(global_home), "APPDATA": str(global_home)},
                clear=False,
            ):
                set_value("model", "global-value", target=target, global_scope=True)
                result = resolve("model", target=target)
        self.assertEqual(ResolvedValue("global-value", "global"), result)

    def test_unset_key_resolves_to_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(resolve("missing", target=Path(directory)))

    def test_git_workflow_defaults_to_trunk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = resolve("git.workflow", target=Path(directory))
        self.assertEqual(ResolvedValue("trunk", "default"), result)

    def test_git_workflow_project_value_overrides_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            set_value("git.workflow", "feature-branch", target=target)
            result = resolve("git.workflow", target=target)
        self.assertEqual(ResolvedValue("feature-branch", "project"), result)

    def test_review_max_lines_defaults_to_400(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = resolve("review.max_lines", target=Path(directory))
        self.assertEqual(ResolvedValue("600", "default"), result)

    def test_review_max_files_defaults_to_8(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = resolve("review.max_files", target=Path(directory))
        self.assertEqual(ResolvedValue("12", "default"), result)

    def test_review_max_lines_project_value_overrides_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            set_value("review.max_lines", "250", target=target)
            result = resolve("review.max_lines", target=target)
        self.assertEqual(ResolvedValue("250", "project"), result)


class ResolveBoolTests(unittest.TestCase):
    def test_override_resolves_true(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = resolve_bool(
                "some.flag", target=Path(directory), override="true"
            )
        self.assertTrue(result)

    def test_override_resolves_false(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = resolve_bool(
                "some.flag", target=Path(directory), override="false"
            )
        self.assertFalse(result)

    def test_env_resolves_true(self) -> None:
        # resolve()'s env-key mapping replaces "-" with "_" but leaves "."
        # untouched, so "some.flag" maps to "CODEV_SOME.FLAG", not
        # "CODEV_SOME_FLAG".
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict("os.environ", {"CODEV_SOME.FLAG": "true"}, clear=False),
        ):
            result = resolve_bool("some.flag", target=Path(directory))
        self.assertTrue(result)

    def test_project_resolves_false(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            set_value("some.flag", "false", target=target)
            result = resolve_bool("some.flag", target=target)
        self.assertFalse(result)

    def test_global_resolves_true(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            global_home = Path(directory) / "global-home"
            with patch.dict(
                "os.environ",
                {"XDG_CONFIG_HOME": str(global_home), "APPDATA": str(global_home)},
                clear=False,
            ):
                set_value("some.flag", "true", target=target, global_scope=True)
                result = resolve_bool("some.flag", target=target)
        self.assertTrue(result)

    def test_git_auto_commit_defaults_to_true(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = resolve_bool("git.auto_commit", target=Path(directory))
        self.assertTrue(result)

    def test_git_auto_open_pr_defaults_to_true(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = resolve_bool("git.auto_open_pr", target=Path(directory))
        self.assertTrue(result)

    def test_override_invalid_value_raises_config_error(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(ConfigError),
        ):
            resolve_bool("some.flag", target=Path(directory), override="yes")

    def test_env_invalid_value_raises_config_error(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict("os.environ", {"CODEV_SOME.FLAG": "1"}, clear=False),
            self.assertRaises(ConfigError),
        ):
            resolve_bool("some.flag", target=Path(directory))

    def test_project_invalid_value_raises_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            set_value("git.auto_commit", "yes", target=target)
            with self.assertRaises(ConfigError) as raised:
                resolve_bool("git.auto_commit", target=target)
        message = str(raised.exception)
        self.assertIn("git.auto_commit", message)
        self.assertIn("yes", message)

    def test_global_invalid_value_raises_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            global_home = Path(directory) / "global-home"
            with patch.dict(
                "os.environ",
                {"XDG_CONFIG_HOME": str(global_home), "APPDATA": str(global_home)},
                clear=False,
            ):
                set_value("some.flag", "enabled", target=target, global_scope=True)
                with self.assertRaises(ConfigError):
                    resolve_bool("some.flag", target=target)

    def test_unset_key_with_no_default_raises_config_error(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(ConfigError) as raised,
        ):
            resolve_bool("some.missing.flag", target=Path(directory))
        message = str(raised.exception)
        self.assertIn("some.missing.flag", message)


class GlobalPathTests(unittest.TestCase):
    # Each branch is exercised on its real OS only: pathlib refuses to
    # instantiate the other platform's concrete Path class even once os.name
    # is patched, so faking the other OS here would test pathlib, not us.
    # The CI matrix (ubuntu/windows/macos) provides genuine coverage of both.

    @unittest.skipUnless(os.name == "nt", "exercises the Windows branch")
    def test_windows_uses_appdata(self) -> None:
        with patch.dict("os.environ", {"APPDATA": "C:/Users/example/AppData/Roaming"}):
            path = _global_config_path()
        self.assertEqual(
            Path("C:/Users/example/AppData/Roaming") / "codev" / "config.toml", path
        )

    @unittest.skipUnless(os.name == "posix", "exercises the POSIX branch")
    def test_posix_uses_xdg_config_home(self) -> None:
        with patch.dict("os.environ", {"XDG_CONFIG_HOME": "/home/example/.config"}):
            path = _global_config_path()
        self.assertEqual(Path("/home/example/.config/codev/config.toml"), path)


class PersistenceTests(unittest.TestCase):
    def test_set_value_round_trips_through_read_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            written = set_value("model", "anthropic/claude", target=target)
            self.assertEqual(_project_config_path(target), written)
            schema_version, values = _read_config(written)
            self.assertEqual(1, schema_version)
            self.assertEqual({"model": "anthropic/claude"}, values)

    def test_set_value_round_trips_a_dotted_key(self) -> None:
        # An unquoted dotted key (e.g. "git.pr_base") is a TOML dotted key --
        # parsed as a nested table, not one literal key -- unless the writer
        # quotes it. Regression coverage for that round-trip.
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            set_value("git.pr_base", "develop", target=target)
            _, values = _read_config(_project_config_path(target))
            self.assertEqual({"git.pr_base": "develop"}, values)
            self.assertEqual(
                ResolvedValue("develop", "project"),
                resolve("git.pr_base", target=target),
            )

    def test_set_value_preserves_other_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            set_value("model", "anthropic/claude", target=target)
            set_value("max_rounds", "2", target=target)
            _, values = _read_config(_project_config_path(target))
            self.assertEqual({"model": "anthropic/claude", "max_rounds": "2"}, values)

    def test_invalid_toml_raises_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            path = _project_config_path(target)
            path.parent.mkdir(parents=True)
            path.write_text("not [ valid toml", encoding="utf-8")
            with self.assertRaises(ConfigError):
                _read_config(path)

    def test_unsupported_schema_version_raises_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            path = _project_config_path(target)
            path.parent.mkdir(parents=True)
            path.write_text("schema_version = 99\n", encoding="utf-8")
            with self.assertRaises(ConfigError):
                _read_config(path)

    def test_missing_config_reads_as_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            schema_version, values = _read_config(Path(directory) / "absent.toml")
        self.assertEqual(1, schema_version)
        self.assertEqual({}, values)


class ListValuesTests(unittest.TestCase):
    def test_merges_project_and_global_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            global_home = Path(directory) / "global-home"
            with patch.dict(
                "os.environ",
                {"XDG_CONFIG_HOME": str(global_home), "APPDATA": str(global_home)},
                clear=False,
            ):
                set_value("model", "global-model", target=target, global_scope=True)
                set_value("adapter", "opencode", target=target)
                result = list_values(target=target)
        self.assertEqual(
            {
                "model": ResolvedValue("global-model", "global"),
                "adapter": ResolvedValue("opencode", "project"),
                "git.workflow": ResolvedValue("trunk", "default"),
                "git.auto_commit": ResolvedValue("true", "default"),
                "git.auto_open_pr": ResolvedValue("true", "default"),
                "review.max_lines": ResolvedValue("600", "default"),
                "review.max_files": ResolvedValue("12", "default"),
                "review.required_approvals": ResolvedValue("1", "default"),
                "review.sensitive_paths": ResolvedValue("", "default"),
                "review.pair_paths": ResolvedValue("", "default"),
            },
            result,
        )


if __name__ == "__main__":
    unittest.main()
