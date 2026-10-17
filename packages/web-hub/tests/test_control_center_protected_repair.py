"""Safety tests for rejecting unpublished protected-path task commits."""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.control_center import ControlCenterError, ControlCenterStore
from src.control_center.github_flow import GitHubFlow
from src.control_center.worktrees import WorktreeManager
from src.control_center_handlers import handle_reject_protected_path
from src.database import Database
from tests.control_center_plan_fixtures import prepare_plan_for_approval


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


class RejectGitHub:
    def __init__(self) -> None:
        self.remote_ref = None
        self.pull = None

    async def get_ref(self, *_args):
        return self.remote_ref

    async def find_pull_request_by_head(self, *_args):
        return self.pull


class ProtectedRepairFixture(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ag_protected_repair_")
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Test User")
        git(self.repo, "config", "user.email", "test@example.invalid")
        git(
            self.repo,
            "remote",
            "add",
            "origin",
            "https://github.com/owner/repo.git",
        )
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "base")
        self.base_sha = git(self.repo, "rev-parse", "HEAD").lower()

        self.database = Database(self.root / "control.db")
        self.project_id = self.database.add_project(
            "Protected repair",
            str(self.repo),
            github_url="https://github.com/owner/repo",
            github_owner="owner",
            github_repo="repo",
            default_branch="main",
            source_kind="github",
        )
        self.store = ControlCenterStore(
            self.database,
            sha_resolver=lambda _project: self.base_sha,
        )
        campaign = self.store.create_campaign(
            {
                "project_id": self.project_id,
                "title": "Protected repair campaign",
                "goal": "Safely reject one unpublished protected-path commit.",
                "rollback_plan": "Reset the isolated task branch to its base SHA.",
            }
        )
        candidate = self.store.create_pr_candidate(
            campaign["id"],
            {
                "title": "Add protected workflow",
                "scope": "Add one workflow and verify protected-path rejection.",
                "acceptance_criteria": ["The rejected file remains available for repair."],
                "required_checks": ["unit"],
                "definition_of_done": "The local task commit is explicitly reviewed.",
            },
        )
        readiness = prepare_plan_for_approval(self.store, campaign["id"])
        approved = self.store.approve_campaign(
            campaign["id"],
            expected_version=2,
            approval_sha=self.base_sha,
            expected_plan_signature=readiness["plan_signature"],
        )
        self.store.activate_candidate(
            candidate["id"],
            approval_sha=approved["approved_sha"],
        )
        self.leased = self.store.lease_next_task("protected-worker")
        self.worktrees = WorktreeManager()
        project = self.database.get_project(self.project_id)
        self.worktree = self.worktrees.ensure_worktree(
            project,
            self.leased,
            fetch=False,
        )
        self.store.transition_task(
            self.leased["id"],
            to_state="running",
            actor="protected-worker",
            lease_token=self.leased["lease_token"],
            reason="Materialized isolated worktree.",
            fields={
                "issue_number": 7,
                "issue_url": "https://github.test/issues/7",
                "worktree_path": str(self.worktree),
                "wake_reason": "agent_execution",
            },
        )
        workflow = self.worktree / ".github" / "workflows" / "check.yml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text("name: check\n", encoding="utf-8")
        self.github = RejectGitHub()
        self.flow = GitHubFlow(
            self.store,
            client=self.github,
            worktrees=self.worktrees,
        )
        with self.assertRaises(ControlCenterError) as raised:
            await self.flow.publish_draft_pull_request(
                self.leased["id"],
                worker_id="protected-worker",
                lease_token=self.leased["lease_token"],
            )
        self.assertEqual(
            raised.exception.code,
            "protected_path_approval_required",
        )
        self.paused = self.store.get_task(self.leased["id"])
        tracked_dependency = self.worktree / "node_modules" / "cache.bin"
        tracked_dependency.parent.mkdir()
        tracked_dependency.write_bytes(b"tracked-in-rejected-head")
        git(self.worktree, "add", "-f", "node_modules/cache.bin")
        git(self.worktree, "commit", "--amend", "--no-edit")
        self.rejected_sha = git(self.worktree, "rev-parse", "HEAD").lower()
        with self.database._get_connection() as conn:
            conn.execute(
                """UPDATE control_agent_tasks
                   SET current_sha = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (self.rejected_sha, self.leased["id"]),
            )
            conn.commit()
        self.paused = self.store.get_task(self.leased["id"])
        self.assertEqual(
            git(self.worktree, "ls-files", "node_modules/cache.bin"),
            "node_modules/cache.bin",
        )

    async def asyncTearDown(self) -> None:
        self.temp.cleanup()

    async def test_reject_rewinds_history_preserves_files_and_audits(self):
        (self.worktree / ".gitignore").write_text(
            "node_modules/\n",
            encoding="utf-8",
        )
        (self.worktree / "package-lock.json").write_text(
            '{"lockfileVersion": 3}\n',
            encoding="utf-8",
        )
        ignored_dependency = self.worktree / "node_modules" / "cache.bin"
        ignored_dependency.parent.mkdir(exist_ok=True)
        ignored_dependency.write_bytes(b"do-not-stage")

        result = await self.flow.reject_protected_path_for_repair(
            self.leased["id"],
            sha=self.rejected_sha,
            actor="security-reviewer",
            reason="Workflow permissions are too broad.",
        )

        task = result["task"]
        self.assertEqual(task["status"], "repair")
        self.assertEqual(task["wake_reason"], "protected_path_rejected")
        self.assertEqual(task["current_sha"], "")
        self.assertEqual(git(self.worktree, "rev-parse", "HEAD"), self.base_sha)
        workflow = self.worktree / ".github" / "workflows" / "check.yml"
        self.assertEqual(workflow.read_text(encoding="utf-8"), "name: check\n")
        status = git(self.worktree, "status", "--short")
        self.assertIn("?? .github/", status)
        self.assertIn("?? .gitignore", status)
        self.assertIn("?? package-lock.json", status)
        self.assertNotIn("node_modules", status)
        self.assertEqual(ignored_dependency.read_bytes(), b"do-not-stage")
        self.assertEqual(result["approval"]["decision"], "rejected")
        self.assertEqual(result["approval"]["sha"], self.rejected_sha)
        self.assertIn(".gitignore", result["rewind"]["changed_files"])
        self.assertIn("package-lock.json", result["rewind"]["changed_files"])
        self.assertFalse(
            any(
                path.startswith("node_modules")
                for path in result["rewind"]["changed_files"]
            )
        )
        self.assertGreaterEqual(
            result["rewind"]["excluded_generated_count"],
            1,
        )
        self.assertIn(
            "node_modules/cache.bin",
            result["rewind"]["excluded_generated_sample"],
        )
        self.assertFalse(
            any(
                item["category"] == "protected_path"
                for item in self.store.overview(self.project_id)["attention"]
            )
        )

        with self.database._get_connection() as conn:
            approval = conn.execute(
                """SELECT * FROM control_human_approvals
                   WHERE entity_id = ? AND approval_type = 'protected_path'
                   ORDER BY created_at DESC LIMIT 1""",
                (self.leased["id"],),
            ).fetchone()
            audit = conn.execute(
                """SELECT * FROM control_audit_events
                   WHERE entity_id = ?
                     AND action = 'protected_path.rejected_for_repair'
                   ORDER BY created_at DESC LIMIT 1""",
                (self.leased["id"],),
            ).fetchone()
        self.assertEqual(approval["decision"], "rejected")
        self.assertEqual(approval["sha"], self.rejected_sha)
        self.assertIn("permissions are too broad", audit["reason"])
        audit_evidence = json.loads(audit["evidence_json"])
        self.assertEqual(audit_evidence["old_sha"], self.rejected_sha)
        self.assertEqual(audit_evidence["base_sha"], self.base_sha)
        self.assertEqual(
            audit_evidence["overlay_tree"],
            result["rewind"]["overlay_tree"],
        )

    async def test_persistence_failure_restores_head_and_overlay(self):
        (self.worktree / ".gitignore").write_text(
            "node_modules/\n",
            encoding="utf-8",
        )
        (self.worktree / "package-lock.json").write_text(
            '{"lockfileVersion": 3}\n',
            encoding="utf-8",
        )
        ignored_dependency = self.worktree / "node_modules" / "cache.bin"
        ignored_dependency.parent.mkdir(exist_ok=True)
        ignored_dependency.write_bytes(b"still-present")

        with patch.object(
            self.store,
            "_audit",
            side_effect=RuntimeError("simulated audit persistence failure"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "simulated audit persistence failure",
            ):
                await self.flow.reject_protected_path_for_repair(
                    self.leased["id"],
                    sha=self.rejected_sha,
                    actor="security-reviewer",
                    reason="Force compensation coverage.",
                )

        self.assertEqual(git(self.worktree, "rev-parse", "HEAD"), self.rejected_sha)
        self.assertEqual(
            (self.worktree / "package-lock.json").read_text(encoding="utf-8"),
            '{"lockfileVersion": 3}\n',
        )
        self.assertEqual(ignored_dependency.read_bytes(), b"still-present")
        status = git(self.worktree, "status", "--short")
        self.assertIn("?? .gitignore", status)
        self.assertIn("?? package-lock.json", status)
        self.assertIn("M node_modules/cache.bin", status)
        task = self.store.get_task(self.leased["id"])
        self.assertEqual(task["status"], "paused")
        self.assertEqual(task["wake_reason"], "protected_path_approval")
        self.assertEqual(task["current_sha"], self.rejected_sha)
        self.assertTrue(
            any(
                item["category"] == "protected_path"
                for item in self.store.overview(self.project_id)["attention"]
            )
        )

    async def test_reject_requires_exact_current_sha(self):
        with self.assertRaises(ControlCenterError) as raised:
            await self.flow.reject_protected_path_for_repair(
                self.leased["id"],
                sha="f" * 40,
                actor="reviewer",
                reason="Wrong SHA must fail closed.",
            )
        self.assertEqual(raised.exception.code, "approval_sha_mismatch")
        self.assertEqual(git(self.worktree, "rev-parse", "HEAD"), self.rejected_sha)

    async def test_reject_refuses_published_branch(self):
        self.github.remote_ref = {
            "ref": f"refs/heads/{self.paused['branch_name']}",
            "sha": self.rejected_sha,
        }
        with self.assertRaises(ControlCenterError) as raised:
            await self.flow.reject_protected_path_for_repair(
                self.leased["id"],
                sha=self.rejected_sha,
                actor="reviewer",
                reason="Published branches must fail closed.",
            )
        self.assertEqual(
            raised.exception.code,
            "protected_repair_branch_published",
        )
        self.assertEqual(git(self.worktree, "rev-parse", "HEAD"), self.rejected_sha)

    async def test_reject_refuses_existing_pull_request(self):
        self.github.pull = {"number": 9, "head_sha": self.rejected_sha}
        with self.assertRaises(ControlCenterError) as raised:
            await self.flow.reject_protected_path_for_repair(
                self.leased["id"],
                sha=self.rejected_sha,
                actor="reviewer",
                reason="Existing pull requests must fail closed.",
            )
        self.assertEqual(
            raised.exception.code,
            "protected_repair_pull_request_exists",
        )
        self.assertEqual(git(self.worktree, "rev-parse", "HEAD"), self.rejected_sha)


class TestProtectedRepairEndpoint(unittest.IsolatedAsyncioTestCase):
    async def test_endpoint_forwards_exact_sha_actor_and_reason(self):
        calls = []

        class FakeStore:
            @staticmethod
            def get_idempotent(_key, _operation):
                return None

            @staticmethod
            def remember_idempotent(_key, _operation, _response):
                return None

        class FakeFlow:
            def __init__(self, store):
                self.store = store

            async def reject_protected_path_for_repair(self, task_id, **kwargs):
                calls.append((task_id, kwargs))
                return {"task": {"id": task_id, "status": "repair"}}

        app = web.Application()
        app.router.add_post(
            "/api/control-center/tasks/{task_id}/protected-path/reject",
            handle_reject_protected_path,
        )
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            with (
                patch("src.control_center_handlers.control_center", FakeStore()),
                patch("src.control_center_handlers.GitHubFlow", FakeFlow),
            ):
                response = await client.post(
                    "/api/control-center/tasks/TASK-ONE/protected-path/reject",
                    json={
                        "sha": "a" * 40,
                        "actor": "reviewer",
                        "reason": "Unsafe workflow permissions.",
                    },
                    headers={"Idempotency-Key": "reject-task-one"},
                )
                payload = await response.json()
        finally:
            await client.close()

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["repair"]["task"]["status"], "repair")
        self.assertEqual(
            calls,
            [
                (
                    "TASK-ONE",
                    {
                        "sha": "a" * 40,
                        "actor": "reviewer",
                        "reason": "Unsafe workflow permissions.",
                    },
                )
            ],
        )

    def test_dashboard_exposes_reject_and_repair_action(self):
        source = (
            Path(__file__).parents[1] / "dashboard" / "js" / "control-center.js"
        ).read_text(encoding="utf-8")
        self.assertIn("Ablehnen &amp; reparieren", source)
        self.assertIn("rejectProtectedPathForRepair", source)
        self.assertIn("/protected-path/reject", source)


class TestRetryLeaseBudget(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ag_retry_budget_")
        root = Path(self.temp.name)
        self.database = Database(root / "control.db")
        self.project_id = self.database.add_project(
            "Retry budget",
            str(root / "repo"),
            github_url="https://github.com/owner/repo",
            github_owner="owner",
            github_repo="repo",
            default_branch="main",
            source_kind="github",
        )
        self.store = ControlCenterStore(
            self.database,
            sha_resolver=lambda _project: "a" * 40,
        )
        campaign = self.store.create_campaign(
            {
                "project_id": self.project_id,
                "title": "Retry budget campaign",
                "goal": "Prove that normal retries cannot exceed their budget.",
                "rollback_plan": "Cancel the isolated task.",
            }
        )
        candidate = self.store.create_pr_candidate(
            campaign["id"],
            {
                "title": "Bound retries",
                "scope": "Exercise lease budget enforcement.",
                "acceptance_criteria": ["Attempts above the limit are not leased."],
                "required_checks": ["unit"],
                "definition_of_done": "The retry budget is enforced atomically.",
            },
        )
        readiness = prepare_plan_for_approval(self.store, campaign["id"])
        approved = self.store.approve_campaign(
            campaign["id"],
            expected_version=2,
            approval_sha="a" * 40,
            expected_plan_signature=readiness["plan_signature"],
        )
        self.store.activate_candidate(
            candidate["id"],
            approval_sha=approved["approved_sha"],
        )
        self.task_id = self.store.list_tasks(project_id=self.project_id)[0]["id"]
        current = self.store.get_repository_policy(self.project_id)
        self.store.update_repository_policy(
            self.project_id,
            {
                **current,
                "max_retry_attempts": 1,
            },
            actor="test",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _set_retry_state(
        self,
        attempt: int,
        wake_reason: str = "retry:executor_failure",
    ) -> None:
        with self.database._get_connection() as conn:
            conn.execute(
                """UPDATE control_agent_tasks
                   SET status = 'repair', wake_reason = ?,
                       attempt = ?, lease_owner = '', lease_token = '',
                       lease_until = NULL
                   WHERE id = ?""",
                (wake_reason, attempt, self.task_id),
            )
            conn.commit()

    def test_normal_lease_is_blocked_above_retry_budget(self):
        self._set_retry_state(2)
        self.assertIsNone(self.store.lease_next_task("over-budget-worker"))
        self.assertEqual(self.store.get_task(self.task_id)["attempt"], 2)

    def test_last_budgeted_retry_is_allowed(self):
        self._set_retry_state(1)
        leased = self.store.lease_next_task("last-budgeted-worker")
        self.assertEqual(leased["id"], self.task_id)
        self.assertEqual(leased["attempt"], 2)

    def test_operator_resume_refund_restores_lease_eligibility(self):
        self._set_retry_state(2)
        self.store.update_policy(
            mode="guided",
            paused=True,
            reason="Operator is applying an infrastructure fix.",
            actor="operator",
        )
        resumed = self.store.resume_task_after_operator_fix(
            self.task_id,
            actor="operator",
            reason="The infrastructure defect is fixed.",
        )
        self.assertEqual(resumed["attempt"], 1)
        self.store.update_policy(
            mode="guided",
            paused=False,
            reason="",
            actor="operator",
        )
        leased = self.store.lease_next_task("refunded-worker")
        self.assertEqual(leased["id"], self.task_id)
        self.assertEqual(leased["attempt"], 1)

    def test_protected_rejection_refunds_once_then_leases_at_exact_budget(self):
        current = self.store.get_repository_policy(self.project_id)
        self.store.update_repository_policy(
            self.project_id,
            {
                **current,
                "max_retry_attempts": 3,
            },
            actor="test",
        )
        self._set_retry_state(4, "protected_path_rejected")
        self.assertIsNone(self.store.lease_next_task("blocked-before-refund"))
        self.store.update_policy(
            mode="guided",
            paused=True,
            reason="Operator reviews a rejected protected-path task.",
            actor="operator",
        )
        resumed = self.store.resume_task_after_operator_fix(
            self.task_id,
            actor="operator",
            reason="Rejected protected changes are ready for a bounded repair.",
        )
        self.assertEqual(resumed["attempt"], 3)
        replay = self.store.resume_task_after_operator_fix(
            self.task_id,
            actor="operator",
            reason="Idempotent replay must not refund twice.",
        )
        self.assertEqual(replay["attempt"], 3)
        self.store.update_policy(
            mode="guided",
            paused=False,
            reason="",
            actor="operator",
        )
        leased = self.store.lease_next_task("protected-refund-worker")
        self.assertEqual(leased["id"], self.task_id)
        self.assertEqual(leased["attempt"], 3)


if __name__ == "__main__":
    unittest.main()
