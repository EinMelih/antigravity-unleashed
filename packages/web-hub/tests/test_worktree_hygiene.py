"""Repository hygiene gates for agent-created Git worktrees."""

import tempfile
import unittest
from pathlib import Path

from src.control_center import ControlCenterError
from src.control_center.worktrees import WorktreeManager


class TestWorktreeCommitHygiene(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ag_worktree_hygiene_")
        self.repository = Path(self.temp.name)
        self.manager = WorktreeManager()
        self.manager._git(self.repository, ["init", "-b", "main"])
        self.manager._git(
            self.repository,
            ["config", "user.name", "Anti-Gravity Test"],
        )
        self.manager._git(
            self.repository,
            ["config", "user.email", "test@example.invalid"],
        )
        (self.repository / "app.js").write_text(
            "export const ready = false;\n",
            encoding="utf-8",
        )
        self.manager._git(self.repository, ["add", "app.js"])
        self.manager._git(self.repository, ["commit", "-m", "baseline"])
        self.baseline = self.manager._git(
            self.repository,
            ["rev-parse", "HEAD"],
        ).stdout.strip()

    def tearDown(self):
        self.temp.cleanup()

    def test_unignored_node_modules_blocks_before_git_add_or_commit(self):
        dependency = self.repository / "node_modules" / "demo"
        dependency.mkdir(parents=True)
        (dependency / "index.js").write_text(
            "module.exports = true;\n",
            encoding="utf-8",
        )
        (self.repository / "app.js").write_text(
            "export const ready = true;\n",
            encoding="utf-8",
        )

        with self.assertRaises(ControlCenterError) as context:
            self.manager.commit_changes(
                self.repository,
                "must not commit generated dependencies",
            )

        self.assertEqual(
            context.exception.code,
            "repository_hygiene_violation",
        )
        self.assertIn("node_modules/demo/index.js", str(context.exception))
        head = self.manager._git(
            self.repository,
            ["rev-parse", "HEAD"],
        ).stdout.strip()
        staged = self.manager._git(
            self.repository,
            ["diff", "--cached", "--name-only"],
        ).stdout.strip()
        self.assertEqual(head, self.baseline)
        self.assertEqual(staged, "")

    def test_ignored_node_modules_is_allowed_and_never_committed(self):
        (self.repository / ".gitignore").write_text(
            "\n".join([
                "node_modules/",
                "cypress/screenshots/",
                "cypress/videos/",
                "*.log",
                "coverage/",
                "dist/",
                "",
            ]),
            encoding="utf-8",
        )
        dependency = self.repository / "node_modules" / "demo"
        dependency.mkdir(parents=True)
        (dependency / "index.js").write_text(
            "module.exports = true;\n",
            encoding="utf-8",
        )
        (self.repository / "app.js").write_text(
            "export const ready = true;\n",
            encoding="utf-8",
        )

        sha = self.manager.commit_changes(
            self.repository,
            "commit source without generated dependencies",
        )

        self.assertNotEqual(sha, self.baseline)
        tracked = self.manager._git(
            self.repository,
            ["ls-tree", "-r", "--name-only", "HEAD"],
        ).stdout.splitlines()
        self.assertIn(".gitignore", tracked)
        self.assertIn("app.js", tracked)
        self.assertFalse(
            any(path.startswith("node_modules/") for path in tracked)
        )

    def test_whitespace_error_blocks_without_touching_real_index(self):
        (self.repository / "app.js").write_text(
            "export const ready = true;  \n",
            encoding="utf-8",
        )
        (self.repository / "new-file.js").write_text(
            "export const added = true;\t\n",
            encoding="utf-8",
        )

        with self.assertRaises(ControlCenterError) as context:
            self.manager.commit_changes(
                self.repository,
                "must not commit whitespace errors",
            )

        self.assertEqual(
            context.exception.code,
            "repository_hygiene_violation",
        )
        self.assertIn("trailing whitespace", str(context.exception))
        self.assertEqual(
            self.manager._git(
                self.repository,
                ["rev-parse", "HEAD"],
            ).stdout.strip(),
            self.baseline,
        )
        self.assertEqual(
            self.manager._git(
                self.repository,
                ["diff", "--cached", "--name-only"],
            ).stdout.strip(),
            "",
        )

    def test_cumulative_branch_whitespace_is_checked_against_task_base(self):
        (self.repository / "app.js").write_text(
            "export const ready = true;  \n",
            encoding="utf-8",
        )
        self.manager._git(self.repository, ["add", "app.js"])
        self.manager._git(
            self.repository,
            ["commit", "-m", "legacy task commit with whitespace"],
        )
        (self.repository / "clean.js").write_text(
            "export const clean = true;\n",
            encoding="utf-8",
        )

        with self.assertRaises(ControlCenterError) as context:
            self.manager.assert_commit_hygiene(
                self.repository,
                base_sha=self.baseline,
            )

        self.assertEqual(
            context.exception.code,
            "repository_hygiene_violation",
        )
        self.assertIn("app.js:1: trailing whitespace", str(context.exception))


if __name__ == "__main__":
    unittest.main()
