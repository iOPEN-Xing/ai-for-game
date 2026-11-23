"""Keep persistence and framework dependencies outside the business rules."""

import ast
import re
import unittest

from studio.settings import ROOT

SQL = re.compile(
    r"^\s*(?:SELECT\s+.+?\s+FROM|INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|CREATE\s+TABLE)\b",
    re.I | re.S,
)


class ArchitectureTests(unittest.TestCase):
    def test_dependency_and_persistence_boundaries(self):
        for package in ("domain", "services", "api"):
            forbidden = {
                "domain": {
                    "os",
                    "sqlite3",
                    "fastapi",
                    "httpx",
                    "agentscope",
                    "quickjs",
                    "studio.infra",
                    "studio.services",
                    "studio.api",
                },
                "services": {"sqlite3", "fastapi"},
                "api": {"sqlite3", "quickjs", "agentscope"},
            }[package]
            for path in (ROOT / "studio" / package).glob("*.py"):
                with self.subTest(file=path.name):
                    for node in ast.walk(ast.parse(path.read_text())):
                        if isinstance(node, ast.Import):
                            mods = [a.name for a in node.names]
                        elif isinstance(node, ast.ImportFrom):
                            mods = [node.module or ""]
                            mods.extend(
                                (node.module or "") + "." + a.name for a in node.names
                            )
                        else:
                            mods = []
                        for mod in mods:
                            self.assertFalse(
                                any(
                                    mod == dep or mod.startswith(dep + ".")
                                    for dep in forbidden
                                ),
                                mod,
                            )
                        if isinstance(node, ast.Constant) and isinstance(
                            node.value, str
                        ):
                            self.assertIsNone(SQL.match(node.value), path.name)
