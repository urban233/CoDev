#!/usr/bin/env python3
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
"""Bump the release version in the files owned by the package release process."""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

# Change one of these settings for a no-argument bump, or pass --bump explicitly.
BUMP_MAJOR = False
BUMP_MINOR = False
BUMP_PATCH = True

VERSION_RE = re.compile(r"^version\s*=\s*[\"']([^\"']+)[\"']$", re.MULTILINE)
UNRELEASED_RE = re.compile(r"^## \[Unreleased\]$", re.MULTILINE)
VERSION_FILES = (
    Path("CHANGELOG.md"),
    Path("pyproject.toml"),
    Path("src/codev_workflow/__init__.py"),
    Path("packaging/BUILD.bazel"),
)


def configured_bump() -> str:
    choices = [
        name
        for enabled, name in (
            (BUMP_MAJOR, "major"),
            (BUMP_MINOR, "minor"),
            (BUMP_PATCH, "patch"),
        )
        if enabled
    ]
    if len(choices) != 1:
        raise ValueError("enable exactly one of BUMP_MAJOR, BUMP_MINOR, BUMP_PATCH")
    return choices[0]


def read_current_version(root: Path) -> str:
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = VERSION_RE.search(pyproject)
    if match is None:
        raise ValueError("could not find project.version in pyproject.toml")
    version = match.group(1)
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"unsupported version format: {version}")
    return version


def bumped_version(version: str, bump: str) -> str:
    major, minor, patch = (int(part) for part in version.split("."))
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    if bump == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"unknown bump type: {bump}")


def update_changelog(content: str, new: str, release_date: str) -> str:
    replacement = f"## [{new}] - {release_date}"
    updated, count = UNRELEASED_RE.subn(replacement, content, count=1)
    if count == 0:
        raise ValueError("could not find ## [Unreleased] in CHANGELOG.md")
    return updated


def replace_in_repository(
    root: Path,
    old: str,
    new: str,
    dry_run: bool,
    release_date: str | None = None,
) -> list[Path]:
    changed: list[Path] = []
    for relative_path in VERSION_FILES:
        path = root / relative_path
        if not path.is_file():
            raise ValueError(f"version file does not exist: {relative_path}")
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as error:
            raise ValueError(f"could not read version file: {relative_path}") from error
        if relative_path == Path("CHANGELOG.md"):
            updated = update_changelog(
                content,
                new,
                release_date or date.today().isoformat(),
            )
        else:
            updated = content.replace(old, new)
        if updated == content:
            continue
        changed.append(path)
        if not dry_run:
            path.write_text(updated, encoding="utf-8", newline="")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument("--bump", choices=("major", "minor", "patch"))
    parser.add_argument(
        "--release-date",
        help="release date for the changelog in YYYY-MM-DD format (defaults to today)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    old = read_current_version(root)
    bump = args.bump or configured_bump()
    new = bumped_version(old, bump)
    changed = replace_in_repository(root, old, new, args.dry_run, args.release_date)
    action = "would update" if args.dry_run else "updated"
    print(f"{action} {len(changed)} file(s): {old} -> {new}")
    for path in changed:
        print(f"  {path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
