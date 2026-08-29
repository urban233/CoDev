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
"""Focused regression tests for the Google Python Style audit parsers."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = (
    ROOT / ".agents/skills/audit-google-python-style/scripts/check_google_rules.py"
)
BUNDLED_CHECKER_PATH = (
    ROOT / "src/codev_workflow/bundle/.agents/skills/audit-google-python-style/"
    "scripts/check_google_rules.py"
)


def load_module(path: Path, name: str) -> ModuleType:
    """Load a Python module from a concrete repository path."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CHECKER = load_module(CHECKER_PATH, "google_style_checker")
BUNDLED_CHECKER = load_module(BUNDLED_CHECKER_PATH, "bundled_google_style_checker")


class GoogleStyleParserTests(unittest.TestCase):
    """Cover parser contracts that previously produced false-clean results."""

    def audit_checker(self, source: str, checker: Any = CHECKER) -> list[Any]:
        """Audit temporary source with the supplemental checker."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "sample.py"
            path.write_text(source, encoding="utf-8")
            return cast(list[Any], checker.audit(path, root))

    def test_checker_raise_matching_and_nested_scope(self) -> None:
        """Require matching qualified raises but ignore nested contracts."""
        source = '''"""Module summary."""

def qualified():
    """Raise an error.

    Raises:
        BadError: A bad error.
    """
    raise errors.BadError()

def qualified_full():
    """Raise an error with a qualified entry.

    Raises:
        errors.BadError: A bad error.
    """
    raise errors.BadError()

def qualified_reverse():
    """Raise an error with a reverse qualified entry.

    Raises:
        errors.BadError: A bad error.
    """
    raise BadError()

def nested_only() -> None:
    """Run nested code."""
    def inner():
        """Raise an inner error.

        Raises:
            ValueError: An inner error.
        """
        raise ValueError()
    pass

def wrong():
    """Raise an error.

    Raises:
        ValueError: A wrong error.
    """
    raise errors.BadError()
'''
        findings = self.audit_checker(source)
        rules = [finding.rule for finding in findings]
        self.assertIn("docstring-raises", rules)
        self.assertTrue(any(finding.level == "violation" for finding in findings))
        self.assertEqual(rules.count("docstring-raises"), 1)

    def test_private_class_naming(self) -> None:
        """Allow private PascalCase classes and reject lowercase classes."""
        source = '''"""Module summary."""

class _Private:
    """Private class."""

class privateClass:
    """Lowercase class."""
'''
        findings = self.audit_checker(source)
        class_findings = [
            finding for finding in findings if finding.rule == "class-naming"
        ]
        self.assertEqual(len(class_findings), 1)
        self.assertEqual(class_findings[0].level, "violation")

    def test_checker_callable_raise_requires_nonempty_raises(self) -> None:
        """Require Raises documentation for callable-generated exceptions."""
        source = '''"""Module summary."""

def generated():
    """Generate an error."""
    raise make_error()
'''
        findings = self.audit_checker(source)
        rules = [finding.rule for finding in findings]
        self.assertIn("docstring-raises", rules)
        self.assertTrue(any(finding.level == "violation" for finding in findings))

        valid = source.replace(
            '    """Generate an error."""',
            '''    """Generate an error.

    Raises:
        Exception: A generated error.
    """''',
        )
        self.assertNotIn(
            "docstring-raises", [finding.rule for finding in self.audit_checker(valid)]
        )

        wrong = valid.replace(
            "Exception: A generated error.", "ValueError: A generated error."
        )
        wrong_findings = self.audit_checker(wrong)
        self.assertIn("docstring-raises", [finding.rule for finding in wrong_findings])
        self.assertTrue(any(finding.level == "violation" for finding in wrong_findings))

        for entry in (
            "Exception: A generated error.\n        ValueError: An extra error.",
            "Exception:",
            "Exception: A generated error",
        ):
            invalid = source.replace(
                '    """Generate an error."""',
                f'''    """Generate an error.

    Raises:
        {entry}
    """''',
            )
            invalid_findings = self.audit_checker(invalid)
            self.assertTrue(
                any(finding.level == "violation" for finding in invalid_findings)
            )

    def test_leading_comments_are_excluded_and_markers_are_precise(self) -> None:
        """Exclude leading comments while checking later comments and markers."""
        source = '''# Leading comment without punctuation or `allowed` :class: markup
"""Module summary."""
# ordinary comment without period
# region nonsense
# region: Checks
# endregion nonsense
# <editor-fold bad>
# <editor-fold desc="Checks">
# </editor-fold>
# region
# endregion
# --- heading ---
# === heading ===
'''
        findings = self.audit_checker(source)
        rules = [finding.rule for finding in findings]
        self.assertEqual(rules.count("comment-punctuation"), 5)
        self.assertFalse(any(finding.line == 1 for finding in findings))

    def test_mutable_function_defaults_are_rejected(self) -> None:
        """Reject known mutable defaults while allowing immutable defaults."""
        source = '''"""Module summary."""

def invalid_defaults(
    items=[],
    mapping={},
    names=set(),
    generated=[item for item in ()],
    *,
    options=dict(),
):
    """Use invalid defaults.

    Args:
        items: Item values.
        mapping: Mapped values.
        names: Name values.
        generated: Generated values.
        options: Option values.
    """

async def valid_defaults(value=None, values=(), *, names=frozenset()):
    """Use immutable defaults.

    Args:
        value: Optional value.
        values: Immutable values.
        names: Immutable names.
    """
'''
        for checker_name, checker in (
            ("local", CHECKER),
            ("bundled", BUNDLED_CHECKER),
        ):
            with self.subTest(checker=checker_name):
                findings = self.audit_checker(source, checker)
                mutable_defaults = [
                    finding for finding in findings if finding.rule == "mutable-default"
                ]
                self.assertEqual(len(mutable_defaults), 5)
                self.assertTrue(
                    all(finding.level == "violation" for finding in mutable_defaults)
                )

    def test_shadowed_mutable_constructor_defaults_require_review(self) -> None:
        """Review constructor defaults when built-in resolution is uncertain."""
        source = '''"""Module summary."""

list = tuple

def module_shadowed(items=list()):
    """Use a module-shadowed constructor.

    Args:
        items: Item values.
    """

class Container:
    """Contain a class-shadowed constructor."""

    set = frozenset

    def class_shadowed(self, names=set()):
        """Use a class-shadowed constructor.

        Args:
            names: Name values.
        """

def enclosing(dict):
    """Define a function with an enclosing shadow.

    Args:
        dict: Mapping factory.
    """
    def function_shadowed(mapping=dict()):
        """Use an enclosing-function-shadowed constructor.

        Args:
            mapping: Mapped values.
        """
'''
        for checker_name, checker in (
            ("local", CHECKER),
            ("bundled", BUNDLED_CHECKER),
        ):
            with self.subTest(checker=checker_name):
                findings = self.audit_checker(source, checker)
                mutable_defaults = [
                    finding for finding in findings if finding.rule == "mutable-default"
                ]
                self.assertEqual(len(mutable_defaults), 3)
                self.assertTrue(
                    all(finding.level == "review" for finding in mutable_defaults)
                )

    def test_comprehension_targets_do_not_shadow_mutable_constructors(self) -> None:
        """Keep comprehension-local names out of enclosing scope resolution."""
        source = '''"""Module summary."""

def enclosing(values):
    """Define a function after a comprehension.

    Args:
        values: Source values.
    """
    observed = [value for list in values for value in list]

    def still_builtin(items=list()):
        """Use an unshadowed built-in constructor.

        Args:
            items: Item values.
        """

def enclosing_named_expression(values):
    """Define a function after a containing-scope binding.

    Args:
        values: Source values.
    """
    observed = [(list := tuple) for value in values]

    def shadowed(items=list()):
        """Use a constructor shadowed from a comprehension.

        Args:
            items: Item values.
        """
'''
        for checker_name, checker in (
            ("local", CHECKER),
            ("bundled", BUNDLED_CHECKER),
        ):
            with self.subTest(checker=checker_name):
                findings = self.audit_checker(source, checker)
                mutable_defaults = [
                    finding for finding in findings if finding.rule == "mutable-default"
                ]
                self.assertEqual(len(mutable_defaults), 2)
                self.assertEqual(
                    [finding.level for finding in mutable_defaults],
                    ["violation", "review"],
                )

    def test_definition_time_bindings_shadow_mutable_constructors(self) -> None:
        """Resolve defaults in their containing lexical scope."""
        source = '''"""Module summary."""

def binder(first=(list := tuple), second=list()):
    """Bind a constructor while evaluating defaults.

    Args:
        first: First default value.
        second: Second default value.
    """
'''
        for checker_name, checker in (
            ("local", CHECKER),
            ("bundled", BUNDLED_CHECKER),
        ):
            with self.subTest(checker=checker_name):
                findings = self.audit_checker(source, checker)
                mutable_defaults = [
                    finding for finding in findings if finding.rule == "mutable-default"
                ]
                self.assertEqual(len(mutable_defaults), 1)
                self.assertEqual(mutable_defaults[0].level, "review")

    def test_pattern_captures_shadow_mutable_constructors(self) -> None:
        """Collect each structural pattern capture form as a binding."""
        source = '''"""Module summary."""

def capture_names(value):
    """Capture constructor names from patterns.

    Args:
        value: Value to match.
    """
    match value:
        case list:
            pass

    def match_as(items=list()):
        """Use a match-as-shadowed constructor.

        Args:
            items: Item values.
        """

def capture_sequences(value):
    """Capture a constructor name from a sequence.

    Args:
        value: Value to match.
    """
    match value:
        case [*dict]:
            pass

    def match_star(mapping=dict()):
        """Use a match-star-shadowed constructor.

        Args:
            mapping: Mapped values.
        """

def capture_mappings(value):
    """Capture a constructor name from a mapping.

    Args:
        value: Value to match.
    """
    match value:
        case {**set}:
            pass

    def match_mapping(names=set()):
        """Use a match-mapping-shadowed constructor.

        Args:
            names: Name values.
        """
'''
        for checker_name, checker in (
            ("local", CHECKER),
            ("bundled", BUNDLED_CHECKER),
        ):
            with self.subTest(checker=checker_name):
                findings = self.audit_checker(source, checker)
                mutable_defaults = [
                    finding for finding in findings if finding.rule == "mutable-default"
                ]
                self.assertEqual(len(mutable_defaults), 3)
                self.assertTrue(
                    all(finding.level == "review" for finding in mutable_defaults)
                )

    @unittest.skipIf(sys.version_info < (3, 12), "PEP 695 requires Python 3.12")
    def test_type_parameters_shadow_mutable_constructors(self) -> None:
        """Collect generic function and class type parameters as bindings."""
        source = '''"""Module summary."""

def outer[list]():
    """Define a generic function."""

    def inner(items=list()):
        """Use a function-type-parameter-shadowed constructor.

        Args:
            items: Item values.
        """

class Container[dict]:
    """Define a generic class."""

    def inner(self, mapping=dict()):
        """Use a class-type-parameter-shadowed constructor.

        Args:
            mapping: Mapped values.
        """
'''
        for checker_name, checker in (
            ("local", CHECKER),
            ("bundled", BUNDLED_CHECKER),
        ):
            with self.subTest(checker=checker_name):
                findings = self.audit_checker(source, checker)
                mutable_defaults = [
                    finding for finding in findings if finding.rule == "mutable-default"
                ]
                self.assertEqual(len(mutable_defaults), 2)
                self.assertTrue(
                    all(finding.level == "review" for finding in mutable_defaults)
                )

    def test_delete_project_controller_fixtures_are_audited(self) -> None:
        """Audit both required controller fixture classes."""
        fixture_root = ROOT / ".codev/eval/tasks"
        phase_a_repo = fixture_root / "audit-google-python-style-phase-a" / "repository"
        phase_a_target = (
            phase_a_repo / "src/pyssa/controllers/delete_project_controller.py"
        )
        phase_b_repo = fixture_root / "audit-google-python-style-phase-b" / "repository"
        phase_b_target = (
            phase_b_repo / "src/pyssa/controllers/delete_project_controller.py"
        )
        for checker_name, checker in (
            ("local", CHECKER),
            ("bundled", BUNDLED_CHECKER),
        ):
            with self.subTest(
                fixture="audit-google-python-style-phase-a", checker=checker_name
            ):
                findings = checker.audit(phase_a_target, phase_a_repo)
                self.assertTrue(
                    any(
                        finding.rule == "docstring-markup" and finding.line == 44
                        for finding in findings
                    )
                )
            with self.subTest(
                fixture="audit-google-python-style-phase-b", checker=checker_name
            ):
                findings = checker.audit(phase_b_target, phase_b_repo)
                violations = [f for f in findings if f.level == "violation"]
                self.assertFalse(
                    violations,
                    "Expected no violations in phase-b fixture but found: "
                    f"{violations}",
                )


if __name__ == "__main__":
    unittest.main()
