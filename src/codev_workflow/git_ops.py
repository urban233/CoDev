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
"""Guarded git/GitHub mutation surface for one CoDev task.

Agents may not run raw `git commit`, `git push`, or `gh pr create` -- those
stay denied in every platform adapter's permission block. This module is the
only path to mutating the repository or GitHub for a task, and it
mechanically enforces what ADR-0002 and ADR-0003 require: operate only on
the branch created for this task, never the repository's default
branch, never a force-push (not exposed as an option at all), and
independently re-verify `codev task check` before opening or readying a pull
request rather than trusting the caller already did.

See docs/adr/0002-inner-loop-self-healing-and-pr-open.md and
docs/adr/0003-outer-loop-triage-and-pr-landing.md.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import warnings
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, cast

from codev_workflow import config, task
from codev_workflow.installer import CoDevError, _read_lock

GIT_STATE_FILENAME = "git-state.json"
_TASK_BRANCH_PREFIX = "codev/"  # must match branch_name_for()
PR_TEMPLATE_PATH = Path(".github/pull_request_template.md")
_PR_TEMPLATE_MARKERS = (
    "summary",
    "validation",
    "changed-files",
    "review",
    "tracking",
    "closes",
)


class GitOpsError(Exception):
    """Raised when a guarded git/GitHub operation cannot proceed safely."""


def branch_name_for(task_id: str) -> str:
    return f"{_TASK_BRANCH_PREFIX}{task_id}"


def _task_dir(target: Path, task_id: str) -> Path:
    task._validate_id(task_id)
    return target / Path(task.TASK_DIR_RELATIVE.as_posix()) / task_id


def _git_state_path(target: Path, task_id: str) -> Path:
    return _task_dir(target, task_id) / GIT_STATE_FILENAME


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


def has_github_remote(*, target: Path) -> bool:
    """Best-effort: does this repository resolve to a real GitHub remote?

    Never raises -- backs `codev task start`'s issue-linkage gate (ADR-0020),
    which must not turn into a hard GitHub dependency for a repository that
    has none, the same restraint `detect_identity` already applies.
    """
    try:
        _run_gh(["repo", "view", "--json", "url"], cwd=target)
    except GitOpsError:
        return False
    return True


def fetch_issue(number: int, *, target: Path) -> dict[str, str]:
    """Read-only lookup of a GitHub issue's title and URL.

    Unlike detect_identity, this raises on failure: it only runs when a
    human explicitly passes --github-issue, so a bad issue number should
    fail loudly rather than silently start a task with no summary.
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


_ISSUE_VIEW_FIELDS = "number,title,url,state,author,createdAt,body,comments"


def view_issue(number: int, *, target: Path) -> dict[str, Any]:
    """Read-only lookup of a GitHub issue, its body, and all its comments.

    Unlike fetch_issue, this is exposed directly as `codev git issue-view`
    for agents to consume issue discussion (requirements, feedback in
    comments) as JSON, not just the title/url summary task start needs.
    """
    raw = _run_gh(
        ["issue", "view", str(number), "--json", _ISSUE_VIEW_FIELDS], cwd=target
    )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise GitOpsError(f"unexpected response from gh issue view: {error}") from error
    return cast(dict[str, Any], payload)


def create_issue(
    title: str,
    body: str,
    *,
    target: Path,
    assignees: list[str] | None = None,
) -> str:
    """Create a new GitHub issue. Has no task precondition.

    Unlike branch|commit|push|open-pr|mark-ready, this runs *before*
    codev task start exists for the item -- pushing a delivery-plan task
    to GitHub happens ahead of starting round-state tracking on it, so
    there is nothing yet to call codev task check against.
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


def _has_recorded_child(task_id: str, *, target: Path) -> bool:
    """True when another task's recorded git-state.json names this task as
    its `parent_task` -- the "last slice in a stack" is the one with no
    such child (ADR-0034). Best-effort: an unreadable or malformed sibling
    state file is skipped rather than raised, since this backs PR-body
    text, not a hard requirement."""
    task_root = target / Path(task.TASK_DIR_RELATIVE.as_posix())
    if not task_root.is_dir():
        return False
    for state_path in task_root.glob(f"*/{GIT_STATE_FILENAME}"):
        if state_path.parent.name == task_id:
            continue
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(state, dict) and state.get("parent_task") == task_id:
            return True
    return False


def _more_slices_remain(task_id: str, *, target: Path) -> bool:
    """True when this task holds a later slice than the one currently being
    worked (ADR-0035). Read from the task's own ordered slice list, which is
    the collection that owns the issue -- not inferred from sibling state.

    Best-effort for the same reason `_has_recorded_child` is: this backs
    pull-request body text, so unreadable round state means "cannot tell",
    not an exception."""
    try:
        return not task.is_final_slice(
            task_id, task.current_slice(task_id, target=target), target=target
        )
    except (task.TaskError, KeyError):
        return False


def _closing_line(issue_number: int, *, task_id: str, target: Path) -> str:
    """`Part of #N` while anything in this task still has to land, `Closes
    #N` on the piece that finishes it.

    Two things can mean "more remains", and both are checked. The task's own
    slice list is authoritative (ADR-0035): the issue belongs to the task,
    so only its final slice closes it. A recorded child task is the older
    sibling-stack form (ADR-0034), still supported for stacks created that
    way."""
    if _more_slices_remain(task_id, target=target) or _has_recorded_child(
        task_id, target=target
    ):
        return f"Part of #{issue_number}"
    return f"Closes #{issue_number}"


def _with_issue_link_line(
    body: str, link_ref: str | None, *, task_id: str, target: Path
) -> str:
    """Append a `Closes #N`/`Part of #N` line when link_ref names this
    repo's own GitHub issue.

    Shared by every code path that writes a pull request body -- open_pr's
    initial body and mark_ready's regenerated one alike -- so the link,
    once earned, cannot be silently dropped by whichever call happens to
    run last.
    """
    issue_number = _closes_issue_number(link_ref, target=target)
    if not issue_number:
        return body
    return f"{body}\n\n{_closing_line(issue_number, task_id=task_id, target=target)}"


def _render_pr_template(task_id: str, *, target: Path) -> str:
    """Render task evidence into the repository's managed PR template.

    Older or project-owned templates remain untouched: their absence or an
    incompatible shape falls back to the established standalone description.
    """
    description = task.describe(task_id, target=target)
    generated = task.pr_description(task_id, target=target)
    template_path = target / PR_TEMPLATE_PATH
    if not template_path.is_file():
        warnings.warn(
            f"{PR_TEMPLATE_PATH} is absent; using CoDev's generated PR body instead",
            stacklevel=2,
        )
        return _with_issue_link_line(
            generated, description.get("link_ref"), task_id=task_id, target=target
        )

    template = template_path.read_text(encoding="utf-8")
    markers = {marker: f"<!-- codev:{marker} -->" for marker in _PR_TEMPLATE_MARKERS}
    missing = [marker for marker, token in markers.items() if token not in template]
    if missing:
        warnings.warn(
            f"{PR_TEMPLATE_PATH} is not CoDev-compatible (missing "
            f"{', '.join(missing)}); using CoDev's generated PR body instead",
            stacklevel=2,
        )
        return _with_issue_link_line(
            generated, description.get("link_ref"), task_id=task_id, target=target
        )

    generated_without_trailing_newline = generated.rstrip()
    validation = generated_without_trailing_newline.split("\n\n## Validation\n", 1)[-1]
    validation = validation.split("\n\nTask: ", 1)[0]
    summary = generated_without_trailing_newline.split("\n\n## Validation\n", 1)[0]
    issue_number = _closes_issue_number(description.get("link_ref"), target=target)
    changed = changed_files(task_id, target=target)
    values = {
        "summary": summary,
        "validation": validation,
        "changed-files": ", ".join(changed) if changed else "none recorded",
        "review": (
            f"Latest task review: {description['latest_decision'] or 'in progress'}."
        ),
        "tracking": generated_without_trailing_newline.rsplit("\n\n", 1)[-1],
        "closes": (
            _closing_line(issue_number, task_id=task_id, target=target)
            if issue_number
            else ""
        ),
    }
    for marker, token in markers.items():
        template = template.replace(token, values[marker])
    return template.rstrip()


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


def _resolve_pr_base(base: str | None, *, target: Path) -> str:
    """`--base` if given, else `git.pr_base`, else the repository's default
    branch -- the resolution order create_branch and open_pr share."""
    if base is not None:
        return base
    configured = config.resolve("git.pr_base", target=target)
    if configured is not None:
        return configured.value
    return default_branch(target)


def _warn_if_base_behind_remote(base: str, *, target: Path) -> None:
    """Warn, never raise, when a resolved base branch has a remote-tracking
    counterpart ahead of it -- a stale local checkout otherwise silently
    becomes the wrong starting point for a new task branch. A no-op when
    `base` is not a local branch with an `origin/<base>` counterpart (an
    explicit snapshot/tag/sha, or no such remote ref)."""
    try:
        _run_git(["rev-parse", "--verify", f"refs/remotes/origin/{base}"], cwd=target)
    except GitOpsError:
        return
    try:
        behind = int(
            _run_git(["rev-list", "--count", f"{base}..origin/{base}"], cwd=target)
        )
    except GitOpsError:
        return
    if behind > 0:
        warnings.warn(
            f"local {base!r} is {behind} commit(s) behind origin/{base!r}; "
            "consider fetching before branching from it",
            stacklevel=2,
        )


def _other_recorded_task_on_head(*, target: Path) -> str | None:
    """The other task id whose own recorded branch HEAD currently sits on,
    or None when HEAD is not on any codev-managed task branch."""
    branch = current_branch(target)
    if not branch.startswith(_TASK_BRANCH_PREFIX):
        return None
    other_task_id = branch[len(_TASK_BRANCH_PREFIX) :]
    if not other_task_id:
        return None
    try:
        _load_git_state(other_task_id, target=target)
    except GitOpsError:
        return None
    return other_task_id


def _resolved_workflow(*, target: Path) -> str:
    resolved = config.resolve("git.workflow", target=target)
    return resolved.value if resolved is not None else config.DEFAULTS["git.workflow"]


def create_branch(
    task_id: str,
    base_snapshot: str | None = None,
    *,
    target: Path,
    allow_dirty: bool = False,
    stack_on: str | None = None,
) -> str:
    state_path = _git_state_path(target, task_id)
    if state_path.exists():
        raise GitOpsError(f"task {task_id!r} already has a branch recorded")

    if not allow_dirty:
        dirty = _dirty_product_paths(target)
        if dirty:
            raise GitOpsError(
                "refusing to create a branch: the worktree has uncommitted "
                f"changes ({', '.join(sorted(dirty)[:5])}"
                f"{', ...' if len(dirty) > 5 else ''}) that would ride onto "
                "the new branch -- commit or stash them first, or pass "
                "--allow-dirty if that is intentional"
            )

    if stack_on is not None:
        # ADR-0034: stacking is only supported under trunk-based
        # development, and every stacking affordance disables itself
        # cleanly under feature-branch rather than firing anyway.
        workflow = _resolved_workflow(target=target)
        if workflow != "trunk":
            raise GitOpsError(
                f"refusing --stack-on: git.workflow resolves to {workflow!r}, "
                "not 'trunk' -- stacking is only supported under trunk-based "
                "development (ADR-0034)"
            )
        try:
            parent_state = _load_git_state(stack_on, target=target)
        except GitOpsError as error:
            raise GitOpsError(
                f"refusing --stack-on {stack_on!r}: it has no branch yet -- "
                f"create it first with `codev git branch --id {stack_on}`"
            ) from error
        resolved_base = cast(str, parent_state["branch"])
    else:
        # The foreign-branch guard below exists to catch *blind* branching
        # while HEAD sits on unrelated, unmerged work. --stack-on replaces
        # that concern with an explicit, named, already-verified parent --
        # checkout -b starts from that parent's pinned commit regardless of
        # HEAD's current branch, so there is nothing left for this guard to
        # protect against once stacking is requested on purpose (ADR-0034).
        other_task_id = _other_recorded_task_on_head(target=target)
        if other_task_id is not None and other_task_id != task_id:
            other_branch = branch_name_for(other_task_id)
            other_state = _load_git_state(other_task_id, target=target)
            ahead = int(
                _run_git(
                    ["rev-list", "--count", f"{other_state['base_snapshot']}..HEAD"],
                    cwd=target,
                )
            )
            if ahead > 0:
                raise GitOpsError(
                    f"refusing to create a branch: HEAD is on {other_branch!r} "
                    f"({other_task_id!r}'s own branch) with {ahead} commit(s) "
                    "not yet in its base -- check out the intended base branch "
                    f"first, or continue work on {other_task_id!r} itself "
                    "instead of branching a new task from underneath it"
                )
        resolved_base = _resolve_pr_base(base_snapshot, target=target)

    _warn_if_base_behind_remote(resolved_base, target=target)
    # Pin to the exact commit now, not the ref name: changed_files and
    # task_size diff against this recorded value later, and a floating
    # branch name (the parent's branch, or the default_branch/git.pr_base
    # fallback) would silently pull in every commit it gains after this
    # branch is created.
    pinned_base = _run_git(["rev-parse", resolved_base], cwd=target)

    branch = branch_name_for(task_id)
    _run_git(["checkout", "-b", branch, pinned_base], cwd=target)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"branch": branch, "base_snapshot": pinned_base}
    if stack_on is not None:
        payload["parent_task"] = stack_on
    state_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return branch


def _load_git_state(task_id: str, *, target: Path) -> dict[str, Any]:
    state_path = _git_state_path(target, task_id)
    if not state_path.exists():
        raise GitOpsError(
            f"task {task_id!r} has no branch yet; call create_branch first"
        )
    return cast("dict[str, Any]", json.loads(state_path.read_text(encoding="utf-8")))


def changed_files(task_id: str, *, target: Path) -> list[str]:
    """Read-only, best-effort list of paths changed on the task's branch.

    Returns an empty list rather than raising when the item has no branch
    recorded yet -- this backs status --verbose's informational overlap
    check, not a hard requirement.
    """
    try:
        git_state = _load_git_state(task_id, target=target)
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


@dataclass(frozen=True)
class TaskSize:
    """Non-generated diff size for one task, plus the budget it is measured
    against -- see docs/features/small-prs/design.md."""

    lines_changed: int
    files_changed: int
    max_lines: int
    max_files: int

    @property
    def over_budget(self) -> bool:
        return (
            self.lines_changed > self.max_lines or self.files_changed > self.max_files
        )


def _resolved_budget(key: str, *, target: Path) -> int:
    default = int(config.DEFAULTS[key])
    resolved = config.resolve(key, target=target)
    if resolved is None:
        return default
    try:
        return int(resolved.value)
    except ValueError:
        warnings.warn(
            f"{key} = {resolved.value!r} is not an integer; using default {default}",
            stacklevel=2,
        )
        return default


def _generated_paths(paths: list[str], *, target: Path) -> set[str]:
    """Paths `.gitattributes` marks `linguist-generated`, per design.md's
    resolved decision: this is the only generated-file signal CoDev uses --
    no CoDev-owned fallback exclude list. Returns an empty set, never
    raises, when a repository has no matching `.gitattributes` entry."""
    if not paths:
        return set()
    try:
        output = _run_git(
            ["check-attr", "linguist-generated", "--", *paths], cwd=target
        )
    except GitOpsError:
        return set()
    generated: set[str] = set()
    for line in output.splitlines():
        path, _, value = line.rpartition(": linguist-generated: ")
        if path and value in ("set", "true"):
            generated.add(path)
    return generated


def slice_size(task_id: str, *, target: Path) -> TaskSize:
    """The size of the slice currently being worked: the diff from the base
    the task is presently on, which `task.advance_slice` moves to each
    finished slice's head.

    This is the measurement the budget applies to. A reviewer reads one pull
    request, and ADR-0035 makes one slice one pull request, so the slice --
    not the task -- is the thing that has to stay small.

    Falls back to the whole task when round state is unreadable, which is
    also the honest answer for a task that never advanced past its first
    slice: the two measurements are identical there.
    """
    try:
        base = task.describe_base_snapshot(task_id, target=target)
    except (task.TaskError, KeyError):
        return task_size(task_id, target=target)
    return _measure(task_id, base, target=target)


def task_size(task_id: str, *, target: Path) -> TaskSize:
    """The whole task's size: the diff from the commit its branch was cut
    from, across every slice it has landed so far.

    Reported, never capped -- a task deliberately sliced into four is
    supposed to total more than one slice's budget. `slice_size` is what the
    budget applies to.

    Returns zero counts rather than raising when the task has no branch
    recorded yet, matching changed_files's established posture -- this
    backs `codev task size` and status --verbose, not a hard requirement.
    """
    try:
        git_state = _load_git_state(task_id, target=target)
    except GitOpsError:
        max_lines = _resolved_budget("review.max_lines", target=target)
        max_files = _resolved_budget("review.max_files", target=target)
        return TaskSize(0, 0, max_lines, max_files)
    return _measure(task_id, git_state["base_snapshot"], target=target)


def _measure(task_id: str, base: str, *, target: Path) -> TaskSize:
    """Non-generated changed lines and files between `base` and the task's
    own branch, plus the resolved budget."""
    max_lines = _resolved_budget("review.max_lines", target=target)
    max_files = _resolved_budget("review.max_files", target=target)
    try:
        git_state = _load_git_state(task_id, target=target)
    except GitOpsError:
        return TaskSize(0, 0, max_lines, max_files)
    try:
        output = _run_git(
            ["diff", "--numstat", base, git_state["branch"]],
            cwd=target,
        )
    except GitOpsError:
        return TaskSize(0, 0, max_lines, max_files)

    # A task's own bookkeeping under .codev/task/<task_id>/ (git-state.json,
    # round-state.json) rides on the same branch and would otherwise count
    # against the very budget this exists to enforce -- exclude it before
    # the linguist-generated check, not as an instance of it.
    own_state_prefix = _task_dir(target, task_id).relative_to(target).as_posix() + "/"

    rows = []
    for line in output.splitlines():
        if not line:
            continue
        parts = line.split("\t", 2)
        if len(parts) == 3 and not parts[2].startswith(own_state_prefix):
            rows.append(parts)
    generated = _generated_paths([path for _, _, path in rows], target=target)

    lines_changed = 0
    files_changed = 0
    for added, deleted, path in rows:
        if path in generated:
            continue
        files_changed += 1
        if added != "-":
            lines_changed += int(added)
        if deleted != "-":
            lines_changed += int(deleted)
    return TaskSize(lines_changed, files_changed, max_lines, max_files)


def own_branch(task_id: str, *, target: Path) -> str:
    return cast(str, _load_git_state(task_id, target=target)["branch"])


def parent_task_id(task_id: str, *, target: Path) -> str | None:
    """The recorded parent task id, or None when the task has no branch
    recorded yet or was not created with --stack-on."""
    try:
        state = _load_git_state(task_id, target=target)
    except GitOpsError:
        return None
    parent = state.get("parent_task")
    return cast(str, parent) if parent else None


def stack_depth(task_id: str, *, target: Path) -> int:
    """1 for a task with no recorded parent; 1 + the parent's own depth
    otherwise. Never raises: an unresolvable link in the chain -- a
    missing parent state file, or a cycle -- stops the walk and returns
    the depth reached so far, since this backs status reporting, not a
    hard requirement."""
    depth = 1
    seen = {task_id}
    current = task_id
    while True:
        parent = parent_task_id(current, target=target)
        if not parent or parent in seen:
            return depth
        seen.add(parent)
        depth += 1
        current = parent


def _ensure_on_own_branch(task_id: str, *, target: Path) -> str:
    branch = own_branch(task_id, target=target)
    actual = current_branch(target)
    if actual != branch:
        raise GitOpsError(
            f"refusing to act: checked out branch is {actual!r}, expected the "
            f"task's own branch {branch!r}"
        )
    return branch


def _managed_paths(target: Path) -> set[str] | None:
    """CoDev-managed target-relative paths, from .codev/lock.json.

    Returns None (never raises) when the lock file is missing or unreadable
    -- the mixed-path commit guard below is a defensive nudge, not a hard
    requirement, and must not block a commit just because a repo has no
    CoDev install to classify paths against.
    """
    try:
        lock = _read_lock(target)
    except CoDevError:
        return None
    return set(lock["files"])


def _dirty_paths(target: Path) -> list[str]:
    # -uall: list files inside an untracked directory individually rather
    # than collapsing the whole directory into one entry -- required for
    # per-file classification against the managed-paths set below.
    status = _run_git(["status", "--porcelain", "-uall"], cwd=target)
    paths: list[str] = []
    for line in status.splitlines():
        if not line:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path)
    return paths


def _dirty_product_paths(target: Path) -> list[str]:
    """_dirty_paths, excluding a task's own not-yet-committed
    .codev/task/<id>/ bookkeeping. create_branch writes git-state.json to
    disk before any commit exists to carry it, so that file alone must
    never register as a reason to refuse creating a further branch."""
    task_dir_prefix = task.TASK_DIR_RELATIVE.as_posix() + "/"
    return [
        path for path in _dirty_paths(target) if not path.startswith(task_dir_prefix)
    ]


def _refuse_if_mixed_dirty_paths(task_id: str, *, target: Path) -> None:
    """Refuse a path-less `git add -A` when the dirty worktree mixes
    CoDev-managed changes with everything else -- prevents concurrent
    workflow-file edits from silently riding along in a product commit.
    Callers wanting one or the other on purpose use --paths or --staged.
    """
    managed = _managed_paths(target)
    if not managed:
        return
    dirty = _dirty_paths(target)
    managed_dirty = sorted(path for path in dirty if path in managed)
    other_dirty = sorted(path for path in dirty if path not in managed)
    if managed_dirty and other_dirty:
        raise GitOpsError(
            f"refusing to commit {task_id!r}: the worktree mixes "
            f"CoDev-managed changes ({', '.join(managed_dirty)}) with other "
            f"changes ({', '.join(other_dirty)}) -- use --paths or --staged "
            "to commit them separately"
        )


def commit(
    task_id: str,
    message: str,
    *,
    target: Path,
    paths: list[str] | None = None,
    staged: bool = False,
    round_number: int | None = None,
    evidence: Any = None,
) -> str:
    if not message.strip():
        raise GitOpsError("commit message must not be empty")
    if paths and staged:
        raise GitOpsError("--paths and --staged are mutually exclusive")
    if (round_number is None) != (evidence is None):
        raise GitOpsError("--round and --evidence must be given together")
    _ensure_on_own_branch(task_id, target=target)
    if staged:
        pass
    elif paths:
        _run_git(["add", "--", *paths], cwd=target)
    else:
        _refuse_if_mixed_dirty_paths(task_id, target=target)
        _run_git(["add", "-A"], cwd=target)
    _run_git(["commit", "-m", message], cwd=target)
    head = current_head(target)
    if round_number is not None:
        task.record_builder(task_id, round_number, head, evidence, target=target)
    return head


def push(task_id: str, *, target: Path) -> None:
    branch = _ensure_on_own_branch(task_id, target=target)
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


def _pr_state(branch: str, *, target: Path) -> str | None:
    """The GitHub pull request state for `branch` ("OPEN"/"CLOSED"/
    "MERGED"), or None when no pull request exists for it."""
    try:
        state = _run_gh(
            ["pr", "view", branch, "--json", "state", "-q", ".state"], cwd=target
        )
    except GitOpsError:
        return None
    return state.strip()


@dataclass(frozen=True)
class HumanApproval:
    """Whether a pull request carries the independent human approval
    ADR-0037 requires, and who supplied it."""

    approvals: tuple[str, ...]
    required: int
    excluded_owner: str | None

    @property
    def satisfied(self) -> bool:
        return len(self.approvals) >= self.required


_BOT_SUFFIX = "[bot]"


def human_approval(
    branch: str, *, owner: str | None, required: int = 1, target: Path
) -> HumanApproval | None:
    """The approving reviews on `branch`'s pull request that count toward
    ADR-0037's gate: state APPROVED, author neither the task owner nor a bot.

    Returns None when GitHub cannot answer at all, so a caller reports
    "cannot tell" rather than "not approved" -- the two are different, and
    only one of them should ever block a human.

    GitHub already refuses to let a pull request's *author* approve it, but
    the task owner and the pull request's author are not always the same
    person, so the owner is excluded here by name rather than assumed.
    """
    try:
        raw = _run_gh(
            ["pr", "view", branch, "--json", "reviews", "-q", ".reviews"], cwd=target
        )
    except GitOpsError:
        return None
    try:
        reviews = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return None
    approvals: list[str] = []
    for review in reviews:
        if not isinstance(review, dict) or review.get("state") != "APPROVED":
            continue
        login = (review.get("author") or {}).get("login")
        if not login or login.endswith(_BOT_SUFFIX):
            continue
        if owner is not None and login == owner:
            continue
        if login not in approvals:
            approvals.append(login)
    return HumanApproval(tuple(approvals), required, owner)


def _resolved_globs(key: str, *, target: Path) -> list[str]:
    resolved = config.resolve(key, target=target)
    raw = resolved.value if resolved is not None else config.DEFAULTS[key]
    return [pattern.strip() for pattern in raw.split(",") if pattern.strip()]


def matching_paths(task_id: str, key: str, *, target: Path) -> list[str]:
    """The task's changed files that match one of `key`'s configured globs."""
    patterns = _resolved_globs(key, target=target)
    if not patterns:
        return []
    return [
        path
        for path in changed_files(task_id, target=target)
        if any(fnmatch(path, pattern) for pattern in patterns)
    ]


def required_approvals(task_id: str, *, target: Path) -> int:
    """How many independent human approvals this task's change needs.

    The configured default, raised to two when the change touches a path the
    team declared sensitive (ADR-0037). Risk is a property of what the
    change touches, which is knowable without asking GitHub for labels."""
    base = _resolved_budget("review.required_approvals", target=target)
    if matching_paths(task_id, "review.sensitive_paths", target=target):
        return max(base, 2)
    return base


def pull_request_state(branch: str, *, target: Path) -> str | None:
    """Public, read-only pull-request state for a branch: "OPEN", "CLOSED",
    "MERGED", or None when GitHub cannot answer -- no pull request, no
    remote, or no credentials. The oracle treats None as "cannot tell" and
    falls back to a local recommendation rather than reporting a guess."""
    return _pr_state(branch, target=target)


def _stacked_pr_base(task_id: str, *, target: Path) -> str | None:
    """The recorded parent's branch, when this task was created with
    --stack-on and that parent's own pull request is still open -- None
    otherwise, so the caller falls through to --base/git.pr_base/the
    repository's default branch (ADR-0034)."""
    parent_id = parent_task_id(task_id, target=target)
    if parent_id is None:
        return None
    try:
        parent_state = _load_git_state(parent_id, target=target)
    except GitOpsError:
        return None
    parent_branch = cast(str, parent_state["branch"])
    return parent_branch if _pr_state(parent_branch, target=target) == "OPEN" else None


def open_pr(
    task_id: str,
    title: str,
    body: str,
    *,
    target: Path,
    base: str | None = None,
    use_template: bool = False,
) -> str:
    branch = _ensure_on_own_branch(task_id, target=target)
    head = current_head(target)
    result = task.check(task_id, head, target=target)
    description = task.describe(task_id, target=target)
    # ok_ready_for_pr is produced exactly once, at the inner-to-outer
    # transition -- it never recurs. An item can reach the outer phase
    # without ever passing through it (codev task reopen recovering
    # straight into the outer phase, or a direct-review entry), so once
    # there, any non-stop check() result is eligible too: the guard that
    # actually matters is "no pull request already exists" below, checked
    # against GitHub itself rather than inferred from round-state alone.
    eligible = result.ok and (
        result.reason == "ok_ready_for_pr" or description["current_phase"] == "outer"
    )
    if not eligible:
        raise GitOpsError(
            "refusing to open a pull request: codev task check returned "
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
    resolved_base = _stacked_pr_base(task_id, target=target)
    if resolved_base is None:
        resolved_base = _resolve_pr_base(base, target=target)
    final_body = (
        _render_pr_template(task_id, target=target)
        if use_template
        else _with_issue_link_line(
            body, description.get("link_ref"), task_id=task_id, target=target
        )
    )
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


_MARK_READY_REASONS = (
    "ok_machine_review_complete",
    "ok_machine_review_complete_with_deferrals",
)


_OWNERSHIP_STATEMENT = (
    "I directed this change and I own it. This is an ownership statement, "
    "not an approval -- ADR-0037 requires a separate approving review from "
    "someone who is neither this task's owner nor a bot."
)


def _resolve_reviewer(task_id: str, *, target: Path) -> str | None:
    """The task's recorded independent reviewer, falling back to a
    CODEOWNERS suggestion for the paths it actually touched.

    Never returns the task owner: a change's author cannot be its
    independent reviewer, however little of it they typed (ADR-0037)."""
    try:
        described = task.describe(task_id, target=target)
    except task.TaskError:
        return None
    owner = described.get("owner")
    recorded = described.get("reviewer")
    if recorded and recorded != owner:
        return str(recorded)
    for candidate in suggest_owners(
        changed_files(task_id, target=target), target=target
    ):
        if candidate != owner:
            return candidate
    return None


def mark_ready(task_id: str, *, target: Path) -> None:
    branch = _ensure_on_own_branch(task_id, target=target)
    head = current_head(target)
    result = task.check(task_id, head, target=target)
    if result.reason not in _MARK_READY_REASONS:
        raise GitOpsError(
            "refusing to mark the pull request ready: codev task check returned "
            f"{result.reason!r}, not one of {_MARK_READY_REASONS} ({result.message})"
        )
    final_body = _render_pr_template(task_id, target=target)
    final_body = f"{final_body}\n\n{_OWNERSHIP_STATEMENT}"
    _run_gh(["pr", "edit", branch, "--body", final_body], cwd=target)
    reviewer = _resolve_reviewer(task_id, target=target)
    if reviewer is not None:
        # Best-effort: a reviewer GitHub will not accept (no write access,
        # not a collaborator) must not block taking the pull request out of
        # draft, which is the step that actually matters here.
        with contextlib.suppress(GitOpsError):
            _run_gh(["pr", "edit", branch, "--add-reviewer", reviewer], cwd=target)
    _run_gh(["pr", "ready", branch], cwd=target)


def restack(task_id: str, *, target: Path) -> str:
    """Rebases a stacked task's branch onto its recorded parent's current
    head, force-pushes with `--force-with-lease`, and re-baselines the
    task's own tracked state so `task.check`'s drift comparison still
    matches the rebase's new commit identity (ADR-0034).

    Refuses when the caller is not on the task's own branch, when the
    task has no recorded parent, or once the parent's pull request has
    already merged. A rebase conflict is reported to the human -- the
    repository is left mid-rebase, exactly as plain `git rebase` would
    leave it, for `git rebase --continue`/`--abort` to resolve normally;
    this never attempts to resolve one automatically.
    """
    branch = _ensure_on_own_branch(task_id, target=target)
    parent_id = parent_task_id(task_id, target=target)
    if parent_id is None:
        raise GitOpsError(
            f"refusing to restack {task_id!r}: it has no recorded parent -- "
            "restack only applies to a task created with `codev git branch "
            "--stack-on`"
        )
    parent_state = _load_git_state(parent_id, target=target)
    parent_branch = cast(str, parent_state["branch"])
    if _pr_state(parent_branch, target=target) == "MERGED":
        raise GitOpsError(
            f"refusing to restack: {parent_branch!r}'s pull request has "
            "already merged -- rebase onto the repository's default branch "
            "manually instead; restack is only for an in-flight parent"
        )

    try:
        _run_git(["rebase", parent_branch], cwd=target)
    except GitOpsError as error:
        raise GitOpsError(
            f"restack stopped: rebasing onto {parent_branch!r} reported a "
            "conflict or another problem -- resolve it with `git status`, "
            f"then `git rebase --continue` or `git rebase --abort`: {error}"
        ) from error

    new_head = current_head(target)
    _run_git(["push", "--force-with-lease", "-u", "origin", branch], cwd=target)

    pinned_parent_head = _run_git(["rev-parse", parent_branch], cwd=target)
    git_state = _load_git_state(task_id, target=target)
    git_state["base_snapshot"] = pinned_parent_head
    _git_state_path(target, task_id).write_text(
        json.dumps(git_state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    task.record_restack(task_id, new_head, target=target)
    return new_head
