"""Focused regression tests for the Google Python Style audit parsers."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = ROOT / ".agents/skills/audit-google-python-style/scripts/check_google_rules.py"
BUNDLED_CHECKER_PATH = ROOT / "src/codev_workflow/bundle/.agents/skills/audit-google-python-style/scripts/check_google_rules.py"


def load_module(path: Path, name: str):
    """Load a Python module from a concrete repository path."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CHECKER = load_module(CHECKER_PATH, "google_style_checker")
BUNDLED_CHECKER = load_module(BUNDLED_CHECKER_PATH, "bundled_google_style_checker")


class GoogleStyleParserTests(unittest.TestCase):
    """Cover parser contracts that previously produced false-clean results."""

    def audit_checker(self, source: str, checker=CHECKER):
        """Audit temporary source with the supplemental checker."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "sample.py"
            path.write_text(source, encoding="utf-8")
            return checker.audit(path, root)

    def test_checker_raise_matching_and_nested_scope(self):
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

    def test_directives_are_position_aware(self):
        """Accept only valid shebang and encoding directive positions."""
        valid = '#!/usr/bin/env python\n"""Module summary."""\n'
        self.assertNotIn("comment-punctuation", [f.rule for f in self.audit_checker(valid)])
        valid_encoding = '# coding: utf-8\n"""Module summary."""\n'
        self.assertNotIn("comment-punctuation", [f.rule for f in self.audit_checker(valid_encoding)])
        valid_encoding_second = '"""Module summary."""\n# coding=utf-8\n'
        self.assertNotIn("comment-punctuation", [f.rule for f in self.audit_checker(valid_encoding_second)])
        valid_emacs = '# -*- coding: utf-8 -*-\n"""Module summary."""\n'
        self.assertNotIn("comment-punctuation", [f.rule for f in self.audit_checker(valid_emacs)])
        invalid = '# ! prose\n#! prose\n# coding nonsense\n"""Module summary."""\n# coding=utf-8\n'
        findings = self.audit_checker(invalid)
        self.assertGreaterEqual([f.rule for f in findings].count("comment-punctuation"), 4)
        indented = '  #!/usr/bin/env python\n"""Module summary."""\n'
        self.assertIn("comment-punctuation", [f.rule for f in self.audit_checker(indented)])
        for malformed in (
            '# -*- coding: utf-8\n"""Module summary."""\n',
            '# coding: utf-8 -*-\n"""Module summary."""\n',
            '"""Module summary."""\n# coding=utf-8\n# coding: utf-8\n',
        ):
            self.assertIn("comment-punctuation", [f.rule for f in self.audit_checker(malformed)])

    def test_private_class_naming(self):
        """Allow private PascalCase classes and reject lowercase classes."""
        source = '''"""Module summary."""

class _Private:
    """Private class."""

class privateClass:
    """Lowercase class."""
'''
        findings = self.audit_checker(source)
        class_findings = [finding for finding in findings if finding.rule == "class-naming"]
        self.assertEqual(len(class_findings), 1)
        self.assertEqual(class_findings[0].level, "violation")

    def test_checker_callable_raise_requires_nonempty_raises(self):
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
        self.assertNotIn("docstring-raises", [finding.rule for finding in self.audit_checker(valid)])

        wrong = valid.replace("Exception: A generated error.", "ValueError: A generated error.")
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
            self.assertTrue(any(finding.level == "violation" for finding in invalid_findings))

    def test_comment_headers_and_markers_are_precise(self):
        """Keep ordinary early comments and malformed markers visible."""
        source = '''# Copyright 2024
# License GPL
# ordinary comment without period
"""Module summary."""
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
        rules = [finding.rule for finding in self.audit_checker(source)]
        self.assertEqual(rules.count("comment-punctuation"), 5)

        license_source = '''# Copyright 2024
# License GPL `bad :class:`
"""Module summary."""
'''
        rules = [finding.rule for finding in self.audit_checker(license_source)]
        self.assertIn("comment-markup", rules)
        self.assertNotIn("comment-punctuation", rules)

        pyssa_header = '''# PySSA - Python-Plugin for Sequence-to-Structure Analysis
# Copyright (C) 2024
# Martin Urban (martin.urban@example.invalid)
# Source code is available at <https://github.com/example/project>
# This program is free software: you can redistribute it.
# ordinary comment without period
"""Module summary."""
'''
        findings = self.audit_checker(pyssa_header)
        self.assertTrue(any(finding.rule == "comment-punctuation" for finding in findings))
        self.assertFalse(any(finding.rule == "comment-markup" for finding in findings))

        capitalized = '''# Copyright 2024
# License GPL
# Ordinary comment without period
"""Module summary."""
'''
        for checker_name, checker in (("local", CHECKER), ("bundled", BUNDLED_CHECKER)):
            with self.subTest(checker=checker_name, case="capitalized ordinary comment"):
                self.assertIn("comment-punctuation", [finding.rule for finding in self.audit_checker(capitalized, checker)])

        blank_separator = '''# Copyright 2024
# License GPL
#
# This program is free software; it may be redistributed.
"""Module summary."""
'''
        for checker_name, checker in (("local", CHECKER), ("bundled", BUNDLED_CHECKER)):
            with self.subTest(checker=checker_name, case="blank header separator"):
                self.assertNotIn("comment-punctuation", [finding.rule for finding in self.audit_checker(blank_separator, checker)])

if __name__ == "__main__":
    unittest.main()
