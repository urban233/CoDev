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

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import codev_workflow.installer as installer


class InstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.target = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def install(
        self,
        platforms: tuple[str, ...] = ("all",),
        programming_language: str = "none",
    ) -> installer.Plan:
        plan = installer.plan_init(self.target, platforms, programming_language)
        self.assertFalse(plan.conflicts)
        installer.apply_plan(self.target, plan)
        return plan

    def test_init_installs_complete_bundle_and_passes_check(self) -> None:
        self.install(programming_language="all")

        bundled = installer._bundle_files(("antigravity", "junie", "opencode"))
        self.assertFalse(any("__pycache__" in path for path in bundled))
        self.assertFalse(any(path.endswith(".pyc") for path in bundled))
        self.assertFalse(any(path.endswith(".template") for path in bundled))
        skills = sorted((self.target / ".agents" / "skills").glob("*/SKILL.md"))
        self.assertEqual(16, len(skills))
        self.assertTrue((self.target / ".agents/skills/pr-review/SKILL.md").is_file())
        self.assertTrue(
            (self.target / ".agents/skills/design-skill-eval/SKILL.md").is_file()
        )
        self.assertTrue(
            (
                self.target
                / ".agents/skills/design-skill-eval/references/eval-design-checklist.md"
            ).is_file()
        )
        self.assertTrue(
            (self.target / ".agents/skills/critique-review/SKILL.md").is_file()
        )
        self.assertTrue(
            (
                self.target / ".agents/skills/audit-google-python-style/SKILL.md"
            ).is_file()
        )
        self.assertTrue(
            (
                self.target / ".agents/skills/audit-google-typescript-style/SKILL.md"
            ).is_file()
        )
        audit_agent = (
            self.target / ".opencode" / "agents" / "code-audit.md"
        ).read_text(encoding="utf-8")
        self.assertIn("audit-google-python-style: allow", audit_agent)
        self.assertIn("audit-google-typescript-style: allow", audit_agent)
        self.assertTrue((self.target / ".opencode/agents/builder.md").is_file())
        self.assertFalse((self.target / ".opencode/agents/lead.md").exists())
        self.assertTrue((self.target / ".junie/agents/assistant.md").is_file())
        self.assertTrue((self.target / ".agents/agents/assistant.md").is_file())
        self.assertTrue((self.target / "docs/codev/README.md").is_file())
        self.assertTrue(
            (self.target / "docs/codev/onboarding/skill-card.template.md").is_file()
        )
        self.assertTrue(
            (self.target / ".codev/for-ai/ai-agent-guidelines.md").is_file()
        )
        self.assertTrue((self.target / ".codev/lock.json").is_file())

        result = installer.check_project(self.target)
        self.assertTrue(result.ok, result.issues)
        self.assertGreater(result.managed_files, 30)

    def test_init_installs_code_audit_gate_for_every_platform(self) -> None:
        self.install(programming_language="python")

        gate_paths = [
            self.target / ".opencode/agents/code-audit-gate.md",
            self.target / ".claude/agents/code-audit-gate.md",
        ]
        for path in gate_paths:
            self.assertTrue(path.is_file(), path)
            text = path.read_text(encoding="utf-8")
            # code-audit-gate is always-autonomous (ADR-0015): unlike
            # code-audit, it must never carry code-audit's own stop-for-
            # approval instruction -- there is no human in its turn to
            # grant one. (The file does mention the phrase once, in its own
            # explicit "never do this" sentence -- checking the stop
            # instruction's exact wording, not the bare phrase, avoids
            # flagging that.)
            self.assertNotIn("Stop with `APPROVAL REQUIRED`", text)
            self.assertIn("audit-google-python-style", text)
        self.assertTrue(installer.check_project(self.target).ok)

    def test_init_defaults_to_language_agnostic_audit(self) -> None:
        self.install()

        skills = sorted(
            path.parent.name
            for path in (self.target / ".agents" / "skills").glob("*/SKILL.md")
        )
        self.assertNotIn("audit-google-python-style", skills)
        self.assertNotIn("audit-google-typescript-style", skills)
        audit_agent = (
            self.target / ".opencode" / "agents" / "code-audit.md"
        ).read_text(encoding="utf-8")
        self.assertIn("language-agnostic code style and quality issues", audit_agent)
        self.assertIn("Do not assume a programming language", audit_agent)
        self.assertNotIn("audit-google-python-style", audit_agent)
        self.assertNotIn("audit-google-typescript-style", audit_agent)
        lock = json.loads(
            (self.target / ".codev" / "lock.json").read_text(encoding="utf-8")
        )
        self.assertEqual("none", lock["programming_language"])
        self.assertTrue(installer.check_project(self.target).ok)

    def test_init_installs_only_python_audit_skill(self) -> None:
        self.install(programming_language="python")

        skills = sorted(
            path.parent.name
            for path in (self.target / ".agents" / "skills").glob("*/SKILL.md")
        )
        self.assertIn("audit-google-python-style", skills)
        self.assertNotIn("audit-google-typescript-style", skills)
        audit_agent = (
            self.target / ".opencode" / "agents" / "code-audit.md"
        ).read_text(encoding="utf-8")
        self.assertIn("audit-google-python-style: allow", audit_agent)
        self.assertNotIn("audit-google-typescript-style: allow", audit_agent)
        lock = json.loads(
            (self.target / ".codev" / "lock.json").read_text(encoding="utf-8")
        )
        self.assertEqual("python", lock["programming_language"])
        self.assertTrue(installer.check_project(self.target).ok)

    def test_init_installs_only_typescript_audit_skill(self) -> None:
        self.install(programming_language="typescript")

        skills = sorted(
            path.parent.name
            for path in (self.target / ".agents" / "skills").glob("*/SKILL.md")
        )
        self.assertNotIn("audit-google-python-style", skills)
        self.assertIn("audit-google-typescript-style", skills)
        audit_agent = (
            self.target / ".opencode" / "agents" / "code-audit.md"
        ).read_text(encoding="utf-8")
        self.assertIn("audit-google-typescript-style: allow", audit_agent)
        self.assertNotIn("audit-google-python-style: allow", audit_agent)
        self.assertTrue(installer.check_project(self.target).ok)

    def test_update_changes_exact_programming_language_selection(self) -> None:
        self.install(programming_language="python")

        plan = installer.plan_update(self.target, programming_language="typescript")

        self.assertFalse(plan.conflicts)
        installer.apply_plan(self.target, plan)
        self.assertFalse(
            (self.target / ".agents/skills/audit-google-python-style").exists()
        )
        self.assertTrue(
            (
                self.target / ".agents/skills/audit-google-typescript-style/SKILL.md"
            ).is_file()
        )
        audit_agent = (
            self.target / ".opencode" / "agents" / "code-audit.md"
        ).read_text(encoding="utf-8")
        self.assertNotIn("audit-google-python-style: allow", audit_agent)
        self.assertIn("audit-google-typescript-style: allow", audit_agent)
        self.assertTrue(installer.check_project(self.target).ok)

    def test_update_without_language_preserves_lock_selection(self) -> None:
        self.install(programming_language="python")

        plan = installer.plan_update(self.target)

        self.assertFalse(plan.conflicts)
        self.assertFalse(plan.changed)
        assert plan.lock is not None
        self.assertEqual("python", plan.lock["programming_language"])

    def test_update_can_switch_to_language_agnostic_audit(self) -> None:
        self.install(programming_language="python")

        plan = installer.plan_update(self.target, programming_language="none")

        self.assertFalse(plan.conflicts)
        installer.apply_plan(self.target, plan)
        self.assertFalse(
            (self.target / ".agents/skills/audit-google-python-style").exists()
        )
        self.assertFalse(
            (self.target / ".agents/skills/audit-google-typescript-style").exists()
        )
        audit_agent = (
            self.target / ".opencode" / "agents" / "code-audit.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Do not assume a programming language", audit_agent)
        self.assertTrue(installer.check_project(self.target).ok)

    def test_update_language_change_conflicts_on_local_audit_skill_edit(self) -> None:
        self.install(programming_language="python")
        skill = self.target / ".agents/skills/audit-google-python-style/SKILL.md"
        skill.write_bytes(skill.read_bytes() + b"\nlocal edit\n")

        plan = installer.plan_update(self.target, programming_language="typescript")

        self.assertTrue(plan.conflicts)
        with self.assertRaises(installer.CoDevError):
            installer.apply_plan(self.target, plan)
        self.assertTrue(skill.exists())

    def test_antigravity_adapter_uses_official_agents_location(self) -> None:
        self.install(("antigravity",))

        self.assertTrue((self.target / ".agents/agents/assistant.md").is_file())
        self.assertFalse((self.target / ".junie").exists())
        self.assertFalse((self.target / ".opencode").exists())
        content = (self.target / ".agents/agents/assistant.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("name: assistant", content)
        self.assertIn("mainAgent: true", content)
        self.assertIn("subagent: true", content)
        self.assertTrue(installer.check_project(self.target).ok)

    def test_junie_adapter_installs_valid_subagents_without_other_adapters(
        self,
    ) -> None:
        self.install(("junie",))

        self.assertTrue((self.target / ".junie/agents/assistant.md").is_file())
        self.assertFalse((self.target / ".opencode").exists())
        self.assertIn(
            'description: "Bounded pair-programming helper',
            (self.target / ".junie/agents/assistant.md").read_text(encoding="utf-8"),
        )
        self.assertTrue(installer.check_project(self.target).ok)

    def test_claude_adapter_installs_valid_agents_without_other_adapters(self) -> None:
        self.install(("claude",))

        agents = sorted((self.target / ".claude" / "agents").glob("*.md"))
        self.assertEqual(
            [
                "architecture-maintainability-specialist.md",
                "builder.md",
                "code-audit-gate.md",
                "code-audit.md",
                "concurrency-specialist.md",
                "correctness-tests-specialist.md",
                "lightweight-reviewer.md",
                "reviewer.md",
                "rollout-specialist.md",
                "security-data-specialist.md",
            ],
            [path.name for path in agents],
        )
        for agent in agents:
            content = agent.read_text(encoding="utf-8")
            self.assertTrue(content.startswith("---\n"))
            self.assertIn(f"name: {agent.stem}", content)
            self.assertIn("description:", content)
        self.assertTrue((self.target / ".claude/commands/pr-review.md").is_file())
        self.assertTrue((self.target / ".claude/settings.json").is_file())
        self.assertTrue((self.target / ".claude/hooks/require_plan.py").is_file())
        self.assertTrue((self.target / ".claude/CLAUDE.md").is_file())
        self.assertFalse((self.target / ".opencode").exists())
        self.assertFalse((self.target / ".junie").exists())
        self.assertTrue(installer.check_project(self.target).ok)

    def test_updating_removes_a_role_the_bundle_stopped_shipping(self) -> None:
        """The migration that protects every existing installation.

        `orchestrator.md` and `planner.md` became `lead.md` (ADR-0040), then
        `lead.md` and `outer-loop-runner.md` were removed entirely (ADR-0044).
        Retaining either the way a retired doc is retained would leave a
        developer with an invocable agent naming a role that no longer
        exists, because every adapter treats a file in its agents directory
        as invocable.
        """
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            installer.apply_plan(
                target, installer.plan_init(target, ("claude",), "none")
            )
            retired = target / ".claude/agents/orchestrator.md"
            retired.write_text("# orchestrator\n", encoding="utf-8")
            lock = json.loads((target / ".codev/lock.json").read_text("utf-8"))
            lock["files"][".claude/agents/orchestrator.md"] = installer._sha256(
                retired.read_bytes()
            )
            (target / ".codev/lock.json").write_text(json.dumps(lock), encoding="utf-8")

            installer.apply_plan(target, installer.plan_update(target))

            self.assertFalse(retired.exists())
            self.assertTrue((target / ".claude/agents/builder.md").is_file())
            self.assertFalse((target / ".claude/agents/lead.md").exists())

    def test_updating_removes_lead_and_outer_loop_runner(self) -> None:
        """ADR-0044's own migration: an installation made under ADR-0040 has
        `lead.md` and `outer-loop-runner.md` on disk. Neither is an agent any
        more; both must go, and nothing replaces them -- coordination now
        lives in `.codev/for-ai/ai-agent-guidelines.md`, which every
        installation already carries and updates in place."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            installer.apply_plan(
                target, installer.plan_init(target, ("claude",), "none")
            )
            lock = json.loads((target / ".codev/lock.json").read_text("utf-8"))
            retired_roles = {
                ".claude/agents/lead.md": "# lead\n",
                ".claude/agents/outer-loop-runner.md": "# outer-loop-runner\n",
            }
            for relative, content in retired_roles.items():
                path = target / relative
                path.write_text(content, encoding="utf-8")
                lock["files"][relative] = installer._sha256(path.read_bytes())
            (target / ".codev/lock.json").write_text(json.dumps(lock), encoding="utf-8")

            installer.apply_plan(target, installer.plan_update(target))

            for relative in retired_roles:
                self.assertFalse((target / relative).exists())
            self.assertTrue((target / ".codev/for-ai/ai-agent-guidelines.md").is_file())

    def test_a_locally_edited_retired_role_is_a_conflict_not_a_deletion(self) -> None:
        """Deleting a developer's own edits is never the default, even for a
        role the bundle no longer ships."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            installer.apply_plan(
                target, installer.plan_init(target, ("claude",), "none")
            )
            retired = target / ".claude/agents/orchestrator.md"
            retired.write_text("# orchestrator\n", encoding="utf-8")
            lock = json.loads((target / ".codev/lock.json").read_text("utf-8"))
            lock["files"][".claude/agents/orchestrator.md"] = installer._sha256(
                b"different"
            )
            (target / ".codev/lock.json").write_text(json.dumps(lock), encoding="utf-8")

            plan = installer.plan_update(target)
            self.assertIn(
                ".claude/agents/orchestrator.md",
                [c.path for c in plan.conflicts],
            )
            self.assertTrue(retired.exists())

    def test_updating_retires_an_opencode_agent_that_no_longer_ships(self) -> None:
        """Otherwise the lock keeps a hash for an agent nothing writes, and
        `codev status` reports drift no update can ever resolve."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            installer.apply_plan(
                target, installer.plan_init(target, ("opencode",), "none")
            )
            config_path = target / ".opencode/opencode.json"
            config = json.loads(config_path.read_text("utf-8"))
            retired = {"model": "m", "description": "a retired agent"}
            config["agent"]["orchestrator"] = retired
            config_path.write_text(json.dumps(config), encoding="utf-8")
            lock_path = target / ".codev/lock.json"
            lock = json.loads(lock_path.read_text("utf-8"))
            lock["integrations"]["opencode_agent_hashes"]["orchestrator"] = (
                installer._json_hash(retired)
            )
            lock_path.write_text(json.dumps(lock), encoding="utf-8")

            installer.apply_plan(target, installer.plan_update(target))

            config = json.loads(config_path.read_text("utf-8"))
            lock = json.loads(lock_path.read_text("utf-8"))
            self.assertNotIn("orchestrator", config["agent"])
            self.assertNotIn(
                "orchestrator", lock["integrations"]["opencode_agent_hashes"]
            )
            self.assertIn("builder", config["agent"])

    def test_updating_removes_a_managed_default_agent_value_of_lead(self) -> None:
        """A lock that already claims `opencode_default_agent_managed` is
        CoDev's own prior write; a leftover retired value under that claim
        is safe to remove."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            installer.apply_plan(
                target, installer.plan_init(target, ("opencode",), "none")
            )
            config_path = target / ".opencode/opencode.json"
            config = json.loads(config_path.read_text("utf-8"))
            config["default_agent"] = "lead"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            lock_path = target / ".codev/lock.json"
            lock = json.loads(lock_path.read_text("utf-8"))
            lock["integrations"]["opencode_default_agent_managed"] = True
            lock_path.write_text(json.dumps(lock), encoding="utf-8")

            installer.apply_plan(target, installer.plan_update(target))

            config = json.loads(config_path.read_text("utf-8"))
            self.assertNotIn("default_agent", config)

    def test_updating_removes_a_managed_default_agent_value_of_orchestrator(
        self,
    ) -> None:
        """The pre-rename retired value is removed the same way."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            installer.apply_plan(
                target, installer.plan_init(target, ("opencode",), "none")
            )
            config_path = target / ".opencode/opencode.json"
            config = json.loads(config_path.read_text("utf-8"))
            config["default_agent"] = "orchestrator"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            lock_path = target / ".codev/lock.json"
            lock = json.loads(lock_path.read_text("utf-8"))
            lock["integrations"]["opencode_default_agent_managed"] = True
            lock_path.write_text(json.dumps(lock), encoding="utf-8")

            installer.apply_plan(target, installer.plan_update(target))

            config = json.loads(config_path.read_text("utf-8"))
            self.assertNotIn("default_agent", config)

    def test_updating_preserves_an_unmanaged_default_agent_value_of_lead(
        self,
    ) -> None:
        """`lead` is a completely plausible name for a developer's own
        OpenCode primary agent -- it is what CoDev's own agent used to be
        called. When the lock never recorded CoDev as having claimed
        `default_agent`, its value must be left alone no matter what it
        reads, not deleted just because it collides with a retired CoDev
        value."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            installer.apply_plan(
                target, installer.plan_init(target, ("opencode",), "none")
            )
            config_path = target / ".opencode/opencode.json"
            config = json.loads(config_path.read_text("utf-8"))
            config["default_agent"] = "lead"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            lock_path = target / ".codev/lock.json"
            lock = json.loads(lock_path.read_text("utf-8"))
            self.assertNotEqual(
                True, lock["integrations"].get("opencode_default_agent_managed")
            )

            installer.apply_plan(target, installer.plan_update(target))

            config = json.loads(config_path.read_text("utf-8"))
            self.assertEqual("lead", config["default_agent"])

    def test_updating_clears_the_managed_flag_after_removing_default_agent(
        self,
    ) -> None:
        """Deleting a managed `default_agent` value must also clear the
        lock's `opencode_default_agent_managed` flag -- otherwise a value
        the developer sets afterwards, for their own reasons, still looks
        like CoDev's own leftover to remove on the *next* update, silently
        deleting a value CoDev never claimed."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            installer.apply_plan(
                target, installer.plan_init(target, ("opencode",), "none")
            )
            config_path = target / ".opencode/opencode.json"
            config = json.loads(config_path.read_text("utf-8"))
            config["default_agent"] = "lead"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            lock_path = target / ".codev/lock.json"
            lock = json.loads(lock_path.read_text("utf-8"))
            lock["integrations"]["opencode_default_agent_managed"] = True
            lock_path.write_text(json.dumps(lock), encoding="utf-8")

            installer.apply_plan(target, installer.plan_update(target))

            config = json.loads(config_path.read_text("utf-8"))
            self.assertNotIn("default_agent", config)
            lock = json.loads(lock_path.read_text("utf-8"))
            self.assertFalse(lock["integrations"]["opencode_default_agent_managed"])

            # The developer now sets their own default_agent to "lead", for
            # their own reasons, unrelated to CoDev. Because the lock no
            # longer claims CoDev owns this key, a later update must
            # preserve it rather than treat it as CoDev's stale leftover
            # again.
            config["default_agent"] = "lead"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            installer.apply_plan(target, installer.plan_update(target))

            config = json.loads(config_path.read_text("utf-8"))
            self.assertEqual("lead", config["default_agent"])

            # The flag must only ever move from managed to unmanaged when
            # this exact removal fires -- not unconditionally on every
            # update. A run where the removal condition does not hold (no
            # retired value present to delete) must leave an incoming
            # `True` flag exactly as it was.
            lock = json.loads(lock_path.read_text("utf-8"))
            lock["integrations"]["opencode_default_agent_managed"] = True
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            config = json.loads(config_path.read_text("utf-8"))
            del config["default_agent"]
            config_path.write_text(json.dumps(config), encoding="utf-8")

            installer.apply_plan(target, installer.plan_update(target))

            lock = json.loads(lock_path.read_text("utf-8"))
            self.assertTrue(lock["integrations"]["opencode_default_agent_managed"])

    def test_bundle_filters_claude_adapter_files(self) -> None:
        claude_files = installer._bundle_files(("claude",))
        opencode_files = installer._bundle_files(("opencode",))

        self.assertEqual(
            {
                ".claude/agents/architecture-maintainability-specialist.md",
                ".claude/agents/builder.md",
                ".claude/agents/code-audit-gate.md",
                ".claude/agents/code-audit.md",
                ".claude/agents/concurrency-specialist.md",
                ".claude/agents/correctness-tests-specialist.md",
                ".claude/agents/lightweight-reviewer.md",
                ".claude/agents/reviewer.md",
                ".claude/agents/rollout-specialist.md",
                ".claude/agents/security-data-specialist.md",
                ".claude/commands/pr-review.md",
                ".claude/settings.json",
                ".claude/hooks/require_plan.py",
                ".claude/hooks/require_wave_shape.py",
                ".claude/hooks/require_small_change.py",
                ".claude/CLAUDE.md",
            },
            {
                path
                for path in claude_files
                if path.startswith(".claude/")
                and not path.startswith(".claude/skills/")
            },
        )
        self.assertFalse(any(path.startswith(".claude/") for path in opencode_files))

    def test_claude_skills_are_mirrored_from_shared_skills(self) -> None:
        self.install(("claude",))

        shared = sorted(
            path.parent.name
            for path in (self.target / ".agents/skills").glob("*/SKILL.md")
        )
        mirrored = sorted(
            path.parent.name
            for path in (self.target / ".claude/skills").glob("*/SKILL.md")
        )
        self.assertEqual(shared, mirrored)
        self.assertGreater(len(mirrored), 0)
        name = mirrored[0]
        self.assertEqual(
            (self.target / ".agents/skills" / name / "SKILL.md").read_bytes(),
            (self.target / ".claude/skills" / name / "SKILL.md").read_bytes(),
        )
        self.assertTrue(installer.check_project(self.target).ok)

    def test_all_adapters_render_selected_audit_language(self) -> None:
        self.install(programming_language="python")

        agents = (
            self.target / ".opencode/agents/code-audit.md",
            self.target / ".claude/agents/code-audit.md",
        )
        for agent in agents:
            content = agent.read_text(encoding="utf-8")
            self.assertIn("audit-google-python-style", content)
            self.assertNotIn("audit-google-typescript-style", content)
        self.assertTrue(installer.check_project(self.target).ok)

    def test_junie_managed_files_update_and_remove_safely(self) -> None:
        self.install(("junie",))
        agent = self.target / ".junie/agents/assistant.md"
        original = agent.read_bytes()

        plan = installer.plan_update(self.target)
        self.assertFalse(plan.conflicts)
        self.assertFalse(plan.changed)

        agent.write_bytes(original + b"\nlocal edit\n")
        remove_plan = installer.plan_remove(self.target)
        self.assertTrue(remove_plan.conflicts)
        self.assertTrue(agent.exists())

    def test_remove_deletes_claude_agents(self) -> None:
        self.install(("claude",))

        plan = installer.plan_remove(self.target)

        self.assertFalse(plan.conflicts)
        installer.apply_plan(self.target, plan)
        self.assertFalse((self.target / ".claude").exists())

    def test_init_preserves_existing_repository_instructions(self) -> None:
        original = "# Local policy\n\nRun the project tests.\n"
        (self.target / "AGENTS.md").write_text(original, encoding="utf-8")

        self.install(("claude",))

        merged = (self.target / "AGENTS.md").read_text(encoding="utf-8")
        self.assertTrue(merged.startswith(original.rstrip()))
        self.assertIn(installer.AGENTS_START, merged)
        self.assertIn(installer.AGENTS_END, merged)
        self.assertFalse((self.target / ".opencode").exists())

    def test_init_creates_gitignore_with_managed_block(self) -> None:
        self.install(("opencode",))

        gitignore = (self.target / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(installer.GITIGNORE_START, gitignore)
        self.assertIn(installer.GITIGNORE_END, gitignore)
        self.assertIn(".codev/task/escalations.jsonl", gitignore)
        self.assertIn(".codev/hooks/decisions.jsonl", gitignore)
        lock = json.loads((self.target / ".codev" / "lock.json").read_text())
        self.assertIn("gitignore_block_hash", lock["integrations"])

    def test_init_preserves_existing_gitignore_content(self) -> None:
        original = "node_modules/\n*.log\n"
        (self.target / ".gitignore").write_text(original, encoding="utf-8")

        self.install(("opencode",))

        merged = (self.target / ".gitignore").read_text(encoding="utf-8")
        self.assertTrue(merged.startswith(original.rstrip()))
        self.assertIn("node_modules/", merged)
        self.assertIn(installer.GITIGNORE_START, merged)

    def test_init_conflicts_on_different_gitignore_block(self) -> None:
        (self.target / ".gitignore").write_text(
            f"{installer.GITIGNORE_START}\nsomething-else\n{installer.GITIGNORE_END}\n",
            encoding="utf-8",
        )

        plan = installer.plan_init(self.target, ("opencode",), "none")

        self.assertTrue(any(item.path == ".gitignore" for item in plan.conflicts))

    def test_update_integrates_gitignore_for_a_prior_install(self) -> None:
        self.install(("opencode",))
        # Simulate an install that predates the gitignore integration: no
        # block in the file, and no record of it in the lock file.
        (self.target / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
        lock_path = self.target / ".codev" / "lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["integrations"].pop("gitignore_block_hash")
        lock_path.write_text(json.dumps(lock), encoding="utf-8")

        plan = installer.plan_update(self.target)

        self.assertFalse(plan.conflicts)
        installer.apply_plan(self.target, plan)
        gitignore = (self.target / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("node_modules/", gitignore)
        self.assertIn(installer.GITIGNORE_START, gitignore)
        updated_lock = json.loads(lock_path.read_text(encoding="utf-8"))
        self.assertIn("gitignore_block_hash", updated_lock["integrations"])

    def test_update_rejects_modified_gitignore_block(self) -> None:
        self.install(("opencode",))
        gitignore_path = self.target / ".gitignore"
        text = gitignore_path.read_text(encoding="utf-8")
        gitignore_path.write_text(
            text.replace("escalations.jsonl", "tampered"), encoding="utf-8"
        )

        plan = installer.plan_update(self.target)

        self.assertTrue(any(item.path == ".gitignore" for item in plan.conflicts))

    def test_remove_removes_managed_gitignore_block_and_preserves_other_content(
        self,
    ) -> None:
        (self.target / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
        self.install(("opencode",))

        plan = installer.plan_remove(self.target)

        self.assertFalse(plan.conflicts)
        installer.apply_plan(self.target, plan)
        gitignore = (self.target / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("node_modules/", gitignore)
        self.assertNotIn(installer.GITIGNORE_START, gitignore)
        self.assertNotIn("escalations.jsonl", gitignore)

    def test_check_project_flags_tampered_gitignore_block(self) -> None:
        self.install(("opencode",))
        gitignore_path = self.target / ".gitignore"
        text = gitignore_path.read_text(encoding="utf-8")
        gitignore_path.write_text(text.replace("escalations.jsonl", "tampered"))

        result = installer.check_project(self.target)

        self.assertFalse(result.ok)
        self.assertTrue(any("gitignore" in issue.lower() for issue in result.issues))

    def test_init_preserves_existing_opencode_default(self) -> None:
        config_path = self.target / ".opencode" / "opencode.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            json.dumps({"default_agent": "my-existing-agent", "theme": "system"}),
            encoding="utf-8",
        )

        self.install(("opencode",))

        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual("my-existing-agent", config["default_agent"])
        self.assertEqual("system", config["theme"])
        self.assertIn("$schema", config)
        self.assertEqual(installer.OPENCODE_AGENT_CONFIGS, config["agent"])
        self.assertEqual("primary", config["agent"]["code-audit"]["mode"])

    def test_init_preserves_existing_opencode_agent(self) -> None:
        config_path = self.target / ".opencode" / "opencode.json"
        config_path.parent.mkdir(parents=True)
        local_lead = {
            "model": "anthropic/claude-sonnet-4",
            "description": "Project-owned orchestrator",
        }
        config_path.write_text(
            json.dumps({"agent": {"lead": local_lead}}),
            encoding="utf-8",
        )

        self.install(("opencode",))

        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(local_lead, config["agent"]["lead"])
        self.assertEqual(
            installer.OPENCODE_AGENT_CONFIGS["builder"], config["agent"]["builder"]
        )
        self.assertEqual(
            installer.OPENCODE_AGENT_CONFIGS["reviewer"], config["agent"]["reviewer"]
        )
        self.assertEqual(
            installer.OPENCODE_AGENT_CONFIGS["code-audit"],
            config["agent"]["code-audit"],
        )

    def test_update_rejects_modified_managed_opencode_agent(self) -> None:
        self.install(("opencode",))
        config_path = self.target / ".opencode" / "opencode.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["agent"]["builder"]["model"] = "project/custom"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        plan = installer.plan_update(self.target)

        self.assertTrue(
            any(item.path == ".opencode/opencode.json" for item in plan.conflicts)
        )

    def test_update_integrates_agents_for_a_prior_opencode_install(self) -> None:
        self.install(("opencode",))
        config_path = self.target / ".opencode" / "opencode.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config.pop("agent")
        config_path.write_text(json.dumps(config), encoding="utf-8")
        lock_path = self.target / ".codev" / "lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["integrations"].pop("opencode_agent_hashes")
        lock_path.write_text(json.dumps(lock), encoding="utf-8")

        plan = installer.plan_update(self.target)

        self.assertFalse(plan.conflicts)
        installer.apply_plan(self.target, plan)
        updated = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(installer.OPENCODE_AGENT_CONFIGS, updated["agent"])

    def test_remove_deletes_managed_files_and_preserves_shared_content(self) -> None:
        agents_path = self.target / "AGENTS.md"
        agents_path.write_text("# Project policy\n", encoding="utf-8")
        config_path = self.target / ".opencode" / "opencode.json"
        config_path.parent.mkdir(parents=True)
        local_lead = {"model": "project/model"}
        config_path.write_text(
            json.dumps(
                {
                    "default_agent": "project-agent",
                    "theme": "system",
                    "agent": {"lead": local_lead},
                }
            ),
            encoding="utf-8",
        )
        self.install(("opencode",))

        plan = installer.plan_remove(self.target)

        self.assertFalse(plan.conflicts)
        installer.apply_plan(self.target, plan)
        self.assertFalse((self.target / ".codev" / "lock.json").exists())
        self.assertFalse((self.target / ".codev").exists())
        self.assertFalse((self.target / ".agents" / "skills").exists())
        self.assertFalse((self.target / ".agents").exists())
        self.assertFalse((self.target / ".opencode" / "agents" / "builder.md").exists())
        self.assertNotIn(
            installer.AGENTS_START, agents_path.read_text(encoding="utf-8")
        )
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual("project-agent", config["default_agent"])
        self.assertEqual("system", config["theme"])
        self.assertEqual(local_lead, config["agent"]["lead"])
        self.assertNotIn("builder", config["agent"])
        self.assertNotIn("code-audit", config["agent"])
        self.assertNotIn("reviewer", config["agent"])
        self.assertNotIn("$schema", config)

    def test_remove_deletes_a_managed_opencode_config_file(self) -> None:
        self.install(("opencode",))

        plan = installer.plan_remove(self.target)

        self.assertFalse(plan.conflicts)
        installer.apply_plan(self.target, plan)
        self.assertFalse((self.target / ".opencode" / "opencode.json").exists())

    def test_remove_conflict_prevents_all_deletions(self) -> None:
        self.install(("opencode",))
        skill = self.target / ".agents" / "skills" / "review-change" / "SKILL.md"
        skill.write_text(
            skill.read_text(encoding="utf-8") + "local edit\n", encoding="utf-8"
        )

        plan = installer.plan_remove(self.target)

        self.assertTrue(plan.conflicts)
        with self.assertRaises(installer.CoDevError):
            installer.apply_plan(self.target, plan)
        self.assertTrue(skill.exists())
        self.assertTrue((self.target / ".codev" / "lock.json").exists())

    def test_init_stops_before_writing_on_collision(self) -> None:
        collision = self.target / ".agents" / "skills" / "build-change" / "SKILL.md"
        collision.parent.mkdir(parents=True)
        collision.write_text("project-owned\n", encoding="utf-8")

        plan = installer.plan_init(self.target, ("opencode",))

        self.assertTrue(plan.conflicts)
        with self.assertRaises(installer.CoDevError):
            installer.apply_plan(self.target, plan)
        self.assertEqual("project-owned\n", collision.read_text(encoding="utf-8"))
        self.assertFalse((self.target / ".codev/lock.json").exists())

    def test_update_is_idempotent(self) -> None:
        self.install(("opencode",))

        plan = installer.plan_update(self.target)

        self.assertFalse(plan.conflicts)
        self.assertFalse(plan.changed)
        installer.apply_plan(self.target, plan)
        self.assertTrue(installer.check_project(self.target).ok)

    def test_update_removes_stale_file_when_upstream_renames_it(self) -> None:
        self.install(("opencode",))
        current_bundle = installer._bundle_files(("opencode",))
        old_path = ".codev/for-ai/ai-agent-guidelines.md"
        new_path = "docs/renamed/ai-agent-guidelines.md"
        renamed_bundle = dict(current_bundle)
        renamed_bundle[new_path] = renamed_bundle.pop(old_path)

        with patch.object(installer, "_bundle_files", return_value=renamed_bundle):
            plan = installer.plan_update(self.target)

        remove_ops = [op for op in plan.operations if op.path == old_path]
        self.assertEqual(1, len(remove_ops))
        self.assertEqual("remove", remove_ops[0].kind)
        self.assertIn(new_path, remove_ops[0].detail)
        add_ops = [op for op in plan.operations if op.path == new_path]
        self.assertEqual(1, len(add_ops))
        self.assertEqual("add", add_ops[0].kind)

        installer.apply_plan(self.target, plan)
        self.assertFalse((self.target / old_path).exists())
        self.assertTrue((self.target / new_path).is_file())

    def test_update_retires_renamed_file_with_local_changes_instead_of_deleting(
        self,
    ) -> None:
        self.install(("opencode",))
        current_bundle = installer._bundle_files(("opencode",))
        old_path = ".codev/for-ai/ai-agent-guidelines.md"
        new_path = "docs/renamed/ai-agent-guidelines.md"
        renamed_bundle = dict(current_bundle)
        renamed_bundle[new_path] = renamed_bundle.pop(old_path)

        local_file = self.target / old_path
        local_file.write_bytes(local_file.read_bytes() + b"\nlocal note\n")

        with patch.object(installer, "_bundle_files", return_value=renamed_bundle):
            plan = installer.plan_update(self.target)

        ops = [op for op in plan.operations if op.path == old_path]
        self.assertEqual(1, len(ops))
        self.assertEqual("retire", ops[0].kind)
        self.assertIn(new_path, ops[0].detail)
        self.assertNotIn(local_file, plan.deletions)

    def test_check_reports_managed_file_drift(self) -> None:
        self.install(("opencode",))
        skill = self.target / ".agents" / "skills" / "review-change" / "SKILL.md"
        skill.write_text(
            skill.read_text(encoding="utf-8") + "\nlocal edit\n",
            encoding="utf-8",
        )

        result = installer.check_project(self.target)

        self.assertFalse(result.ok)
        self.assertTrue(
            any("review-change/SKILL.md" in issue for issue in result.issues)
        )

    def test_update_conflict_prevents_all_planned_writes(self) -> None:
        self.install(("opencode",))
        current_bundle = installer._bundle_files(("opencode",))
        first, second = sorted(current_bundle)[:2]
        changed_bundle = dict(current_bundle)
        changed_bundle[first] += b"\nupstream one\n"
        changed_bundle[second] += b"\nupstream two\n"
        first_path = (self.target / Path(first)).resolve()
        second_path = (self.target / Path(second)).resolve()
        original_first = first_path.read_bytes()
        second_path.write_bytes(second_path.read_bytes() + b"\nlocal edit\n")

        with patch.object(installer, "_bundle_files", return_value=changed_bundle):
            plan = installer.plan_update(self.target)
            self.assertTrue(plan.conflicts)
            self.assertIn(first_path, plan.writes)
            with self.assertRaises(installer.CoDevError):
                installer.apply_plan(self.target, plan)

        self.assertEqual(original_first, first_path.read_bytes())

    def test_modified_agents_block_is_a_conflict(self) -> None:
        self.install(("opencode",))
        agents = self.target / "AGENTS.md"
        agents.write_text(
            agents.read_text(encoding="utf-8").replace(
                "Use the lightest safe path.", "Use every possible document."
            ),
            encoding="utf-8",
        )

        plan = installer.plan_update(self.target)

        self.assertTrue(any(item.path == "AGENTS.md" for item in plan.conflicts))

    def _make_single_file_conflict(self) -> tuple[str, bytes, bytes]:
        """Install, then create one conflicted managed file: OpenCode's code-
        audit agent both changes upstream and gets a local edit. Returns
        (relative path, local bytes, upstream bytes)."""
        self.install(("opencode",))
        current_bundle = installer._bundle_files(("opencode",))
        relative = ".opencode/agents/code-audit.md"
        upstream = current_bundle[relative] + b"\n# upstream change\n"
        changed_bundle = dict(current_bundle)
        changed_bundle[relative] = upstream
        destination = (self.target / Path(relative)).resolve()
        destination.write_bytes(destination.read_bytes() + b"\n# local edit\n")
        local = destination.read_bytes()
        self._bundle_patch = patch.object(
            installer, "_bundle_files", return_value=changed_bundle
        )
        self._bundle_patch.start()
        self.addCleanup(self._bundle_patch.stop)
        return relative, local, upstream

    def test_apply_plan_with_override_resolution_adopts_upstream(self) -> None:
        relative, _local, upstream = self._make_single_file_conflict()
        plan = installer.plan_update(self.target)
        conflict = next(item for item in plan.conflicts if item.path == relative)
        self.assertEqual(upstream, conflict.new_content)

        unresolved = installer.apply_plan(
            self.target, plan, {relative: installer.Resolution.OVERRIDE}
        )

        self.assertEqual([], unresolved)
        self.assertEqual(upstream, (self.target / Path(relative)).read_bytes())
        self.assertEqual([], installer.plan_update(self.target).conflicts)

    def test_apply_plan_with_keep_resolution_preserves_local_as_new_baseline(
        self,
    ) -> None:
        relative, local, _upstream = self._make_single_file_conflict()
        plan = installer.plan_update(self.target)

        unresolved = installer.apply_plan(
            self.target, plan, {relative: installer.Resolution.KEEP}
        )

        self.assertEqual([], unresolved)
        self.assertEqual(local, (self.target / Path(relative)).read_bytes())
        self.assertEqual([], installer.plan_update(self.target).conflicts)

    def test_apply_plan_with_copy_resolution_writes_sidecar_and_stays_conflicted(
        self,
    ) -> None:
        relative, local, upstream = self._make_single_file_conflict()
        plan = installer.plan_update(self.target)

        unresolved = installer.apply_plan(
            self.target, plan, {relative: installer.Resolution.COPY}
        )

        self.assertEqual(1, len(unresolved))
        self.assertEqual(relative, unresolved[0].path)
        destination = self.target / Path(relative)
        self.assertEqual(local, destination.read_bytes())
        sidecar = installer.copy_sidecar_path(destination)
        self.assertEqual(upstream, sidecar.read_bytes())
        self.assertTrue(installer.plan_update(self.target).conflicts)
        result = installer.check_project(self.target)
        self.assertFalse(result.ok)
        self.assertTrue(
            any(relative in issue for issue in result.issues), result.issues
        )

    def test_apply_plan_with_delete_resolution_removes_the_local_file(self) -> None:
        relative, _local, _upstream = self._make_single_file_conflict()
        plan = installer.plan_update(self.target)

        unresolved = installer.apply_plan(
            self.target, plan, {relative: installer.Resolution.DELETE}
        )

        self.assertEqual([], unresolved)
        self.assertFalse((self.target / Path(relative)).exists())
        replanned = [
            item
            for item in installer.plan_update(self.target).operations
            if item.path == relative
        ]
        self.assertEqual(["add"], [item.kind for item in replanned])

    def test_apply_plan_leaves_a_skipped_conflict_untouched_but_writes_the_rest(
        self,
    ) -> None:
        self.install(("opencode",))
        current_bundle = installer._bundle_files(("opencode",))
        first, second = sorted(current_bundle)[:2]
        changed_bundle = dict(current_bundle)
        changed_bundle[first] += b"\nupstream one\n"
        changed_bundle[second] += b"\nupstream two\n"
        first_path = (self.target / Path(first)).resolve()
        second_path = (self.target / Path(second)).resolve()
        second_path.write_bytes(second_path.read_bytes() + b"\nlocal edit\n")
        local_second = second_path.read_bytes()

        with patch.object(installer, "_bundle_files", return_value=changed_bundle):
            plan = installer.plan_update(self.target)
            self.assertTrue(plan.conflicts)
            unresolved = installer.apply_plan(
                self.target, plan, {second: installer.Resolution.SKIP}
            )

        self.assertEqual(1, len(unresolved))
        self.assertEqual(second, unresolved[0].path)
        self.assertEqual(changed_bundle[first], first_path.read_bytes())
        self.assertEqual(local_second, second_path.read_bytes())

        # A skipped conflict must stay a visible problem, not silently drop
        # out of management: `codev status` (`check_project`) has to keep
        # reporting it until the conflict is genuinely resolved, not report
        # "no drift" just because this update chose to skip it.
        result = installer.check_project(self.target)
        self.assertFalse(result.ok)
        self.assertTrue(any(second in issue for issue in result.issues), result.issues)

    def test_apply_plan_delete_stops_tracking_the_deleted_path(self) -> None:
        # DELETE must NOT inherit the old-hash re-seeding that keeps a
        # SKIPped conflict visible as drift (tested above): the file is gone,
        # so there's nothing left for a future hash comparison to mean.
        relative, _local, _upstream = self._make_single_file_conflict()
        plan = installer.plan_update(self.target)

        unresolved = installer.apply_plan(
            self.target, plan, {relative: installer.Resolution.DELETE}
        )

        self.assertEqual([], unresolved)
        self.assertFalse((self.target / Path(relative)).exists())
        lock = json.loads(
            (self.target / ".codev" / "lock.json").read_text(encoding="utf-8")
        )
        self.assertNotIn(relative, lock["files"])
        result = installer.check_project(self.target)
        self.assertTrue(result.ok, result.issues)

    def test_skipped_new_file_collision_has_no_baseline_to_restore(self) -> None:
        # Distinguishes the fix above from over-reach: a brand-new bundle
        # file that collides with an unrelated pre-existing local file was
        # never previously managed, so it has no old hash to re-seed and
        # correctly stays untracked after a skip -- there was never a
        # "should look like X" expectation for `check_project` to enforce.
        self.install(("opencode",))
        current_bundle = installer._bundle_files(("opencode",))
        relative = "docs/codev/onboarding/brand-new-file.md"
        self.assertNotIn(relative, current_bundle)
        expanded_bundle = dict(current_bundle)
        expanded_bundle[relative] = b"new upstream content\n"
        destination = (self.target / Path(relative)).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"unrelated pre-existing local content\n")

        with patch.object(installer, "_bundle_files", return_value=expanded_bundle):
            plan = installer.plan_update(self.target)
            conflict = next(item for item in plan.conflicts if item.path == relative)
            self.assertIn("collides locally", conflict.detail)
            unresolved = installer.apply_plan(
                self.target, plan, {relative: installer.Resolution.SKIP}
            )

        self.assertEqual(1, len(unresolved))
        lock = json.loads(
            (self.target / ".codev" / "lock.json").read_text(encoding="utf-8")
        )
        self.assertNotIn(relative, lock["files"])
        result = installer.check_project(self.target)
        self.assertTrue(result.ok, result.issues)

    def test_apply_plan_override_without_upstream_content_raises(self) -> None:
        self.install(("opencode",))
        plan = installer.plan_update(self.target)
        plan.operations.append(
            installer.Operation("conflict", "no/such/file.md", "manufactured")
        )

        with self.assertRaises(installer.CoDevError):
            installer.apply_plan(
                self.target,
                plan,
                {"no/such/file.md": installer.Resolution.OVERRIDE},
            )


class OpencodeAgentConfigCoverageTests(unittest.TestCase):
    def test_every_bundled_opencode_agent_is_registered(self) -> None:
        """Regression test: an `.opencode/agents/*.md` file with no matching
        `OPENCODE_AGENT_CONFIGS` entry never gets written into a target
        repository's `.opencode/opencode.json`, so OpenCode has nothing
        telling it the agent exists -- this caught `outer-loop-runner` and
        six other agents missing from the config entirely, silent because
        `_walk_bundle()`/installer file-copying never consulted this dict at
        all, only `.opencode/opencode.json` merging did.
        """
        agents_dir = Path(installer.__file__).parent / "bundle" / ".opencode" / "agents"
        bundled_names = {path.stem for path in agents_dir.glob("*.md")}
        rendered_code_audit = Path(installer.AUDIT_AGENT_TEMPLATES["opencode"][1]).stem
        bundled_names.add(rendered_code_audit)
        missing = sorted(bundled_names - set(installer.OPENCODE_AGENT_CONFIGS))
        self.assertEqual([], missing)


class InternalDevToolingExcludedFromBundleTests(unittest.TestCase):
    """Regression test (ADR-0009): this repository's own workflow-validation
    scripts and their catalog must never reappear inside
    src/codev_workflow/bundle/ -- they are development tooling for this
    project, not something a target repository installs or runs."""

    def test_walk_bundle_excludes_internal_dev_tooling(self) -> None:
        files = installer._walk_bundle()
        leaked = [
            path
            for path in files
            if path.endswith("evaluate-development-workflow.py")
            or path.endswith("validate-development-workflow.py")
            or path.endswith("evals/development-workflow/scenarios.json")
        ]
        self.assertEqual([], leaked)


class SkillCardAndLicenseTests(unittest.TestCase):
    """Every bundled skill carries a real `license` frontmatter field and a
    filled-out `skill-card.md`, per docs/adr/0029-adopt-skill-cards-and-
    license-metadata.md. Both ship to an installed project automatically --
    `_walk_bundle()` copies every file under bundle/, no separate install-time
    logic exists for either -- so walking the bundle here is the real,
    installed-project view, not a shortcut around it."""

    _REQUIRED_SKILL_CARD_SECTIONS = (
        "**Description:**",
        "**Owner:**",
        "**License / Terms of Use:**",
        "**Use Case:**",
        "**Deployment Geography for Use:**",
        "**Requirements / Dependencies:**",
        "**Known Risks and Mitigations:**",
        "**References:**",
        "**Skill Output:**",
        "**Skill Version:**",
        "**Ethical Considerations:**",
    )

    def _bundled_skill_names(self, files: dict[str, bytes]) -> set[str]:
        return {
            path.split("/")[2]
            for path in files
            if path.startswith(".agents/skills/") and path.endswith("/SKILL.md")
        }

    def test_every_bundled_skill_declares_a_license(self) -> None:
        files = installer._walk_bundle()
        names = self._bundled_skill_names(files)
        self.assertTrue(names)
        for name in sorted(names):
            with self.subTest(skill=name):
                text = files[f".agents/skills/{name}/SKILL.md"].decode("utf-8")
                lines = text.splitlines()
                end = lines.index("---", 1)
                license_lines = [
                    line for line in lines[1:end] if line.startswith("license:")
                ]
                self.assertEqual(
                    1, len(license_lines), f"{name}: expected exactly one license field"
                )
                self.assertIn("BSD-3-Clause", license_lines[0])

    def test_every_bundled_skill_has_a_filled_out_skill_card(self) -> None:
        files = installer._walk_bundle()
        names = self._bundled_skill_names(files)
        for name in sorted(names):
            with self.subTest(skill=name):
                path = f".agents/skills/{name}/skill-card.md"
                self.assertIn(path, files, f"{name}: missing skill-card.md")
                text = files[path].decode("utf-8")
                self.assertIn(f"# Skill Card: {name}", text)
                for section in self._REQUIRED_SKILL_CARD_SECTIONS:
                    with self.subTest(section=section):
                        self.assertIn(section, text)
                # A skill card copied from the template without being filled
                # in still contains its bracketed placeholder prose -- catch
                # that instead of silently accepting an unfilled copy.
                self.assertNotIn("[", text)
                self.assertNotIn("]", text)

    def test_skill_card_template_is_bundled_and_lists_every_section(self) -> None:
        files = installer._walk_bundle()
        path = "docs/codev/onboarding/skill-card.template.md"
        self.assertIn(path, files)
        text = files[path].decode("utf-8")
        for section in self._REQUIRED_SKILL_CARD_SECTIONS:
            with self.subTest(section=section):
                self.assertIn(section, text)


class CodeownersInitTests(unittest.TestCase):
    def test_writes_a_starter_file_under_dot_github(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / "src").mkdir()
            (target / "docs").mkdir()
            (target / ".git").mkdir()
            destination = installer.codeowners_init(target)
            self.assertEqual(target.resolve() / ".github" / "CODEOWNERS", destination)
            text = destination.read_text(encoding="utf-8")
        self.assertIn("CODEOWNERS", text)
        self.assertIn("# src/  @your-team-here", text)
        self.assertIn("# docs/  @your-team-here", text)
        self.assertNotIn(".git/", text)

    def test_refuses_when_a_codeowners_file_already_exists_at_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / "CODEOWNERS").write_text("* @someone\n", encoding="utf-8")
            with self.assertRaises(installer.CoDevError):
                installer.codeowners_init(target)

    def test_refuses_when_a_codeowners_file_already_exists_under_docs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / "docs").mkdir()
            (target / "docs" / "CODEOWNERS").write_text(
                "* @someone\n", encoding="utf-8"
            )
            with self.assertRaises(installer.CoDevError):
                installer.codeowners_init(target)

    def test_never_overwrites_an_existing_dot_github_codeowners(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / ".github").mkdir()
            existing = target / ".github" / "CODEOWNERS"
            existing.write_text("* @someone\n", encoding="utf-8")
            with self.assertRaises(installer.CoDevError):
                installer.codeowners_init(target)
            self.assertEqual("* @someone\n", existing.read_text(encoding="utf-8"))

    def test_placeholder_line_when_no_top_level_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            destination = installer.codeowners_init(target)
            text = destination.read_text(encoding="utf-8")
        self.assertIn("# path/pattern  @your-team-here", text)


class AdapterRemoveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.target = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def install(
        self,
        platforms: tuple[str, ...] = ("all",),
        programming_language: str = "none",
    ) -> installer.Plan:
        plan = installer.plan_init(self.target, platforms, programming_language)
        self.assertFalse(plan.conflicts)
        installer.apply_plan(self.target, plan)
        return plan

    def test_remove_opencode_from_multi_platform_install(self) -> None:
        self.install(("claude", "opencode"))
        self.assertTrue((self.target / ".opencode" / "agents" / "builder.md").is_file())
        self.assertTrue((self.target / ".claude" / "agents" / "builder.md").is_file())

        plan = installer.plan_adapter_remove(self.target, "opencode")

        self.assertFalse(plan.conflicts)
        installer.apply_plan(self.target, plan)
        self.assertFalse((self.target / ".opencode").exists())
        self.assertTrue((self.target / ".claude" / "agents" / "builder.md").is_file())
        lock = json.loads(
            (self.target / ".codev" / "lock.json").read_text(encoding="utf-8")
        )
        self.assertEqual(["claude"], lock["platforms"])
        self.assertFalse(any(p.startswith(".opencode/") for p in lock["files"]))

    def test_remove_claude_from_multi_platform_install(self) -> None:
        self.install(("opencode", "claude"))
        self.assertTrue((self.target / ".claude" / "agents" / "builder.md").is_file())
        self.assertTrue((self.target / ".opencode" / "agents" / "builder.md").is_file())

        plan = installer.plan_adapter_remove(self.target, "claude")

        self.assertFalse(plan.conflicts)
        installer.apply_plan(self.target, plan)
        self.assertFalse((self.target / ".claude").exists())
        self.assertTrue((self.target / ".opencode" / "agents" / "builder.md").is_file())
        lock = json.loads(
            (self.target / ".codev" / "lock.json").read_text(encoding="utf-8")
        )
        self.assertEqual(["opencode"], lock["platforms"])
        self.assertFalse(any(p.startswith(".claude/") for p in lock["files"]))

    def test_remove_shared_skills_preserved(self) -> None:
        self.install(("claude", "opencode"))
        skills_before = sorted(
            str(p.relative_to(self.target))
            for p in (self.target / ".agents" / "skills").glob("*")
        )

        plan = installer.plan_adapter_remove(self.target, "opencode")
        self.assertFalse(plan.conflicts)
        installer.apply_plan(self.target, plan)

        skills_after = sorted(
            str(p.relative_to(self.target))
            for p in (self.target / ".agents" / "skills").glob("*")
        )
        self.assertEqual(skills_before, skills_after)
        lock = json.loads(
            (self.target / ".codev" / "lock.json").read_text(encoding="utf-8")
        )
        self.assertTrue(any(p.startswith(".agents/skills/") for p in lock["files"]))

    def test_remove_last_platform_rejected(self) -> None:
        self.install(("opencode",))

        with self.assertRaises(installer.CoDevError) as ctx:
            installer.plan_adapter_remove(self.target, "opencode")
        self.assertIn("codev remove", str(ctx.exception))

    def test_remove_not_installed_platform_raises(self) -> None:
        self.install(("opencode",))

        with self.assertRaises(installer.CoDevError) as ctx:
            installer.plan_adapter_remove(self.target, "junie")
        self.assertIn("not installed", str(ctx.exception))

    def test_remove_unknown_platform_raises(self) -> None:
        self.install(("opencode",))
        with self.assertRaises(installer.CoDevError):
            installer.plan_adapter_remove(self.target, "bogus")

    def _mark_platform_stale(self, name: str) -> None:
        """Simulate a lock file predating a platform's removal from the tool.

        Injects `name` into the recorded platforms without any matching
        bundle files -- the same shape as a real pre-existing install of a
        platform later dropped (e.g. Codex, ADR-0031): recorded, but no
        longer something the current version can produce or validate.
        """
        lock_path = self.target / ".codev" / "lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["platforms"].append(name)
        lock_path.write_text(json.dumps(lock), encoding="utf-8")

    def test_remove_platform_no_longer_valid_but_still_recorded(self) -> None:
        self.install(("opencode",))
        self._mark_platform_stale("dropped-platform")

        plan = installer.plan_adapter_remove(self.target, "dropped-platform")

        self.assertFalse(plan.conflicts)
        installer.apply_plan(self.target, plan)
        lock = json.loads(
            (self.target / ".codev" / "lock.json").read_text(encoding="utf-8")
        )
        self.assertEqual(["opencode"], lock["platforms"])

    def test_update_tolerates_a_stale_recorded_platform(self) -> None:
        self.install(("opencode",))
        self._mark_platform_stale("dropped-platform")

        plan = installer.plan_update(self.target)

        self.assertFalse(plan.conflicts)

    def test_remove_conflict_on_local_edit(self) -> None:
        self.install(("claude", "opencode"))
        agent = self.target / ".opencode" / "agents" / "builder.md"
        original = agent.read_text(encoding="utf-8")
        agent.write_text(original + "\nlocal edit\n", encoding="utf-8")

        plan = installer.plan_adapter_remove(self.target, "opencode")

        self.assertTrue(plan.conflicts)
        self.assertTrue(agent.exists())
        lock = json.loads(
            (self.target / ".codev" / "lock.json").read_text(encoding="utf-8")
        )
        self.assertIn("opencode", lock["platforms"])

    def test_remove_opencode_cleans_config_managed_entries(self) -> None:
        self.install(("claude", "opencode"))
        config_path = self.target / ".opencode" / "opencode.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertIn("agent", config)
        self.assertIn("$schema", config)

        plan = installer.plan_adapter_remove(self.target, "opencode")
        self.assertFalse(plan.conflicts)
        installer.apply_plan(self.target, plan)
        self.assertFalse(config_path.exists())

    def test_remove_opencode_preserves_user_owned_config(self) -> None:
        self.install(("claude", "opencode"))
        config_path = self.target / ".opencode" / "opencode.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["theme"] = "custom"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        plan = installer.plan_adapter_remove(self.target, "opencode")
        self.assertFalse(plan.conflicts)
        installer.apply_plan(self.target, plan)
        remaining = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual("custom", remaining["theme"])
        self.assertNotIn("agent", remaining)
        self.assertNotIn("$schema", remaining)

    def test_remove_produces_valid_lock(self) -> None:
        self.install(("claude", "opencode"))
        plan = installer.plan_adapter_remove(self.target, "opencode")
        self.assertFalse(plan.conflicts)
        installer.apply_plan(self.target, plan)

        lock = json.loads(
            (self.target / ".codev" / "lock.json").read_text(encoding="utf-8")
        )
        self.assertEqual(2, lock["schema_version"])
        self.assertEqual(["claude"], lock["platforms"])
        remaining_files = set(lock["files"])
        for rel in remaining_files:
            self.assertTrue(
                (self.target / rel).is_file(),
                f"lock references missing file {rel}",
            )

    def test_remove_then_add_back_round_trip(self) -> None:
        self.install(("claude", "opencode"))
        remove_plan = installer.plan_adapter_remove(self.target, "opencode")
        self.assertFalse(remove_plan.conflicts)
        installer.apply_plan(self.target, remove_plan)

        add_plan = installer.plan_update(self.target, ["opencode"])
        self.assertFalse(add_plan.conflicts)
        installer.apply_plan(self.target, add_plan)

        self.assertTrue((self.target / ".opencode" / "agents" / "builder.md").is_file())
        lock = json.loads(
            (self.target / ".codev" / "lock.json").read_text(encoding="utf-8")
        )
        self.assertIn("opencode", lock["platforms"])

    def test_dry_run_does_not_modify_files(self) -> None:
        self.install(("claude", "opencode"))
        plan = installer.plan_adapter_remove(self.target, "opencode")
        self.assertFalse(plan.conflicts)
        self.assertTrue(plan.changed)

        self.assertTrue((self.target / ".opencode" / "agents" / "builder.md").is_file())
        lock = json.loads(
            (self.target / ".codev" / "lock.json").read_text(encoding="utf-8")
        )
        self.assertIn("opencode", lock["platforms"])

    def test_remove_junie_from_multi_platform(self) -> None:
        self.install(("opencode", "junie"))
        self.assertTrue((self.target / ".junie" / "agents" / "assistant.md").is_file())

        plan = installer.plan_adapter_remove(self.target, "junie")
        self.assertFalse(plan.conflicts)
        installer.apply_plan(self.target, plan)
        self.assertFalse((self.target / ".junie").exists())
        self.assertTrue((self.target / ".opencode" / "agents" / "builder.md").is_file())


if __name__ == "__main__":
    unittest.main()
