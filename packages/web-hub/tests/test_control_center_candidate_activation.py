"""Regression tests for transactional candidate activation gates."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.control_center import ControlCenterError, ControlCenterStore
from src.control_center_handlers import handle_activate_candidate
from src.database import Database
from tests.control_center_plan_fixtures import prepare_plan_for_approval


SHA = "a" * 40


class CandidateActivationFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ag_candidate_activation_")
        self.database = Database(Path(self.temp.name) / "control.db")
        self.project_id = self.database.add_project(
            "Candidate Activation Test",
            self.temp.name,
        )
        self.store = ControlCenterStore(
            self.database,
            sha_resolver=lambda _project: SHA,
        )

    def tearDown(self):
        self.temp.cleanup()

    def campaign(self):
        return self.store.create_campaign(
            {
                "project_id": self.project_id,
                "title": "Transactional candidate activation",
                "goal": "Activate candidates only after dependencies and waves are complete.",
                "non_goals": "No automatic merge.",
                "planning_depth": "compact",
                "max_candidates": 5,
            }
        )

    def candidate(self, campaign_id, title, **overrides):
        payload = {
            "title": title,
            "scope": f"Implement the isolated scope for {title}.",
            "acceptance_criteria": [f"{title} is verified."],
        }
        payload.update(overrides)
        return self.store.create_pr_candidate(campaign_id, payload)

    def approve(self, campaign_id):
        readiness = prepare_plan_for_approval(self.store, campaign_id)
        with self.database._get_connection() as conn:
            version = int(
                conn.execute(
                    "SELECT version FROM control_campaigns WHERE id = ?",
                    (campaign_id,),
                ).fetchone()["version"]
            )
        return self.store.approve_campaign(
            campaign_id,
            expected_version=version,
            approval_sha=SHA,
            expected_plan_signature=readiness["plan_signature"],
            actor="owner",
        )

    def candidate_status(self, candidate_id):
        with self.database._get_connection() as conn:
            return str(
                conn.execute(
                    "SELECT status FROM control_pr_candidates WHERE id = ?",
                    (candidate_id,),
                ).fetchone()["status"]
            )

    def mark_merged(self, candidate_id):
        with self.database._get_connection() as conn:
            conn.execute(
                """UPDATE control_pr_candidates
                   SET status = 'merged', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (candidate_id,),
            )
            conn.commit()

    def assert_not_activated(self, candidate_id):
        with self.database._get_connection() as conn:
            work_orders = int(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM control_work_orders WHERE candidate_id = ?",
                    (candidate_id,),
                ).fetchone()["count"]
            )
            tasks = int(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM control_agent_tasks WHERE candidate_id = ?",
                    (candidate_id,),
                ).fetchone()["count"]
            )
        self.assertEqual(work_orders, 0)
        self.assertEqual(tasks, 0)
        self.assertEqual(self.candidate_status(candidate_id), "ready")


class TestTransactionalCandidateActivation(
    CandidateActivationFixture,
    unittest.TestCase,
):
    def test_dependency_must_finish_before_candidate_activation(self):
        campaign = self.campaign()
        dependency = self.candidate(campaign["id"], "Foundation")
        candidate = self.candidate(
            campaign["id"],
            "Dependent slice",
            depends_on=[dependency["id"]],
        )
        self.approve(campaign["id"])

        with self.assertRaises(ControlCenterError) as context:
            self.store.activate_candidate(
                candidate["id"],
                approval_sha=SHA,
                actor="owner",
            )

        self.assertEqual(context.exception.code, "candidate_dependencies_pending")
        self.assertIn(dependency["id"], str(context.exception))
        self.assertIn("ready", str(context.exception))
        self.assert_not_activated(candidate["id"])

        self.mark_merged(dependency["id"])
        work_order = self.store.activate_candidate(
            candidate["id"],
            approval_sha=SHA,
            actor="owner",
        )
        self.assertEqual(work_order["candidate_id"], candidate["id"])

    def test_later_wave_waits_for_every_earlier_wave(self):
        campaign = self.campaign()
        first = self.candidate(campaign["id"], "First wave")
        later = self.candidate(campaign["id"], "Later wave")
        self.store.set_candidate_conflicts(
            campaign["id"],
            first["id"],
            [
                {
                    "candidate_id": later["id"],
                    "reason": "Both slices change the same runtime resource.",
                    "resources": ["src/runtime.py"],
                }
            ],
        )
        simulation = self.store.simulate_campaign(campaign["id"])
        waves = {
            candidate_id: item["wave"]
            for item in simulation["waves"]
            for candidate_id in item["candidate_ids"]
        }
        earlier_id = min(waves, key=waves.get)
        later_id = max(waves, key=waves.get)
        self.assertGreater(waves[later_id], waves[earlier_id])
        self.approve(campaign["id"])

        with self.assertRaises(ControlCenterError) as context:
            self.store.activate_candidate(
                later_id,
                approval_sha=SHA,
                actor="owner",
            )

        self.assertEqual(context.exception.code, "candidate_wave_blocked")
        self.assertIn(f"Wave {waves[later_id]}", str(context.exception))
        self.assertIn(earlier_id, str(context.exception))
        self.assert_not_activated(later_id)

        self.mark_merged(earlier_id)
        work_order = self.store.activate_candidate(
            later_id,
            approval_sha=SHA,
            actor="owner",
        )
        self.assertEqual(work_order["candidate_id"], later_id)


class TestAutomaticWaveActivation(
    CandidateActivationFixture,
    unittest.TestCase,
):
    def setUp(self):
        super().setUp()
        self.store.update_policy(
            mode="campaign",
            paused=False,
            reason="Exercise automatic wave activation.",
            actor="test",
        )

    def wave_campaign(self):
        return self.store.create_campaign(
            {
                "project_id": self.project_id,
                "title": "Automatic wave activation",
                "goal": "Activate only the earliest unfinished campaign wave.",
                "non_goals": "No automatic merge.",
                "planning_depth": "compact",
                "max_candidates": 5,
                "activation_policy": "campaign_wave",
            }
        )

    def test_wave_activation_requires_human_approved_campaign_and_policy(self):
        unapproved = self.wave_campaign()
        self.candidate(unapproved["id"], "Unapproved slice")
        self.store.simulate_campaign(unapproved["id"])

        with self.assertRaises(ControlCenterError) as unapproved_error:
            self.store.activate_ready_wave(unapproved["id"])
        self.assertEqual(
            unapproved_error.exception.code,
            "campaign_not_approved",
        )

        wrong_policy = self.store.create_campaign(
            {
                "project_id": self.project_id,
                "title": "Manual activation policy",
                "goal": "Keep candidate approval manual.",
                "non_goals": "No campaign-wave delegation.",
                "planning_depth": "compact",
                "max_candidates": 2,
                "activation_policy": "per_candidate",
            }
        )
        self.candidate(wrong_policy["id"], "Manual slice")
        self.store.simulate_campaign(wrong_policy["id"])
        self.approve(wrong_policy["id"])

        with self.assertRaises(ControlCenterError) as policy_error:
            self.store.activate_ready_wave(wrong_policy["id"])
        self.assertEqual(
            policy_error.exception.code,
            "wave_activation_not_allowed",
        )

        self.store.update_policy(
            mode="guided",
            paused=False,
            reason="Verify that guided mode cannot delegate a campaign wave.",
            actor="test",
        )
        with self.assertRaises(ControlCenterError) as mode_error:
            self.store.activate_ready_wave(wrong_policy["id"])
        self.assertEqual(mode_error.exception.code, "campaign_mode_required")

    def wave_candidates(self, campaign_id):
        foundation = self.candidate(campaign_id, "Foundation")
        peer = self.candidate(campaign_id, "Independent peer")
        successor = self.candidate(
            campaign_id,
            "Foundation successor",
            depends_on=[foundation["id"]],
        )
        simulation = self.store.simulate_campaign(campaign_id)
        waves = {
            candidate_id: item["wave"]
            for item in simulation["waves"]
            for candidate_id in item["candidate_ids"]
        }
        self.assertEqual(waves[foundation["id"]], waves[peer["id"]])
        self.assertGreater(waves[successor["id"]], waves[peer["id"]])
        return foundation, peer, successor

    def finish(self, activation):
        with self.database._get_connection() as conn:
            conn.execute(
                """UPDATE control_agent_tasks
                   SET status = 'completed', finished_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (activation["task_id"],),
            )
            conn.execute(
                """UPDATE control_pr_candidates
                   SET status = 'merged', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (activation["candidate_id"],),
            )
            conn.commit()

    def test_later_wave_waits_until_every_earlier_candidate_is_terminal(self):
        campaign = self.wave_campaign()
        foundation, peer, successor = self.wave_candidates(campaign["id"])
        self.approve(campaign["id"])

        first = self.store.activate_ready_wave(campaign["id"])
        self.assertEqual(
            {item["candidate_id"] for item in first["activated"]},
            {foundation["id"], peer["id"]},
        )
        open_approvals = {
            item["entity_id"]
            for item in self.store.overview(self.project_id)["attention"]
            if item["category"] == "work_order_approval"
        }
        self.assertNotIn(foundation["id"], open_approvals)
        self.assertNotIn(peer["id"], open_approvals)
        self.assertIn(successor["id"], open_approvals)
        foundation_activation = next(
            item
            for item in first["activated"]
            if item["candidate_id"] == foundation["id"]
        )
        peer_activation = next(
            item
            for item in first["activated"]
            if item["candidate_id"] == peer["id"]
        )
        self.finish(foundation_activation)

        with self.database._get_connection() as conn:
            audit_before = int(conn.execute(
                """SELECT COUNT(*) AS count FROM control_audit_events
                   WHERE entity_id = ? AND action = 'campaign.wave_activated'""",
                (campaign["id"],),
            ).fetchone()["count"])
        for _ in range(3):
            blocked = self.store.activate_ready_wave(campaign["id"])
            self.assertEqual(blocked["activated"], [])
        with self.database._get_connection() as conn:
            audit_after = int(conn.execute(
                """SELECT COUNT(*) AS count FROM control_audit_events
                   WHERE entity_id = ? AND action = 'campaign.wave_activated'""",
                (campaign["id"],),
            ).fetchone()["count"])
        self.assertEqual(audit_after, audit_before)
        self.assert_not_activated(successor["id"])

        self.finish(peer_activation)
        released = self.store.activate_ready_wave(campaign["id"])
        self.assertEqual(
            [item["candidate_id"] for item in released["activated"]],
            [successor["id"]],
        )
        self.assertFalse(
            any(
                item["category"] == "work_order_approval"
                for item in self.store.overview(self.project_id)["attention"]
            )
        )

    def test_completed_campaign_is_reconciled_and_stale_attention_is_resolved(self):
        campaign = self.wave_campaign()
        candidate = self.candidate(campaign["id"], "Only wave")
        self.approve(campaign["id"])
        activation = self.store.activate_ready_wave(campaign["id"])["activated"][0]
        self.finish(activation)
        with self.database._get_connection() as conn:
            self.store._attention(
                conn,
                project_id=self.project_id,
                category="work_order_approval",
                entity_type="pr_candidate",
                entity_id=candidate["id"],
                title="Stale approval",
                consequence="Should be reconciled.",
                recommendation="Complete the campaign.",
                urgency="normal",
            )
            conn.commit()

        result = self.store.activate_ready_wave(campaign["id"])

        self.assertEqual(result["reason"], "campaign_completed")
        with self.database._get_connection() as conn:
            current = conn.execute(
                "SELECT status FROM control_campaigns WHERE id = ?",
                (campaign["id"],),
            ).fetchone()
            profile = conn.execute(
                "SELECT completed_at FROM control_campaign_profiles WHERE campaign_id = ?",
                (campaign["id"],),
            ).fetchone()
        self.assertEqual(current["status"], "completed")
        self.assertIsNotNone(profile["completed_at"])
        self.assertFalse(
            any(
                item["category"] == "work_order_approval"
                for item in self.store.overview(self.project_id)["attention"]
            )
        )

    def test_campaign_does_not_complete_while_a_candidate_is_open(self):
        campaign = self.wave_campaign()
        first = self.candidate(campaign["id"], "Finished slice")
        second = self.candidate(campaign["id"], "Open slice")
        self.approve(campaign["id"])
        self.mark_merged(first["id"])

        with self.database._get_connection() as conn:
            completed = self.store._complete_campaign_if_done(
                conn,
                campaign["id"],
                actor="test",
            )
            conn.commit()

        self.assertFalse(completed)
        with self.database._get_connection() as conn:
            current = conn.execute(
                "SELECT status FROM control_campaigns WHERE id = ?",
                (campaign["id"],),
            ).fetchone()
        self.assertEqual(current["status"], "approved")
        self.assertEqual(self.candidate_status(second["id"]), "ready")

    def test_paused_campaign_with_open_amendment_does_not_complete(self):
        campaign = self.wave_campaign()
        candidate = self.candidate(campaign["id"], "Terminal before amendment")
        self.approve(campaign["id"])
        self.mark_merged(candidate["id"])
        self.store.propose_plan_amendment(
            campaign["id"],
            {
                "reason": "Add a newly discovered follow-up slice before completion.",
                "impact": {"candidate_count": 1},
                "actor": "test",
            },
        )

        with self.database._get_connection() as conn:
            completed = self.store._complete_campaign_if_done(
                conn,
                campaign["id"],
                actor="test",
            )
            conn.commit()

        self.assertFalse(completed)
        with self.database._get_connection() as conn:
            current = conn.execute(
                "SELECT status FROM control_campaigns WHERE id = ?",
                (campaign["id"],),
            ).fetchone()
        self.assertEqual(current["status"], "paused")
        self.assertTrue(
            any(
                item["category"] == "plan_amendment"
                for item in self.store.overview(self.project_id)["attention"]
            )
        )

    def test_pinned_later_wave_cannot_bypass_capacity_limited_earlier_wave(self):
        policy = self.store.get_repository_policy(self.project_id)
        self.store.update_repository_policy(
            self.project_id,
            {**policy, "max_open_prs": 1},
            actor="test",
        )
        campaign = self.wave_campaign()
        foundation, peer, successor = self.wave_candidates(campaign["id"])
        with self.database._get_connection() as conn:
            conn.execute(
                """UPDATE control_candidate_contracts
                   SET pinned = 1 WHERE candidate_id = ?""",
                (successor["id"],),
            )
            conn.commit()
        self.approve(campaign["id"])

        first = self.store.activate_ready_wave(campaign["id"])
        self.assertEqual(len(first["activated"]), 1)
        self.assertEqual(first["activated"][0]["candidate_id"], foundation["id"])
        self.finish(first["activated"][0])

        second = self.store.activate_ready_wave(campaign["id"])
        self.assertEqual(
            [item["candidate_id"] for item in second["activated"]],
            [peer["id"]],
        )
        self.assert_not_activated(successor["id"])


class TestCandidateActivationAPI(
    CandidateActivationFixture,
    unittest.IsolatedAsyncioTestCase,
):
    async def asyncSetUp(self):
        self.patch = patch(
            "src.control_center_handlers.control_center",
            self.store,
        )
        self.patch.start()
        app = web.Application()
        app.router.add_post(
            "/api/control-center/pr-candidates/{candidate_id}/activate",
            handle_activate_candidate,
        )
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.patch.stop()

    async def test_api_returns_precise_dependency_conflict_without_mutation(self):
        campaign = self.campaign()
        dependency = self.candidate(campaign["id"], "API foundation")
        candidate = self.candidate(
            campaign["id"],
            "API dependent",
            depends_on=[dependency["id"]],
        )
        self.approve(campaign["id"])

        response = await self.client.post(
            f"/api/control-center/pr-candidates/{candidate['id']}/activate",
            json={
                "approval_sha": SHA,
                "actor": "owner",
                "rationale": "E2E activation",
            },
        )
        payload = await response.json()

        self.assertEqual(response.status, 409)
        self.assertEqual(payload["code"], "candidate_dependencies_pending")
        self.assertIn(dependency["id"], payload["error"])
        self.assert_not_activated(candidate["id"])
