"""Behavioral tests for the generated project reference bundle."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import unquote
from pathlib import Path
from types import ModuleType


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENERATOR = PROJECT_ROOT / "scripts" / "generate_reference_docs.py"
EXPECTED_FILES = {
    "DEPENDENCY_INVENTORY.md",
    "FRONTEND_IMPORT_GRAPH.md",
    "HTTP_ROUTES.md",
    "PYTHON_IMPORT_GRAPH.md",
    "SQLITE_SCHEMA.md",
    "database_schema.json",
    "dependencies.json",
    "frontend_import_graph.json",
    "http_routes.json",
    "python_import_graph.json",
}
GUIDE_FILES = (
    "README.md",
    "API_REFERENCE.md",
    "CODEBASE_GUIDE.md",
    "CONFIGURATION.md",
    "DATABASE_SCHEMA.md",
    "DEPENDENCIES.md",
    "KNOWLEDGE_CHAIN.md",
    "OPERATIONS.md",
)


class ReferenceDocsGeneratorTests(unittest.TestCase):
    def load_generator_module(self) -> ModuleType:
        spec = importlib.util.spec_from_file_location("reference_docs_generator", GENERATOR)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def run_generator(self, output_dir: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(GENERATOR),
                "--repo-root",
                str(PROJECT_ROOT),
                "--output-dir",
                str(output_dir),
                *extra,
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def test_cli_generates_the_same_complete_bundle_twice(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ag_reference_docs_") as temp:
            first = Path(temp) / "first"
            second = Path(temp) / "second"

            first_run = self.run_generator(first)
            second_run = self.run_generator(second)

            self.assertEqual(first_run.returncode, 0, first_run.stderr or first_run.stdout)
            self.assertEqual(second_run.returncode, 0, second_run.stderr or second_run.stdout)
            self.assertEqual({path.name for path in first.iterdir()}, EXPECTED_FILES)
            self.assertEqual({path.name for path in second.iterdir()}, EXPECTED_FILES)
            for name in EXPECTED_FILES:
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())

            routes = json.loads((first / "http_routes.json").read_text(encoding="utf-8"))
            self.assertIn(
                ("GET", "/api/control-center/overview"),
                {(route["method"], route["path"]) for route in routes["routes"]},
            )
            schema = json.loads((first / "database_schema.json").read_text(encoding="utf-8"))
            self.assertIn("control_campaigns", {table["name"] for table in schema["tables"]})
            graph = json.loads((first / "python_import_graph.json").read_text(encoding="utf-8"))
            self.assertIn(
                {"from": "src.control_center.store", "to": "src.control_center.artifacts"},
                graph["internal_edges"],
            )
            frontend_graph = json.loads(
                (first / "frontend_import_graph.json").read_text(encoding="utf-8")
            )
            self.assertIn(
                {
                    "from": "frontend/src/app/App.tsx",
                    "to": "frontend/src/components/shell/app-shell.tsx",
                },
                frontend_graph["internal_edges"],
            )
            self.assertIn("react", frontend_graph["external_dependencies"])
            dependencies = json.loads(
                (first / "dependencies.json").read_text(encoding="utf-8")
            )
            self.assertIn(
                {"name": "aiohttp", "requested": ">=3.9"},
                dependencies["python"]["direct"],
            )
            self.assertIn(
                {"name": "aiohttp", "version": "3.14.0"},
                dependencies["python"]["locked"],
            )
            self.assertIn(
                {"name": "mcp", "requested": "==2.1.1"},
                dependencies["python"]["profiles"]["mcp"]["direct"],
            )
            self.assertIn(
                {"name": "mcp", "version": "2.1.1"},
                dependencies["python"]["profiles"]["mcp"]["locked"],
            )
            self.assertIn(
                {
                    "license": "MIT",
                    "name": "react",
                    "requested": "^19.2.8",
                    "version": "19.2.8",
                },
                dependencies["frontend"]["runtime"],
            )
            self.assertEqual(dependencies["frontend"]["node_engine"], ">=22")

    def test_check_reports_drift_without_rewriting_the_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ag_reference_docs_") as temp:
            output_dir = Path(temp) / "generated"
            generate = self.run_generator(output_dir)
            self.assertEqual(generate.returncode, 0, generate.stderr or generate.stdout)

            current = self.run_generator(output_dir, "--check")
            self.assertEqual(current.returncode, 0, current.stderr or current.stdout)

            route_reference = output_dir / "HTTP_ROUTES.md"
            modified = route_reference.read_text(encoding="utf-8") + "local drift\n"
            route_reference.write_text(modified, encoding="utf-8")

            drift = self.run_generator(output_dir, "--check")
            self.assertEqual(drift.returncode, 1, drift.stderr or drift.stdout)
            self.assertIn("changed: HTTP_ROUTES.md", drift.stdout)
            self.assertEqual(route_reference.read_text(encoding="utf-8"), modified)

    def test_redaction_removes_machine_paths_and_common_token_shapes(self) -> None:
        module = self.load_generator_module()
        sample = (
            f"repo={PROJECT_ROOT}\n"
            f"home={Path.home()}\n"
            "Authorization: Bearer github_pat_abcdefghijklmnopqrstuvwxyz123456\n"
            "openai=sk-abcdefghijklmnopqrstuvwxyz123456\n"
            "remote=https://operator:secret@example.test/repository.git\n"
        )

        redacted = module._redact(sample, PROJECT_ROOT)

        self.assertNotIn(str(PROJECT_ROOT), redacted)
        self.assertNotIn(str(Path.home()), redacted)
        self.assertNotIn("github_pat_", redacted)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz", redacted)
        self.assertNotIn("operator:secret@", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_dynamic_route_registration_is_reported_as_unresolved(self) -> None:
        module = self.load_generator_module()
        with tempfile.TemporaryDirectory(prefix="ag_route_fixture_") as temp:
            root = Path(temp)
            source_dir = root / "src"
            source_dir.mkdir()
            (source_dir / "routes.py").write_text(
                "ROUTE_LABELS = {('GET', '/static'): 'Static'}\n"
                "ROUTES = (('GET', '/tuple'),)\n"
                "def register(app, dynamic_path, handler):\n"
                "    app.router.add_get('/static', handler)\n"
                "    for method, path in ROUTES:\n"
                "        app.router.add_route(method, path, handler)\n"
                "    app.router.add_get(dynamic_path, handler)\n",
                encoding="utf-8",
            )

            document = module.collect_http_routes(root)

        self.assertEqual(
            [(route["method"], route["path"]) for route in document["routes"]],
            [("GET", "/static"), ("GET", "/tuple")],
        )
        self.assertEqual(len(document["unresolved_registrations"]), 1)
        self.assertIn("dynamic_path", document["unresolved_registrations"][0]["expression"])

    def test_frontend_import_graph_resolves_alias_relative_and_package_imports(self) -> None:
        module = self.load_generator_module()
        with tempfile.TemporaryDirectory(prefix="ag_frontend_graph_") as temp:
            root = Path(temp)
            source_dir = root / "frontend" / "src"
            (source_dir / "components").mkdir(parents=True)
            (source_dir / "features").mkdir()
            (source_dir / "components" / "button.tsx").write_text(
                'import { clsx } from "clsx";\nexport const Button = clsx("button");\n',
                encoding="utf-8",
            )
            (source_dir / "features" / "panel.tsx").write_text(
                'export { Button } from "../components/button";\n',
                encoding="utf-8",
            )
            (source_dir / "main.tsx").write_text(
                'import { Button } from "@/components/button";\n'
                'const panel = import("@/features/panel");\n'
                'void Button; void panel;\n',
                encoding="utf-8",
            )

            document = module.collect_frontend_import_graph(root)

        self.assertEqual(
            document["internal_edges"],
            [
                {
                    "from": "frontend/src/features/panel.tsx",
                    "to": "frontend/src/components/button.tsx",
                },
                {
                    "from": "frontend/src/main.tsx",
                    "to": "frontend/src/components/button.tsx",
                },
                {
                    "from": "frontend/src/main.tsx",
                    "to": "frontend/src/features/panel.tsx",
                },
            ],
        )
        self.assertEqual(document["external_dependencies"], ["clsx"])
        self.assertEqual(document["unresolved_internal_imports"], [])

    def test_schema_probe_does_not_inherit_unrelated_environment_values(self) -> None:
        module = self.load_generator_module()
        completed = subprocess.CompletedProcess(
            args=[sys.executable],
            returncode=0,
            stdout=(
                '__REFERENCE_SCHEMA__'
                '{"format_version":1,"source":"fixture","tables":[],"user_version":0}'
            ),
            stderr="",
        )

        with mock.patch.dict(
            module.os.environ,
            {"PATH": "fixture-path", "SECRET_TEST_VALUE": "must-not-leak"},
            clear=True,
        ), mock.patch.object(module.subprocess, "run", return_value=completed) as run:
            module.collect_database_schema(PROJECT_ROOT)

        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["PATH"], "fixture-path")
        self.assertIn("ANTIGRAVITY_HUB_DB", environment)
        self.assertEqual(environment["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertNotIn("SECRET_TEST_VALUE", environment)

    def test_primary_documentation_links_resolve_locally(self) -> None:
        docs_root = PROJECT_ROOT / "docs"
        missing: list[str] = []
        for name in GUIDE_FILES:
            source = docs_root / name
            for raw_target in re.findall(
                r"\[[^\]]+\]\(([^)]+)\)",
                source.read_text(encoding="utf-8"),
            ):
                target = raw_target.strip().strip("<>").split("#", 1)[0]
                if not target or "://" in target or target.startswith("mailto:"):
                    continue
                resolved = (source.parent / unquote(target)).resolve()
                if not resolved.exists():
                    missing.append(f"{name}: {target}")

        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
