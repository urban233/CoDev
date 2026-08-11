"""Guarded git/GitHub mutation surface for one CoDev work item.

Agents may not run raw `git commit`, `git push`, or `gh pr create` -- those
stay denied in every platform adapter's permission block. This module is the
only path to mutating the repository or GitHub for a work item, and it
mechanically enforces what ADR-0002 and ADR-0003 require: operate only on
the branch created for this work item, never the repository's default
branch, never a force-push (not exposed as an option at all), and
independently re-verify `codev work check` before opening or readying a pull
request rather than trusting the caller already did.

See docs/adr/0002-inner-loop-self-healing-and-pr-open.md and
docs/adr/0003-outer-loop-triage-and-pr-landing.md.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

from codev_workflow import work

GIT_STATE_FILENAME = "git-state.json"


class GitOpsError(Exception):
    """Raised when a guarded git/GitHub operation cannot proceed safely."""


def branch_name_for(work_item_id: str) -> str:
    return f"codev/{work_item_id}"


def _work_item_dir(target: Path, work_item_id: str) -> Path:
    work._validate_id(work_item_id)
    return target / Path(work.WORK_DIR_RELATIVE.as_posix()) / work_item_id


def _git_state_path(target: Path, work_item_id: str) -> Path:
    return _work_item_dir(target, work_item_id) / GIT_STATE_FILENAME


def _gh_executable() -> str | None:
    """Resolve gh even when a desktop agent omits machine PATH entries."""
    configured = os.environ.get("CODEV_GH_PATH")
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which("gh")
    if found:
        return found
    if os.name == "nt":
        for candidate in (
            Path(os.environ.get("PROGRAMFILES", "C:\\Program Files"))
            / "GitHub CLI"
            / "gh.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"))
            / "GitHub CLI"
            / "gh.exe",
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "Programs"
            / "GitHub CLI"
            / "gh.exe",
        ):
            if candidate.is_file():
                return str(candidate)
    return None


def _run_git(args: list[str], *, cwd: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GitOpsError(f"git {' '.join(args)} failed: {error}") from error
    if completed.returncode != 0:
        detail = (
            completed.stderr.strip() or completed.stdout.strip() or "unknown git error"
        )
        raise GitOpsError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout.strip()


def _run_gh(args: list[str], *, cwd: Path) -> str:
    gh_executable = _gh_executable()
    if gh_executable is None:
        raise GitOpsError("gh CLI was not found; install it or set CODEV_GH_PATH")
    try:
        completed = subprocess.run(
            [gh_executable, *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GitOpsError(f"gh {' '.join(args)} failed: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "unknown gh CLI error"
        raise GitOpsError(f"gh {' '.join(args)} failed: {detail}")
    return completed.stdout.strip()


def current_branch(target: Path) -> str:
    return _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=target)


def current_head(target: Path) -> str:
    return _run_git(["rev-parse", "HEAD"], cwd=target)


def default_branch(target: Path) -> str:
    try:
        ref = _run_git(
            ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=target
        )
        return ref.removeprefix("origin/")
    except GitOpsError:
        pass
    return _run_gh(
        ["repo", "view", "--json", "defaultBranchRef", "-q", ".defaultBranchRef.name"],
        cwd=target,
    )


def create_branch(work_item_id: str, base_snapshot: str, *, target: Path) -> str:
    state_path = _git_state_path(target, work_item_id)
    if state_path.exists():
        raise GitOpsError(f"work item {work_item_id!r} already has a branch recorded")
    branch = branch_name_for(work_item_id)
    _run_git(["checkout", "-b", branch, base_snapshot], cwd=target)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"branch": branch, "base_snapshot": base_snapshot}
    state_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return branch


def _load_git_state(work_item_id: str, *, target: Path) -> dict[str, Any]:
    state_path = _git_state_path(target, work_item_id)
    if not state_path.exists():
        raise GitOpsError(
            f"work item {work_item_id!r} has no branch yet; call create_branch first"
        )
    return cast("dict[str, Any]", json.loads(state_path.read_text(encoding="utf-8")))


def own_branch(work_item_id: str, *, target: Path) -> str:
    return cast(str, _load_git_state(work_item_id, target=target)["branch"])


def _ensure_on_own_branch(work_item_id: str, *, target: Path) -> str:
    branch = own_branch(work_item_id, target=target)
    actual = current_branch(target)
    if actual != branch:
        raise GitOpsError(
            f"refusing to act: checked out branch is {actual!r}, expected the work "
            f"item's own branch {branch!r}"
        )
    return branch


def commit(work_item_id: str, message: str, *, target: Path) -> str:
    if not message.strip():
        raise GitOpsError("commit message must not be empty")
    _ensure_on_own_branch(work_item_id, target=target)
    _run_git(["add", "-A"], cwd=target)
    _run_git(["commit", "-m", message], cwd=target)
    return current_head(target)


def push(work_item_id: str, *, target: Path) -> None:
    branch = _ensure_on_own_branch(work_item_id, target=target)
    default = default_branch(target)
    if branch == default:
        raise GitOpsError(
            f"refusing to push: branch {branch!r} resolves to the repository's "
            "default branch"
        )
    _run_git(["push", "-u", "origin", branch], cwd=target)


def open_pr(
    work_item_id: str,
    title: str,
    body: str,
    *,
    target: Path,
    base: str | None = None,
) -> str:
    branch = _ensure_on_own_branch(work_item_id, target=target)
    head = current_head(target)
    result = work.check(work_item_id, head, target=target)
    if result.reason != "ok_ready_for_pr":
        raise GitOpsError(
            "refusing to open a pull request: codev work check returned "
            f"{result.reason!r}, not ok_ready_for_pr ({result.message})"
        )
    resolved_base = base or default_branch(target)
    return _run_gh(
        [
            "pr",
            "create",
            "--draft",
            "--base",
            resolved_base,
            "--head",
            branch,
            "--title",
            title,
            "--body",
            body,
        ],
        cwd=target,
    )


def mark_ready(work_item_id: str, *, target: Path) -> None:
    branch = _ensure_on_own_branch(work_item_id, target=target)
    head = current_head(target)
    result = work.check(work_item_id, head, target=target)
    if result.reason != "ok_approve":
        raise GitOpsError(
            "refusing to mark the pull request ready: codev work check returned "
            f"{result.reason!r}, not ok_approve ({result.message})"
        )
    body = work.log_text(work_item_id, target=target)
    _run_gh(["pr", "edit", branch, "--body", body], cwd=target)
    _run_gh(["pr", "ready", branch], cwd=target)
