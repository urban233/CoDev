from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts import verify_release


class ReleaseVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "src/codev_workflow").mkdir(parents=True)
        (self.root / "pyproject.toml").write_text(
            '[project]\nversion = "0.1.3"\n',
            encoding="utf-8",
        )
        self.runtime_path = self.root / "src/codev_workflow/__init__.py"
        self.runtime_path.write_text('__version__ = "0.1.3"\n', encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_matching_versions_and_tag_pass(self) -> None:
        self.assertEqual(
            ("0.1.3", "0.1.3"),
            verify_release.verify(self.root, "v0.1.3"),
        )

    def test_mismatched_runtime_version_fails(self) -> None:
        self.runtime_path.write_text('__version__ = "0.1.2"\n', encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "runtime version 0.1.2"):
            verify_release.verify(self.root, "v0.1.3")

    def test_mismatched_tag_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "tag v0.1.4"):
            verify_release.verify(self.root, "v0.1.4")
