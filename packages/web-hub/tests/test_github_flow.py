"""End-to-end state tests for task-to-GitHub materialization."""

import tempfile
import unittest
from pathlib import Path

from src.control_center import ControlCenterError, ControlCenterStore
from src.control_center.github_flow import GitHubFlow
from src.database import Database
from src.github_client import GitHubAPIError
from tests.control_center_plan_fixtures import prepare_plan_for_approval


SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40


class FakeGitHub:
    def __init__(self):
        self.created_issues = 0
        self.created_pulls = 0
        self.pull_error = None
        self.before_pull_read = None
        self.pull = {
            "number": 2,
            "html_url": "https://github.test/pull/2",
            "title": "Implement flow",
            "state": "open",
            "draft": True,
            "head_sha": SHA_B,
            "merged": False,
            "merge_commit_sha": "",
        }

    async def find_issue_by_marker(self, *_args):
        return None

    async def create_issue(self, *_args, **_kwargs):
        self.created_issues += 1
        return {"number": 1, "html_url": "https://github.test/issues/1"}

    async def find_pull_request_by_head(self, *_args):
        return None

    async def create_pull_request(self, *_args, **kwargs):
        self.created_pulls += 1
        return {
            "number": 2,
            "html_url": "https://github.test/pull/2",
            "title": kwargs["title"],
            "state": "open",
            "draft": True,
            "head_sha": SHA_B,
        }

    async def get_pull_request(self, *_args):
        if self.before_pull_read:
            callback, self.before_pull_read = self.before_pull_read, None
            callback()
        if self.pull_error:
            raise self.pull_error
        return dict(self.pull)

    async def get_check_runs(self, *_args):
        return [{"name": "unit", "status": "completed", "conclusion": "success"}]

    async def get_commit_status(self, *_args):
        return {"state": "success", "statuses": []}

    async def get_pull_request_reviews(self, *_args):
        return []

    async def get_review_comments(self, *_args):
        return []


class FakeWorktrees:
    def __init__(self, root: Path, changed=None):
        self.root = root
        self.changed = changed or ["src/control_center/executor.py"]
        self.pushed = False
        self.default_sha = SHA_A
        self.ensured_task = None
        self.hygiene_checked = False
        self.hygiene_error = None
        self.committed = False

    def default_branch_sha(self, _project, *, fetch=True):
        return self.default_sha

    def ensure_worktree(self, _project, _task):
        self.ensured_task = dict(_task)
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root

    def changed_files(self, _worktree, _base_sha):
        return list(self.changed)

    def assert_commit_hygiene(self, _worktree, *, base_sha=""):
        self.hygiene_checked = True
        self.hygiene_base_sha = base_sha
        if self.hygiene_error:
            raise self.hygiene_error

    def commit_changes(self, _worktree, _message):
        self.committed = True
        return SHA_B

    def push_branch(self, _worktree, _branch):
        self.pushed = True


class TestGitHubFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ag_github_flow_")
        root = Path(self.temp.name)
        self.database = Database(root / "control.db")
        self.project_id = self.database.add_project(
            "Flow",
            str(root / "repo"),
            github_url="https://github.com/owner/repo",
            github_owner="owner",
            github_repo="repo",
            default_branch="main",
            source_kind="github",
        )
        self.store = ControlCenterStore(
            self.database,
            sha_resolver=lambda _project: SHA_A,
        )
        campaign = self.store.create_campaign(
            {
                "project_id": self.project_id,
                "title": "Flow campaign",
                "goal": "Exercise a complete idempotent GitHub materialization flow.",
                "rollback_plan": "Revert the resulting merge commit.",
            }
        )
        candidate = self.store.create_pr_candidate(
            campaign["id"],
            {
                "title": "Implement flow",
                "scope": "Implement and verify the complete GitHub task flow.",
                "acceptance_criteria": ["The draft PR is created once."],
                "required_checks": ["unit"],
                "definition_of_done": "Exact-SHA evidence exists.",
            },
        )
        readiness = prepare_plan_for_approval(self.store, campaign["id"])
        approved = self.store.approve_campaign(
            campaign["id"],
            expected_version=2,
            approval_sha=SHA_A,
            expected_plan_signature=readiness["plan_signature"],
        )
        self.store.activate_candidate(
            candidate["id"],
            approval_sha=approved["approved_sha"],
        )
        self.task = self.store.lease_next_task("worker-1")
        self.fake_github = FakeGitHub()
        self.fake_worktrees = FakeWorktrees(root / "worktree")
        self.flow = GitHubFlow(
            self.store,
            client=self.fake_github,
            worktrees=self.fake_worktrees,
        )

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def _publish_task(self):
        await self.flow.materialize_task(
            self.task["id"],
            worker_id="worker-1",
            lease_token=self.task["lease_token"],
        )
        return await self.flow.publish_draft_pull_request(
            self.task["id"],
            worker_id="worker-1",
            lease_token=self.task["lease_token"],
        )

    async def test_materialize_and_publish_draft_releases_worker_lease(self):
        running = await self.flow.materialize_task(
            self.task["id"],
            worker_id="worker-1",
            lease_token=self.task["lease_token"],
        )
        self.assertEqual(running["status"], "running")
        self.assertEqual(running["issue_number"], 1)

        waiting = await self.flow.publish_draft_pull_request(
            self.task["id"],
            worker_id="worker-1",
            lease_token=self.task["lease_token"],
        )
        self.assertEqual(waiting["status"], "waiting_ci")
        self.assertEqual(waiting["current_sha"], SHA_B)
        self.assertEqual(waiting["lease_owner"], "")
        self.assertTrue(self.fake_worktrees.pushed)
        self.assertTrue(self.fake_worktrees.hygiene_checked)
        self.assertEqual(self.fake_worktrees.hygiene_base_sha, SHA_A)
        self.assertEqual(self.fake_github.created_issues, 1)
        self.assertEqual(self.fake_github.created_pulls, 1)

    async def test_identical_github_sync_is_audit_idempotent(self):
        await self.flow.materialize_task(
            self.task["id"],
            worker_id="worker-1",
            lease_token=self.task["lease_token"],
        )
        await self.flow.publish_draft_pull_request(
            self.task["id"],
            worker_id="worker-1",
            lease_token=self.task["lease_token"],
        )

        first = await self.flow.sync_pull_request(self.task["id"])
        self.assertEqual(first["task"]["status"], "waiting_review")
        await self.flow.sync_pull_request(self.task["id"])

        with self.database._get_connection() as conn:
            evidence_count = conn.execute(
                "SELECT COUNT(*) FROM control_evidence_items"
            ).fetchone()[0]
            audit_counts = {
                row["action"]: row["amount"]
                for row in conn.execute(
                    """SELECT action, COUNT(*) AS amount
                       FROM control_audit_events
                       WHERE action IN (
                           'evidence.recorded',
                           'evidence.evaluated',
                           'agent_task.waiting_review'
                       )
                       GROUP BY action"""
                ).fetchall()
            }

        self.assertEqual(evidence_count, 1)
        self.assertEqual(audit_counts.get("evidence.recorded"), 1)
        self.assertEqual(audit_counts.get("evidence.evaluated"), 1)
        self.assertEqual(audit_counts.get("agent_task.waiting_review"), 1)

    async def test_missing_pull_request_is_cancelled_once(self):
        await self._publish_task()
        self.fake_github.pull_error = GitHubAPIError(
            404,
            "GET",
            "/repos/owner/repo/pulls/2",
            "Not Found",
        )

        result = await self.flow.sync_pull_request(self.task["id"])
        repeated = await self.flow.sync_pull_request(self.task["id"])

        self.assertEqual(result["remote_reconciled"], "missing")
        self.assertEqual(result["task"]["status"], "cancelled")
        self.assertEqual(result["task"]["wake_reason"], "github_pr_missing")
        self.assertTrue(repeated["terminal_noop"])
        with self.database._get_connection() as conn:
            candidate_status = conn.execute(
                "SELECT status FROM control_pr_candidates WHERE id = ?",
                (self.task["candidate_id"],),
            ).fetchone()["status"]
            work_order_status = conn.execute(
                "SELECT status FROM control_work_orders WHERE id = ?",
                (self.task["work_order_id"],),
            ).fetchone()["status"]
            evidence_status = conn.execute(
                "SELECT status FROM control_evidence_packs WHERE task_id = ?",
                (self.task["id"],),
            ).fetchone()["status"]
            audit_count = conn.execute(
                """SELECT COUNT(*) AS count FROM control_audit_events
                   WHERE entity_id = ? AND action = 'agent_task.cancelled'""",
                (self.task["id"],),
            ).fetchone()["count"]
        self.assertEqual(candidate_status, "cancelled")
        self.assertEqual(work_order_status, "cancelled")
        self.assertEqual(evidence_status, "cancelled")
        self.assertEqual(audit_count, 1)

    async def test_closed_unmerged_pull_request_is_cancelled(self):
        await self._publish_task()
        self.fake_github.pull.update({"state": "closed", "merged": False})

        result = await self.flow.sync_pull_request(self.task["id"])

        self.assertEqual(result["remote_reconciled"], "closed")
        self.assertEqual(result["task"]["status"], "cancelled")
        self.assertEqual(result["task"]["wake_reason"], "github_pr_closed")

    async def test_externally_merged_pull_request_completes_local_task(self):
        await self._publish_task()
        self.fake_github.pull.update(
            {
                "state": "closed",
                "merged": True,
                "merge_commit_sha": SHA_C,
            }
        )

        result = await self.flow.sync_pull_request(self.task["id"])

        self.assertEqual(result["remote_reconciled"], "merged")
        self.assertEqual(result["task"]["status"], "completed")
        self.assertEqual(result["task"]["merged_sha"], SHA_C)
        self.assertTrue(result["campaign_completed"])
        with self.database._get_connection() as conn:
            candidate_status = conn.execute(
                "SELECT status FROM control_pr_candidates WHERE id = ?",
                (self.task["candidate_id"],),
            ).fetchone()["status"]
            campaign_status = conn.execute(
                "SELECT status FROM control_campaigns WHERE id = ?",
                (self.task["campaign_id"],),
            ).fetchone()["status"]
        self.assertEqual(candidate_status, "merged")
        self.assertEqual(campaign_status, "completed")

    async def test_transient_github_failure_preserves_waiting_state(self):
        await self._publish_task()
        self.fake_github.pull_error = ConnectionError("GitHub unavailable")

        with self.assertRaises(ConnectionError):
            await self.flow.sync_pull_request(self.task["id"])

        task = self.store.get_task(self.task["id"])
        self.assertEqual(task["status"], "waiting_ci")
        self.assertEqual(task["wake_reason"], "github_checks")

    async def test_stale_remote_terminal_response_does_not_overwrite_resume(self):
        await self._publish_task()
        self.fake_github.pull.update({"state": "closed", "merged": False})

        def resume_while_request_is_in_flight():
            with self.database._get_connection() as conn:
                conn.execute(
                    """UPDATE control_agent_tasks
                       SET status = 'queued', wake_reason = 'operator_resume'
                       WHERE id = ?""",
                    (self.task["id"],),
                )
                conn.commit()

        self.fake_github.before_pull_read = resume_while_request_is_in_flight

        result = await self.flow.sync_pull_request(self.task["id"])

        self.assertTrue(result["terminal_noop"])
        self.assertTrue(result["stale_sync_ignored"])
        task = self.store.get_task(self.task["id"])
        self.assertEqual(task["status"], "queued")
        self.assertEqual(task["wake_reason"], "operator_resume")

    async def test_sync_without_required_checks_advances_to_evidence_review(self):
        with self.database._get_connection() as conn:
            conn.execute(
                """UPDATE control_candidate_contracts
                   SET required_checks_json = '[]'
                   WHERE candidate_id = ?""",
                (self.task["candidate_id"],),
            )
            conn.commit()

        await self.flow.materialize_task(
            self.task["id"],
            worker_id="worker-1",
            lease_token=self.task["lease_token"],
        )
        waiting = await self.flow.publish_draft_pull_request(
            self.task["id"],
            worker_id="worker-1",
            lease_token=self.task["lease_token"],
        )
        self.assertEqual(waiting["status"], "waiting_ci")

        result = await self.flow.sync_pull_request(self.task["id"])

        self.assertEqual(result["task"]["status"], "waiting_review")
        self.assertEqual(result["task"]["wake_reason"], "review_and_evidence")
        self.assertEqual(result["evidence_pack"]["status"], "collecting")
        self.assertEqual(
            result["evidence_pack"]["test_pack"]["required_checks"],
            [],
        )
        self.assertIn(
            "acceptance:1",
            result["evidence_pack"]["test_pack"]["missing"],
        )

    async def test_empty_required_checks_do_not_bypass_human_gate(self):
        with self.database._get_connection() as conn:
            conn.execute(
                """UPDATE control_candidate_contracts
                   SET required_checks_json = '[]'
                   WHERE candidate_id = ?""",
                (self.task["candidate_id"],),
            )
            conn.commit()

        await self.flow.materialize_task(
            self.task["id"],
            worker_id="worker-1",
            lease_token=self.task["lease_token"],
        )
        await self.flow.publish_draft_pull_request(
            self.task["id"],
            worker_id="worker-1",
            lease_token=self.task["lease_token"],
        )
        self.store.add_evidence(
            self.task["id"],
            {
                "kind": "acceptance",
                "criterion_key": "acceptance:1",
                "title": "The draft PR is created once.",
                "status": "passed",
                "sha": SHA_B,
                "result": "verified",
            },
            actor="test",
        )
        self.store.add_evidence(
            self.task["id"],
            {
                "kind": "manual",
                "criterion_key": "manual:1",
                "title": "Verify the bounded outcome manually.",
                "status": "passed",
                "sha": SHA_B,
                "result": "verified",
            },
            actor="test",
        )

        result = await self.flow.sync_pull_request(self.task["id"])

        self.assertEqual(result["task"]["status"], "waiting_human")
        self.assertEqual(result["task"]["wake_reason"], "human_test")
        self.assertEqual(result["evidence_pack"]["status"], "ready_for_human")
        self.assertNotEqual(result["task"]["status"], "completed")

    async def test_hygiene_failure_stops_before_commit(self):
        self.fake_worktrees.hygiene_error = ControlCenterError(
            "Unignored node_modules detected.",
            code="repository_hygiene_violation",
            status=409,
        )
        await self.flow.materialize_task(
            self.task["id"],
            worker_id="worker-1",
            lease_token=self.task["lease_token"],
        )

        with self.assertRaises(ControlCenterError) as context:
            await self.flow.publish_draft_pull_request(
                self.task["id"],
                worker_id="worker-1",
                lease_token=self.task["lease_token"],
            )

        self.assertEqual(
            context.exception.code,
            "repository_hygiene_violation",
        )
        self.assertTrue(self.fake_worktrees.hygiene_checked)
        self.assertFalse(self.fake_worktrees.committed)
        self.assertFalse(self.fake_worktrees.pushed)
        self.assertEqual(self.fake_github.created_pulls, 0)

    async def test_protected_path_pauses_before_push(self):
        self.fake_worktrees.changed = [".github/workflows/release.yml"]
        await self.flow.materialize_task(
            self.task["id"],
            worker_id="worker-1",
            lease_token=self.task["lease_token"],
        )
        with self.assertRaises(ControlCenterError) as context:
            await self.flow.publish_draft_pull_request(
                self.task["id"],
                worker_id="worker-1",
                lease_token=self.task["lease_token"],
            )
        self.assertEqual(
            context.exception.code,
            "protected_path_approval_required",
        )
        paused = self.store.get_task(self.task["id"])
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(paused["current_sha"], SHA_B)
        self.assertFalse(self.fake_worktrees.pushed)
        self.store.record_human_approval(
            self.task["id"],
            approval_type="protected_path",
            sha=SHA_B,
            decision="approved",
        )
        queued = self.store.get_task(self.task["id"])
        self.assertEqual(queued["status"], "queued")
        self.assertEqual(queued["wake_reason"], "protected_path_approved")

        # Publishing an already-reviewed exact SHA is a continuation, not a new
        # agent attempt. It must remain leasable even when the repair consumed
        # the final retry budget, and leasing it must not increment the counter.
        with self.store.db._get_connection() as conn:
            conn.execute(
                """UPDATE control_agent_tasks
                   SET attempt = 4
                   WHERE id = ?""",
                (self.task["id"],),
            )
            conn.commit()

        resumed = self.store.lease_next_task("worker-2")
        self.assertIsNotNone(resumed)
        self.assertEqual(resumed["attempt"], 4)
        waiting = await self.flow.publish_draft_pull_request(
            self.task["id"],
            worker_id="worker-2",
            lease_token=resumed["lease_token"],
        )
        self.assertEqual(waiting["status"], "waiting_ci")
        self.assertTrue(self.fake_worktrees.pushed)
        self.assertFalse(
            any(
                item["category"] == "protected_path"
                for item in self.store.overview(self.project_id)["attention"]
            )
        )

    async def test_successor_wave_uses_current_default_branch_sha(self):
        self.store.transition_task(
            self.task["id"],
            to_state="cancelled",
            actor="test",
            lease_token=self.task["lease_token"],
            reason="Isolate successor-wave regression.",
        )
        self.store.update_policy(
            mode="campaign",
            paused=False,
            reason="",
            actor="test",
        )
        campaign = self.store.create_campaign(
            {
                "project_id": self.project_id,
                "title": "Successor wave",
                "goal": "Base dependent work on the latest merged default branch.",
                "rollback_plan": "Revert each merge in reverse order.",
                "activation_policy": "campaign_wave",
            }
        )
        first = self.store.create_pr_candidate(
            campaign["id"],
            {
                "title": "First dependency",
                "scope": "Create the prerequisite change for the successor wave.",
                "acceptance_criteria": ["The prerequisite is merged."],
                "required_checks": ["unit"],
                "definition_of_done": "The default branch contains the prerequisite.",
            },
        )
        second = self.store.create_pr_candidate(
            campaign["id"],
            {
                "title": "Dependent successor",
                "scope": "Build the next change on top of the merged prerequisite.",
                "acceptance_criteria": ["The successor contains the prerequisite."],
                "required_checks": ["unit"],
                "definition_of_done": "The successor starts from the current default branch.",
                "depends_on": [first["id"]],
            },
        )
        self.store.simulate_campaign(campaign["id"])
        readiness = prepare_plan_for_approval(self.store, campaign["id"])
        approved = self.store.approve_campaign(
            campaign["id"],
            expected_version=3,
            approval_sha=SHA_A,
            expected_plan_signature=readiness["plan_signature"],
        )
        self.assertEqual(approved["status"], "approved")
        first_wave = self.store.activate_ready_wave(campaign["id"])
        self.assertEqual(
            [item["candidate_id"] for item in first_wave["activated"]],
            [first["id"]],
        )
        first_task_id = first_wave["activated"][0]["task_id"]
        with self.database._get_connection() as conn:
            conn.execute(
                """UPDATE control_agent_tasks
                   SET status = 'completed', finished_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (first_task_id,),
            )
            conn.execute(
                """UPDATE control_pr_candidates
                   SET status = 'merged', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (first["id"],),
            )
            conn.commit()

        second_wave = self.store.activate_ready_wave(campaign["id"])
        self.assertEqual(
            [item["candidate_id"] for item in second_wave["activated"]],
            [second["id"]],
        )
        successor = self.store.lease_next_task("successor-worker")
        self.fake_worktrees.default_sha = SHA_B
        flow = GitHubFlow(
            self.store,
            client=self.fake_github,
            worktrees=self.fake_worktrees,
        )
        materialized = await flow.materialize_task(
            successor["id"],
            worker_id="successor-worker",
            lease_token=successor["lease_token"],
        )

        self.assertEqual(materialized["base_sha"], SHA_B)
        self.assertEqual(self.fake_worktrees.ensured_task["base_sha"], SHA_B)
        with self.database._get_connection() as conn:
            candidate = conn.execute(
                "SELECT base_sha FROM control_pr_candidates WHERE id = ?",
                (second["id"],),
            ).fetchone()
            work_order = conn.execute(
                "SELECT approval_sha FROM control_work_orders WHERE candidate_id = ?",
                (second["id"],),
            ).fetchone()
        self.assertEqual(candidate["base_sha"], SHA_B)
        self.assertEqual(work_order["approval_sha"], SHA_B)


if __name__ == "__main__":
    unittest.main()
