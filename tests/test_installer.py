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
import tomllib
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

        bundled = installer._bundle_files(("antigravity", "codex", "junie", "opencode"))
        self.assertFalse(any("__pycache__" in path for path in bundled))
        self.assertFalse(any(path.endswith(".pyc") for path in bundled))
        self.assertFalse(any(path.endswith(".template") for path in bundled))
        skills = sorted((self.target / ".agents" / "skills").glob("*/SKILL.md"))
        self.assertEqual(13, len(skills))
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
        self.assertTrue((self.target / ".opencode/agents/orchestrator.md").is_file())
        self.assertTrue((self.target / ".junie/agents/orchestrator.md").is_file())
        self.assertTrue((self.target / ".junie/commands/pr-review.md").is_file())
        self.assertTrue((self.target / ".agents/agents/orchestrator.md").is_file())
        self.assertTrue((self.target / ".codex/agents/builder.toml").is_file())
        self.assertTrue((self.target / ".codex/agents/orchestrator.toml").is_file())
        self.assertTrue((self.target / ".codex/agents/reviewer.toml").is_file())
        self.assertTrue(
            (self.target / "docs/codev/onboarding/onboarding-guide.md").is_file()
        )
        self.assertTrue((self.target / "docs/codev/onboarding/examples.md").is_file())
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
            self.target / ".junie/agents/code-audit-gate.md",
            self.target / ".agents/agents/code-audit-gate.md",
            self.target / ".codex/agents/code-audit-gate.toml",
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

    def test_codex_adapter_installs_valid_agents_without_other_adapters(self) -> None:
        self.install(("codex",))

        agents = sorted((self.target / ".codex" / "agents").glob("*.toml"))
        self.assertEqual(
            [
                "architecture-maintainability-specialist.toml",
                "builder.toml",
                "code-audit-gate.toml",
                "code-audit.toml",
                "concurrency-specialist.toml",
                "correctness-tests-specialist.toml",
                "lightweight-reviewer.toml",
                "orchestrator.toml",
                "outer-loop-runner.toml",
                "reviewer.toml",
                "rollout-specialist.toml",
                "security-data-specialist.toml",
            ],
            [path.name for path in agents],
        )
        for agent in agents:
            config = tomllib.loads(agent.read_text(encoding="utf-8"))
            self.assertEqual(agent.stem, config["name"])
            self.assertTrue(config["description"])
            self.assertTrue(config["developer_instructions"])
        self.assertFalse((self.target / ".opencode").exists())
        self.assertFalse((self.target / ".junie").exists())
        self.assertTrue(installer.check_project(self.target).ok)

    def test_bundle_filters_codex_adapter_files(self) -> None:
        codex_files = installer._bundle_files(("codex",))
        opencode_files = installer._bundle_files(("opencode",))

        self.assertEqual(
            {
                ".codex/agents/architecture-maintainability-specialist.toml",
                ".codex/agents/builder.toml",
                ".codex/agents/code-audit-gate.toml",
                ".codex/agents/code-audit.toml",
                ".codex/agents/concurrency-specialist.toml",
                ".codex/agents/correctness-tests-specialist.toml",
                ".codex/agents/lightweight-reviewer.toml",
                ".codex/agents/orchestrator.toml",
                ".codex/agents/outer-loop-runner.toml",
                ".codex/agents/reviewer.toml",
                ".codex/agents/rollout-specialist.toml",
                ".codex/agents/security-data-specialist.toml",
            },
            {path for path in codex_files if path.startswith(".codex/")},
        )
        self.assertFalse(any(path.startswith(".codex/") for path in opencode_files))

    def test_antigravity_adapter_uses_official_agents_location(self) -> None:
        self.install(("antigravity",))

        self.assertTrue((self.target / ".agents/agents/builder.md").is_file())
        self.assertTrue((self.target / ".agents/agents/code-audit.md").is_file())
        self.assertTrue((self.target / ".agents/agents/orchestrator.md").is_file())
        self.assertTrue((self.target / ".agents/agents/reviewer.md").is_file())
        self.assertFalse((self.target / ".junie").exists())
        self.assertFalse((self.target / ".opencode").exists())
        content = (self.target / ".agents/agents/reviewer.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("name: reviewer", content)
        self.assertIn("mainAgent: false", content)
        self.assertIn("subagent: true", content)
        audit = (self.target / ".agents/agents/code-audit.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("mainAgent: true", audit)
        self.assertIn("language-agnostic", audit)
        self.assertTrue(installer.check_project(self.target).ok)

    def test_junie_adapter_installs_valid_subagents_without_other_adapters(
        self,
    ) -> None:
        self.install(("junie",))

        self.assertTrue((self.target / ".junie/agents/builder.md").is_file())
        self.assertTrue((self.target / ".junie/agents/code-audit.md").is_file())
        self.assertTrue((self.target / ".junie/agents/orchestrator.md").is_file())
        self.assertTrue((self.target / ".junie/agents/reviewer.md").is_file())
        self.assertFalse((self.target / ".opencode").exists())
        self.assertIn(
            'description: "Bounded implementation subagent',
            (self.target / ".junie/agents/builder.md").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "language-agnostic",
            (self.target / ".junie/agents/code-audit.md").read_text(encoding="utf-8"),
        )
        self.assertTrue(installer.check_project(self.target).ok)

    def test_all_adapters_render_selected_audit_language(self) -> None:
        self.install(programming_language="python")

        agents = (
            self.target / ".opencode/agents/code-audit.md",
            self.target / ".junie/agents/code-audit.md",
            self.target / ".agents/agents/code-audit.md",
            self.target / ".codex/agents/code-audit.toml",
        )
        for agent in agents:
            content = agent.read_text(encoding="utf-8")
            self.assertIn("audit-google-python-style", content)
            self.assertNotIn("audit-google-typescript-style", content)
        self.assertTrue(installer.check_project(self.target).ok)

    def test_junie_managed_files_update_and_remove_safely(self) -> None:
        self.install(("junie",))
        agent = self.target / ".junie/agents/reviewer.md"
        original = agent.read_bytes()

        plan = installer.plan_update(self.target)
        self.assertFalse(plan.conflicts)
        self.assertFalse(plan.changed)

        agent.write_bytes(original + b"\nlocal edit\n")
        remove_plan = installer.plan_remove(self.target)
        self.assertTrue(remove_plan.conflicts)
        self.assertTrue(agent.exists())

    def test_remove_deletes_codex_agents(self) -> None:
        self.install(("codex",))

        plan = installer.plan_remove(self.target)

        self.assertFalse(plan.conflicts)
        installer.apply_plan(self.target, plan)
        self.assertFalse((self.target / ".codex").exists())

    def test_init_preserves_existing_repository_instructions(self) -> None:
        original = "# Local policy\n\nRun the project tests.\n"
        (self.target / "AGENTS.md").write_text(original, encoding="utf-8")

        self.install(("codex",))

        merged = (self.target / "AGENTS.md").read_text(encoding="utf-8")
        self.assertTrue(merged.startswith(original.rstrip()))
        self.assertIn(installer.AGENTS_START, merged)
        self.assertIn(installer.AGENTS_END, merged)
        self.assertFalse((self.target / ".opencode").exists())

    def test_init_creates_gitignore_with_managed_block(self) -> None:
        self.install(("codex",))

        gitignore = (self.target / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(installer.GITIGNORE_START, gitignore)
        self.assertIn(installer.GITIGNORE_END, gitignore)
        self.assertIn(".codev/work/escalations.jsonl", gitignore)
        lock = json.loads((self.target / ".codev" / "lock.json").read_text())
        self.assertIn("gitignore_block_hash", lock["integrations"])

    def test_init_preserves_existing_gitignore_content(self) -> None:
        original = "node_modules/\n*.log\n"
        (self.target / ".gitignore").write_text(original, encoding="utf-8")

        self.install(("codex",))

        merged = (self.target / ".gitignore").read_text(encoding="utf-8")
        self.assertTrue(merged.startswith(original.rstrip()))
        self.assertIn("node_modules/", merged)
        self.assertIn(installer.GITIGNORE_START, merged)

    def test_init_conflicts_on_different_gitignore_block(self) -> None:
        (self.target / ".gitignore").write_text(
            f"{installer.GITIGNORE_START}\nsomething-else\n{installer.GITIGNORE_END}\n",
            encoding="utf-8",
        )

        plan = installer.plan_init(self.target, ("codex",), "none")

        self.assertTrue(any(item.path == ".gitignore" for item in plan.conflicts))

    def test_update_integrates_gitignore_for_a_prior_install(self) -> None:
        self.install(("codex",))
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
        self.install(("codex",))
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
        self.install(("codex",))

        plan = installer.plan_remove(self.target)

        self.assertFalse(plan.conflicts)
        installer.apply_plan(self.target, plan)
        gitignore = (self.target / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("node_modules/", gitignore)
        self.assertNotIn(installer.GITIGNORE_START, gitignore)
        self.assertNotIn("escalations.jsonl", gitignore)

    def test_check_project_flags_tampered_gitignore_block(self) -> None:
        self.install(("codex",))
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
        local_orchestrator = {
            "model": "anthropic/claude-sonnet-4",
            "description": "Project-owned orchestrator",
        }
        config_path.write_text(
            json.dumps({"agent": {"orchestrator": local_orchestrator}}),
            encoding="utf-8",
        )

        self.install(("opencode",))

        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(local_orchestrator, config["agent"]["orchestrator"])
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
        local_orchestrator = {"model": "project/model"}
        config_path.write_text(
            json.dumps(
                {
                    "default_agent": "project-agent",
                    "theme": "system",
                    "agent": {"orchestrator": local_orchestrator},
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
        self.assertEqual(local_orchestrator, config["agent"]["orchestrator"])
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
        self.install(("codex",))
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

        plan = installer.plan_init(self.target, ("codex",))

        self.assertTrue(plan.conflicts)
        with self.assertRaises(installer.CoDevError):
            installer.apply_plan(self.target, plan)
        self.assertEqual("project-owned\n", collision.read_text(encoding="utf-8"))
        self.assertFalse((self.target / ".codev/lock.json").exists())

    def test_update_is_idempotent(self) -> None:
        self.install(("codex",))

        plan = installer.plan_update(self.target)

        self.assertFalse(plan.conflicts)
        self.assertFalse(plan.changed)
        installer.apply_plan(self.target, plan)
        self.assertTrue(installer.check_project(self.target).ok)

    def test_update_removes_stale_file_when_upstream_renames_it(self) -> None:
        self.install(("codex",))
        current_bundle = installer._bundle_files(("codex",))
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
        self.install(("codex",))
        current_bundle = installer._bundle_files(("codex",))
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
        self.install(("codex",))
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
        self.install(("codex",))
        current_bundle = installer._bundle_files(("codex",))
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
        self.install(("codex",))
        agents = self.target / "AGENTS.md"
        agents.write_text(
            agents.read_text(encoding="utf-8").replace(
                "Use the lightest safe path.", "Use every possible document."
            ),
            encoding="utf-8",
        )

        plan = installer.plan_update(self.target)

        self.assertTrue(any(item.path == "AGENTS.md" for item in plan.conflicts))


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


if __name__ == "__main__":
    unittest.main()
