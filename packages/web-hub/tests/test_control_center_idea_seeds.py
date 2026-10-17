"""Store contracts for the lightweight Idea Seed inbox."""

import tempfile
import unittest
from pathlib import Path

from src.control_center import ControlCenterError, ControlCenterStore
from src.database import Database


class TestIdeaSeedStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="antigravity_idea_seeds_")
        self.database = Database(Path(self.temp.name) / "control.db")
        self.project_id = self.database.add_project(
            "Idea Seed Test",
            self.temp.name,
        )
        self.other_project_id = self.database.add_project(
            "Other Idea Seed Test",
            self.temp.name,
        )
        self.store = ControlCenterStore(self.database)

    def tearDown(self):
        self.temp.cleanup()

    def _create_seed(self, *, project_id=None, title="Keep planning focused"):
        return self.store.create_idea_seed(
            {
                "project_id": project_id or self.project_id,
                "title": title,
                "note": "Capture follow-up work without expanding the active task.",
                "source": "agent",
                "provenance": {"task_id": "TASK-7", "path": "src/planner.py"},
            }
        )

    def test_seeds_can_be_listed_by_project_and_retrieved_individually(self):
        seed = self._create_seed()
        other = self._create_seed(
            project_id=self.other_project_id,
            title="Unrelated repository idea",
        )

        project_seeds = self.store.list_idea_seeds(self.project_id)
        all_seeds = self.store.list_idea_seeds()
        retrieved = self.store.get_idea_seed(seed["id"])

        self.assertEqual([item["id"] for item in project_seeds], [seed["id"]])
        self.assertEqual(
            {item["id"] for item in all_seeds},
            {seed["id"], other["id"]},
        )
        self.assertEqual(
            retrieved["provenance"],
            {"task_id": "TASK-7", "path": "src/planner.py"},
        )

    def test_global_inbox_excludes_seeds_from_archived_projects(self):
        active_seed = self._create_seed()
        archived_seed = self._create_seed(
            project_id=self.other_project_id,
            title="Archived repository idea",
        )
        with self.database._get_connection() as conn:
            conn.execute(
                "UPDATE projects SET archived_at = CURRENT_TIMESTAMP WHERE id = ?",
                (self.other_project_id,),
            )
            conn.commit()

        listed_ids = {item["id"] for item in self.store.list_idea_seeds()}

        self.assertIn(active_seed["id"], listed_ids)
        self.assertNotIn(archived_seed["id"], listed_ids)

    def test_seed_content_can_be_updated_without_changing_its_disposition(self):
        seed = self._create_seed()

        updated = self.store.update_idea_seed(
            seed["id"],
            {
                "title": "Preserve a discovered follow-up",
                "note": "Keep this idea available for the next planning session.",
                "source": "human",
                "provenance": {"task_id": "TASK-9", "line": 42},
            },
            actor="owner",
        )

        self.assertEqual(updated["title"], "Preserve a discovered follow-up")
        self.assertEqual(
            updated["note"],
            "Keep this idea available for the next planning session.",
        )
        self.assertEqual(updated["source"], "human")
        self.assertEqual(updated["provenance"], {"task_id": "TASK-9", "line": 42})
        self.assertEqual(updated["status"], "inbox")

    def test_seed_can_be_deferred_reopened_and_dismissed(self):
        seed = self._create_seed()

        deferred = self.store.disposition_idea_seed(
            seed["id"],
            disposition="deferred",
            reason="Revisit after the current campaign.",
            actor="owner",
        )
        replay = self.store.disposition_idea_seed(
            seed["id"],
            disposition="deferred",
            reason="Revisit after the current campaign.",
            actor="owner",
        )
        reopened = self.store.disposition_idea_seed(
            seed["id"],
            disposition="inbox",
            reason="The current campaign has completed.",
            actor="owner",
        )
        dismissed = self.store.disposition_idea_seed(
            seed["id"],
            disposition="dismissed",
            reason="The repository no longer needs this follow-up.",
            actor="owner",
        )

        self.assertEqual(deferred["status"], "deferred")
        self.assertEqual(replay["status"], "deferred")
        self.assertEqual(reopened["status"], "inbox")
        self.assertEqual(dismissed["status"], "dismissed")

    def test_seed_update_rejects_invalid_or_state_fields(self):
        seed = self._create_seed()

        with self.assertRaises(ControlCenterError) as invalid_provenance:
            self.store.update_idea_seed(
                seed["id"],
                {"provenance": ["TASK-7"]},
            )
        with self.assertRaises(ControlCenterError) as direct_state_change:
            self.store.update_idea_seed(
                seed["id"],
                {"status": "dismissed"},
            )

        self.assertEqual(invalid_provenance.exception.code, "invalid_provenance")
        self.assertEqual(
            direct_state_change.exception.code,
            "invalid_idea_seed_fields",
        )
        self.assertEqual(self.store.get_idea_seed(seed["id"])["status"], "inbox")

    def test_seed_disposition_requires_reason_and_valid_transition(self):
        seed = self._create_seed()

        with self.assertRaises(ControlCenterError) as missing_reason:
            self.store.disposition_idea_seed(
                seed["id"],
                disposition="dismissed",
            )
        dismissed = self.store.disposition_idea_seed(
            seed["id"],
            disposition="dismissed",
            reason="Duplicate of an existing campaign.",
        )
        with self.assertRaises(ControlCenterError) as invalid_transition:
            self.store.disposition_idea_seed(
                seed["id"],
                disposition="deferred",
                reason="Maybe later.",
            )

        self.assertEqual(missing_reason.exception.code, "reason_required")
        self.assertEqual(dismissed["status"], "dismissed")
        self.assertEqual(
            invalid_transition.exception.code,
            "invalid_state_transition",
        )

    def test_existing_seed_can_start_planning_without_being_duplicated(self):
        seed = self._create_seed(title="Plan durable review evidence")
        before_count = len(self.store.list_idea_seeds(self.project_id))

        job = self.store.create_planning_job(
            {
                "idea_seed_id": seed["id"],
                "planning_depth": "balanced",
                "max_candidates": 8,
                "activation_policy": "campaign_wave",
            }
        )

        self.assertEqual(job["idea_seed_id"], seed["id"])
        self.assertEqual(job["project_id"], self.project_id)
        self.assertEqual(job["wish"], seed["note"])
        self.assertEqual(len(self.store.list_idea_seeds(self.project_id)), before_count)
        self.assertEqual(self.store.get_idea_seed(seed["id"])["status"], "planning")

    def test_seed_returns_to_inbox_after_failure_or_cancel_and_retry_reclaims_it(self):
        seed = self._create_seed(title="Retry a bounded planning session")
        job = self.store.create_planning_job({"idea_seed_id": seed["id"]})
        self.store.claim_planning_job()

        self.store.fail_planning_job(job["id"], "Planner unavailable.")
        self.assertEqual(self.store.get_idea_seed(seed["id"])["status"], "inbox")

        self.store.retry_planning_job(job["id"])
        self.assertEqual(self.store.get_idea_seed(seed["id"])["status"], "planning")

        self.store.cancel_planning_job(job["id"], reason="No longer needed.")
        self.assertEqual(self.store.get_idea_seed(seed["id"])["status"], "inbox")


if __name__ == "__main__":
    unittest.main()
