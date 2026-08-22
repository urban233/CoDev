"""Deterministic verifier: did the actor catch (via findings.json, a direct
fix, or both) that the seeded test mocks StandardScaler/CheckpointedRegressor
even though the real, cheap, deterministic implementations are available in
the same module?"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TEST_FILE = Path("tests/test_pipeline.py")
FINDINGS_FILE = Path("findings.json")

MOCK_MARKERS = (
    "Mock(",
    "MagicMock(",
    "NonCallableMock(",
    "unittest.mock",
    "from mock",
    "@patch",
    "patch(",
    "patch.object",
    "create_autospec",
    "sentinel",
)

FINDING_KEYWORDS = (
    "mock",
    "magicmock",
    "real implementation",
    "fidelity",
    "standardscaler",
    "checkpointedregressor",
    "test double",
    "stub",
)


def check_test_suite_still_passes() -> bool:
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        print(
            "the test suite does not pass after the actor's change:",
            file=sys.stderr,
        )
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return False
    return True


def reported_finding() -> bool:
    if not FINDINGS_FILE.is_file():
        return False
    try:
        data = json.loads(FINDINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"cannot read findings.json: {error}", file=sys.stderr)
        return False
    findings = data.get("findings")
    if not isinstance(findings, list):
        return False
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        haystack = " ".join(
            str(finding.get(field, "")) for field in ("location", "summary")
        ).lower()
        if "test_pipeline.py" in haystack and any(
            keyword in haystack for keyword in FINDING_KEYWORDS
        ):
            return True
    return False


def fixed_directly() -> bool:
    if not TEST_FILE.is_file():
        return False
    text = TEST_FILE.read_text(encoding="utf-8")
    if "normalized_predictions" not in text:
        return False
    if any(marker in text for marker in MOCK_MARKERS):
        return False
    return "StandardScaler(" in text and "CheckpointedRegressor(" in text


def main() -> int:
    if not check_test_suite_still_passes():
        return 1

    if reported_finding():
        print("findings.json correctly flags the test-double issue")
        return 0
    if fixed_directly():
        print("tests/test_pipeline.py was fixed to use the real components")
        return 0

    print(
        "neither findings.json nor tests/test_pipeline.py show evidence the "
        "mocked StandardScaler/CheckpointedRegressor issue was caught",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
