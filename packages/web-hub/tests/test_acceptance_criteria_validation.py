"""Regression tests for strict PR-candidate acceptance criteria."""

import tempfile
import unittest
from pathlib import Path

from src.control_center import ControlCenterError, ControlCenterStore
from src.database import Database


SHA = "a" * 40


class TestAcceptanceCriteriaValidation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ag_criteria_")
        self.root = Path(self.temp.name)
        self.database = Database(self.root / "control.db")
        self.project_id = self.database.add_project("Criteria Test", str(self.root))
        self.store = ControlCenterStore(
            self.database,
            sha_resolver=lambda _project: SHA,
        )

    def tearDown(self):
        self.temp.cleanup()

    def _campaign(self):
        return self.store.create_campaign(
            {
                "project_id": self.project_id,
                "title": "Strict acceptance criteria",
                "goal": "Reject invalid acceptance criteria before execution.",
                "planning_depth": "compact",
                "rollback_plan": "Discard the unapproved plan.",
            }
        )

    @staticmethod
    def _candidate_payload(criteria):
        return {
            "title": "Validate candidate criteria",
            "scope": "Validate every acceptance criterion before persistence.",
            "acceptance_criteria": criteria,
            "required_checks": ["unit"],
            "definition_of_done": "All strict-validation tests pass.",
        }

    @staticmethod
    def _generated_plan(criteria):
        return {
            "title": "Generated strict-validation plan",
            "goal": "Keep invalid planner output out of the control plane.",
            "non_goals": "No production execution.",
            "risk_level": "medium",
            "pivotal_fork": "Validate generated contracts before persistence.",
            "success_metrics": ["Invalid criteria are rejected atomically."],
            "constraints": [],
            "assumptions": [],
            "acceptance_matrix": [],
            "rollout_plan": "Review the generated plan before activation.",
            "rollback_plan": "Discard the generated plan.",
            "repository_map": "",
            "design_document": "",
            "adr": "",
            "candidates": [
                {
                    "id": "slice-01",
                    "title": "Validate generated criteria",
                    "scope": "Reject malformed generated acceptance criteria atomically.",
                    "acceptance_criteria": criteria,
                    "required_checks": ["unit"],
                    "definition_of_done": "The invalid plan is not persisted.",
                    "risk_level": "medium",
                    "priority": 10,
                    "depends_on": [],
                }
            ],
        }

    def test_manual_candidate_rejects_non_string_and_blank_criteria(self):
        campaign = self._campaign()
        for criteria in ([None], [7], [" \t "], "A plain string"):
            with self.subTest(criteria=criteria):
                with self.assertRaises(ControlCenterError) as context:
                    self.store.create_pr_candidate(
                        campaign["id"],
                        self._candidate_payload(criteria),
                    )
                self.assertEqual(
                    context.exception.code,
                    "invalid_acceptance_criteria",
                )

        with self.assertRaises(ControlCenterError) as context:
            self.store.create_pr_candidate(
                campaign["id"],
                self._candidate_payload([]),
            )
        self.assertEqual(context.exception.code, "criteria_required")
        stored = self.store.overview(self.project_id)["campaigns"][0]
        self.assertEqual(stored["pr_candidates"], [])

    def test_planner_import_rejects_null_criterion_atomically(self):
        job = self.store.create_planning_job(
            {
                "project_id": self.project_id,
                "wish": "Generate one strictly validated PR candidate.",
                "planning_depth": "compact",
                "max_candidates": 1,
            }
        )
        self.store.claim_planning_job()

        with self.assertRaises(ControlCenterError) as context:
            self.store.complete_planning_job(
                job["id"],
                self._generated_plan([None]),
            )

        self.assertEqual(context.exception.code, "invalid_acceptance_criteria")
        self.assertEqual(self.store.overview(self.project_id)["campaigns"], [])

    def test_valid_criteria_are_trimmed_consistently(self):
        campaign = self._campaign()
        candidate = self.store.create_pr_candidate(
            campaign["id"],
            self._candidate_payload(["  Exact observable result.  "]),
        )
        self.assertEqual(
            candidate["acceptance_criteria"],
            ["Exact observable result."],
        )

    def test_readiness_blocks_invalid_persisted_criteria(self):
        campaign = self._campaign()
        candidate = self.store.create_pr_candidate(
            campaign["id"],
            self._candidate_payload(["A valid criterion is persisted."]),
        )
        with self.database._get_connection() as conn:
            conn.execute(
                """UPDATE control_pr_candidates
                   SET acceptance_criteria_json = '[null]'
                   WHERE id = ?""",
                (candidate["id"],),
            )
            conn.commit()

        readiness = self.store.evaluate_campaign_readiness(
            campaign["id"],
            persist=False,
        )
        self.assertFalse(readiness["ready"])
        self.assertIn(
            "candidate_acceptance_criteria_invalid",
            readiness["missing"],
        )

        with self.assertRaises(ControlCenterError) as context:
            self.store.approve_campaign(
                campaign["id"],
                expected_version=2,
                approval_sha=SHA,
                expected_plan_signature=readiness["plan_signature"],
                actor="test",
            )
        self.assertEqual(context.exception.code, "plan_not_ready")
        stored = self.store.overview(self.project_id)["campaigns"][0]
        self.assertEqual(stored["status"], "draft")


if __name__ == "__main__":
    unittest.main()
