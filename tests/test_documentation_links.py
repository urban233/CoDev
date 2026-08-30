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

from scripts.check_bundled_doc_links import find_broken_links_in_file, main

_REPO_ROOT = Path(__file__).resolve().parents[1]


class BundledDocLinksTests(unittest.TestCase):
    """Regression guard for the exact bug this script was written to catch:
    bundled onboarding docs linking to content (the former Wiki handbooks)
    that doesn't travel with the bundle. See
    docs/adr/0031-drop-codex-narrow-junie-and-antigravity-to-an-edit-assistant.md's
    sibling documentation-overhaul work.
    """

    def test_repository_has_no_broken_documentation_links(self) -> None:
        self.assertEqual(0, main(["--repo", str(_REPO_ROOT)]))

    def test_missing_link_target_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            doc = Path(directory) / "guide.md"
            doc.write_text("See [the cookbook](../handbooks/COOKBOOK.md).\n")
            problems = find_broken_links_in_file(doc)
        self.assertEqual(1, len(problems))
        self.assertIn("COOKBOOK.md", problems[0])

    def test_link_outside_containment_root_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "bundle"
            (bundle / "docs").mkdir(parents=True)
            (root / "outside.md").write_text("# Not part of the bundle\n")
            doc = bundle / "docs" / "guide.md"
            doc.write_text("See [this](../../outside.md).\n")
            problems = find_broken_links_in_file(doc, containment_root=bundle)
        self.assertEqual(1, len(problems))
        self.assertIn("outside the bundle", problems[0])

    def test_link_inside_containment_root_is_not_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs" / "other").mkdir(parents=True)
            (root / "docs" / "other" / "page.md").write_text("# Page\n")
            doc = root / "docs" / "guide.md"
            doc.write_text("See [this](other/page.md).\n")
            problems = find_broken_links_in_file(doc, containment_root=root)
        self.assertEqual([], problems)

    def test_fragment_is_stripped_before_resolving_the_file(self) -> None:
        # Real production usage: onboarding-guide.md links to
        # normal-development-workflow.md#a-specific-heading. The fragment
        # must not become part of the path being resolved.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "page.md").write_text("# Page\n\n## A Heading\n")
            doc = root / "guide.md"
            doc.write_text("See [this](page.md#a-heading).\n")
            problems = find_broken_links_in_file(doc)
        self.assertEqual([], problems)

    def test_bare_fragment_with_no_path_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            doc = Path(directory) / "guide.md"
            doc.write_text("See [this section](#a-heading).\n")
            problems = find_broken_links_in_file(doc)
        self.assertEqual([], problems)

    def test_external_url_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            doc = Path(directory) / "guide.md"
            doc.write_text("See [GitHub](https://github.com/example/example).\n")
            problems = find_broken_links_in_file(doc)
        self.assertEqual([], problems)


if __name__ == "__main__":
    unittest.main()
