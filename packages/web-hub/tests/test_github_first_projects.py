import subprocess
import tempfile
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.database import Database
from src.project_handlers import handle_github_status
from src.project_manager import ProjectManager, git_has_commit, git_init


class TestGithubFirstProjectRegistry(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _git(path: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=path,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_git_init_creates_bootstrap_commit_without_user_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = root / "bootstrap"
            repository.mkdir()
            empty_global_config = root / "empty-gitconfig"
            empty_global_config.write_text("", encoding="utf-8")

            with patch.dict(
                "os.environ",
                {"GIT_CONFIG_GLOBAL": str(empty_global_config)},
            ):
                self.assertTrue(git_init(str(repository)))

            self.assertTrue(git_has_commit(str(repository)))
            identity = self._git(
                repository,
                "show",
                "-s",
                "--format=%an|%ae|%s",
                "HEAD",
            ).stdout.strip()
            self.assertEqual(
                identity,
                "Anti-Gravity Hub|antigravity-hub@localhost|"
                "Initial commit from Anti-Gravity Hub",
            )

    async def test_github_status_validates_authenticated_user(self):
        fake_config = SimpleNamespace(
            github_configured=True,
            github_token="test-token",
            github_owner="configured-owner",
            projects_base_dir="D:\\Projects",
        )
        fake_client = SimpleNamespace(
            check_token=AsyncMock(return_value={"login": "verified-owner"})
        )
        with patch("src.project_handlers.config", fake_config), patch(
            "src.project_handlers.GitHubClient",
            return_value=fake_client,
        ):
            response = await handle_github_status(None)
        payload = json.loads(response.text)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["status"], "valid")
        self.assertEqual(payload["owner"], "verified-owner")

    async def test_github_status_exposes_invalid_credentials_without_secret(self):
        fake_config = SimpleNamespace(
            github_configured=True,
            github_token="secret-token",
            github_owner="configured-owner",
            projects_base_dir="D:\\Projects",
        )
        fake_client = SimpleNamespace(
            check_token=AsyncMock(
                side_effect=RuntimeError(
                    "GitHub API error 401 on GET /user: Bad credentials"
                )
            )
        )
        with patch("src.project_handlers.config", fake_config), patch(
            "src.project_handlers.GitHubClient",
            return_value=fake_client,
        ):
            response = await handle_github_status(None)
        payload = json.loads(response.text)
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["status"], "invalid")
        self.assertNotIn("secret-token", response.text)

    async def test_new_github_project_pushes_verified_local_bootstrap(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            remote = root / "remote.git"
            subprocess.run(
                ["git", "init", "--bare", str(remote)],
                check=True,
                capture_output=True,
            )
            database = Database(root / "hub-test.db")
            fake_config = SimpleNamespace(
                projects_base_dir=str(root),
                github_configured=True,
                github_token="test-token",
                github_owner="configured-owner",
                default_repo_visibility="private",
            )
            fake_client = SimpleNamespace(
                create_repo=AsyncMock(
                    return_value={
                        "full_name": "api-owner/new-project",
                        "html_url": "https://github.com/api-owner/new-project",
                        "clone_url": str(remote),
                        "default_branch": "main",
                    }
                ),
                ensure_labels=AsyncMock(),
            )

            with patch("src.project_manager.db", database), patch(
                "src.project_manager.config",
                fake_config,
            ), patch(
                "src.github_client.GitHubClient",
            ) as github_client_class:
                github_client_class.slugify.return_value = "new-project"
                github_client_class.return_value = fake_client
                created = await ProjectManager.register_project(
                    "New Project",
                    custom_path=str(root / "new-project"),
                    create_github=True,
                )

            fake_client.create_repo.assert_awaited_once_with(
                "new-project",
                description="Antigravity-managed project: New Project",
                private=True,
                auto_init=False,
            )
            self.assertEqual(created["github_owner"], "api-owner")
            self.assertEqual(created["github_setup_status"], "ready")
            remote_head = subprocess.run(
                ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/main"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertTrue(remote_head)

    async def test_reconcile_adopts_remote_branch_for_unborn_local_repo(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            remote = root / "remote.git"
            seed = root / "seed"
            local = root / "local"
            subprocess.run(
                ["git", "init", "--bare", str(remote)],
                check=True,
                capture_output=True,
            )
            seed.mkdir()
            self._git(seed, "init", "-b", "main")
            (seed / "README.md").write_text("# Remote bootstrap\n", encoding="utf-8")
            self._git(seed, "add", "README.md")
            self._git(
                seed,
                "-c",
                "user.name=Remote Bootstrap",
                "-c",
                "user.email=remote@example.invalid",
                "commit",
                "-m",
                "Remote bootstrap",
            )
            self._git(seed, "remote", "add", "origin", str(remote))
            self._git(seed, "push", "-u", "origin", "main")

            local.mkdir()
            self._git(local, "init", "-b", "main")
            self._git(local, "remote", "add", "origin", str(remote))

            database = Database(root / "hub-test.db")
            project_id = database.add_project(
                "Legacy Partial",
                str(local),
                github_url="https://github.com/api-owner/legacy-partial",
                github_owner="api-owner",
                github_repo="legacy-partial",
                default_branch="main",
                source_kind="github",
            )
            database.update_project_github_setup(
                project_id,
                "repair_required",
                "old initial push failed",
            )
            fake_config = SimpleNamespace(
                github_configured=True,
                github_token="test-token",
            )
            fake_client = SimpleNamespace(
                get_repository=AsyncMock(
                    return_value={
                        "html_url": "https://github.com/api-owner/legacy-partial",
                        "clone_url": str(remote),
                        "default_branch": "main",
                    }
                ),
                ensure_labels=AsyncMock(),
            )

            with patch("src.project_manager.db", database), patch(
                "src.project_manager.config",
                fake_config,
            ), patch(
                "src.github_client.GitHubClient",
                return_value=fake_client,
            ):
                repaired = await ProjectManager.reconcile_github_repository(
                    project_id
                )

            local_head = self._git(local, "rev-parse", "HEAD").stdout.strip()
            remote_head = subprocess.run(
                ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/main"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertEqual(local_head, remote_head)
            self.assertEqual(repaired["github_setup_status"], "ready")
            self.assertFalse(repaired["github_bootstrap_required"])

    async def test_explicit_hub_project_is_visible_without_legacy_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = Database(root / "hub-test.db")
            database.add_project("old-auto-entry", str(root / "old"))

            with patch("src.project_manager.db", database):
                created = await ProjectManager.register_project(
                    "New Hub Project",
                    custom_path=str(root / "New Hub Project"),
                    create_github=False,
                )
                visible = ProjectManager.get_projects()

            self.assertEqual(created["source_kind"], "hub")
            self.assertEqual([project["name"] for project in visible], ["New Hub Project"])

    async def test_legacy_projects_stay_hidden_until_explicit_github_import(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_path = root / "example-repo"
            repo_path.mkdir()
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "remote", "add", "origin", "https://github.com/EinMelih/example-repo.git"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

            database = Database(root / "hub-test.db")
            legacy_id = database.add_project(
                "example-repo",
                str(repo_path),
                github_url="https://github.com/EinMelih/example-repo",
                github_owner="EinMelih",
                github_repo="example-repo",
                default_branch="main",
            )

            with patch("src.project_manager.db", database), patch(
                "src.project_manager.git_current_branch", return_value="main"
            ):
                self.assertEqual(ProjectManager.get_projects(), [])

                imported = await ProjectManager.import_github_repository({
                    "owner": "EinMelih",
                    "name": "example-repo",
                    "full_name": "EinMelih/example-repo",
                    "html_url": "https://github.com/EinMelih/example-repo",
                    "clone_url": "https://github.com/EinMelih/example-repo.git",
                    "default_branch": "main",
                })

                visible = ProjectManager.get_projects()
                self.assertEqual(imported["id"], legacy_id)
                self.assertEqual([project["id"] for project in visible], [legacy_id])
                self.assertEqual(visible[0]["source_kind"], "github")

    def test_resume_route_and_ui_are_wired(self):
        root = Path(__file__).resolve().parents[1]
        proxy_source = (root / "src" / "proxy_server.py").read_text(
            encoding="utf-8"
        )
        app_source = (root / "dashboard" / "js" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("/api/projects/{id}/github-bootstrap", proxy_source)
        self.assertIn("requestProjectGithubReconcile", app_source)
        self.assertIn("GitHub-Reparatur erforderlich", app_source)
        self.assertIn("workflowIncomplete", app_source)
        self.assertIn("scrollDashboardToProjects", app_source)


if __name__ == "__main__":
    unittest.main()
