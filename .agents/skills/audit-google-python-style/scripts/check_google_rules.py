#!/usr/bin/env python3
"""Run deterministic, standard-library Google Python Style checks."""

from __future__ import annotations

import argparse
import ast
import dataclasses
import json
import pathlib
import re
import sys
import textwrap
import tokenize


@dataclasses.dataclass(frozen=True)
class Finding:
    """Represent one audit result."""

    level: str
    rule: str
    file: str
    line: int
    column: int
    message: str


EXCLUDED = frozenset({
    ".git", ".agents", ".mypy_cache", ".pytest_cache", ".pyrefly",
    ".ruff_cache", ".venv", "__pycache__", "cache", ".cache", "build", "dist", "generated",
    "gen", "node_modules", "site-packages", "vendor",
})
DUNDER = re.compile(r"^__[^_].*__$")
TYPE_COMMENT = re.compile(r"#\s*type:\s*(?!ignore\b)")
TODO = re.compile(r"#\s*TODO(?!\s*:\s*\S+\s+-\s+\S+)", re.IGNORECASE)
PYLINT = re.compile(r"#\s*pylint\s*:", re.IGNORECASE)
SECTION = re.compile(r"^(Args|Raises|Returns|Yields):$")
LICENSE_MARKERS = (
    "copyright", "license", "licensed", "spdx", "gnu general public license",
    "free software foundation", "warranty", "redistribution",
)
HEADER_LINE_PATTERNS = (
    "copyright", "spdx-license-identifier", "license", "licensed", "gnu ",
    "free software foundation", "warranty", "redistribution", "source code",
    "this program", "you should", "along with", "without", "either ",
)
SHEBANG = re.compile(r"^#!\s*/[A-Za-z0-9_.+/-]+(?:\s+.*)?$")
ENCODING_PLAIN = re.compile(r"^coding[:=]\s*[-\w.]+$")
ENCODING_EMACS = re.compile(r"^-\*-\s*coding[:=]\s*[-\w.]+\s*-\*-$")


def header_comment_lines(source):
    """Return punctuation-exempt lines in a recognized leading header.

    Args:
        source: Python source text.
    Returns:
        Header comment line numbers.
    """
    leading = []
    for number, line in enumerate(source.splitlines()[:25], start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            if stripped.startswith("#"):
                leading.append((number, stripped[1:].strip()))
            continue
        break
    def structured(text, continuation=False):
        """Return whether a comment resembles structured header text.

        Args:
            text: Comment text without its hash.
            continuation: Whether a legal continuation line follows a marker.
        Returns:
            Whether the text is structured header content.
        """
        lowered = text.lower()
        return (
            any(lowered.startswith(pattern) for pattern in HEADER_LINE_PATTERNS)
            or bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*\s+-\s+Python\b.*", text))
            or (continuation and text == "")
            or (continuation and bool(re.fullmatch(r"[A-Z][A-Za-z'-]+(?:\s+[A-Z][A-Za-z'-]+)+\s+\([^)]*@[^)]*\)", text)))
        )

    markers = [index for index, (_, text) in enumerate(leading) if structured(text) and any(marker in text.lower() for marker in LICENSE_MARKERS)]
    directives = set()
    raw_lines = source.splitlines()
    for number, line in enumerate(raw_lines[:2], start=1):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        text = stripped[1:].strip()
        if (number == 1 and SHEBANG.fullmatch(line)) or (
            number in {1, 2}
            and (ENCODING_PLAIN.fullmatch(text) or ENCODING_EMACS.fullmatch(text))
        ):
            directives.add(number)
    if not markers:
        return directives
    exempt = set()
    for number, text in leading[min(markers):]:
        if text == "":
            exempt.add(number)
            continue
        if not structured(text, continuation=True):
            break
        exempt.add(number)
    for number, text in leading[:min(markers)]:
        if structured(text):
            exempt.add(number)
    return exempt | directives


def section_or_fold_comment(text):
    """Return whether a comment is a genuine section or fold marker.

    Args:
        text: Comment text without its hash.
    Returns:
        Whether punctuation is exempt.
    """
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


def add(results, root, path, node, rule, level, message, line=None):
    """Append a finding with a stable relative location.

    Args:
        results: Finding collection.
        root: Audit root.
        path: Source path.
        node: Source node.
        rule: Rule identifier.
        level: Finding severity.
        message: Finding message.
        line: Optional source line.
    """
    results.append(Finding(level, rule, path.relative_to(root).as_posix(), line or getattr(node, "lineno", 1), getattr(node, "col_offset", 0) + 1, message))


def valid_snake(name):
    """Return whether a function or binding uses snake case.

    Args:
        name: Candidate name.
    Returns:
        Whether the name is valid.
    """
    return name == "_" or bool(re.fullmatch(r"_+[a-z][a-z0-9_]*|[a-z][a-z0-9_]*|__[^_].*__", name))


def valid_class(name):
    """Return whether a class uses PascalCase.

    Args:
        name: Candidate name.
    Returns:
        Whether the name is valid.
    """
    return bool(re.fullmatch(r"_?[A-Z][A-Za-z0-9]*", name))


def meaningful_args(node):
    """Return function parameters that need Args entries.

    Args:
        node: Function syntax node.
    Returns:
        Parameter names.
    """
    args = [*getattr(node.args, "posonlyargs", []), *node.args.args, *node.args.kwonlyargs]
    names = [arg.arg for arg in args if arg.arg not in {"self", "cls"}]
    if node.args.vararg:
        names.append(node.args.vararg.arg)
    if node.args.kwarg:
        names.append(node.args.kwarg.arg)
    return names


def has_value_return(node):
    """Return whether a function returns a value.

    Args:
        node: Function syntax node.
    Returns:
        Whether a value is returned.
    """
    if _contains_current_scope(node, ast.Return, lambda item: item.value is not None):
        return True
    return _has_value_return_annotation(node.returns)


def _has_value_return_annotation(annotation):
    """Return whether an annotation represents a value-returning contract.

    Args:
        annotation: Return annotation node, if present.
    Returns:
        Whether Returns documentation is applicable.
    """
    if annotation is None:
        return False
    if isinstance(annotation, ast.Constant):
        return annotation.value not in {None, "None", "NoReturn", "Never"}
    if isinstance(annotation, ast.Name):
        return annotation.id not in {"None", "NoReturn", "Never"}
    if isinstance(annotation, ast.Attribute):
        return annotation.attr not in {"NoReturn", "Never"}
    return True


def has_yield(node):
    """Return whether a function yields values.

    Args:
        node: Function syntax node.
    Returns:
        Whether values are yielded.
    """
    return _contains_current_scope(node, (ast.Yield, ast.YieldFrom), lambda item: True)


def _contains_current_scope(node, node_types, predicate):
    """Find a matching node without entering nested executable scopes.

    Args:
        node: Current function node.
        node_types: AST type or types to find.
        predicate: Additional matching predicate.
    Returns:
        Whether a matching node exists in the current scope.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(child, node_types) and predicate(child):
            return True
        if _contains_current_scope(child, node_types, predicate):
            return True
    return False


def current_scope_raises(node):
    """Return normalized exception names raised in the current scope.

    Args:
        node: Current function node.
    Returns:
        Qualified, leaf, or callable-raise markers.
    """
    names = []

    def walk(current):
        """Walk current executable scope only.

        Args:
            current: Current AST node.
        """
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


def _is_test_file(path):
    """Return whether a path conventionally identifies a test module.

    Args:
        path: Source path.
    Returns:
        Whether the path is a test file.
    """
    return path.name.startswith("test_") or path.name.endswith("_test.py")


def _is_mutable_value(node):
    """Return whether an expression likely creates mutable state.

    Args:
        node: Expression node.
    Returns:
        Whether the expression is likely mutable.
    """
    if isinstance(node, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)):
        return True
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"dict", "list", "set"}


def _is_ast_visitor_hook(name):
    """Return whether a name is an exact AST visitor dispatch override.

    Args:
        name: Candidate method name.
    Returns:
        Whether the name maps to an AST node class.
    """
    if not name.startswith("visit_"):
        return False
    node_type = getattr(ast, name[6:], None)
    return isinstance(node_type, type) and issubclass(node_type, ast.AST)


def doc_findings(results, root, path, node, kind):
    """Check documentation and naming for one documentable symbol.

    Args:
        results: Finding collection.
        root: Audit root.
        path: Source path.
        node: Documentable syntax node.
        kind: Symbol kind.
    """
    doc = ast.get_docstring(node, clean=False)
    if doc is None:
        add(results, root, path, node, f"{kind}-docstring", "violation", f"Add a docstring for this {kind}.")
        doc = ""
    doc = textwrap.dedent(doc)
    lines = doc.splitlines()
    if not lines or not lines[0].strip().endswith("."):
        add(results, root, path, node, "docstring-summary", "violation", "Docstring summary must end with a period.")
    if "`" in doc or ":class:" in doc:
        add(results, root, path, node, "docstring-markup", "violation", "Docstrings must not contain backticks or Sphinx class markup.")
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        required = "Yields" if has_yield(node) else "Returns" if has_value_return(node) else None
        sections = _doc_sections(lines)
        if meaningful_args(node):
            _check_section_entries(results, root, path, node, sections, "Args", meaningful_args(node))
        if required:
            _check_section_entries(results, root, path, node, sections, required, None)
        raised = current_scope_raises(node)
        if raised and "Raises" not in sections:
            add(results, root, path, node, "docstring-raises", "violation", "Document current-scope raises in a Raises section.")
        if raised and "Raises" in sections:
            found = {name for name, _description in sections["Raises"]}
            if "__callable_raise__" in raised and (len(sections["Raises"]) != 1 or found != {"Exception"}):
                add(results, root, path, node, "docstring-raises", "violation", "Dynamic raises require exactly one Exception entry.")
            missing = [
                name for name in raised
                if name != "__callable_raise__"
                and not (
                    name in found
                    or name.rsplit(".", 1)[-1] in found
                    or any(entry.rsplit(".", 1)[-1] == name.rsplit(".", 1)[-1] for entry in found)
                )
            ]
            if missing:
                add(results, root, path, node, "docstring-raises", "violation", f"Raises entries do not match: {', '.join(missing)}.")
        if "Raises" in sections:
            _check_section_entries(results, root, path, node, sections, "Raises", None)


def _doc_sections(lines):
    """Parse Google-style documentation sections and their logical entries.

    Args:
        lines: Dedented docstring lines.
    Returns:
        Section names mapped to entry descriptions.
    """
    sections = {}
    current = None
    current_name = None
    for line in lines:
        heading = re.match(r"^\s*(Args|Raises|Returns|Yields):\s*$", line)
        if heading:
            current_name = heading.group(1)
            current = []
            sections[current_name] = current
            continue
        if current is None:
            continue
        entry = re.match(r"^\s*([^:]+):\s*(.*)$", line)
        if entry:
            current.append([entry.group(1).strip(), entry.group(2).strip()])
        elif line.strip() and current_name in {"Returns", "Yields"} and not current:
            current.append(["__prose__", line.strip()])
        elif line.strip() and current and current[-1][1]:
            current[-1][1] += " " + line.strip()
    return sections


def _check_section_entries(results, root, path, node, sections, section, required):
    """Validate required section entries and punctuation.

    Args:
        results: Finding collection.
        root: Audit root.
        path: Source path.
        node: Documentable node.
        sections: Parsed documentation sections.
        section: Section name.
        required: Required parameter names, or None for prose sections.
    """
    entries = sections.get(section)
    if not entries:
        rule = "docstring-args" if section == "Args" else f"docstring-{section.lower()}"
        add(results, root, path, node, rule, "violation", f"Document non-empty entries in {section}.")
        return
    if required:
        found = {entry[0].lstrip("*").split()[0] for entry in entries}
        missing = [name for name in required if name not in found]
        if missing:
            add(results, root, path, node, "docstring-args", "violation", f"Document every parameter in Args; missing {', '.join(missing)}.")
    if any(not description or not description.endswith(".") for _, description in entries):
        add(results, root, path, node, "docstring-section-punctuation", "violation", f"Descriptions in {section} must be non-empty and end with a period.")


class Visitor(ast.NodeVisitor):
    """Collect AST-based audit findings without treating methods as nested functions."""

    def __init__(self, root, path):
        """Initialize the visitor.

        Args:
            root: Audit root.
            path: Source path.
        """
        self.root, self.path, self.results, self.scopes = root, path, [], ["module"]

    def visit_Import(self, node):
        """Check ordinary import statements.

        Args:
            node: Import syntax node.
        """
        if len(node.names) > 1:
            add(self.results, self.root, self.path, node, "multiple-imports", "violation", "Each import statement must contain one module.")
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        """Check from-import statements.

        Args:
            node: Import syntax node.
        """
        if len(node.names) > 1:
            add(self.results, self.root, self.path, node, "multiple-from-imports", "violation", "Each from-import statement must contain one symbol.")
        if any(alias.name == "*" for alias in node.names):
            add(self.results, self.root, self.path, node, "no-wildcard-imports", "violation", "Wildcard imports are forbidden.")
        if node.level:
            add(self.results, self.root, self.path, node, "absolute-imports", "violation", "Use an absolute import path.")
        if node.module == "typing" and any(alias.name == "Text" for alias in node.names):
            add(self.results, self.root, self.path, node, "no-typing-text", "violation", "Use str instead of typing.Text.")
        if node.module in {"typing", "typing_extensions"} and any(alias.name in {"List", "Dict", "Set", "Tuple"} for alias in node.names):
            add(self.results, self.root, self.path, node, "legacy-typing-alias", "review", "Prefer built-in collection types when supported.")
        self.generic_visit(node)

    def visit_Attribute(self, node):
        """Check qualified legacy typing names.

        Args:
            node: Attribute syntax node.
        """
        if isinstance(node.value, ast.Name) and node.value.id == "typing" and node.attr == "Text":
            add(self.results, self.root, self.path, node, "no-typing-text", "violation", "Use str instead of typing.Text.")
        self.generic_visit(node)

    def visit_ExceptHandler(self, node):
        """Flag broad exception handlers for review.

        Args:
            node: Exception handler node.
        """
        if node.type is None or (isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"}):
            add(self.results, self.root, self.path, node, "broad-exception", "review", "Confirm that catching a broad exception is justified.")
        self.generic_visit(node)

    def visit_Assert(self, node):
        """Flag assertions outside conventional tests.

        Args:
            node: Assertion node.
        """
        if not _is_test_file(self.path):
            add(self.results, self.root, self.path, node, "assertion-control-flow", "review", "Confirm that assert is not application control flow.")
        self.generic_visit(node)

    def visit_Lambda(self, node):
        """Flag lambdas for readability review.

        Args:
            node: Lambda node.
        """
        add(self.results, self.root, self.path, node, "lambda-expression", "review", "Confirm that a lambda is clearer than a named function.")
        self.generic_visit(node)

    def visit_Name(self, node):
        """Check variable and binding names.

        Args:
            node: Name syntax node.
        """
        if isinstance(node.ctx, (ast.Store, ast.Del)) and node.id.startswith("tmp_"):
            add(self.results, self.root, self.path, node, "tmp-prefix", "violation", "Bindings must not use the tmp_ prefix.")
        if isinstance(node.ctx, (ast.Store, ast.Del)) and not (node.id.isupper() or valid_snake(node.id)):
            add(self.results, self.root, self.path, node, "binding-naming", "violation", "Bindings must use snake_case or an uppercase constant name.")

    def visit_arg(self, node):
        """Check parameter names.

        Args:
            node: Parameter syntax node.
        """
        if node.arg.startswith("tmp_"):
            add(self.results, self.root, self.path, node, "tmp-prefix", "violation", "Parameters must not use the tmp_ prefix.")
        if not valid_snake(node.arg):
            add(self.results, self.root, self.path, node, "parameter-naming", "violation", "Parameters must use snake_case.")

    def visit_FunctionDef(self, node):
        """Check synchronous function documentation and names.

        Args:
            node: Function syntax node.
        """
        self._function(node)

    def visit_AsyncFunctionDef(self, node):
        """Check asynchronous function documentation and names.

        Args:
            node: Function syntax node.
        """
        self._function(node)

    def _function(self, node):
        """Check one function node.

        Args:
            node: Function syntax node.
        """
        if node.name.startswith("tmp_"):
            add(self.results, self.root, self.path, node, "tmp-prefix", "violation", "Functions must not use the tmp_ prefix.")
        if not (_is_ast_visitor_hook(node.name) or DUNDER.fullmatch(node.name) or valid_snake(node.name)):
            add(self.results, self.root, self.path, node, "function-naming", "violation", "Functions and methods must use snake_case.")
        doc_findings(self.results, self.root, self.path, node, "function")
        if self.scopes[-1] == "function":
            add(self.results, self.root, self.path, node, "nested-function", "review", "Review whether this nested function is necessary.")
        if node.end_lineno is not None and node.end_lineno - node.lineno + 1 > 40:
            add(self.results, self.root, self.path, node, "function-length", "review", "Review whether this function can remain focused below about 40 lines.")
        self.scopes.append("function")
        self.generic_visit(node)
        self.scopes.pop()

    def visit_Assign(self, node):
        """Flag likely mutable module and class state.

        Args:
            node: Assignment node.
        """
        if self.scopes[-1] in {"module", "class"} and _is_mutable_value(node.value):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if not names or any(not name.isupper() for name in names):
                add(self.results, self.root, self.path, node, "mutable-global-state", "review", "Review mutable module or class state and document its justification.")
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        """Check class documentation and names.

        Args:
            node: Class syntax node.
        """
        if not valid_class(node.name):
            add(self.results, self.root, self.path, node, "class-naming", "violation", "Classes must use PascalCase.")
        if self.scopes[-1] != "module":
            add(self.results, self.root, self.path, node, "nested-class", "review", "Review whether this nested class is necessary.")
        doc_findings(self.results, self.root, self.path, node, "class")
        self.scopes.append("class")
        self.generic_visit(node)
        self.scopes.pop()


def token_findings(source, root, path):
    """Check comments, punctuation, and tokenization.

    Args:
        source: Python source text.
        root: Audit root.
        path: Source path.
    Returns:
        Token findings.
    """
    results = []
    for line_number, line in enumerate(source.splitlines(), start=1):
        if len(line) > 80:
            add(results, root, path, ast.Constant(value=None), "line-length", "review", "Review this line over the Google 80-character limit.", line_number)
        if TYPE_COMMENT.search(line):
            add(results, root, path, ast.Constant(value=None), "type-comments", "violation", "Use annotations instead of type comments.", line_number)
        if TODO.search(line):
            add(results, root, path, ast.Constant(value=None), "todo-format", "review", "Use TODO: context - explanation with a traceable context link.", line_number)
        if PYLINT.search(line):
            add(results, root, path, ast.Constant(value=None), "ruff-suppression", "review", "Review whether this Pylint suppression should be replaced with scoped Ruff syntax.", line_number)
        if re.search(r"\\\s*$", line) and not line.lstrip().startswith("#"):
            add(results, root, path, ast.Constant(value=None), "explicit-line-continuation", "review", "Prefer implicit line joining.", line_number)
    try:
        tokens = tokenize.generate_tokens(iter(source.splitlines(keepends=True)).__next__)
        for token in tokens:
            if token.type == tokenize.OP and token.string == ";":
                add(results, root, path, token, "semicolons", "violation", "Do not use statement semicolons.", token.start[0])
            if token.type != tokenize.COMMENT:
                continue
            text = token.string.lstrip("#").strip()
            if not text:
                continue
            if "`" in text or ":class:" in text:
                add(results, root, path, token, "comment-markup", "violation", "Comments must not contain backticks or Sphinx class markup.", token.start[0])
            if token.start[0] in header_comment_lines(source) or section_or_fold_comment(text):
                continue
            if not text.endswith("."):
                add(results, root, path, token, "comment-punctuation", "violation", "Code comments must end with a period.", token.start[0])
    except (tokenize.TokenError, IndentationError) as error:
        add(results, root, path, ast.Constant(value=None), "tokenization", "violation", f"Tokenization failed: {error}.")
    return results


def audit(path, root):
    """Audit one Python file.

    Args:
        path: Source path.
        root: Audit root.
    Returns:
        Findings for the file.
    """
    try:
        with tokenize.open(path) as source_file:
            source = source_file.read()
    except (OSError, UnicodeError, SyntaxError) as error:
        return [Finding("violation", "source-read", path.relative_to(root).as_posix(), 1, 1, f"Could not read source: {error}.")]
    results = token_findings(source, root, path)
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as error:
        results.append(Finding("violation", "syntax", path.relative_to(root).as_posix(), error.lineno or 1, error.offset or 1, error.msg))
    else:
        visitor = Visitor(root, path)
        visitor.visit(tree)
        results.extend(visitor.results)
        if ast.get_docstring(tree) is None:
            results.append(Finding("violation", "module-docstring", path.relative_to(root).as_posix(), 1, 1, "Add a module docstring."))
        else:
            doc_findings(results, root, path, tree, "module")
    return results


def main():
    """Emit JSON-lines findings and return nonzero for violations.

    Returns:
        Process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd())
    root = parser.parse_args().root.resolve()
    paths = sorted(path for path in root.rglob("*.py") if not any(part.lower() in EXCLUDED for part in path.relative_to(root).parts))
    findings = [finding for path in paths for finding in audit(path, root)]
    for finding in findings:
        print(json.dumps(dataclasses.asdict(finding), sort_keys=True))
    violations = sum(finding.level == "violation" for finding in findings)
    print(f"Checked {len(paths)} Python files: {violations} violations.", file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
