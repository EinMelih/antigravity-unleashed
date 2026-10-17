import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src import project_stack, project_stack_handlers
from src.project_stack import (
    ProjectPathViolation,
    _resolve_relative_file,
    inspect_project_stack,
)
from src.proxy_server import create_app


SENTINEL = "stack-inspector-secret-sentinel"


def create_sqlite(path: Path, *, secret: str = SENTINEL) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, value TEXT)")
        connection.executemany(
            "INSERT INTO accounts(value) VALUES (?)",
            [(secret,), (f"{secret}-second",)],
        )
        connection.execute("INSERT INTO events(value) VALUES (?)", (secret,))
        connection.commit()
    finally:
        connection.close()


class ProjectStackInspectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "registered-project"
        self.root.mkdir()
        self.project = {
            "id": 17,
            "name": "Stack Test",
            "path": str(self.root),
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, relative: str, content: str) -> Path:
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def test_inspects_stack_without_exposing_secrets_rows_or_host_paths(self) -> None:
        self.write(
            "package.json",
            json.dumps(
                {
                    "dependencies": {
                        "react": "18.3.0",
                        "better-sqlite3": "11.0.0",
                    },
                    "devDependencies": {"vite": "5.0.0"},
                    "privateConfiguration": SENTINEL,
                }
            ),
        )
        self.write(
            "backend/pyproject.toml",
            f"""
[project]
name = "backend"
description = "{SENTINEL}"
dependencies = ["fastapi>=0.110", "psycopg[binary]>=3.1"]
""".strip(),
        )
        self.write(
            "Dockerfile",
            f"""
FROM node:20-alpine AS frontend
ARG PRIVATE_TOKEN={SENTINEL}
EXPOSE 3000/tcp 99999 $PORT
HEALTHCHECK CMD echo {SENTINEL}
FROM python:3.12-slim AS runtime
""".strip(),
        )
        self.write(
            "compose.yml",
            f"""
services:
  web:
    image: example/web:1.2
    build:
      context: .
    ports:
      - "8080:80"
    volumes:
      - "./src:/app/src:ro"
      - "/home/{SENTINEL}:/run/private:ro"
      - "C:\\Users\\{SENTINEL}:/run/windows-private:ro"
      - type: bind
        source: ${{CONFIG_PATH:-./config.json}}
        target: /app/config.json
        read_only: true
    depends_on:
      database:
        condition: service_healthy
    environment:
      API_TOKEN: "{SENTINEL}"
    healthcheck:
      test: ["CMD", "echo", "{SENTINEL}"]
  database:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: "{SENTINEL}"
volumes:
  app_data:
networks:
  private_net:
""".strip(),
        )
        self.write(".env", f"API_TOKEN={SENTINEL}\n")
        self.write(
            "node_modules/package.json",
            json.dumps({"dependencies": {SENTINEL: "1.0.0"}}),
        )
        create_sqlite(self.root / "data" / "application.sqlite")
        create_sqlite(self.root / "backups" / "ignored.sqlite")
        create_sqlite(self.root / "scratch" / "ignored.sqlite")

        payload = inspect_project_stack(self.project)
        serialized = json.dumps(payload, sort_keys=True)

        self.assertNotIn(SENTINEL, serialized)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn(str(self.base), serialized)
        self.assertNotIn("API_TOKEN", serialized)
        self.assertNotIn("POSTGRES_PASSWORD", serialized)
        self.assertNotIn("SELECT COUNT", serialized)
        self.assertTrue(payload["scan"]["read_only"])
        self.assertIn("relative response paths", " ".join(payload["privacy"]["guarantees"]))

        technology_ids = {item["id"] for item in payload["technologies"]}
        self.assertTrue(
            {"nodejs", "python", "react", "vite", "fastapi", "docker", "compose"}
            <= technology_ids
        )
        driver_ids = {item["id"] for item in payload["database_drivers"]}
        self.assertTrue({"sqlite", "postgresql"} <= driver_ids)

        manifests = {item["path"]: item for item in payload["manifests"]}
        self.assertEqual(manifests["package.json"]["dependency_count"], 2)
        self.assertEqual(manifests["package.json"]["dev_dependency_count"], 1)
        self.assertEqual(manifests["backend/pyproject.toml"]["dependency_count"], 2)
        self.assertNotIn("node_modules/package.json", manifests)

        dockerfile = payload["docker"]["dockerfiles"][0]
        self.assertEqual(dockerfile["base_images"], ["node:20-alpine", "python:3.12-slim"])
        self.assertEqual(dockerfile["exposed_ports"], ["3000/tcp"])
        self.assertEqual(dockerfile["healthcheck"], "configured")
        self.assertEqual([stage["name"] for stage in dockerfile["stages"]], ["frontend", "runtime"])

        compose = payload["docker"]["compose_files"][0]
        self.assertEqual(compose["named_volumes"], ["app_data"])
        self.assertEqual(compose["networks"], ["private_net"])
        services = {service["name"]: service for service in compose["services"]}
        self.assertEqual(services["web"]["image"], "example/web:1.2")
        self.assertEqual(services["web"]["build"]["context"], ".")
        self.assertEqual(services["web"]["ports"], ["8080:80"])
        self.assertEqual(services["web"]["depends_on"], ["database"])
        self.assertTrue(services["web"]["healthcheck"])
        external_volumes = [
            volume for volume in services["web"]["volumes"] if volume["external"]
        ]
        self.assertEqual(len(external_volumes), 3)
        self.assertTrue(
            all(volume["source"] == "<external-path>" for volume in external_volumes)
        )
        self.assertNotIn("type", {volume["source"] for volume in services["web"]["volumes"]})
        long_mount = next(
            volume
            for volume in services["web"]["volumes"]
            if volume["target"] == "/app/config.json"
        )
        self.assertEqual(long_mount["type"], "bind")
        self.assertTrue(long_mount["external"])

        self.assertEqual(len(payload["databases"]), 1)
        database = payload["databases"][0]
        self.assertEqual(database["path"], "data/application.sqlite")
        self.assertEqual(database["status"], "ok")
        self.assertEqual(database["quick_check"], "ok")
        self.assertEqual(database["table_count"], 2)
        table_counts = {table["name"]: table["row_count"] for table in database["tables"]}
        self.assertEqual(table_counts, {"accounts": 2, "events": 1})

    def test_rejects_absolute_traversal_and_external_symlink_paths(self) -> None:
        safe = self.write("nested/safe.txt", "safe")
        self.assertEqual(_resolve_relative_file(self.root, "nested/safe.txt"), safe)

        with self.assertRaises(ProjectPathViolation):
            _resolve_relative_file(self.root, "../outside.txt")
        with self.assertRaises(ProjectPathViolation):
            _resolve_relative_file(self.root, str(safe))

        outside = self.base / "outside.sqlite"
        create_sqlite(outside)
        link = self.root / "linked.sqlite"
        link_created = False
        try:
            link.symlink_to(outside)
            link_created = True
        except OSError:
            pass

        if link_created:
            with self.assertRaises(ProjectPathViolation):
                _resolve_relative_file(self.root, "linked.sqlite")
        payload = inspect_project_stack(self.project)
        self.assertEqual(payload["databases"], [])
        self.assertNotIn(str(outside), json.dumps(payload))

    def test_malformed_and_oversized_inputs_degrade_without_content_leaks(self) -> None:
        self.write("package.json", "{" + SENTINEL)
        self.write("compose.yml", "services:\n  web:\n    environment:\n      TOKEN: " + SENTINEL)
        invalid_database = self.root / "invalid.db"
        invalid_database.write_bytes(b"not sqlite " + SENTINEL.encode("utf-8"))

        with patch.object(project_stack, "MAX_COMPOSE_BYTES", 8):
            payload = inspect_project_stack(self.project)

        serialized = json.dumps(payload)
        self.assertNotIn(SENTINEL, serialized)
        self.assertEqual(payload["manifests"][0]["status"], "invalid")
        self.assertEqual(payload["manifests"][0]["reason"], "parse_error")
        self.assertEqual(payload["docker"]["compose_files"][0]["status"], "skipped")
        self.assertEqual(payload["docker"]["compose_files"][0]["reason"], "size_limit")
        self.assertEqual(payload["databases"][0]["status"], "invalid")
        self.assertEqual(payload["databases"][0]["reason"], "not_sqlite")


class ProjectStackHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_handler_uses_threads_and_sets_no_store(self) -> None:
        project = {"id": 4, "name": "Threaded", "path": "unused"}
        expected = {"project": {"id": 4, "name": "Threaded"}}
        request = SimpleNamespace(match_info={"id": "4"})

        def run_inline(function, *args):
            return function(*args)

        with (
            patch.object(project_stack_handlers.db, "get_project", return_value=project),
            patch.object(project_stack_handlers, "inspect_project_stack", return_value=expected),
            patch.object(
                project_stack_handlers.asyncio,
                "to_thread",
                new=AsyncMock(side_effect=run_inline),
            ) as to_thread,
        ):
            response = await project_stack_handlers.handle_project_stack(request)

        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.text), expected)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(to_thread.await_count, 2)

    async def test_handler_returns_bounded_error_contracts_without_exception_text(self) -> None:
        invalid = await project_stack_handlers.handle_project_stack(
            SimpleNamespace(match_info={"id": "../4"})
        )
        self.assertEqual(invalid.status, 400)
        self.assertEqual(json.loads(invalid.text)["code"], "INVALID_PROJECT_ID")

        with patch.object(project_stack_handlers.db, "get_project", return_value=None):
            missing = await project_stack_handlers.handle_project_stack(
                SimpleNamespace(match_info={"id": "404"})
            )
        self.assertEqual(missing.status, 404)
        self.assertEqual(json.loads(missing.text)["code"], "PROJECT_NOT_FOUND")

        with patch.object(
            project_stack_handlers.db,
            "get_project",
            side_effect=RuntimeError(SENTINEL),
        ):
            database_failure = await project_stack_handlers.handle_project_stack(
                SimpleNamespace(match_info={"id": "5"})
            )
        self.assertEqual(database_failure.status, 500)
        self.assertEqual(
            json.loads(database_failure.text)["code"],
            "STACK_INSPECTION_FAILED",
        )
        self.assertNotIn(SENTINEL, database_failure.text)

        missing_project = {
            "id": 9,
            "name": "Missing",
            "path": str(Path(tempfile.gettempdir()) / "missing-stack-project"),
        }
        with patch.object(
            project_stack_handlers.db,
            "get_project",
            return_value=missing_project,
        ):
            unavailable = await project_stack_handlers.handle_project_stack(
                SimpleNamespace(match_info={"id": "9"})
            )
        self.assertEqual(unavailable.status, 409)
        self.assertEqual(json.loads(unavailable.text)["code"], "PROJECT_PATH_UNAVAILABLE")
        self.assertNotIn(missing_project["path"], unavailable.text)

        with (
            patch.object(
                project_stack_handlers.db,
                "get_project",
                return_value={"id": 10, "name": "Broken", "path": "unused"},
            ),
            patch.object(
                project_stack_handlers,
                "inspect_project_stack",
                side_effect=RuntimeError(SENTINEL),
            ),
        ):
            failed = await project_stack_handlers.handle_project_stack(
                SimpleNamespace(match_info={"id": "10"})
            )
        self.assertEqual(failed.status, 500)
        self.assertEqual(json.loads(failed.text)["code"], "STACK_INSPECTION_FAILED")
        self.assertNotIn(SENTINEL, failed.text)
        for response in (invalid, missing, database_failure, unavailable, failed):
            self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_proxy_registers_stack_route_before_catch_all(self) -> None:
        app = create_app()
        resources = list(app.router.resources())
        canonicals = [resource.canonical for resource in resources]
        self.assertIn("/api/projects/{id}/stack", canonicals)
        stack_index = canonicals.index("/api/projects/{id}/stack")
        catch_all_index = next(
            index
            for index, canonical in enumerate(canonicals)
            if canonical in {"/{path}", "/{path:.*}"} or "path" in canonical and index > stack_index
        )
        self.assertLess(stack_index, catch_all_index)
        methods = {
            route.method
            for route in resources[stack_index]
        }
        self.assertEqual(methods, {"GET", "HEAD"})


if __name__ == "__main__":
    unittest.main()
