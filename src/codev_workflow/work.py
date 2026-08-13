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

ROUND_SCHEMA_VERSION = 2
WORK_DIR_RELATIVE = PurePosixPath(".codev/work")
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

VALID_ENTRY_MODES = ("takeover", "direct-review")


class WorkError(Exception):
    """Raised for invalid work-item state or lifecycle transitions."""


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    reason: str
    message: str


def load_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise WorkError(f"cannot read {path}: {error}") from error


def _validate_id(work_item_id: str) -> None:
    if not _ID_PATTERN.match(work_item_id):
        raise WorkError(
            f"invalid work item id {work_item_id!r}; use letters, digits, '.', '_', '-'"
        )


def _work_item_dir(target: Path, work_item_id: str) -> Path:
    _validate_id(work_item_id)
    return target / Path(WORK_DIR_RELATIVE.as_posix()) / work_item_id


def _work_item_path(target: Path, work_item_id: str) -> Path:
    return _work_item_dir(target, work_item_id) / "round-state.json"


def _load(work_item_id: str, *, target: Path) -> dict[str, Any]:
    path = _work_item_path(target, work_item_id)
    if not path.exists():
        raise WorkError(f"no work item {work_item_id!r} at {path}")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise WorkError(f"cannot read {path}: {error}") from error
    if (
        not isinstance(state, dict)
        or state.get("round_schema_version") != ROUND_SCHEMA_VERSION
    ):
        raise WorkError(
            f"{path} has an unsupported or invalid round schema; "
            "install a compatible CoDev version"
        )
    return state


def _save(work_item_id: str, state: dict[str, Any], *, target: Path) -> None:
    path = _work_item_path(target, work_item_id)
    content = (json.dumps(state, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write(path, content)


def _ensure_in_progress(state: dict[str, Any]) -> None:
    if state["status"] != "in_progress":
        raise WorkError(f"work item is {state['status']!r}, not in_progress")


def _normalize_max_rounds(max_rounds: int | dict[str, int] | None) -> dict[str, int]:
    if max_rounds is None:
        return {"inner": DEFAULT_INNER_MAX_ROUNDS, "outer": DEFAULT_OUTER_MAX_ROUNDS}
    if isinstance(max_rounds, bool):
        raise WorkError(
            "max_rounds must be an int or a {'inner': int, 'outer': int} dict"
        )
    if isinstance(max_rounds, int):
        if max_rounds < 1:
            raise WorkError("max_rounds must be at least 1")
        return {"inner": max_rounds, "outer": max_rounds}
    if isinstance(max_rounds, dict):
        missing = [phase for phase in PHASES if phase not in max_rounds]
        if missing:
            raise WorkError(f"max_rounds is missing phase(s): {', '.join(missing)}")
        extra = sorted(set(max_rounds) - set(PHASES))
        if extra:
            raise WorkError(f"max_rounds has unknown phase(s): {', '.join(extra)}")
        for phase in PHASES:
            value = max_rounds[phase]
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise WorkError(f"max_rounds[{phase!r}] must be an integer >= 1")
        return {phase: max_rounds[phase] for phase in PHASES}
    raise WorkError("max_rounds must be an int or a {'inner': int, 'outer': int} dict")


def _validate_optional_text(field_name: str, value: str | None) -> None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise WorkError(f"{field_name} must be non-empty text when provided")


def _validate_required_text(field_name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise WorkError(f"{field_name} must be non-empty text")


def start(
    work_item_id: str,
    base_snapshot: str,
    *,
    target: Path,
    max_rounds: int | dict[str, int] | None = None,
    link_ref: str | None = None,
    summary: str | None = None,
    description: str | None = None,
    owner: str | None = None,
    entry: str | None = None,
) -> Path:
    resolved_max_rounds = _normalize_max_rounds(max_rounds)
    _validate_optional_text("link_ref", link_ref)
    _validate_optional_text("summary", summary)
    _validate_optional_text("description", description)
    _validate_optional_text("owner", owner)
    if entry is not None and entry not in VALID_ENTRY_MODES:
        raise WorkError(
            f"entry must be null or one of {VALID_ENTRY_MODES}, got {entry!r}"
        )
    path = _work_item_path(target, work_item_id)
    if path.exists():
        raise WorkError(
            f"work item {work_item_id!r} already exists at {path}; to continue "
            "it (after a close, a round-cap stop, or drift) use `codev work "
            "reopen`, not `start`"
        )
    # direct-review has nothing for the inner loop to do -- round 1 opens
    # straight into the outer phase so the first `codev work record` lands on
    # it directly, instead of the inner-to-outer transition `_round_slot`
    # normally requires a READY_FOR_OUTER_LOOP decision to create.
    initial_phase = "outer" if entry == "direct-review" else "inner"
    state: dict[str, Any] = {
        "round_schema_version": ROUND_SCHEMA_VERSION,
        "work_item_id": work_item_id,
        "base_snapshot": base_snapshot,
        "max_rounds": resolved_max_rounds,
        "current_round": 1,
        "rounds": [
            {"round": 1, "phase": initial_phase, "builder": None, "reviewer": None}
        ],
        "status": "in_progress",
        "link_ref": link_ref,
        "summary": summary,
        "description": description,
        "owner": owner,
        "entry": entry,
    }
    _save(work_item_id, state, target=target)
    return path


def _phase_round_count(rounds: list[dict[str, Any]], phase: str) -> int:
    return sum(1 for round_entry in rounds if round_entry["phase"] == phase)


def _round_slot(state: dict[str, Any], round_number: int) -> dict[str, Any]:
    rounds: list[dict[str, Any]] = state["rounds"]
    for round_entry in rounds:
        if round_entry["round"] == round_number:
            return round_entry

    if round_number != len(rounds) + 1:
        raise WorkError(
            f"cannot open round {round_number}: expected round {len(rounds) + 1}"
        )
    previous = rounds[-1]
    previous_reviewer = previous["reviewer"]
    if previous_reviewer is None:
        raise WorkError(
            f"cannot open round {round_number}: round {previous['round']} has no "
            "reviewer decision yet"
        )
    previous_decision = previous_reviewer["decision"]
    if previous_decision == "CHANGES_REQUIRED":
        phase = previous["phase"]
        if phase == "outer" and previous.get("triage") is None:
            raise WorkError(
                f"cannot open round {round_number}: round {previous['round']} has "
                "no recorded triage yet"
            )
    elif previous_decision == "READY_FOR_OUTER_LOOP":
        if previous["phase"] != "inner":
            raise WorkError(
                f"cannot open round {round_number}: READY_FOR_OUTER_LOOP is only a "
                "valid transition from the inner phase"
            )
        phase = "outer"
    else:
        raise WorkError(
            f"cannot open round {round_number}: round {previous['round']} decision "
            f"{previous_decision!r} does not permit opening a new round"
        )

    if _phase_round_count(rounds, phase) + 1 > state["max_rounds"][phase]:
        raise WorkError(
            f"cannot open round {round_number}: max_rounds for phase {phase!r} is "
            f"{state['max_rounds'][phase]}; a human may continue this item with "
            "`codev work reopen`, optionally raising the cap"
        )
    new_round: dict[str, Any] = {
        "round": round_number,
        "phase": phase,
        "builder": None,
        "reviewer": None,
    }
    rounds.append(new_round)
    state["current_round"] = round_number
    return new_round


def _validate_findings(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise WorkError("findings must be a JSON array")
    validated: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise WorkError(f"finding[{index}] must be a JSON object")
        finding_id = item.get("id")
        if not isinstance(finding_id, str) or not finding_id:
            raise WorkError(f"finding[{index}] needs a non-empty id")
        if finding_id in seen_ids:
            raise WorkError(f"duplicate finding id: {finding_id}")
        seen_ids.add(finding_id)
        for field_name in ("location", "category", "summary"):
            value = item.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise WorkError(
                    f"finding {finding_id!r}: {field_name} must be non-empty text"
                )
        if not isinstance(item.get("blocking"), bool):
            raise WorkError(f"finding {finding_id!r}: blocking must be true or false")
        if not isinstance(item.get("rank"), int):
            raise WorkError(f"finding {finding_id!r}: rank must be an integer")
        expansion_reason = item.get("expansion_reason")
        if (
            expansion_reason is not None
            and expansion_reason not in VALID_EXPANSION_REASONS
        ):
            raise WorkError(
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
        raise WorkError("coverage must be a JSON object")
    validated: dict[str, Any] = {}
    for dimension, entry in raw.items():
        if dimension not in REQUIRED_COVERAGE_DIMENSIONS:
            raise WorkError(f"unknown coverage dimension: {dimension!r}")
        if not isinstance(entry, dict):
            raise WorkError(f"coverage[{dimension!r}] must be a JSON object")
        passed = entry.get("passed")
        evidence = entry.get("evidence")
        if not isinstance(passed, bool):
            raise WorkError(f"coverage[{dimension!r}].passed must be true or false")
        if not isinstance(evidence, str) or not evidence.strip():
            raise WorkError(f"coverage[{dimension!r}].evidence must be non-empty text")
        validated[dimension] = {"passed": passed, "evidence": evidence}
    return validated


def record_builder(
    work_item_id: str,
    round_number: int,
    head_snapshot: str,
    evidence: Any,
    *,
    target: Path,
) -> None:
    state = _load(work_item_id, target=target)
    _ensure_in_progress(state)
    if not isinstance(evidence, dict):
        raise WorkError("builder evidence must be a JSON object")
    round_entry = _round_slot(state, round_number)
    if round_entry["builder"] is not None:
        raise WorkError(
            f"round {round_number} already has a recorded builder entry; to "
            "record a correction, target a new round instead -- the next "
            "sequential round, or `codev work reopen` if this item is in a "
            "terminal state"
        )
    round_entry["builder"] = {"head_snapshot": head_snapshot, "evidence": evidence}
    _save(work_item_id, state, target=target)


def record_reviewer(
    work_item_id: str,
    round_number: int,
    head_snapshot: str,
    findings: Any,
    coverage: Any,
    decision: str,
    *,
    target: Path,
) -> None:
    if decision not in VALID_DECISIONS:
        raise WorkError(
            f"invalid decision {decision!r}; expected one of {VALID_DECISIONS}"
        )
    state = _load(work_item_id, target=target)
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
        raise WorkError(
            f"round {round_number} is already in the outer phase; "
            "READY_FOR_OUTER_LOOP only means an inner-phase hand-off to the "
            "outer loop -- record READY_FOR_HUMAN_APPROVAL, "
            "CHANGES_REQUIRED, or BLOCKED_BY_MISSING_EVIDENCE instead"
        )
    if round_entry["reviewer"] is not None:
        raise WorkError(
            f"round {round_number} already has a recorded reviewer entry; to "
            "re-review after a correction, record a new round instead -- the "
            "next sequential round, or `codev work reopen` if this item is "
            "in a terminal state"
        )
    round_entry["reviewer"] = {
        "head_snapshot": head_snapshot,
        "findings": _validate_findings(findings),
        "coverage": _validate_coverage(coverage) if coverage else {},
        "decision": decision,
    }
    _save(work_item_id, state, target=target)


def _validate_triage(raw: Any, findings: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise WorkError("triage must be a JSON object")
    dispositions = raw.get("dispositions")
    if not isinstance(dispositions, dict):
        raise WorkError("triage.dispositions must be a JSON object")
    all_ids = {finding["id"] for finding in findings}
    blocking_ids = {finding["id"] for finding in findings if finding["blocking"]}
    validated: dict[str, dict[str, Any]] = {}
    for finding_id, entry in dispositions.items():
        if finding_id not in all_ids:
            raise WorkError(f"triage references unknown finding id: {finding_id!r}")
        if not isinstance(entry, dict):
            raise WorkError(f"triage[{finding_id!r}] must be a JSON object")
        disposition = entry.get("disposition")
        if disposition not in VALID_TRIAGE_DISPOSITIONS:
            raise WorkError(
                f"triage[{finding_id!r}].disposition must be one of "
                f"{VALID_TRIAGE_DISPOSITIONS}"
            )
        override_reason = entry.get("override_reason")
        if override_reason is not None and not isinstance(override_reason, str):
            raise WorkError(f"triage[{finding_id!r}].override_reason must be text")
        if (
            disposition == "defer"
            and finding_id in blocking_ids
            and not (isinstance(override_reason, str) and override_reason.strip())
        ):
            raise WorkError(
                f"triage[{finding_id!r}]: deferring a blocking finding requires a "
                "non-empty override_reason"
            )
        validated[finding_id] = {
            "disposition": disposition,
            "override_reason": override_reason,
        }
    missing = blocking_ids - set(validated)
    if missing:
        raise WorkError(
            "triage is missing a disposition for blocking finding(s): "
            + ", ".join(sorted(missing))
        )
    return {"dispositions": validated}


def record_triage(
    work_item_id: str,
    round_number: int,
    triage: Any,
    *,
    target: Path,
    by: str | None = None,
) -> None:
    _validate_optional_text("by", by)
    state = _load(work_item_id, target=target)
    _ensure_in_progress(state)
    round_entry = _round_slot(state, round_number)
    if round_entry["phase"] != "outer":
        raise WorkError(
            f"round {round_number} is not in the outer phase; triage does not apply"
        )
    reviewer = round_entry["reviewer"]
    if reviewer is None:
        raise WorkError(f"round {round_number} has no recorded reviewer findings yet")
    if reviewer["decision"] != "CHANGES_REQUIRED":
        raise WorkError(
            f"round {round_number} decision is not CHANGES_REQUIRED; nothing to triage"
        )
    if round_entry.get("triage") is not None:
        raise WorkError(f"round {round_number} already has a recorded triage")
    validated = _validate_triage(triage, reviewer["findings"])
    validated["by"] = by
    round_entry["triage"] = validated
    _save(work_item_id, state, target=target)


def _triage_owner_note(owner: str | None, triage: dict[str, Any] | None) -> str | None:
    if not owner or triage is None:
        return None
    by = triage.get("by")
    if by and by == owner:
        return f"note: {owner} both owns this work item and triaged this round"
    return None


def triage_note(work_item_id: str, *, target: Path) -> str | None:
    """The same-person owner/triager note for the work item's latest round.

    Informational only -- callers print this alongside `check`'s result, it
    is never a new check() outcome and never affects the exit code.
    """
    state = _load(work_item_id, target=target)
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


def check(work_item_id: str, head: str, *, target: Path) -> CheckResult:
    state = _load(work_item_id, target=target)
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
            " -- codev work triage may address or defer it (with a reason) to "
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
                    "ok_approve_with_deferrals",
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
                "unexamined drift), then run `codev work reopen` before "
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
        return CheckResult(True, "ok_approve", "ready to present to the human")

    return CheckResult(True, "ok_blocked_missing_evidence", decision)


def close(work_item_id: str, outcome: str, *, target: Path) -> None:
    if outcome not in VALID_OUTCOMES:
        raise WorkError(
            f"invalid outcome {outcome!r}; expected one of {VALID_OUTCOMES}"
        )
    state = _load(work_item_id, target=target)
    _ensure_in_progress(state)
    state["status"] = "closed"
    state["outcome"] = outcome
    _save(work_item_id, state, target=target)


def reopen(
    work_item_id: str,
    head: str,
    reason: str,
    *,
    target: Path,
    max_rounds: int | dict[str, int] | None = None,
    by: str | None = None,
) -> Path:
    """Human-authorized recovery for a work item `check` reports as stuck.

    `start` refuses to reuse an id once its state file exists at all, and
    `_round_slot` mechanically refuses to open a round beyond `max_rounds` --
    both correctly protect the normal flow, but together with drift
    detection they leave no path back for a closed item, an exhausted round
    cap, or an approved change committed after the last recorded snapshot
    (a pre-PR audit fix, for example). This is the deliberate escape hatch:
    it works regardless of `status`, never touches a previously recorded
    round's builder/reviewer entry, and only re-baselines `base_snapshot` to
    `head` and appends one fresh, empty round so the ordinary
    builder/reviewer/`codev work record` flow can resume from there. Every
    call is appended to `reopens` so the recovery is as visible as the
    history it continues -- see docs/adr/0007-work-item-recovery.md.

    Callers (agents) must treat this the same as any other hard-to-reverse
    action: only run it on an explicit human decision, never on your own
    initiative because a round looked stuck.
    """
    _validate_required_text("head", head)
    _validate_required_text("reason", reason)
    _validate_optional_text("by", by)
    state = _load(work_item_id, target=target)

    resolved_max_rounds = state["max_rounds"]
    if max_rounds is not None:
        resolved_max_rounds = _normalize_max_rounds(max_rounds)
        for phase in PHASES:
            done = _phase_round_count(state["rounds"], phase)
            if resolved_max_rounds[phase] < done:
                raise WorkError(
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
    path = _work_item_path(target, work_item_id)
    _save(work_item_id, state, target=target)
    return path


def waive(
    work_item_id: str,
    dimension: str,
    reason: str,
    *,
    target: Path,
    by: str | None = None,
) -> Path:
    """Human-authorized: this coverage dimension will not be run for this
    work item, instead of leaving it to eventually be covered by some round.

    Modeled on `reopen`'s append-only pattern, not `record_triage`'s
    single-slot-per-round one -- `waive` is meant to be callable multiple
    times, across different dimensions and different rounds, the same way
    `reopen` is callable multiple times across an item's life.

    Deliberately distinct from a passing coverage entry (no `passed` key):
    `_effective_coverage` folds waivers into the same most-recent-wins merge
    as real coverage verdicts, but `codev work log` and `pr_description()`
    always render a waiver as "waived", never as "passed" -- this system
    never claims something was verified when a human decided not to run it.

    Callers (agents) must treat this the same as any other hard-to-reverse
    scope decision: only run it on an explicit human choice, never on your
    own initiative because a specialist looked skippable.
    """
    if dimension not in REQUIRED_COVERAGE_DIMENSIONS:
        raise WorkError(
            f"unknown coverage dimension: {dimension!r}; expected one of "
            f"{REQUIRED_COVERAGE_DIMENSIONS}"
        )
    _validate_required_text("reason", reason)
    _validate_optional_text("by", by)
    state = _load(work_item_id, target=target)
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
    path = _work_item_path(target, work_item_id)
    _save(work_item_id, state, target=target)
    return path


def describe(work_item_id: str, *, target: Path) -> dict[str, Any]:
    state = _load(work_item_id, target=target)
    latest = state["rounds"][-1]
    reviewer = latest["reviewer"]
    return {
        "work_item_id": state["work_item_id"],
        "status": state["status"],
        "current_round": state["current_round"],
        "current_phase": latest["phase"],
        "max_rounds": state["max_rounds"],
        "latest_decision": reviewer["decision"] if reviewer is not None else None,
        "link_ref": state.get("link_ref"),
        "summary": state.get("summary"),
        "description": state.get("description"),
        "owner": state.get("owner"),
        "entry": state.get("entry"),
    }


def describe_all(*, target: Path) -> list[dict[str, Any]]:
    root = target / Path(WORK_DIR_RELATIVE.as_posix())
    if not root.exists():
        return []
    results = []
    for entry in sorted(root.iterdir()):
        if (entry / "round-state.json").exists():
            results.append(describe(entry.name, target=target))
    return results


def log_text(work_item_id: str, *, target: Path) -> str:
    state = _load(work_item_id, target=target)
    lines = [
        f"work item {state['work_item_id']} - {state['status']} "
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


def pr_description(work_item_id: str, *, target: Path) -> str:
    """A human-readable pull request body, self-contained without the repo's
    own docs -- distinct from log_text()'s round-by-round evidence log, which
    stays the audit trail (`codev work log`) and is never embedded here.

    Draws on `description` (falling back to `summary` for a small item that
    never needed the fuller text) for the why/what, and the item's coverage
    manifest for a prose validation summary -- both already recorded by the
    time an item reaches `open-pr`/`mark-ready`, so this needs no new input.
    """
    state = _load(work_item_id, target=target)
    rounds: list[dict[str, Any]] = state["rounds"]
    lines: list[str] = []

    narrative = state.get("description") or state.get("summary")
    lines.append(narrative if narrative else f"Work item {state['work_item_id']}.")
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

    tracking = f"Work item: {state['work_item_id']}"
    link_ref = state.get("link_ref")
    if link_ref:
        tracking += f" ({link_ref})"
    lines.append(tracking)
    lines.append(f"Full review history: `codev work log --id {state['work_item_id']}`")
    return "\n".join(lines) + "\n"


def _escalations_path(target: Path) -> Path:
    return target / Path(WORK_DIR_RELATIVE.as_posix()) / ESCALATIONS_FILENAME


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_escalation(
    work_item_id: str,
    trigger: str,
    cause: str,
    *,
    target: Path,
    phase: str | None = None,
    round_number: int | None = None,
) -> None:
    """Append one local, gitignored escalation record. Never called by `check`,
    which stays read-only; the caller records an escalation explicitly after
    observing a `stop_*` result, a pre-build critical interrupt, or a human
    override of a blocking finding during triage."""
    _validate_id(work_item_id)
    if trigger not in VALID_ESCALATION_TRIGGERS:
        raise WorkError(
            f"trigger must be one of {VALID_ESCALATION_TRIGGERS}, got {trigger!r}"
        )
    if phase is not None and phase not in PHASES:
        raise WorkError(f"phase must be one of {PHASES} or null, got {phase!r}")
    if not cause.strip():
        raise WorkError("cause must not be empty")
    record = {
        "timestamp": _utc_now_iso(),
        "work_item_id": work_item_id,
        "phase": phase,
        "round": round_number,
        "trigger": trigger,
        "cause": cause,
    }
    path = _escalations_path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def read_escalations(
    *,
    target: Path,
    since: str | None = None,
    work_item_id: str | None = None,
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
        if work_item_id is not None and record["work_item_id"] != work_item_id:
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
            f"{record['timestamp']} {record['work_item_id']} "
            f"[{phase}/round {round_number}] {record['trigger']}: {record['cause']}"
        )
    return "\n".join(lines) + "\n"
