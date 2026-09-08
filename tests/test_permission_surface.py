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
"""Guard the Claude Code permission surface added for D6 (see
docs/plans/claude-code-adapter-verification-first.md and
docs/codev/task/claude-code-adapter-verification-first/permission-surface-implementation-plan.md).

`.claude/settings.json`'s `permissions.deny` is what turns AGENTS.md's
publish-recipe warning from prose into an enforced rule -- if either deny
entry were silently deleted, an agent could invoke `just publish-pypi` /
`just publish-testpypi` without even a prompt. This pins both the JSON
validity and the presence of both entries, and that the bundle source and
this repository's own installed copy stay byte-identical (installer.py
diffs them via `codev diff --target .`, and scripts/verify_self_install.py
is what caught a prior drift between the two -- see that script's
docstring).
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BUNDLE_SETTINGS = (
    _REPO_ROOT / "src" / "codev_workflow" / "bundle" / ".claude" / "settings.json"
)
_INSTALLED_SETTINGS = _REPO_ROOT / ".claude" / "settings.json"

_DENIED_PUBLISH_RECIPES = (
    "Bash(just publish-pypi:*)",
    "Bash(just publish-testpypi:*)",
)


class PermissionSurfaceTests(unittest.TestCase):
    def test_bundle_settings_json_parses(self) -> None:
        json.loads(_BUNDLE_SETTINGS.read_text(encoding="utf-8"))

    def test_bundle_and_installed_copies_are_byte_identical(self) -> None:
        self.assertEqual(
            _BUNDLE_SETTINGS.read_bytes(),
            _INSTALLED_SETTINGS.read_bytes(),
            "src/codev_workflow/bundle/.claude/settings.json and the "
            "installed .claude/settings.json have drifted apart -- "
            "scripts/verify_self_install.py exists to catch exactly this.",
        )

    def test_publish_recipes_are_denied(self) -> None:
        settings = json.loads(_BUNDLE_SETTINGS.read_text(encoding="utf-8"))
        deny = settings["permissions"]["deny"]
        for recipe in _DENIED_PUBLISH_RECIPES:
            self.assertIn(recipe, deny)

    def test_default_mode_and_hooks_are_untouched(self) -> None:
        settings = json.loads(_BUNDLE_SETTINGS.read_text(encoding="utf-8"))
        self.assertEqual("plan", settings["permissions"]["defaultMode"])
        self.assertIn("PreToolUse", settings["hooks"])
        self.assertEqual(3, len(settings["hooks"]["PreToolUse"]))


if __name__ == "__main__":
    unittest.main()
