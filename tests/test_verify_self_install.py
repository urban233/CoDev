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
from __future__ import annotations

import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from codev_workflow import installer
from scripts.verify_self_install import verify


class VerifySelfInstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.target = Path(self.temporary.name)
        plan = installer.plan_init(self.target, ("opencode",), "none")
        self.assertFalse(plan.conflicts)
        installer.apply_plan(self.target, plan)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_fresh_install_has_no_drift(self) -> None:
        with patch("sys.stdout", new=StringIO()):
            code = verify(self.target)
        self.assertEqual(0, code)

    def test_a_hand_edited_managed_file_is_reported_as_drift(self) -> None:
        skill_file = self.target / ".agents/skills/build-change/SKILL.md"
        skill_file.write_text(
            skill_file.read_text(encoding="utf-8") + "\nlocal tweak\n",
            encoding="utf-8",
        )
        with (
            patch("sys.stdout", new=StringIO()) as stdout,
            patch("sys.stderr", new=StringIO()) as stderr,
        ):
            code = verify(self.target)
        self.assertEqual(1, code)
        self.assertIn("drifted", stderr.getvalue())
        self.assertIn("build-change/SKILL.md", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
