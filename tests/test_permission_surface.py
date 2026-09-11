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

The five no-argument-safe `just` recipes in `permissions.allow` (`lint`,
`typecheck`, `fmt-check`, `validate-catalog`, `test`) use exact-match
entries (no trailing `:*`) rather than prefix wildcards. That is a
deliberate hardening, not an oversight: `just` itself lets a trailing word
after a no-argument recipe run as a second, chained recipe (e.g. `just lint
publish-pypi` actually runs `lint` and then `publish-pypi`), and `just
test`'s variadic argument is interpolated unquoted into a shell line,
making `just test '&& echo INJECTED'` a real injection primitive. A
prefix-wildcard allow entry like `Bash(just lint:*)` matches either
attack's full command string and never reaches `permissions.deny` at all.
An exact-match entry with no wildcard matches only that literal command
string, so it cannot be widened this way; anything else (arguments
included) falls through to a permission prompt instead of being
auto-approved.
"""

from __future__ import annotations

import json
import shutil
import subprocess
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

# The full expected allow list, in order -- checked for equality rather than
# membership so a future silent widening (e.g. reverting an exact-match
# entry back to a prefix wildcard) is caught immediately.
_EXPECTED_ALLOW = [
    "Bash(codev next:*)",
    "Bash(codev task check:*)",
    "Bash(codev task log:*)",
    "Bash(just test)",
    "Bash(just lint)",
    "Bash(just typecheck)",
    "Bash(just fmt-check)",
    "Bash(just validate-catalog)",
    "Bash(git diff:*)",
    "Bash(git status:*)",
    "Bash(git log:*)",
    "Bash(git show:*)",
    "Bash(gh pr view:*)",
    "Bash(gh run view:*)",
]


def _resolve_just() -> str | None:
    """Find a runnable `just` binary, matching how other tests in this repo
    resolve tooling paths that are not necessarily on PATH (see
    tests/test_small_change_hook.py's `_hook_env`): prefer PATH, then fall
    back to the repo-local, gitignored `.tools/just` (see AGENTS.md's
    "It is not installed system-wide" note).
    """
    found = shutil.which("just")
    if found is not None:
        return found
    local = _REPO_ROOT / ".tools" / "just"
    if local.is_file():
        return str(local)
    return None


class PermissionSurfaceTests(unittest.TestCase):
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

    def test_allow_list_matches_expected_exact_list(self) -> None:
        settings = json.loads(_BUNDLE_SETTINGS.read_text(encoding="utf-8"))
        self.assertEqual(
            _EXPECTED_ALLOW,
            settings["permissions"]["allow"],
            "permissions.allow drifted from the expected list -- if this "
            "is a deliberate widening, confirm none of the five "
            "no-argument-safe `just` recipes regressed from exact-match "
            "back to a prefix wildcard (see this module's docstring).",
        )

    def test_default_mode_and_hooks_are_untouched(self) -> None:
        settings = json.loads(_BUNDLE_SETTINGS.read_text(encoding="utf-8"))
        self.assertEqual("plan", settings["permissions"]["defaultMode"])
        self.assertIn("PreToolUse", settings["hooks"])
        self.assertEqual(
            3,
            len(settings["hooks"]["PreToolUse"]),
            "if this changes because slice 3 of the parent plan added a "
            "fourth hook, update this count deliberately rather than let "
            "it silently break.",
        )

    def test_chained_just_lint_publish_pypi_is_not_allow_matched(self) -> None:
        """Regression test for SEC-1. `.claude/settings.json`'s
        `permissions.allow` is consulted against the full Bash command
        string an agent would send, never against a real permission
        engine this test can shell out to directly -- so the load-bearing
        assertion here reimplements Claude Code's documented matching
        semantics (exact string equality with no trailing `:*`, prefix
        match with one) and applies it to the exact malicious string SEC-1
        used: `just lint publish-pypi`. Before the fix, the prefix-wildcard
        `Bash(just lint:*)` entry matched this string; the exact-match
        `Bash(just lint)` entry cannot.

        The dry run below is a live confirmation that the underlying
        danger is real, not hypothetical: `just` itself really does chain
        `publish-pypi` as a second recipe here (any no-argument recipe
        followed by a further bare word runs that word as its own
        recipe), which is exactly why an allow-matched single Bash call
        must never be allowed to reach this string.
        """
        settings = json.loads(_BUNDLE_SETTINGS.read_text(encoding="utf-8"))
        allow_patterns = [
            pattern[len("Bash(") : -1]
            for pattern in settings["permissions"]["allow"]
            if pattern.startswith("Bash(") and pattern.endswith(")")
        ]

        def matches(prefix_pattern: str, command: str) -> bool:
            if prefix_pattern.endswith(":*"):
                prefix = prefix_pattern[: -len(":*")]
                return command == prefix or command.startswith(prefix + " ")
            return command == prefix_pattern

        chained_publish = "just lint publish-pypi"
        self.assertFalse(
            any(matches(pattern, chained_publish) for pattern in allow_patterns),
            f"{chained_publish!r} matches a permissions.allow entry -- a "
            "trailing-wildcard `Bash(just lint:*)` would auto-approve "
            "this exact chained-recipe string (SEC-1).",
        )

        just = _resolve_just()
        if just is None:
            self.skipTest("`just` not found on PATH or at .tools/just")
        result = subprocess.run(
            [just, "-n", "lint", "publish-pypi"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("wheel.publish", result.stdout + result.stderr)

    def test_just_test_with_extra_args_is_not_allow_matched(self) -> None:
        """Regression test for SEC-2: `just test *args` interpolates its
        variadic argument unquoted into a shell line, so any invocation
        with extra arguments is a shell-injection primitive (e.g. `just
        test '&& echo INJECTED'`). The exact-match `Bash(just test)` entry
        can only ever match the bare string `just test`, not that string
        plus a trailing argument.
        """
        settings = json.loads(_BUNDLE_SETTINGS.read_text(encoding="utf-8"))
        allow_patterns = [
            pattern[len("Bash(") : -1]
            for pattern in settings["permissions"]["allow"]
            if pattern.startswith("Bash(") and pattern.endswith(")")
        ]

        def matches(prefix_pattern: str, command: str) -> bool:
            if prefix_pattern.endswith(":*"):
                prefix = prefix_pattern[: -len(":*")]
                return command == prefix or command.startswith(prefix + " ")
            return command == prefix_pattern

        injected = "just test '&& echo INJECTED'"
        self.assertFalse(
            any(matches(pattern, injected) for pattern in allow_patterns),
            f"{injected!r} matches a permissions.allow entry -- a "
            "trailing-wildcard `Bash(just test:*)` would auto-approve "
            "this exact injection string (SEC-2).",
        )
        self.assertTrue(
            any(matches(pattern, "just test") for pattern in allow_patterns),
            "the bare `just test` invocation should still be allow-matched.",
        )


if __name__ == "__main__":
    unittest.main()
