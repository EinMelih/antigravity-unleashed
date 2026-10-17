import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from src.control_center import ControlCenterStore
from src.database import Database
from src.project_archiving import ProjectArchiver
from src.project_handlers import (
    handle_delete_project,
    handle_delete_project_github_repository,
    handle_project_removal_impact,
    handle_restore_project,
)


def seed_project(database: Database, root: Path) -> int:
    project_id = database.add_project(
        "archive-me",
        str(root),
        github_url="https://github.com/example/archive-me",
        github_owner="example",
        github_repo="archive-me",
        source_kind="github",
    )
    issue_id = database.add_issue(project_id, "Issue", "Description")
    database.create_agent_run(issue_id, status="running")
    database.add_subtask(issue_id, "Subtask")
    store = ControlCenterStore(database)
    with database._get_connection() as conn:
        conn.execute(
            """INSERT INTO control_campaigns
               (id, project_id, title, goal, status)
               VALUES ('CAM-1', ?, 'Campaign', 'Goal', 'active')""",
            (project_id,),
        )
        conn.execute(
            """INSERT INTO control_pr_candidates
               (id, campaign_id, title, scope, acceptance_criteria_json,
                status, base_sha)
               VALUES ('PRC-1', 'CAM-1', 'Candidate', 'Scope', '["ok"]',
                       'approved', 'abcdef1')"""
        )
        conn.execute(
            """INSERT INTO control_work_orders
               (id, candidate_id, status, approval_sha, approved_by)
               VALUES ('WO-1', 'PRC-1', 'approved', 'abcdef1', 'human')"""
        )
        conn.execute(
            """INSERT INTO control_agent_tasks
               (id, work_order_id, project_id, campaign_id, candidate_id,
                status, base_sha, branch_name, antigravity_chat_id, pr_number)
               VALUES ('TASK-1', 'WO-1', ?, 'CAM-1', 'PRC-1', 'running',
                       'abcdef1', 'feature/test', 'native-chat', 42)""",
            (project_id,),
        )
        conn.execute(
            """INSERT INTO control_evidence_packs
               (id, task_id, project_id, candidate_id, status)
               VALUES ('EV-1', 'TASK-1', ?, 'PRC-1', 'collecting')""",
            (project_id,),
        )
        conn.execute(
            """INSERT INTO control_attention_items
               (id, project_id, category, entity_type, entity_id, title)
               VALUES ('ATT-1', ?, 'agent_permission', 'agent_task',
                       'TASK-1', 'Attention')""",
            (project_id,),
        )
        conn.execute(
            """INSERT INTO control_idea_seeds
               (id, project_id, title, note, status)
               VALUES ('IDEA-1', ?, 'Idea', 'Note', 'planning')""",
            (project_id,),
        )
        conn.execute(
            """INSERT INTO control_planning_jobs
               (id, project_id, idea_seed_id, status, planning_depth,
                max_candidates, activation_policy, wish)
               VALUES ('PLAN-1', ?, 'IDEA-1', 'running', 'balanced', 3,
                       'per_candidate', 'Plan this project')""",
            (project_id,),
        )
        conn.execute(
            """INSERT INTO control_deployments
               (id, project_id, environment, status, sha)
               VALUES ('DEP-1', ?, 'preview', 'running', 'abcdef1')""",
            (project_id,),
        )
        conn.execute(
            """INSERT INTO proxy_conversations (id, project_id, title)
               VALUES ('CHAT-1', ?, 'Chat')""",
            (project_id,),
        )
        conn.commit()
    return project_id


class ProjectArchiverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.marker = self.root / "keep.txt"
        self.marker.write_text("keep", encoding="utf-8")
        self.db = Database(Path(self.temp.name) / "hub.db")
        self.project_id = seed_project(self.db, self.root)
        self.archiver = ProjectArchiver(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_impact_and_archive_preserve_data_but_terminalize_active_state(self):
        impact = self.archiver.impact(self.project_id)
        self.assertEqual(impact["dependencies"]["issues"]["total"], 1)
        self.assertEqual(impact["dependencies"]["tasks"]["active"], 1)
        self.assertEqual(
            impact["dependencies"]["pr_candidates"]["with_pull_request"], 1
        )
        self.assertEqual(impact["dependencies"]["proxy_chats"]["total"], 1)
        self.assertEqual(
            impact["retention"]["local_project_directory"], "preserved"
        )

        result = self.archiver.archive(self.project_id)
        self.assertTrue(result["archived"])
        self.assertTrue(self.marker.exists())
        self.assertEqual(self.db.get_projects(), [])
        self.assertIsNone(self.db.get_project(self.project_id))
        archived = self.db.get_project(self.project_id, include_archived=True)
        self.assertIsNotNone(archived["archived_at"])
        self.assertEqual(self.db.get_issues(), [])

        with self.db._get_connection() as conn:
            expectations = (
                ("control_agent_tasks", "cancelled"),
                ("control_pr_candidates", "cancelled"),
                ("control_work_orders", "cancelled"),
                ("control_campaigns", "cancelled"),
                ("control_planning_jobs", "cancelled"),
                ("control_deployments", "cancelled"),
                ("control_evidence_packs", "cancelled"),
            )
            for table, expected in expectations:
                status = conn.execute(f"SELECT status FROM {table}").fetchone()[0]
                self.assertEqual(status, expected, table)
            attention = conn.execute(
                "SELECT status FROM control_attention_items"
            ).fetchone()[0]
            self.assertEqual(attention, "resolved")
            self.assertEqual(
                conn.execute(
                    "SELECT status FROM control_idea_seeds"
                ).fetchone()[0],
                "inbox",
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0], 1
            )

        store = ControlCenterStore(self.db)
        self.assertEqual(store.overview()["campaigns"], [])
        self.assertEqual(store.list_tasks(), [])

        repeated = self.archiver.archive(self.project_id)
        self.assertTrue(repeated["already_archived"])
        self.assertEqual(repeated["transitions"], {})

    def test_restore_returns_project_to_standard_lists_without_restarting_work(self):
        self.archiver.archive(self.project_id)
        restored = self.archiver.restore(self.project_id)
        self.assertTrue(restored["restored"])
        self.assertIsNone(restored["project"]["archived_at"])
        self.assertEqual(len(self.db.get_projects()), 1)
        with self.db._get_connection() as conn:
            self.assertEqual(
                conn.execute("SELECT status FROM control_agent_tasks").fetchone()[0],
                "cancelled",
            )


class ProjectArchiveApiTests(AioHTTPTestCase):
    async def get_application(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.db = Database(Path(self.temp.name) / "hub.db")
        self.project_id = seed_project(self.db, self.root)
        self.db_patch = patch("src.project_handlers.db", self.db)
        self.db_patch.start()
        app = web.Application()
        app.router.add_get(
            "/api/projects/{id}/removal-impact",
            handle_project_removal_impact,
        )
        app.router.add_delete("/api/projects/{id}", handle_delete_project)
        app.router.add_post("/api/projects/{id}/restore", handle_restore_project)
        app.router.add_delete(
            "/api/projects/{id}/github-repository",
            handle_delete_project_github_repository,
        )
        return app

    async def asyncTearDown(self):
        await super().asyncTearDown()
        self.db_patch.stop()
        self.temp.cleanup()

    async def test_api_security_remote_delete_contract_archive_and_restore(self):
        impact = await self.client.get(
            f"/api/projects/{self.project_id}/removal-impact"
        )
        self.assertEqual(impact.status, 200)
        self.assertEqual((await impact.json())["project"]["name"], "archive-me")

        external = await self.client.delete(
            f"/api/projects/{self.project_id}",
            headers={"Origin": "https://untrusted.example"},
        )
        self.assertEqual(external.status, 403)
        self.assertIsNotNone(self.db.get_project(self.project_id))

        remote = await self.client.delete(
            f"/api/projects/{self.project_id}",
            json={"delete_remote_repository": True},
            headers={"Origin": "http://127.0.0.1:8000"},
        )
        self.assertEqual(remote.status, 409)
        remote_payload = await remote.json()
        self.assertFalse(remote_payload["remote_action_performed"])
        self.assertIsNotNone(self.db.get_project(self.project_id))

        archived = await self.client.delete(
            f"/api/projects/{self.project_id}",
            json={"mode": "hub_only"},
            headers={"Origin": "http://127.0.0.1:8000"},
        )
        self.assertEqual(archived.status, 200)
        self.assertTrue((await archived.json())["archived"])

        restored = await self.client.post(
            f"/api/projects/{self.project_id}/restore",
            headers={"Origin": "http://127.0.0.1:8000"},
        )
        self.assertEqual(restored.status, 200)
        self.assertTrue((await restored.json())["restored"])

    async def test_remote_delete_requires_exact_identity_and_calls_only_linked_repo(self):
        client = SimpleNamespace(
            get_repository=AsyncMock(return_value={"full_name": "example/archive-me"}),
            delete_repo=AsyncMock(return_value=True),
        )
        with (
            patch("src.project_handlers.config", SimpleNamespace(github_token="token")),
            patch("src.github_client.GitHubClient", return_value=client),
        ):
            mismatch = await self.client.delete(
                f"/api/projects/{self.project_id}/github-repository",
                json={"confirm": True, "repository": "example/other"},
                headers={"Origin": "http://127.0.0.1:8000"},
            )
            self.assertEqual(mismatch.status, 400)
            client.delete_repo.assert_not_awaited()

            deleted = await self.client.delete(
                f"/api/projects/{self.project_id}/github-repository",
                json={"confirm": True, "repository": "example/archive-me"},
                headers={"Origin": "http://127.0.0.1:8000"},
            )
        self.assertEqual(deleted.status, 200, await deleted.text())
        client.get_repository.assert_awaited_once_with("example", "archive-me")
        client.delete_repo.assert_awaited_once_with("example", "archive-me")


if __name__ == "__main__":
    unittest.main()
