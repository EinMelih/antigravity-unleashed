"""Edge-case contracts for atomic planning, merge provenance, and planner isolation."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.control_center import ControlCenterError, ControlCenterStore
from src.control_center.executor_service import ControlCenterExecutor
from src.control_center.github_flow import GitHubFlow
from src.database import Database
from tests.control_center_plan_fixtures import prepare_plan_for_approval


SHA_HEAD = "a" * 40
SHA_MERGED = "b" * 40


class MergeGitHub:
    def __init__(self, *, fail_close=False):
        self.marked_ready = False
        self.fail_close = fail_close
        self.pull_requests_read = 0

    async def get_pull_request(self, *_args, **_kwargs):
        self.pull_requests_read += 1
        return {
            "state": "open",
            "draft": True,
            "head_sha": SHA_HEAD,
        }

    async def mark_pull_request_ready(self, *_args, **_kwargs):
        self.marked_ready = True
        return {"draft": False}

    async def merge_pull_request(self, *_args, **_kwargs):
        return {
            "merged": True,
            "message": "merged",
            "sha": SHA_MERGED,
        }

    async def close_issue(self, *_args, **_kwargs):
        if self.fail_close:
            raise RuntimeError("synthetic issue close failure")
        return {"state": "closed"}


class PlannerAdapter:
    def __init__(self):
        self.dispatched = False
        self.read_called = False

    async def dispatch_planning(self, _job, _project):
        self.dispatched = True
        return {"chat_id": "planner-chat"}

    async def wait_until_complete(self, _chat_id, *, timeout_seconds):
        return {"status": "complete", "timeout_seconds": timeout_seconds}

    def read_planning_result(self, _chat_id):
        self.read_called = True
        raise AssertionError("A mutated planning result must never be imported.")

    async def archive_chat(self, _chat_id):
        return None


class QuestionPlannerAdapter:
    def __init__(self):
        self.archived = False

    async def dispatch_planning(self, _job, _project):
        return {"chat_id": "socratic-planner-chat"}

    async def wait_until_complete(self, _chat_id, *, timeout_seconds):
        return {"status": "complete", "timeout_seconds": timeout_seconds}

    def read_planning_result(self, _chat_id):
        return {
            "type": "question",
            "question": {
                "branch": "success",
                "question": "Which outcome defines success?",
                "rationale": "The answer changes acceptance criteria.",
            },
        }

    async def archive_chat(self, _chat_id):
        self.archived = True


class LinkedQuestionPlannerAdapter(QuestionPlannerAdapter):
    async def dispatch_planning(self, _job, _project):
        return {
            "chat_id": "socratic-planner-chat",
            "project_context": {
                "project_uuid": "confirmed-native-uuid",
                "workspace_path": str(_project["path"]),
                "project_name": "Confirmed native project",
            },
        }


class RepairingQuestionPlannerAdapter(QuestionPlannerAdapter):
    def __init__(self):
        super().__init__()
        self.read_count = 0
        self.repair_count = 0

    def read_planning_result(self, _chat_id):
        self.read_count += 1
        if self.read_count == 1:
            raise ControlCenterError(
                "Planner-JSON ist ungültig: missing comma at char 10247",
                code="invalid_planning_output",
                status=409,
            )
        return super().read_planning_result(_chat_id)

    async def repair_planning_output(self, chat_id, error):
        self.repair_count += 1
        self.repair_chat_id = chat_id
        self.repair_error = error
        return {"chat_id": chat_id, "delivery_verified": True}


class CancellingPlannerAdapter(QuestionPlannerAdapter):
    def __init__(self, store, job_id):
        super().__init__()
        self.store = store
        self.job_id = job_id

    def read_planning_result(self, chat_id):
        self.store.cancel_planning_job(
            self.job_id,
            actor="owner",
            reason="Cancel while the planner result is in flight.",
        )
        return super().read_planning_result(chat_id)


class BlockingPlannerAdapter:
    def __init__(self):
        self.started = asyncio.Event()
        self.wait_cancelled = False
        self.read_called = False

    async def dispatch_planning(self, _job, _project):
        return {"chat_id": "blocking-planner-chat"}

    async def wait_until_complete(self, _chat_id, *, timeout_seconds):
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.wait_cancelled = True
            raise

    def read_planning_result(self, _chat_id):
        self.read_called = True
        raise AssertionError("A cancelled planning result must never be read.")

    async def archive_chat(self, _chat_id):
        return None


class StableSnapshots:
    def repository_snapshot(self, _project):
        return {
            "head": SHA_HEAD,
            "status": "",
            "fingerprint": "stable-planning-baseline",
        }


class SlowTaskAdapter:
    async def wait_until_complete(self, _chat_id, *, timeout_seconds):
        await asyncio.sleep(0.06)
        return {
            "completed": True,
            "timeout_seconds": timeout_seconds,
        }


class MutatingSnapshots:
    def __init__(self):
        self.calls = 0

    def repository_snapshot(self, _project):
        self.calls += 1
        return {
            "head": SHA_HEAD,
            "status": "",
            "fingerprint": f"snapshot-{self.calls}",
        }


class TestControlCenterEdgeCases(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ag_control_edges_")
        self.root = Path(self.temp.name)
        self.database = Database(self.root / "control.db")
        self.project_id = self.database.add_project(
            "Edge cases",
            str(self.root),
            github_url="https://github.com/owner/repo",
            github_owner="owner",
            github_repo="repo",
            default_branch="main",
            source_kind="github",
        )
        self.store = ControlCenterStore(
            self.database,
            sha_resolver=lambda _project: SHA_HEAD,
        )

    def tearDown(self):
        self.temp.cleanup()

    def _task(self):
        campaign = self.store.create_campaign(
            {
                "project_id": self.project_id,
                "title": "SHA provenance",
                "goal": "Keep reviewed and merged revisions independently auditable.",
                "rollback_plan": "Revert the merge commit.",
            }
        )
        candidate = self.store.create_pr_candidate(
            campaign["id"],
            {
                "title": "Preserve merge SHA",
                "scope": "Store the reviewed PR head and the resulting merge commit.",
                "acceptance_criteria": ["Both revisions remain independently visible."],
                "required_checks": ["unit"],
                "definition_of_done": "Production uses the merge commit SHA.",
            },
        )
        readiness = prepare_plan_for_approval(self.store, campaign["id"])
        approved = self.store.approve_campaign(
            campaign["id"],
            expected_version=2,
            approval_sha=SHA_HEAD,
            expected_plan_signature=readiness["plan_signature"],
        )
        self.store.activate_candidate(
            candidate["id"],
            approval_sha=approved["approved_sha"],
        )
        return self.store.list_tasks(campaign_id=campaign["id"])[0]

    def _ready_merge_task(self):
        task = self._task()
        return self._authorize_merge_task(task)

    def _authorize_merge_task(self, task, *, pr_number=7):
        self.store.set_task_revision(task["id"], sha=SHA_HEAD)
        for key in ("acceptance:1", "check:unit", "manual:1"):
            self.store.add_evidence(
                task["id"],
                {
                    "kind": "test",
                    "criterion_key": key,
                    "title": key,
                    "status": "passed",
                    "sha": SHA_HEAD,
                },
            )
        self.store.evaluate_evidence_pack(task["id"])
        for approval_type in ("human_test", "merge"):
            self.store.record_human_approval(
                task["id"],
                approval_type=approval_type,
                sha=SHA_HEAD,
                decision="approved",
            )
        self.store.update_repository_policy(
            self.project_id,
            {
                "capability": {
                    "merge_pr": True,
                    "deploy_production": True,
                }
            },
        )
        with self.database._get_connection() as conn:
            conn.execute(
                """UPDATE control_agent_tasks
                   SET pr_number = ?, issue_number = 3, status = 'waiting_human'
                   WHERE id = ?""",
                (pr_number, task["id"]),
            )
            conn.commit()
        return self.store.get_task(task["id"])

    def test_materialized_artifact_failure_rolls_back_database(self):
        with patch.object(Path, "write_bytes", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.store.save_artifact(
                    {
                        "project_id": self.project_id,
                        "artifact_type": "adr",
                        "title": "Atomic artifact",
                        "content": "# Decision\n\nCommit file and row together.",
                    }
                )
        self.assertEqual(self.store.list_artifacts(self.project_id), [])

    def test_merge_sha_is_distinct_and_required_for_production(self):
        task = self._ready_merge_task()
        github = MergeGitHub()
        flow = GitHubFlow(self.store, client=github)
        result = asyncio.run(flow.merge_task(task["id"]))
        merged_task = result["task"]
        self.assertEqual(merged_task["current_sha"], SHA_HEAD)
        self.assertEqual(merged_task["merged_sha"], SHA_MERGED)
        self.assertTrue(github.marked_ready)
        self.assertTrue(result["campaign_completed"])
        with self.database._get_connection() as conn:
            campaign = conn.execute(
                "SELECT status FROM control_campaigns WHERE id = ?",
                (task["campaign_id"],),
            ).fetchone()
            profile = conn.execute(
                "SELECT completed_at FROM control_campaign_profiles WHERE campaign_id = ?",
                (task["campaign_id"],),
            ).fetchone()
        self.assertEqual(campaign["status"], "completed")
        self.assertIsNotNone(profile["completed_at"])
        overview = self.store.overview(self.project_id)
        self.assertEqual(overview["summary"]["campaigns_open"], 0)
        self.assertFalse(
            any(
                item["category"] == "work_order_approval"
                for item in overview["attention"]
            )
        )
        self.store.record_human_approval(
            task["id"],
            approval_type="production",
            sha=SHA_MERGED,
            decision="approved",
        )
        deployment = self.store.create_deployment(
            task["id"],
            {
                "environment": "production",
                "sha": SHA_MERGED,
            },
        )
        self.assertEqual(deployment["sha"], SHA_MERGED)

    def test_two_real_merges_complete_only_after_the_final_candidate(self):
        campaign = self.store.create_campaign(
            {
                "project_id": self.project_id,
                "title": "Two merge completion",
                "goal": "Complete the campaign only after both pull requests merge.",
                "rollback_plan": "Revert both merge commits in reverse order.",
            }
        )
        candidates = [
            self.store.create_pr_candidate(
                campaign["id"],
                {
                    "title": title,
                    "scope": f"Implement {title} as an isolated change.",
                    "acceptance_criteria": [f"{title} is verified."],
                    "required_checks": ["unit"],
                    "definition_of_done": f"{title} is merged.",
                },
            )
            for title in ("First slice", "Second slice")
        ]
        with self.database._get_connection() as conn:
            version = int(
                conn.execute(
                    "SELECT version FROM control_campaigns WHERE id = ?",
                    (campaign["id"],),
                ).fetchone()["version"]
            )
        readiness = prepare_plan_for_approval(self.store, campaign["id"])
        approved = self.store.approve_campaign(
            campaign["id"],
            expected_version=version,
            approval_sha=SHA_HEAD,
            expected_plan_signature=readiness["plan_signature"],
        )
        for candidate in candidates:
            self.store.activate_candidate(
                candidate["id"],
                approval_sha=approved["approved_sha"],
            )
        tasks = {
            task["candidate_id"]: task
            for task in self.store.list_tasks(campaign_id=campaign["id"])
        }
        first = self._authorize_merge_task(tasks[candidates[0]["id"]], pr_number=11)
        second = self._authorize_merge_task(tasks[candidates[1]["id"]], pr_number=12)
        flow = GitHubFlow(self.store, client=MergeGitHub())

        first_result = asyncio.run(flow.merge_task(first["id"]))

        self.assertFalse(first_result["campaign_completed"])
        with self.database._get_connection() as conn:
            after_first = conn.execute(
                """SELECT c.status, p.completed_at
                   FROM control_campaigns c
                   JOIN control_campaign_profiles p ON p.campaign_id = c.id
                   WHERE c.id = ?""",
                (campaign["id"],),
            ).fetchone()
        self.assertIn(after_first["status"], {"approved", "active"})
        self.assertIsNone(after_first["completed_at"])

        second_result = asyncio.run(flow.merge_task(second["id"]))

        self.assertTrue(second_result["campaign_completed"])
        overview = self.store.overview(self.project_id)
        for key in (
            "attention_open",
            "campaigns_open",
            "human_gates_open",
            "tasks_active",
            "tasks_waiting_human",
        ):
            self.assertEqual(overview["summary"][key], 0, key)

    def test_campaign_completion_is_idempotent_and_audited_once(self):
        task = self._ready_merge_task()
        result = asyncio.run(
            GitHubFlow(self.store, client=MergeGitHub()).merge_task(task["id"])
        )
        self.assertTrue(result["campaign_completed"])
        with self.database._get_connection() as conn:
            before = conn.execute(
                """SELECT completed_at FROM control_campaign_profiles
                   WHERE campaign_id = ?""",
                (task["campaign_id"],),
            ).fetchone()["completed_at"]
            audit_before = int(
                conn.execute(
                    """SELECT COUNT(*) AS count FROM control_audit_events
                       WHERE entity_type = 'campaign' AND entity_id = ?
                         AND action = 'campaign.completed'""",
                    (task["campaign_id"],),
                ).fetchone()["count"]
            )
            completed = self.store._complete_campaign_if_done(
                conn,
                task["campaign_id"],
                actor="test-repeat",
            )
            conn.commit()
            after = conn.execute(
                """SELECT completed_at FROM control_campaign_profiles
                   WHERE campaign_id = ?""",
                (task["campaign_id"],),
            ).fetchone()["completed_at"]
            audit_after = int(
                conn.execute(
                    """SELECT COUNT(*) AS count FROM control_audit_events
                       WHERE entity_type = 'campaign' AND entity_id = ?
                         AND action = 'campaign.completed'""",
                    (task["campaign_id"],),
                ).fetchone()["count"]
            )

        self.assertTrue(completed)
        self.assertEqual(after, before)
        self.assertEqual(audit_before, 1)
        self.assertEqual(audit_after, 1)

    def test_issue_followup_failure_does_not_mask_successful_merge(self):
        task = self._ready_merge_task()
        flow = GitHubFlow(
            self.store,
            client=MergeGitHub(fail_close=True),
        )
        result = asyncio.run(flow.merge_task(task["id"]))
        self.assertEqual(result["task"]["status"], "completed")
        self.assertEqual(result["task"]["merged_sha"], SHA_MERGED)
        self.assertIn("issue close failure", result["issue_close_warning"])
        overview = self.store.overview(self.project_id)
        self.assertTrue(
            any(
                item["category"] == "github_followup"
                for item in overview["attention"]
            )
        )

    def test_completed_task_sync_is_a_terminal_noop(self):
        task = self._ready_merge_task()
        github = MergeGitHub()
        flow = GitHubFlow(self.store, client=github)
        asyncio.run(flow.merge_task(task["id"]))
        self.assertEqual(github.pull_requests_read, 1)

        result = asyncio.run(flow.sync_pull_request(task["id"]))

        self.assertTrue(result["terminal_noop"])
        self.assertEqual(result["task"]["status"], "completed")
        self.assertEqual(result["task"]["merged_sha"], SHA_MERGED)
        self.assertEqual(github.pull_requests_read, 1)
        with self.database._get_connection() as conn:
            candidate = conn.execute(
                "SELECT status FROM control_pr_candidates WHERE id = ?",
                (result["task"]["candidate_id"],),
            ).fetchone()
        self.assertEqual(candidate["status"], "merged")

    def test_long_agent_wait_renews_the_task_lease(self):
        task = self._task()
        leased = self.store.lease_next_task("worker-heartbeat")
        self.assertEqual(leased["id"], task["id"])
        executor = ControlCenterExecutor(
            self.store,
            adapter=SlowTaskAdapter(),
            heartbeat_interval_seconds=0.01,
        )
        with patch.object(
            self.store,
            "heartbeat_task",
            wraps=self.store.heartbeat_task,
        ) as heartbeat:
            result = asyncio.run(
                executor._wait_for_agent_with_heartbeat(
                    task_id=leased["id"],
                    worker_id="worker-heartbeat",
                    lease_token=leased["lease_token"],
                    chat_id="slow-chat",
                    timeout_seconds=60,
                )
            )
        self.assertTrue(result["completed"])
        self.assertGreaterEqual(heartbeat.call_count, 2)
        active = self.store.get_task(task["id"])
        self.assertEqual(active["lease_owner"], "worker-heartbeat")
        self.assertEqual(active["status"], "leased")

    def test_repository_hygiene_failure_moves_existing_task_to_repair(self):
        task = self._task()
        leased = self.store.lease_next_task("hygiene-worker")
        executor = ControlCenterExecutor(self.store)

        asyncio.run(
            executor._handle_execution_error(
                task["id"],
                ControlCenterError(
                    "Unignored node_modules detected.",
                    code="repository_hygiene_violation",
                    status=409,
                ),
                "hygiene-worker",
            )
        )

        current = self.store.get_task(leased["id"])
        self.assertEqual(current["status"], "repair")
        self.assertEqual(
            current["wake_reason"],
            "retry:repository_hygiene_violation",
        )
        self.assertEqual(current["id"], task["id"])

    def test_planner_repository_mutation_fails_before_import(self):
        job = self.store.create_planning_job(
            {
                "project_id": self.project_id,
                "wish": "Plan a safe, reviewable change without modifying the repository.",
            }
        )
        claimed = self.store.claim_planning_job()
        self.assertEqual(claimed["id"], job["id"])
        adapter = PlannerAdapter()
        executor = ControlCenterExecutor(
            self.store,
            adapter=adapter,
            worktree_manager=MutatingSnapshots(),
        )
        asyncio.run(executor._execute_planning_job(claimed))
        failed = self.store.get_planning_job(job["id"])
        self.assertEqual(failed["status"], "failed")
        self.assertIn("Read-only planning modified", failed["last_error"])
        self.assertFalse(adapter.read_called)
        with self.database._get_connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS count FROM control_campaigns"
            ).fetchone()["count"]
        self.assertEqual(count, 0)

    def test_planner_rechecks_repository_read_policy_before_dispatch(self):
        job = self.store.create_planning_job(
            {
                "project_id": self.project_id,
                "wish": "Do not dispatch when repository-read permission is revoked.",
            }
        )
        claimed = self.store.claim_planning_job()
        self.store.update_repository_policy(
            self.project_id,
            {"capability": {"read_repository": False}},
        )
        adapter = PlannerAdapter()
        executor = ControlCenterExecutor(
            self.store,
            adapter=adapter,
            worktree_manager=StableSnapshots(),
        )

        asyncio.run(executor._execute_planning_job(claimed))

        failed = self.store.get_planning_job(job["id"])
        self.assertEqual(failed["status"], "failed")
        self.assertIn("nicht lesen", failed["last_error"])
        self.assertFalse(adapter.dispatched)

    def test_planner_question_keeps_session_chat_open(self):
        job = self.store.create_planning_job(
            {
                "project_id": self.project_id,
                "wish": "Clarify the outcome before creating PR slices.",
                "planning_depth": "compact",
            }
        )
        claimed = self.store.claim_planning_job()
        adapter = QuestionPlannerAdapter()
        executor = ControlCenterExecutor(
            self.store,
            adapter=adapter,
            worktree_manager=StableSnapshots(),
        )

        asyncio.run(executor._execute_planning_job(claimed))

        waiting = self.store.get_planning_job(job["id"])
        self.assertEqual(waiting["status"], "waiting_human")
        self.assertEqual(waiting["waiting_reason"], "question")
        self.assertEqual(
            waiting["antigravity_chat_id"],
            "socratic-planner-chat",
        )
        self.assertFalse(adapter.archived)

    def test_planner_persists_verified_native_project_context(self):
        self.database.update_project_integrity_link(
            self.project_id,
            str(self.root),
            "",
            "Pending native project",
        )
        job = self.store.create_planning_job(
            {
                "project_id": self.project_id,
                "wish": "Confirm the native project while planning a safe change.",
                "planning_depth": "compact",
            }
        )
        claimed = self.store.claim_planning_job()
        executor = ControlCenterExecutor(
            self.store,
            adapter=LinkedQuestionPlannerAdapter(),
            worktree_manager=StableSnapshots(),
        )

        asyncio.run(executor._execute_planning_job(claimed))

        linked = self.database.get_project(self.project_id)
        self.assertEqual(linked["integrity_project_uuid"], "confirmed-native-uuid")
        self.assertEqual(linked["integrity_workspace_path"], str(self.root))
        self.assertEqual(
            linked["antigravity_project_name"],
            "Confirmed native project",
        )

    def test_planner_repairs_invalid_json_in_the_same_attempt(self):
        job = self.store.create_planning_job(
            {
                "project_id": self.project_id,
                "wish": "Repair malformed planner JSON without changing the plan.",
                "planning_depth": "compact",
            }
        )
        claimed = self.store.claim_planning_job()
        adapter = RepairingQuestionPlannerAdapter()
        executor = ControlCenterExecutor(
            self.store,
            adapter=adapter,
            worktree_manager=StableSnapshots(),
        )

        asyncio.run(executor._execute_planning_job(claimed))

        waiting = self.store.get_planning_job(job["id"])
        self.assertEqual(waiting["status"], "waiting_human")
        self.assertEqual(waiting["waiting_reason"], "question")
        self.assertEqual(adapter.read_count, 2)
        self.assertEqual(adapter.repair_count, 1)
        self.assertEqual(adapter.repair_chat_id, "socratic-planner-chat")
        self.assertIn("missing comma", adapter.repair_error)

    def test_cancelled_planner_ignores_late_result_without_double_failure(self):
        job = self.store.create_planning_job(
            {
                "project_id": self.project_id,
                "wish": "Discard any planner result that arrives after cancellation.",
                "planning_depth": "compact",
            }
        )
        claimed = self.store.claim_planning_job()
        adapter = CancellingPlannerAdapter(self.store, job["id"])
        executor = ControlCenterExecutor(
            self.store,
            adapter=adapter,
            worktree_manager=StableSnapshots(),
        )

        asyncio.run(executor._execute_planning_job(claimed))

        current = self.store.get_planning_job(job["id"])
        self.assertEqual(current["status"], "cancelled")
        self.assertEqual(
            self.store.overview(self.project_id)["campaigns"],
            [],
        )
        self.assertFalse(adapter.archived)

    def test_cancelled_planner_releases_local_waiter_promptly(self):
        job = self.store.create_planning_job(
            {
                "project_id": self.project_id,
                "wish": "Stop the local planner waiter promptly after cancellation.",
                "planning_depth": "compact",
            }
        )
        claimed = self.store.claim_planning_job()

        async def run_cancelled_job():
            adapter = BlockingPlannerAdapter()
            executor = ControlCenterExecutor(
                self.store,
                adapter=adapter,
                worktree_manager=StableSnapshots(),
                planning_status_poll_seconds=0.01,
            )
            runner = asyncio.create_task(
                executor._execute_planning_job(claimed)
            )
            await asyncio.wait_for(adapter.started.wait(), timeout=0.5)
            await asyncio.to_thread(
                self.store.cancel_planning_job,
                job["id"],
                actor="owner",
                reason="The owner stopped this planning run.",
            )
            await asyncio.wait_for(runner, timeout=0.5)
            return adapter

        adapter = asyncio.run(run_cancelled_job())

        self.assertTrue(adapter.wait_cancelled)
        self.assertFalse(adapter.read_called)
        self.assertEqual(
            self.store.get_planning_job(job["id"])["status"],
            "cancelled",
        )


if __name__ == "__main__":
    unittest.main()
