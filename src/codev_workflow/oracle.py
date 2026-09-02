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
"""Resolves where a task stands and what should happen next.

ADR-0036 rule three: phase-boundary guidance is computed, not conventional.
The agent consults this at the start of every turn and after every state
change, then renders it as one plain-language recommendation -- so the
sequencing knowledge lives here, tested, rather than in a paragraph each
adapter is asked to remember.

This module is deliberately a pure read. It never writes state, never calls
GitHub for anything but status, and never decides authority: every
recommendation it returns is something a human or an agent then chooses to
do. `next_action` answers "where am I and what now?"; acting on the answer
is someone else's job.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from codev_workflow import git_ops, task


@dataclass(frozen=True)
class NextAction:
    """One computed position, with the single next step it implies."""

    position: str
    recommendation: str
    reason: str
    command: str | None = None
    task_id: str | None = None
    branch: str | None = None
    slice_id: str | None = None
    check_reason: str | None = None
    blocked: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# Every `task.check` outcome maps to exactly one next step. Keeping this a
# table rather than a chain of conditionals is the point: the thirteen
# outcomes already are the routing table, and a missing entry should be a
# visible KeyError in a test rather than a silent fallthrough in a session.
_BY_CHECK_REASON: dict[str, tuple[str, str, str | None, bool]] = {
    # Covers both a freshly opened round and one whose builder has already
    # reported, so the reason must not claim a builder round exists -- the
    # discovery step for slice C1 caught it asserting exactly that on a task
    # that had only just started.
    "ok_waiting_on_reviewer": (
        "review the round",
        "this round has no reviewer verdict recorded yet",
        "dispatch lightweight-reviewer against the current head",
        False,
    ),
    "ok_continue": (
        "correct the findings",
        "the reviewer asked for changes and the round cap allows another pass",
        "route the findings back to builder, then re-review",
        False,
    ),
    "ok_ready_for_pr": (
        "open the pull request",
        "the inner loop is satisfied for this slice",
        "codev git push, then codev git open-pr",
        False,
    ),
    "ok_waiting_on_triage": (
        "triage the blocking findings",
        "specialists recorded findings and a human must choose what is "
        "addressed this round",
        "codev task triage",
        False,
    ),
    "ok_machine_review_complete": (
        "request human review",
        "every machine gate is satisfied -- this is not a human approval",
        "codev git mark-ready",
        False,
    ),
    "ok_machine_review_complete_with_deferrals": (
        "request human review",
        "every blocking finding was deferred with a reason; the machine gates "
        "are satisfied and the deferrals are on record",
        "codev git mark-ready",
        False,
    ),
    "ok_blocked_missing_evidence": (
        "supply the missing evidence",
        "the reviewer could not judge the change from what it was given",
        None,
        False,
    ),
    "ok_outer_loop_needs_reopen": (
        "confirm, then reopen",
        "this item is already in the outer phase with a recorded hand-off; "
        "re-entering must be a deliberate decision, not drift",
        "codev task reopen",
        True,
    ),
    "stop_drift": (
        "escalate: the snapshot moved",
        "code changed outside the tracked builder/reviewer flow",
        "codev task escalate --trigger stop_drift",
        True,
    ),
    "stop_round_cap": (
        "escalate: the round cap is reached",
        "this phase has spent its rounds without converging",
        "codev task escalate --trigger stop_round_cap",
        True,
    ),
    "stop_repeated_finding": (
        "escalate: a finding repeated",
        "the same blocking finding came back, so the correction is not working",
        "codev task escalate --trigger stop_repeated_finding",
        True,
    ),
    "stop_scope_expansion": (
        "escalate: scope expanded",
        "a finding appeared that this phase's first round did not raise",
        "codev task escalate --trigger stop_scope_expansion",
        True,
    ),
    "stop_incomplete_coverage": (
        "cover the missing dimensions",
        "the coverage manifest is incomplete or failing",
        "dispatch the specialists that own the missing dimensions, or waive "
        "them with a reason",
        True,
    ),
}


def _task_id_for_branch(branch: str) -> str | None:
    prefix = git_ops.branch_name_for("")
    return branch[len(prefix) :] if branch.startswith(prefix) else None


def next_action(
    *, target: Path, task_id: str | None = None, check_github: bool = True
) -> NextAction:
    """Where the work stands, and the one thing to do next."""
    try:
        branch = git_ops.current_branch(target)
    except git_ops.GitOpsError:
        return NextAction(
            position="not a git repository",
            recommendation="run this inside a repository with CoDev installed",
            reason="no git branch could be resolved",
            blocked=True,
        )

    resolved = task_id or _task_id_for_branch(branch)
    if resolved is None:
        return NextAction(
            position="no task on this branch",
            recommendation="pick up an issue and start a task",
            reason=(
                f"branch {branch!r} is not one codev git branch created, so no "
                "task's round state is associated with it"
            ),
            command="codev git branch, then codev task start",
            branch=branch,
        )

    try:
        state = task.describe(resolved, target=target)
    except task.TaskError:
        return NextAction(
            position="branch exists, no round state",
            recommendation="open round state for this task",
            reason=f"branch {branch!r} exists but task {resolved!r} has none",
            command="codev task start",
            task_id=resolved,
            branch=branch,
        )

    if state["status"] != "in_progress":
        return NextAction(
            position=f"task closed ({state['status']})",
            recommendation="start the next task",
            reason=f"task {resolved!r} is closed, nothing further is tracked",
            task_id=resolved,
            branch=branch,
        )

    head = git_ops.current_head(target)
    result = task.check(resolved, head, target=target)
    slice_id = task.current_slice(resolved, target=target)
    final = task.is_final_slice(resolved, slice_id, target=target)

    if check_github and result.reason in (
        "ok_machine_review_complete",
        "ok_machine_review_complete_with_deferrals",
    ):
        github = _github_position(resolved, branch, slice_id, final, target=target)
        if github is not None:
            return github

    recommendation, reason, command, blocked = _BY_CHECK_REASON[result.reason]
    return NextAction(
        position=f"{state['current_phase']} phase, round {state['current_round']}",
        recommendation=recommendation,
        reason=reason,
        command=command,
        task_id=resolved,
        branch=branch,
        slice_id=slice_id,
        check_reason=result.reason,
        blocked=blocked,
    )


def _github_position(
    task_id: str, branch: str, slice_id: str, final: bool, *, target: Path
) -> NextAction | None:
    """The positions only GitHub knows about: whether this slice's pull
    request is open, merged, or absent, and what that implies.

    Returns None when GitHub cannot answer, so the caller falls back to the
    local recommendation rather than reporting a guess as fact.
    """
    state = git_ops.pull_request_state(branch, target=target)
    if state is None:
        return None
    if state == "MERGED":
        if final:
            return NextAction(
                position="final slice merged",
                recommendation="close the task",
                reason="every slice this task holds has landed",
                command="codev task close --outcome approved",
                task_id=task_id,
                branch=branch,
                slice_id=slice_id,
            )
        return NextAction(
            position="slice merged, more remain",
            recommendation="advance to the next slice",
            reason=(f"slice {slice_id!r} has landed and this task holds a later one"),
            command="codev task advance-slice",
            task_id=task_id,
            branch=branch,
            slice_id=slice_id,
        )
    if state == "OPEN":
        return NextAction(
            position="pull request open, awaiting human review",
            recommendation="wait for an independent human approval",
            reason=(
                "the machine gates are satisfied and the pull request is open; "
                "approval is a human decision this tool does not make"
            ),
            task_id=task_id,
            branch=branch,
            slice_id=slice_id,
            check_reason="ok_machine_review_complete",
        )
    return None
