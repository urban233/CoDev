# BSD 3-Clause License
#
# Copyright (c) 2026, Martin Urban, Hannah Kullik
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
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
from codev_workflow import hook_log as hook_log_module
from codev_workflow import task as task_module
from codev_workflow.adapter import AdapterVerificationError, verify_adapter
from codev_workflow.config import ConfigError
from codev_workflow.conflict_wizard import resolve_non_interactive, run_wizard
from codev_workflow.eval import (
    EvaluationError,
    create_task,
    evaluate,
    run_benchmark,
)
from codev_workflow.eval_nvidia import VERBS as _NVIDIA_VERBS
from codev_workflow.eval_nvidia import run_verb as _run_nvidia_verb
from codev_workflow.installer import (
    CoDevError,
    Resolution,
    _read_lock,
    apply_plan,
    check_project,
    codeowners_init,
    format_plan,
    plan_adapter_remove,
    plan_init,
    plan_remove,
    plan_update,
)
from codev_workflow.task import (
    VALID_DECISIONS,
    VALID_OUTCOMES,
    TaskError,
)

_AGENT_PLATFORMS = ("antigravity", "claude", "junie", "opencode")
_AGENT_PLATFORM_CHOICES = ("all", *_AGENT_PLATFORMS)


def _target(value: str) -> Path:
    return Path(value).expanduser()


def _skill_name(value: str) -> str:
    """A skill name never contains a path separator -- but `.agents/skills/`
    is exactly the path a developer sees when browsing for one, so typing
    `.agents/skills/<name>` (or a longer path ending in it, with or without
    a trailing slash) instead of the bare name is a natural mistake. Strip
    that prefix if present rather than failing (or, worse, silently
    resolving to a nonsense doubled path like `.agents/skills/.agents/skills/
    <name>`) further downstream."""
    marker = ".agents/skills/"
    index = value.replace("\\", "/").rstrip("/").find(marker)
    if index == -1:
        return value
    return value.replace("\\", "/").rstrip("/")[index + len(marker) :]


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
        "status", help="show installed bundle, adapters, and task health"
    )
    status.add_argument("--target", type=_target, default=Path.cwd())
    status.add_argument("--verbose", action="store_true")
    status.add_argument("--json", action="store_true")
    status.add_argument(
        "--since", help="ISO 8601 timestamp lower bound for gate-decision counts"
    )

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
    update.add_argument(
        "--resolve",
        action="store_true",
        help="walk conflicts interactively instead of aborting on them",
    )
    update.add_argument(
        "--on-conflict",
        choices=("abort", "override", "keep", "copy", "delete", "skip"),
        default="abort",
        help="apply one resolution to every conflict, non-interactively "
        "(default: abort, the previous behavior; skip applies everything "
        "else and leaves conflicts pending, unlike abort which writes "
        "nothing)",
    )

    remove = commands.add_parser(
        "remove", help="remove an unchanged CoDev installation"
    )
    remove.add_argument("--target", type=_target, default=Path.cwd())
    remove.add_argument("--dry-run", action="store_true", help="show the plan only")

    evaluation = commands.add_parser("eval", help="skill-evaluation tasks and runs")
    eval_commands = evaluation.add_subparsers(dest="eval_command", required=True)

    e_task = eval_commands.add_parser("task", help="manage evaluation tasks")
    e_task_commands = e_task.add_subparsers(dest="eval_task_command", required=True)
    e_task_create = e_task_commands.add_parser(
        "create", help="create an evaluation task"
    )
    e_task_create.add_argument("name")
    e_task_create.add_argument("--target", type=_target, required=True)
    e_task_create.add_argument("--include", action="append", required=True)

    e_task_run = e_task_commands.add_parser("run", help="run a local evaluation task")
    e_task_run.add_argument("name")
    e_task_run.add_argument("--target", type=_target, required=True)
    e_task_run.add_argument("--output", type=_target, required=True)
    e_task_run.add_argument(
        "--baseline",
        action="store_true",
        help="run the baseline condition -- without staging the task's skill "
        "into the worktree",
    )
    e_task_run.add_argument(
        "--agent",
        default=None,
        help="override the resolved OpenCode executable -- point at a "
        "fake-agent stub script for a zero-cost dry run of verifier/checks "
        "logic, instead of a real actor invocation",
    )
    e_task_run.add_argument(
        "--sandbox",
        choices=("worktree", "docker"),
        default="worktree",
        help="where the actor executes; 'docker' requires the task to "
        "declare an environment block in its task.json (see ADR-0027) -- "
        "worktree isolation on the host remains the default",
    )

    e_benchmark = eval_commands.add_parser(
        "benchmark", help="skill performance benchmarks (with/without comparisons)"
    )
    e_benchmark_commands = e_benchmark.add_subparsers(
        dest="eval_benchmark_command", required=True
    )
    e_benchmark_run = e_benchmark_commands.add_parser(
        "run", help="run every task for one skill, with and without it, repeated"
    )
    e_benchmark_run.add_argument("skill", type=_skill_name)
    e_benchmark_run.add_argument("--target", type=_target, required=True)
    e_benchmark_run.add_argument("--output", type=_target, required=True)
    e_benchmark_run.add_argument("--repetitions", type=int, default=3)
    e_benchmark_run.add_argument(
        "--category",
        dest="categories",
        action="append",
        help="restrict the run to this category; repeat to select several",
    )
    e_benchmark_run.add_argument(
        "--no-package",
        dest="package",
        action="store_false",
        default=True,
        help="do not write the skill's own evals/benchmark.json and "
        "evals/BENCHMARK.md eval trace (an unrestricted run packages by "
        "default; a --category-restricted run never packages)",
    )
    e_benchmark_run.add_argument(
        "--agent",
        default=None,
        help="override the resolved OpenCode executable for every trial in "
        "this run -- point at a fake-agent stub script for a zero-cost dry "
        "run of a whole category before spending real model budget, the "
        "same idea as 'eval task run --agent'",
    )
    e_benchmark_run.add_argument(
        "--sandbox",
        choices=("worktree", "docker"),
        default="worktree",
        help="where each trial's actor executes; 'docker' requires every "
        "task in this benchmark to declare an environment block in its "
        "task.json (see ADR-0027) -- worktree isolation on the host remains "
        "the default, same as 'eval task run --sandbox'",
    )

    e_doctor = eval_commands.add_parser(
        "doctor", help="check readiness for running an evaluation task"
    )
    e_doctor.add_argument("--target", type=_target, default=Path.cwd())

    e_report = eval_commands.add_parser(
        "report", help="render a trial's or benchmark's output directory as text"
    )
    e_report.add_argument("output", type=_target)

    e_show = eval_commands.add_parser(
        "show", help="show a packaged skill's eval trace (evals/benchmark.json)"
    )
    e_show.add_argument("skill", type=_skill_name)
    e_show.add_argument("--target", type=_target, default=Path.cwd())

    e_nvidia = eval_commands.add_parser(
        "nvidia",
        help="run the external NVIDIA SkillEvaluator against a skill directory",
    )
    e_nvidia_commands = e_nvidia.add_subparsers(
        dest="eval_nvidia_command", required=True
    )
    e_nvidia_tier3_commands = None
    for _nvidia_spec in _NVIDIA_VERBS:
        if len(_nvidia_spec.argv) == 1:
            _nvidia_group, _nvidia_dest = e_nvidia_commands, _nvidia_spec.name
        else:
            if e_nvidia_tier3_commands is None:
                e_nvidia_tier3 = e_nvidia_commands.add_parser(
                    "tier3", help="Tier 3 live-agent expert aliases"
                )
                e_nvidia_tier3_commands = e_nvidia_tier3.add_subparsers(
                    dest="eval_nvidia_tier3_command", required=True
                )
            _nvidia_group, _nvidia_dest = e_nvidia_tier3_commands, _nvidia_spec.argv[-1]
        _nvidia_verb_parser = _nvidia_group.add_parser(
            _nvidia_dest, help=f"skillevaluator {' '.join(_nvidia_spec.argv)}"
        )
        if _nvidia_spec.needs_target:
            _nvidia_verb_parser.add_argument("skill_path", type=_target)
        _nvidia_verb_parser.add_argument("--output", type=_target, required=True)
        _nvidia_verb_parser.add_argument(
            "--timeout",
            type=int,
            default=900,
            dest="timeout_seconds",
            help="subprocess timeout in seconds (default: 900)",
        )
        _nvidia_verb_parser.add_argument(
            "--extra",
            dest="extra",
            action="append",
            default=[],
            metavar="FLAG",
            help="one additional skillevaluator flag or value, forwarded "
            "verbatim after CoDev's own flags in the order given; repeat "
            "for more. Use --extra=VALUE (with '=', not a space) whenever "
            "VALUE itself starts with '-', e.g. --extra=--env-mode "
            "--extra=docker",
        )
        _nvidia_verb_parser.set_defaults(nvidia_verb=_nvidia_spec.name)

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

    a_remove = adapter_commands.add_parser(
        "remove", help="remove one adapter from an existing installation"
    )
    # No `choices=` here, unlike `add`/`verify`: a platform an earlier CoDev
    # version installed but the current one no longer supports (e.g. Codex,
    # ADR-0031) must still be removable. `installer.plan_adapter_remove`
    # does the real validation -- installed-or-currently-valid -- and raises
    # a `CoDevError` for anything else, which main() already reports cleanly.
    a_remove.add_argument("platform")
    a_remove.add_argument("--target", type=_target, default=Path.cwd())
    a_remove.add_argument("--dry-run", action="store_true", help="show the plan only")

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

    codeowners_parser = commands.add_parser(
        "codeowners", help="scaffold a starter CODEOWNERS file; run directly by a human"
    )
    codeowners_commands = codeowners_parser.add_subparsers(
        dest="codeowners_command", required=True
    )
    codeowners_init_parser = codeowners_commands.add_parser(
        "init", help="write .github/CODEOWNERS; refuses if one already exists"
    )
    codeowners_init_parser.add_argument("--target", type=_target, default=Path.cwd())

    task = commands.add_parser(
        "task", help="track builder/reviewer round state for one task"
    )
    task_commands = task.add_subparsers(dest="task_command", required=True)

    t_start = task_commands.add_parser("start", help="open a new task")
    t_start.add_argument("--id", required=True)
    t_start.add_argument("--base", required=True, help="base git snapshot")
    t_start.add_argument(
        "--max-rounds",
        type=int,
        default=None,
        help="applies to both phases; defaults to 2/2",
    )
    t_start.add_argument(
        "--link", default=None, help="pointer to the artifact authorizing this work"
    )
    t_start.add_argument(
        "--summary", default=None, help="one-line human-readable description"
    )
    t_start.add_argument(
        "--description",
        default=None,
        help="fuller why/what, proportional to the work's size; used to build "
        "the pull request description -- omit for a small item where "
        "--summary is already enough",
    )
    t_start.add_argument(
        "--owner", default=None, help="defaults to the detected local/gh identity"
    )
    t_start.add_argument(
        "--github-issue",
        type=int,
        default=None,
        help="populate --link/--summary from this issue unless given explicitly",
    )
    t_start.add_argument(
        "--no-github-issue",
        action="store_true",
        help="acknowledge this item intentionally has no GitHub issue link -- "
        "required in place of --github-issue/--link when the repository has "
        "a GitHub remote and neither was given",
    )
    t_start.add_argument(
        "--entry",
        choices=("takeover", "direct-review"),
        default=None,
        help=(
            "takeover: unfinished human work continues in the inner loop; "
            "direct-review: finished human work skips straight to the outer "
            "loop; omit for the default cold start"
        ),
    )
    t_start.add_argument("--target", type=_target, default=Path.cwd())

    t_record = task_commands.add_parser(
        "record", help="record one builder or reviewer round entry"
    )
    t_record.add_argument("--id", required=True)
    t_record.add_argument("--round", type=int, required=True)
    t_record.add_argument("--role", choices=("builder", "reviewer"), required=True)
    t_record.add_argument("--head", required=True, help="head git snapshot")
    t_record.add_argument(
        "--evidence", type=_target, help="builder: JSON evidence file"
    )
    t_record.add_argument(
        "--findings", type=_target, help="reviewer: JSON findings file"
    )
    t_record.add_argument(
        "--coverage", type=_target, help="reviewer: JSON coverage-manifest file"
    )
    t_record.add_argument(
        "--selection",
        type=_target,
        help="reviewer, outer phase: JSON specialist-selection audit file",
    )
    t_record.add_argument("--decision", choices=VALID_DECISIONS)
    t_record.add_argument("--target", type=_target, default=Path.cwd())

    t_check = task_commands.add_parser(
        "check", help="check whether it is safe to continue this task"
    )
    t_check.add_argument("--id", required=True)
    t_check.add_argument("--head", required=True, help="current git snapshot")
    t_check.add_argument("--json", action="store_true")
    t_check.add_argument("--target", type=_target, default=Path.cwd())

    t_close = task_commands.add_parser("close", help="close a task")
    t_close.add_argument("--id", required=True)
    t_close.add_argument("--outcome", choices=VALID_OUTCOMES, required=True)
    t_close.add_argument("--target", type=_target, default=Path.cwd())

    t_reopen = task_commands.add_parser(
        "reopen",
        help=(
            "human-authorized recovery for a task stuck behind a round "
            "cap, drift, or a close -- never run without an explicit human "
            "decision"
        ),
    )
    t_reopen.add_argument("--id", required=True)
    t_reopen.add_argument(
        "--head", required=True, help="current git snapshot to re-baseline onto"
    )
    t_reopen.add_argument(
        "--reason", required=True, help="why this recovery is authorized"
    )
    t_reopen.add_argument(
        "--max-rounds",
        type=int,
        default=None,
        help="optionally raise the round cap; applies to both phases",
    )
    t_reopen.add_argument(
        "--by", default=None, help="defaults to the detected local/gh identity"
    )
    t_reopen.add_argument("--target", type=_target, default=Path.cwd())

    t_waive = task_commands.add_parser(
        "waive",
        help=(
            "human-authorized: this coverage dimension will not be run for "
            "this task -- never run without an explicit human decision"
        ),
    )
    t_waive.add_argument("--id", required=True)
    t_waive.add_argument(
        "--dimension", required=True, help="one of REQUIRED_COVERAGE_DIMENSIONS"
    )
    t_waive.add_argument("--reason", required=True, help="why this waiver is granted")
    t_waive.add_argument(
        "--by", default=None, help="defaults to the detected local/gh identity"
    )
    t_waive.add_argument("--target", type=_target, default=Path.cwd())

    t_relink = task_commands.add_parser(
        "relink",
        help=(
            "correct link_ref after `start` already ran -- the recovery path "
            "when a GitHub issue is created only after round-state exists"
        ),
    )
    t_relink.add_argument("--id", required=True)
    t_relink_source = t_relink.add_mutually_exclusive_group(required=True)
    t_relink_source.add_argument(
        "--github-issue", type=int, help="resolve --link from this issue's URL"
    )
    t_relink_source.add_argument(
        "--link", help="pointer to the artifact authorizing this work"
    )
    t_relink.add_argument(
        "--by", default=None, help="defaults to the detected local/gh identity"
    )
    t_relink.add_argument("--target", type=_target, default=Path.cwd())

    t_status = task_commands.add_parser("status", help="show one or all open tasks")
    t_status.add_argument("--id")
    t_status.add_argument("--json", action="store_true")
    t_status.add_argument("--target", type=_target, default=Path.cwd())

    t_size = task_commands.add_parser(
        "size",
        help=(
            "report a task's non-generated changed-line/file count against "
            "review.max_lines/review.max_files"
        ),
    )
    t_size.add_argument("--id", required=True)
    t_size.add_argument("--json", action="store_true")
    t_size.add_argument("--target", type=_target, default=Path.cwd())

    t_log = task_commands.add_parser("log", help="print one task's round history")
    t_log.add_argument("--id", required=True)
    t_log.add_argument("--target", type=_target, default=Path.cwd())

    t_triage = task_commands.add_parser(
        "triage",
        help="record the human's address/defer disposition for one outer-loop round",
    )
    t_triage.add_argument("--id", required=True)
    t_triage.add_argument("--round", type=int, required=True)
    t_triage.add_argument(
        "--triage", type=_target, required=True, help="JSON triage payload file"
    )
    t_triage.add_argument(
        "--by", default=None, help="defaults to the detected local/gh identity"
    )
    t_triage.add_argument("--target", type=_target, default=Path.cwd())

    t_escalate = task_commands.add_parser(
        "escalate",
        help="append one local, gitignored escalation record",
    )
    t_escalate.add_argument("--id", required=True)
    t_escalate.add_argument("--trigger", required=True)
    t_escalate.add_argument("--cause", required=True)
    t_escalate.add_argument("--phase", choices=("inner", "outer"))
    t_escalate.add_argument("--round", type=int, dest="round_number")
    t_escalate.add_argument("--target", type=_target, default=Path.cwd())

    t_escalations = task_commands.add_parser(
        "escalations", help="print recorded escalations, most projects skim this"
    )
    t_escalations.add_argument("--since", help="ISO 8601 timestamp lower bound")
    t_escalations.add_argument("--target", type=_target, default=Path.cwd())

    git_parser = commands.add_parser(
        "git", help="guarded git/GitHub mutation for one task's own branch"
    )
    git_commands = git_parser.add_subparsers(dest="git_command", required=True)

    g_issue_create = git_commands.add_parser(
        "issue-create",
        help=(
            "push a delivery-plan task to GitHub as an issue; "
            "has no task precondition, runs before codev task start"
        ),
    )
    g_issue_create.add_argument("--title", required=True)
    g_issue_create.add_argument("--body", help="literal issue body text")
    g_issue_create.add_argument(
        "--body-file", type=_target, help="path to an issue body file"
    )
    g_issue_create.add_argument(
        "--path",
        action="append",
        default=[],
        dest="paths",
        help="repeatable; prints a CODEOWNERS-suggested assignee, never applied",
    )
    g_issue_create.add_argument(
        "--assignee", action="append", default=[], dest="assignees"
    )
    g_issue_create.add_argument("--target", type=_target, default=Path.cwd())

    g_issue_view = git_commands.add_parser(
        "issue-view",
        help=(
            "print a GitHub issue's body and all its comments as JSON; "
            "has no task precondition, read-only"
        ),
    )
    g_issue_view.add_argument("--number", type=int, required=True)
    g_issue_view.add_argument("--target", type=_target, default=Path.cwd())

    g_branch = git_commands.add_parser(
        "branch", help="create the task's own branch from a base snapshot"
    )
    g_branch.add_argument("--id", required=True)
    g_branch.add_argument(
        "--base",
        default=None,
        help="base git snapshot; defaults to the 'git.pr_base' config value, "
        "then the repository's default branch",
    )
    g_branch.add_argument(
        "--allow-dirty",
        action="store_true",
        help="proceed despite uncommitted worktree changes",
    )
    g_branch.add_argument("--target", type=_target, default=Path.cwd())

    g_commit = git_commands.add_parser(
        "commit", help="commit outstanding changes on the task's own branch"
    )
    g_commit.add_argument("--id", required=True)
    g_commit.add_argument("--message", required=True)
    g_commit_scope = g_commit.add_mutually_exclusive_group()
    g_commit_scope.add_argument(
        "--paths",
        nargs="+",
        default=None,
        help="stage and commit only these paths, instead of everything dirty",
    )
    g_commit_scope.add_argument(
        "--staged",
        action="store_true",
        help="commit exactly what is already staged; stage nothing new",
    )
    g_commit.add_argument(
        "--round",
        type=int,
        default=None,
        dest="round_number",
        help="builder round to record; requires --evidence",
    )
    g_commit.add_argument(
        "--evidence",
        type=_target,
        default=None,
        help="builder: JSON evidence file; with --round, atomically records "
        "the builder receipt against the resulting commit",
    )
    g_commit.add_argument("--target", type=_target, default=Path.cwd())

    g_push = git_commands.add_parser(
        "push", help="push the task's own branch, never the default branch"
    )
    g_push.add_argument("--id", required=True)
    g_push.add_argument("--target", type=_target, default=Path.cwd())

    g_open_pr = git_commands.add_parser(
        "open-pr",
        help="open a draft PR once codev task check reports ok_ready_for_pr",
    )
    g_open_pr.add_argument("--id", required=True)
    g_open_pr.add_argument("--title", required=True)
    g_open_pr.add_argument(
        "--body",
        help="literal PR body text; omit both this and --body-file to "
        "generate one from the task's description and coverage",
    )
    g_open_pr.add_argument("--body-file", type=_target, help="path to a PR body file")
    g_open_pr.add_argument(
        "--base",
        help="defaults to the 'git.pr_base' config value, then the "
        "repository's default branch",
    )
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

    if head == "check":
        _warn_deprecated("'check'", "'status'")
        return ["status", *rest]

    if head == "doctor":
        _warn_deprecated("'doctor'", "'status --verbose'")
        return ["status", "--verbose", *rest]

    return argv


def _print_size_report(task_id: str, *, target: Path) -> None:
    """Surface a task's running size where splitting is still cheap -- see
    docs/features/small-prs/design.md. Never raises: a measurement failure
    must not block the commit or pull-request path it decorates."""
    try:
        size = git_ops_module.task_size(task_id, target=target)
    except git_ops_module.GitOpsError:
        return
    status_word = "over budget" if size.over_budget else "within budget"
    print(
        f"Size: {size.lines_changed} line(s) (budget {size.max_lines}), "
        f"{size.files_changed} file(s) (budget {size.max_files}) -- {status_word}"
    )


def _in_progress_owner_counts(tasks: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in tasks:
        if item["status"] != "in_progress":
            continue
        owner = item.get("owner")
        if not owner:
            continue
        counts[owner] = counts.get(owner, 0) + 1
    return counts


def _task_sizes(
    tasks: list[dict[str, Any]], *, target: Path
) -> dict[str, dict[str, int | bool]]:
    in_progress_ids = [
        item["task_id"] for item in tasks if item["status"] == "in_progress"
    ]
    sizes: dict[str, dict[str, int | bool]] = {}
    for task_id in in_progress_ids:
        size = git_ops_module.task_size(task_id, target=target)
        sizes[task_id] = {
            "lines_changed": size.lines_changed,
            "files_changed": size.files_changed,
            "max_lines": size.max_lines,
            "max_files": size.max_files,
            "over_budget": size.over_budget,
        }
    return sizes


def _changed_file_overlaps(
    tasks: list[dict[str, Any]], *, target: Path
) -> list[dict[str, list[str]]]:
    in_progress_ids = [
        item["task_id"] for item in tasks if item["status"] == "in_progress"
    ]
    changed = {
        item_id: set(git_ops_module.changed_files(item_id, target=target))
        for item_id in in_progress_ids
    }
    overlaps: list[dict[str, list[str]]] = []
    for index, first in enumerate(in_progress_ids):
        for second in in_progress_ids[index + 1 :]:
            shared = sorted(changed[first] & changed[second])
            if shared:
                overlaps.append({"tasks": [first, second], "paths": shared})
    return overlaps


def _run_status_command(args: argparse.Namespace) -> int:
    target = args.target.resolve()
    result = check_project(target)
    platforms = list(_read_lock(target).get("platforms", []))
    tasks = task_module.describe_all(target=target)
    in_progress = sum(1 for item in tasks if item["status"] == "in_progress")

    payload: dict[str, object] = {
        "codev_version": __version__,
        "target": str(target),
        "healthy": result.ok,
        "managed_files": result.managed_files,
        "issues": list(result.issues),
        "adapters": platforms,
        "tasks_in_progress": in_progress,
    }
    owner_counts: dict[str, int] = {}
    overlaps: list[dict[str, list[str]]] = []
    sizes: dict[str, dict[str, int | bool]] = {}
    gate_decisions: dict[str, dict[str, int]] = {}
    if args.verbose:
        payload["python_version"] = platform.python_version()
        payload["system"] = platform.system()
        owner_counts = _in_progress_owner_counts(tasks)
        overlaps = _changed_file_overlaps(tasks, target=target)
        sizes = _task_sizes(tasks, target=target)
        payload["tasks_in_progress_by_owner"] = owner_counts
        payload["changed_file_overlaps"] = overlaps
        payload["task_sizes"] = sizes
        decisions = hook_log_module.read_decisions(target=target, since=args.since)
        gate_decisions = hook_log_module.summarize_decisions(decisions)
        payload["gate_decisions"] = gate_decisions

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
        print(f"Tasks in progress: {in_progress}")
        if args.verbose and owner_counts:
            print("Work in progress by owner:")
            for owner, count in sorted(owner_counts.items()):
                print(f"  {owner}: {count}")
        if args.verbose and overlaps:
            print("Changed-file overlaps between concurrently open tasks:")
            for overlap in overlaps:
                items = " & ".join(overlap["tasks"])
                paths = ", ".join(overlap["paths"])
                print(f"  {items}: {paths}")
        if args.verbose and sizes:
            print("Task sizes (non-generated changed lines/files vs. budget):")
            for task_id in sorted(sizes):
                size = sizes[task_id]
                flag = " (over budget)" if size["over_budget"] else ""
                print(
                    f"  {task_id}: {size['lines_changed']}/{size['max_lines']} "
                    f"lines, {size['files_changed']}/{size['max_files']} files"
                    f"{flag}"
                )
        if args.verbose:
            if gate_decisions:
                print("Gate decisions:")
                for hook in sorted(gate_decisions):
                    by_decision = gate_decisions[hook]
                    counts = ", ".join(
                        f"{decision}={count}"
                        for decision, count in sorted(by_decision.items())
                    )
                    print(f"  {hook}: {counts}")
            else:
                print("Gate decisions: none recorded yet")
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

    if args.adapter_command == "remove":
        plan = plan_adapter_remove(target, args.platform)
        print(format_plan(plan))
        if plan.conflicts:
            print(f"Adapter remove stopped: {len(plan.conflicts)} conflict(s).")
            return 2
        if args.dry_run:
            print("Dry run complete; no files were written.")
            return 0
        apply_plan(target, plan)
        print(f"Removed adapter {args.platform!r} from {target}")
        return 0

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


def _run_codeowners_command(args: argparse.Namespace) -> int:
    if args.codeowners_command == "init":
        destination = codeowners_init(args.target.resolve())
        print(f"Wrote a starter CODEOWNERS file at {destination}")
        return 0
    return 2


def _run_task_command(args: argparse.Namespace) -> int:
    target = args.target.resolve()
    if args.task_command == "start":
        link_ref = args.link
        summary = args.summary
        if args.github_issue is not None:
            issue = git_ops_module.fetch_issue(args.github_issue, target=target)
            if link_ref is None:
                link_ref = issue["url"]
            if summary is None:
                summary = issue["title"]
        if (
            link_ref is None
            and not args.no_github_issue
            and git_ops_module.has_github_remote(target=target)
        ):
            raise TaskError(
                "this repository has a GitHub remote but no issue linkage was "
                "given for this task -- run `codev git issue-create` "
                "first and pass --github-issue N (or --link), or pass "
                "--no-github-issue to acknowledge this item intentionally "
                "has none"
            )
        owner = args.owner
        if owner is None:
            owner = git_ops_module.detect_identity(target=target)
        path = task_module.start(
            args.id,
            args.base,
            target=target,
            max_rounds=args.max_rounds,
            link_ref=link_ref,
            summary=summary,
            description=args.description,
            owner=owner,
            entry=args.entry,
        )
        print(f"Started task {args.id} at {path}")
        return 0

    if args.task_command == "record":
        if args.role == "builder":
            if args.evidence is None:
                raise TaskError("--evidence is required when --role builder")
            evidence = task_module.load_json_file(args.evidence)
            task_module.record_builder(
                args.id, args.round, args.head, evidence, target=target
            )
        else:
            if args.findings is None or args.decision is None:
                raise TaskError(
                    "--findings and --decision are required when --role reviewer"
                )
            findings = task_module.load_json_file(args.findings)
            coverage = (
                task_module.load_json_file(args.coverage) if args.coverage else {}
            )
            selection = (
                task_module.load_json_file(args.selection) if args.selection else None
            )
            task_module.record_reviewer(
                args.id,
                args.round,
                args.head,
                findings,
                coverage,
                args.decision,
                target=target,
                specialist_selection=selection,
            )
        print(f"Recorded round {args.round} ({args.role}) for {args.id}")
        return 0

    if args.task_command == "check":
        result = task_module.check(args.id, args.head, target=target)
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
            note = task_module.triage_note(args.id, target=target)
            if note:
                print(note)
        return 0 if result.ok else 1

    if args.task_command == "close":
        task_module.close(args.id, args.outcome, target=target)
        print(f"Closed task {args.id} as {args.outcome}")
        return 0

    if args.task_command == "reopen":
        by = args.by
        if by is None:
            by = git_ops_module.detect_identity(target=target)
        path = task_module.reopen(
            args.id,
            args.head,
            args.reason,
            target=target,
            max_rounds=args.max_rounds,
            by=by,
        )
        print(f"Reopened task {args.id} at {path}")
        return 0

    if args.task_command == "waive":
        by = args.by
        if by is None:
            by = git_ops_module.detect_identity(target=target)
        path = task_module.waive(
            args.id,
            args.dimension,
            args.reason,
            target=target,
            by=by,
        )
        print(f"Waived {args.dimension!r} for task {args.id} at {path}")
        return 0

    if args.task_command == "relink":
        link_ref = args.link
        if args.github_issue is not None:
            issue = git_ops_module.fetch_issue(args.github_issue, target=target)
            link_ref = issue["url"]
        by = args.by
        if by is None:
            by = git_ops_module.detect_identity(target=target)
        path = task_module.relink(
            args.id,
            link_ref,
            target=target,
            by=by,
        )
        print(f"Relinked task {args.id} to {link_ref!r} at {path}")
        return 0

    if args.task_command == "status":
        if args.id:
            summaries = [task_module.describe(args.id, target=target)]
        else:
            summaries = task_module.describe_all(target=target)
        if args.json:
            print(json.dumps(summaries[0] if args.id else summaries))
        elif not summaries:
            print("No open tasks.")
        else:
            for item in summaries:
                phase = item["current_phase"]
                print(
                    f"{item['task_id']}: {item['status']} "
                    f"(round {item['current_round']} [{phase}]/"
                    f"{item['max_rounds'][phase]}, "
                    f"latest decision: {item['latest_decision']})"
                )
        return 0

    if args.task_command == "size":
        size = git_ops_module.task_size(args.id, target=target)
        if args.json:
            print(
                json.dumps(
                    {
                        "task_id": args.id,
                        "lines_changed": size.lines_changed,
                        "files_changed": size.files_changed,
                        "max_lines": size.max_lines,
                        "max_files": size.max_files,
                        "over_budget": size.over_budget,
                    }
                )
            )
        else:
            status_word = "over budget" if size.over_budget else "within budget"
            print(
                f"{args.id}: {size.lines_changed} line(s) changed "
                f"(budget {size.max_lines}), {size.files_changed} file(s) "
                f"changed (budget {size.max_files}) -- {status_word}"
            )
        return 0

    if args.task_command == "log":
        print(task_module.log_text(args.id, target=target), end="")
        return 0

    if args.task_command == "triage":
        triage = task_module.load_json_file(args.triage)
        by = args.by
        if by is None:
            by = git_ops_module.detect_identity(target=target)
        task_module.record_triage(args.id, args.round, triage, target=target, by=by)
        print(f"Recorded triage for round {args.round} of {args.id}")
        return 0

    if args.task_command == "escalate":
        task_module.record_escalation(
            args.id,
            args.trigger,
            args.cause,
            target=target,
            phase=args.phase,
            round_number=args.round_number,
        )
        print(f"Recorded escalation for {args.id}: {args.trigger}")
        return 0

    if args.task_command == "escalations":
        print(task_module.escalations_text(target=target, since=args.since), end="")
        return 0

    return 2


def _run_git_command(args: argparse.Namespace) -> int:
    target = args.target.resolve()
    if args.git_command == "issue-create":
        if args.body_file is not None:
            body = args.body_file.read_text(encoding="utf-8")
        elif args.body is not None:
            body = args.body
        else:
            raise git_ops_module.GitOpsError("either --body or --body-file is required")
        if args.paths:
            suggested = git_ops_module.suggest_owners(args.paths, target=target)
            if suggested:
                print(f"Suggested owners (from CODEOWNERS): {', '.join(suggested)}")
        url = git_ops_module.create_issue(
            args.title, body, target=target, assignees=args.assignees
        )
        print(url)
        return 0

    if args.git_command == "issue-view":
        payload = git_ops_module.view_issue(args.number, target=target)
        print(json.dumps(payload))
        return 0

    if args.git_command == "branch":
        branch = git_ops_module.create_branch(
            args.id, args.base, target=target, allow_dirty=args.allow_dirty
        )
        print(f"Created branch {branch} for {args.id}")
        return 0

    if args.git_command == "commit":
        if (args.round_number is None) != (args.evidence is None):
            raise git_ops_module.GitOpsError(
                "--round and --evidence must be given together"
            )
        evidence = (
            task_module.load_json_file(args.evidence)
            if args.evidence is not None
            else None
        )
        head = git_ops_module.commit(
            args.id,
            args.message,
            target=target,
            paths=args.paths,
            staged=args.staged,
            round_number=args.round_number,
            evidence=evidence,
        )
        print(f"Committed {head} on {args.id}'s branch")
        _print_size_report(args.id, target=target)
        return 0

    if args.git_command == "push":
        git_ops_module.push(args.id, target=target)
        print(f"Pushed {args.id}'s branch")
        return 0

    if args.git_command == "open-pr":
        use_template = False
        if args.body_file is not None:
            body = args.body_file.read_text(encoding="utf-8")
        elif args.body is not None:
            body = args.body
        else:
            body = task_module.pr_description(args.id, target=target)
            use_template = True
        url = git_ops_module.open_pr(
            args.id,
            args.title,
            body,
            target=target,
            base=args.base,
            use_template=use_template,
        )
        print(url)
        _print_size_report(args.id, target=target)
        return 0

    if args.git_command == "mark-ready":
        git_ops_module.mark_ready(args.id, target=target)
        print(f"Marked {args.id}'s pull request ready for review")
        return 0

    return 2


def _format_benchmark_report(report: dict[str, Any]) -> str:
    """Render a skill performance benchmark as an aligned category matrix."""
    rows = [(category, data) for category, data in sorted(report["categories"].items())]
    rows.append(("Overall", report["overall"]))
    name_width = max(len("Category"), *(len(name) for name, _ in rows))

    def line(name: str, with_pct: str, baseline_pct: str, delta: str) -> str:
        return f"{name:<{name_width}}  {with_pct:>10}  {baseline_pct:>10}  {delta:>9}"

    lines = [
        f"Skill: {report['skill']} ({report['repetitions']} repetitions)",
        "",
        line("Category", "With-skill", "Baseline", "Delta"),
        "-" * (name_width + 36),
    ]
    for name, data in rows:
        if name == "Overall":
            lines.append("-" * (name_width + 36))
        lines.append(
            line(
                name,
                f"{data['with_skill_percentage']}%",
                f"{data['baseline_percentage']}%",
                f"{data['delta']:+.1f}pp",
            )
        )
    return "\n".join(lines)


def _run_eval_doctor_command(args: argparse.Namespace) -> int:
    """Fast, zero-cost readiness check before a real trial run."""
    ready = True
    print("codev eval doctor")
    git_path = shutil.which("git")
    if git_path:
        print(f"  git       pass  {git_path}")
    else:
        print("  git       fail  not found on PATH")
        ready = False
    opencode_path = shutil.which("opencode")
    if opencode_path:
        print(f"  opencode  pass  {opencode_path}")
    else:
        print("  opencode  fail  not found on PATH")
        ready = False
    if not ready:
        print(
            "codev: not ready -- install the missing tool(s) above before "
            "running a real task",
            file=sys.stderr,
        )
    return 0 if ready else 1


def _run_eval_report_command(args: argparse.Namespace) -> int:
    """Render a trial's or benchmark's output directory as plain text."""
    output: Path = args.output
    benchmark_path = output / "benchmark.json"
    result_path = output / "result.json"
    if benchmark_path.is_file():
        report = json.loads(benchmark_path.read_text(encoding="utf-8"))
        print(_format_benchmark_report(report))
        return 0
    if result_path.is_file():
        result = json.loads(result_path.read_text(encoding="utf-8"))
        judge = result.get("judge", {})
        judge_line = judge.get("status", "skipped")
        if judge.get("verdict"):
            judge_line = f"{judge_line} ({judge['verdict']})"
        print(f"Task: {result['task']['name']}")
        print(f"Outcome: {result['outcome']}")
        print(f"Actor: {result.get('actor', {}).get('status', 'skipped')}")
        print(f"Verifier: {result.get('verifier', {}).get('status', 'skipped')}")
        print(f"Judge: {judge_line}")
        return 0
    print(
        f"codev: no result.json or benchmark.json found in {output}",
        file=sys.stderr,
    )
    return 2


def _run_eval_show_command(args: argparse.Namespace) -> int:
    """Show a skill's packaged eval trace, if `codev eval benchmark run` has
    written one into its own directory (see docs/adr/0028-skill-packages-
    carry-their-own-eval-trace.md)."""
    target: Path = args.target.resolve()
    trace_path = target / ".agents" / "skills" / args.skill / "evals" / "benchmark.json"
    if not trace_path.is_file():
        print(
            f"codev: no eval trace found for skill '{args.skill}' "
            f"({trace_path}) -- run `codev eval benchmark run {args.skill} "
            "--target . --output <dir>` to create one",
            file=sys.stderr,
        )
        return 1
    report = json.loads(trace_path.read_text(encoding="utf-8"))
    print(_format_benchmark_report(report))
    generated_at = report.get("generated_at")
    if generated_at:
        print(f"\nGenerated: {generated_at}")
    print(f"Trace file: {trace_path}")
    return 0


def _run_eval_nvidia_command(args: argparse.Namespace) -> int:
    passed = _run_nvidia_verb(
        args.nvidia_verb,
        target=getattr(args, "skill_path", None),
        output=args.output,
        extra_flags=list(args.extra),
        timeout_seconds=args.timeout_seconds,
    )
    print(f"Evaluation {'passed' if passed else 'failed'}: {args.output}")
    return 0 if passed else 1


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
            resolve = getattr(args, "resolve", False)
            on_conflict = getattr(args, "on_conflict", "abort")
            if resolve and on_conflict != "abort":
                raise CoDevError("pass either --resolve or --on-conflict, not both")
            if plan.conflicts and (not resolve and on_conflict == "abort"):
                print(f"Update stopped: {len(plan.conflicts)} conflict(s).")
                return 2
            if args.command == "diff":
                print("Preview complete; no files were written.")
                return 0
            resolutions = None
            if plan.conflicts and resolve:
                resolutions = run_wizard(target, plan)
            elif plan.conflicts and on_conflict != "abort":
                resolutions = resolve_non_interactive(plan, Resolution(on_conflict))
            unresolved = apply_plan(target, plan, resolutions)
            if unresolved:
                print(
                    f"Updated CoDev bundle to {__version__} in {target}; "
                    f"{len(unresolved)} conflict(s) still unresolved:"
                )
                for op in unresolved:
                    print(f"  CONFLICT  {op.path} — {op.detail}")
                return 2
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
        if (
            args.command == "eval"
            and args.eval_command == "task"
            and args.eval_task_command == "create"
        ):
            created = create_task(args.name, args.target, args.include)
            print(f"Created task at {created}")
            return 0
        if (
            args.command == "eval"
            and args.eval_command == "task"
            and args.eval_task_command == "run"
        ):
            evaluate_kwargs: dict[str, Any] = {
                "with_skill": not args.baseline,
                "sandbox": args.sandbox,
            }
            if args.agent is not None:
                evaluate_kwargs["opencode"] = args.agent
            passed = evaluate(
                args.name,
                args.target,
                args.output,
                **evaluate_kwargs,
            )
            print(f"Evaluation {'passed' if passed else 'failed'}: {args.output}")
            return 0 if passed else 1
        if (
            args.command == "eval"
            and args.eval_command == "benchmark"
            and args.eval_benchmark_command == "run"
        ):
            benchmark_kwargs: dict[str, Any] = {
                "repetitions": args.repetitions,
                "only_categories": args.categories,
                "package": args.package,
                "sandbox": args.sandbox,
            }
            if args.agent is not None:
                benchmark_kwargs["opencode"] = args.agent
            report = run_benchmark(
                args.skill,
                args.target,
                args.output,
                **benchmark_kwargs,
            )
            print(_format_benchmark_report(report))
            print(f"Full report: {args.output / 'benchmark.json'}")
            return 0
        if args.command == "eval" and args.eval_command == "doctor":
            return _run_eval_doctor_command(args)
        if args.command == "eval" and args.eval_command == "report":
            return _run_eval_report_command(args)
        if args.command == "eval" and args.eval_command == "show":
            return _run_eval_show_command(args)
        if args.command == "eval" and args.eval_command == "nvidia":
            return _run_eval_nvidia_command(args)
        if args.command == "adapter":
            return _run_adapter_command(args)
        if args.command == "config":
            return _run_config_command(args)
        if args.command == "self":
            return _run_self_command(args)
        if args.command == "codeowners":
            return _run_codeowners_command(args)
        if args.command == "task":
            return _run_task_command(args)
        if args.command == "git":
            return _run_git_command(args)
    except (
        CoDevError,
        EvaluationError,
        TaskError,
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
