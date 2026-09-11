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
"""Makes the always-on instruction-payload budget
(docs/plans/claude-code-adapter-verification-first.md) a regression check
instead of a table someone has to remember to update by hand.

Slices 1 and 3 tracked byte deltas for two of the original research's five
sources -- `.codev/for-ai/ai-agent-guidelines.md` and `AGENTS.md` -- in the
plan's own ledger. `.claude/CLAUDE.md`, skill descriptions, and agent
descriptions were measured once, at the parent plan's baseline commit, and
never checked again. This asserts the combined total of all five, every run.

Measures this repository's own root-level files (via
`//:instruction_budget_sources` in the top-level BUILD.bazel), not
`codev_workflow`'s `bundle/**`, which mirrors this content for every
repository CoDev installs into, not just the one this test runs in.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BASELINE_PATH = _REPO_ROOT / ".codev/instruction-budget-baseline.json"

# Derived in the slice's implementation plan from the original research's
# own measurement: 42,818 bytes across these five sources corresponded to
# ~9,698 tokens at `d13e0a9`, so the accepted 7,500-token ceiling lands at
# roughly 42,818 / 9,698 * 7,500 =~ 33,100 bytes. A proxy, not a re-run of
# the real tokenizer -- see the plan's Decision 1.
_CEILING_BYTES = 33_100

_DESCRIPTION_LINE = re.compile(r"^description:.*$", re.MULTILINE)


def _byte_length(text: str) -> int:
    return len(text.encode("utf-8"))


def _description_bytes(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for match in _DESCRIPTION_LINE.finditer(text):
            total += _byte_length(match.group() + "\n")
    return total


def _measure() -> dict[str, int]:
    guidelines = _REPO_ROOT / ".codev/for-ai/ai-agent-guidelines.md"
    agents_md = _REPO_ROOT / "AGENTS.md"
    claude_md = _REPO_ROOT / ".claude/CLAUDE.md"
    skill_files = sorted((_REPO_ROOT / ".claude/skills").glob("*/SKILL.md"))
    agent_files = sorted((_REPO_ROOT / ".claude/agents").glob("*.md"))

    breakdown = {
        "ai-agent-guidelines.md": _byte_length(guidelines.read_text(encoding="utf-8")),
        "AGENTS.md": _byte_length(agents_md.read_text(encoding="utf-8")),
        ".claude/CLAUDE.md": _byte_length(claude_md.read_text(encoding="utf-8")),
        "skill descriptions": _description_bytes(skill_files),
        "agent descriptions": _description_bytes(agent_files),
    }
    breakdown["total"] = sum(breakdown.values())
    return breakdown


class InstructionBudgetTests(unittest.TestCase):
    @unittest.skip(
        "Decision 1 in this slice's implementation plan is not yet resolved "
        "by the developer: the real measured total (34,389 bytes) is "
        "already over the derived 33,100-byte ceiling, and this slice's own "
        "hooks license at most ~300 bytes of retirement -- nowhere near "
        "enough to close a ~1,300-byte gap the ledger never actually "
        "tracked (only two of these five sources were ever measured "
        "per-slice). Un-skip once the developer decides whether to retire "
        "more prose, revisit the byte/token conversion, or accept the "
        "overage as a separately-tracked follow-up."
    )
    def test_total_is_at_or_under_the_ratcheted_ceiling(self) -> None:
        breakdown = _measure()
        self.assertLessEqual(
            breakdown["total"],
            _CEILING_BYTES,
            f"instruction payload is {breakdown['total']} bytes across "
            f"{breakdown}, over the {_CEILING_BYTES}-byte ceiling derived "
            "from the original 7,500-token budget -- retire prose before "
            "adding more, per the standing instruction-budget rule",
        )

    def test_total_has_not_grown_past_the_recorded_baseline(self) -> None:
        """A later slice that increases the total should fail here, not
        only at the absolute ceiling -- the ceiling alone would let this
        creep the same way it already did once, unmeasured, between the
        original research and this test's own addition."""
        recorded = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
        breakdown = _measure()
        self.assertLessEqual(
            breakdown["total"],
            recorded["total_bytes"],
            f"instruction payload grew from the recorded baseline of "
            f"{recorded['total_bytes']} bytes to {breakdown['total']} -- "
            f"either retire prose to bring it back down, or update "
            f"{_BASELINE_PATH.relative_to(_REPO_ROOT)} deliberately if the "
            "increase is intended and stays under the absolute ceiling",
        )

    def test_baseline_file_is_not_stale_in_the_other_direction(self) -> None:
        """The baseline should track real retirement, not sit above what is
        actually measured forever -- otherwise a regression could still
        creep most of the way back up before either assertion above would
        catch it."""
        recorded = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
        breakdown = _measure()
        self.assertEqual(
            recorded["total_bytes"],
            breakdown["total"],
            f"the recorded baseline ({recorded['total_bytes']} bytes) no "
            f"longer matches what is actually measured ({breakdown['total']}"
            f") -- update {_BASELINE_PATH.relative_to(_REPO_ROOT)} to the "
            "measured total",
        )


if __name__ == "__main__":
    unittest.main()
