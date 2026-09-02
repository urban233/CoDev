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
"""Navigator coverage: how much of a task's lifecycle `codev next` can drive.

The unified-workflow brief asks for a developer who completes a task having
typed no `codev` command. That measure cannot be built as worded -- it needs a
session transcript format that does not exist, it audits a session that already
happened rather than running in CI, and its value depends on sampling an LLM.
See `docs/plans/navigator-coverage-measure.md` for the full argument.

What is measured instead is the precondition. A developer types a command for
exactly one reason: the agent did not know what to run. The agent knows what to
run when, and only when, the navigator tells it -- which is what ADR-0036 rule
three made `codev next` for. So this walks one complete lifecycle against a
real repository and counts the steps where `next_action` does not name the
single action that advances the work.

**The definition of a step, which the baseline is worthless without.** A step
is one state transition: the work sits in some position, one action moves it to
the next. Before each transition the walk asks the navigator, and the step is
covered only when the navigator's `command` names that exact action. A step is
uncovered when the command is absent, names something else, or -- the rule that
makes this honest -- names more than one thing. A field reading "codev git
push, then codev git open-pr" has not told an agent what to run; it has told it
what to read, and without this rule the successor plan's package 2, whose
entire purpose is collapsing exactly those, would show no improvement.

Coverage at zero does not prove a developer typed nothing: an agent may still
hand a command over, and a human still makes every decision the loop stops for,
which is intended and is not counted here. Zero proves that nothing in the
lifecycle *forces* a developer to supply a command. That is the part CoDev
controls.

This walk drives the same functions the CLI drives rather than shelling out to
`codev`, matching the rest of the integration tier. The command spelling each
step declares is therefore a claim about the CLI surface, checked by eye and
pinned by the baseline, not derived from argv.
"""

from __future__ import annotations

import json
import os
import unittest
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codev_workflow import git_ops, navigator, task
from tests.integration_support import Sandbox

_BASELINE = Path(__file__).with_name("navigator-coverage-baseline.json")

# Same limitation the lifecycle suite documents: cmd.exe cannot carry a
# multi-line --body, and this walk renders a real pull-request body.
_GH_BODY_UNSUPPORTED = os.name == "nt"

_TASK = "measure"


@dataclass(frozen=True)
class Step:
    """One state transition, and what the navigator must say to cover it."""

    name: str
    # "cli" -- advanced by a codev command, which `expects` spells.
    # "dispatch" -- advanced by invoking a subagent, which `expects` names.
    kind: str
    expects: str

    def covers(self, command: str | None) -> bool:
        if command is None:
            return False
        if self.kind == "dispatch":
            return self.expects.lower() in command.lower()
        # More than one `codev ` in the field means the navigator described a
        # procedure rather than naming a command.
        if command.count("codev ") != 1:
            return False
        return self.expects in command


class NavigatorCoverageTests(unittest.TestCase):
    """The measure, plus the two facts it rests on."""

    maxDiff = None

    def setUp(self) -> None:
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.close)
        self.work = self.sandbox.work

    # -- the walk ---------------------------------------------------------

    def _next_command(self) -> str | None:
        action = navigator.next_action(target=self.work, check_github=True)
        return action.command

    def _steps(self) -> list[tuple[Step, Callable[[], Any]]]:
        """The single-slice lifecycle, from an empty repository to a closed
        task, paired with the action that advances each position.

        Single-slice on purpose. A multi-slice walk shares every step with
        this one except `advance-slice`, so adding it before the measure has
        proved useful would be speculative.
        """
        base = self.sandbox.base

        def begin() -> None:
            git_ops.create_branch(_TASK, base, target=self.work)

        def start() -> None:
            task.start(
                _TASK,
                base,
                target=self.work,
                link_ref="https://github.com/o/r/issues/1",
            )

        def build() -> None:
            self.sandbox.write("measured.py", "value = 1\n")

        def record_build() -> None:
            head = git_ops.commit(_TASK, "the measured change", target=self.work)
            task.record_builder(_TASK, 1, head, {"validation": "ran"}, target=self.work)

        def review() -> None:
            task.record_reviewer(
                _TASK,
                1,
                self.sandbox.head(),
                [],
                {},
                "READY_FOR_OUTER_LOOP",
                target=self.work,
            )

        def publish() -> None:
            git_ops.push(_TASK, target=self.work)
            git_ops.open_pr(_TASK, "the measured change", "body", target=self.work)

        def outer_review() -> None:
            coverage = {
                dimension: {"passed": True, "evidence": "checked"}
                for dimension in task.REQUIRED_COVERAGE_DIMENSIONS
            }
            task.record_reviewer(
                _TASK,
                2,
                self.sandbox.head(),
                [],
                coverage,
                "READY_FOR_HUMAN_APPROVAL",
                target=self.work,
            )

        def request_human_review() -> None:
            git_ops.mark_ready(_TASK, target=self.work)
            # The merge itself is the human's, on GitHub, and is deliberately
            # not a step: there is no codev command for it and the navigator
            # naming one would be wrong. It is setup for the closing position.
            self.sandbox.gh.set_pr_state(f"codev/{_TASK}", "MERGED")

        def close() -> None:
            task.close(_TASK, "approved", target=self.work)

        return [
            (Step("begin_slice", "cli", "codev git branch"), begin),
            (Step("start_round_state", "cli", "codev task start"), start),
            (Step("dispatch_builder", "dispatch", "builder"), build),
            (Step("record_builder_round", "cli", "codev git commit"), record_build),
            (Step("dispatch_reviewer", "dispatch", "reviewer"), review),
            (Step("open_pull_request", "cli", "codev git push"), publish),
            (Step("dispatch_specialists", "dispatch", "specialist"), outer_review),
            (
                Step("request_human_review", "cli", "codev git mark-ready"),
                request_human_review,
            ),
            (Step("close_task", "cli", "codev task close"), close),
        ]

    def _walk(self) -> dict[str, Any]:
        uncovered: list[str] = []
        observed: dict[str, str | None] = {}
        for step, advance in self._steps():
            command = self._next_command()
            observed[step.name] = command
            if not step.covers(command):
                uncovered.append(step.name)
            advance()
        return {"uncovered": uncovered, "observed": observed}

    # -- the assertions ---------------------------------------------------

    @unittest.skipIf(
        _GH_BODY_UNSUPPORTED,
        "the gh stub cannot carry a multi-line --body through a cmd.exe wrapper",
    )
    def test_navigator_coverage_matches_the_recorded_baseline(self) -> None:
        """Fails on a regression, and on an unrecorded improvement.

        An improvement failing is deliberate. A measure that silently
        ratchets is a measure nobody reads; making each successor package
        carry a visible baseline edit is what makes the improvement
        reviewable in its own diff.
        """
        baseline = json.loads(_BASELINE.read_text(encoding="utf-8"))
        result = self._walk()

        observed = "\n".join(
            f"  {name}: {result['observed'][name]!r}" for name in result["uncovered"]
        )
        self.assertEqual(
            baseline["uncovered"],
            result["uncovered"],
            "navigator coverage changed. If this is an improvement, update "
            f"{_BASELINE.name} in the same commit so the gain is reviewable.\n"
            f"what the navigator said at each uncovered step:\n{observed}",
        )

    def test_every_uncovered_step_has_a_recorded_reason(self) -> None:
        """Keeps the baseline from decaying into a list of bare names.

        A count tells a reviewer that six things are wrong. The reasons tell
        them which six, which is what makes a successor package's diff
        readable when a name disappears from the list.
        """
        baseline = json.loads(_BASELINE.read_text(encoding="utf-8"))
        self.assertEqual(
            sorted(baseline["uncovered"]),
            sorted(baseline["reasons"]),
            "every uncovered step needs a reason, and a reason without an "
            "uncovered step is stale",
        )

    @unittest.skipIf(
        _GH_BODY_UNSUPPORTED,
        "the gh stub cannot carry a multi-line --body through a cmd.exe wrapper",
    )
    def test_every_walked_step_reaches_the_position_it_claims(self) -> None:
        """The walk is worthless if it does not actually move.

        Without this, a step whose advance silently no-ops would score as
        covered forever. Reading `_BY_CHECK_REASON` statically would be
        cheaper than this whole module and would measure nothing.
        """
        result = self._walk()
        self.assertEqual(
            [step.name for step, _ in self._steps()],
            list(result["observed"]),
        )
        state = task.describe(_TASK, target=self.work)
        self.assertEqual("closed", state["status"])

    def test_the_navigator_has_no_position_for_the_planning_phases(self) -> None:
        """The gap package 3 of the successor plan exists to close.

        `navigator.next_action` collapses every state in which no task branch
        exists into one recommendation, so the whole Understand/Design/Plan
        half of the lifecycle -- where a developer spends the moment they
        have the least guidance for -- scores as uncovered by construction.
        This is asserted rather than walked, because there is no position to
        walk to.
        """
        action = navigator.next_action(target=self.work, check_github=False)
        self.assertEqual("no task on this branch", action.position)

        baseline = json.loads(_BASELINE.read_text(encoding="utf-8"))
        for name in baseline["planning_positions_absent"]:
            self.assertNotIn(name, (action.position or ""))


if __name__ == "__main__":
    unittest.main()
