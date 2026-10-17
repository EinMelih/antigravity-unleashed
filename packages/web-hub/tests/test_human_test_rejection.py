"""Regression coverage for SHA-bound negative human-test repair handoff."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.control_center import ControlCenterError, ControlCenterStore
from src.control_center_handlers import handle_task_approval
from src.database import Database
from tests.control_center_plan_fixtures import prepare_plan_for_approval


SHA = "b" * 40


def _ready_human_task(store: ControlCenterStore, project_id: int) -> dict:
    campaign = store.create_campaign(
        {
            "project_id": project_id,
            "title": "Negative human test repair",
            "goal": "Turn a reproducible failed human test into bounded repair work.",
            "non_goals": "No automatic merge.",
            "risk_level": "medium",
            "planning_depth": "compact",
            "max_candidates": 2,
            "rollback_plan": "Revert the repair commit.",
        }
    )
    candidate = store.create_pr_candidate(
        campaign["id"],
        {
            "title": "Repair the observed interaction",
            "scope": "Reproduce and repair the failed browser interaction.",
            "acceptance_criteria": ["The interaction matches the expected behavior."],
            "required_checks": ["unit"],
            "manual_tests": [],
            "definition_of_done": "The failed human scenario passes for the exact SHA.",
            "risk_level": "medium",
            "priority": 5,
        },
    )
    readiness = prepare_plan_for_approval(store, campaign["id"])
    campaign = store.approve_campaign(
        campaign["id"],
        expected_version=2,
        approval_sha="a" * 40,
        expected_plan_signature=readiness["plan_signature"],
        actor="owner",
    )
    store.activate_candidate(
        candidate["id"],
        approval_sha=campaign["approved_sha"],
        actor="owner",
    )
    task = store.list_tasks(campaign_id=campaign["id"])[0]
    store.set_task_revision(task["id"], sha=SHA)
    for criterion_key in ("acceptance:1", "check:unit", "manual:1"):
        store.add_evidence(
            task["id"],
            {
                "kind": "test",
                "criterion_key": criterion_key,
                "title": criterion_key,
                "status": "passed",
                "sha": SHA,
            },
        )
    pack = store.evaluate_evidence_pack(task["id"])
    if pack["status"] != "ready_for_human":
        raise AssertionError(pack)
    return store.get_task(task["id"])


def _reproduction(**overrides) -> dict:
    evidence = {
        "executed_steps": "1. Open the drawer\n2. Submit the form",
        "expected_behavior": "The saved state appears immediately.",
        "observed_behavior": "The drawer closes but the old state remains visible.",
        "environment": "Windows 11, Chromium 140, local Hub",
        "diagnosis": "The overview refresh may race the mutation response.",
        "artifact_ref": "artifacts/human-test/failed-state.png",
        "note": "Reproduced twice.",
    }
    evidence.update(overrides)
    return evidence


class TestNegativeHumanTestStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ag_human_reject_")
        self.database = Database(Path(self.temp.name) / "control.db")
        self.project_id = self.database.add_project("Human rejection", self.temp.name)
        self.store = ControlCenterStore(
            self.database,
            sha_resolver=lambda _project: "a" * 40,
        )
        self.task = _ready_human_task(self.store, self.project_id)

    def tearDown(self):
        self.temp.cleanup()

    def reject(self, evidence=None):
        return self.store.record_human_approval(
            self.task["id"],
            approval_type="human_test",
            sha=SHA,
            decision="rejected",
            actor="owner",
            reason="The verified interaction still fails.",
            evidence=_reproduction() if evidence is None else evidence,
        )

    def test_rejection_atomically_persists_reproduction_and_queues_repair(self):
        approval = self.reject()

        self.assertEqual(approval["decision"], "rejected")
        self.assertEqual(approval["evidence"]["environment"], _reproduction()["environment"])
        task = self.store.get_task(self.task["id"])
        self.assertEqual(task["status"], "repair")
        self.assertEqual(task["wake_reason"], "human_test_rejected")
        self.assertEqual(task["lease_owner"], "")
        pack = self.store.evidence_pack(self.task["id"])
        self.assertEqual(pack["status"], "rejected")
        reproduction = [
            item for item in pack["items"]
            if item["kind"] == "human_test"
            and item["criterion_key"] == "human_test:rejection"
        ]
        self.assertEqual(len(reproduction), 1)
        self.assertEqual(reproduction[0]["status"], "failed")
        self.assertEqual(reproduction[0]["sha"], SHA)
        self.assertEqual(
            reproduction[0]["payload"]["observed_behavior"],
            _reproduction()["observed_behavior"],
        )
        findings = [item for item in pack["findings"] if item["source"] == "human_test"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["classification"], "REQUIRED")
        self.assertEqual(findings[0]["status"], "open")
        self.assertEqual(findings[0]["sha"], SHA)
        self.assertEqual(
            findings[0]["external_id"],
            f"human-test:{self.task['id']}:{SHA}",
        )
        with self.database._get_connection() as conn:
            candidate = conn.execute(
                "SELECT status FROM control_pr_candidates WHERE id = ?",
                (self.task["candidate_id"],),
            ).fetchone()
            attention = conn.execute(
                """SELECT * FROM control_attention_items
                   WHERE entity_type = 'agent_task' AND entity_id = ?
                     AND category = 'human_test_repair' AND status = 'open'""",
                (self.task["id"],),
            ).fetchall()
            audit = conn.execute(
                """SELECT * FROM control_audit_events
                   WHERE entity_type = 'agent_task' AND entity_id = ?
                     AND action = 'human_test.rejected_for_repair'""",
                (self.task["id"],),
            ).fetchall()
        self.assertEqual(candidate["status"], "repair")
        self.assertEqual(len(attention), 1)
        self.assertEqual(len(audit), 1)

    def test_reproduction_fields_are_required_without_changing_task(self):
        evidence = _reproduction()
        evidence["observed_behavior"] = ""
        with self.assertRaises(ControlCenterError) as raised:
            self.reject(evidence)
        self.assertEqual(raised.exception.code, "human_test_reproduction_required")
        self.assertEqual(self.store.get_task(self.task["id"])["status"], "waiting_human")
        self.assertEqual(self.store.evidence_pack(self.task["id"])["approvals"], [])

    def test_repeated_rejection_reopens_one_finding_and_updates_one_evidence_item(self):
        first = self.reject()
        pack = self.store.evidence_pack(self.task["id"])
        finding = next(item for item in pack["findings"] if item["source"] == "human_test")
        reproduction = next(item for item in pack["items"] if item["kind"] == "human_test")
        with self.database._get_connection() as conn:
            conn.execute(
                "UPDATE control_findings SET status = 'resolved', resolution = 'temporary' WHERE id = ?",
                (finding["id"],),
            )
            conn.execute(
                "UPDATE control_evidence_packs SET status = 'ready_for_human' WHERE task_id = ?",
                (self.task["id"],),
            )
            conn.execute(
                "UPDATE control_agent_tasks SET status = 'waiting_human', wake_reason = 'human_test' WHERE id = ?",
                (self.task["id"],),
            )
            conn.execute(
                "UPDATE control_pr_candidates SET status = 'human_test' WHERE id = ?",
                (self.task["candidate_id"],),
            )
            conn.commit()

        second = self.reject(
            _reproduction(observed_behavior="The stale state remains after three retries."),
        )
        updated = self.store.evidence_pack(self.task["id"])
        findings = [item for item in updated["findings"] if item["source"] == "human_test"]
        reproductions = [item for item in updated["items"] if item["kind"] == "human_test"]
        with self.database._get_connection() as conn:
            attention_count = conn.execute(
                """SELECT COUNT(*) AS count FROM control_attention_items
                   WHERE entity_type = 'agent_task' AND entity_id = ?
                     AND category = 'human_test_repair' AND status = 'open'""",
                (self.task["id"],),
            ).fetchone()["count"]
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["id"], finding["id"])
        self.assertEqual(findings[0]["status"], "open")
        self.assertEqual(len(reproductions), 1)
        self.assertEqual(reproductions[0]["id"], reproduction["id"])
        self.assertEqual(
            reproductions[0]["payload"]["observed_behavior"],
            "The stale state remains after three retries.",
        )
        self.assertEqual(attention_count, 1)

    def test_terminal_task_cannot_be_resurrected_by_late_rejection(self):
        with self.database._get_connection() as conn:
            conn.execute(
                "UPDATE control_agent_tasks SET status = 'completed', finished_at = CURRENT_TIMESTAMP WHERE id = ?",
                (self.task["id"],),
            )
            conn.commit()
        with self.assertRaises(ControlCenterError) as raised:
            self.reject()
        self.assertEqual(raised.exception.code, "human_test_repair_not_allowed")
        self.assertEqual(self.store.get_task(self.task["id"])["status"], "completed")
        self.assertEqual(self.store.evidence_pack(self.task["id"])["approvals"], [])

    def test_rejected_task_is_claimable_as_a_bounded_repair(self):
        self.reject()
        leased = self.store.lease_next_task("repair-worker")
        self.assertIsNotNone(leased)
        self.assertEqual(leased["id"], self.task["id"])
        self.assertEqual(leased["status"], "leased")
        self.assertEqual(leased["lease_owner"], "repair-worker")


class TestNegativeHumanTestAPI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ag_human_reject_api_")
        self.database = Database(Path(self.temp.name) / "control.db")
        self.project_id = self.database.add_project("Human rejection API", self.temp.name)
        self.store = ControlCenterStore(
            self.database,
            sha_resolver=lambda _project: "a" * 40,
        )
        self.task = _ready_human_task(self.store, self.project_id)
        self.store_patch = patch("src.control_center_handlers.control_center", self.store)
        self.store_patch.start()
        app = web.Application()
        app.router.add_post(
            "/api/control-center/tasks/{task_id}/approvals",
            handle_task_approval,
        )
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.store_patch.stop()
        self.temp.cleanup()

    async def test_api_forwards_reproduction_evidence_into_atomic_repair(self):
        response = await self.client.post(
            f"/api/control-center/tasks/{self.task['id']}/approvals",
            json={
                "approval_type": "human_test",
                "sha": SHA,
                "decision": "rejected",
                "actor": "owner",
                "reason": "The verified interaction still fails.",
                "evidence": _reproduction(),
            },
            headers={"Idempotency-Key": "human-rejection-1"},
        )
        self.assertEqual(response.status, 201, await response.text())
        body = await response.json()
        self.assertEqual(body["approval"]["evidence"], _reproduction())
        self.assertEqual(self.store.get_task(self.task["id"])["status"], "repair")


if __name__ == "__main__":
    unittest.main()
