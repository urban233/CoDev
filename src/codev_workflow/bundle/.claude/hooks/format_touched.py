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
"""Reformat a file the agent just wrote, so the tree never carries a
formatting-only diff the agent has to remember to clean up.

`PostToolUse` fires after the tool already ran, so this hook cannot prevent
a bad edit -- it can only react to one. That is why it runs the formatter
and nothing else. A type checker here would fire between the edits of a
multi-file sequence, where intermediate states are legitimately broken, and
report errors that are expected and about to be fixed; the agent would then
chase them. Type checking belongs at `Stop`, where the change is coherent,
and lives in `require_green.py`.

Fails open on everything. A formatter that cannot run must never interrupt
work, and reformatting is not a safety property.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_HOOK_NAME = "format_touched.py"
_DECISIONS_LOG_RELATIVE = ".codev/hooks/decisions.jsonl"
_TIMEOUT_SECONDS = 20


def _log(
    repo_root: Path, decision: str, *, tool_name: str = "", reason: str = ""
) -> None:
    """Appends one local, gitignored record. Never raises."""
    try:
        record = {
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "hook": _HOOK_NAME,
            "decision": decision,
            "tool_name": tool_name,
            "reason": reason,
        }
        path = repo_root / _DECISIONS_LOG_RELATIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    except Exception:  # noqa: BLE001 - logging must never affect the hook
        pass


def _touched_paths(payload: dict[str, object]) -> list[Path]:
    """Every file path this tool call wrote, as absolute paths.

    Covers `Edit`/`Write` (one `file_path`) and `MultiEdit` (one
    `file_path`, many edits within it). A payload shape that carries none
    of them yields nothing, which is the correct no-op.
    """
    raw_input = payload.get("tool_input")
    if not isinstance(raw_input, dict):
        return []
    found: list[Path] = []
    single = raw_input.get("file_path")
    if isinstance(single, str) and single:
        found.append(Path(single))
    edits = raw_input.get("edits")
    if isinstance(edits, list):
        for edit in edits:
            if isinstance(edit, dict):
                nested = edit.get("file_path")
                if isinstance(nested, str) and nested:
                    found.append(Path(nested))
    return found


def _formatter_argv() -> list[str] | None:
    """The formatter, resolved without trusting `PATH` alone.

    Same reasoning as `codev_argv` in `_hook_common.py`: the hook's
    environment is frequently not the shell the tooling was installed into.
    Returns None when no formatter is reachable, which is a no-op, not an
    error.
    """
    try:
        import importlib.util

        if importlib.util.find_spec("ruff") is not None:
            # -P: see the gate hooks. cwd is the repository being formatted.
            return [sys.executable, "-P", "-m", "ruff"]
    except (ImportError, ValueError):
        pass
    found = shutil.which("ruff")
    if found:
        return [found]
    return None


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)
    if not isinstance(payload, dict):
        sys.exit(0)

    repo_root = Path(payload.get("cwd") or Path.cwd())
    tool_name = str(payload.get("tool_name") or "")
    targets = [p for p in _touched_paths(payload) if p.suffix == ".py"]
    if not targets:
        sys.exit(0)

    argv = _formatter_argv()
    if argv is None:
        _log(
            repo_root,
            "degraded",
            tool_name=tool_name,
            reason="no formatter reachable, so the touched file was left as written",
        )
        sys.exit(0)

    reformatted: list[str] = []
    for target in targets:
        if not target.exists():
            continue
        try:
            completed = subprocess.run(
                # --force-exclude: ruff honours the project's `exclude`
                # for an explicitly named path only when this is set.
                # Without it this hook rewrites vendored bundle mirrors,
                # skill sources, and eval fixture repositories whose exact
                # bytes are evaluation input -- none of which `just
                # fmt-check` would ever flag, because it respects the
                # exclusions this call was bypassing.
                [*argv, "format", "--force-exclude", str(target)],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            _log(
                repo_root,
                "degraded",
                tool_name=tool_name,
                reason=f"formatter did not complete for {target.name}",
            )
            continue
        # ruff prints "1 file reformatted" only when it changed something,
        # and "1 file left unchanged" otherwise. Reporting every call would
        # spend a turn's attention on the no-op case.
        if completed.returncode == 0 and "reformatted" in completed.stdout:
            reformatted.append(target.name)

    if reformatted:
        _log(
            repo_root,
            "formatted",
            tool_name=tool_name,
            reason=f"reformatted {', '.join(reformatted)}",
        )
        # The file on disk now differs from what the agent wrote, and an
        # agent that does not know that will re-apply its own spacing on
        # the next edit.
        json.dump(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": (
                        f"The formatter rewrote {', '.join(reformatted)} after "
                        "this edit. Re-read the file before editing it again."
                    ),
                }
            },
            sys.stdout,
        )
    sys.exit(0)


if __name__ == "__main__":
    main()
