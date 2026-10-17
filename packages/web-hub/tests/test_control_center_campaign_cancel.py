"""Audit-safe cancellation tests for unstarted Control Center campaigns."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.control_center import ControlCenterError, ControlCenterStore
from src.control_center_handlers import handle_cancel_campaign
from src.database import Database
from src.proxy_server import create_app
from tests.control_center_plan_fixtures import prepare_plan_for_approval


SHA = "a" * 40


class CampaignCancelFixture:
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory(prefix="ag_campaign_cancel_")
        self.database = Database(Path(self.temp.name) / "control.db")
        self.project_id = self.database.add_project("Campaign Cancel", self.temp.name)
        self.store = ControlCenterStore(self.database, sha_resolver=lambda _project: SHA)

    def tearDown(self):
        self.temp.cleanup()
        super().tearDown()

    def campaign_with_candidate(self):
        campaign = self.store.create_campaign(
            {
                "project_id": self.project_id,
                "title": "Disposable planning campaign",
                "goal": "Prove that an unstarted campaign can be cancelled safely.",
            }
        )
        candidate = self.store.create_pr_candidate(
            campaign["id"],
            {
                "title": "Unstarted slice",
                "scope": "Exercise the cancellation transaction.",
                "acceptance_criteria": ["History remains queryable."],
            },
        )
        return campaign, candidate

    def approve_and_activate(self):
        campaign, candidate = self.campaign_with_candidate()
        stored = next(
            item
            for item in self.store.overview(self.project_id)["campaigns"]
            if item["id"] == campaign["id"]
        )
        readiness = prepare_plan_for_approval(self.store, campaign["id"])
        self.store.approve_campaign(
            campaign["id"],
            expected_version=stored["version"],
            approval_sha=SHA,
            expected_plan_signature=readiness["plan_signature"],
            actor="owner",
        )
        work_order = self.store.activate_candidate(
            candidate["id"], approval_sha=SHA, actor="owner"
        )
        return campaign, candidate, work_order


class TestCampaignCancel(CampaignCancelFixture, unittest.TestCase):
    def test_draft_campaign_is_soft_cancelled_and_replay_is_idempotent(self):
        campaign, candidate = self.campaign_with_candidate()
        result = self.store.cancel_campaign(
            campaign["id"], actor="owner", reason="Test data is obsolete."
        )

        self.assertEqual(result["campaign"]["status"], "cancelled")
        self.assertFalse(result["idempotent"])
        with self.database._get_connection() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT status FROM control_pr_candidates WHERE id = ?",
                    (candidate["id"],),
                ).fetchone()["status"],
                "cancelled",
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM control_attention_items WHERE status = 'open' AND (entity_id = ? OR entity_id = ?)",
                    (campaign["id"], candidate["id"]),
                ).fetchone()["count"],
                0,
            )
            audit_before = conn.execute(
                "SELECT COUNT(*) AS count FROM control_audit_events WHERE action = 'campaign.cancelled' AND entity_id = ?",
                (campaign["id"],),
            ).fetchone()["count"]

        replay = self.store.cancel_campaign(campaign["id"], actor="owner")
        self.assertTrue(replay["idempotent"])
        with self.database._get_connection() as conn:
            audit_after = conn.execute(
                "SELECT COUNT(*) AS count FROM control_audit_events WHERE action = 'campaign.cancelled' AND entity_id = ?",
                (campaign["id"],),
            ).fetchone()["count"]
        self.assertEqual(audit_after, audit_before)

    def test_approved_campaign_cancels_only_queued_execution_rows(self):
        campaign, candidate, work_order = self.approve_and_activate()
        result = self.store.cancel_campaign(campaign["id"], actor="owner")
        self.assertEqual(result["cancelled"]["tasks"], 1)
        with self.database._get_connection() as conn:
            task = conn.execute(
                "SELECT id, status FROM control_agent_tasks WHERE campaign_id = ?",
                (campaign["id"],),
            ).fetchone()
            pack = conn.execute(
                "SELECT status FROM control_evidence_packs WHERE task_id = ?",
                (task["id"],),
            ).fetchone()
            self.assertEqual(task["status"], "cancelled")
            self.assertEqual(pack["status"], "cancelled")
            self.assertEqual(
                conn.execute(
                    "SELECT status FROM control_work_orders WHERE id = ?",
                    (work_order["id"],),
                ).fetchone()["status"],
                "cancelled",
            )
            self.assertEqual(
                conn.execute(
                    "SELECT status FROM control_pr_candidates WHERE id = ?",
                    (candidate["id"],),
                ).fetchone()["status"],
                "cancelled",
            )

    def test_started_task_returns_409_semantics_without_partial_changes(self):
        campaign, candidate, work_order = self.approve_and_activate()
        self.assertIsNotNone(self.store.lease_next_task("worker"))

        with self.assertRaises(ControlCenterError) as context:
            self.store.cancel_campaign(campaign["id"], actor="owner")
        self.assertEqual(context.exception.code, "campaign_already_started")
        self.assertEqual(context.exception.status, 409)
        with self.database._get_connection() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT status FROM control_campaigns WHERE id = ?",
                    (campaign["id"],),
                ).fetchone()["status"],
                "approved",
            )
            self.assertEqual(
                conn.execute(
                    "SELECT status FROM control_work_orders WHERE id = ?",
                    (work_order["id"],),
                ).fetchone()["status"],
                "approved",
            )
            self.assertEqual(
                conn.execute(
                    "SELECT status FROM control_pr_candidates WHERE id = ?",
                    (candidate["id"],),
                ).fetchone()["status"],
                "approved",
            )


class TestCampaignCancelAPI(CampaignCancelFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.patch = patch("src.control_center_handlers.control_center", self.store)
        self.patch.start()
        app = web.Application()
        app.router.add_post(
            "/api/control-center/campaigns/{campaign_id}/cancel",
            handle_cancel_campaign,
        )
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.patch.stop()

    async def test_endpoint_rejects_external_origin_before_mutation(self):
        campaign, _candidate = self.campaign_with_candidate()
        response = await self.client.post(
            f"/api/control-center/campaigns/{campaign['id']}/cancel",
            json={"reason": "Must not execute."},
            headers={"Origin": "https://attacker.example"},
        )
        self.assertEqual(response.status, 403)
        with self.database._get_connection() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT status FROM control_campaigns WHERE id = ?",
                    (campaign["id"],),
                ).fetchone()["status"],
                "draft",
            )

    async def test_endpoint_cancels_campaign(self):
        campaign, _candidate = self.campaign_with_candidate()
        response = await self.client.post(
            f"/api/control-center/campaigns/{campaign['id']}/cancel",
            json={"actor": "owner", "reason": "Obsolete test plan."},
            headers={"Origin": "http://127.0.0.1:8000"},
        )
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(
            (await response.json())["cancellation"]["campaign"]["status"],
            "cancelled",
        )


class TestCampaignCancelRoute(unittest.TestCase):
    def test_route_is_registered(self):
        paths = {resource.canonical for resource in create_app().router.resources()}
        self.assertIn(
            "/api/control-center/campaigns/{campaign_id}/cancel",
            paths,
        )


if __name__ == "__main__":
    unittest.main()
