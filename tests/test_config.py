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
            },
            result,
        )


if __name__ == "__main__":
    unittest.main()
