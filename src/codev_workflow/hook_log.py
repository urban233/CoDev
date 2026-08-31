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
"""Reads the local, gitignored gate-decision log Claude Code's hook scripts
write to `.codev/hooks/decisions.jsonl` -- see
docs/features/production-readiness/brief.md. The hook scripts themselves
(`.claude/hooks/require_plan.py`, `.claude/hooks/require_wave_shape.py`)
write this file directly, with their own duplicated append logic: they are
standalone scripts a target repository never imports `codev_workflow` to
run, so this module is read-only from their point of view. `codev status`
is the one reader.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any, cast

DECISIONS_LOG_RELATIVE = PurePosixPath(".codev/hooks/decisions.jsonl")


def _decisions_log_path(target: Path) -> Path:
    return target / Path(DECISIONS_LOG_RELATIVE.as_posix())


def read_decisions(*, target: Path, since: str | None = None) -> list[dict[str, Any]]:
    """Returns every recorded gate decision, oldest first. Missing or
    unreadable log lines are skipped rather than raised -- this log is
    diagnostic, and a malformed line must never break `codev status`."""
    path = _decisions_log_path(target)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = cast("dict[str, Any]", json.loads(line))
        except json.JSONDecodeError:
            continue
        if since is not None and record.get("timestamp", "") < since:
            continue
        records.append(record)
    return records


def summarize_decisions(records: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Returns {hook_name: {decision: count}}, e.g.
    {"require_plan.py": {"ask": 2, "allow": 11}}."""
    summary: dict[str, dict[str, int]] = {}
    for record in records:
        hook = str(record.get("hook", "unknown"))
        decision = str(record.get("decision", "unknown"))
        by_decision = summary.setdefault(hook, {})
        by_decision[decision] = by_decision.get(decision, 0) + 1
    return summary
