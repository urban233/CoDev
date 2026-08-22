from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts import version


class VersionScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "CHANGELOG.md").write_text(
            (
                "# Changelog\n\n## [Unreleased]\n\n- New change\n\n"
                "## [0.1.1] - 2026-08-02\n"
            ),
            encoding="utf-8",
        )
        for relative_path in version.VERSION_FILES[1:]:
            path = self.root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("release 0.1.1\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_only_release_owned_files_are_updated(self) -> None:
        unrelated = self.root / ".idea" / "workspace.xml"
        generated = self.root / "src" / "codev_workflow.egg-info" / "PKG-INFO"
        unrelated.parent.mkdir(parents=True)
        generated.parent.mkdir(parents=True)
        unrelated.write_text("0.1.1\n", encoding="utf-8")
        generated.write_text("Version: 0.1.1\n", encoding="utf-8")

        changed = version.replace_in_repository(
            self.root,
            "0.1.1",
            "0.1.2",
            False,
            "2026-08-05",
        )

        self.assertEqual(
            [self.root / relative_path for relative_path in version.VERSION_FILES],
            changed,
        )
        self.assertEqual("0.1.1\n", unrelated.read_text(encoding="utf-8"))
        self.assertEqual("Version: 0.1.1\n", generated.read_text(encoding="utf-8"))
        changelog = (self.root / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [0.1.2] - 2026-08-05", changelog)
        self.assertIn("## [0.1.1] - 2026-08-02", changelog)

    def test_changelog_requires_unreleased_heading(self) -> None:
        with self.assertRaisesRegex(ValueError, r"\[Unreleased\]"):
            version.update_changelog("# Changelog\n", "0.1.2", "2026-08-05")

    def test_dry_run_does_not_write(self) -> None:
        changed = version.replace_in_repository(self.root, "0.1.1", "0.1.2", True)

        self.assertEqual(len(version.VERSION_FILES), len(changed))
        for relative_path in version.VERSION_FILES:
            content = (self.root / relative_path).read_text(encoding="utf-8")
            if relative_path == Path("CHANGELOG.md"):
                self.assertIn("## [0.1.1] - 2026-08-02", content)
                self.assertNotIn("## [0.1.2]", content)
            else:
                self.assertEqual("release 0.1.1\n", content)


if __name__ == "__main__":
    unittest.main()
