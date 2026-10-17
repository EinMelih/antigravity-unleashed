"""Safety regressions for resuming one task after a Hub infrastructure fix."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from src.control_center import ControlCenterError, ControlCenterStore
from src.control_center.executor_service import ControlCenterExecutor
from src.control_center_handlers import handle_resume_task_after_fix
from src.database import Database
from tests.control_center_plan_fixtures import prepare_plan_for_approval


SHA = "a" * 40


class RecordingAdapter:
    def __init__(self):
        self.repair_flags = []

    async def dispatch(self, _context, *, repair=False):
        self.repair_flags.append(repair)
        return {"chat_id": "replacement-chat"}

    async def wait_until_complete(self, _chat_id, *, timeout_seconds):
        return {"completed": True, "timeout_seconds": timeout_seconds}

    @staticmethod
    def progress_payload(_result):
        return {"summary": "Operator resume completed."}


class RecordingFlow:
    instances = []

    def __init__(self, store):
        self.store = store
        self.materialize_calls = 0
        self.publish_calls = 0
        self.__class__.instances.append(self)

    def _context(self, task_id):
        return self.store.get_task(task_id)

    async def materialize_task(self, *_args, **_kwargs):
        self.materialize_calls += 1
        raise AssertionError("A materialized task must not be materialized again.")

    async def publish_draft_pull_request(
        self,
        task_id,
        *,
        worker_id,
        lease_token,
    ):
        self.publish_calls += 1
        return self.store.transition_task(
            task_id,
            to_state="waiting_ci",
            actor=worker_id,
            lease_token=lease_token,
            reason="Test publish.",
            fields={"wake_reason": "github_checks"},
        )


class StaleReviewSyncFlow:
    """Simulate an in-flight sync finishing after an operator resume."""

    def __init__(self, store):
        self.store = store

    async def sync_pull_request(self, task_id):
        with self.store.db._get_connection() as conn:
            conn.execute(
                """UPDATE control_agent_tasks
                   SET status = 'queued', wake_reason = 'operator_resume',
                       lease_owner = '', lease_token = '', lease_until = NULL
                   WHERE id = ?""",
                (task_id,),
            )
            conn.commit()
        return {"evidence_pack": {"status": "blocked"}}


class RecordingReviewSyncFlow:
    calls = []

    def __init__(self, _store):
        pass

    async def sync_pull_request(self, task_id):
        self.__class__.calls.append(task_id)
        return {"evidence_pack": {"status": "collecting"}}


class TransientReviewSyncFlow:
    calls = []

    def __init__(self, _store):
        pass

    async def sync_pull_request(self, task_id):
        self.__class__.calls.append(task_id)
        raise ConnectionError("GitHub unavailable")


class TestOperatorTaskResume(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ag_operator_resume_")
        root = Path(self.temp.name)
        self.database = Database(root / "control.db")
        self.project_id = self.database.add_project(
            "Operator resume",
            str(root / "repo"),
            github_url="https://github.com/owner/repo",
            github_owner="owner",
            github_repo="repo",
            default_branch="main",
            source_kind="github",
        )
        self.store = ControlCenterStore(
            self.database,
            sha_resolver=lambda _project: SHA,
        )
        campaign = self.store.create_campaign(
            {
                "project_id": self.project_id,
                "title": "Resume campaign",
                "goal": "Resume an interrupted task without duplicating resources.",
                "rollback_plan": "Discard the isolated worktree.",
            }
        )
        candidate = self.store.create_pr_candidate(
            campaign["id"],
            {
                "title": "Resume implementation",
                "scope": "Exercise the operator recovery path.",
                "acceptance_criteria": ["The same task resumes once."],
                "required_checks": ["unit"],
                "definition_of_done": "The durable task identity is preserved.",
            },
        )
        readiness = prepare_plan_for_approval(self.store, campaign["id"])
        approved = self.store.approve_campaign(
            campaign["id"],
            expected_version=2,
            approval_sha=SHA,
            expected_plan_signature=readiness["plan_signature"],
        )
        self.store.activate_candidate(
            candidate["id"],
            approval_sha=approved["approved_sha"],
        )
        leased = self.store.lease_next_task("worker-before-fix")
        self.store.transition_task(
            leased["id"],
            to_state="running",
            actor="worker-before-fix",
            lease_token=leased["lease_token"],
            reason="Materialized before infrastructure failure.",
            fields={
                "issue_number": 17,
                "issue_url": "https://github.test/issues/17",
                "worktree_path": str(root / "existing-worktree"),
                "wake_reason": "agent_execution",
            },
        )
        self.store.transition_task(
            leased["id"],
            to_state="repair",
            actor="orchestrator",
            reason="Project discovery failed before chat creation.",
            fields={
                "last_error": "Linked project did not become visible.",
                "wake_reason": "retry:executor_failure",
            },
        )
        self.task_id = leased["id"]

    def tearDown(self):
        self.temp.cleanup()

    def test_resume_requires_global_pause_and_preserves_all_identities(self):
        before = self.store.get_task(self.task_id)
        with self.assertRaises(ControlCenterError) as context:
            self.store.resume_task_after_operator_fix(
                self.task_id,
                actor="operator",
                reason="Fix deployed.",
            )
        self.assertEqual(context.exception.code, "operator_resume_requires_pause")

        self.store.update_policy(
            mode="guided",
            paused=True,
            reason="Deploying infrastructure fix.",
            actor="operator",
        )
        resumed = self.store.resume_task_after_operator_fix(
            self.task_id,
            actor="operator",
            reason="Project discovery fix deployed.",
        )
        self.assertEqual(resumed["status"], "queued")
        self.assertEqual(resumed["wake_reason"], "operator_resume")
        self.assertEqual(resumed["attempt"], before["attempt"] - 1)
        identity_fields = (
            "id",
            "work_order_id",
            "campaign_id",
            "candidate_id",
            "base_sha",
            "branch_name",
            "worktree_path",
            "issue_number",
            "issue_url",
            "antigravity_chat_id",
            "pr_number",
            "pr_url",
        )
        self.assertEqual(
            tuple(resumed[field] for field in identity_fields),
            tuple(before[field] for field in identity_fields),
        )
        self.assertIsNone(self.store.lease_next_task("blocked-by-pause"))

        replay = self.store.resume_task_after_operator_fix(
            self.task_id,
            actor="operator",
            reason="Idempotent request replay.",
        )
        self.assertEqual(replay["attempt"], resumed["attempt"])

        self.store.update_policy(
            mode="guided",
            paused=False,
            reason="",
            actor="operator",
        )
        leased = self.store.lease_next_task("worker-after-fix")
        self.assertEqual(leased["id"], self.task_id)
        self.assertEqual(leased["attempt"], max(1, before["attempt"] - 1))
        self.assertEqual(leased["issue_number"], 17)
        self.assertEqual(leased["worktree_path"], before["worktree_path"])
        with self.database._get_connection() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM control_agent_tasks WHERE id = ?",
                    (self.task_id,),
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM control_work_orders WHERE id = ?",
                    (before["work_order_id"],),
                ).fetchone()[0],
                1,
            )

    def test_executor_reuses_materialization_with_normal_first_chat_prompt(self):
        self.store.update_policy(
            mode="guided",
            paused=True,
            reason="Deploying infrastructure fix.",
            actor="operator",
        )
        resumed = self.store.resume_task_after_operator_fix(
            self.task_id,
            actor="operator",
            reason="Project discovery fix deployed.",
        )
        self.store.update_policy(
            mode="guided",
            paused=False,
            reason="",
            actor="operator",
        )
        leased = self.store.lease_next_task("worker-after-fix")
        adapter = RecordingAdapter()
        RecordingFlow.instances.clear()
        executor = ControlCenterExecutor(
            self.store,
            adapter=adapter,
            flow_factory=RecordingFlow,
        )

        asyncio.run(executor._execute_task(leased, "worker-after-fix"))

        flow = RecordingFlow.instances[-1]
        self.assertEqual(flow.materialize_calls, 0)
        self.assertEqual(flow.publish_calls, 1)
        self.assertEqual(adapter.repair_flags, [False])
        current = self.store.get_task(self.task_id)
        self.assertEqual(current["id"], resumed["id"])
        self.assertEqual(current["status"], "waiting_ci")
        self.assertEqual(current["issue_number"], 17)
        self.assertEqual(current["worktree_path"], resumed["worktree_path"])
        self.assertEqual(current["branch_name"], resumed["branch_name"])
        self.assertEqual(current["antigravity_chat_id"], "replacement-chat")
        self.assertEqual(current["last_error"], "")

    def test_executor_marks_resume_with_existing_chat_as_repair(self):
        with self.database._get_connection() as conn:
            conn.execute(
                """UPDATE control_agent_tasks
                   SET antigravity_chat_id = 'existing-chat'
                   WHERE id = ?""",
                (self.task_id,),
            )
            conn.commit()
        self.store.update_policy(
            mode="guided",
            paused=True,
            reason="Deploying infrastructure fix.",
            actor="operator",
        )
        self.store.resume_task_after_operator_fix(
            self.task_id,
            actor="operator",
            reason="Existing chat repair can continue.",
        )
        self.store.update_policy(
            mode="guided",
            paused=False,
            reason="",
            actor="operator",
        )
        leased = self.store.lease_next_task("worker-existing-chat")
        adapter = RecordingAdapter()
        RecordingFlow.instances.clear()
        executor = ControlCenterExecutor(
            self.store,
            adapter=adapter,
            flow_factory=RecordingFlow,
        )

        asyncio.run(executor._execute_task(leased, "worker-existing-chat"))

        self.assertEqual(adapter.repair_flags, [True])
        self.assertEqual(self.store.get_task(self.task_id)["status"], "waiting_ci")

    def test_exhausted_executor_failure_can_resume_after_operator_fix(self):
        leased = self.store.lease_next_task("worker-final-attempt")
        self.store.transition_task(
            self.task_id,
            to_state="failed",
            actor="worker-final-attempt",
            lease_token=leased["lease_token"],
            reason="Executor infrastructure failed.",
            fields={
                "last_error": "Executor-Fehler: duplicate project config",
                "wake_reason": "failed:executor_failure",
            },
        )
        before = self.store.get_task(self.task_id)
        self.store.update_policy(
            mode="guided",
            paused=True,
            reason="Deploying the resolver fix.",
            actor="operator",
        )

        resumed = self.store.resume_task_after_operator_fix(
            self.task_id,
            actor="operator",
            reason="Resolver fix deployed.",
        )

        self.assertEqual(resumed["status"], "queued")
        self.assertEqual(resumed["wake_reason"], "operator_resume")
        self.assertEqual(resumed["attempt"], before["attempt"] - 1)
        with self.database._get_connection() as conn:
            candidate_status = conn.execute(
                "SELECT status FROM control_pr_candidates WHERE id = ?",
                (resumed["candidate_id"],),
            ).fetchone()["status"]
        self.assertEqual(candidate_status, "approved")

        self.store.update_policy(
            mode="guided",
            paused=False,
            reason="",
            actor="operator",
        )
        retried = self.store.lease_next_task("worker-after-exhausted-fix")
        self.assertEqual(retried["attempt"], resumed["attempt"])

    def test_legacy_executor_failure_can_resume_but_other_failure_cannot(self):
        leased = self.store.lease_next_task("worker-legacy-failure")
        self.store.transition_task(
            self.task_id,
            to_state="failed",
            actor="worker-legacy-failure",
            lease_token=leased["lease_token"],
            reason="Legacy executor infrastructure failed.",
            fields={
                "last_error": "Executor-Fehler: legacy failure without code",
                "wake_reason": "agent_execution",
            },
        )
        self.store.update_policy(
            mode="guided",
            paused=True,
            reason="Deploying the compatibility fix.",
            actor="operator",
        )
        resumed = self.store.resume_task_after_operator_fix(
            self.task_id,
            actor="operator",
            reason="Compatibility fix deployed.",
        )
        self.assertEqual(resumed["status"], "queued")

        with self.database._get_connection() as conn:
            conn.execute(
                """UPDATE control_agent_tasks
                   SET status = 'failed', wake_reason = 'agent_execution',
                       last_error = 'Validation failed', finished_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (self.task_id,),
            )
            conn.commit()
        with self.assertRaises(ControlCenterError) as context:
            self.store.resume_task_after_operator_fix(
                self.task_id,
                actor="operator",
                reason="Must not retry a product failure.",
            )
        self.assertEqual(context.exception.code, "operator_resume_not_allowed")

    def test_blocked_sha_review_can_resume_after_hub_fix(self):
        with self.database._get_connection() as conn:
            conn.execute(
                """UPDATE control_agent_tasks
                   SET status = 'waiting_review', wake_reason = 'review_and_evidence',
                       current_sha = ?, attempt = 4,
                       lease_owner = '', lease_token = '', lease_until = NULL
                   WHERE id = ?""",
                (SHA, self.task_id),
            )
            conn.commit()
        finding = self.store.record_finding(
            self.task_id,
            {
                "classification": "REQUIRED",
                "source": "independent_review",
                "body": "Repair prompt omitted this finding.",
                "sha": SHA,
            },
        )
        self.store.update_policy(
            mode="guided",
            paused=True,
            reason="Deploying the repair-prompt fix.",
            actor="operator",
        )

        resumed = self.store.resume_task_after_operator_fix(
            self.task_id,
            actor="operator",
            reason="Finding delivery is fixed and can be retried once.",
        )

        self.assertEqual(finding["status"], "open")
        self.assertEqual(resumed["status"], "queued")
        self.assertEqual(resumed["attempt"], 3)
        with self.database._get_connection() as conn:
            audit = conn.execute(
                """SELECT evidence_json FROM control_audit_events
                   WHERE entity_id = ? AND action = 'agent_task.operator_resumed'
                   ORDER BY id DESC LIMIT 1""",
                (self.task_id,),
            ).fetchone()
        evidence = json.loads(audit["evidence_json"])
        self.assertEqual(evidence["resume_kind"], "review_after_system_fix")
        self.assertEqual(evidence["blocking_review_findings"], 1)

    def test_nonblocking_review_finding_cannot_use_system_fix_resume(self):
        with self.database._get_connection() as conn:
            conn.execute(
                """UPDATE control_agent_tasks
                   SET status = 'waiting_review', wake_reason = 'review_and_evidence',
                       current_sha = ?, attempt = 4,
                       lease_owner = '', lease_token = '', lease_until = NULL
                   WHERE id = ?""",
                (SHA, self.task_id),
            )
            conn.commit()
        self.store.record_finding(
            self.task_id,
            {
                "classification": "SUGGESTION",
                "source": "review",
                "body": "Optional wording improvement.",
                "sha": SHA,
            },
        )
        self.store.update_policy(
            mode="guided",
            paused=True,
            reason="Testing review resume boundaries.",
            actor="operator",
        )

        with self.assertRaises(ControlCenterError) as context:
            self.store.resume_task_after_operator_fix(
                self.task_id,
                actor="operator",
                reason="A suggestion must not grant another run.",
            )

        self.assertEqual(context.exception.code, "operator_resume_not_allowed")

    def test_stale_review_sync_cannot_overwrite_operator_resume(self):
        with self.database._get_connection() as conn:
            conn.execute(
                """UPDATE control_agent_tasks
                   SET status = 'waiting_review', wake_reason = 'review_and_evidence',
                       current_sha = ?, pr_number = 5, attempt = 1,
                       lease_owner = '', lease_token = '', lease_until = NULL
                   WHERE id = ?""",
                (SHA, self.task_id),
            )
            conn.commit()
        executor = ControlCenterExecutor(
            self.store,
            adapter=RecordingAdapter(),
            flow_factory=StaleReviewSyncFlow,
        )

        asyncio.run(executor._sync_waiting_tasks())

        current = self.store.get_task(self.task_id)
        self.assertEqual(current["status"], "queued")
        self.assertEqual(current["wake_reason"], "operator_resume")

    def test_waiting_human_is_polled_and_transient_failure_preserves_state(self):
        with self.database._get_connection() as conn:
            conn.execute(
                """UPDATE control_agent_tasks
                   SET status = 'waiting_human', wake_reason = 'human_test',
                       current_sha = ?, pr_number = 5,
                       lease_owner = '', lease_token = '', lease_until = NULL
                   WHERE id = ?""",
                (SHA, self.task_id),
            )
            conn.commit()

        RecordingReviewSyncFlow.calls = []
        executor = ControlCenterExecutor(
            self.store,
            adapter=RecordingAdapter(),
            flow_factory=RecordingReviewSyncFlow,
        )
        asyncio.run(executor._sync_waiting_tasks())
        self.assertEqual(RecordingReviewSyncFlow.calls, [self.task_id])

        TransientReviewSyncFlow.calls = []
        executor = ControlCenterExecutor(
            self.store,
            adapter=RecordingAdapter(),
            flow_factory=TransientReviewSyncFlow,
        )
        asyncio.run(executor._sync_waiting_tasks())

        self.assertEqual(TransientReviewSyncFlow.calls, [self.task_id])
        self.assertEqual(self.store.get_task(self.task_id)["status"], "waiting_human")
        self.assertIn("GitHub unavailable", executor.last_error)
        self.assertEqual(executor._syncing, set())

    def test_public_resume_endpoint_is_idempotent(self):
        self.store.update_policy(
            mode="guided",
            paused=True,
            reason="Deploying infrastructure fix.",
            actor="operator",
        )
        before = self.store.get_task(self.task_id)

        async def exercise():
            app = web.Application()
            app.router.add_post(
                "/api/control-center/tasks/{task_id}/resume-after-fix",
                handle_resume_task_after_fix,
            )
            client = TestClient(TestServer(app))
            await client.start_server()
            try:
                headers = {"Idempotency-Key": "resume-system-fix-once"}
                payload = {
                    "actor": "operator",
                    "reason": "Project discovery fix deployed.",
                }
                first = await client.post(
                    f"/api/control-center/tasks/{self.task_id}/resume-after-fix",
                    json=payload,
                    headers=headers,
                )
                self.assertEqual(first.status, 200, await first.text())
                first_body = await first.json()
                replay = await client.post(
                    f"/api/control-center/tasks/{self.task_id}/resume-after-fix",
                    json=payload,
                    headers=headers,
                )
                self.assertEqual(replay.status, 200, await replay.text())
                replay_body = await replay.json()
                self.assertTrue(replay_body["idempotent_replay"])
                self.assertEqual(
                    replay_body["task"]["attempt"],
                    first_body["task"]["attempt"],
                )
            finally:
                await client.close()

        with patch("src.control_center_handlers.control_center", self.store):
            asyncio.run(exercise())

        current = self.store.get_task(self.task_id)
        self.assertEqual(current["attempt"], before["attempt"] - 1)
        with self.database._get_connection() as conn:
            audit_count = conn.execute(
                """SELECT COUNT(*) FROM control_audit_events
                   WHERE entity_id = ?
                     AND action = 'agent_task.operator_resumed'""",
                (self.task_id,),
            ).fetchone()[0]
        self.assertEqual(audit_count, 1)


if __name__ == "__main__":
    unittest.main()
