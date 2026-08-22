"""Thin subprocess wrapper around the external NVIDIA SkillEvaluator CLI.

This module never reimplements SkillEvaluator's own validation, scoring, or
live-agent logic. It resolves the external ``skillevaluator`` executable
(installed and authenticated by the user, exactly like ``opencode`` in
:mod:`codev_workflow.eval`), runs one verb as a subprocess with an isolated,
verb-specific environment, captures and redacts its stdout/stderr, copies
whatever native report file(s) the verb wrote into the caller's output
directory, and publishes a small, engine-agnostic ``engine-result.json``
envelope alongside them using the same atomic-publish convention as the
native harness.

See docs/features/nvidia-skill-evaluator/design.md for the full contract and
docs/adr/0026-external-evaluation-engines-are-thin-subprocess-wrappers.md for
why this is infrastructure reuse rather than a shared behavioral interface
with the native harness.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codev_workflow.eval import (
    EvaluationError,
    isolated_subprocess_env,
    publish_result_bundle,
    redact_process_text,
    run_process,
)

EXECUTABLE = "skillevaluator"

# Verified against skillevaluator 0.2.0; see
# docs/features/nvidia-skill-evaluator/design.md's Compatibility Evidence
# section for what was actually run against this commit.
VERIFIED_COMMIT = "e70f0e3ee68bb72d8cf68178a7d4fa2052bc1433"

INSTALL_HINT = (
    "uv tool install --python 3.13 "
    f'"skillevaluator[all] @ git+https://github.com/NVIDIA/SkillEvaluator.git@{VERIFIED_COMMIT}"'
)

# SkillEvaluator's own configuration namespace is always safe to forward: it
# carries no CoDev secrets and is meaningless to any other subprocess this
# codebase launches. A short, explicit list of common provider-credential
# names supplements it. This is a curated allowlist, never a passthrough of
# the calling process's full environment -- see isolated_subprocess_env.
_ALWAYS_ALLOWED_PREFIXES = ("SKILL_EVAL_", "SKILLEVALUATOR_")
_ALWAYS_ALLOWED_NAMES = frozenset(
    {"NVIDIA_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"}
)
_DOCKER_ALLOWED_NAMES = frozenset(
    {
        "DOCKER_HOST",
        "DOCKER_CONFIG",
        "DOCKER_CONTEXT",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
    }
)
# NOT added here: isolated_subprocess_env's shared base (eval.py's
# _isolated_env) already unconditionally allows OPENCODE_API_KEY,
# OPENCODE_AUTH_TOKEN, and OPENCODE_SERVER_PASSWORD -- the same three
# variables the native OpenCode-based harness forwards to its actor/judge.
# That means every codev eval nvidia subprocess already receives these three
# if they're set, regardless of which --agents value is requested, without
# anything specific to opencode needed here. See
# docs/features/nvidia-skill-evaluator/how-to.md's OpenCode-as-Tier-3-agent
# entry for what this means in practice.


@dataclass(frozen=True)
class VerbSpec:
    """One supported ``skillevaluator`` subcommand.

    ``argv`` is the subcommand path (``("validate",)`` or
    ``("tier3", "evaluate")``). ``report_flag`` names the flag (``-o`` or
    ``--results-dir``) this verb uses to accept a report/results directory,
    confirmed against the installed CLI's own ``--help`` output; ``None``
    means the verb has no such flag and this wrapper only captures raw
    stdout/stderr. ``tier3`` marks verbs that may exercise SkillEvaluator's
    live-agent path, which needs an agent CLI credential and a sandbox that
    CoDev never provisions -- these print an explicit notice before running.
    """

    name: str
    argv: tuple[str, ...]
    needs_target: bool = True
    report_flag: str | None = "-o"
    tier3: bool = False


# Deliberately excludes three categories of upstream command, documented in
# docs/features/nvidia-skill-evaluator/design.md rather than silently omitted:
#   - view / harbor-view: open an interactive HTML/browser viewer, which does
#     not fit this wrapper's "everything lands in --output" evidence model.
#   - create-eval-dataset / init-custom-grader / init-harbor-task: scaffolding
#     commands that intentionally write into the *target skill directory*
#     itself (evals/...), not an isolated output directory -- a genuinely
#     different, mutating contract that deserves its own design pass rather
#     than being forced into this one.
VERBS: tuple[VerbSpec, ...] = (
    VerbSpec("validate", ("validate",), tier3=True),
    VerbSpec("quality-check", ("quality-check",)),
    VerbSpec("rubric-eval", ("rubric-eval",)),
    VerbSpec("security-scan", ("security-scan",)),
    VerbSpec("pii-scan", ("pii-scan",)),
    VerbSpec("lint-scripts", ("lint-scripts",)),
    VerbSpec("similarity-check", ("similarity-check",)),
    VerbSpec("context-optimization-check", ("context-optimization-check",)),
    VerbSpec("dedup-scan", ("dedup-scan",)),
    VerbSpec("compare", ("compare",), report_flag="--results-dir"),
    VerbSpec("doctor", ("doctor",), needs_target=False, report_flag=None, tier3=True),
    VerbSpec(
        "health-check",
        ("health-check",),
        needs_target=False,
        report_flag=None,
        tier3=True,
    ),
    VerbSpec("models", ("models",), needs_target=False, report_flag=None),
    VerbSpec(
        "tier3-evaluate",
        ("tier3", "evaluate"),
        report_flag="--results-dir",
        tier3=True,
    ),
    VerbSpec("tier3-validate", ("tier3", "validate"), report_flag=None, tier3=True),
)

VERBS_BY_NAME: dict[str, VerbSpec] = {verb.name: verb for verb in VERBS}


def _requests_docker_env_mode(extra_flags: list[str]) -> bool:
    """True if --extra spells --env-mode docker in either accepted form.

    argparse's own append action means a value that itself starts with '-'
    (like '--env-mode') must be passed as one token via '--extra=--env-mode',
    which this function must still recognize as the *separate* flag
    '--env-mode' followed by a second '--extra=docker' -- but a user
    reasonably following the same '=' convention skillevaluator's own CLI
    accepts might instead glue the value on too, '--extra=--env-mode=docker',
    producing one list item. Both shapes are checked so the precondition
    below cannot be silently bypassed by whichever form the user happened to
    use, and instead always fails fast with a clear message when Docker is
    genuinely unavailable.
    """
    for index, flag in enumerate(extra_flags):
        if flag == "--env-mode=docker":
            return True
        if flag == "--env-mode":
            return index + 1 < len(extra_flags) and extra_flags[index + 1] == "docker"
    return False


def _env_allowlist(extra_flags: list[str]) -> frozenset[str]:
    # Prefix match is resolved against the *current* environment up front, so
    # isolated_subprocess_env (which only matches exact names) still never
    # forwards anything this function did not explicitly decide to allow.
    allowed = {
        key for key in os.environ if key.upper().startswith(_ALWAYS_ALLOWED_PREFIXES)
    }
    allowed |= _ALWAYS_ALLOWED_NAMES
    if _requests_docker_env_mode(extra_flags):
        allowed |= _DOCKER_ALLOWED_NAMES
    return frozenset(allowed)


def _docker_precondition(extra_flags: list[str]) -> None:
    if not _requests_docker_env_mode(extra_flags):
        return
    if shutil.which("docker") is None:
        raise EvaluationError(
            "this command was given --env-mode docker but no `docker` "
            "executable is on PATH; install/start Docker or choose a "
            "different --env-mode"
        )


def available() -> str:
    """Resolve the ``skillevaluator`` executable, or raise EvaluationError.

    Falls back to a plain file-existence check when ``shutil.which`` finds
    nothing -- the same fallback ``evaluate()`` already uses for
    ``opencode``/``git``. This matters on Windows: Python 3.12 tightened
    ``shutil.which``'s extension matching, so an explicit path whose
    extension isn't in ``PATHEXT`` (e.g. a `.py` script, as this project's
    own fake-executable test stubs are) is no longer resolved purely via
    ``shutil.which`` there, even though the file genuinely exists and is
    exactly what the caller asked to run.
    """
    resolved = shutil.which(EXECUTABLE)
    if resolved is None and Path(EXECUTABLE).is_file():
        resolved = str(Path(EXECUTABLE).resolve())
    if resolved is None:
        raise EvaluationError(
            f"skillevaluator not found on PATH. Install: {INSTALL_HINT}"
        )
    return resolved


def _check_output_dir(output: Path) -> None:
    if not output.exists() or output.is_symlink() or not output.is_dir():
        raise EvaluationError("--output must be an existing directory")
    if any(output.iterdir()):
        raise EvaluationError("--output must be empty")


def _envelope(
    *,
    verb: str,
    target: Path | None,
    exit_code: int | None,
    duration: float,
    timed_out: bool,
    outcome: str,
    summary: str,
    artifacts: dict[str, str],
) -> str:
    envelope: dict[str, Any] = {
        "schema_version": 1,
        "engine": "nvidia-skillevaluator",
        "verb": verb,
        "target": (
            {"kind": "skill_directory", "path": str(target)}
            if target is not None
            else None
        ),
        "process": {
            "exit_code": exit_code,
            "duration_seconds": round(duration, 3),
            "timeout": timed_out,
        },
        "outcome": outcome,
        "summary": summary,
        "artifacts": artifacts,
    }
    return json.dumps(envelope, indent=2) + "\n"


def run_verb(
    verb: str,
    *,
    output: Path,
    target: Path | None = None,
    extra_flags: list[str] | None = None,
    timeout_seconds: int = 900,
) -> bool:
    """Run one SkillEvaluator verb, publish its evidence, and report success.

    Returns whether the SkillEvaluator subprocess's own exit code indicated
    success (``0``). This is strictly a process-outcome signal -- it is never
    a reinterpretation of SkillEvaluator's own findings or scores, which
    always live in the separately captured native report/stdout artifacts.
    Raises :class:`EvaluationError` for anything that prevented a valid
    evaluation from running at all (missing executable, bad --output,
    unmet Tier 3 precondition, launch failure, or timeout); in every one of
    those cases except the first two, partial evidence is still published
    before the exception is raised.
    """
    spec = VERBS_BY_NAME.get(verb)
    if spec is None:
        raise EvaluationError(f"unknown skillevaluator verb: {verb}")
    if spec.needs_target and target is None:
        raise EvaluationError(f"'{verb}' requires a target path")
    # SkillEvaluator runs with cwd set to a private scratch directory (below),
    # not the caller's cwd, so a relative target must be resolved against the
    # caller's cwd now -- otherwise the subprocess would look for it relative
    # to the scratch directory instead and fail with a spurious "not found".
    if target is not None:
        target = target.resolve()
    extra_flags = list(extra_flags or [])

    executable = available()
    _check_output_dir(output)
    if spec.tier3:
        print(
            f"Note: 'skillevaluator {' '.join(spec.argv)}' may exercise "
            "NVIDIA SkillEvaluator's live-agent (Tier 3) path, which needs "
            "an agent CLI credential and a sandbox (Docker by default). "
            "CoDev does not provision or store either -- configure your own "
            "environment before this succeeds.",
            file=sys.stderr,
        )
    _docker_precondition(extra_flags)

    env = isolated_subprocess_env(extra_allowed=_env_allowlist(extra_flags))

    # SkillEvaluator writes its own native report(s) itself, given a
    # directory via -o/--results-dir; that write happens mid-subprocess, so
    # it cannot target the caller's --output directly (publish_result_bundle
    # requires that directory to still be empty when this module writes to
    # it). A private scratch directory decouples the two: SkillEvaluator
    # writes there freely, and everything it produced is folded, as in-memory
    # content, into the one atomic publish_result_bundle call below.
    with tempfile.TemporaryDirectory(prefix="codev-eval-nvidia-") as scratch_name:
        scratch = Path(scratch_name)
        argv = [executable, *spec.argv]
        if spec.needs_target and target is not None:
            argv.append(str(target))
        if spec.report_flag == "-o":
            argv.extend(["-o", str(scratch)])
            if not any(flag in ("-r", "--report") for flag in extra_flags):
                argv.extend(["-r", "json"])
        elif spec.report_flag == "--results-dir":
            argv.extend(["--results-dir", str(scratch)])
        argv.extend(extra_flags)

        try:
            run = run_process(argv, cwd=scratch, timeout=timeout_seconds, env=env)
        except EvaluationError as exc:
            files = {
                "engine-result.json": _envelope(
                    verb=verb,
                    target=target,
                    exit_code=None,
                    duration=0.0,
                    timed_out=False,
                    outcome="error",
                    summary=str(exc),
                    artifacts={},
                )
            }
            publish_result_bundle(output, files)
            raise

        artifacts: dict[str, str] = {}
        files = {}
        if run.stdout:
            files["nvidia-stdout.txt"] = redact_process_text(run.stdout)
            artifacts["stdout"] = "nvidia-stdout.txt"
        if run.stderr:
            files["nvidia-stderr.txt"] = redact_process_text(run.stderr)
            artifacts["stderr"] = "nvidia-stderr.txt"
        for native_path in sorted(scratch.rglob("*")):
            if not native_path.is_file():
                continue
            relative = native_path.relative_to(scratch).as_posix()
            # publish_result_bundle stages files by flat name (it does not
            # create parent directories), so a nested native report path is
            # flattened into one file name rather than reproducing its tree.
            destination = "native-report__" + relative.replace("/", "__")
            content = native_path.read_bytes().decode("utf-8", errors="surrogateescape")
            files[destination] = redact_process_text(content)
            artifacts[f"report:{relative}"] = destination

    if run.timed_out:
        outcome = "error"
        summary = (
            f"skillevaluator {' '.join(spec.argv)} timed out after {timeout_seconds}s"
        )
    elif run.code == 0:
        outcome = "passed"
        summary = f"skillevaluator {' '.join(spec.argv)} exited 0"
    else:
        outcome = "failed"
        summary = f"skillevaluator {' '.join(spec.argv)} exited {run.code}"

    files["engine-result.json"] = _envelope(
        verb=verb,
        target=target,
        exit_code=run.code,
        duration=run.duration,
        timed_out=run.timed_out,
        outcome=outcome,
        summary=summary,
        artifacts=artifacts,
    )
    publish_result_bundle(output, files)
    if run.timed_out:
        raise EvaluationError(summary)
    return run.code == 0
