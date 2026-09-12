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
"""Tests for `require_green.py`'s two scientific-reproducibility checks: an
unseeded-RNG check and a dependency-gap check.

Same "pin the external contract against a fake, not the real tool" pattern
as `tests/test_require_green_hook.py`: the bundled hook is run as an
independent subprocess against fixture stdin, in a real scratch git
repository, and the block/allow paths are asserted through the hook's own
JSON contract.

Every scratch repository below plants a Justfile whose recipes always pass
(`_write_justfile` plus `_plant_passing_just`, the same technique
`test_require_green_hook.py` uses to control `_checks()`'s discovered
tooling). Without it, an "allow" fixture would fall through to this
hook's own `_checks()`, which -- absent a Justfile -- runs this
repository's real, ambient `ruff`/`mypy`/`pytest` against the scratch
fixture and can block for a reason that has nothing to do with either
check under test here (an unused import, for instance). Planting it keeps
every test scoped to the scientific-gates checks alone.

The dependency-gap check resolves an import name to a distribution name
through `importlib.metadata.packages_distributions()`, which reflects
whatever is actually installed under the interpreter running the hook
subprocess (`sys.executable`, inherited from the test process itself). This
repository does not depend on `numpy` or any other RNG-adjacent third-party
package (see the implementation plan's Repository evidence), so the
unseeded-RNG tests below spell `np.random....` calls directly, without an
accompanying `import numpy` -- an added call is all the RNG check reads, and
omitting the import keeps those tests from also tripping the (separately
and directly tested) dependency-gap check on an import this repository
cannot actually resolve. The dependency-gap tests instead use
`pre_commit`/`pre-commit` (this repository's own sole runtime dependency)
and `yaml`/`PyYAML` (one of its transitive dependencies) as the real,
actually-installed distributions to declare against.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

_HOOK = (
    Path(__file__).resolve().parent.parent
    / "src/codev_workflow/bundle/.claude/hooks/require_green.py"
)


def _run(repo: Path, payload: dict[str, Any] | None = None) -> Any:
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(payload or {"cwd": str(repo)}),
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=120,
        env=dict(os.environ),
    )


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "README.md").write_text("test\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


def _write_justfile(repo: Path) -> None:
    """A Justfile whose every recipe passes. See the module docstring for
    why every scratch repository below plants one."""
    repo.joinpath("Justfile").write_text(
        "lint:\n    @exit 0\ntypecheck:\n    @exit 0\ntest:\n    @exit 0\n",
        encoding="utf-8",
    )


def _plant_passing_just(repo: Path) -> None:
    """A repository-local `.tools/just` stand-in whose every recipe exits 0.

    The hook looks for `.tools/just` before a `just` on `PATH`, so this is
    enough to make `_checks()` use the Justfile above regardless of whether
    a real `just` binary happens to be installed wherever this suite runs.
    """
    tools = repo / ".tools"
    tools.mkdir(exist_ok=True)
    if os.name == "nt":
        (tools / "just.bat").write_text("@echo off\r\nexit /b 0\r\n", encoding="utf-8")
        return
    launcher = tools / "just"
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)


def _init_isolated_repo(path: Path) -> None:
    """A scratch repository whose own `_checks()` always passes trivially."""
    _init_repo(path)
    _write_justfile(path)
    _plant_passing_just(path)


def _commit_all(path: Path) -> None:
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "t"], cwd=path, check=True)


def _reason(result: Any) -> str:
    """The hook's block reason, or "" when it allowed."""
    if not result.stdout.strip():
        return ""
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return ""
    return str(payload.get("reason", ""))


def _decision(result: Any) -> str:
    if not result.stdout.strip():
        return "allow"
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return "allow"
    return str(payload.get("decision", "allow"))


class UnseededRngTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name)
        _init_isolated_repo(self.repo)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_blocks_an_added_unseeded_random_call(self) -> None:
        self.repo.joinpath("analysis.py").write_text(
            "import random\n\n\ndef roll():\n    return random.random()\n",
            encoding="utf-8",
        )
        result = _run(self.repo)
        self.assertEqual("block", _decision(result))
        self.assertIn("random.random()", _reason(result))

    def test_allows_when_seed_call_present_anywhere_in_the_file(self) -> None:
        self.repo.joinpath("analysis.py").write_text(
            "import random\n\n"
            "random.seed(0)\n\n\n"
            "def roll():\n    return random.random()\n",
            encoding="utf-8",
        )
        result = _run(self.repo)
        self.assertEqual("allow", _decision(result))

    def test_blocks_an_added_unseeded_numpy_random_call(self) -> None:
        # No accompanying `import numpy` -- see the module docstring.
        self.repo.joinpath("analysis.py").write_text(
            "def roll():\n    return np.random.rand()\n", encoding="utf-8"
        )
        result = _run(self.repo)
        self.assertEqual("block", _decision(result))
        self.assertIn("np.random.rand()", _reason(result))

    def test_default_rng_with_no_argument_still_blocks(self) -> None:
        """`default_rng()` is itself OS-entropy-seeded, so an empty call does
        not count as seeding anything (Decision 3)."""
        self.repo.joinpath("analysis.py").write_text(
            "def rng():\n    return np.random.default_rng()\n", encoding="utf-8"
        )
        result = _run(self.repo)
        self.assertEqual("block", _decision(result))
        self.assertIn("default_rng()", _reason(result))

    def test_default_rng_with_an_argument_allows(self) -> None:
        self.repo.joinpath("analysis.py").write_text(
            "def rng():\n    return np.random.default_rng(42)\n", encoding="utf-8"
        )
        result = _run(self.repo)
        self.assertEqual("allow", _decision(result))

    def test_allows_a_call_already_present_at_the_base_commit(self) -> None:
        """Pre-existing debt this turn did not introduce (Decision 2)."""
        path = self.repo / "analysis.py"
        path.write_text(
            "import random\n\n\ndef roll():\n    return random.random()\n",
            encoding="utf-8",
        )
        _commit_all(self.repo)
        # Touch the file without touching the offending line.
        path.write_text(
            "import random\n\n\n"
            "def roll():\n    return random.random()\n\n\n"
            "def other():\n    return 1\n",
            encoding="utf-8",
        )
        result = _run(self.repo)
        self.assertEqual("allow", _decision(result))

    def test_allows_the_same_call_inside_a_test_file(self) -> None:
        """A randomised or property-based test is a legitimate pattern, not
        the reproducibility concern this check targets (Decision 4)."""
        self.repo.joinpath("test_analysis.py").write_text(
            "import random\n\n\n"
            "def test_roll():\n    assert 0 <= random.random() < 1\n",
            encoding="utf-8",
        )
        result = _run(self.repo)
        self.assertEqual("allow", _decision(result))

    def test_ignores_an_unrelated_pre_existing_call_in_an_untouched_file(self) -> None:
        """Scoped to `_changed_source`'s file list, not a whole-repository
        scan: a file this turn never touched is not this turn's problem."""
        victim = self.repo / "victim.py"
        victim.write_text(
            "import random\n\n\ndef roll():\n    return random.random()\n",
            encoding="utf-8",
        )
        _commit_all(self.repo)
        self.repo.joinpath("other.py").write_text("x = 1\n", encoding="utf-8")
        result = _run(self.repo)
        self.assertEqual("allow", _decision(result))


class DependencyGapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name)
        _init_isolated_repo(self.repo)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_pyproject(self, dependencies: list[str]) -> None:
        deps = ", ".join(f'"{dep}"' for dep in dependencies)
        self.repo.joinpath("pyproject.toml").write_text(
            f'[project]\nname = "scratch"\nversion = "0"\ndependencies = [{deps}]\n',
            encoding="utf-8",
        )

    def test_allows_an_import_declared_in_pyproject_dependencies(self) -> None:
        self._write_pyproject(["pre-commit>=4.6.1"])
        self.repo.joinpath("analysis.py").write_text(
            "import pre_commit\n", encoding="utf-8"
        )
        result = _run(self.repo)
        self.assertEqual("allow", _decision(result))

    def test_allows_an_import_declared_only_in_requirements_txt(self) -> None:
        self._write_pyproject([])
        self.repo.joinpath("requirements.txt").write_text(
            "PyYAML==6.0\n", encoding="utf-8"
        )
        self.repo.joinpath("analysis.py").write_text("import yaml\n", encoding="utf-8")
        result = _run(self.repo)
        self.assertEqual("allow", _decision(result))

    def test_blocks_an_import_with_no_declared_dependency_and_nothing_installed(
        self,
    ) -> None:
        self._write_pyproject([])
        self.repo.joinpath("analysis.py").write_text(
            "import totally_undeclared_package_xyz\n", encoding="utf-8"
        )
        result = _run(self.repo)
        self.assertEqual("block", _decision(result))
        self.assertIn("totally_undeclared_package_xyz", _reason(result))

    def test_never_flags_a_stdlib_import(self) -> None:
        self._write_pyproject([])
        self.repo.joinpath("analysis.py").write_text(
            "import json\n\njson.dumps({})\n", encoding="utf-8"
        )
        result = _run(self.repo)
        self.assertEqual("allow", _decision(result))

    def test_never_flags_a_first_party_import_in_a_flat_layout(self) -> None:
        self._write_pyproject([])
        package = self.repo / "mypkg"
        package.mkdir()
        (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
        _commit_all(self.repo)
        self.repo.joinpath("analysis.py").write_text(
            "import mypkg\n\nmypkg.VALUE\n", encoding="utf-8"
        )
        result = _run(self.repo)
        self.assertEqual("allow", _decision(result))

    def test_never_flags_a_first_party_import_in_a_src_layout(self) -> None:
        self._write_pyproject([])
        package = self.repo / "src" / "mypkg"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
        _commit_all(self.repo)
        self.repo.joinpath("analysis.py").write_text(
            "import mypkg\n\nmypkg.VALUE\n", encoding="utf-8"
        )
        result = _run(self.repo)
        self.assertEqual("allow", _decision(result))

    def test_never_flags_a_sibling_module_in_the_importing_files_own_directory(
        self,
    ) -> None:
        """Reproduces this task's own `require_plan.py` importing
        `_hook_common`, which lives beside it rather than at the repository
        root or under `src/` -- neither of `_is_first_party`'s other two
        bases would resolve it."""
        self._write_pyproject([])
        subdir = self.repo / "hooks"
        subdir.mkdir()
        (subdir / "_sibling_helper.py").write_text("VALUE = 1\n", encoding="utf-8")
        _commit_all(self.repo)
        subdir.joinpath("consumer.py").write_text(
            "import _sibling_helper\n\n_sibling_helper.VALUE\n", encoding="utf-8"
        )
        result = _run(self.repo)
        self.assertEqual("allow", _decision(result))

    def test_applies_uniformly_to_a_test_file(self) -> None:
        """Unlike the RNG check, test files are not excluded (Decision 4): a
        missing dependency breaks a test environment just as much."""
        self._write_pyproject([])
        self.repo.joinpath("test_analysis.py").write_text(
            "import totally_undeclared_package_xyz\n", encoding="utf-8"
        )
        result = _run(self.repo)
        self.assertEqual("block", _decision(result))
        self.assertIn("totally_undeclared_package_xyz", _reason(result))


class ScientificGatesScopeTests(unittest.TestCase):
    """Both checks are gated behind `_changed_source`, the same as every
    other check in this hook: a turn that changed no source runs neither."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name)
        _init_isolated_repo(self.repo)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_skipped_entirely_on_a_turn_that_changed_no_source(self) -> None:
        path = self.repo / "analysis.py"
        path.write_text(
            "import random\n\n\ndef roll():\n    return random.random()\n",
            encoding="utf-8",
        )
        _commit_all(self.repo)
        result = _run(self.repo)
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
