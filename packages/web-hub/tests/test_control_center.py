"""Tests for the Stage-1 Engineering Control Center."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.control_center import ControlCenterError, ControlCenterStore
from src.control_center_handlers import (
    handle_activate_candidate,
    handle_approve_campaign,
    handle_control_overview,
    handle_control_policy,
    handle_create_campaign,
    handle_create_checkpoint,
    handle_create_pr_candidate,
    handle_create_recommendation,
    handle_recommendation_disposition,
)
from src.database import Database
from src.proxy_server import create_app
from tests.control_center_plan_fixtures import prepare_plan_for_approval


SHA_A = "a" * 40
SHA_B = "b" * 40
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestControlCenterStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="antigravity_control_")
        self.database = Database(Path(self.temp.name) / "control.db")
        self.project_id = self.database.add_project("Control Test", self.temp.name)
        self.sha = SHA_A
        self.store = ControlCenterStore(
            self.database,
            sha_resolver=lambda _project: self.sha,
        )

    def tearDown(self):
        self.temp.cleanup()

    def _recommendation(self):
        return self.store.create_recommendation({
            "project_id": self.project_id,
            "title": "Retries nachvollziehbar machen",
            "summary": "Identische Retries sollen als No-progress erkannt werden.",
            "evidence": "src/orchestrator.py und drei gleiche Fehlversuche",
            "risk_level": "medium",
        })

    def _campaign(self, recommendation_id=None):
        return self.store.create_campaign({
            "project_id": self.project_id,
            "recommendation_id": recommendation_id,
            "title": "Durable Retry Policy",
            "goal": "Wiederholte identische Fehler werden deterministisch pausiert.",
            "non_goals": "Keine automatische Produktionsfreigabe.",
            "risk_level": "high",
        })

    def _candidate(self, campaign_id, **overrides):
        payload = {
            "title": "Retry-Zähler persistieren",
            "scope": "Persistenten No-progress-Zähler und einen klaren Stop-Zustand ergänzen.",
            "acceptance_criteria": [
                "Drei identische Fehler pausieren die Work Order.",
                "Der Audit Trail enthält den Stop-Grund.",
            ],
            "risk_level": "medium",
            "priority": 10,
        }
        payload.update(overrides)
        return self.store.create_pr_candidate(campaign_id, payload)

    def test_recommendations_are_deduplicated_and_dispositioned(self):
        first = self._recommendation()
        duplicate = self._recommendation()
        self.assertEqual(first["id"], duplicate["id"])
        self.assertFalse(first["deduplicated"])
        self.assertTrue(duplicate["deduplicated"])

        accepted = self.store.disposition_recommendation(
            first["id"], disposition="accepted", reason="", actor="owner"
        )
        self.assertEqual(accepted["status"], "accepted")
        overview = self.store.overview(self.project_id)
        self.assertEqual(overview["summary"]["attention_open"], 1)
        self.assertEqual(overview["attention"][0]["category"], "campaign_planning")

        with self.assertRaises(ControlCenterError) as context:
            self.store.disposition_recommendation(
                first["id"], disposition="rejected", reason="changed", actor="owner"
            )
        self.assertEqual(context.exception.code, "invalid_state_transition")

    def test_campaign_work_order_flow_is_version_and_sha_bound(self):
        recommendation = self._recommendation()
        self.store.disposition_recommendation(
            recommendation["id"], disposition="accepted", reason="", actor="owner"
        )
        campaign = self._campaign(recommendation["id"])
        candidate = self._candidate(campaign["id"])
        overview = self.store.overview(self.project_id)
        stored_campaign = overview["campaigns"][0]
        self.assertEqual(stored_campaign["version"], 2)
        self.assertEqual(stored_campaign["base_sha"], SHA_A)
        readiness = prepare_plan_for_approval(self.store, campaign["id"])

        with self.assertRaises(ControlCenterError) as context:
            self.store.approve_campaign(
                campaign["id"], expected_version=1, approval_sha=SHA_A,
                expected_plan_signature=readiness["plan_signature"], actor="owner"
            )
        self.assertEqual(context.exception.code, "stale_plan_version")

        approved = self.store.approve_campaign(
            campaign["id"],
            expected_version=2,
            approval_sha=SHA_A,
            expected_plan_signature=readiness["plan_signature"],
            actor="owner",
            reason="Plan geprüft",
        )
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["approved_sha"], SHA_A)

        self.store.update_policy(mode="observer", paused=False, reason="", actor="owner")
        with self.assertRaises(ControlCenterError) as context:
            self.store.activate_candidate(candidate["id"], approval_sha=SHA_A, actor="owner")
        self.assertEqual(context.exception.code, "observer_mode")

        self.store.update_policy(mode="guided", paused=True, reason="Wartung", actor="owner")
        with self.assertRaises(ControlCenterError) as context:
            self.store.activate_candidate(candidate["id"], approval_sha=SHA_A, actor="owner")
        self.assertEqual(context.exception.code, "control_center_paused")

        self.store.update_policy(mode="guided", paused=False, reason="", actor="owner")
        work_order = self.store.activate_candidate(
            candidate["id"], approval_sha=SHA_A, actor="owner", rationale="Scope geprüft"
        )
        replay = self.store.activate_candidate(
            candidate["id"], approval_sha=SHA_A, actor="owner"
        )
        self.assertEqual(work_order["id"], replay["id"])
        self.assertEqual(work_order["approval_sha"], SHA_A)

        final = self.store.overview(self.project_id)
        self.assertEqual(final["summary"]["work_orders_approved"], 1)
        self.assertEqual(final["summary"]["attention_open"], 0)
        actions = {event["action"] for event in final["audit"]}
        self.assertIn("campaign.approved", actions)
        self.assertIn("work_order.approved", actions)

    def test_sha_drift_invalidates_campaign_approval(self):
        campaign = self._campaign()
        self._candidate(campaign["id"])
        readiness = prepare_plan_for_approval(self.store, campaign["id"])
        self.sha = SHA_B
        with self.assertRaises(ControlCenterError) as context:
            self.store.approve_campaign(
                campaign["id"], expected_version=2, approval_sha=SHA_A,
                expected_plan_signature=readiness["plan_signature"], actor="owner"
            )
        self.assertEqual(context.exception.code, "stale_base_sha")

    def test_candidate_dependencies_stay_inside_campaign(self):
        first_campaign = self._campaign()
        first = self._candidate(first_campaign["id"])
        second_campaign = self._campaign()
        with self.assertRaises(ControlCenterError) as context:
            self._candidate(
                second_campaign["id"],
                title="Ungültige Abhängigkeit",
                depends_on=[first["id"]],
            )
        self.assertEqual(context.exception.code, "invalid_dependency")

    def test_checkpoint_is_durable_and_audited(self):
        campaign = self._campaign()
        checkpoint = self.store.create_checkpoint({
            "project_id": self.project_id,
            "entity_type": "campaign",
            "entity_id": campaign["id"],
            "actor": "planner-agent",
            "summary": "Repository-Mapping abgeschlossen.",
            "payload": {"base_sha": SHA_A, "next_step": "PR-Slices definieren"},
        })
        self.assertEqual(checkpoint["payload"]["base_sha"], SHA_A)
        overview = self.store.overview(self.project_id)
        self.assertEqual(overview["checkpoints"][0]["id"], checkpoint["id"])
        self.assertEqual(overview["audit"][0]["action"], "checkpoint.created")


class TestControlCenterAPI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="antigravity_control_api_")
        self.database = Database(Path(self.temp.name) / "control-api.db")
        self.project_id = self.database.add_project("Control API Test", self.temp.name)
        self.store = ControlCenterStore(self.database, sha_resolver=lambda _project: SHA_A)
        self.patch = patch("src.control_center_handlers.control_center", self.store)
        self.patch.start()

        app = web.Application()
        app.router.add_get("/api/control-center/overview", handle_control_overview)
        app.router.add_post("/api/control-center/policy", handle_control_policy)
        app.router.add_post("/api/control-center/recommendations", handle_create_recommendation)
        app.router.add_post(
            "/api/control-center/recommendations/{recommendation_id}/disposition",
            handle_recommendation_disposition,
        )
        app.router.add_post("/api/control-center/campaigns", handle_create_campaign)
        app.router.add_post(
            "/api/control-center/campaigns/{campaign_id}/pr-candidates",
            handle_create_pr_candidate,
        )
        app.router.add_post(
            "/api/control-center/campaigns/{campaign_id}/approve", handle_approve_campaign
        )
        app.router.add_post(
            "/api/control-center/pr-candidates/{candidate_id}/activate", handle_activate_candidate
        )
        app.router.add_post("/api/control-center/checkpoints", handle_create_checkpoint)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.patch.stop()
        self.temp.cleanup()

    async def test_create_recommendation_is_idempotent(self):
        payload = {
            "project_id": self.project_id,
            "title": "Audit exportieren",
            "summary": "Die Timeline soll später als Evidence Pack exportierbar sein.",
        }
        headers = {"Idempotency-Key": "recommendation-test-key"}
        first_response = await self.client.post(
            "/api/control-center/recommendations", json=payload, headers=headers
        )
        self.assertEqual(first_response.status, 201, await first_response.text())
        first = await first_response.json()
        replay_response = await self.client.post(
            "/api/control-center/recommendations", json=payload, headers=headers
        )
        self.assertEqual(replay_response.status, 201, await replay_response.text())
        replay = await replay_response.json()
        self.assertEqual(first["recommendation"]["id"], replay["recommendation"]["id"])
        self.assertTrue(replay["idempotent_replay"])

        overview = await self.client.get(
            f"/api/control-center/overview?project_id={self.project_id}"
        )
        data = await overview.json()
        self.assertEqual(len(data["recommendations"]), 1)

    async def test_invalid_json_is_reported_without_server_error(self):
        response = await self.client.post(
            "/api/control-center/campaigns",
            data="not-json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json())["code"], "invalid_json")


class TestControlCenterIntegration(unittest.TestCase):
    def test_routes_and_dashboard_assets_are_registered(self):
        paths = {resource.canonical for resource in create_app().router.resources()}
        self.assertIn("/api/control-center/overview", paths)
        self.assertIn("/api/control-center/campaigns/{campaign_id}/approve", paths)
        self.assertIn("/api/control-center/pr-candidates/{candidate_id}/activate", paths)

        html = (PROJECT_ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
        script = (PROJECT_ROOT / "dashboard" / "js" / "control-center.js").read_text(encoding="utf-8")
        style = (PROJECT_ROOT / "dashboard" / "css" / "control-center.css").read_text(encoding="utf-8")
        self.assertIn('id="control-center-tab"', html)
        self.assertIn("js/control-center.js?v=20260727-14", html)
        self.assertIn('id="cc-deployment-list"', html)
        self.assertIn("/api/control-center/overview", script)
        self.assertIn("renderControlDeployments", script)
        self.assertIn("cc-dashboard-grid", style)


if __name__ == "__main__":
    unittest.main()
