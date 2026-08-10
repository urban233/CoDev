"""Round-state lifecycle tracking for the builder/reviewer correction loop.

Turns "stop after two correction attempts with the same root cause" from a
sentence an orchestrator has to remember into state a script can check. See
docs/adr/0001-work-lifecycle-invariant.md for why this may run during a build.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

from codev_workflow.installer import _atomic_write

ROUND_SCHEMA_VERSION = 1
WORK_DIR_RELATIVE = PurePosixPath(".codev/work")
DEFAULT_MAX_ROUNDS = 2
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

REQUIRED_COVERAGE_DIMENSIONS = (
    "correctness",
    "security_privacy_data_concurrency_compatibility",
    "error_handling",
    "test_quality",
    "architecture_scope",
    "maintainability",
    "rollout",
)

VALID_DECISIONS = (
    "READY_FOR_HUMAN_APPROVAL",
    "CHANGES_REQUIRED",
    "BLOCKED_BY_MISSING_EVIDENCE",
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


def start(
    work_item_id: str,
    base_snapshot: str,
    *,
    target: Path,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
) -> Path:
    if max_rounds < 1:
        raise WorkError("max_rounds must be at least 1")
    path = _work_item_path(target, work_item_id)
    if path.exists():
        raise WorkError(f"work item {work_item_id!r} already exists at {path}")
    state: dict[str, Any] = {
        "round_schema_version": ROUND_SCHEMA_VERSION,
        "work_item_id": work_item_id,
        "base_snapshot": base_snapshot,
        "max_rounds": max_rounds,
        "current_round": 1,
        "rounds": [{"round": 1, "builder": None, "reviewer": None}],
        "status": "in_progress",
    }
    _save(work_item_id, state, target=target)
    return path


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
    if (
        previous["reviewer"] is None
        or previous["reviewer"]["decision"] != "CHANGES_REQUIRED"
    ):
        raise WorkError(
            f"cannot open round {round_number}: round {previous['round']} has no "
            "CHANGES_REQUIRED reviewer decision yet"
        )
    if round_number > state["max_rounds"]:
        raise WorkError(
            f"cannot open round {round_number}: max_rounds is {state['max_rounds']}"
        )
    new_round: dict[str, Any] = {
        "round": round_number,
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
        validated.append(
            {
                "id": finding_id,
                "location": item["location"],
                "category": item["category"],
                "blocking": item["blocking"],
                "rank": item["rank"],
                "summary": item["summary"],
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


def _find_repeated_blocking_finding(
    rounds: list[dict[str, Any]],
) -> dict[str, Any] | None:
    latest = rounds[-1]
    if latest["reviewer"] is None:
        return None
    seen: set[tuple[str, str]] = set()
    for round_entry in rounds[:-1]:
        reviewer = round_entry["reviewer"]
        if reviewer is None:
            continue
        for finding in reviewer["findings"]:
            if finding["blocking"]:
                seen.add((finding["location"], finding["category"]))
    latest_findings = cast(list[dict[str, Any]], latest["reviewer"]["findings"])
    for finding in latest_findings:
        if finding["blocking"] and (finding["location"], finding["category"]) in seen:
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
        repeat = _find_repeated_blocking_finding(rounds)
        if repeat is not None:
            return CheckResult(
                False,
                "stop_repeated_finding",
                f"finding at {repeat['location']} ({repeat['category']}) was already "
                "raised as blocking in an earlier round: same root cause, escalate "
                "to the human",
            )
        if state["current_round"] >= state["max_rounds"]:
            return CheckResult(
                False,
                "stop_round_cap",
                f"round {state['current_round']} of {state['max_rounds']}: "
                "stop and escalate to the human",
            )
        return CheckResult(
            True, "ok_continue", f"round {latest['round'] + 1} may begin"
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
        "max_rounds": state["max_rounds"],
        "latest_decision": reviewer["decision"] if reviewer is not None else None,
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
    for round_entry in state["rounds"]:
        lines.append(f"round {round_entry['round']}:")
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
                lines.append(
                    f"    [{marker}] {finding['category']} {finding['location']}: "
                    f"{finding['summary']}"
                )
    return "\n".join(lines) + "\n"
