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
"""Fail on a relative Markdown link with no matching file.

Written after finding the actual failure mode this guards against: bundled onboarding
docs linked to a "Workflow Cookbook" and three "Handbooks" that existed only on a GitHub
Wiki -- a separate git remote never cloned with the repository -- so every one of those
links 404'd for anyone who actually clicked them. See
docs/adr/0031-drop-codex-narrow-junie-and-antigravity-to-an-edit-assistant.md's sibling
documentation-overhaul work for the full story.

A bundled document (anything under src/codev_workflow/bundle/) travels alone into a
target repository -- a relative link that resolves outside the bundle is exactly as
broken there as one that resolves nowhere at all, so both are checked for bundled docs.
A non-bundled document (README.md, docs/*.md) may freely link anywhere else in this
repository; only a genuinely missing file is an error there.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_BUNDLE_RELATIVE = Path("src/codev_workflow/bundle")


def _resolve_target(markdown_file: Path, target: str) -> Path | None:
    """The filesystem path a relative Markdown link target points at.

    Returns None for anything this checker doesn't evaluate: an absolute URL, a
    mailto link, or a same-page anchor (`#section`) with no path component.
    """
    if target.startswith(("http://", "https://", "mailto:")):
        return None
    path_part = target.split("#", 1)[0]
    if not path_part:
        return None
    return (markdown_file.parent / path_part).resolve()


def find_broken_links_in_file(
    markdown_file: Path, *, containment_root: Path | None = None
) -> list[str]:
    """Relative Markdown links in one file that don't resolve to a real file.

    When `containment_root` is given, a link that resolves to a real file *outside*
    it is reported too -- the bundled-doc case, where "exists somewhere in this
    repository" isn't good enough because only the bundle itself ships.
    """
    problems: list[str] = []
    contained = containment_root.resolve() if containment_root else None
    text = markdown_file.read_text(encoding="utf-8")
    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in _LINK_PATTERN.finditer(line):
            target = _resolve_target(markdown_file, match.group(1))
            if target is None:
                continue
            location = f"{markdown_file}:{line_number}"
            if not target.exists():
                problems.append(
                    f"{location}: link target does not exist: {match.group(1)!r}"
                )
            elif (
                contained is not None
                and target != contained
                and contained not in target.parents
            ):
                problems.append(
                    f"{location}: link target exists but is outside the bundle "
                    f"it would ship with: {match.group(1)!r}"
                )
    return problems


def find_broken_links(
    scan_root: Path, *, containment_root: Path | None = None
) -> list[str]:
    """`find_broken_links_in_file`, applied to every `.md` file under `scan_root`."""
    problems: list[str] = []
    for markdown_file in sorted(scan_root.rglob("*.md")):
        problems.extend(
            find_broken_links_in_file(markdown_file, containment_root=containment_root)
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path("."), help="repository root to check"
    )
    args = parser.parse_args(argv)
    repo = args.repo.resolve()

    bundle_root = repo / _BUNDLE_RELATIVE
    problems = find_broken_links(bundle_root, containment_root=bundle_root)
    problems += find_broken_links(repo / "docs", containment_root=None)
    problems += [
        problem
        for markdown_file in sorted(repo.glob("*.md"))
        for problem in find_broken_links_in_file(markdown_file)
    ]
    for line in problems:
        print(line, file=sys.stderr)
    if problems:
        print(f"{len(problems)} broken documentation link(s) found.", file=sys.stderr)
        return 1
    print("No broken documentation links found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
