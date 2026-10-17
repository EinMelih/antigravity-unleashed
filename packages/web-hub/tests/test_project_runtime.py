import asyncio
import json
import socket
import tempfile
import unittest
from pathlib import Path

from src.project_runtime import ProjectRuntimeManager, detect_project_runtime


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


class ProjectRuntimeDetectionTests(unittest.TestCase):
    def test_detects_vite_frontend_and_fastapi_backend(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "package.json").write_text(
                json.dumps({
                    "scripts": {"dev": "vite"},
                    "devDependencies": {"vite": "latest"},
                }),
                encoding="utf-8",
            )
            (root / "main.py").write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n",
                encoding="utf-8",
            )
            profile = detect_project_runtime(root, 7)
            self.assertIn("npm run dev", profile["services"]["frontend"]["command"])
            self.assertIn("uvicorn main:app", profile["services"]["backend"]["command"])
            self.assertNotIn(
                profile["services"]["backend"]["port"],
                {8000, 8001, 8002, 8007, 8010},
            )

    def test_detects_frontend_subdirectory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            frontend = root / "frontend"
            frontend.mkdir()
            (frontend / "package.json").write_text(
                json.dumps({"scripts": {"dev": "vite"}}),
                encoding="utf-8",
            )
            profile = detect_project_runtime(root, 8)
            self.assertEqual(profile["services"]["frontend"]["cwd"], "frontend")
            self.assertIn("npm run dev", profile["services"]["frontend"]["command"])

    def test_separates_root_fastify_backend_from_nested_vite_frontend(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "package.json").write_text(
                json.dumps({
                    "main": "dist/server/index.js",
                    "scripts": {"dev": "bun run src/server/index.ts"},
                    "dependencies": {"fastify": "latest"},
                }),
                encoding="utf-8",
            )
            web = root / "web"
            web.mkdir()
            (web / "package.json").write_text(
                json.dumps({
                    "scripts": {"dev": "vite"},
                    "dependencies": {"react": "latest"},
                    "devDependencies": {"vite": "latest"},
                }),
                encoding="utf-8",
            )
            profile = detect_project_runtime(root, 9)
            self.assertEqual(profile["services"]["frontend"]["cwd"], "web")
            self.assertIn("npm run dev", profile["services"]["frontend"]["command"])
            self.assertEqual(profile["services"]["backend"]["cwd"], ".")
            self.assertEqual(profile["services"]["backend"]["command"], "npm run dev")

    def test_rejects_unsafe_host_reserved_port_and_cwd_escape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manager = ProjectRuntimeManager(
                store_path=root / "profiles.json",
                runtime_root=root / "runtime",
            )
            base = {
                "enabled": True,
                "command": "python -m http.server {port} --bind {host}",
                "cwd": ".",
                "host": "127.0.0.1",
                "port": free_port(),
                "health_path": "/",
            }
            with self.assertRaisesRegex(ValueError, "loopback"):
                manager.validate_service(root, "frontend", {**base, "host": "0.0.0.0"})
            with self.assertRaisesRegex(ValueError, "reserved"):
                manager.validate_service(root, "frontend", {**base, "port": 8000})
            with self.assertRaisesRegex(ValueError, "inside"):
                manager.validate_service(root, "frontend", {**base, "cwd": ".."})


class ProjectRuntimeLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.manager = ProjectRuntimeManager(
            store_path=self.root / "profiles.json",
            runtime_root=self.root / "runtime",
        )
        self.project = {"id": 91, "path": str(self.root), "name": "Runtime Test"}

    async def asyncTearDown(self):
        for service in ("frontend", "backend"):
            try:
                await self.manager.stop(self.project, service)
            except Exception:
                pass
        self.temporary.cleanup()

    def profile(self, port: int):
        return {
            "services": {
                "frontend": {
                    "enabled": True,
                    "command": "python -m http.server {port} --bind {host}",
                    "cwd": ".",
                    "host": "127.0.0.1",
                    "port": port,
                    "health_path": "/",
                },
                "backend": {
                    "enabled": False,
                    "command": "",
                    "cwd": ".",
                    "host": "127.0.0.1",
                    "port": free_port(),
                    "health_path": "/health",
                },
            }
        }

    async def test_persists_starts_reuses_and_stops_managed_runtime(self):
        port = free_port()
        saved = self.manager.save_profile(self.project, self.profile(port))
        self.assertEqual(saved["services"]["frontend"]["port"], port)
        self.assertTrue((self.root / "profiles.json").is_file())

        started = await self.manager.start(self.project, "frontend")
        self.assertTrue(started["managed"])
        for _ in range(30):
            status = self.manager.service_status(self.project, "frontend")
            if status["status"] == "running":
                break
            await asyncio.sleep(0.1)
        self.assertEqual(status["status"], "running")

        reused = await self.manager.start(self.project, "frontend")
        self.assertTrue(reused["unchanged"])
        stopped = await self.manager.stop(self.project, "frontend")
        self.assertEqual(stopped["status"], "stopped")

    async def test_never_stops_an_external_port_owner(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        port = int(listener.getsockname()[1])
        try:
            self.manager.save_profile(self.project, self.profile(port))
            started = await self.manager.start(self.project, "frontend")
            self.assertEqual(started["status"], "external")
            self.assertFalse(started["managed"])
            stopped = await self.manager.stop(self.project, "frontend")
            self.assertEqual(stopped["status"], "external")
            self.assertIn("not stopped", stopped["message"])
            self.assertEqual(listener.getsockname()[1], port)
        finally:
            listener.close()

    async def test_requires_explicit_dependency_setup_before_npm_start(self):
        (self.root / "package.json").write_text(
            json.dumps({"scripts": {"dev": "vite"}, "devDependencies": {"vite": "latest"}}),
            encoding="utf-8",
        )
        (self.root / "package-lock.json").write_text("{}", encoding="utf-8")
        profile = self.profile(free_port())
        profile["services"]["frontend"]["command"] = "npm run dev"
        self.manager.save_profile(self.project, profile)
        setup = self.manager.service_status(self.project, "frontend")["setup"]
        self.assertTrue(setup["required"])
        self.assertEqual(setup["command"], "npm ci")
        self.assertEqual(
            setup["reason"],
            "Dependencies are not installed in the project root.",
        )
        with self.assertRaisesRegex(RuntimeError, "Dependencies are missing"):
            await self.manager.start(self.project, "frontend")


if __name__ == "__main__":
    unittest.main()
