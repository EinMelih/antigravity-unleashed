"""Public HTTP behavior for the allowlisted documentation library."""

from __future__ import annotations

import unittest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.control_plane_handlers import CONTROL_DOC_PATHS, handle_control_plane_docs


class TestControlPlaneDocumentation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        app = web.Application()
        app.router.add_get(
            "/api/control-plane/docs/{document_id}",
            handle_control_plane_docs,
        )
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()

    async def test_serves_an_allowlisted_document(self) -> None:
        response = await self.client.get("/api/control-plane/docs/api")

        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "text/markdown")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("# API reference", await response.text())

    async def test_every_allowlisted_document_exists(self) -> None:
        for document_id, document_path in CONTROL_DOC_PATHS.items():
            with self.subTest(document_id=document_id):
                self.assertTrue(document_path.is_file(), document_path)

    async def test_serves_the_dependency_documentation(self) -> None:
        response = await self.client.get(
            "/api/control-plane/docs/dependencies"
        )

        self.assertEqual(response.status, 200)
        self.assertIn(
            "# Dependencies and runtime baseline",
            await response.text(),
        )

    async def test_serves_the_generated_frontend_import_graph(self) -> None:
        response = await self.client.get(
            "/api/control-plane/docs/frontend-imports"
        )

        self.assertEqual(response.status, 200)
        self.assertIn("# Frontend Import Graph", await response.text())

    async def test_serves_the_knowledge_chain_guide(self) -> None:
        response = await self.client.get(
            "/api/control-plane/docs/knowledge-chain"
        )

        self.assertEqual(response.status, 200)
        self.assertIn("# Knowledge Chain", await response.text())

    async def test_serves_the_plan_amendment_guide(self) -> None:
        response = await self.client.get(
            "/api/control-plane/docs/plan-amendments"
        )

        self.assertEqual(response.status, 200)
        self.assertIn("# Focused Re-Grilling and Plan Amendments", await response.text())

    async def test_serves_the_configuration_guide(self) -> None:
        response = await self.client.get(
            "/api/control-plane/docs/configuration"
        )

        self.assertEqual(response.status, 200)
        self.assertIn("# Configuration", await response.text())

    async def test_rejects_unknown_document_ids(self) -> None:
        response = await self.client.get(
            "/api/control-plane/docs/not-allowlisted"
        )

        self.assertEqual(response.status, 404)
        self.assertEqual(
            await response.json(),
            {"error": "Documentation was not found."},
        )
