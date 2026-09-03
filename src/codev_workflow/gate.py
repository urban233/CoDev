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
"""The gate decisions CoDev enforces, owned by `codev` rather than by one
platform's hook scripts.

The three guardrails -- plan-first, rolling-wave shape, and change size --
began as Claude Code hook scripts, which meant CoDev's opinions were a
property of one adapter and every other platform got the prose version: the
version that can be talked out of. This module is the single implementation;
each platform's hook becomes a thin shim that calls `codev gate check` and
translates the answer into its own protocol.

Every gate asks and pauses rather than refusing (ADR-0030), and every gate
fails open: a guardrail that errors must never block work.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from codev_workflow import git_ops, task

GATES = ("plan", "wave-shape", "small-change")

_GATED_EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

_DESTRUCTIVE_BASH_PREFIXES = (
    "git commit",
    "git push",
    "git merge",
    "git reset",
    "git checkout",
    "git clean",
    "git rebase",
    "rm -rf",
    "rm -r ",
    "codev git branch",
    "codev git commit",
    "codev git push",
    "codev git restack",
)

_TASK_BRANCH_PREFIX = "codev/"  # must match git_ops.branch_name_for()

_TASK_PLAN_TEMPLATE = "docs/codev/task/{task_id}/implementation-plan.md"

_SPEC_GLOBS = (
    "docs/features/*/design.md",
    "docs/codev/features/*/design.md",
    "docs/codev/wave/*.md",
    # A gate that cannot see the artifact it asks for teaches agents that the
    # artifact is pointless. This one could not: `docs/plans/` is where this
    # repository keeps every accepted plan, including the ones authorizing the
    # work the gate was interrupting.
    "docs/plans/*.md",
)

# Paths where a small diff does large damage, so size is the wrong question.
# Deliberately a fixed list rather than a configuration key: CoDev's answer to
# "more structure" is a better default, not another thing to configure.
_ALWAYS_PLANNED = (
    # Reproducibility. A one-line version bump can change what the code
    # computes, and for research software that surfaces as an unreproducible
    # result rather than an outage.
    "pyproject.toml",
    "uv.lock",
    "requirements*.txt",
    "package.json",
    "package-lock.json",
    "Cargo.toml",
    "go.mod",
    "environment*.yml",
    # Whether anything is checked at all is not a small change.
    ".github/workflows/*",
    # Irreversible against real data.
    "*/migrations/*",
    "migrations/*",
)

_UNGATED_BRANCHES = {"main", "master", "HEAD"}

_GATED_CONTENT_TOOLS = {"Write", "Edit", "MultiEdit"}

_ISSUE_CREATE_PREFIX = "codev git issue-create"

_WAVE_PLAN_GLOB = "docs/codev/wave/*.md"

_LATER_WAVES_HEADING = "## Later waves"

_OPEN_PR_PREFIX = "codev git open-pr"

_TASK_ID_PATTERN = re.compile(r"--id[= ]+(\S+)")


@dataclass(frozen=True)
class GateDecision:
    """One gate's answer: `allow` or `ask`, and why."""

    decision: str
    reason: str
    gate: str
    # False when the gate never applied -- a tool it does not watch, or a
    # payload it could not read. Those are not guardrail decisions and must
    # not reach the decision log, or `codev status`'s gate summary would
    # count every unrelated tool call as an allow.
    recorded: bool = True

    @property
    def asks(self) -> bool:
        return self.decision == "ask"

    @property
    def allows(self) -> bool:
        """`degraded` allows the tool call too -- it just did not check."""
        return self.decision in ("allow", "degraded")

    def as_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "decision": self.decision,
            "reason": self.reason,
            "recorded": self.recorded,
        }


def _allow(gate: str, reason: str) -> GateDecision:
    return GateDecision("allow", reason, gate)


def _not_applicable(gate: str, reason: str) -> GateDecision:
    return GateDecision("allow", reason, gate, recorded=False)


def _degraded(gate: str, reason: str) -> GateDecision:
    """The gate could not decide. It allows -- a guardrail that errors must
    never block work -- but this is not a guardrail that passed, and the two
    must not look the same in the record."""
    return GateDecision("degraded", reason, gate)


def _ask(gate: str, reason: str) -> GateDecision:
    return GateDecision("ask", reason, gate)


def _gate_reason(payload: dict[str, Any]) -> str | None:
    """Returns why this call is gated, or None if it should be allowed
    without any further check."""
    tool_name = payload.get("tool_name")
    if tool_name in _GATED_EDIT_TOOLS:
        return "edit"
    if tool_name == "Bash":
        tool_input = payload.get("tool_input")
        command = ""
        if isinstance(tool_input, dict):
            command = str(tool_input.get("command") or "").strip()
        if any(command.startswith(prefix) for prefix in _DESTRUCTIVE_BASH_PREFIXES):
            return "bash"
    return None


def _current_branch(repo_root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _has_precise_task_plan(repo_root: Path, branch: str) -> bool:
    if not branch.startswith(_TASK_BRANCH_PREFIX):
        return False
    task_id = branch[len(_TASK_BRANCH_PREFIX) :]
    if not task_id:
        return False
    plan = repo_root / _TASK_PLAN_TEMPLATE.format(task_id=task_id)
    return plan.is_file()


def _branch_slug(branch: str) -> str:
    tail = branch.rsplit("/", 1)[-1]
    return tail.strip().lower()


def _has_matching_spec(repo_root: Path, slug: str) -> bool:
    for pattern in _SPEC_GLOBS:
        for match in repo_root.glob(pattern):
            # docs/features/*/design.md and docs/codev/features/*/design.md
            # carry the slug in the parent directory; docs/codev/wave/*.md
            # carries it in the filename itself -- check both rather than
            # assuming one convention for every glob.
            candidates = {match.parent.name.lower(), match.stem.lower()}
            if slug and any(
                slug in candidate or candidate in slug for candidate in candidates
            ):
                return True
    return False


def _later_waves_section_lines(text: str) -> list[str]:
    """Returns the lines of the "## Later waves" section, or an empty list
    if the document has no such heading. Stops at the next "## " heading."""
    section: list[str] = []
    in_section = False
    for line in text.splitlines():
        if line.strip() == _LATER_WAVES_HEADING:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section:
            section.append(line)
    return section


def _has_populated_task_table(section_lines: list[str]) -> bool:
    """A markdown table row starts with "|". The wave-plan template's own
    explanatory HTML comment inside this section never does, so no
    special-casing is needed for it."""
    return any(line.strip().startswith("|") for line in section_lines)


def _relative(path: Path, repo_root: Path) -> Path:
    return path.relative_to(repo_root) if path.is_absolute() else path


def _wave_plan_violation(repo_root: Path) -> Path | None:
    """Returns the first wave-plan document (by sorted path) with a
    populated task table in its "Later waves" section, or None if every
    wave-plan document -- if any exist at all -- is well-formed."""
    for match in sorted(repo_root.glob(_WAVE_PLAN_GLOB)):
        try:
            text = match.read_text(encoding="utf-8")
        except OSError:
            continue
        if _has_populated_task_table(_later_waves_section_lines(text)):
            return match
    return None


def _apply_edit(
    content: str, old_string: str, new_string: str, replace_all: bool
) -> str | None:
    """Applies one Edit-style replacement to content. Returns None (not
    applicable) when old_string equals new_string or is absent from
    content, mirroring the real Edit tool's own refusal conditions rather
    than guessing past them."""
    if old_string == new_string or old_string not in content:
        return None
    if replace_all:
        return content.replace(old_string, new_string)
    return content.replace(old_string, new_string, 1)


def _target_content_after_edit(
    payload: dict[str, Any], repo_root: Path
) -> tuple[Path, str] | None:
    """For a Write/Edit/MultiEdit call targeting a wave-plan path, returns
    (path, the content that path would have after this call). Returns None
    for any other call, or when the resulting content can't be determined
    -- this only ever inspects a wave-plan document's own content, never an
    unrelated file's, and never guesses past an unexpected payload shape."""
    tool_name = payload.get("tool_name")
    if tool_name not in _GATED_CONTENT_TOOLS:
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    file_path = str(tool_input.get("file_path") or tool_input.get("path") or "")
    if not file_path:
        return None
    candidate = Path(file_path)
    relative = _relative(candidate, repo_root)
    if not relative.match(_WAVE_PLAN_GLOB):
        return None

    if tool_name == "Write":
        content = tool_input.get("content")
        if not isinstance(content, str):
            return None
        return candidate, content

    try:
        current = candidate.read_text(encoding="utf-8")
    except OSError:
        return None

    if tool_name == "Edit":
        old_string = tool_input.get("old_string")
        new_string = tool_input.get("new_string")
        if not isinstance(old_string, str) or not isinstance(new_string, str):
            return None
        result = _apply_edit(
            current, old_string, new_string, bool(tool_input.get("replace_all"))
        )
        return (candidate, result) if result is not None else None

    # MultiEdit -- [unverified] payload shape, see module docstring. An
    # unexpected shape returns None here, which falls through to allow.
    edits = tool_input.get("edits")
    if not isinstance(edits, list) or not edits:
        return None
    for edit in edits:
        if not isinstance(edit, dict):
            return None
        old_string = edit.get("old_string")
        new_string = edit.get("new_string")
        if not isinstance(old_string, str) or not isinstance(new_string, str):
            return None
        result = _apply_edit(
            current, old_string, new_string, bool(edit.get("replace_all"))
        )
        if result is None:
            return None
        current = result
    return candidate, current


def _is_issue_create(payload: dict[str, Any]) -> bool:
    if payload.get("tool_name") != "Bash":
        return False
    tool_input = payload.get("tool_input")
    command = ""
    if isinstance(tool_input, dict):
        command = str(tool_input.get("command") or "").strip()
    return command.startswith(_ISSUE_CREATE_PREFIX)


def _open_pr_task_id(payload: dict[str, Any]) -> str | None:
    """The task id of a `codev git open-pr` Bash call, or None when this
    call isn't one, or the id can't be found -- prefix matching, not a
    full shell parse, the same heuristic require_plan.py's gated-command
    check already accepts (see its own module docstring)."""
    if payload.get("tool_name") != "Bash":
        return None
    tool_input = payload.get("tool_input")
    command = ""
    if isinstance(tool_input, dict):
        command = str(tool_input.get("command") or "").strip()
    if not command.startswith(_OPEN_PR_PREFIX):
        return None
    match = _TASK_ID_PATTERN.search(command)
    return match.group(1) if match else None


def _is_always_planned(relative: Path) -> bool:
    """Whether this path is one the plan gate asks about regardless of size."""
    text = relative.as_posix()
    return any(
        fnmatch(text, pattern) or fnmatch(relative.name, pattern)
        for pattern in _ALWAYS_PLANNED
    )


def _within_size_budget(repo_root: Path, branch: str) -> bool | None:
    """Whether the change accumulated on this branch still fits a focus card.

    None when it cannot be measured, which the caller treats as "ask" rather
    than "allow": this relaxes a guardrail, so an unmeasurable change must
    keep the stricter answer.

    The gate fires *before* an edit, so the only diff it can see is the one
    already on the branch. That reads like a flaw and is the point: the old
    gate interrupted before the work started, when a developer knows least
    about what the change will need. This one interrupts when the change
    grows past what a focus card can carry, which is when a written plan is
    worth its cost.
    """
    if not branch.startswith(_TASK_BRANCH_PREFIX):
        return None
    task_id = branch[len(_TASK_BRANCH_PREFIX) :]
    if not task_id:
        return None
    # `codev task size` answers with zeros and over_budget=false for a task it
    # cannot actually measure -- one that does not exist, or whose state
    # carries no base to diff against. That is a measurement of nothing, not a
    # measurement of a small change, and trusting it would let any branch
    # merely *named* `codev/...` skip the gate entirely. Require a base
    # snapshot before believing the number.
    task_dir = repo_root / ".codev" / "task" / task_id
    try:
        state = json.loads((task_dir / "round-state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(state, dict) or not state.get("base_snapshot"):
        return None
    # And the branch must be one CoDev recorded. `_measure` returns
    # TaskSize(0, 0, ...) when it cannot load `git-state.json`, which is
    # indistinguishable from a genuinely small change -- so a branch merely
    # *named* `codev/...` and given round state by hand, without
    # `codev git branch` ever recording it, would measure as zero and skip
    # the gate however large it grew. Found by the outer-loop review of the
    # pull request that introduced this tier, and reproduced with a 500-line
    # change scoring `within-budget-small-change`.
    if not (task_dir / "git-state.json").is_file():
        return None
    size = _slice_size(task_id, repo_root=repo_root)
    if size is None or "over_budget" not in size:
        return None
    return not bool(size["over_budget"])


def _plan_gate(payload: dict[str, Any], repo_root: Path) -> GateDecision:
    """Plan-first: pause before the first source edit, or the first
    repository-mutating git command, when no design or plan document exists
    for the active branch."""
    gate = "plan"
    reason = _gate_reason(payload)
    if reason is None:
        return _not_applicable(gate, "not-a-gated-tool")

    tool_input = payload.get("tool_input")
    file_path = ""
    if reason == "edit" and isinstance(tool_input, dict):
        file_path = str(tool_input.get("file_path") or tool_input.get("path") or "")
    if file_path:
        candidate = Path(file_path)
        relative = (
            candidate.relative_to(repo_root) if candidate.is_absolute() else candidate
        )
        if relative.parts and relative.parts[0] == "docs":
            return _allow(gate, "docs")

    branch = _current_branch(repo_root)
    if not branch or branch in _UNGATED_BRANCHES:
        return _allow(gate, "ungated-branch")
    if _has_precise_task_plan(repo_root, branch):
        return _allow(gate, "precise-task-plan")
    if _has_matching_spec(repo_root, _branch_slug(branch)):
        return _allow(gate, "coarse-spec-match")

    # Risk-tiered, and only for edits: a repository-mutating git command is
    # not made safe by the change being small, and `--allow-dirty` style
    # mistakes are exactly what the bash arm exists to catch.
    if reason == "edit":
        if file_path and _is_always_planned(_relative(Path(file_path), repo_root)):
            return _ask(
                gate,
                f"{file_path} is a dependency manifest, CI definition, or "
                "migration -- a small diff there changes what the code "
                "computes, what gets checked, or what happens to real data, "
                "so size is not the question. If this is an intentional, "
                "already-discussed step, approve and continue.",
            )
        if _within_size_budget(repo_root, branch):
            return _allow(gate, "within-budget-small-change")

    if reason == "bash":
        return _ask(
            gate,
            "This looks like a repository-mutating git command, and no "
            "design/plan doc or recorded task plan was found for this "
            "branch. If this is an intentional, already-discussed step, "
            "approve and continue -- otherwise consider design-solution "
            "or build-change first.",
        )
    return _ask(
        gate,
        "No design/plan doc or recorded task plan was found for this "
        "branch. If this is intentionally a small, spec-free change, "
        "approve and continue -- otherwise consider design-solution or "
        "build-change first.",
    )


def _wave_shape_gate(payload: dict[str, Any], repo_root: Path) -> GateDecision:
    """Rolling-wave discipline (ADR-0032): detail only the current wave."""
    gate = "wave-shape"
    edit_target = _target_content_after_edit(payload, repo_root)
    if edit_target is not None:
        _, content = edit_target
        if _has_populated_task_table(_later_waves_section_lines(content)):
            return _ask(
                gate,
                "This save leaves a populated task table in a 'Later "
                "waves' section -- plan-wave's rolling-wave discipline "
                "keeps only the current wave detailed. If this is "
                "intentional, approve and continue.",
            )
        return _allow(gate, "well-formed")

    if _is_issue_create(payload):
        violation = _wave_plan_violation(repo_root)
        if violation is None:
            return _allow(gate, "no-violation")
        return _ask(
            gate,
            f"{_relative(violation, repo_root)} has a populated task "
            "table in its 'Later waves' section -- detail only the "
            "current wave before creating issues. If this issue "
            "genuinely is for the current wave and the other section "
            "just needs cleanup, approve and continue.",
        )
    return _not_applicable(gate, "not-a-gated-tool")


def _small_change_gate(payload: dict[str, Any], repo_root: Path) -> GateDecision:
    """Size: pause before a pull request opens for an over-budget slice."""
    gate = "small-change"
    task_id = _open_pr_task_id(payload)
    if task_id is None:
        return _not_applicable(gate, "not-a-gated-tool")
    size = _slice_size(task_id, repo_root=repo_root)
    if size is None:
        return _degraded(
            gate, "the slice size could not be measured, so it was not checked"
        )
    if not size.get("over_budget"):
        return _allow(gate, "within-budget")
    return _ask(
        gate,
        f"{task_id!r}'s slice is {size.get('lines_changed')} non-generated "
        f"line(s) (budget {size.get('max_lines')}) and "
        f"{size.get('files_changed')} file(s) (budget {size.get('max_files')}) "
        "-- over budget. A reviewer reads one pull request, so the budget "
        "applies per slice. If this is intentional, approve and continue; "
        "otherwise consider splitting it into slices first (see the plan's "
        "Slices field, and codev task start --slice).",
    )


def _slice_size(task_id: str, *, repo_root: Path) -> dict[str, Any] | None:
    """The slice's running size, or None when it cannot be measured.

    Measured in-process. This used to shell out to `codev task size`, which
    dated from the hooks being standalone scripts outside the package; now
    that the gates live in `codev_workflow`, spawning a second copy of
    ourselves made both gates depend on a `codev` happening to be on PATH and
    on it being the same build. A gate that silently stops checking because
    an executable moved is exactly the failure this module's own degraded
    reporting exists to surface.
    """
    try:
        size = git_ops.slice_size(task_id, target=repo_root)
    except (git_ops.GitOpsError, task.TaskError, KeyError, OSError):
        return None
    return {
        "lines_changed": size.lines_changed,
        "files_changed": size.files_changed,
        "max_lines": size.max_lines,
        "max_files": size.max_files,
        "over_budget": size.over_budget,
    }


_GATES = {
    "plan": _plan_gate,
    "wave-shape": _wave_shape_gate,
    "small-change": _small_change_gate,
}


def check(gate: str, payload: Any, *, target: Path) -> GateDecision:
    """Decide one gate for one tool-use payload.

    Fails open on anything unexpected: a guardrail that errors must never
    block work, and every caller here is a hook standing between a developer
    and their next edit.
    """
    if gate not in _GATES:
        raise ValueError(f"unknown gate {gate!r}; expected one of {GATES}")
    if not isinstance(payload, dict):
        return _not_applicable(gate, "unreadable-payload")
    repo_root = Path(payload.get("cwd") or target)
    try:
        return _GATES[gate](payload, repo_root)
    except Exception as error:  # noqa: BLE001 - guardrails fail open
        return _degraded(gate, f"internal error: {error}")
