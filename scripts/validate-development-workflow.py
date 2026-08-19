#!/usr/bin/env python3
"""Validate the repository's human-AI workflow without dependencies."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

EXPECTED_SKILLS = {
    "specify-project": [
        "assets/specification.template.md",
        "references/interview-coverage.md",
        "scripts/validate_specification.py",
    ],
    "define-product": ["assets/brief.template.md"],
    "design-solution": [
        "assets/design.template.md",
        "assets/adr.template.md",
    ],
    "plan-delivery": ["assets/delivery-plan.template.md"],
    "build-change": ["assets/implementation-plan.template.md"],
    "review-change": [],
    "pr-review": ["scripts/publish_review.py"],
    "critique-review": ["assets/suggested-edit.template.md"],
    "launch-product": ["assets/launch-plan.template.md"],
    "design-skill-eval": ["references/eval-design-checklist.md"],
}

EXPECTED_HANDBOOKS: list[str] = []

EXPECTED_GUIDES = [
    "AGENTS.md",
    "docs/codev/onboarding/onboarding-guide.md",
    ".codev/for-ai/ai-agent-guidelines.md",
]

# The workflow evaluator and its catalog are this script's own sibling dev
# tooling -- neither ships in the bundle this script validates (--repo
# points at src/codev_workflow/bundle, which has no scripts/ or evals/ of
# its own) -- so they resolve relative to this file's own location, not
# --repo.
_SELF_ROOT = Path(__file__).resolve().parent.parent
EVALUATION_SCRIPT = _SELF_ROOT / "scripts" / "evaluate-development-workflow.py"
EVALUATION_CATALOG = _SELF_ROOT / "evals" / "development-workflow" / "scenarios.json"


def parse_frontmatter(text: str, path: Path, errors: list[str]) -> dict[str, str]:
    """Parse skill metadata and append malformed-line errors.

    Args:
        text: Skill file text containing YAML-like frontmatter.
        path: Skill file path used in error messages.
        errors: Mutable list receiving validation errors.

    Returns:
        Parsed frontmatter fields.
    """
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        errors.append(f"{path}: missing opening YAML delimiter")
        return {}
    try:
        end = lines.index("---", 1)
    except ValueError:
        errors.append(f"{path}: missing closing YAML delimiter")
        return {}

    result: dict[str, str] = {}
    for line in lines[1:end]:
        match = re.fullmatch(r"([a-zA-Z0-9_-]+):\s*(.+)", line)
        if not match:
            errors.append(f"{path}: unsupported frontmatter line: {line!r}")
            continue
        result[match.group(1)] = match.group(2).strip().strip('"')
    return result


def validate_skill(root: Path, name: str, assets: list[str], errors: list[str]) -> None:
    """Validate one skill and its required supporting assets.

    Args:
        root: Root directory containing installed skills.
        name: Skill directory name.
        assets: Relative asset paths required by the skill.
        errors: Mutable list receiving validation errors.
    """
    skill_dir = root / name
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        errors.append(f"{skill_file}: missing")
        return

    text = skill_file.read_text(encoding="utf-8")
    metadata = parse_frontmatter(text, skill_file, errors)
    if set(metadata) != {"name", "description"}:
        errors.append(
            f"{skill_file}: frontmatter must contain only name and description"
        )
    if metadata.get("name") != name:
        errors.append(f"{skill_file}: name must match directory {name!r}")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64:
        errors.append(
            f"{skill_file}: name must be hyphen-case and at most 64 characters"
        )
    description = metadata.get("description", "")
    if len(description) < 80:
        errors.append(f"{skill_file}: description is too short to trigger reliably")
    if len(description) > 1024 or "<" in description or ">" in description:
        errors.append(f"{skill_file}: description violates skill metadata limits")
    if len(text.splitlines()) > 500:
        errors.append(f"{skill_file}: exceeds the 500-line skill budget")
    if re.search(r"\b(TODO|TBD)\b", text, re.IGNORECASE):
        errors.append(f"{skill_file}: contains an unfinished placeholder")

    ui_file = skill_dir / "agents" / "openai.yaml"
    if not ui_file.is_file():
        errors.append(f"{ui_file}: missing")
    else:
        ui = ui_file.read_text(encoding="utf-8")
        for field in ("display_name", "short_description", "default_prompt"):
            if not re.search(rf"^\s*{field}:\s*\".+\"\s*$", ui, re.MULTILINE):
                errors.append(f"{ui_file}: missing quoted {field}")
        if f"${name}" not in ui:
            errors.append(f"{ui_file}: default_prompt must mention ${name}")

    for relative in assets:
        asset = skill_dir / relative
        if not asset.is_file() or asset.stat().st_size == 0:
            errors.append(f"{asset}: missing or empty")


def validate_guides(repo: Path, errors: list[str]) -> None:
    """Validate that required guides reference every installed skill.

    Args:
        repo: Bundle repository root.
        errors: Mutable list receiving validation errors.
    """
    guides = [repo / relative for relative in EXPECTED_GUIDES]
    for guide in guides:
        if not guide.is_file():
            errors.append(f"{guide}: missing")
            continue
        text = guide.read_text(encoding="utf-8")
        for skill in EXPECTED_SKILLS:
            if skill not in text:
                errors.append(f"{guide}: does not reference {skill}")


def validate_handbooks(repo: Path, errors: list[str]) -> None:
    """Validate required handbook contents when handbook expectations exist.

    Args:
        repo: Bundle repository root.
        errors: Mutable list receiving validation errors.
    """
    handbook_root = repo / "docs" / "handbooks"
    for name in EXPECTED_HANDBOOKS:
        handbook = handbook_root / name
        if not handbook.is_file():
            errors.append(f"{handbook}: missing")
            continue
        text = handbook.read_text(encoding="utf-8")
        if len(text.splitlines()) < 100:
            errors.append(f"{handbook}: unexpectedly short")
        if re.search(r"\b(TODO|TBD)\b", text, re.IGNORECASE):
            errors.append(f"{handbook}: contains an unfinished placeholder")
        for skill in EXPECTED_SKILLS:
            if skill not in text:
                errors.append(f"{handbook}: does not reference {skill}")


def validate_evaluations(errors: list[str]) -> int:
    """Validate the behavioral evaluation catalog and scorer.

    Uses EVALUATION_SCRIPT/EVALUATION_CATALOG (this script's own sibling
    tooling), not the bundle repo being validated elsewhere in this module.

    Args:
        errors: Mutable list receiving validation errors.

    Returns:
        Number of scenarios in the valid catalog, or zero on failure.
    """
    if not EVALUATION_SCRIPT.is_file():
        errors.append(f"{EVALUATION_SCRIPT}: missing")
        return 0
    if not EVALUATION_CATALOG.is_file():
        errors.append(f"{EVALUATION_CATALOG}: missing")
        return 0

    for label, extra_args in (
        ("catalog", []),
        ("scorer self-test", ["--self-test"]),
    ):
        try:
            completed = subprocess.run(
                [sys.executable, str(EVALUATION_SCRIPT), *extra_args],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            errors.append(f"behavioral evaluation {label} timed out")
            return 0
        if completed.returncode != 0:
            detail = (completed.stdout + completed.stderr).strip()
            errors.append(f"behavioral evaluation {label} is invalid: {detail}")
            return 0

    try:
        data = json.loads(EVALUATION_CATALOG.read_text(encoding="utf-8"))
        return len(data.get("scenarios", []))
    except (OSError, ValueError, TypeError) as error:
        errors.append(f"{EVALUATION_CATALOG}: cannot count scenarios: {error}")
        return 0


def main() -> int:
    """Validate installed skills, guides, handbooks, and evaluations.

    Returns:
        Zero when all repository checks pass, otherwise one.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root (defaults to the script's repository)",
    )
    args = parser.parse_args()
    repo = args.repo.resolve()
    skill_root = repo / ".agents" / "skills"
    errors: list[str] = []

    for skill, assets in EXPECTED_SKILLS.items():
        validate_skill(skill_root, skill, assets, errors)
    validate_guides(repo, errors)
    validate_handbooks(repo, errors)
    scenario_count = validate_evaluations(errors)

    if errors:
        print("Workflow validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        "Workflow validation passed: "
        f"{len(EXPECTED_SKILLS)} skills, {len(EXPECTED_GUIDES)} guides, and "
        f"{len(EXPECTED_HANDBOOKS)} handbooks, plus "
        f"{scenario_count} behavioral scenarios"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
