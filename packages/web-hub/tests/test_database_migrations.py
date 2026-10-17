import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.database import DATABASE_SCHEMA_VERSION, Database


class DatabaseMigrationTests(unittest.TestCase):
    def test_old_minimal_schema_is_upgraded_and_versioned(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "old.db"
            connection = sqlite3.connect(db_path)
            try:
                connection.executescript(
                    """
                    CREATE TABLE projects (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        path TEXT NOT NULL UNIQUE,
                        test_command TEXT DEFAULT 'python -m unittest',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE issues (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        project_id INTEGER NOT NULL,
                        title TEXT NOT NULL,
                        description TEXT,
                        status TEXT DEFAULT 'open',
                        priority TEXT DEFAULT 'medium',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE agent_runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        issue_id INTEGER NOT NULL,
                        status TEXT DEFAULT 'pending',
                        branch_name TEXT,
                        started_at TIMESTAMP,
                        completed_at TIMESTAMP
                    );
                    """
                )
                connection.commit()
            finally:
                connection.close()

            Database(db_path)

            connection = sqlite3.connect(db_path)
            try:
                project_columns = {
                    str(row[1]) for row in connection.execute("PRAGMA table_info(projects)")
                }
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                query_plan = [
                    str(row[3])
                    for row in connection.execute(
                        "EXPLAIN QUERY PLAN SELECT * FROM issues "
                        "WHERE project_id = ? AND github_number = ?",
                        (1, 1),
                    )
                ]
            finally:
                connection.close()

            self.assertIn("github_url", project_columns)
            self.assertIn("antigravity_project_name", project_columns)
            self.assertIn("archived_at", project_columns)
            self.assertEqual(version, DATABASE_SCHEMA_VERSION)
            self.assertTrue(
                any(
                    "idx_issues_project_github_number" in detail
                    for detail in query_plan
                ),
                query_plan,
            )

    def test_managed_antigravity_conversation_registry_persists_lifecycle(self):
        conversation_id = "11111111-1111-4111-8111-111111111111"
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "managed-chats.db"
            database = Database(db_path)

            database.upsert_managed_antigravity_conversation(
                conversation_id,
                state="active",
            )
            self.assertEqual(
                database.list_managed_antigravity_conversations(state="active")[0][
                    "conversation_id"
                ],
                conversation_id,
            )

            self.assertTrue(
                database.set_managed_antigravity_conversation_state(
                    conversation_id,
                    "archived",
                )
            )
            reopened = Database(db_path)
            archived = reopened.list_managed_antigravity_conversations(
                state="archived"
            )
            self.assertEqual(len(archived), 1)
            self.assertEqual(archived[0]["conversation_id"], conversation_id)

            self.assertTrue(
                reopened.set_managed_antigravity_conversation_state(
                    conversation_id,
                    "deleted",
                )
            )
            self.assertEqual(
                reopened.list_managed_antigravity_conversations(state="active"),
                [],
            )


if __name__ == "__main__":
    unittest.main()
