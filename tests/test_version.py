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
