#!/usr/bin/env python3
"""Run every seeded-defect fixture against a live OpenCode actor and report recall.

Requires OpenCode already installed and authenticated, per
docs/features/skill-eval/README.md. This measures whether an actor
following review-change's conventions actually catches each planted defect
in .codev/fixtures/seeded-defect-*/ - the recall-calibration mechanism
referenced by docs/adr/0001-work-lifecycle-invariant.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from codev_workflow.eval import EvaluationError, evaluate

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_ROOT = REPO_ROOT / ".codev" / "fixtures"


def seeded_defect_fixture_names(fixtures_root: Path = FIXTURES_ROOT) -> list[str]:
    if not fixtures_root.is_dir():
        return []
    return sorted(
        path.name
        for path in fixtures_root.iterdir()
        if path.is_dir() and path.name.startswith("seeded-defect-")
    )


def run_suite(
    names: list[str], *, repo: Path, output: Path
) -> tuple[list[str], list[str]]:
    output.mkdir(parents=True, exist_ok=True)
    passed: list[str] = []
    failed: list[str] = []
    for name in names:
        destination = output / name
        try:
            caught = evaluate(name, repo, destination)
        except EvaluationError as error:
            print(f"{name}: error: {error}", file=sys.stderr)
            failed.append(name)
            continue
        (passed if caught else failed).append(name)
        print(f"{name}: {'caught' if caught else 'missed'}")
    return passed, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)

    names = seeded_defect_fixture_names()
    if not names:
        print("no seeded-defect fixtures found", file=sys.stderr)
        return 1

    passed, failed = run_suite(names, repo=args.repo, output=args.output)
    print(f"\nRecall: {len(passed)}/{len(names)} planted defects caught")
    if failed:
        print("Missed: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
