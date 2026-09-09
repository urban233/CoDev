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

import ast
import unittest
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent


def _last_statement_is_main_guard(tree: ast.Module) -> bool:
    if not tree.body:
        return False
    last = tree.body[-1]
    if not isinstance(last, ast.If):
        return False
    test = last.test
    is_name_check = (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == "__main__"
    )
    if not is_name_check:
        return False
    return any(
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Call)
        and isinstance(stmt.value.func, ast.Attribute)
        and stmt.value.func.attr == "main"
        for stmt in last.body
    )


class EveryTestClassRunsUnderBazelTests(unittest.TestCase):
    """Regression guard for the defect this module's sibling tests were
    written to catch (every-test-actually-runs): `tests/BUILD.bazel` builds
    every `test_*.py` as a `py_test` with no explicit `main`, so Bazel
    executes each file as `__main__`. A file with no
    `if __name__ == "__main__": unittest.main()` block never calls
    `unittest.main()` at all and silently runs zero tests under Bazel; a
    file whose block is not the last statement stops running before any test
    class defined after it. Both shapes stay green under CI's
    `python -m unittest discover` legs, which import rather than execute the
    module, so only this check -- or manually diffing Bazel's `Ran N tests`
    against the file's actual class count -- would catch either one.
    """

    def test_every_test_module_ends_with_a_main_guard(self) -> None:
        missing = []
        for path in sorted(_TESTS_DIR.glob("test_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if not _last_statement_is_main_guard(tree):
                missing.append(path.name)
        self.assertEqual(
            [],
            missing,
            "these tests/test_*.py files are missing a trailing "
            '`if __name__ == "__main__": unittest.main()` block, so Bazel '
            "(which runs each file as __main__ with no explicit `main=`) "
            "will run zero of their tests: " + ", ".join(missing),
        )


if __name__ == "__main__":
    unittest.main()
