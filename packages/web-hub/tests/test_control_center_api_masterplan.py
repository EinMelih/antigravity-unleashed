"""Public REST and webhook contracts for the engineering control plane."""

import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.control_center import ControlCenterStore
from src.control_center_handlers import (
    handle_answer_planning_question,
    handle_cancel_planning_job,
    handle_github_webhook,
    handle_idea_seed,
    handle_idea_seed_disposition,
    handle_idea_seed_plan,
    handle_idea_seeds,
    handle_decide_plan_amendment,
    handle_plan_amendment,
    handle_plan_amendment_detail,
    handle_planning_job,
    handle_planning_jobs,
    handle_repository_policy,
)
from src.database import Database


SHA = "a" * 40


class TestControlCenterMasterplanAPI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ag_control_api_masterplan_")
        self.database = Database(Path(self.temp.name) / "control.db")
        self.project_id = self.database.add_project(
            "API Masterplan",
            self.temp.name,
        )
        self.store = ControlCenterStore(
            self.database,
            sha_resolver=lambda _project: SHA,
        )
        self.store_patch = patch(
            "src.control_center_handlers.control_center",
            self.store,
        )
        self.store_patch.start()
        self.config_patch = patch.dict(
            "src.control_center_handlers.config.config_dict",
            {"github_webhook_secret": "test-webhook-secret"},
        )
        self.config_patch.start()
        app = web.Application()
        app.router.add_get(
            "/api/control-center/projects/{project_id}/policy",
            handle_repository_policy,
        )
        app.router.add_put(
            "/api/control-center/projects/{project_id}/policy",
            handle_repository_policy,
        )
        app.router.add_get(
            "/api/control-center/planning-jobs",
            handle_planning_jobs,
        )
        app.router.add_post(
            "/api/control-center/planning-jobs",
            handle_planning_jobs,
        )
        app.router.add_get(
            "/api/control-center/idea-seeds",
            handle_idea_seeds,
        )
        app.router.add_post(
            "/api/control-center/idea-seeds",
            handle_idea_seeds,
        )
        app.router.add_get(
            "/api/control-center/idea-seeds/{idea_seed_id}",
            handle_idea_seed,
        )
        app.router.add_patch(
            "/api/control-center/idea-seeds/{idea_seed_id}",
            handle_idea_seed,
        )
        app.router.add_post(
            "/api/control-center/idea-seeds/{idea_seed_id}/disposition",
            handle_idea_seed_disposition,
        )
        app.router.add_post(
            "/api/control-center/idea-seeds/{idea_seed_id}/plan",
            handle_idea_seed_plan,
        )
        app.router.add_get(
            "/api/control-center/planning-jobs/{job_id}",
            handle_planning_job,
        )
        app.router.add_post(
            "/api/control-center/planning-jobs/{job_id}/cancel",
            handle_cancel_planning_job,
        )
        app.router.add_post(
            "/api/control-center/planning-questions/{question_id}/answer",
            handle_answer_planning_question,
        )
        app.router.add_post(
            "/api/control-center/campaigns/{campaign_id}/amendments",
            handle_plan_amendment,
        )
        app.router.add_get(
            "/api/control-center/amendments/{amendment_id}",
            handle_plan_amendment_detail,
        )
        app.router.add_post(
            "/api/control-center/amendments/{amendment_id}/decision",
            handle_decide_plan_amendment,
        )
        app.router.add_post(
            "/api/control-center/github/webhook",
            handle_github_webhook,
        )
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.config_patch.stop()
        self.store_patch.stop()
        self.temp.cleanup()

    async def test_planning_job_rest_is_idempotent_and_bounded(self):
        payload = {
            "project_id": self.project_id,
            "wish": "Plan a complete but bounded reliability improvement campaign.",
            "planning_depth": "exhaustive",
            "max_candidates": 100,
        }
        headers = {"Idempotency-Key": "wish-plan-1"}
        first = await self.client.post(
            "/api/control-center/planning-jobs",
            json=payload,
            headers=headers,
        )
        self.assertEqual(first.status, 202, await first.text())
        first_body = await first.json()
        replay = await self.client.post(
            "/api/control-center/planning-jobs",
            json=payload,
            headers=headers,
        )
        self.assertEqual(replay.status, 202, await replay.text())
        replay_body = await replay.json()
        self.assertEqual(
            first_body["planning_job"]["id"],
            replay_body["planning_job"]["id"],
        )
        self.assertTrue(replay_body["idempotent_replay"])
        listing = await self.client.get(
            f"/api/control-center/planning-jobs?project_id={self.project_id}"
        )
        self.assertEqual(listing.status, 200)
        self.assertEqual(len((await listing.json())["planning_jobs"]), 1)

    async def test_planning_job_errors_are_redacted_before_storage_and_api_output(self):
        job = self.store.create_planning_job(
            {
                "project_id": self.project_id,
                "wish": "Diagnose a bounded planning failure.",
                "planning_depth": "compact",
            }
        )
        self.store.claim_planning_job()
        raw_error = (
            r"Failed at D:\private projects\secret-repo\.env; "
            "Authorization: Bearer bearer-secret-value; "
            "api_key=provider-secret-value"
        )

        self.store.fail_planning_job(job["id"], raw_error)

        with self.database._get_connection() as connection:
            persisted = str(
                connection.execute(
                    "SELECT last_error FROM control_planning_jobs WHERE id = ?",
                    (job["id"],),
                ).fetchone()["last_error"]
            )
        detail = await self.client.get(
            f"/api/control-center/planning-jobs/{job['id']}"
        )
        self.assertEqual(detail.status, 200, await detail.text())
        exposed = str((await detail.json())["planning_job"]["last_error"])

        for value in (
            "private projects",
            "bearer-secret-value",
            "provider-secret-value",
        ):
            self.assertNotIn(value, persisted)
            self.assertNotIn(value, exposed)
        self.assertIn("[PATH REDACTED]", persisted)
        self.assertIn("[REDACTED]", exposed)

        with self.database._get_connection() as connection:
            connection.execute(
                "UPDATE control_planning_jobs SET last_error = ? WHERE id = ?",
                (raw_error, job["id"]),
            )
            connection.commit()
        legacy_detail = await self.client.get(
            f"/api/control-center/planning-jobs/{job['id']}"
        )
        legacy_exposed = str((await legacy_detail.json())["planning_job"]["last_error"])
        self.assertNotIn("private projects", legacy_exposed)
        self.assertNotIn("bearer-secret-value", legacy_exposed)
        self.assertNotIn("provider-secret-value", legacy_exposed)

    async def test_session_answer_returns_requeued_planning_job(self):
        job = self.store.create_planning_job(
            {
                "project_id": self.project_id,
                "wish": "Clarify the success outcome before creating PR slices.",
                "planning_depth": "compact",
            }
        )
        self.store.claim_planning_job()
        self.store.update_planning_job_chat(job["id"], "session-chat")
        waiting = self.store.complete_planning_job(
            job["id"],
            {
                "type": "question",
                "question": {
                    "branch": "success",
                    "question": "Which outcome defines success?",
                    "rationale": "The answer changes the acceptance criteria.",
                },
            },
        )

        response = await self.client.post(
            "/api/control-center/planning-questions/"
            f"{waiting['active_question_id']}/answer",
            json={
                "answer": "A verified user completes the flow.",
                "answer_source": "owner",
            },
            headers={"Idempotency-Key": "planning-answer-1"},
        )

        self.assertEqual(response.status, 200, await response.text())
        body = await response.json()
        self.assertEqual(body["question"]["status"], "answered")
        self.assertEqual(body["planning_job"]["id"], job["id"])
        self.assertEqual(body["planning_job"]["status"], "queued")
        self.assertEqual(
            body["planning_job"]["antigravity_chat_id"],
            "session-chat",
        )

    async def test_repository_policy_rejects_unregistered_delete(self):
        response = await self.client.delete(
            f"/api/control-center/projects/{self.project_id}/policy"
        )
        self.assertEqual(response.status, 405)

    async def test_plan_amendment_rest_forwards_exact_identity_and_returns_job(self):
        amendment = {
            "id": "AMD-api-1",
            "campaign_id": "CMP-api-1",
            "planning_job_id": "PLN-api-1",
            "status": "planning",
        }
        planning_job = {
            "id": "PLN-api-1",
            "job_type": "plan_amendment",
            "amendment_id": "AMD-api-1",
            "status": "queued",
        }
        start_payload = {
            "reason": "Replan only future work with an exact reviewed target.",
            "focus": {"requested_change": "Split the future slice."},
            "expected_version": 4,
            "expected_base_sha": SHA,
            "expected_plan_signature": "b" * 64,
            "expected_plan_signature_version": 2,
            "actor": "human",
        }
        with patch.object(
            self.store,
            "start_plan_amendment",
            return_value={"amendment": amendment, "planning_job": planning_job},
        ) as start:
            response = await self.client.post(
                "/api/control-center/campaigns/CMP-api-1/amendments",
                json=start_payload,
                headers={"Idempotency-Key": "amendment-start-api-1"},
            )
        self.assertEqual(response.status, 201, await response.text())
        self.assertEqual((await response.json())["planning_job"]["job_type"], "plan_amendment")
        start.assert_called_once_with("CMP-api-1", start_payload)

        with patch.object(
            self.store,
            "get_plan_amendment",
            return_value={**amendment, "status": "review"},
        ):
            detail = await self.client.get(
                "/api/control-center/amendments/AMD-api-1"
            )
        self.assertEqual(detail.status, 200, await detail.text())
        self.assertEqual((await detail.json())["amendment"]["id"], "AMD-api-1")

        decision_payload = {
            "decision": "approved",
            "actor": "reviewer",
            "reason": "Exact target reviewed.",
            "approval_sha": SHA,
            "expected_from_version": 4,
            "expected_before_plan_sha256": "c" * 64,
            "expected_target_plan_sha256": "d" * 64,
            "expected_patch_sha256": "e" * 64,
        }
        with (
            patch.object(
                self.store,
                "decide_plan_amendment",
                return_value={**amendment, "status": "approved"},
            ) as decide,
            patch.object(
                self.store,
                "get_planning_job",
                return_value={**planning_job, "status": "completed"},
            ),
        ):
            decision = await self.client.post(
                "/api/control-center/amendments/AMD-api-1/decision",
                json=decision_payload,
                headers={"Idempotency-Key": "amendment-decision-api-1"},
            )
        self.assertEqual(decision.status, 200, await decision.text())
        decision_body = await decision.json()
        self.assertEqual(decision_body["amendment"]["status"], "approved")
        self.assertEqual(decision_body["planning_job"]["status"], "completed")
        decide.assert_called_once_with(
            "AMD-api-1",
            decision="approved",
            actor="reviewer",
            approval_sha=SHA,
            reason="Exact target reviewed.",
            expected_from_version=4,
            expected_before_plan_sha256="c" * 64,
            expected_target_plan_sha256="d" * 64,
            expected_patch_sha256="e" * 64,
        )

    async def test_idea_seed_rest_supports_inbox_editing_and_disposition(self):
        created = await self.client.post(
            "/api/control-center/idea-seeds",
            json={
                "project_id": self.project_id,
                "title": "Reliable review summaries",
                "note": "Capture review evidence in a concise human-readable summary.",
                "source": "human",
            },
            headers={"Idempotency-Key": "idea-seed-create-1"},
        )
        self.assertEqual(created.status, 201, await created.text())
        seed = (await created.json())["idea_seed"]

        listing = await self.client.get(
            f"/api/control-center/idea-seeds?project_id={self.project_id}"
        )
        self.assertEqual(listing.status, 200, await listing.text())
        self.assertEqual([item["id"] for item in (await listing.json())["idea_seeds"]], [seed["id"]])

        detail = await self.client.get(
            f"/api/control-center/idea-seeds/{seed['id']}"
        )
        self.assertEqual(detail.status, 200, await detail.text())
        self.assertEqual((await detail.json())["idea_seed"]["note"], seed["note"])

        updated = await self.client.patch(
            f"/api/control-center/idea-seeds/{seed['id']}",
            json={"title": "Review evidence summaries", "actor": "human"},
            headers={"Idempotency-Key": "idea-seed-update-1"},
        )
        self.assertEqual(updated.status, 200, await updated.text())
        self.assertEqual((await updated.json())["idea_seed"]["title"], "Review evidence summaries")

        deferred = await self.client.post(
            f"/api/control-center/idea-seeds/{seed['id']}/disposition",
            json={
                "disposition": "deferred",
                "reason": "First finish the active campaign.",
                "actor": "human",
            },
            headers={"Idempotency-Key": "idea-seed-defer-1"},
        )
        self.assertEqual(deferred.status, 200, await deferred.text())
        self.assertEqual((await deferred.json())["idea_seed"]["status"], "deferred")

    async def test_existing_idea_seed_can_be_planned_read_and_cancelled(self):
        seed = self.store.create_idea_seed(
            {
                "project_id": self.project_id,
                "title": "Plan a bounded reliability change",
                "note": "Turn this reliability idea into ordered reviewable PR slices.",
                "source": "human",
            }
        )
        planned = await self.client.post(
            f"/api/control-center/idea-seeds/{seed['id']}/plan",
            json={
                "planning_depth": "balanced",
                "max_candidates": 8,
                "activation_policy": "per_candidate",
                "actor": "human",
            },
            headers={"Idempotency-Key": "idea-seed-plan-1"},
        )
        self.assertEqual(planned.status, 202, await planned.text())
        job = (await planned.json())["planning_job"]
        self.assertEqual(job["idea_seed_id"], seed["id"])

        detail = await self.client.get(
            f"/api/control-center/planning-jobs/{job['id']}"
        )
        self.assertEqual(detail.status, 200, await detail.text())
        self.assertEqual((await detail.json())["planning_job"]["id"], job["id"])

        cancelled = await self.client.post(
            f"/api/control-center/planning-jobs/{job['id']}/cancel",
            json={"reason": "The owner changed direction.", "actor": "human"},
            headers={"Idempotency-Key": "planning-job-cancel-1"},
        )
        self.assertEqual(cancelled.status, 200, await cancelled.text())
        self.assertEqual((await cancelled.json())["planning_job"]["status"], "cancelled")
        self.assertEqual(self.store.get_idea_seed(seed["id"])["status"], "inbox")

    async def test_webhook_requires_valid_hmac_and_deduplicates_delivery(self):
        payload = {
            "action": "completed",
            "repository": {"full_name": "unknown/repository"},
            "check_suite": {"id": 91},
        }
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        invalid = await self.client.post(
            "/api/control-center/github/webhook",
            data=raw,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Delivery": "delivery-1",
                "X-GitHub-Event": "check_suite",
                "X-Hub-Signature-256": "sha256=invalid",
            },
        )
        self.assertEqual(invalid.status, 401)
        signature = "sha256=" + hmac.new(
            b"test-webhook-secret",
            raw,
            hashlib.sha256,
        ).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-GitHub-Delivery": "delivery-1",
            "X-GitHub-Event": "check_suite",
            "X-Hub-Signature-256": signature,
        }
        first = await self.client.post(
            "/api/control-center/github/webhook",
            data=raw,
            headers=headers,
        )
        self.assertEqual(first.status, 200, await first.text())
        first_body = await first.json()
        self.assertEqual(first_body["webhook"]["status"], "ignored")
        replay = await self.client.post(
            "/api/control-center/github/webhook",
            data=raw,
            headers=headers,
        )
        self.assertEqual(replay.status, 200, await replay.text())
        replay_body = await replay.json()
        self.assertTrue(replay_body["webhook"]["deduplicated"])


if __name__ == "__main__":
    unittest.main()
