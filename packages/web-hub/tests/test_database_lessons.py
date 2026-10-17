import tempfile
import unittest
from pathlib import Path

from src.database import Database


class DatabaseLessonsTests(unittest.TestCase):
    def test_archived_project_lessons_are_excluded_from_active_reads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "lessons.db")
            active_project_id = database.add_project("Active", "C:/projects/active")
            archived_project_id = database.add_project("Archived", "C:/projects/archived")

            active_lesson_id = database.add_lesson(
                active_project_id,
                None,
                "Keep active context",
                "Visible for active projects.",
            )
            archived_lesson_id = database.add_lesson(
                archived_project_id,
                None,
                "Hide archived context",
                "Must not leak into active knowledge.",
            )
            with database._get_connection() as connection:
                global_lesson_id = connection.execute(
                    "INSERT INTO lessons (project_id, technique, solution) VALUES (NULL, ?, ?)",
                    ("Global practice", "Visible without a project."),
                ).lastrowid
                connection.execute(
                    "UPDATE projects SET archived_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (archived_project_id,),
                )
                connection.commit()

            visible_ids = {lesson["id"] for lesson in database.get_lessons()}

            self.assertIn(active_lesson_id, visible_ids)
            self.assertIn(global_lesson_id, visible_ids)
            self.assertNotIn(archived_lesson_id, visible_ids)
            self.assertEqual(database.get_lessons(archived_project_id), [])


if __name__ == "__main__":
    unittest.main()
