"""Audit-safe withdrawal tests for unstarted Control Center work orders."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.control_center import ControlCenterError, ControlCenterStore
from src.control_center_handlers import handle_cancel_work_order
from src.database import Database
from src.proxy_server import create_app
from tests.control_center_plan_fixtures import prepare_plan_for_approval


SHA = "a" * 40
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WorkOrderCancelFixture:
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory(prefix="ag_work_order_cancel_")
        self.database = Database(Path(self.temp.name) / "control.db")
        self.project_id = self.database.add_project("Cancel Test", self.temp.name)
        self.store = ControlCenterStore(
            self.database,
            sha_resolver=lambda _project: SHA,
        )

    def tearDown(self):
        self.temp.cleanup()
        super().tearDown()

    def create_approved_candidate(self, *, with_dependency=False):
        campaign = self.store.create_campaign(
            {
                "project_id": self.project_id,
                "title": "Auditable cancellation",
                "goal": "Withdraw accidental work orders before execution.",
                "non_goals": "No running task cancellation.",
                "risk_level": "medium",
            }
        )
        dependency = None
        if with_dependency:
            dependency = self.store.create_pr_candidate(
                campaign["id"],
                {
                    "title": "Foundation",
                    "scope": "Provide the prerequisite.",
                    "acceptance_criteria": ["Foundation is complete."],
                },
            )
        candidate = self.store.create_pr_candidate(
            campaign["id"],
            {
                "title": "Dependent slice" if dependency else "Independent slice",
                "scope": "Exercise the cancellation state machine.",
                "acceptance_criteria": ["The state transition is audited."],
                "depends_on": [dependency["id"]] if dependency else [],
            },
        )
        overview = self.store.overview(self.project_id)
        stored_campaign = next(
            item for item in overview["campaigns"] if item["id"] == campaign["id"]
        )
        readiness = prepare_plan_for_approval(self.store, campaign["id"])
        self.store.approve_campaign(
            campaign["id"],
            expected_version=stored_campaign["version"],
            approval_sha=SHA,
            expected_plan_signature=readiness["plan_signature"],
            actor="owner",
            reason="Plan reviewed.",
        )
        if dependency:
            with self.database._get_connection() as conn:
                conn.execute(
                    """UPDATE control_pr_candidates
                       SET status = 'completed' WHERE id = ?""",
                    (dependency["id"],),
                )
                conn.commit()
        return campaign, candidate, dependency


class TestWorkOrderCancel(WorkOrderCancelFixture, unittest.TestCase):
    def test_unstarted_work_order_is_withdrawn_and_can_be_reapproved(self):
        _campaign, candidate, dependency = self.create_approved_candidate(
            with_dependency=True
        )
        work_order = self.store.activate_candidate(
            candidate["id"],
            approval_sha=SHA,
            actor="owner",
            rationale="Accidentally approved.",
        )
        task = self.store.list_tasks(project_id=self.project_id)[0]

        result = self.store.cancel_unstarted_work_order(
            work_order["id"],
            actor="owner",
            reason="Wrong PR slice selected.",
        )

        self.assertFalse(result["idempotent"])
        self.assertEqual(result["work_order"]["status"], "cancelled")
        self.assertEqual(result["task"]["status"], "cancelled")
        self.assertEqual(result["task"]["attempt"], 0)
        with self.database._get_connection() as conn:
            stored_candidate = conn.execute(
                "SELECT status FROM control_pr_candidates WHERE id = ?",
                (candidate["id"],),
            ).fetchone()
            stored_dependency = conn.execute(
                """SELECT depends_on_id FROM control_pr_dependencies
                   WHERE candidate_id = ?""",
                (candidate["id"],),
            ).fetchone()
            pack = conn.execute(
                """SELECT status, summary FROM control_evidence_packs
                   WHERE task_id = ?""",
                (task["id"],),
            ).fetchone()
        self.assertEqual(stored_candidate["status"], "ready")
        self.assertEqual(stored_dependency["depends_on_id"], dependency["id"])
        self.assertEqual(pack["status"], "cancelled")
        self.assertTrue(pack["summary"])

        replay = self.store.cancel_unstarted_work_order(
            work_order["id"],
            actor="owner",
            reason="Retry after a network timeout.",
        )
        self.assertTrue(replay["idempotent"])

        overview = self.store.overview(self.project_id)
        self.assertEqual(overview["summary"]["work_orders_approved"], 0)
        self.assertTrue(
            any(
                item["entity_id"] == candidate["id"]
                and item["category"] == "work_order_approval"
                for item in overview["attention"]
            )
        )
        actions = [item["action"] for item in overview["audit"]]
        self.assertIn("work_order.cancelled", actions)
        self.assertIn("agent_task.cancelled", actions)

        reapproved = self.store.activate_candidate(
            candidate["id"],
            approval_sha=SHA,
            actor="owner",
            rationale="Dependencies and SHA reviewed again.",
        )
        self.assertEqual(reapproved["id"], work_order["id"])
        self.assertEqual(reapproved["status"], "approved")
        requeued = self.store.get_task(task["id"])
        self.assertEqual(requeued["status"], "queued")
        self.assertIsNone(requeued["finished_at"])
        overview = self.store.overview(self.project_id)
        self.assertEqual(overview["summary"]["work_orders_approved"], 1)
        actions = [item["action"] for item in overview["audit"]]
        self.assertIn("work_order.reapproved", actions)
        self.assertIn("agent_task.requeued", actions)

    def test_leased_work_order_cannot_be_withdrawn(self):
        _campaign, candidate, _dependency = self.create_approved_candidate()
        work_order = self.store.activate_candidate(
            candidate["id"],
            approval_sha=SHA,
            actor="owner",
        )
        leased = self.store.lease_next_task("test-worker")
        self.assertIsNotNone(leased)

        with self.assertRaises(ControlCenterError) as context:
            self.store.cancel_unstarted_work_order(
                work_order["id"],
                actor="owner",
                reason="Too late.",
            )

        self.assertEqual(context.exception.code, "work_order_already_started")
        with self.database._get_connection() as conn:
            states = conn.execute(
                """SELECT wo.status AS work_order_status,
                          pc.status AS candidate_status
                   FROM control_work_orders wo
                   JOIN control_pr_candidates pc ON pc.id = wo.candidate_id
                   WHERE wo.id = ?""",
                (work_order["id"],),
            ).fetchone()
        self.assertEqual(states["work_order_status"], "approved")
        self.assertEqual(states["candidate_status"], "approved")


class TestWorkOrderCancelAPI(WorkOrderCancelFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.control_patch = patch(
            "src.control_center_handlers.control_center",
            self.store,
        )
        self.control_patch.start()
        app = web.Application()
        app.router.add_post(
            "/api/control-center/work-orders/{work_order_id}/cancel",
            handle_cancel_work_order,
        )
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.control_patch.stop()

    async def test_cancel_endpoint_requires_reason_and_is_idempotent(self):
        _campaign, candidate, _dependency = self.create_approved_candidate()
        work_order = self.store.activate_candidate(
            candidate["id"],
            approval_sha=SHA,
            actor="owner",
        )

        missing_reason = await self.client.post(
            f"/api/control-center/work-orders/{work_order['id']}/cancel",
            json={"reason": ""},
        )
        self.assertEqual(missing_reason.status, 400)
        self.assertEqual((await missing_reason.json())["code"], "missing_reason")

        headers = {"Idempotency-Key": "cancel-unstarted-work-order"}
        response = await self.client.post(
            f"/api/control-center/work-orders/{work_order['id']}/cancel",
            json={"reason": "Wrong slice selected."},
            headers=headers,
        )
        self.assertEqual(response.status, 200, await response.text())
        payload = await response.json()
        self.assertEqual(
            payload["cancellation"]["work_order"]["status"],
            "cancelled",
        )

        replay = await self.client.post(
            f"/api/control-center/work-orders/{work_order['id']}/cancel",
            json={"reason": "Wrong slice selected."},
            headers=headers,
        )
        self.assertEqual(replay.status, 200, await replay.text())
        self.assertTrue((await replay.json())["idempotent_replay"])


class TestWorkOrderCancelIntegration(unittest.TestCase):
    def test_route_and_dashboard_action_are_registered(self):
        paths = {resource.canonical for resource in create_app().router.resources()}
        self.assertIn(
            "/api/control-center/work-orders/{work_order_id}/cancel",
            paths,
        )
        script = (
            PROJECT_ROOT / "dashboard" / "js" / "control-center.js"
        ).read_text(encoding="utf-8")
        self.assertIn("async function cancelUnstartedWorkOrder", script)
        self.assertIn("Vor Ausführung zurückgenommen", script)


if __name__ == "__main__":
    unittest.main()
