#!/usr/bin/env python3
"""Verify release metadata and run deterministic release-readiness checks."""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
import tomllib
from pathlib import Path

VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+")


def _release_commands(root: Path) -> list[tuple[str, list[str]]]:
    python = sys.executable
    return [
        (
            "unit tests",
            [python, "-m", "unittest", "discover", "-s", "tests", "-v"],
        ),
        ("compile check", [python, "-m", "compileall", "-q", "src", "tests"]),
        (
            "workflow validation",
            [
                python,
                "src/codev_workflow/bundle/scripts/validate-development-workflow.py",
                "--repo",
                "src/codev_workflow/bundle",
            ],
        ),
        (
            "workflow evaluator self-test",
            [
                python,
                "src/codev_workflow/bundle/scripts/evaluate-development-workflow.py",
                "--repo",
                "src/codev_workflow/bundle",
                "--self-test",
            ],
        ),
        ("Ruff lint", [python, "-m", "ruff", "check", "."]),
        ("Ruff format", [python, "-m", "ruff", "format", "--check", "."]),
        ("type check", [python, "-m", "mypy"]),
        ("package build", [python, "-m", "build"]),
    ]


def _run_check(root: Path, name: str, command: list[str]) -> None:
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise ValueError(f"{name} could not run: {error}") from error
    if completed.returncode == 0:
        return
    output = (completed.stdout + completed.stderr).strip()
    detail = f"\n{output}" if output else ""
    raise ValueError(
        f"{name} failed with exit code {completed.returncode}:"
        f" {' '.join(command)}{detail}"
    )


def run_release_checks(root: Path) -> None:
    """Run the deterministic checks required by the release CI pipeline."""

    for name, command in _release_commands(root):
        _run_check(root, name, command)

    distributions = sorted((root / "dist").glob("*"))
    if not distributions:
        raise ValueError("distribution metadata check could not run: dist is empty")
    _run_check(
        root,
        "distribution metadata check",
        [
            sys.executable,
            "-m",
            "twine",
            "check",
            *[str(path) for path in distributions],
        ],
    )


def read_project_version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as file:
        version = tomllib.load(file)["project"]["version"]
    if not isinstance(version, str) or VERSION_PATTERN.fullmatch(version) is None:
        raise ValueError(f"invalid project version: {version!r}")
    return version


def read_runtime_version(root: Path) -> str:
    path = root / "src" / "codev_workflow" / "__init__.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        if node.targets[0].id != "__version__":
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            version = node.value.value
            if VERSION_PATTERN.fullmatch(version) is None:
                raise ValueError(f"invalid runtime version: {version!r}")
            return version
    raise ValueError("could not find runtime __version__")


def verify(root: Path, tag: str | None = None) -> tuple[str, str]:
    project_version = read_project_version(root)
    runtime_version = read_runtime_version(root)
    if runtime_version != project_version:
        raise ValueError(
            "runtime version "
            f"{runtime_version} does not match project version {project_version}"
        )
    if tag is not None and tag != f"v{project_version}":
        raise ValueError(
            f"tag {tag} does not match project version {project_version} "
            f"(expected v{project_version})"
        )
    return project_version, runtime_version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--tag", help="release tag to validate, for example v0.1.3")
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="validate versions and tag without running release checks",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    print(f"Project version: {read_project_version(root)}")
    print(f"Runtime version: {read_runtime_version(root)}")
    if args.tag:
        print(f"Release tag: {args.tag}")
    try:
        verify(root, args.tag)
    except (OSError, SyntaxError, KeyError, TypeError, ValueError) as error:
        parser.error(str(error))
    print("Release metadata is consistent.")
    if args.metadata_only:
        return 0
    try:
        run_release_checks(root)
    except ValueError as error:
        parser.error(str(error))
    print("Release readiness checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
