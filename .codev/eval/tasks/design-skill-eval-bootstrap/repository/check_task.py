"""Deterministic verifier: did the actor design a well-formed, honest task?

Unlike a seeded-defect task, there is no single expected output value -- the
actor's job is to produce a whole new task (its own task.json, prompt.md,
verifier.json or checks.json, rubric.md, repository/) for the toy
`greet-user` skill seeded alongside this script. This checks the parts of
"well-formed" that are actually mechanical: it validates as a real task, it
is tagged for the right skill, and its prompt does not name the skill under
test -- the one concrete, non-obvious rule this whole eval corpus depends on.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from codev_workflow.eval import EvaluationError, validate_task
except ImportError as error:
    print(f"cannot import codev_workflow: {error}", file=sys.stderr)
    print(
        "this verifier must run under the same interpreter as CoDev itself",
        file=sys.stderr,
    )
    sys.exit(1)

TARGET_SKILL = "greet-user"
PLACEHOLDER_CATEGORY = "replace-with-category"


def main() -> int:
    candidates = sorted(Path(".codev/eval/tasks").glob("*/task.json"))
    if len(candidates) != 1:
        print(
            "expected exactly one new task under .codev/eval/tasks, found "
            f"{len(candidates)}",
            file=sys.stderr,
        )
        return 1
    task_dir = candidates[0].parent

    try:
        task = validate_task(task_dir)
    except EvaluationError as error:
        print(f"new task at {task_dir} is not valid: {error}", file=sys.stderr)
        return 1

    if task.skill != TARGET_SKILL:
        print(
            f"task.json skill must be {TARGET_SKILL!r}, got {task.skill!r}",
            file=sys.stderr,
        )
        return 1
    if not task.category or task.category == PLACEHOLDER_CATEGORY:
        print(
            "task.json category was left as the scaffold placeholder",
            file=sys.stderr,
        )
        return 1

    prompt_text = task.prompt.decode("utf-8", errors="replace").lower()
    if TARGET_SKILL in prompt_text or "greet_user" in prompt_text:
        print(
            f"prompt.md names the skill under test ({TARGET_SKILL!r}); the "
            "prompt must describe the task on its own terms so staging the "
            "skill is the only thing that differs between conditions",
            file=sys.stderr,
        )
        return 1

    print(
        "new task is valid, tagged for "
        f"{TARGET_SKILL!r}/{task.category!r}, and does not name the "
        "skill under test"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
