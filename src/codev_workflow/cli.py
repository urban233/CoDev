"""Command-line interface for CoDev."""

from __future__ import annotations

import argparse
import platform
import sys
from collections.abc import Sequence
from pathlib import Path

from codev_workflow import __version__
from codev_workflow.installer import (
    CoDevError,
    apply_plan,
    check_project,
    format_plan,
    plan_init,
    plan_remove,
    plan_update,
)


def _target(value: str) -> Path:
    return Path(value).expanduser()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codev",
        description="Install and maintain human-guided AI delivery workflows.",
    )
    parser.add_argument("--version", action="version", version=f"CoDev {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="install CoDev into a repository")
    init.add_argument("--target", type=_target, default=Path.cwd())
    init.add_argument(
        "--agent-platform",
        action="append",
        choices=("all", "antigravity", "codex", "junie", "opencode"),
        default=None,
        help="target adapter; repeat to select several (default: all)",
    )
    init.add_argument(
        "--programming-language",
        choices=("none", "all", "python", "typescript"),
        default="none",
        help="code style audit skills to install (default: none)",
    )
    init.add_argument("--dry-run", action="store_true", help="show the plan only")

    check = commands.add_parser("check", help="verify an installed bundle")
    check.add_argument("--target", type=_target, default=Path.cwd())

    doctor = commands.add_parser("doctor", help="show environment and bundle health")
    doctor.add_argument("--target", type=_target, default=Path.cwd())

    diff = commands.add_parser("diff", help="preview update changes")
    diff.add_argument("--target", type=_target, default=Path.cwd())
    diff.add_argument(
        "--agent-platform",
        action="append",
        choices=("all", "antigravity", "codex", "junie", "opencode"),
        default=None,
        help="also add this adapter; repeat to select several",
    )
    diff.add_argument(
        "--programming-language",
        choices=("none", "all", "python", "typescript"),
        default=None,
        help="code style audit skills to select",
    )

    update = commands.add_parser("update", help="apply a conflict-free bundle update")
    update.add_argument("--target", type=_target, default=Path.cwd())
    update.add_argument(
        "--agent-platform",
        action="append",
        choices=("all", "antigravity", "codex", "junie", "opencode"),
        default=None,
        help="also add this adapter; repeat to select several",
    )
    update.add_argument(
        "--programming-language",
        choices=("none", "all", "python", "typescript"),
        default=None,
        help="code style audit skills to select",
    )

    remove = commands.add_parser(
        "remove", help="remove an unchanged CoDev installation"
    )
    remove.add_argument("--target", type=_target, default=Path.cwd())
    remove.add_argument("--dry-run", action="store_true", help="show the plan only")
    return parser


def _print_check(target: Path) -> int:
    result = check_project(target)
    if result.ok:
        print(
            f"CoDev {result.version} is healthy: "
            f"{result.managed_files} managed files, no drift."
        )
        return 0
    print(f"CoDev check found {len(result.issues)} issue(s):")
    for issue in result.issues:
        print(f"- {issue}")
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            target = args.target.resolve()
            platforms = args.agent_platform or ["all"]
            plan = plan_init(target, platforms, args.programming_language)
            print(format_plan(plan))
            if plan.conflicts:
                print(f"Installation stopped: {len(plan.conflicts)} conflict(s).")
                return 2
            if args.dry_run:
                print("Dry run complete; no files were written.")
                return 0
            apply_plan(target, plan)
            print(f"Installed CoDev {__version__} into {target}")
            return 0

        if args.command == "check":
            return _print_check(args.target.resolve())

        if args.command == "doctor":
            print(f"CoDev: {__version__}")
            print(f"Python: {platform.python_version()} ({platform.system()})")
            print(f"Target: {args.target.resolve()}")
            return _print_check(args.target.resolve())

        if args.command in {"diff", "update"}:
            target = args.target.resolve()
            plan = plan_update(
                target,
                args.agent_platform,
                programming_language=args.programming_language,
            )
            print(format_plan(plan))
            if plan.conflicts:
                print(f"Update stopped: {len(plan.conflicts)} conflict(s).")
                return 2
            if args.command == "diff":
                print("Preview complete; no files were written.")
                return 0
            apply_plan(target, plan)
            print(f"Updated CoDev bundle to {__version__} in {target}")
            return 0

        if args.command == "remove":
            target = args.target.resolve()
            plan = plan_remove(target)
            print(format_plan(plan))
            if plan.conflicts:
                print(f"Removal stopped: {len(plan.conflicts)} conflict(s).")
                return 2
            if args.dry_run:
                print("Dry run complete; no files were removed.")
                return 0
            apply_plan(target, plan)
            print(f"Removed CoDev from {target}")
            return 0
    except CoDevError as error:
        print(f"codev: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"codev: filesystem error: {error}", file=sys.stderr)
        return 2
    return 2
