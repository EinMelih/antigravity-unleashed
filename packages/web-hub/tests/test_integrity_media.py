import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.project_handlers import handle_get_integrity_media


class TestIntegrityMediaBoundary(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ag_media_boundary_")
        self.home = Path(self.temp.name).resolve()
        self.brain = self.home / ".gemini" / "antigravity" / "brain"
        self.sibling = self.home / ".gemini" / "antigravity" / "brain-evil"
        self.brain.mkdir(parents=True)
        self.sibling.mkdir(parents=True)
        self.allowed_file = self.brain / "allowed.png"
        self.sibling_file = self.sibling / "private.png"
        self.allowed_file.write_bytes(b"allowed")
        self.sibling_file.write_bytes(b"private")

        app = web.Application()
        app.router.add_get("/api/antigravity/media", handle_get_integrity_media)
        self.client = TestClient(TestServer(app))
        self.home_patch = patch(
            "src.project_handlers.Path.home",
            return_value=self.home,
        )
        self.home_patch.start()
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        self.home_patch.stop()
        self.temp.cleanup()

    async def test_media_is_served_only_from_the_resolved_brain_directory(self) -> None:
        allowed = await self.client.get(
            "/api/antigravity/media",
            params={"path": str(self.allowed_file)},
        )
        sibling = await self.client.get(
            "/api/antigravity/media",
            params={"path": str(self.sibling_file)},
        )

        self.assertEqual(allowed.status, 200)
        self.assertEqual(await allowed.read(), b"allowed")
        self.assertEqual(sibling.status, 403)


if __name__ == "__main__":
    unittest.main()
