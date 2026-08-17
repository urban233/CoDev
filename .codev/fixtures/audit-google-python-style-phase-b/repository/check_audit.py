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
"""Deterministic standard-library verifier for the approved style fixture."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import textwrap
import tokenize
from pathlib import Path


TARGET = Path("src/pyssa/controllers/delete_project_controller.py")
IGNORED_CHANGED_DIRECTORIES = frozenset(
    {
        ".mypy_cache",
        ".pytest_cache",
        ".pyrefly",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        ".cache",
        "cache",
        "build",
        "dist",
        "generated",
        "gen",
    }
)
SECTIONS = {"Args", "Raises", "Returns", "Yields"}


def _git_changed_paths() -> tuple[set[str] | None, str | None]:
    """Return every path reported by Git, or a fail-closed diagnostic.

    Returns:
        Changed paths and no diagnostic, or no paths and an error message.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all", "-z"],
            capture_output=True,
            check=False,
        )
    except OSError as error:
        return None, f"Could not obtain Git status: {error}."
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        return None, f"Git status failed: {detail or result.returncode}."
    try:
        output = result.stdout.decode("utf-8")
    except UnicodeDecodeError as error:
        return None, f"Git status was not valid UTF-8: {error}."
    records = output.split("\0")
    paths: set[str] = set()
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if len(record) < 4 or record[2] != " ":
            return None, "Git status contained an unparseable record."
        status = record[:2]
        path = record[3:]
        if not path:
            return None, "Git status contained an empty path."
        paths.add(path)
        if status[0] in "RC" or status[1] in "RC":
            if index >= len(records) or not records[index]:
                return None, "Git status contained an incomplete rename or copy record."
            paths.add(records[index])
            index += 1
    return paths, None


def _is_ignored_changed_path(path: str) -> bool:
    """Return whether a changed path is a generated or cache artifact."""
    path_object = Path(path)
    return (
        any(part in IGNORED_CHANGED_DIRECTORIES for part in path_object.parts)
        or path_object.suffix == ".pyc"
    )


def _current_scope(node: ast.AST, node_types, predicate) -> bool:
    """Find a node without entering nested function, class, or lambda scopes."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(child, node_types) and predicate(child):
            return True
        if _current_scope(child, node_types, predicate):
            return True
    return False


def _value_annotation(annotation: ast.expr | None) -> bool:
    """Return whether an annotation requires Returns documentation."""
    if annotation is None:
        return False
    if isinstance(annotation, ast.Constant):
        return annotation.value not in {None, "None", "Never", "NoReturn"}
    if isinstance(annotation, ast.Name):
        return annotation.id not in {"None", "Never", "NoReturn"}
    if isinstance(annotation, ast.Attribute):
        return annotation.attr not in {"Never", "NoReturn"}
    return True


def _current_scope_raises(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Return named exceptions raised in the current function scope."""
    names: list[str] = []

    def walk(current: ast.AST) -> None:
        for child in ast.iter_child_nodes(current):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            if isinstance(child, ast.Raise) and child.exc is not None:
                expression = child.exc.func if isinstance(child.exc, ast.Call) else child.exc
                if isinstance(expression, ast.Name) and expression.id[:1].isupper():
                    names.append(expression.id)
                elif isinstance(expression, ast.Attribute) and expression.attr[:1].isupper():
                    names.extend((ast.unparse(expression), expression.attr))
                else:
                    names.append("__callable_raise__")
            walk(child)

    walk(node)
    return names


def _section_or_fold_comment(text: str) -> bool:
    """Return whether a comment is a genuine section or fold marker."""
    lowered = text.lower().strip()
    return bool(
        re.fullmatch(r"<editor-fold(?:\s+desc=\"[^\"<>]*\")?>", lowered)
        or lowered == "</editor-fold>"
        or lowered in {"region", "endregion"}
        or re.fullmatch(r"-{3,}", lowered)
        or re.fullmatch(r"={3,}", lowered)
        or re.fullmatch(r"---\s+.+\s+---", lowered)
        or re.fullmatch(r"===\s+.+\s+===", lowered)
    )


def _meaningful_parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Return all parameters requiring Args entries."""
    arguments = node.args
    values = [
        *getattr(arguments, "posonlyargs", []),
        *arguments.args,
        *arguments.kwonlyargs,
    ]
    names = [value.arg for value in values if value.arg not in {"self", "cls"}]
    if arguments.vararg:
        names.append(arguments.vararg.arg)
    if arguments.kwarg:
        names.append(arguments.kwarg.arg)
    return names


def _sections(docstring: str) -> dict[str, list[tuple[str, str]]]:
    """Parse Google-style sections into named entries and descriptions."""
    sections: dict[str, list[tuple[str, str]]] = {}
    current: str | None = None
    for line in textwrap.dedent(docstring).splitlines():
        heading = line.strip().rstrip(":")
        if line.strip().endswith(":") and heading in SECTIONS:
            current = heading
            sections[current] = []
            continue
        if current is None or not line.strip():
            continue
        entry = line.strip().split(":", 1)
        if len(entry) == 2 and entry[0].strip():
            sections[current].append((entry[0].strip().lstrip("*"), entry[1].strip()))
        elif current in {"Returns", "Yields"} and not sections[current]:
            sections[current].append(("__prose__", line.strip()))
        elif sections[current]:
            name, description = sections[current][-1]
            sections[current][-1] = (name, f"{description} {line.strip()}".strip())
        else:
            sections[current].append(("__malformed__", line.strip()))
    return sections


def _check_sections(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    docstring: str,
    file_path: Path,
) -> list[str]:
    """Validate applicable and present documentation sections."""
    violations: list[str] = []
    sections = _sections(docstring)
    required_args = _meaningful_parameters(node)
    required_returns = _current_scope(node, ast.Return, lambda item: item.value is not None) or _value_annotation(node.returns)
    required_yields = _current_scope(node, (ast.Yield, ast.YieldFrom), lambda _item: True)
    raised = _current_scope_raises(node)
    required_raises = bool(raised)

    if required_args:
        entries = sections.get("Args", [])
        found = {name for name, _description in entries}
        missing = [name for name in required_args if name not in found]
        if missing:
            violations.append(f"{file_path}:{node.lineno}: Missing Args entries: {', '.join(missing)}.")
    if required_returns and not sections.get("Returns"):
        violations.append(f"{file_path}:{node.lineno}: Missing non-empty Returns section.")
    if required_yields and not sections.get("Yields"):
        violations.append(f"{file_path}:{node.lineno}: Missing non-empty Yields section.")
    if required_raises:
        entries = sections.get("Raises", [])
        if not entries:
            violations.append(f"{file_path}:{node.lineno}: Raises section must be non-empty.")
        found = {name for name, _description in entries}
        if "__callable_raise__" in raised and (len(entries) != 1 or found != {"Exception"}):
            violations.append(f"{file_path}:{node.lineno}: Dynamic raises require exactly one Exception entry.")
        missing = []
        for name in raised:
            if name == "__callable_raise__":
                continue
            leaf = name.rsplit(".", 1)[-1]
            if not any(entry == name or entry.rsplit(".", 1)[-1] == leaf for entry in found):
                missing.append(name)
        if missing:
            violations.append(f"{file_path}:{node.lineno}: Missing Raises entries: {', '.join(missing)}.")

    for section, entries in sections.items():
        if not entries or any(
            name == "__malformed__" or not description or not description.endswith(".")
            for name, description in entries
        ):
            violations.append(f"{file_path}:{node.lineno}: Entries in {section} must be non-empty and end with a period.")
    return violations


def _document_symbol(node: ast.AST, file_path: Path) -> list[str]:
    """Validate summary, markup, and function documentation."""
    violations: list[str] = []
    docstring = ast.get_docstring(node, clean=False)
    name = getattr(node, "name", "module")
    if not docstring:
        return [f"{file_path}:{getattr(node, 'lineno', 1)}: Missing docstring for '{name}'."]
    lines = [line.strip() for line in docstring.splitlines() if line.strip()]
    if not lines or not lines[0].endswith("."):
        violations.append(f"{file_path}:{getattr(node, 'lineno', 1)}: Docstring summary for '{name}' must end with a period.")
    if "`" in docstring or ":class:" in docstring:
        violations.append(f"{file_path}:{getattr(node, 'lineno', 1)}: Docstring for '{name}' contains forbidden markup.")
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        violations.extend(_check_sections(node, docstring, file_path))
    return violations


def _check_file(file_path: Path) -> list[str]:
    """Check one Python source file."""
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))
    except (OSError, UnicodeError, SyntaxError) as error:
        return [f"{file_path}: Syntax or read error: {error}."]
    violations: list[str] = []
    module_docstring_line = (
        tree.body[0].lineno
        if tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
        else None
    )
    if ast.get_docstring(tree) is None:
        violations.append(f"{file_path}:1: Missing module docstring.")
    else:
        violations.extend(_document_symbol(tree, file_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and len(node.names) > 1:
            violations.append(f"{file_path}:{node.lineno}: Multiple imports on one line.")
        if isinstance(node, ast.ImportFrom):
            if any(alias.name == "*" for alias in node.names):
                violations.append(f"{file_path}:{node.lineno}: Wildcard import is not allowed.")
            if len(node.names) > 1:
                violations.append(f"{file_path}:{node.lineno}: Multiple imported symbols on one line.")
        if isinstance(node, ast.Name) and node.id.startswith("tmp_"):
            violations.append(f"{file_path}:{node.lineno}: Illegal tmp_ binding '{node.id}'.")
        if isinstance(node, ast.arg) and node.arg.startswith("tmp_"):
            violations.append(f"{file_path}:{node.lineno}: Illegal tmp_ parameter '{node.arg}'.")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            violations.extend(_document_symbol(node, file_path))
            if node.name[0].isupper():
                violations.append(f"{file_path}:{node.lineno}: Function '{node.name}' should use snake_case.")
        if isinstance(node, ast.ClassDef):
            violations.extend(_document_symbol(node, file_path))
            if not node.name[0].isupper():
                violations.append(f"{file_path}:{node.lineno}: Class '{node.name}' should use PascalCase.")
    try:
        with file_path.open("rb") as source:
            for token in tokenize.tokenize(source.readline):
                if token.type != tokenize.COMMENT:
                    continue
                comment = token.string.lstrip("#").strip()
                if not comment:
                    continue
                if "`" in comment or ":class:" in comment:
                    violations.append(f"{file_path}:{token.start[0]}: Comment contains forbidden markup.")
                if (
                    module_docstring_line is not None
                    and token.start[0] < module_docstring_line
                ) or _section_or_fold_comment(comment):
                    continue
                if not comment.endswith("."):
                    violations.append(f"{file_path}:{token.start[0]}: Comment must end with a period.")
    except (OSError, tokenize.TokenError) as error:
        violations.append(f"{file_path}: Tokenizer error: {error}.")
    return violations


def main() -> int:
    """Verify Git scope and the approved target's Google Python Style."""
    changed, error = _git_changed_paths()
    if error:
        print(error, file=sys.stderr)
        return 1
    assert changed is not None
    target = TARGET.as_posix()
    unexpected = sorted(
        path
        for path in changed
        if path != target and not _is_ignored_changed_path(path)
    )
    if unexpected:
        print("Unexpected changed paths:", file=sys.stderr)
        for path in unexpected:
            print(f"  {path}", file=sys.stderr)
        return 1
    if not TARGET.is_file():
        print(f"Missing approved target: {TARGET}.", file=sys.stderr)
        return 1
    violations = _check_file(TARGET)
    if violations:
        print("Google Python Style Audit Violations Found:", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        return 1
    print("All Python files cleanly passed Google Python Style compliance audit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
