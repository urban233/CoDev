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
"""Round-state lifecycle tracking for the builder/reviewer correction loop.

Turns "stop after two correction attempts with the same root cause" from a
sentence an orchestrator has to remember into state a script can check. See
docs/adr/0001-work-lifecycle-invariant.md for why this may run during a build.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast

from codev_workflow.installer import _atomic_write

# v3 (ADR-0023): "work item" is renamed to "task" throughout -- the schema
# key is task_id (was work_item_id) and state lives under .codev/task/ (was
# .codev/work/). v2 files are rejected by _load's version guard below -- no
# migration, same precedent ADR-0003 set for v1->v2.
# v4 (ADR-0035): the slice becomes the unit of execution and a task becomes
# the ordered collection its slices belong to. A task recorded before this
# reads as a task holding exactly one slice whose id is the task id, so no
# file on disk is rewritten and no round's recorded evidence changes.
#
# Slice D-prep-1 read v4 while still writing v3, so that the schema change
# could land on its own and be reverted without leaving a v4 artifact on
# disk. Slice D1 enables the writers: v4 is now what is written, v3 is still
# read and upgraded in memory by `_as_current_schema`, and the strip that
# kept writes at v3 is gone.
ROUND_SCHEMA_VERSION = 4
SUPPORTED_ROUND_SCHEMA_VERSIONS = (3, 4)
TASK_DIR_RELATIVE = PurePosixPath(".codev/task")
ESCALATIONS_FILENAME = "escalations.jsonl"
DEFAULT_INNER_MAX_ROUNDS = 2
DEFAULT_OUTER_MAX_ROUNDS = 2
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

PHASES = ("inner", "outer")

# v2 (ADR-0003): split concurrency out of the combined security/data key so a
# dedicated Concurrency specialist can own it. v1 round-state files use the
# old combined key and are rejected by _load's version guard below -- no
# migration, consistent with this project's pre-1.0 breaking-change policy.
REQUIRED_COVERAGE_DIMENSIONS = (
    "correctness",
    "security_privacy_data_compatibility",
    "concurrency",
    "error_handling",
    "test_quality",
    "architecture_scope",
    "maintainability",
    "rollout",
)

VALID_DECISIONS = (
    "READY_FOR_HUMAN_APPROVAL",
    "READY_FOR_OUTER_LOOP",
    "CHANGES_REQUIRED",
    "BLOCKED_BY_MISSING_EVIDENCE",
)

VALID_EXPANSION_REASONS = ("regression", "newly_discovered_critical")

VALID_TRIAGE_DISPOSITIONS = ("address", "defer")

VALID_ESCALATION_TRIGGERS = (
    "critical_interrupt",
    "stop_drift",
    "stop_repeated_finding",
    "stop_round_cap",
    "stop_scope_expansion",
    "blocked_missing_evidence",
    "human_override_blocking_finding",
)

VALID_OUTCOMES = ("approved", "abandoned", "escalated")

# ADR-0037: `ok_approve` never meant a human approved anything -- it meant the
# machine gates were satisfied. In a tool whose pitch is that generated code
# is not merged as slop, that name invited exactly the conflation the ADR
# exists to prevent, so it says what it means now.
#
# A returned reason is part of the machine contract ADR-0036 made explicit,
# so this is an observable change for anything reading `codev task check
# --json`. For one release each renamed reason also reports its former name,
# so a pinned consumer can see the rename rather than silently stop matching.
# Remove this map, and the `deprecated_reason` field it feeds, in the release
# after the one that introduces it.
DEPRECATED_REASON_ALIASES = {
    "ok_machine_review_complete": "ok_approve",
    "ok_machine_review_complete_with_deferrals": "ok_approve_with_deferrals",
}


def deprecated_reason_for(reason: str) -> str | None:
    """The former name of a renamed `check` reason, or None for every reason
    that was never renamed."""
    return DEPRECATED_REASON_ALIASES.get(reason)


VALID_ENTRY_MODES = ("takeover", "direct-review")

# ADR-0038: how a slice gets built. `pair` keeps the work in the developer's
# own session -- the loop does not dispatch `builder` -- but records the same
# rounds, runs the same reviewer, and lands the same evidence. Pair mode is a
# work style the loop supports, not an exit from it: if it fell outside the
# state machine, the work a developer cares most about would be the work
# carrying no record.
VALID_WORK_STYLES = ("pair", "delegate")
DEFAULT_WORK_STYLE = "delegate"

# ADR-0018: the outer loop's five specialist reviewers, by name -- reused to
# validate a round's optional `specialist_selection` audit record.
SPECIALIST_NAMES = (
    "correctness-tests-specialist",
    "security-data-specialist",
    "concurrency-specialist",
    "architecture-maintainability-specialist",
    "rollout-specialist",
)


class TaskError(Exception):
    """Raised for invalid task state or lifecycle transitions."""


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    reason: str
    message: str


def load_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TaskError(f"cannot read {path}: {error}") from error


def _validate_id(task_id: str) -> None:
    if not _ID_PATTERN.match(task_id):
        raise TaskError(
            f"invalid task id {task_id!r}; use letters, digits, '.', '_', '-'"
        )


def _task_dir(target: Path, task_id: str) -> Path:
    _validate_id(task_id)
    return target / Path(TASK_DIR_RELATIVE.as_posix()) / task_id


def _task_path(target: Path, task_id: str) -> Path:
    return _task_dir(target, task_id) / "round-state.json"


def _load(task_id: str, *, target: Path) -> dict[str, Any]:
    path = _task_path(target, task_id)
    if not path.exists():
        raise TaskError(f"no task {task_id!r} at {path}")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TaskError(f"cannot read {path}: {error}") from error
    if (
        not isinstance(state, dict)
        or state.get("round_schema_version") not in SUPPORTED_ROUND_SCHEMA_VERSIONS
    ):
        raise TaskError(
            f"{path} has an unsupported or invalid round schema; "
            "install a compatible CoDev version"
        )
    return _as_current_schema(state)


def _as_current_schema(state: dict[str, Any]) -> dict[str, Any]:
    """Present a v3 document in v4 shape (ADR-0035): a task holding exactly
    one slice, whose id is the task id, that every recorded round belongs to.

    A v4 document is returned untouched -- its `slices` list and per-round
    `slice_id` are authoritative, and defaulting them would silently
    reassign rounds that belong to a later slice.

    The upgraded state is marked v4, so the next ordinary write persists it.
    Without that, a rewritten legacy document would claim version 3 while
    carrying v4 fields -- a shape no reader should ever have to interpret."""
    if state["round_schema_version"] == ROUND_SCHEMA_VERSION:
        # `current_slice` arrived after the first v4 writes, so default it
        # from the newest round rather than assuming the first slice.
        if "current_slice" not in state:
            state["current_slice"] = state["rounds"][-1]["slice_id"]
        return state
    task_id = state["task_id"]
    state["slices"] = [task_id]
    for round_entry in state["rounds"]:
        round_entry["slice_id"] = task_id
    state["current_slice"] = task_id
    state["round_schema_version"] = ROUND_SCHEMA_VERSION
    return state


def current_slice_id(state: dict[str, Any]) -> str:
    """The slice new rounds belong to.

    Slice D1 returned the *last* slice the task held, which was correct only
    while every task held exactly one. Once a task holds several, the slice
    being worked is tracked explicitly: a round opened after a later slice
    exists must not silently attach to that later slice."""
    current: str = state["current_slice"]
    return current


def _save(task_id: str, state: dict[str, Any], *, target: Path) -> None:
    path = _task_path(target, task_id)
    content = (json.dumps(state, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write(path, content)


def _commit_bookkeeping(task_id: str, *, target: Path, defer: bool) -> None:
    """Best-effort auto-commit for a state-mutating write this module just
    made (ADR-0045), routed through `git_ops._maybe_commit_bookkeeping`.

    Imported lazily: `git_ops` already imports this module at load time
    (it calls back into several read-only `task` functions), so importing
    it back here at module scope would be a real circular import. By the
    time any of the functions below actually run, both modules have long
    since finished loading -- the same precedent `eval.py`'s own lazy
    import of `eval_checks` already uses in this codebase.
    """
    from codev_workflow import git_ops

    git_ops._maybe_commit_bookkeeping(task_id, target=target, defer=defer)


def _ensure_in_progress(state: dict[str, Any]) -> None:
    if state["status"] != "in_progress":
        raise TaskError(f"task is {state['status']!r}, not in_progress")


def _normalize_slices(task_id: str, slices: list[str] | None) -> list[str]:
    """The ordered slice list a task holds. Omitting it means the task holds
    exactly one slice, named for the task itself -- the degenerate case
    ADR-0035 names, not the normal shape."""
    if slices is None:
        return [task_id]
    if not slices:
        raise TaskError("slices must name at least one slice")
    seen = set()
    for slice_id in slices:
        _validate_id(slice_id)
        if slice_id in seen:
            raise TaskError(f"duplicate slice id: {slice_id!r}")
        seen.add(slice_id)
    return list(slices)


def _normalize_max_rounds(max_rounds: int | dict[str, int] | None) -> dict[str, int]:
    if max_rounds is None:
        return {"inner": DEFAULT_INNER_MAX_ROUNDS, "outer": DEFAULT_OUTER_MAX_ROUNDS}
    if isinstance(max_rounds, bool):
        raise TaskError(
            "max_rounds must be an int or a {'inner': int, 'outer': int} dict"
        )
    if isinstance(max_rounds, int):
        if max_rounds < 1:
            raise TaskError("max_rounds must be at least 1")
        return {"inner": max_rounds, "outer": max_rounds}
    if isinstance(max_rounds, dict):
        missing = [phase for phase in PHASES if phase not in max_rounds]
        if missing:
            raise TaskError(f"max_rounds is missing phase(s): {', '.join(missing)}")
        extra = sorted(set(max_rounds) - set(PHASES))
        if extra:
            raise TaskError(f"max_rounds has unknown phase(s): {', '.join(extra)}")
        for phase in PHASES:
            value = max_rounds[phase]
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise TaskError(f"max_rounds[{phase!r}] must be an integer >= 1")
        return {phase: max_rounds[phase] for phase in PHASES}
    raise TaskError("max_rounds must be an int or a {'inner': int, 'outer': int} dict")


def _validate_optional_text(field_name: str, value: str | None) -> None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise TaskError(f"{field_name} must be non-empty text when provided")


def _validate_required_text(field_name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise TaskError(f"{field_name} must be non-empty text")


def start(
    task_id: str,
    base_snapshot: str,
    *,
    target: Path,
    max_rounds: int | dict[str, int] | None = None,
    link_ref: str | None = None,
    summary: str | None = None,
    description: str | None = None,
    owner: str | None = None,
    entry: str | None = None,
    slices: list[str] | None = None,
    reviewer: str | None = None,
    pair_slices: list[str] | None = None,
) -> Path:
    resolved_max_rounds = _normalize_max_rounds(max_rounds)
    resolved_slices = _normalize_slices(task_id, slices)
    styles = {slice_id: DEFAULT_WORK_STYLE for slice_id in resolved_slices}
    for slice_id in pair_slices or []:
        if slice_id not in styles:
            raise TaskError(
                f"cannot mark {slice_id!r} as pair work: this task holds "
                f"{resolved_slices}"
            )
        styles[slice_id] = "pair"
    _validate_optional_text("link_ref", link_ref)
    _validate_optional_text("summary", summary)
    _validate_optional_text("description", description)
    _validate_optional_text("owner", owner)
    _validate_optional_text("reviewer", reviewer)
    if reviewer is not None and owner is not None and reviewer == owner:
        raise TaskError(
            "the independent reviewer must not be the task owner (ADR-0037): "
            f"both resolve to {owner!r}"
        )
    if entry is not None and entry not in VALID_ENTRY_MODES:
        raise TaskError(
            f"entry must be null or one of {VALID_ENTRY_MODES}, got {entry!r}"
        )
    path = _task_path(target, task_id)
    if path.exists():
        raise TaskError(
            f"task {task_id!r} already exists at {path}; to continue "
            "it (after a close, a round-cap stop, or drift) use `codev task "
            "reopen`, not `start`"
        )
    # direct-review has nothing for the inner loop to do -- round 1 opens
    # straight into the outer phase so the first `codev task record` lands on
    # it directly, instead of the inner-to-outer transition `_round_slot`
    # normally requires a READY_FOR_OUTER_LOOP decision to create.
    initial_phase = "outer" if entry == "direct-review" else "inner"
    state: dict[str, Any] = {
        "round_schema_version": ROUND_SCHEMA_VERSION,
        "task_id": task_id,
        "base_snapshot": base_snapshot,
        "max_rounds": resolved_max_rounds,
        "current_round": 1,
        # ADR-0035: a task holds an ordered list of slices, declared from the
        # accepted plan's slice list. A change that genuinely fits in one
        # pull request is a task holding exactly one slice.
        "slices": resolved_slices,
        "slice_styles": styles,
        "current_slice": resolved_slices[0],
        "rounds": [
            {
                "round": 1,
                "phase": initial_phase,
                "slice_id": resolved_slices[0],
                "builder": None,
                "reviewer": None,
            }
        ],
        "status": "in_progress",
        "link_ref": link_ref,
        "summary": summary,
        "description": description,
        "owner": owner,
        # ADR-0037: the task owns its independent reviewer, and a slice
        # inherits it. The owner is the author of the change however little
        # of it they typed, so the two must differ.
        "reviewer": reviewer,
        "entry": entry,
    }
    _save(task_id, state, target=target)
    return path


def _phase_round_count(rounds: list[dict[str, Any]], phase: str) -> int:
    return sum(1 for round_entry in rounds if round_entry["phase"] == phase)


def _round_slot(state: dict[str, Any], round_number: int) -> dict[str, Any]:
    rounds: list[dict[str, Any]] = state["rounds"]
    for round_entry in rounds:
        if round_entry["round"] == round_number:
            return round_entry

    if round_number != len(rounds) + 1:
        raise TaskError(
            f"cannot open round {round_number}: expected round {len(rounds) + 1}"
        )
    previous = rounds[-1]
    previous_reviewer = previous["reviewer"]
    if previous_reviewer is None:
        raise TaskError(
            f"cannot open round {round_number}: round {previous['round']} has no "
            "reviewer decision yet"
        )
    previous_decision = previous_reviewer["decision"]
    if previous_decision == "CHANGES_REQUIRED":
        phase = previous["phase"]
        if phase == "outer" and previous.get("triage") is None:
            raise TaskError(
                f"cannot open round {round_number}: round {previous['round']} has "
                "no recorded triage yet"
            )
    elif previous_decision == "READY_FOR_OUTER_LOOP":
        if previous["phase"] != "inner":
            raise TaskError(
                f"cannot open round {round_number}: READY_FOR_OUTER_LOOP is only a "
                "valid transition from the inner phase"
            )
        phase = "outer"
    else:
        raise TaskError(
            f"cannot open round {round_number}: round {previous['round']} decision "
            f"{previous_decision!r} does not permit opening a new round"
        )

    if _phase_round_count(rounds, phase) + 1 > state["max_rounds"][phase]:
        raise TaskError(
            f"cannot open round {round_number}: max_rounds for phase {phase!r} is "
            f"{state['max_rounds'][phase]}; a human may continue this item with "
            "`codev task reopen`, optionally raising the cap"
        )
    new_round: dict[str, Any] = {
        "round": round_number,
        "phase": phase,
        "slice_id": current_slice_id(state),
        "builder": None,
        "reviewer": None,
    }
    rounds.append(new_round)
    state["current_round"] = round_number
    return new_round


def _validate_findings(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise TaskError("findings must be a JSON array")
    validated: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise TaskError(f"finding[{index}] must be a JSON object")
        finding_id = item.get("id")
        if not isinstance(finding_id, str) or not finding_id:
            raise TaskError(f"finding[{index}] needs a non-empty id")
        if finding_id in seen_ids:
            raise TaskError(f"duplicate finding id: {finding_id}")
        seen_ids.add(finding_id)
        for field_name in ("location", "category", "summary"):
            value = item.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise TaskError(
                    f"finding {finding_id!r}: {field_name} must be non-empty text"
                )
        if not isinstance(item.get("blocking"), bool):
            raise TaskError(f"finding {finding_id!r}: blocking must be true or false")
        if not isinstance(item.get("rank"), int):
            raise TaskError(f"finding {finding_id!r}: rank must be an integer")
        expansion_reason = item.get("expansion_reason")
        if (
            expansion_reason is not None
            and expansion_reason not in VALID_EXPANSION_REASONS
        ):
            raise TaskError(
                f"finding {finding_id!r}: expansion_reason must be null or one of "
                f"{VALID_EXPANSION_REASONS}"
            )
        validated.append(
            {
                "id": finding_id,
                "location": item["location"],
                "category": item["category"],
                "blocking": item["blocking"],
                "rank": item["rank"],
                "summary": item["summary"],
                "expansion_reason": expansion_reason,
            }
        )
    return validated


def _validate_coverage(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise TaskError("coverage must be a JSON object")
    validated: dict[str, Any] = {}
    for dimension, entry in raw.items():
        if dimension not in REQUIRED_COVERAGE_DIMENSIONS:
            raise TaskError(f"unknown coverage dimension: {dimension!r}")
        if not isinstance(entry, dict):
            raise TaskError(f"coverage[{dimension!r}] must be a JSON object")
        passed = entry.get("passed")
        evidence = entry.get("evidence")
        if not isinstance(passed, bool):
            raise TaskError(f"coverage[{dimension!r}].passed must be true or false")
        if not isinstance(evidence, str) or not evidence.strip():
            raise TaskError(f"coverage[{dimension!r}].evidence must be non-empty text")
        validated[dimension] = {"passed": passed, "evidence": evidence}
    return validated


def _validate_specialist_selection(raw: Any) -> dict[str, Any]:
    """ADR-0018: an audit record of which outer-loop specialists actually
    ran this round -- `specialists` may be empty (a comment-sourced entry,
    ADR-0010, dispatches none of the five), but every named entry must be a
    real specialist, named at most once."""
    if not isinstance(raw, dict):
        raise TaskError("specialist_selection must be a JSON object")
    specialists = raw.get("specialists")
    if not isinstance(specialists, list) or not all(
        isinstance(name, str) for name in specialists
    ):
        raise TaskError("specialist_selection.specialists must be a list of strings")
    unknown = [name for name in specialists if name not in SPECIALIST_NAMES]
    if unknown:
        raise TaskError(f"specialist_selection names unknown specialist(s): {unknown}")
    if len(set(specialists)) != len(specialists):
        raise TaskError("specialist_selection.specialists must not repeat a name")
    return {"specialists": list(specialists)}


def record_builder(
    task_id: str,
    round_number: int,
    head_snapshot: str,
    evidence: Any,
    *,
    target: Path,
    defer: bool = False,
) -> None:
    state = _load(task_id, target=target)
    _ensure_in_progress(state)
    if not isinstance(evidence, dict):
        raise TaskError("builder evidence must be a JSON object")
    round_entry = _round_slot(state, round_number)
    if round_entry["builder"] is not None:
        raise TaskError(
            f"round {round_number} already has a recorded builder entry; to "
            "record a correction, target a new round instead -- the next "
            "sequential round, or `codev task reopen` if this item is in a "
            "terminal state"
        )
    round_entry["builder"] = {"head_snapshot": head_snapshot, "evidence": evidence}
    _save(task_id, state, target=target)
    _commit_bookkeeping(task_id, target=target, defer=defer)


def record_reviewer(
    task_id: str,
    round_number: int,
    head_snapshot: str,
    findings: Any,
    coverage: Any,
    decision: str,
    *,
    target: Path,
    specialist_selection: Any = None,
    defer: bool = False,
) -> None:
    if decision not in VALID_DECISIONS:
        raise TaskError(
            f"invalid decision {decision!r}; expected one of {VALID_DECISIONS}"
        )
    state = _load(task_id, target=target)
    _ensure_in_progress(state)
    round_entry = _round_slot(state, round_number)
    if decision == "READY_FOR_OUTER_LOOP" and round_entry["phase"] != "inner":
        # ADR-0017: this decision means exactly one thing -- "hand off to the
        # outer loop" -- and only means it coming from an inner-phase round.
        # Recording it on a round that is already `"outer"` (reachable after
        # a human-authorized `reopen` back into the outer phase) produces a
        # state `_round_slot` will then refuse to build on: the very next
        # attempt to open a round raises "READY_FOR_OUTER_LOOP is only a
        # valid transition from the inner phase". Reject it here, at the
        # write site, instead of letting that corrupted state be recorded at
        # all -- see `check()`'s `ok_outer_loop_needs_reopen` for the
        # matching upfront signal, and the escaped incident this closes.
        raise TaskError(
            f"round {round_number} is already in the outer phase; "
            "READY_FOR_OUTER_LOOP only means an inner-phase hand-off to the "
            "outer loop -- record READY_FOR_HUMAN_APPROVAL, "
            "CHANGES_REQUIRED, or BLOCKED_BY_MISSING_EVIDENCE instead"
        )
    if round_entry["reviewer"] is not None:
        raise TaskError(
            f"round {round_number} already has a recorded reviewer entry; to "
            "re-review after a correction, record a new round instead -- the "
            "next sequential round, or `codev task reopen` if this item is "
            "in a terminal state"
        )
    reviewer_entry: dict[str, Any] = {
        "head_snapshot": head_snapshot,
        "findings": _validate_findings(findings),
        "coverage": _validate_coverage(coverage) if coverage else {},
        "decision": decision,
    }
    if specialist_selection is not None:
        reviewer_entry["specialist_selection"] = _validate_specialist_selection(
            specialist_selection
        )
    round_entry["reviewer"] = reviewer_entry
    _save(task_id, state, target=target)
    _commit_bookkeeping(task_id, target=target, defer=defer)


def _validate_triage(raw: Any, findings: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise TaskError("triage must be a JSON object")
    dispositions = raw.get("dispositions")
    if not isinstance(dispositions, dict):
        raise TaskError("triage.dispositions must be a JSON object")
    all_ids = {finding["id"] for finding in findings}
    blocking_ids = {finding["id"] for finding in findings if finding["blocking"]}
    validated: dict[str, dict[str, Any]] = {}
    for finding_id, entry in dispositions.items():
        if finding_id not in all_ids:
            raise TaskError(f"triage references unknown finding id: {finding_id!r}")
        if not isinstance(entry, dict):
            raise TaskError(f"triage[{finding_id!r}] must be a JSON object")
        disposition = entry.get("disposition")
        if disposition not in VALID_TRIAGE_DISPOSITIONS:
            raise TaskError(
                f"triage[{finding_id!r}].disposition must be one of "
                f"{VALID_TRIAGE_DISPOSITIONS}"
            )
        override_reason = entry.get("override_reason")
        if override_reason is not None and not isinstance(override_reason, str):
            raise TaskError(f"triage[{finding_id!r}].override_reason must be text")
        if (
            disposition == "defer"
            and finding_id in blocking_ids
            and not (isinstance(override_reason, str) and override_reason.strip())
        ):
            raise TaskError(
                f"triage[{finding_id!r}]: deferring a blocking finding requires a "
                "non-empty override_reason"
            )
        validated[finding_id] = {
            "disposition": disposition,
            "override_reason": override_reason,
        }
    missing = blocking_ids - set(validated)
    if missing:
        raise TaskError(
            "triage is missing a disposition for blocking finding(s): "
            + ", ".join(sorted(missing))
        )
    return {"dispositions": validated}


def record_triage(
    task_id: str,
    round_number: int,
    triage: Any,
    *,
    target: Path,
    by: str | None = None,
    defer: bool = False,
) -> None:
    _validate_optional_text("by", by)
    state = _load(task_id, target=target)
    _ensure_in_progress(state)
    round_entry = _round_slot(state, round_number)
    if round_entry["phase"] != "outer":
        raise TaskError(
            f"round {round_number} is not in the outer phase; triage does not apply"
        )
    reviewer = round_entry["reviewer"]
    if reviewer is None:
        raise TaskError(f"round {round_number} has no recorded reviewer findings yet")
    if reviewer["decision"] != "CHANGES_REQUIRED":
        raise TaskError(
            f"round {round_number} decision is not CHANGES_REQUIRED; nothing to triage"
        )
    if round_entry.get("triage") is not None:
        raise TaskError(f"round {round_number} already has a recorded triage")
    validated = _validate_triage(triage, reviewer["findings"])
    validated["by"] = by
    round_entry["triage"] = validated
    _save(task_id, state, target=target)
    _commit_bookkeeping(task_id, target=target, defer=defer)


def _triage_owner_note(owner: str | None, triage: dict[str, Any] | None) -> str | None:
    if not owner or triage is None:
        return None
    by = triage.get("by")
    if by and by == owner:
        return f"note: {owner} both owns this task and triaged this round"
    return None


def triage_note(task_id: str, *, target: Path) -> str | None:
    """The same-person owner/triager note for the task's latest round.

    Informational only -- callers print this alongside `check`'s result, it
    is never a new check() outcome and never affects the exit code.
    """
    state = _load(task_id, target=target)
    latest = state["rounds"][-1]
    return _triage_owner_note(state.get("owner"), latest.get("triage"))


def _blocking_set(round_entry: dict[str, Any]) -> set[tuple[str, str]]:
    reviewer = round_entry["reviewer"]
    if reviewer is None:
        return set()
    return {
        (finding["location"], finding["category"])
        for finding in reviewer["findings"]
        if finding["blocking"]
    }


def _triaged_finding_ids(round_entry: dict[str, Any]) -> set[str]:
    triage = round_entry.get("triage")
    if triage is None:
        return set()
    return set(triage["dispositions"])


def _find_repeated_blocking_finding(
    rounds: list[dict[str, Any]],
) -> dict[str, Any] | None:
    latest = rounds[-1]
    if latest["reviewer"] is None:
        return None
    phase = latest["phase"]
    seen: set[tuple[str, str]] = set()
    for round_entry in rounds[:-1]:
        if round_entry["phase"] != phase:
            continue
        seen |= _blocking_set(round_entry)
    # A finding the human has already triaged on this round -- address or
    # defer, either way an explicit decision -- is resolved, not repeated:
    # otherwise a deferred finding would keep tripping this check forever,
    # since it necessarily also appeared blocking in an earlier round.
    triaged = _triaged_finding_ids(latest)
    latest_findings = cast(list[dict[str, Any]], latest["reviewer"]["findings"])
    for finding in latest_findings:
        if finding["id"] in triaged:
            continue
        if finding["blocking"] and (finding["location"], finding["category"]) in seen:
            return finding
    return None


def _find_scope_expansion(rounds: list[dict[str, Any]]) -> dict[str, Any] | None:
    latest = rounds[-1]
    if latest["reviewer"] is None:
        return None
    phase = latest["phase"]
    phase_rounds = [
        round_entry for round_entry in rounds if round_entry["phase"] == phase
    ]
    if len(phase_rounds) < 2 or phase_rounds[0] is latest:
        return None
    baseline = _blocking_set(phase_rounds[0])
    # Same reasoning as _find_repeated_blocking_finding: a triaged finding
    # (address or defer) has already had its one required human look: this
    # guard exists to force that look, not to survive it forever.
    triaged = _triaged_finding_ids(latest)
    latest_findings = cast(list[dict[str, Any]], latest["reviewer"]["findings"])
    for finding in latest_findings:
        if not finding["blocking"]:
            continue
        if finding["id"] in triaged:
            continue
        if (finding["location"], finding["category"]) in baseline:
            continue
        if finding.get("expansion_reason") is not None:
            continue
        return finding
    return None


def _all_blocking_deferred(
    findings: list[dict[str, Any]], triage: dict[str, Any]
) -> bool:
    dispositions = triage["dispositions"]
    return all(
        dispositions[finding["id"]]["disposition"] == "defer"
        for finding in findings
        if finding["blocking"]
    )


def _incomplete_coverage(coverage: dict[str, Any]) -> list[str]:
    missing = []
    for dimension in REQUIRED_COVERAGE_DIMENSIONS:
        entry = coverage.get(dimension)
        if entry is None:
            missing.append(f"{dimension}: missing")
        elif entry.get("waived"):
            continue
        elif not entry.get("passed"):
            missing.append(f"{dimension}: not passed")
    return missing


def _effective_coverage(state: dict[str, Any]) -> dict[str, Any]:
    """Coverage as of the latest round, filled in from history.

    A round only needs to record the dimensions it actually re-verified --
    the recording agent must not hand-assemble a merged manifest from prior
    rounds' prose, a step earlier revisions of this workflow required and
    that turned out to be exactly the kind of bookkeeping agents get wrong
    under load. For every dimension the latest round's own coverage is
    silent on, this walks the round history in order and keeps the most
    recent verdict recorded for it, including a `reopen` recovery's
    surviving prior rounds. A later round's entry for a dimension always
    wins over an earlier one, so a dimension that regresses stays failing
    until something re-verifies it -- carry-forward never resurrects a
    stale pass.

    A human-authorized waiver (`waive()`) participates in the same
    round-ordered merge, interleaved by the round it was recorded at: a
    later round's real verdict for a dimension -- pass or fail -- always
    overrides an earlier waiver, and a later waiver can just as validly
    override an earlier failing verdict (a human revisiting a finding and
    deciding it doesn't matter). Within the same round, an actual recorded
    verdict wins over a waiver for that same dimension, on the assumption
    that real verification is always more authoritative than a waiver
    recorded in passing at that round's start.
    """
    rounds: list[dict[str, Any]] = state["rounds"]
    waivers_by_round: dict[int, list[dict[str, Any]]] = {}
    for waiver in state.get("coverage_waivers", []):
        waivers_by_round.setdefault(waiver["round"], []).append(waiver)

    round_numbers = sorted(
        {round_entry["round"] for round_entry in rounds} | set(waivers_by_round)
    )
    rounds_by_number = {round_entry["round"]: round_entry for round_entry in rounds}

    merged: dict[str, Any] = {}
    for round_number in round_numbers:
        for waiver in waivers_by_round.get(round_number, []):
            merged[waiver["dimension"]] = {
                "waived": True,
                "reason": waiver["reason"],
                "by": waiver.get("by"),
            }
        round_entry = rounds_by_number.get(round_number)
        reviewer = round_entry.get("reviewer") if round_entry else None
        if reviewer is not None:
            merged.update(reviewer["coverage"])
    return merged


def check(task_id: str, head: str, *, target: Path) -> CheckResult:
    state = _load(task_id, target=target)
    rounds: list[dict[str, Any]] = state["rounds"]
    latest = rounds[-1]

    if (
        state.get("entry") == "direct-review"
        and latest["builder"] is None
        and latest["reviewer"] is None
    ):
        return CheckResult(
            True,
            "ok_ready_for_pr",
            "direct-review entry: human-authored work is already complete, no "
            "inner-loop round is required before opening a pull request",
        )

    if latest["reviewer"] is not None:
        expected_head = latest["reviewer"]["head_snapshot"]
    elif latest["builder"] is not None:
        expected_head = latest["builder"]["head_snapshot"]
    else:
        expected_head = state["base_snapshot"]
    if head != expected_head:
        return CheckResult(
            False,
            "stop_drift",
            f"round {latest['round']}: expected head {expected_head}, got {head}; "
            "code changed outside the tracked builder/reviewer flow",
        )

    reviewer = latest["reviewer"]
    if reviewer is None:
        return CheckResult(
            True,
            "ok_waiting_on_reviewer",
            f"round {latest['round']}: no reviewer verdict recorded yet",
        )

    decision = reviewer["decision"]
    if decision == "CHANGES_REQUIRED":
        phase = latest["phase"]
        triage_hint = (
            " -- codev task triage may address or defer it (with a reason) to "
            "resolve this"
            if phase == "outer"
            else ""
        )
        expansion = _find_scope_expansion(rounds)
        if expansion is not None:
            return CheckResult(
                False,
                "stop_scope_expansion",
                f"finding at {expansion['location']} ({expansion['category']}) was "
                "not raised in this phase's first round and carries no "
                f"expansion_reason: treat as scope creep, escalate to the human"
                f"{triage_hint}",
            )
        repeat = _find_repeated_blocking_finding(rounds)
        if repeat is not None:
            return CheckResult(
                False,
                "stop_repeated_finding",
                f"finding at {repeat['location']} ({repeat['category']}) was already "
                "raised as blocking in an earlier round: same root cause, escalate "
                f"to the human{triage_hint}",
            )
        if phase == "outer":
            triage = latest.get("triage")
            if triage is None:
                return CheckResult(
                    True,
                    "ok_waiting_on_triage",
                    f"round {latest['round']}: findings recorded, waiting on the "
                    "human to triage which are addressed this round",
                )
            if _all_blocking_deferred(reviewer["findings"], triage):
                # Every blocking finding was explicitly deferred -- nothing is
                # left for a builder to do, so there is nothing to spend the
                # round cap on. The round's own decision stays CHANGES_REQUIRED
                # (an honest record of what the specialists found); this is a
                # distinct, later verdict about what happens next, exactly like
                # every other CHANGES_REQUIRED sub-case above.
                missing = _incomplete_coverage(_effective_coverage(state))
                if missing:
                    return CheckResult(
                        False,
                        "stop_incomplete_coverage",
                        "coverage manifest incomplete or failing: "
                        + ", ".join(missing),
                    )
                return CheckResult(
                    True,
                    "ok_machine_review_complete_with_deferrals",
                    f"round {latest['round']}: every blocking finding was triaged "
                    "as defer, nothing left to build -- ready to present to the "
                    "human with the deferred findings on record",
                )
        phase_round_count = _phase_round_count(rounds, phase)
        if phase_round_count >= state["max_rounds"][phase]:
            return CheckResult(
                False,
                "stop_round_cap",
                f"round {phase_round_count} of {state['max_rounds'][phase]} for "
                f"phase {phase!r}: stop and escalate to the human",
            )
        return CheckResult(
            True, "ok_continue", f"round {latest['round'] + 1} may begin"
        )

    if decision == "READY_FOR_OUTER_LOOP":
        if latest["phase"] == "outer":
            # ADR-0017: defense-in-depth for a round-state.json already in
            # this shape (record_reviewer now refuses to create it fresh).
            # This is not the normal inner-to-outer hand-off signal reused --
            # it is a distinct case that needs a distinct answer: recording
            # another round here will hit `_round_slot`'s "READY_FOR_OUTER_
            # LOOP is only a valid transition from the inner phase" raise.
            return CheckResult(
                True,
                "ok_outer_loop_needs_reopen",
                f"round {latest['round']}: already in the outer phase with "
                "READY_FOR_OUTER_LOOP recorded -- confirm with the human "
                "that re-entering the outer loop is actually intended (not "
                "unexamined drift), then run `codev task reopen` before "
                "dispatching specialists or recording anything; a further "
                "round cannot be recorded here as-is",
            )
        return CheckResult(
            True,
            "ok_ready_for_pr",
            f"round {latest['round']}: inner loop satisfied, ready to open a pull "
            "request",
        )

    if decision == "READY_FOR_HUMAN_APPROVAL":
        missing = _incomplete_coverage(_effective_coverage(state))
        if missing:
            return CheckResult(
                False,
                "stop_incomplete_coverage",
                "coverage manifest incomplete or failing: " + ", ".join(missing),
            )
        return CheckResult(
            True, "ok_machine_review_complete", "ready to present to the human"
        )

    return CheckResult(True, "ok_blocked_missing_evidence", decision)


def close(task_id: str, outcome: str, *, target: Path, defer: bool = False) -> None:
    if outcome not in VALID_OUTCOMES:
        raise TaskError(
            f"invalid outcome {outcome!r}; expected one of {VALID_OUTCOMES}"
        )
    state = _load(task_id, target=target)
    _ensure_in_progress(state)
    state["status"] = "closed"
    state["outcome"] = outcome
    _save(task_id, state, target=target)
    _commit_bookkeeping(task_id, target=target, defer=defer)


def reopen(
    task_id: str,
    head: str,
    reason: str,
    *,
    target: Path,
    max_rounds: int | dict[str, int] | None = None,
    by: str | None = None,
    defer: bool = False,
) -> Path:
    """Human-authorized recovery for a task `check` reports as stuck.

    `start` refuses to reuse an id once its state file exists at all, and
    `_round_slot` mechanically refuses to open a round beyond `max_rounds` --
    both correctly protect the normal flow, but together with drift
    detection they leave no path back for a closed item, an exhausted round
    cap, or an approved change committed after the last recorded snapshot
    (a pre-PR audit fix, for example). This is the deliberate escape hatch:
    it works regardless of `status`, never touches a previously recorded
    round's builder/reviewer entry, and only re-baselines `base_snapshot` to
    `head` and appends one fresh, empty round so the ordinary
    builder/reviewer/`codev task record` flow can resume from there. Every
    call is appended to `reopens` so the recovery is as visible as the
    history it continues -- see docs/adr/0007-work-item-recovery.md.

    Callers (agents) must treat this the same as any other hard-to-reverse
    action: only run it on an explicit human decision, never on your own
    initiative because a round looked stuck.
    """
    _validate_required_text("head", head)
    _validate_required_text("reason", reason)
    _validate_optional_text("by", by)
    state = _load(task_id, target=target)

    resolved_max_rounds = state["max_rounds"]
    if max_rounds is not None:
        resolved_max_rounds = _normalize_max_rounds(max_rounds)
        for phase in PHASES:
            done = _phase_round_count(state["rounds"], phase)
            if resolved_max_rounds[phase] < done:
                raise TaskError(
                    f"max_rounds[{phase!r}] ({resolved_max_rounds[phase]}) is "
                    f"below the {done} round(s) already recorded for that phase"
                )

    previous_status = state["status"]
    previous = state["rounds"][-1]
    reviewer = previous["reviewer"]
    if (
        reviewer is not None
        and reviewer["decision"] == "READY_FOR_OUTER_LOOP"
        and previous["phase"] == "inner"
    ):
        next_phase = "outer"
    else:
        next_phase = previous["phase"]

    new_round_number = previous["round"] + 1
    state["rounds"].append(
        {
            "round": new_round_number,
            "phase": next_phase,
            "slice_id": current_slice_id(state),
            "builder": None,
            "reviewer": None,
        }
    )
    state["current_round"] = new_round_number
    state["base_snapshot"] = head
    state["max_rounds"] = resolved_max_rounds
    state["status"] = "in_progress"
    state.pop("outcome", None)
    state.setdefault("reopens", []).append(
        {
            "timestamp": _utc_now_iso(),
            "previous_status": previous_status,
            "from_round": previous["round"],
            "to_round": new_round_number,
            "phase": next_phase,
            "head": head,
            "reason": reason,
            "by": by,
            "max_rounds": resolved_max_rounds,
        }
    )
    path = _task_path(target, task_id)
    _save(task_id, state, target=target)
    _commit_bookkeeping(task_id, target=target, defer=defer)
    return path


def record_restack(
    task_id: str, new_head: str, *, target: Path, by: str | None = None
) -> Path:
    """Reconciles round-state after `codev git restack` rewrites a
    stacked task's own branch history (ADR-0034).

    A rebase changes a commit's identity without changing its tree, so
    the round evidence it affects is still valid -- unlike `reopen`, this
    appends no new round and records no new builder/reviewer verdict; it
    only updates the pointers `check`'s drift comparison reads, so the
    rebase itself does not look like drift. Updates `base_snapshot` and,
    when the current round already recorded a builder or reviewer
    verdict, that verdict's own `head_snapshot` too. Every call is
    appended to `restacks`, mirroring `reopens`' visibility.
    """
    _validate_required_text("new_head", new_head)
    _validate_optional_text("by", by)
    state = _load(task_id, target=target)
    _ensure_in_progress(state)
    previous_base = state["base_snapshot"]
    state["base_snapshot"] = new_head
    latest = state["rounds"][-1]
    if latest["reviewer"] is not None:
        latest["reviewer"]["head_snapshot"] = new_head
    elif latest["builder"] is not None:
        latest["builder"]["head_snapshot"] = new_head
    state.setdefault("restacks", []).append(
        {
            "timestamp": _utc_now_iso(),
            "round": latest["round"],
            "previous_base_snapshot": previous_base,
            "new_head": new_head,
            "by": by,
        }
    )
    path = _task_path(target, task_id)
    _save(task_id, state, target=target)
    return path


def waive(
    task_id: str,
    dimension: str,
    reason: str,
    *,
    target: Path,
    by: str | None = None,
) -> Path:
    """Human-authorized: this coverage dimension will not be run for this
    task, instead of leaving it to eventually be covered by some round.

    Modeled on `reopen`'s append-only pattern, not `record_triage`'s
    single-slot-per-round one -- `waive` is meant to be callable multiple
    times, across different dimensions and different rounds, the same way
    `reopen` is callable multiple times across an item's life.

    Deliberately distinct from a passing coverage entry (no `passed` key):
    `_effective_coverage` folds waivers into the same most-recent-wins merge
    as real coverage verdicts, but `codev task log` and `pr_description()`
    always render a waiver as "waived", never as "passed" -- this system
    never claims something was verified when a human decided not to run it.

    Callers (agents) must treat this the same as any other hard-to-reverse
    scope decision: only run it on an explicit human choice, never on your
    own initiative because a specialist looked skippable.
    """
    if dimension not in REQUIRED_COVERAGE_DIMENSIONS:
        raise TaskError(
            f"unknown coverage dimension: {dimension!r}; expected one of "
            f"{REQUIRED_COVERAGE_DIMENSIONS}"
        )
    _validate_required_text("reason", reason)
    _validate_optional_text("by", by)
    state = _load(task_id, target=target)
    _ensure_in_progress(state)
    state.setdefault("coverage_waivers", []).append(
        {
            "timestamp": _utc_now_iso(),
            "round": state["current_round"],
            "dimension": dimension,
            "reason": reason,
            "by": by,
        }
    )
    path = _task_path(target, task_id)
    _save(task_id, state, target=target)
    return path


def waive_review(
    task_id: str,
    reason: str,
    *,
    target: Path,
    by: str | None = None,
    defer: bool = False,
) -> Path:
    """Human-authorized: this task lands without the independent human
    approval ADR-0037 requires.

    ADR-0037's own Consequences section calls for this: a repository with no
    second engineer -- a solo adopter -- cannot satisfy that gate by
    construction, and must be able to record that it is deliberately
    operating without one rather than silently failing every task.

    Deliberately per-task and reason-bearing rather than a configuration
    flag. A flag is set once and applies silently to every task afterwards,
    which reproduces the reflexive-approval failure ADR-0037 exists to
    prevent, only globally and invisibly. Restating the reason each time is
    the point, not friction to be optimized away.

    Like `waive`, this never claims something happened that did not: the
    navigator reports a distinct state, and the pull-request body says the
    review was waived rather than omitting the line.
    """
    _validate_required_text("reason", reason)
    state = _load(task_id, target=target)
    _ensure_in_progress(state)
    state["review_waiver"] = {
        "reason": reason,
        "by": by,
        "at": _utc_now_iso(),
    }
    _save(task_id, state, target=target)
    _commit_bookkeeping(task_id, target=target, defer=defer)
    return _task_path(target, task_id)


def review_waiver(task_id: str, *, target: Path) -> dict[str, Any] | None:
    """The recorded waiver of independent review, or None."""
    waiver: dict[str, Any] | None = _load(task_id, target=target).get("review_waiver")
    return waiver


def relink(
    task_id: str,
    link_ref: str,
    *,
    target: Path,
    by: str | None = None,
) -> Path:
    """Human-authorized correction of link_ref after `start()` already ran.

    `--github-issue` can only be resolved at `start()` time (ADR-0004), and
    `link_ref` is otherwise write-once for the rest of an item's life -- this
    is the recovery path for the ordinary real-world case where a human
    catches a missing or wrong issue link only after round-state already
    exists (ADR-0020). Modeled on `waive()`'s shape: the previous value is
    never discarded, only superseded, so a correction stays visible in
    `codev task log` instead of silently overwriting history. The very next
    `codev git open-pr`/`mark-ready` call reads `link_ref` fresh through
    `describe()`, so no other code path needs to know a correction happened.
    """
    _validate_required_text("link_ref", link_ref)
    _validate_optional_text("by", by)
    state = _load(task_id, target=target)
    _ensure_in_progress(state)
    previous = state.get("link_ref")
    state["link_ref"] = link_ref
    state.setdefault("link_ref_updates", []).append(
        {
            "timestamp": _utc_now_iso(),
            "previous": previous,
            "new": link_ref,
            "by": by,
        }
    )
    path = _task_path(target, task_id)
    _save(task_id, state, target=target)
    return path


def _derive_status(task_id: str, state: dict[str, Any], *, target: Path) -> str:
    """ADR-0045, Slice 5: a task's own recorded `status` can go stale without
    ever being wrong about anything a human decided -- `slice land` writes
    `"closed"` only after its slice's pull request has already merged, so
    that commit necessarily lands on a branch already past the point anyone
    routinely commits further, and reaching `main` needs a second, separate
    action nobody is obliged to take. This is not a class of drift a repair
    needs to persist to be honest about: whether the task is done is exactly
    as checkable from here as it was from the branch that recorded it.

    Only ever checks GitHub -- a real network call -- for the one case where
    the answer could actually be stale: locally `"in_progress"`, and the
    current slice is the task's last one, so nothing further is expected
    before completion. Every other status (`closed`, or `in_progress` with
    slices still remaining) is trusted as recorded, at zero extra cost.

    Never raises for "no branch recorded yet" -- `describe` is called for a
    task freshly started with `task.start` alone, before `create_branch` has
    ever run (this module's own test suite exercises exactly that), and a
    derived status is a best-effort convenience layered on top of the
    already-durable recorded one, not a new hard requirement callers must
    satisfy.
    """
    raw_status: str = state["status"]
    if raw_status != "in_progress":
        return raw_status
    slice_id: str = state["current_slice"]
    if not is_final_slice(task_id, slice_id, target=target):
        return raw_status
    from codev_workflow import git_ops

    try:
        branch = git_ops.branch_for_slice(task_id, slice_id, target=target)
    except git_ops.GitOpsError:
        return raw_status
    if branch is None:
        return raw_status
    if git_ops.pull_request_state(branch, target=target) == "MERGED":
        return "closed"
    return raw_status


def describe(task_id: str, *, target: Path) -> dict[str, Any]:
    """Cheap and local: never touches GitHub. Used pervasively, including by
    `git_ops`'s own bookkeeping-commit-message builder -- `status` here is
    exactly the recorded value, not `describe_with_live_status`'s derived
    one, so every one of those existing callers stays a local-only read."""
    state = _load(task_id, target=target)
    latest = state["rounds"][-1]
    reviewer = latest["reviewer"]
    return {
        "task_id": state["task_id"],
        "status": state["status"],
        "current_round": state["current_round"],
        "current_phase": latest["phase"],
        "max_rounds": state["max_rounds"],
        "latest_decision": reviewer["decision"] if reviewer is not None else None,
        "link_ref": state.get("link_ref"),
        "summary": state.get("summary"),
        "description": state.get("description"),
        "owner": state.get("owner"),
        "reviewer": state.get("reviewer"),
        "entry": state.get("entry"),
    }


def describe_with_live_status(task_id: str, *, target: Path) -> dict[str, Any]:
    """`describe`, with `status` derived against GitHub when the recorded
    value could actually be stale (ADR-0045, Slice 5) -- for the callers
    that exist specifically to answer "is this task actually done": a
    human or agent checking one task by id, or listing every task. Not for
    internal, high-frequency reads that never asked this question -- see
    `describe`'s own docstring for why those stay local-only."""
    described = describe(task_id, target=target)
    state = _load(task_id, target=target)
    described["status"] = _derive_status(task_id, state, target=target)
    return described


def describe_all(*, target: Path) -> list[dict[str, Any]]:
    """Every task's status report -- with a live-derived `status`
    (ADR-0045, Slice 5), since this function's only callers are `codev
    status` and `codev task status`'s list form, both human/agent-facing
    overviews where a stale `in_progress` count is exactly the failure mode
    worth the extra GitHub reads."""
    root = target / Path(TASK_DIR_RELATIVE.as_posix())
    if not root.exists():
        return []
    results = []
    for entry in sorted(root.iterdir()):
        if (entry / "round-state.json").exists():
            results.append(describe_with_live_status(entry.name, target=target))
    return results


def slice_ids(task_id: str, *, target: Path) -> list[str]:
    """The ordered slice ids this task holds (ADR-0035). A task recorded
    before v4 holds exactly one, named for the task itself."""
    slices: list[str] = list(_load(task_id, target=target)["slices"])
    return slices


def advance_slice(task_id: str, head: str, *, target: Path) -> str:
    """Move this task on to its next slice and open a fresh round against
    `head` (ADR-0035).

    A slice is one pull request's worth of work, so the next one starts from
    where the previous one landed -- the same re-baselining `reopen` does,
    for the same reason: `check`'s drift guard compares against a recorded
    snapshot, and the new slice's work has not happened yet."""
    state = _load(task_id, target=target)
    _ensure_in_progress(state)
    slices: list[str] = state["slices"]
    position = slices.index(state["current_slice"])
    if position + 1 >= len(slices):
        raise TaskError(
            f"task {task_id!r} is on its final slice "
            f"{state['current_slice']!r}; there is no next slice to advance to"
        )
    next_slice = slices[position + 1]
    state["current_slice"] = next_slice
    new_round_number = state["rounds"][-1]["round"] + 1
    state["rounds"].append(
        {
            "round": new_round_number,
            "phase": "inner",
            "slice_id": next_slice,
            "builder": None,
            "reviewer": None,
        }
    )
    state["current_round"] = new_round_number
    state["base_snapshot"] = head
    _save(task_id, state, target=target)
    return next_slice


def describe_base_snapshot(task_id: str, *, target: Path) -> str:
    """The base the task is presently working from. `advance_slice` and
    `reopen` both move it, so this is the current slice's starting point,
    not the branch's."""
    base: str = _load(task_id, target=target)["base_snapshot"]
    return base


def work_style(task_id: str, slice_id: str | None = None, *, target: Path) -> str:
    """How the named slice is built -- `pair` or `delegate` (ADR-0038).
    Defaults to the slice being worked."""
    state = _load(task_id, target=target)
    resolved = slice_id or current_slice_id(state)
    style: str = state.get("slice_styles", {}).get(resolved, DEFAULT_WORK_STYLE)
    return style


def set_work_style(
    task_id: str, slice_id: str | None, style: str, *, target: Path
) -> str:
    """Change a slice's work style while it is still open. ADR-0038 makes
    this changeable mid-slice on purpose: a developer who realises partway
    through that a change needs their hands should not have to leave the
    loop to get that."""
    if style not in VALID_WORK_STYLES:
        raise TaskError(f"style must be one of {VALID_WORK_STYLES}, got {style!r}")
    state = _load(task_id, target=target)
    _ensure_in_progress(state)
    resolved = slice_id or current_slice_id(state)
    if resolved not in state["slices"]:
        raise TaskError(f"task {task_id!r} holds no slice {resolved!r}")
    state.setdefault("slice_styles", {})[resolved] = style
    _save(task_id, state, target=target)
    return resolved


def pause(task_id: str, head: str, reason: str, *, target: Path) -> None:
    """Record that a human interrupted this slice mid-round (ADR-0038).

    Interrupting used to leave files edited, nothing committed, nothing
    recorded, and the next `check` reporting `stop_drift` -- a false report
    about what happened, and the developer's in-progress work losing its
    traceability. Pausing makes the interruption a recorded fact with the
    partial head attached, so `resume` can re-baseline onto it."""
    _validate_required_text("reason", reason)
    state = _load(task_id, target=target)
    _ensure_in_progress(state)
    state["paused"] = {"head": head, "reason": reason, "at": _utc_now_iso()}
    _save(task_id, state, target=target)
    record_escalation(
        task_id,
        "critical_interrupt",
        reason,
        target=target,
        phase=state["rounds"][-1]["phase"],
        round_number=state["current_round"],
    )


def resume(
    task_id: str, head: str, reason: str, *, target: Path, by: str | None = None
) -> str:
    """Re-enter a paused slice in `pair` style, absorbing whatever was
    written by hand while it was paused.

    Raises the round cap for the resumed phase by one, because the round
    this opens is not the failure mode the cap guards against. The cap
    exists to stop the loop churning on the same problem without human
    attention; a pause and resume is *definitionally* human attention --
    the developer took the keyboard, and `pause` recorded a
    `critical_interrupt` with a stated reason to prove it. Spending cap on
    that would stop a developer for something unrelated to their code.

    The cap is raised rather than the round exempted from counting. A
    `counts_toward_cap` flag would make `_phase_round_count` lie about how
    many rounds have happened; raising the cap keeps every round a round and
    leaves the change visible in `reopens` history and `codev task log`.
    """
    state = _load(task_id, target=target)
    if state.get("paused") is None:
        raise TaskError(f"task {task_id!r} is not paused")
    phase = state["rounds"][-1]["phase"]
    raised = dict(state["max_rounds"])
    raised[phase] = raised[phase] + 1
    reopen(task_id, head, reason, target=target, by=by, max_rounds=raised)
    slice_id = set_work_style(task_id, None, "pair", target=target)
    resumed = _load(task_id, target=target)
    resumed.pop("paused", None)
    _save(task_id, resumed, target=target)
    return slice_id


def current_slice(task_id: str, *, target: Path) -> str:
    """The slice this task's most recent round belongs to (ADR-0035)."""
    state = _load(task_id, target=target)
    return current_slice_id(state)


def is_final_slice(task_id: str, slice_id: str, *, target: Path) -> bool:
    """True when `slice_id` is the last slice its task holds, so nothing
    further in this task remains to land.

    This is what decides `Closes #N` against `Part of #N` for a task whose
    work is sliced. An unknown slice id is treated as final rather than
    raising: this backs pull-request body text, and a wrong-but-conservative
    `Closes` is a worse failure than an exception only if it is silent, so
    callers that care check membership themselves."""
    slices = slice_ids(task_id, target=target)
    return not slices or slices[-1] == slice_id


def log_records(task_id: str, *, target: Path) -> dict[str, Any]:
    """The task's full recorded state -- everything `log_text` renders, as
    data. ADR-0036: `codev task log --json` is the machine-readable form of
    an item's whole history, so an agent never parses the rendered text."""
    return _load(task_id, target=target)


def log_text(task_id: str, *, target: Path) -> str:
    state = _load(task_id, target=target)
    lines = [
        f"task {state['task_id']} - {state['status']} "
        f"(round {state['current_round']}/{state['max_rounds']})"
    ]
    summary = state.get("summary")
    if summary:
        lines.append(f"summary: {summary}")
    link_ref = state.get("link_ref")
    if link_ref:
        lines.append(f"link: {link_ref}")
    owner = state.get("owner")
    if owner:
        lines.append(f"owner: {owner}")
    entry = state.get("entry")
    if entry:
        lines.append(f"entry: {entry}")
    for round_entry in state["rounds"]:
        lines.append(f"round {round_entry['round']}:")
        lines.append(f"  phase: {round_entry['phase']}")
        builder = round_entry["builder"]
        if builder is not None:
            lines.append(f"  builder @ {builder['head_snapshot']}")
        reviewer = round_entry["reviewer"]
        if reviewer is not None:
            lines.append(
                f"  reviewer @ {reviewer['head_snapshot']}: {reviewer['decision']}"
            )
            selection = reviewer.get("specialist_selection")
            if selection is not None:
                names = ", ".join(selection["specialists"]) or "none"
                lines.append(f"  specialists: {names}")
            for finding in sorted(reviewer["findings"], key=lambda item: item["rank"]):
                marker = "BLOCKING" if finding["blocking"] else "non-blocking"
                expansion = finding.get("expansion_reason")
                suffix = f" [{expansion}]" if expansion else ""
                lines.append(
                    f"    [{marker}] {finding['category']} {finding['location']}: "
                    f"{finding['summary']}{suffix}"
                )
        triage = round_entry.get("triage")
        if triage is not None:
            by = triage.get("by")
            lines.append(f"  triage (by {by}):" if by else "  triage:")
            for finding_id, entry in sorted(triage["dispositions"].items()):
                reason = (
                    f" ({entry['override_reason']})"
                    if entry.get("override_reason")
                    else ""
                )
                lines.append(f"    {finding_id}: {entry['disposition']}{reason}")
            owner_note = _triage_owner_note(state.get("owner"), triage)
            if owner_note:
                lines.append(f"  {owner_note}")
    for reopen_record in state.get("reopens", []):
        by = reopen_record.get("by")
        by_suffix = f" by {by}" if by else ""
        lines.append(
            f"reopened{by_suffix} after round {reopen_record['from_round']} "
            f"(was {reopen_record['previous_status']}): {reopen_record['reason']}"
        )
    for waiver in state.get("coverage_waivers", []):
        by = waiver.get("by")
        by_suffix = f" by {by}" if by else ""
        lines.append(
            f"waived{by_suffix} at round {waiver['round']}: {waiver['dimension']} "
            f"-- {waiver['reason']}"
        )
    for update in state.get("link_ref_updates", []):
        by = update.get("by")
        by_suffix = f" by {by}" if by else ""
        previous = update.get("previous") or "(none)"
        lines.append(f"relinked{by_suffix}: {previous} -> {update['new']}")
    return "\n".join(lines) + "\n"


_DIMENSION_LABELS: dict[str, str] = {
    "correctness": "correctness",
    "security_privacy_data_compatibility": "security, privacy, data, and compatibility",
    "concurrency": "concurrency",
    "error_handling": "error handling",
    "test_quality": "test quality",
    "architecture_scope": "architecture and scope",
    "maintainability": "maintainability",
    "rollout": "rollout",
}


def pr_description(task_id: str, *, target: Path) -> str:
    """A human-readable pull request body, self-contained without the repo's
    own docs -- distinct from log_text()'s round-by-round evidence log, which
    stays the audit trail (`codev task log`) and is never embedded here.

    Draws on `description` (falling back to `summary` for a small item that
    never needed the fuller text) for the why/what, and the item's coverage
    manifest for a prose validation summary -- both already recorded by the
    time an item reaches `open-pr`/`mark-ready`, so this needs no new input.
    """
    state = _load(task_id, target=target)
    rounds: list[dict[str, Any]] = state["rounds"]
    lines: list[str] = []

    narrative = state.get("description") or state.get("summary")
    lines.append(narrative if narrative else f"Task {state['task_id']}.")
    lines.append("")

    lines.append("## Validation")
    latest_reviewer = rounds[-1]["reviewer"]
    if latest_reviewer is None:
        lines.append("Review is still in progress.")
    else:
        coverage = _effective_coverage(state)
        missing = _incomplete_coverage(coverage)
        all_passed = not missing and all(
            coverage.get(dimension, {}).get("passed")
            for dimension in REQUIRED_COVERAGE_DIMENSIONS
        )
        if all_passed:
            lines.append(
                f"All {len(REQUIRED_COVERAGE_DIMENSIONS)} review dimensions pass."
            )
        else:
            for dimension in REQUIRED_COVERAGE_DIMENSIONS:
                label = _DIMENSION_LABELS.get(dimension, dimension)
                entry = coverage.get(dimension)
                if entry is None:
                    lines.append(f"- {label}: not yet reviewed")
                elif entry.get("waived"):
                    reason = entry.get("reason", "")
                    by = entry.get("by")
                    by_suffix = f" (by {by})" if by else ""
                    lines.append(f"- {label}: waived{by_suffix} -- {reason}")
                elif entry.get("passed"):
                    lines.append(f"- {label}: passed")
                else:
                    lines.append(f"- {label}: not passed")
    lines.append("")

    tracking = f"Task: {state['task_id']}"
    link_ref = state.get("link_ref")
    if link_ref:
        tracking += f" ({link_ref})"
    lines.append(tracking)
    lines.append(f"Full review history: `codev task log --id {state['task_id']}`")
    return "\n".join(lines) + "\n"


def _escalations_path(target: Path) -> Path:
    return target / Path(TASK_DIR_RELATIVE.as_posix()) / ESCALATIONS_FILENAME


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_escalation(
    task_id: str,
    trigger: str,
    cause: str,
    *,
    target: Path,
    phase: str | None = None,
    round_number: int | None = None,
    defer: bool = False,
) -> None:
    """Append one local, gitignored escalation record. Never called by `check`,
    which stays read-only; the caller records an escalation explicitly after
    observing a `stop_*` result, a pre-build critical interrupt, or a human
    override of a blocking finding during triage.

    The record itself never becomes part of a commit -- `escalations.jsonl`
    is gitignored by design, so `_commit_bookkeeping` below stages nothing
    for it. Called anyway, for two reasons: uniformity with the other six
    state-mutating functions (the conformance test below treats all seven
    alike), and because escalating is itself a natural flush point --
    handing a stopped round to a human for a decision is exactly the
    boundary ADR-0045 says to flush any other bookkeeping accumulated so
    far, not just leave it pending.
    """
    _validate_id(task_id)
    if trigger not in VALID_ESCALATION_TRIGGERS:
        raise TaskError(
            f"trigger must be one of {VALID_ESCALATION_TRIGGERS}, got {trigger!r}"
        )
    if phase is not None and phase not in PHASES:
        raise TaskError(f"phase must be one of {PHASES} or null, got {phase!r}")
    if not cause.strip():
        raise TaskError("cause must not be empty")
    record = {
        "timestamp": _utc_now_iso(),
        "task_id": task_id,
        "phase": phase,
        "round": round_number,
        "trigger": trigger,
        "cause": cause,
    }
    path = _escalations_path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    _commit_bookkeeping(task_id, target=target, defer=defer)


def read_escalations(
    *,
    target: Path,
    since: str | None = None,
    task_id: str | None = None,
) -> list[dict[str, Any]]:
    path = _escalations_path(target)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = cast("dict[str, Any]", json.loads(line))
        if since is not None and record["timestamp"] < since:
            continue
        if task_id is not None and record["task_id"] != task_id:
            continue
        records.append(record)
    return records


def escalations_text(*, target: Path, since: str | None = None) -> str:
    records = read_escalations(target=target, since=since)
    if not records:
        return "No escalations recorded.\n"
    lines = []
    for record in records:
        phase = record["phase"] or "-"
        round_number = record["round"] if record["round"] is not None else "-"
        lines.append(
            f"{record['timestamp']} {record['task_id']} "
            f"[{phase}/round {round_number}] {record['trigger']}: {record['cause']}"
        )
    return "\n".join(lines) + "\n"
