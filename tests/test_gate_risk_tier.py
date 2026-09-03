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
"""The plan gate's risk tier, measured against a real task.

The cheap cases live in `test_gate.py`. These two need a real slice size,
which needs a real branch, a real base, and real commits -- exactly what this
tier exists to provide. Faking round state produces a measurement of nothing,
which is the failure mode the tier itself guards against.
"""

from __future__ import annotations

import os
import unittest

from codev_workflow import git_ops, task
from codev_workflow.gate import check
from tests.integration_support import Sandbox

_GH_BODY_UNSUPPORTED = os.name == "nt"


@unittest.skipIf(_GH_BODY_UNSUPPORTED, "drives a real gh stub through cmd.exe")
class RiskTierMeasurementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.close)
        self.work = self.sandbox.work
        task.start("sized", self.sandbox.base, target=self.work, link_ref="x")
        git_ops.create_branch("sized", self.sandbox.base, target=self.work)

    def _edit(self) -> str:
        return check(
            "plan",
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/foo.py"},
                "cwd": str(self.work),
            },
            target=self.work,
        ).decision

    def test_a_small_change_on_a_tracked_slice_is_not_interrupted(self) -> None:
        """The ceremony this package removes: a one-file fix on a real slice
        used to demand a written implementation plan first."""
        self.sandbox.write("small.py", "value = 1\n")
        git_ops.commit("sized", "a small change", target=self.work)
        self.assertEqual("allow", self._edit())

    def test_a_change_that_has_grown_past_the_budget_asks_again(self) -> None:
        """The safety-critical direction, and the whole design of the tier.

        The gate fires before an edit, so it sees only the diff already on
        the branch. It therefore does not interrupt before the work starts,
        when a developer knows least about what it will need -- it interrupts
        on the first edit after the change outgrows what a focus card can
        carry. Toll booth to tripwire.
        """
        (self.work / ".codev" / "config.toml").write_text(
            'schema_version = 1\n\n[values]\n"review.max_lines" = "1"\n',
            encoding="utf-8",
        )
        self.sandbox.write("grown.py", "\n".join(f"v{n} = {n}" for n in range(40)))
        git_ops.commit("sized", "a change that grew", target=self.work)
        self.assertEqual("ask", self._edit())


if __name__ == "__main__":
    unittest.main()
