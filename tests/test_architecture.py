"""Verify application boundaries and the registrations needed to extend a workflow."""

import ast
import asyncio
import re
import unittest
from importlib.util import resolve_name
from unittest.mock import patch

from studio.application.agents import registry, skillbook
from studio.application.harness.production.nodes import AGENT_NODES, DELIVERABLES
from studio.application.prompts.builder import role_instructions
from studio.domain import agent_outputs, deliberation
from studio.domain.revision import STEPS
from studio.settings import ROOT

SQL = re.compile(
    r"^\s*(?:SELECT\s+.+?\s+FROM|INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|CREATE\s+TABLE)\b",
    re.I | re.S,
)

# Legacy entry points may import application modules. Internal code uses the implementation.
V1_FACADES = {
    "studio.acceptance",
    "studio.agents",
    "studio.cartridge",
    "studio.deliberation",
    "studio.operations",
    "studio.production",
    "studio.store",
}


def imports(node, package):
    if isinstance(node, ast.Import):
        return [item.name for item in node.names]
    if isinstance(node, ast.ImportFrom):
        source = resolve_name("." * node.level + (node.module or ""), package)
        return [source, *(source + "." + item.name for item in node.names)]
    return []


class ArchitectureTests(unittest.TestCase):
    def test_dependency_and_persistence_boundaries(self):
        app = "studio.application."
        workflow = {app + "harness", app + "usecases"}
        boundaries = {
            "domain": {
                "studio.infra",
                "studio.application",
                "os",
                "httpx",
                "quickjs",
                "agentscope",
                "fastapi",
            },
            "infra": {"studio.application", "studio.api"},
            "api": {"agentscope", "quickjs", app + "harness", app + "agents.gateway"},
            "application/agents": workflow | {app + "tools", "fastapi"},
            "application/prompts": workflow
            | {"studio.infra", "agentscope", app + "agents.gateway", "fastapi"},
            "application/memory": workflow | {"agentscope", "fastapi"},
            "application/tools": workflow | {app + "agents", "agentscope", "fastapi"},
            "application/harness": {"fastapi", "agentscope"},
            "application/usecases": {
                app + "harness",
                app + "agents.gateway",
                "agentscope",
                "fastapi",
            },
        }
        for layer, forbidden in boundaries.items():
            files = list((ROOT / "studio" / layer).rglob("*.py"))
            self.assertTrue(any(p.name != "__init__.py" for p in files), layer)
            forbidden = forbidden | V1_FACADES
            if layer != "infra":
                forbidden = forbidden | {"sqlite3"}
            if layer != "api":
                forbidden = forbidden | {"studio.api"}
            for path in files:
                relative = path.relative_to(ROOT)
                package = ".".join(relative.parts[:-1])
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                    for mod in imports(node, package):
                        with self.subTest(
                            file=str(relative), line=node.lineno, dependency=mod
                        ):
                            self.assertFalse(
                                any(
                                    mod == dep or mod.startswith(dep + ".")
                                    for dep in forbidden
                                )
                            )
                    if (
                        layer != "infra"
                        and isinstance(node, ast.Constant)
                        and isinstance(node.value, str)
                    ):
                        self.assertIsNone(
                            SQL.match(node.value), f"{relative}:{node.lineno}"
                        )

    def test_roles_have_workflow_contracts_prompts_and_packaged_skills(self):
        expected_nodes = {node for stage in STEPS.values() for node in stage} - {
            "validation"
        }
        self.assertEqual(set(AGENT_NODES), expected_nodes | {"impact"})
        self.assertEqual(
            {owner for owner, _ in AGENT_NODES.values()},
            {
                name
                for name, role in registry.ROLES.items()
                if role.team == "production"
            },
        )
        self.assertEqual(
            {owner for owner, _ in DELIVERABLES.values()},
            set(
                agent_outputs.Route.model_json_schema()["properties"]["next_role"][
                    "enum"
                ]
            ),
        )
        self.assertEqual(
            {*deliberation.EXPERTS, "Moderator"},
            {
                name
                for name, role in registry.ROLES.items()
                if role.team == "operations"
            },
        )
        prompt_dir = ROOT / "studio/application/prompts/roles"
        self.assertEqual({p.stem for p in prompt_dir.glob("*.md")}, set(registry.ROLES))
        available = {s["name"] for s in asyncio.run(skillbook.read())}
        for name, role in registry.ROLES.items():
            with self.subTest(role=name):
                self.assertTrue(role_instructions(name))
                for task in (
                    ("production",)
                    if role.team == "production"
                    else registry.TASK_SKILLS
                ):
                    required = set(registry.skills_for_role(name, task))
                    self.assertTrue(required)
                    self.assertLessEqual(
                        required,
                        set(registry.manifest_skills(registry.routes_for_run(task))),
                    )
                    self.assertLessEqual(required, available)

    def test_new_team_skill_is_pinned_only_for_its_workflow(self):
        addition = registry.Role("production", ("sample-art-direction",))
        with patch.dict(registry.ROLES, {"ArtAssistant": addition}):
            self.assertIn(
                "sample-art-direction",
                registry.manifest_skills(registry.routes_for_run("production")),
            )
            self.assertNotIn(
                "sample-art-direction",
                registry.manifest_skills(registry.routes_for_run("iteration")),
            )

    def test_v1_entry_points_resolve_to_the_application_implementations(self):
        from studio import acceptance, agents, cartridge, operations, production
        from studio.application.agents import gateway
        from studio.application.harness.operations import analysis
        from studio.application.harness.production import workflow
        from studio.application.tools import acceptance as verification
        from studio.application.tools import cartridge as compiler
        from studio.application.usecases.operations import decisions

        self.assertIs(agents.consult, gateway.consult)
        self.assertIs(agents.Art, agent_outputs.Art)
        self.assertIs(acceptance.verify, verification.verify)
        self.assertIs(cartridge.compile_bundle, compiler.compile_bundle)
        self.assertIs(production.produce, workflow.produce)
        self.assertIs(operations.analyze, analysis.analyze)
        self.assertIs(operations.review_proposal, decisions.review_proposal)
