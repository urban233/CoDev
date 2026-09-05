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
"""The navigator: where the work stands, and the one thing to do next.

Named for the half of a driver/navigator pair that does not have hands on the
keyboard. That is this module's entire job, and in a `pair` slice (ADR-0038)
the metaphor is literal -- the developer drives and this says what is next.

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

from codev_workflow import config, git_ops, task


@dataclass(frozen=True)
class Option:
    """One thing a human could choose here, and what choosing it means.

    A blocked position used to return a single escalate command, which reads
    as a dead end even though every stop has at least two honest ways out.
    Carrying them as data lets an agent render a decision instead of a wall,
    without moving any authority: choosing is still a human's job.
    """

    label: str
    command: str | None
    consequence: str


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
    options: tuple[Option, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _Routing:
    """What one `task.check` outcome implies. A record rather than a tuple
    because the fifth field arrived and unpacking four-tuples in a dozen
    places is how a fifth field gets skipped."""

    recommendation: str
    reason: str
    command: str | None
    blocked: bool
    options: tuple[Option, ...] = ()


# Every `task.check` outcome maps to exactly one next step. Keeping this a
# table rather than a chain of conditionals is the point: the thirteen
# outcomes already are the routing table, and a missing entry should be a
# visible KeyError in a test rather than a silent fallthrough in a session.
_ESCALATE = "record the escalation and stop for a human"

_BY_CHECK_REASON: dict[str, _Routing] = {
    # Covers a round whose builder has already reported. The freshly-opened
    # case no longer lands here: `_inner_loop_position` splits it out below,
    # because telling an agent to review a round that has no work in it is
    # naming the wrong actor, not merely being vague.
    "ok_waiting_on_reviewer": _Routing(
        "review the round",
        "the builder's round is committed and recorded, and no reviewer "
        "verdict has been recorded against it yet",
        "dispatch lightweight-reviewer against the current head",
        False,
    ),
    "ok_continue": _Routing(
        "correct the findings",
        "the reviewer asked for changes and the round cap allows another pass",
        "route the findings back to builder, then re-review",
        False,
    ),
    "ok_ready_for_pr": _Routing(
        "publish the slice",
        "the inner loop is satisfied for this slice",
        "codev slice publish",
        False,
    ),
    "ok_waiting_on_triage": _Routing(
        "triage the blocking findings",
        "specialists recorded findings and a human must choose what is "
        "addressed this round",
        "codev task triage",
        False,
    ),
    "ok_machine_review_complete": _Routing(
        "request human review",
        "every machine gate is satisfied -- this is not a human approval",
        "codev git mark-ready",
        False,
    ),
    "ok_machine_review_complete_with_deferrals": _Routing(
        "request human review",
        "every blocking finding was deferred with a reason; the machine gates "
        "are satisfied and the deferrals are on record",
        "codev git mark-ready",
        False,
    ),
    "ok_blocked_missing_evidence": _Routing(
        "supply the missing evidence",
        "the reviewer could not judge the change from what it was given",
        None,
        False,
        (
            Option(
                "re-run the builder for evidence only",
                "codev round close --role builder --evidence <file>",
                "the same change, re-reported with the validation it omitted",
            ),
            Option(
                "review it yourself instead",
                None,
                "you judge the diff directly; nothing further is automated",
            ),
        ),
    ),
    "ok_outer_loop_needs_reopen": _Routing(
        "confirm, then reopen",
        "this item is already in the outer phase with a recorded hand-off; "
        "re-entering must be a deliberate decision, not drift",
        "codev task reopen",
        True,
        (
            Option(
                "reopen deliberately",
                "codev task reopen",
                "the outer phase re-enters and the reopen is on record",
            ),
            Option(
                "leave it in the outer phase",
                None,
                "the recorded hand-off stands and nothing changes",
            ),
        ),
    ),
    "stop_drift": _Routing(
        "escalate: the snapshot moved",
        "code changed outside the tracked builder/reviewer flow",
        "codev task escalate --trigger stop_drift",
        True,
        (
            Option(
                "absorb the change as pair work",
                "codev task pause, then codev task resume --reason <why>",
                "the edits become part of the record and the round cap is "
                "raised so the interruption costs no budget. `resume` acts on "
                "a paused slice, so `pause` records the interruption first -- "
                "naming only `resume` here sent a caller to a command that "
                "refuses with 'is not paused', found by taking this very "
                "option on this module's own pull request",
            ),
            Option(
                "escalate",
                "codev task escalate --trigger stop_drift",
                _ESCALATE,
            ),
        ),
    ),
    "stop_round_cap": _Routing(
        "escalate: the round cap is reached",
        "this phase has spent its rounds without converging",
        "codev task escalate --trigger stop_round_cap",
        True,
        (
            Option(
                "take the keyboard",
                "codev task pause, then codev task resume --reason <why>",
                "pair work continues the slice and raises the cap by one; "
                "`resume` acts on a paused slice, so `pause` comes first",
            ),
            Option(
                "escalate",
                "codev task escalate --trigger stop_round_cap",
                _ESCALATE,
            ),
        ),
    ),
    "stop_repeated_finding": _Routing(
        "escalate: a finding repeated",
        "the same blocking finding came back, so the correction is not working",
        "codev task escalate --trigger stop_repeated_finding",
        True,
        (
            Option(
                "re-scope the correction",
                "codev task pause, then codev task resume --reason <why>",
                "the repeated finding is worked by hand rather than by another "
                "identical builder pass",
            ),
            Option(
                "defer it with a reason",
                "codev task waive --reason <why>",
                "the finding is recorded as deliberately not addressed, and "
                "says so in the pull-request body",
            ),
            Option(
                "escalate",
                "codev task escalate --trigger stop_repeated_finding",
                _ESCALATE,
            ),
        ),
    ),
    "stop_scope_expansion": _Routing(
        "escalate: scope expanded",
        "a finding appeared that this phase's first round did not raise",
        "codev task escalate --trigger stop_scope_expansion",
        True,
        (
            Option(
                "split the new finding into its own slice",
                "codev slice begin --id <new-id> --base <sha>",
                "this slice lands at its original scope and the new work gets "
                "its own branch, issue, and review",
            ),
            Option(
                "escalate",
                "codev task escalate --trigger stop_scope_expansion",
                _ESCALATE,
            ),
        ),
    ),
    "stop_incomplete_coverage": _Routing(
        "cover the missing dimensions",
        "the coverage manifest is incomplete or failing",
        "dispatch the specialists that own the missing dimensions",
        True,
        (
            Option(
                "run the missing specialists",
                "dispatch the specialists that own the missing dimensions",
                "the manifest completes and the outer phase can conclude",
            ),
            Option(
                "waive a dimension with a reason",
                "codev task waive --reason <why>",
                "the gap is recorded as deliberate rather than closed",
            ),
        ),
    ),
}


# Where each planning artifact lives, most advanced first. The `Status:` line
# every one of these carries in its opening lines is the acceptance signal --
# a convention `gate.py` already relies on, so this introduces no new metadata
# format for a repository to keep in step.
_PLANNING_STAGES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("plan", ("docs/plans/*.md", "docs/codev/task/*/implementation-plan.md")),
    ("wave plan", ("docs/codev/wave/*.md",)),
    (
        "design",
        (
            "docs/features/*/design.md",
            "docs/codev/features/*/design.md",
            "docs/codev/design/*/design.md",
        ),
    ),
    ("brief", ("docs/codev/brief/*.md", "docs/features/*/brief.md")),
)

_NEXT_AFTER: dict[str, tuple[str, str]] = {
    "brief": ("design-solution", "a design decides the contracts before slices exist"),
    "design": ("plan-wave", "a plan turns an accepted design into ordered slices"),
    "wave plan": ("plan-wave", "the wave's tasks each need a plan with slices"),
}

_STATUS_SCAN_BYTES = 600


def _is_accepted(path: Path) -> bool | None:
    """Whether a planning artifact declares itself accepted, or None when it
    carries no `Status:` line at all and so makes no claim either way."""
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:_STATUS_SCAN_BYTES]
    except OSError:
        return None
    for line in head.splitlines():
        stripped = line.strip().replace("*", "")
        if stripped.lower().startswith("status:"):
            status = stripped.split(":", 1)[1].strip().lower()
            return bool(status.split() and status.split()[0] == "accepted")
    return None


def _planning_position(branch: str, *, target: Path) -> NextAction:
    """What to do when no task branch exists.

    Every state before a task used to collapse into one sentence -- "pick up
    an issue and start a task" -- which left the whole Understand, Design and
    Plan half of the lifecycle unguided. That is the half where a developer
    has the least context and the most to decide, so it is the half the
    guidance obligation was written for.
    """
    for stage, patterns in _PLANNING_STAGES:
        found = [
            match
            for pattern in patterns
            for match in sorted(target.glob(pattern))
            if match.is_file()
        ]
        if not found:
            continue
        accepted = [path for path in found if _is_accepted(path) is True]
        drafted = [path for path in found if _is_accepted(path) is False]
        if stage == "plan" and accepted:
            names = ", ".join(sorted(path.name for path in accepted[:3]))
            return NextAction(
                position="accepted plan, no branch",
                recommendation="begin a slice from an accepted plan",
                reason=(
                    f"{names} declare themselves accepted, and no task branch "
                    "is tracking one of their slices"
                ),
                command="codev slice begin",
                branch=branch,
            )
        if drafted and not accepted:
            names = ", ".join(sorted(path.name for path in drafted[:3]))
            return NextAction(
                position=f"{stage} drafted, not accepted",
                recommendation="get a decision on the draft",
                reason=(
                    f"{names} exist but declare no accepted status, and "
                    "nothing downstream of them can start until one does"
                ),
                command=None,
                branch=branch,
            )
        if accepted and stage in _NEXT_AFTER:
            skill, why = _NEXT_AFTER[stage]
            return NextAction(
                position=f"{stage} accepted, nothing downstream",
                recommendation=f"use {skill}",
                reason=f"an accepted {stage} exists but {why}",
                command=None,
                branch=branch,
            )
    return NextAction(
        position="no planning artifact",
        recommendation="frame the work first",
        reason=(
            "this repository holds no brief, design, or plan, so there is "
            "nothing an implementation could be checked against"
        ),
        command=None,
        branch=branch,
        options=(
            Option(
                "frame one change",
                "use define-product",
                "a brief naming the users, outcome, and scope of one addition",
            ),
            Option(
                "frame the whole product",
                "use specify-project",
                "one canonical SPECIFICATION.md, for greenfield or a redesign",
            ),
        ),
    )


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
        return _planning_position(branch, target=target)

    try:
        state = task.describe(resolved, target=target)
    except task.TaskError:
        return NextAction(
            position="branch exists, no round state",
            recommendation="open round state for this task",
            reason=f"branch {branch!r} exists but task {resolved!r} has none",
            # Not `slice begin`: it creates the branch, and the branch is what
            # already exists. This position is the recovery path for a branch
            # made before `slice begin` existed, or one whose `begin` failed
            # partway, so it names the granular verb that can still run.
            command="codev task start",
            task_id=resolved,
            branch=branch,
        )

    # The raw recorded status, not `describe()`'s ADR-0045 derived one: a
    # task whose final slice's pull request has merged but whose own
    # `slice land` has not yet run reads as *derivable* to "closed" from
    # anywhere -- correct for a standalone `codev task status`, wrong here,
    # where reporting it early would skip straight past the one
    # recommendation this position exists to give: run `slice land` itself.
    # `_github_position` below already answers this case correctly by
    # checking GitHub directly, once actually reached.
    raw_status = task.log_records(resolved, target=target)["status"]
    if raw_status != "in_progress":
        return NextAction(
            position=f"task closed ({raw_status})",
            recommendation="start the next task",
            reason=f"task {resolved!r} is closed, nothing further is tracked",
            task_id=resolved,
            branch=branch,
        )

    head = git_ops.head_for_check(resolved, target=target)
    result = task.check(resolved, head, target=target)
    slice_id = task.current_slice(resolved, target=target)
    final = task.is_final_slice(resolved, slice_id, target=target)

    # Ask GitHub for any position where a pull request could already exist,
    # not only the two reasons that happen to imply human review. Restricting
    # it to those meant a merged slice sitting at `ok_ready_for_pr` was told
    # to open a pull request it had already merged -- observed on `main`
    # minutes after this module's own measure landed.
    if check_github and not result.reason.startswith("stop_"):
        github = _github_position(
            resolved, branch, slice_id, final, result.reason, target=target
        )
        if github is not None:
            return github

    if result.reason == "ok_waiting_on_reviewer":
        inner = _inner_loop_position(resolved, branch, slice_id, target=target)
        if inner is not None:
            return inner

    if result.reason == "ok_ready_for_pr":
        gated = _auto_open_pr_position(resolved, branch, slice_id, target=target)
        if gated is not None:
            return gated

    routing = _BY_CHECK_REASON[result.reason]
    return NextAction(
        position=f"{state['current_phase']} phase, round {state['current_round']}",
        recommendation=routing.recommendation,
        reason=routing.reason,
        command=routing.command,
        task_id=resolved,
        branch=branch,
        slice_id=slice_id,
        check_reason=result.reason,
        blocked=routing.blocked,
        options=routing.options,
    )


def _inner_loop_position(
    task_id: str, branch: str, slice_id: str, *, target: Path
) -> NextAction | None:
    """Split `ok_waiting_on_reviewer` into the three states it conflates.

    `task.check` cannot tell a freshly opened round from one whose builder
    has already reported -- both have no reviewer verdict -- so the single
    routing entry recommended dispatching the reviewer in every case,
    including before any work existed. Naming the wrong actor is worse than
    naming none: an agent that follows it reviews an empty diff.

    The two facts that separate them are local and cheap: whether this
    slice's current round has a builder receipt, and whether the worktree
    holds uncommitted work. Returns None when the recorded case applies, so
    the routing table stays the single description of it.
    """
    state = task.log_records(task_id, target=target)
    current = state["rounds"][-1]
    if current.get("builder") is not None:
        return None

    position = f"{current['phase']} phase, round {state['current_round']}"
    if git_ops.dirty_product_paths(target=target):
        return NextAction(
            position=position,
            recommendation="close the builder's round",
            reason=(
                "the worktree holds uncommitted work and this round has no "
                "builder receipt, so the change exists but is not on record"
            ),
            command="codev round close --role builder --evidence <file>",
            task_id=task_id,
            branch=branch,
            slice_id=slice_id,
            check_reason="ok_waiting_on_reviewer",
        )
    return NextAction(
        position=position,
        recommendation="build the slice",
        reason="this round has no builder receipt and the worktree is clean, "
        "so no work has been done for it yet",
        command="dispatch builder against this slice's plan",
        task_id=task_id,
        branch=branch,
        slice_id=slice_id,
        check_reason="ok_waiting_on_reviewer",
    )


def _auto_open_pr_position(
    task_id: str, branch: str, slice_id: str, *, target: Path
) -> NextAction | None:
    """ADR-0045, Slice 6: `ok_ready_for_pr`'s routing-table recommendation
    ("publish the slice", `codev slice publish`) is only correct when
    `git.auto_open_pr` actually permits opening one -- the branch this
    decision lives in per ADR-0036, not agent-side convention. Returns None
    (falls through to the table entry) when the flag is true, so the
    common case costs nothing beyond one config read."""
    if config.resolve_bool("git.auto_open_pr", target=target):
        return None
    return NextAction(
        position="inner loop satisfied, pull request not yet opened",
        recommendation="ask before opening the pull request",
        reason="git.auto_open_pr is false, so opening one is a decision for "
        "a human, not something to do automatically",
        command=None,
        task_id=task_id,
        branch=branch,
        slice_id=slice_id,
        check_reason="ok_ready_for_pr",
    )


def _github_position(
    task_id: str,
    branch: str,
    slice_id: str,
    final: bool,
    check_reason: str,
    *,
    target: Path,
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
                command="codev slice land",
                task_id=task_id,
                branch=branch,
                slice_id=slice_id,
            )
        return NextAction(
            position="slice merged, more remain",
            recommendation="advance to the next slice",
            reason=(f"slice {slice_id!r} has landed and this task holds a later one"),
            command="codev slice land",
            task_id=task_id,
            branch=branch,
            slice_id=slice_id,
        )
    if state == "OPEN":
        # A pull request is open but the outer loop has not run: the local
        # reason still reads `ok_ready_for_pr`, whose routing would tell an
        # agent to publish a slice that is already published. The step that
        # actually advances the work here is the specialist pass, and nothing
        # named it before -- it is the `dispatch_specialists` row of the
        # recorded coverage baseline.
        if check_reason == "ok_ready_for_pr":
            return NextAction(
                position="pull request open, outer loop not started",
                recommendation="review the pull request with the specialists",
                reason=(
                    "this slice's pull request is open and no outer-phase "
                    "round has been recorded against it"
                ),
                command="dispatch the specialists this slice's diff calls for",
                task_id=task_id,
                branch=branch,
                slice_id=slice_id,
                check_reason=check_reason,
            )
        if not check_reason.startswith("ok_machine_review_complete"):
            return None
        return _open_pull_request_position(task_id, branch, slice_id, target=target)
    return None


def _open_pull_request_position(
    task_id: str, branch: str, slice_id: str, *, target: Path
) -> NextAction:
    """ADR-0037's gate, reported rather than enforced: the machine gates
    being satisfied is not a human approval, and the difference is the whole
    point of the rename in ADR-0037."""
    waiver = task.review_waiver(task_id, target=target)
    if waiver is not None:
        return NextAction(
            position="independent review waived",
            recommendation="merge is the human's decision, then land the slice",
            reason=(
                "no independent review was obtained; a human waived the "
                f"requirement on the record -- {waiver['reason']}"
            ),
            task_id=task_id,
            branch=branch,
            slice_id=slice_id,
            check_reason="ok_human_review_waived",
        )
    owner = task.describe(task_id, target=target).get("owner")
    # `required` travels on the record itself, so the count reported and the
    # count compared against can never diverge.
    approval = git_ops.human_approval(
        branch,
        owner=owner,
        required=git_ops.required_approvals(task_id, target=target),
        target=target,
    )
    if approval is None:
        return NextAction(
            position="pull request open, review state unknown",
            recommendation="check the pull request's reviews by hand",
            reason="GitHub could not be asked whether an approval exists",
            task_id=task_id,
            branch=branch,
            slice_id=slice_id,
            check_reason="ok_machine_review_complete",
        )
    if approval.satisfied:
        return NextAction(
            position="approved by a human",
            recommendation="merge is the human's decision, then land the slice",
            reason=(
                f"{len(approval.approvals)} of {approval.required} required "
                "independent approval(s) recorded: "
                f"{', '.join(approval.approvals)}"
            ),
            task_id=task_id,
            branch=branch,
            slice_id=slice_id,
            check_reason="ok_human_approved",
        )
    if git_ops.pull_request_is_draft(branch, target=target):
        # Nobody can review a draft. Reporting "awaiting human review" here
        # described a wait that nothing would ever end: `mark-ready` is what
        # takes the pull request out of draft and requests the review, and
        # until this, nothing the navigator said ever named it.
        return NextAction(
            position="machine gates satisfied, pull request still a draft",
            recommendation="request human review",
            reason=(
                "every machine gate is satisfied and the pull request is "
                "still a draft, so no review has been asked of anyone"
            ),
            command="codev git mark-ready",
            task_id=task_id,
            branch=branch,
            slice_id=slice_id,
            check_reason="ok_machine_review_complete",
        )
    return NextAction(
        position="pull request open, awaiting human review",
        recommendation="wait for an independent human approval",
        reason=(
            f"{len(approval.approvals)} of {approval.required} required "
            "independent approval(s) recorded; the machine gates being "
            "satisfied is not "
            "an approval, and neither the task owner nor a bot can supply one"
        ),
        task_id=task_id,
        branch=branch,
        slice_id=slice_id,
        check_reason="ok_machine_review_complete",
    )
