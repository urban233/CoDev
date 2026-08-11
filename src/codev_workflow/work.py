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


def start(
    work_item_id: str,
    base_snapshot: str,
    *,
    target: Path,
    max_rounds: int | dict[str, int] | None = None,
    link_ref: str | None = None,
    summary: str | None = None,
    owner: str | None = None,
) -> Path:
    resolved_max_rounds = _normalize_max_rounds(max_rounds)
    _validate_optional_text("link_ref", link_ref)
    _validate_optional_text("summary", summary)
    _validate_optional_text("owner", owner)
    path = _work_item_path(target, work_item_id)
    if path.exists():
        raise WorkError(f"work item {work_item_id!r} already exists at {path}")
    state: dict[str, Any] = {
        "round_schema_version": ROUND_SCHEMA_VERSION,
        "work_item_id": work_item_id,
        "base_snapshot": base_snapshot,
        "max_rounds": resolved_max_rounds,
        "current_round": 1,
        "rounds": [{"round": 1, "phase": "inner", "builder": None, "reviewer": None}],
        "status": "in_progress",
        "link_ref": link_ref,
        "summary": summary,
        "owner": owner,
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
            f"{state['max_rounds'][phase]}"
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
        raise WorkError(f"round {round_number} already has a recorded builder entry")
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
    if round_entry["reviewer"] is not None:
        raise WorkError(f"round {round_number} already has a recorded reviewer entry")
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
    latest_findings = cast(list[dict[str, Any]], latest["reviewer"]["findings"])
    for finding in latest_findings:
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
    latest_findings = cast(list[dict[str, Any]], latest["reviewer"]["findings"])
    for finding in latest_findings:
        if not finding["blocking"]:
            continue
        if (finding["location"], finding["category"]) in baseline:
            continue
        if finding.get("expansion_reason") is not None:
            continue
        return finding
    return None


def _incomplete_coverage(coverage: dict[str, Any]) -> list[str]:
    missing = []
    for dimension in REQUIRED_COVERAGE_DIMENSIONS:
        entry = coverage.get(dimension)
        if entry is None:
            missing.append(f"{dimension}: missing")
        elif not entry.get("passed"):
            missing.append(f"{dimension}: not passed")
    return missing


def check(work_item_id: str, head: str, *, target: Path) -> CheckResult:
    state = _load(work_item_id, target=target)
    rounds: list[dict[str, Any]] = state["rounds"]
    latest = rounds[-1]

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
        expansion = _find_scope_expansion(rounds)
        if expansion is not None:
            return CheckResult(
                False,
                "stop_scope_expansion",
                f"finding at {expansion['location']} ({expansion['category']}) was "
                "not raised in this phase's first round and carries no "
                "expansion_reason: treat as scope creep, escalate to the human",
            )
        repeat = _find_repeated_blocking_finding(rounds)
        if repeat is not None:
            return CheckResult(
                False,
                "stop_repeated_finding",
                f"finding at {repeat['location']} ({repeat['category']}) was already "
                "raised as blocking in an earlier round: same root cause, escalate "
                "to the human",
            )
        phase = latest["phase"]
        phase_round_count = _phase_round_count(rounds, phase)
        if phase_round_count >= state["max_rounds"][phase]:
            return CheckResult(
                False,
                "stop_round_cap",
                f"round {phase_round_count} of {state['max_rounds'][phase]} for "
                f"phase {phase!r}: stop and escalate to the human",
            )
        if phase == "outer" and latest.get("triage") is None:
            return CheckResult(
                True,
                "ok_waiting_on_triage",
                f"round {latest['round']}: findings recorded, waiting on the human "
                "to triage which are addressed this round",
            )
        return CheckResult(
            True, "ok_continue", f"round {latest['round'] + 1} may begin"
        )

    if decision == "READY_FOR_OUTER_LOOP":
        return CheckResult(
            True,
            "ok_ready_for_pr",
            f"round {latest['round']}: inner loop satisfied, ready to open a pull "
            "request",
        )

    if decision == "READY_FOR_HUMAN_APPROVAL":
        missing = _incomplete_coverage(reviewer["coverage"])
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
        "owner": state.get("owner"),
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
