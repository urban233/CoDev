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
import re
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


def detect_identity(*, target: Path) -> str | None:
    """Best-effort local identity for defaulting --owner/--by. Never raises.

    Prefers the authenticated GitHub login, since that is what CODEOWNERS
    entries and GitHub assignees are keyed by; falls back to the local git
    config so this stays useful without any GitHub setup. Returns None
    rather than a fabricated placeholder when neither resolves.
    """
    gh_executable = _gh_executable()
    if gh_executable is not None:
        try:
            completed = subprocess.run(
                [gh_executable, "api", "user", "--jq", ".login"],
                cwd=target,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            completed = None
        if completed is not None and completed.returncode == 0:
            login = completed.stdout.strip()
            if login:
                return login
    try:
        completed = subprocess.run(
            ["git", "config", "user.name"],
            cwd=target,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode == 0:
        name = completed.stdout.strip()
        if name:
            return name
    return None


def fetch_issue(number: int, *, target: Path) -> dict[str, str]:
    """Read-only lookup of a GitHub issue's title and URL.

    Unlike detect_identity, this raises on failure: it only runs when a
    human explicitly passes --github-issue, so a bad issue number should
    fail loudly rather than silently start a work item with no summary.
    """
    raw = _run_gh(["issue", "view", str(number), "--json", "title,url"], cwd=target)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise GitOpsError(f"unexpected response from gh issue view: {error}") from error
    title = payload.get("title")
    url = payload.get("url")
    if not isinstance(title, str) or not isinstance(url, str):
        raise GitOpsError("gh issue view response missing title or url")
    return {"title": title, "url": url}


def create_issue(
    title: str,
    body: str,
    *,
    target: Path,
    assignees: list[str] | None = None,
) -> str:
    """Create a new GitHub issue. Has no work-item precondition.

    Unlike branch|commit|push|open-pr|mark-ready, this runs *before*
    codev work start exists for the item -- pushing a delivery-plan work
    item to GitHub happens ahead of starting round-state tracking on it, so
    there is nothing yet to call codev work check against.
    """
    args = ["issue", "create", "--title", title, "--body", body]
    for assignee in assignees or []:
        args.extend(["--assignee", assignee])
    return _run_gh(args, cwd=target)


_CODEOWNERS_LOCATIONS = ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS")


def _find_codeowners(target: Path) -> Path | None:
    for relative in _CODEOWNERS_LOCATIONS:
        candidate = target / Path(relative)
        if candidate.is_file():
            return candidate
    return None


def _codeowners_pattern_to_regex(pattern: str) -> re.Pattern[str]:
    anchored = pattern.startswith("/")
    pattern = pattern.removeprefix("/")
    is_dir = pattern.endswith("/")
    pattern = pattern.removesuffix("/")
    segments = [
        ".*" if segment == "**" else re.escape(segment).replace(r"\*", "[^/]*")
        for segment in pattern.split("/")
    ]
    body = "/".join(segments)
    if is_dir:
        body += "(/.*)?"
    prefix = "^" if anchored else "^(.*/)?"
    return re.compile(prefix + body + "$")


def suggest_owners(paths: list[str], *, target: Path) -> list[str]:
    """Best-effort CODEOWNERS-suggested owners for the given paths.

    Mirrors last-match-wins glob resolution, the same semantics GitHub
    itself uses. Never raises and never requires CODEOWNERS to exist: this
    is a suggestion for a human to confirm via --assignee, never applied
    automatically.
    """
    codeowners_path = _find_codeowners(target)
    if codeowners_path is None:
        return []
    try:
        lines = codeowners_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rules: list[tuple[re.Pattern[str], list[str]]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        tokens = stripped.split()
        if len(tokens) < 2:
            continue
        rules.append((_codeowners_pattern_to_regex(tokens[0]), tokens[1:]))
    suggested: dict[str, None] = {}
    for path in paths:
        normalized = path.replace("\\", "/").lstrip("/")
        matched_owners: list[str] | None = None
        for regex, owners in rules:
            if regex.match(normalized):
                matched_owners = owners
        for owner in matched_owners or []:
            suggested[owner] = None
    return list(suggested)


_GITHUB_ISSUE_URL = re.compile(
    r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/(?P<number>\d+)$"
)


def _closes_issue_number(link_ref: str | None, *, target: Path) -> int | None:
    """The issue number to auto-close, only when link_ref is this repo's own.

    Inspects only CoDev's own previously-recorded link_ref field, never a
    foreign document -- never cross-links a different repository's issue.
    """
    if not link_ref:
        return None
    match = _GITHUB_ISSUE_URL.match(link_ref)
    if not match:
        return None
    try:
        name_with_owner = _run_gh(
            ["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            cwd=target,
        )
    except GitOpsError:
        return None
    if name_with_owner != f"{match['owner']}/{match['repo']}":
        return None
    return int(match["number"])


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


def changed_files(work_item_id: str, *, target: Path) -> list[str]:
    """Read-only, best-effort list of paths changed on the work item's branch.

    Returns an empty list rather than raising when the item has no branch
    recorded yet -- this backs status --verbose's informational overlap
    check, not a hard requirement.
    """
    try:
        git_state = _load_git_state(work_item_id, target=target)
    except GitOpsError:
        return []
    try:
        output = _run_git(
            ["diff", "--name-only", git_state["base_snapshot"], git_state["branch"]],
            cwd=target,
        )
    except GitOpsError:
        return []
    return [line for line in output.splitlines() if line]


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


def _existing_pr_url(branch: str, *, target: Path) -> str | None:
    """Read-only: the URL of an already-open PR for this branch, if any."""
    try:
        return _run_gh(
            ["pr", "view", branch, "--json", "url", "-q", ".url"], cwd=target
        )
    except GitOpsError:
        return None


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
    description = work.describe(work_item_id, target=target)
    # ok_ready_for_pr is produced exactly once, at the inner-to-outer
    # transition -- it never recurs. An item can reach the outer phase
    # without ever passing through it (codev work reopen recovering
    # straight into the outer phase, or a direct-review entry), so once
    # there, any non-stop check() result is eligible too: the guard that
    # actually matters is "no pull request already exists" below, checked
    # against GitHub itself rather than inferred from round-state alone.
    eligible = result.ok and (
        result.reason == "ok_ready_for_pr" or description["current_phase"] == "outer"
    )
    if not eligible:
        raise GitOpsError(
            "refusing to open a pull request: codev work check returned "
            f"{result.reason!r} ({result.message}); a pull request may only be "
            "opened at the ok_ready_for_pr checkpoint, or for an item already in "
            "the outer phase with none yet"
        )
    existing = _existing_pr_url(branch, target=target)
    if existing is not None:
        raise GitOpsError(
            f"refusing to open a pull request: {branch!r} already has one open "
            f"at {existing} -- use `codev git mark-ready` instead"
        )
    resolved_base = base or default_branch(target)
    link_ref = description.get("link_ref")
    issue_number = _closes_issue_number(link_ref, target=target)
    final_body = f"{body}\n\nCloses #{issue_number}" if issue_number else body
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
            final_body,
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
