"""Shared verifier building blocks for evaluation tasks.

Every hand-written verifier script this project has ever shipped
(`check_review.py`, `check_test_double.py`, `check_audit_plan.py`, ...)
independently reimplements the same three things: load and validate a
structured JSON output file, check whether some finding in it matches an
expected location/keyword shape, and check whether the actor touched only
the files it was allowed to. This module is that shared code, in one place,
importable both by a custom `verifier.json` script (which runs under the
same Python interpreter as CoDev itself -- see `_isolated_env`'s PATH
handling in `codev_workflow.eval`) and by this module's own declarative
`checks.json` runner.

A task declares exactly one of `verifier.json` (a custom script) or
`checks.json` (a list of checks expressed as data, run by
`run_declarative_checks`) -- never both. See
docs/features/skill-eval-ergonomics/design.md for the full contract.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any


def load_structured_output(path: str | Path) -> dict[str, Any]:
    """Load a JSON file the actor was asked to write.

    Raises FileNotFoundError/json.JSONDecodeError with the *original*
    exception type -- callers that want the "print to stderr and exit 1"
    behavior common to every verifier main() should use `require` around
    this, not catch these directly:

        try:
            data = load_structured_output("audit-plan.json")
        except (OSError, json.JSONDecodeError) as error:
            require(False, f"cannot read audit-plan.json: {error}")
    """
    with open(path, encoding="utf-8") as handle:
        data: dict[str, Any] = json.load(handle)
        return data


def finding_matches(
    findings: Iterable[Any],
    *,
    location_contains: str,
    keywords: Sequence[str],
    fields: Sequence[str] = ("location", "summary", "category"),
) -> bool:
    """True if some entry in `findings` combines `fields` into text containing
    both `location_contains` and at least one of `keywords` (case-insensitive).

    This is the "does this finding mention the right thing" check every
    existing verifier reimplemented by hand with its own haystack/keyword
    logic; this is that logic, written once.
    """
    location_contains = location_contains.lower()
    lowered_keywords = [keyword.lower() for keyword in keywords]
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        haystack = " ".join(str(finding.get(field, "")) for field in fields).lower()
        if location_contains in haystack and any(
            keyword in haystack for keyword in lowered_keywords
        ):
            return True
    return False


def changed_paths_since_seed(*, ignore: Sequence[str] = ()) -> list[str]:
    """Every path that differs from the seed's root commit, or is untracked,
    excluding `ignore` -- the file-purity check every existing verifier
    either reimplemented differently or skipped entirely. Run from the
    worktree's own directory (the verifier's cwd already is that directory).

    Uses the working tree, not just the index, so this is correct whether
    the actor committed its changes or left them uncommitted -- and it
    finds the seed's root commit itself rather than requiring the caller to
    know its hash, so it is correct regardless of whether the actor made
    additional commits of its own.
    """
    root = subprocess.run(
        ["git", "rev-list", "--max-parents=0", "HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    seed_commits = [line for line in root.stdout.splitlines() if line.strip()]
    if root.returncode != 0 or not seed_commits:
        return ["<could not resolve the seed commit>"]
    seed = seed_commits[0]

    diff = subprocess.run(
        ["git", "diff", "--name-only", seed, "--"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    tracked_changed = {line for line in diff.stdout.splitlines() if line.strip()}

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    untracked = {
        line[3:].strip()
        for line in status.stdout.splitlines()
        if line.startswith("??")
    }

    return sorted((tracked_changed | untracked) - set(ignore))


def require(condition: bool, message: str) -> None:
    """Print `message` to stderr and exit 1 if `condition` is False.

    The small assert-and-exit helper every verifier main() needs; use it in
    place of a bespoke `if not X: print(...); return 1` per check.
    """
    if not condition:
        print(message, file=sys.stderr)
        sys.exit(1)


class ChecksError(RuntimeError):
    """A checks.json entry is malformed, or a check itself found a problem."""


def _dot_path_get(data: Any, dotted: str) -> Any:
    current = data
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ChecksError(f"field {dotted!r} not found")
        current = current[part]
    return current


def _run_json_field_equals(check: dict[str, Any]) -> None:
    data = load_structured_output(check["file"])
    actual = _dot_path_get(data, check["field"])
    expected = check["equals"]
    if actual != expected:
        raise ChecksError(
            f"{check['file']}: expected {check['field']} == {expected!r}, "
            f"got {actual!r}"
        )


def _run_finding_matches(check: dict[str, Any]) -> None:
    data = load_structured_output(check["file"])
    findings = _dot_path_get(data, check["field"])
    if not isinstance(findings, list):
        raise ChecksError(f"{check['file']}: {check['field']} is not a list")
    if not finding_matches(
        findings,
        location_contains=check["location_contains"],
        keywords=check["any_keyword"],
    ):
        raise ChecksError(
            f"{check['file']}: no entry in {check['field']} matches "
            f"location_contains={check['location_contains']!r} with any of "
            f"{check['any_keyword']!r}"
        )


def _run_files_unchanged_except(check: dict[str, Any]) -> None:
    unexpected = changed_paths_since_seed(ignore=check.get("except", []))
    if unexpected:
        raise ChecksError(
            "unexpected change(s) beyond the allowed exceptions: "
            + ", ".join(unexpected)
        )


def _run_command_succeeds(check: dict[str, Any]) -> None:
    result = subprocess.run(
        check["argv"],
        capture_output=True,
        text=True,
        timeout=check.get("timeout", 60),
    )
    if result.returncode != 0:
        raise ChecksError(
            f"command {check['argv']} exited {result.returncode}: "
            f"{result.stderr or result.stdout}"
        )


_CHECK_RUNNERS = {
    "json_field_equals": _run_json_field_equals,
    "finding_matches": _run_finding_matches,
    "files_unchanged_except": _run_files_unchanged_except,
    "command_succeeds": _run_command_succeeds,
}


def run_declarative_checks(checks: list[dict[str, Any]]) -> tuple[bool, str]:
    """Run every check in order; stop at the first failure.

    Returns (True, "") on success, or (False, message) naming which check
    failed and why -- the same shape a hand-written verifier's main() would
    print to stderr before exiting 1.
    """
    for index, check in enumerate(checks):
        check_type = check.get("type")
        runner = _CHECK_RUNNERS.get(check_type)  # type: ignore[arg-type]
        if runner is None:
            return False, f"checks[{index}]: unknown check type {check_type!r}"
        try:
            runner(check)
        except ChecksError as error:
            return False, f"checks[{index}] ({check_type}): {error}"
        except (OSError, json.JSONDecodeError, KeyError) as error:
            return False, f"checks[{index}] ({check_type}): {error}"
    return True, ""
