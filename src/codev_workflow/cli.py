"""Command-line interface for CoDev."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from codev_workflow import __version__
from codev_workflow import config as config_module
from codev_workflow import git_ops as git_ops_module
from codev_workflow import work as work_module
from codev_workflow.adapter import AdapterVerificationError, verify_adapter
from codev_workflow.config import ConfigError
from codev_workflow.eval import (
    EvaluationError,
    create_fixture,
    evaluate,
    run_snapshot,
)
from codev_workflow.installer import (
    CoDevError,
    _read_lock,
    apply_plan,
    check_project,
    format_plan,
    plan_init,
    plan_remove,
    plan_update,
)
from codev_workflow.work import (
    VALID_DECISIONS,
    VALID_OUTCOMES,
    WorkError,
)

_AGENT_PLATFORMS = ("antigravity", "codex", "junie", "opencode")
_AGENT_PLATFORM_CHOICES = ("all", *_AGENT_PLATFORMS)
_DEPRECATED_EVAL_SUBCOMMANDS = {"run", "fixture", "snapshot"}


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
        choices=_AGENT_PLATFORM_CHOICES,
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

    status = commands.add_parser(
        "status", help="show installed bundle, adapters, and work-item health"
    )
    status.add_argument("--target", type=_target, default=Path.cwd())
    status.add_argument("--verbose", action="store_true")
    status.add_argument("--json", action="store_true")

    diff = commands.add_parser("diff", help="preview update changes")
    diff.add_argument("--target", type=_target, default=Path.cwd())
    diff.add_argument(
        "--agent-platform",
        action="append",
        choices=_AGENT_PLATFORM_CHOICES,
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
        choices=_AGENT_PLATFORM_CHOICES,
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

    evaluation = commands.add_parser("eval", help="skill-evaluation fixtures and runs")
    eval_commands = evaluation.add_subparsers(dest="eval_command", required=True)

    e_fixture = eval_commands.add_parser("fixture", help="manage evaluation fixtures")
    e_fixture_commands = e_fixture.add_subparsers(
        dest="eval_fixture_command", required=True
    )
    e_fixture_create = e_fixture_commands.add_parser(
        "create", help="create an evaluation fixture"
    )
    e_fixture_create.add_argument("name")
    e_fixture_create.add_argument("--target", type=_target, required=True)
    e_fixture_create.add_argument("--include", action="append", required=True)

    e_run = eval_commands.add_parser("run", help="evaluate a local fixture")
    e_run.add_argument("name")
    e_run.add_argument("--target", type=_target, required=True)
    e_run.add_argument("--output", type=_target, required=True)
    e_run.add_argument(
        "--without-skill",
        action="store_true",
        help="run without staging the fixture's skill into the worktree",
    )

    e_snapshot = eval_commands.add_parser(
        "snapshot", help="skill performance snapshots (with/without comparisons)"
    )
    e_snapshot_commands = e_snapshot.add_subparsers(
        dest="eval_snapshot_command", required=True
    )
    e_snapshot_run = e_snapshot_commands.add_parser(
        "run", help="run every fixture for one skill, with and without it, repeated"
    )
    e_snapshot_run.add_argument("skill")
    e_snapshot_run.add_argument("--target", type=_target, required=True)
    e_snapshot_run.add_argument("--output", type=_target, required=True)
    e_snapshot_run.add_argument("--repetitions", type=int, default=3)
    e_snapshot_run.add_argument(
        "--category",
        dest="categories",
        action="append",
        help="restrict the run to this category; repeat to select several",
    )

    adapter = commands.add_parser("adapter", help="manage platform adapters")
    adapter_commands = adapter.add_subparsers(dest="adapter_command", required=True)

    a_list = adapter_commands.add_parser("list", help="show installed adapters")
    a_list.add_argument("--target", type=_target, default=Path.cwd())
    a_list.add_argument("--json", action="store_true")

    a_add = adapter_commands.add_parser(
        "add", help="add one adapter to an existing installation"
    )
    a_add.add_argument("platform", choices=_AGENT_PLATFORMS)
    a_add.add_argument("--target", type=_target, default=Path.cwd())
    a_add.add_argument(
        "--programming-language",
        choices=("none", "all", "python", "typescript"),
        default=None,
        help="code style audit skills to select",
    )
    a_add.add_argument("--dry-run", action="store_true", help="show the plan only")

    a_verify = adapter_commands.add_parser(
        "verify", help="check one installed adapter's structural conformance"
    )
    a_verify.add_argument("platform", choices=_AGENT_PLATFORMS)
    a_verify.add_argument("--target", type=_target, default=Path.cwd())
    a_verify.add_argument("--json", action="store_true")

    config = commands.add_parser("config", help="read or write layered configuration")
    config_commands = config.add_subparsers(dest="config_command", required=True)

    c_get = config_commands.add_parser("get", help="resolve one config key")
    c_get.add_argument("key")
    c_get.add_argument("--target", type=_target, default=Path.cwd())
    c_get.add_argument("--json", action="store_true")

    c_set = config_commands.add_parser("set", help="write one config key")
    c_set.add_argument("key")
    c_set.add_argument("value")
    c_set.add_argument("--target", type=_target, default=Path.cwd())
    c_set.add_argument(
        "--global",
        dest="global_scope",
        action="store_true",
        help="write to the global config",
    )

    c_list = config_commands.add_parser("list", help="show every resolved config key")
    c_list.add_argument("--target", type=_target, default=Path.cwd())
    c_list.add_argument("--json", action="store_true")

    self_parser = commands.add_parser("self", help="manage the installed codev tool")
    self_commands = self_parser.add_subparsers(dest="self_command", required=True)
    self_commands.add_parser("version", help="print the installed codev version")
    self_commands.add_parser(
        "update", help="show how to upgrade the installed codev tool"
    )

    work = commands.add_parser(
        "work", help="track builder/reviewer round state for one work item"
    )
    work_commands = work.add_subparsers(dest="work_command", required=True)

    w_start = work_commands.add_parser("start", help="open a new work item")
    w_start.add_argument("--id", required=True)
    w_start.add_argument("--base", required=True, help="base git snapshot")
    w_start.add_argument(
        "--max-rounds",
        type=int,
        default=None,
        help="applies to both phases; defaults to 2/2",
    )
    w_start.add_argument("--target", type=_target, default=Path.cwd())

    w_record = work_commands.add_parser(
        "record", help="record one builder or reviewer round entry"
    )
    w_record.add_argument("--id", required=True)
    w_record.add_argument("--round", type=int, required=True)
    w_record.add_argument("--role", choices=("builder", "reviewer"), required=True)
    w_record.add_argument("--head", required=True, help="head git snapshot")
    w_record.add_argument(
        "--evidence", type=_target, help="builder: JSON evidence file"
    )
    w_record.add_argument(
        "--findings", type=_target, help="reviewer: JSON findings file"
    )
    w_record.add_argument(
        "--coverage", type=_target, help="reviewer: JSON coverage-manifest file"
    )
    w_record.add_argument("--decision", choices=VALID_DECISIONS)
    w_record.add_argument("--target", type=_target, default=Path.cwd())

    w_check = work_commands.add_parser(
        "check", help="check whether it is safe to continue this work item"
    )
    w_check.add_argument("--id", required=True)
    w_check.add_argument("--head", required=True, help="current git snapshot")
    w_check.add_argument("--json", action="store_true")
    w_check.add_argument("--target", type=_target, default=Path.cwd())

    w_close = work_commands.add_parser("close", help="close a work item")
    w_close.add_argument("--id", required=True)
    w_close.add_argument("--outcome", choices=VALID_OUTCOMES, required=True)
    w_close.add_argument("--target", type=_target, default=Path.cwd())

    w_status = work_commands.add_parser(
        "status", help="show one or all open work items"
    )
    w_status.add_argument("--id")
    w_status.add_argument("--json", action="store_true")
    w_status.add_argument("--target", type=_target, default=Path.cwd())

    w_log = work_commands.add_parser("log", help="print one work item's round history")
    w_log.add_argument("--id", required=True)
    w_log.add_argument("--target", type=_target, default=Path.cwd())

    w_triage = work_commands.add_parser(
        "triage",
        help="record the human's address/defer disposition for one outer-loop round",
    )
    w_triage.add_argument("--id", required=True)
    w_triage.add_argument("--round", type=int, required=True)
    w_triage.add_argument(
        "--triage", type=_target, required=True, help="JSON triage payload file"
    )
    w_triage.add_argument("--target", type=_target, default=Path.cwd())

    w_escalate = work_commands.add_parser(
        "escalate",
        help="append one local, gitignored escalation record",
    )
    w_escalate.add_argument("--id", required=True)
    w_escalate.add_argument("--trigger", required=True)
    w_escalate.add_argument("--cause", required=True)
    w_escalate.add_argument("--phase", choices=("inner", "outer"))
    w_escalate.add_argument("--round", type=int, dest="round_number")
    w_escalate.add_argument("--target", type=_target, default=Path.cwd())

    w_escalations = work_commands.add_parser(
        "escalations", help="print recorded escalations, most projects skim this"
    )
    w_escalations.add_argument("--since", help="ISO 8601 timestamp lower bound")
    w_escalations.add_argument("--target", type=_target, default=Path.cwd())

    git_parser = commands.add_parser(
        "git", help="guarded git/GitHub mutation for one work item's own branch"
    )
    git_commands = git_parser.add_subparsers(dest="git_command", required=True)

    g_branch = git_commands.add_parser(
        "branch", help="create the work item's own branch from a base snapshot"
    )
    g_branch.add_argument("--id", required=True)
    g_branch.add_argument("--base", required=True, help="base git snapshot")
    g_branch.add_argument("--target", type=_target, default=Path.cwd())

    g_commit = git_commands.add_parser(
        "commit", help="commit outstanding changes on the work item's own branch"
    )
    g_commit.add_argument("--id", required=True)
    g_commit.add_argument("--message", required=True)
    g_commit.add_argument("--target", type=_target, default=Path.cwd())

    g_push = git_commands.add_parser(
        "push", help="push the work item's own branch, never the default branch"
    )
    g_push.add_argument("--id", required=True)
    g_push.add_argument("--target", type=_target, default=Path.cwd())

    g_open_pr = git_commands.add_parser(
        "open-pr",
        help="open a draft PR once codev work check reports ok_ready_for_pr",
    )
    g_open_pr.add_argument("--id", required=True)
    g_open_pr.add_argument("--title", required=True)
    g_open_pr.add_argument("--body", help="literal PR body text")
    g_open_pr.add_argument("--body-file", type=_target, help="path to a PR body file")
    g_open_pr.add_argument("--base", help="defaults to the repository's default branch")
    g_open_pr.add_argument("--target", type=_target, default=Path.cwd())

    g_mark_ready = git_commands.add_parser(
        "mark-ready",
        help="regenerate the PR body from round-state and mark it ready for review",
    )
    g_mark_ready.add_argument("--id", required=True)
    g_mark_ready.add_argument("--target", type=_target, default=Path.cwd())
    return parser


def _warn_deprecated(old: str, new: str) -> None:
    print(
        f"codev: {old} is deprecated; use {new} instead "
        "(will be removed in a future major version).",
        file=sys.stderr,
    )


def _apply_deprecated_aliases(argv: list[str]) -> list[str]:
    """Rewrite pre-Phase-3 command forms onto their replacements, with a warning."""
    if not argv:
        return argv
    head, rest = argv[0], argv[1:]

    if head == "fixture" and rest and rest[0] == "create":
        _warn_deprecated("'fixture create'", "'eval fixture create'")
        return ["eval", "fixture", *rest]

    if head == "eval" and (not rest or rest[0] not in _DEPRECATED_EVAL_SUBCOMMANDS):
        _warn_deprecated("'eval <name>'", "'eval run <name>'")
        return ["eval", "run", *rest]

    if head == "check":
        _warn_deprecated("'check'", "'status'")
        return ["status", *rest]

    if head == "doctor":
        _warn_deprecated("'doctor'", "'status --verbose'")
        return ["status", "--verbose", *rest]

    return argv


def _run_status_command(args: argparse.Namespace) -> int:
    target = args.target.resolve()
    result = check_project(target)
    platforms = list(_read_lock(target).get("platforms", []))
    work_items = work_module.describe_all(target=target)
    in_progress = sum(1 for item in work_items if item["status"] == "in_progress")

    payload: dict[str, object] = {
        "codev_version": __version__,
        "target": str(target),
        "healthy": result.ok,
        "managed_files": result.managed_files,
        "issues": list(result.issues),
        "adapters": platforms,
        "work_items_in_progress": in_progress,
    }
    if args.verbose:
        payload["python_version"] = platform.python_version()
        payload["system"] = platform.system()

    if args.json:
        print(json.dumps(payload))
    else:
        print(f"CoDev {__version__} - {target}")
        if args.verbose:
            print(f"Python {platform.python_version()} ({platform.system()})")
        if result.ok:
            print(f"Bundle: healthy ({result.managed_files} managed files, no drift)")
        else:
            print(f"Bundle: {len(result.issues)} issue(s):")
            for issue in result.issues:
                print(f"  - {issue}")
        print(f"Adapters: {', '.join(platforms) if platforms else 'none'}")
        print(f"Work items in progress: {in_progress}")
    return 0 if result.ok else 1


def _run_adapter_command(args: argparse.Namespace) -> int:
    target = args.target.resolve()

    if args.adapter_command == "list":
        platforms = list(_read_lock(target).get("platforms", []))
        if args.json:
            print(json.dumps(platforms))
        elif platforms:
            for name in platforms:
                print(name)
        else:
            print("No adapters installed.")
        return 0

    if args.adapter_command == "add":
        plan = plan_update(
            target, [args.platform], programming_language=args.programming_language
        )
        print(format_plan(plan))
        if plan.conflicts:
            print(f"Adapter add stopped: {len(plan.conflicts)} conflict(s).")
            return 2
        if args.dry_run:
            print("Dry run complete; no files were written.")
            return 0
        apply_plan(target, plan)
        print(f"Added adapter {args.platform!r} in {target}")
        return 0

    if args.adapter_command == "verify":
        result = verify_adapter(args.platform, target=target)
        if args.json:
            print(
                json.dumps(
                    {
                        "platform": result.platform,
                        "ok": result.ok,
                        "findings": [
                            {
                                "role": finding.role,
                                "path": finding.path,
                                "ok": finding.ok,
                                "problems": list(finding.problems),
                            }
                            for finding in result.findings
                        ],
                    }
                )
            )
        else:
            for finding in result.findings:
                if finding.ok:
                    print(f"{finding.role} ({finding.path}): ok")
                else:
                    print(f"{finding.role} ({finding.path}): FAILED")
                    for problem in finding.problems:
                        print(f"  - {problem}")
        return 0 if result.ok else 1

    return 2


def _run_config_command(args: argparse.Namespace) -> int:
    target = args.target.resolve()

    if args.config_command == "get":
        result = config_module.resolve(args.key, target=target)
        if result is None:
            if args.json:
                print(json.dumps(None))
            else:
                print(f"{args.key}: not set")
            return 1
        if args.json:
            print(json.dumps({"value": result.value, "source": result.source}))
        else:
            print(f"{result.value} (from {result.source})")
        return 0

    if args.config_command == "set":
        path = config_module.set_value(
            args.key, args.value, target=target, global_scope=args.global_scope
        )
        print(f"Set {args.key!r} in {path}")
        return 0

    if args.config_command == "list":
        values = config_module.list_values(target=target)
        if args.json:
            print(
                json.dumps(
                    {
                        key: {"value": item.value, "source": item.source}
                        for key, item in values.items()
                    }
                )
            )
        elif not values:
            print("No configuration set.")
        else:
            for key in sorted(values):
                item = values[key]
                print(f"{key} = {item.value} (from {item.source})")
        return 0

    return 2


def _self_update_hint() -> str:
    if shutil.which("pipx"):
        return "Run: pipx upgrade open-codev-workflow"
    if shutil.which("uv"):
        return "Run: uv tool upgrade open-codev-workflow"
    return (
        "Upgrade with the tool you used to install CoDev, for example:\n"
        "  pipx upgrade open-codev-workflow\n"
        "  uv tool upgrade open-codev-workflow"
    )


def _run_self_command(args: argparse.Namespace) -> int:
    if args.self_command == "version":
        print(f"CoDev {__version__}")
        return 0
    if args.self_command == "update":
        print(_self_update_hint())
        return 0
    return 2


def _run_work_command(args: argparse.Namespace) -> int:
    target = args.target.resolve()
    if args.work_command == "start":
        path = work_module.start(
            args.id, args.base, target=target, max_rounds=args.max_rounds
        )
        print(f"Started work item {args.id} at {path}")
        return 0

    if args.work_command == "record":
        if args.role == "builder":
            if args.evidence is None:
                raise WorkError("--evidence is required when --role builder")
            evidence = work_module.load_json_file(args.evidence)
            work_module.record_builder(
                args.id, args.round, args.head, evidence, target=target
            )
        else:
            if args.findings is None or args.decision is None:
                raise WorkError(
                    "--findings and --decision are required when --role reviewer"
                )
            findings = work_module.load_json_file(args.findings)
            coverage = (
                work_module.load_json_file(args.coverage) if args.coverage else {}
            )
            work_module.record_reviewer(
                args.id,
                args.round,
                args.head,
                findings,
                coverage,
                args.decision,
                target=target,
            )
        print(f"Recorded round {args.round} ({args.role}) for {args.id}")
        return 0

    if args.work_command == "check":
        result = work_module.check(args.id, args.head, target=target)
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": result.ok,
                        "reason": result.reason,
                        "message": result.message,
                    }
                )
            )
        else:
            print(f"{result.reason}: {result.message}")
        return 0 if result.ok else 1

    if args.work_command == "close":
        work_module.close(args.id, args.outcome, target=target)
        print(f"Closed work item {args.id} as {args.outcome}")
        return 0

    if args.work_command == "status":
        if args.id:
            summaries = [work_module.describe(args.id, target=target)]
        else:
            summaries = work_module.describe_all(target=target)
        if args.json:
            print(json.dumps(summaries[0] if args.id else summaries))
        elif not summaries:
            print("No open work items.")
        else:
            for item in summaries:
                phase = item["current_phase"]
                print(
                    f"{item['work_item_id']}: {item['status']} "
                    f"(round {item['current_round']} [{phase}]/"
                    f"{item['max_rounds'][phase]}, "
                    f"latest decision: {item['latest_decision']})"
                )
        return 0

    if args.work_command == "log":
        print(work_module.log_text(args.id, target=target), end="")
        return 0

    if args.work_command == "triage":
        triage = work_module.load_json_file(args.triage)
        work_module.record_triage(args.id, args.round, triage, target=target)
        print(f"Recorded triage for round {args.round} of {args.id}")
        return 0

    if args.work_command == "escalate":
        work_module.record_escalation(
            args.id,
            args.trigger,
            args.cause,
            target=target,
            phase=args.phase,
            round_number=args.round_number,
        )
        print(f"Recorded escalation for {args.id}: {args.trigger}")
        return 0

    if args.work_command == "escalations":
        print(work_module.escalations_text(target=target, since=args.since), end="")
        return 0

    return 2


def _run_git_command(args: argparse.Namespace) -> int:
    target = args.target.resolve()
    if args.git_command == "branch":
        branch = git_ops_module.create_branch(args.id, args.base, target=target)
        print(f"Created branch {branch} for {args.id}")
        return 0

    if args.git_command == "commit":
        head = git_ops_module.commit(args.id, args.message, target=target)
        print(f"Committed {head} on {args.id}'s branch")
        return 0

    if args.git_command == "push":
        git_ops_module.push(args.id, target=target)
        print(f"Pushed {args.id}'s branch")
        return 0

    if args.git_command == "open-pr":
        if args.body_file is not None:
            body = args.body_file.read_text(encoding="utf-8")
        elif args.body is not None:
            body = args.body
        else:
            raise git_ops_module.GitOpsError("either --body or --body-file is required")
        url = git_ops_module.open_pr(
            args.id, args.title, body, target=target, base=args.base
        )
        print(url)
        return 0

    if args.git_command == "mark-ready":
        git_ops_module.mark_ready(args.id, target=target)
        print(f"Marked {args.id}'s pull request ready for review")
        return 0

    return 2


def _format_snapshot_report(report: dict[str, Any]) -> str:
    """Render a skill performance snapshot as an aligned category matrix."""
    rows = [(category, data) for category, data in sorted(report["categories"].items())]
    rows.append(("Overall", report["overall"]))
    name_width = max(len("Category"), *(len(name) for name, _ in rows))

    def line(name: str, with_pct: str, without_pct: str, delta: str) -> str:
        return f"{name:<{name_width}}  {with_pct:>10}  {without_pct:>14}  {delta:>9}"

    lines = [
        f"Skill: {report['skill']} ({report['repetitions']} repetitions)",
        "",
        line("Category", "With-skill", "Without-skill", "Delta"),
        "-" * (name_width + 40),
    ]
    for name, data in rows:
        if name == "Overall":
            lines.append("-" * (name_width + 40))
        lines.append(
            line(
                name,
                f"{data['with_skill_percentage']}%",
                f"{data['without_skill_percentage']}%",
                f"{data['delta']:+.1f}pp",
            )
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    args = _parser().parse_args(_apply_deprecated_aliases(raw_argv))
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

        if args.command == "status":
            return _run_status_command(args)

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
        if args.command == "eval" and args.eval_command == "fixture":
            created = create_fixture(args.name, args.target, args.include)
            print(f"Created fixture at {created}")
            return 0
        if args.command == "eval" and args.eval_command == "run":
            passed = evaluate(
                args.name,
                args.target,
                args.output,
                with_skill=not args.without_skill,
            )
            print(f"Evaluation {'passed' if passed else 'failed'}: {args.output}")
            return 0 if passed else 1
        if (
            args.command == "eval"
            and args.eval_command == "snapshot"
            and args.eval_snapshot_command == "run"
        ):
            report = run_snapshot(
                args.skill,
                args.target,
                args.output,
                repetitions=args.repetitions,
                only_categories=args.categories,
            )
            print(_format_snapshot_report(report))
            print(f"Full report: {args.output / 'snapshot.json'}")
            return 0
        if args.command == "adapter":
            return _run_adapter_command(args)
        if args.command == "config":
            return _run_config_command(args)
        if args.command == "self":
            return _run_self_command(args)
        if args.command == "work":
            return _run_work_command(args)
        if args.command == "git":
            return _run_git_command(args)
    except (
        CoDevError,
        EvaluationError,
        WorkError,
        ConfigError,
        AdapterVerificationError,
        git_ops_module.GitOpsError,
    ) as error:
        print(f"codev: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"codev: filesystem error: {error}", file=sys.stderr)
        return 2
    return 2
