"""Tests for reading and summarizing the local gate-decision log.

The log itself is written by the standalone hook scripts
(.claude/hooks/require_plan.py, .claude/hooks/require_wave_shape.py, tested
directly in test_claude_hook.py and test_wave_shape_hook.py); this module is
read-only, so these tests write fixture JSONL directly.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from codev_workflow.hook_log import (
    DECISIONS_LOG_RELATIVE,
    read_decisions,
    summarize_decisions,
)


def _write_records(target: Path, records: list[dict[str, object]]) -> None:
    path = target / Path(DECISIONS_LOG_RELATIVE.as_posix())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


class ReadDecisionsTests(unittest.TestCase):
    def test_no_file_yet_reads_as_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual([], read_decisions(target=Path(directory)))

    def test_reads_recorded_lines_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            _write_records(
                target,
                [
                    {
                        "timestamp": "2026-08-31T10:00:00Z",
                        "hook": "require_plan.py",
                        "decision": "allow",
                    },
                    {
                        "timestamp": "2026-08-31T11:00:00Z",
                        "hook": "require_plan.py",
                        "decision": "ask",
                    },
                ],
            )
            records = read_decisions(target=target)
        self.assertEqual(2, len(records))
        self.assertEqual("allow", records[0]["decision"])
        self.assertEqual("ask", records[1]["decision"])

    def test_since_filters_older_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            _write_records(
                target,
                [
                    {
                        "timestamp": "2026-08-30T10:00:00Z",
                        "hook": "require_plan.py",
                        "decision": "allow",
                    },
                    {
                        "timestamp": "2026-08-31T10:00:00Z",
                        "hook": "require_plan.py",
                        "decision": "ask",
                    },
                ],
            )
            records = read_decisions(target=target, since="2026-08-31T00:00:00Z")
        self.assertEqual(1, len(records))
        self.assertEqual("ask", records[0]["decision"])

    def test_skips_malformed_lines_without_raising(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            path = target / Path(DECISIONS_LOG_RELATIVE.as_posix())
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                'not json\n{"timestamp": "2026-08-31T10:00:00Z", "hook": "x", '
                '"decision": "allow"}\n',
                encoding="utf-8",
            )
            records = read_decisions(target=target)
        self.assertEqual(1, len(records))


class SummarizeDecisionsTests(unittest.TestCase):
    def test_empty_records_summarize_to_empty(self) -> None:
        self.assertEqual({}, summarize_decisions([]))

    def test_counts_by_hook_and_decision(self) -> None:
        records = [
            {"hook": "require_plan.py", "decision": "allow"},
            {"hook": "require_plan.py", "decision": "allow"},
            {"hook": "require_plan.py", "decision": "ask"},
            {"hook": "require_wave_shape.py", "decision": "ask"},
        ]
        self.assertEqual(
            {
                "require_plan.py": {"allow": 2, "ask": 1},
                "require_wave_shape.py": {"ask": 1},
            },
            summarize_decisions(records),
        )


if __name__ == "__main__":
    unittest.main()
