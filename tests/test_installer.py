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

    def install(self, platforms: tuple[str, ...] = ("all",)) -> installer.Plan:
        plan = installer.plan_init(self.target, platforms)
        self.assertFalse(plan.conflicts)
        installer.apply_plan(self.target, plan)
        return plan

    def test_init_installs_complete_bundle_and_passes_check(self) -> None:
        self.install()

        bundled = installer._bundle_files(("antigravity", "codex", "junie", "opencode"))
        self.assertFalse(any("__pycache__" in path for path in bundled))
        self.assertFalse(any(path.endswith(".pyc") for path in bundled))
        skills = sorted((self.target / ".agents" / "skills").glob("*/SKILL.md"))
        self.assertEqual(10, len(skills))
        self.assertTrue((self.target / ".agents/skills/pr-review/SKILL.md").is_file())
        self.assertTrue(
            (self.target / ".agents/skills/clean-code-review/SKILL.md").is_file()
        )
        self.assertTrue(
            (self.target / ".agents/skills/critique-review/SKILL.md").is_file()
        )
        self.assertTrue((self.target / ".opencode/agents/orchestrator.md").is_file())
        self.assertTrue((self.target / ".junie/agents/orchestrator.md").is_file())
        self.assertTrue((self.target / ".junie/commands/pr-review.md").is_file())
        self.assertTrue((self.target / ".agents/agents/orchestrator.md").is_file())
        self.assertTrue((self.target / "docs/WORKFLOW-HUMAN.md").is_file())
        self.assertTrue((self.target / ".codev/lock.json").is_file())

        result = installer.check_project(self.target)
        self.assertTrue(result.ok, result.issues)
        self.assertGreater(result.managed_files, 30)

    def test_antigravity_adapter_uses_official_agents_location(self) -> None:
        self.install(("antigravity",))

        self.assertTrue((self.target / ".agents/agents/builder.md").is_file())
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
        self.assertTrue(installer.check_project(self.target).ok)

    def test_junie_adapter_installs_valid_subagents_without_other_adapters(
        self,
    ) -> None:
        self.install(("junie",))

        self.assertTrue((self.target / ".junie/agents/builder.md").is_file())
        self.assertTrue((self.target / ".junie/agents/orchestrator.md").is_file())
        self.assertTrue((self.target / ".junie/agents/reviewer.md").is_file())
        self.assertFalse((self.target / ".opencode").exists())
        self.assertIn(
            'description: "Bounded implementation subagent',
            (self.target / ".junie/agents/builder.md").read_text(encoding="utf-8"),
        )
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

    def test_init_preserves_existing_repository_instructions(self) -> None:
        original = "# Local policy\n\nRun the project tests.\n"
        (self.target / "AGENTS.md").write_text(original, encoding="utf-8")

        self.install(("codex",))

        merged = (self.target / "AGENTS.md").read_text(encoding="utf-8")
        self.assertTrue(merged.startswith(original.rstrip()))
        self.assertIn(installer.AGENTS_START, merged)
        self.assertIn(installer.AGENTS_END, merged)
        self.assertFalse((self.target / ".opencode").exists())

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


if __name__ == "__main__":
    unittest.main()
