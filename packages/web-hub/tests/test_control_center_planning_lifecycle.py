"""Planning-job lifecycle contracts across generated Campaign review."""

import tempfile
import threading
import unittest
from pathlib import Path

from src.control_center import ControlCenterError, ControlCenterStore
from src.database import Database


SHA = "a" * 40


class TestPlanningLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ag_planning_lifecycle_")
        self.root = Path(self.temp.name)
        self.database = Database(self.root / "control.db")
        self.project_id = self.database.add_project(
            "Planning lifecycle",
            str(self.root),
        )
        self.store = ControlCenterStore(
            self.database,
            sha_resolver=lambda _project: SHA,
            repository_reader=lambda _project, _sha, path: (
                "class PlanningJobMixin:\n    pass\n"
                if path == "src/control_center/planning_jobs.py"
                else None
            ),
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _create_job(self):
        return self.store.create_planning_job(
            {
                "project_id": self.project_id,
                "wish": "Split this idea into one reviewable and verifiable PR slice.",
                "planning_depth": "compact",
                "max_candidates": 1,
            }
        )

    @staticmethod
    def _generated_plan():
        return {
            "title": "Reviewable planning lifecycle",
            "goal": "Keep generated planning active until a human approves the plan.",
            "non_goals": "Do not start implementation before exact plan approval.",
            "risk_level": "medium",
            "pivotal_fork": "Keep plan approval separate from plan generation.",
            "success_metrics": ["Approval completes the linked planning job exactly once."],
            "alternatives": [
                {
                    "title": "Explicit approval state",
                    "mechanism": "Keep the job waiting until exact plan approval.",
                    "tradeoffs": "One extra state, but truthful human ownership.",
                },
                {
                    "title": "Generation completes job",
                    "mechanism": "Mark planning complete as soon as JSON is imported.",
                    "tradeoffs": "Simpler lifecycle, but falsely reports human approval.",
                },
            ],
            "review_strategy": "An independent reviewer checks lifecycle and exact evidence.",
            "rollout_plan": "Exercise the lifecycle in a private proof campaign.",
            "rollback_plan": "Cancel the draft and restore the idea to the inbox.",
            "repository_map": (
                "# Repository map\n\n"
                "`src/control_center/planning_jobs.py` owns lifecycle state."
            ),
            "branch_assessments": [
                {
                    "branch": branch,
                    "question": f"What repository fact grounds {branch}?",
                    "rationale": f"Repository inspection verifies {branch} lifecycle impact.",
                    "status": "grounded",
                    "owner": "repository-mapper",
                    "evidence": {"path": "src/control_center/planning_jobs.py"},
                }
                for branch in ("architecture", "data", "security", "operations")
            ],
            "candidates": [
                {
                    "id": "slice-01",
                    "title": "Implement lifecycle",
                    "scope": "Implement the durable planning lifecycle state transitions.",
                    "purpose": "Keep generated plans waiting for exact human approval.",
                    "non_goals": "Do not activate implementation automatically.",
                    "components": ["src/control_center/planning_jobs.py"],
                    "expected_diff_type": "code-and-tests",
                    "acceptance_criteria": [
                        "Campaign approval completes the linked planning job."
                    ],
                    "required_checks": ["unit"],
                    "manual_tests": ["Generate a plan and inspect its waiting state."],
                    "reversibility": "Revert the lifecycle transition commit.",
                    "migration_plan": "Use additive lifecycle values only.",
                    "compatibility_plan": "Preserve existing completed and cancelled rows.",
                    "documentation_changes": ["Document plan-approval waiting state."],
                    "definition_of_done": "The lifecycle contract test passes.",
                    "risk_level": "medium",
                    "priority": 10,
                    "depends_on": [],
                }
            ],
        }

    def _complete_generated_plan(self):
        job = self._create_job()
        self.store.claim_planning_job()
        return self.store.complete_planning_job(job["id"], self._generated_plan())

    def test_campaign_approval_completes_linked_planning_job(self):
        waiting = self._complete_generated_plan()

        self.assertEqual(waiting["status"], "waiting_human")
        self.assertIsNone(waiting["finished_at"])
        self.assertEqual(
            self.store.get_idea_seed(waiting["idea_seed_id"])["status"],
            "planned",
        )
        before_approval = [
            event
            for event in self.store.overview(self.project_id)["audit"]
            if event["entity_id"] == waiting["id"]
        ]
        self.assertEqual(before_approval[0]["action"], "planning_job.plan_generated")
        self.assertNotIn(
            "planning_job.completed",
            {event["action"] for event in before_approval},
        )
        campaign_before = next(
            item
            for item in self.store.overview(self.project_id)["campaigns"]
            if item["id"] == waiting["campaign_id"]
        )
        readiness = self.store.evaluate_campaign_readiness(
            waiting["campaign_id"],
            persist=False,
        )
        campaign = self.store.approve_campaign(
            waiting["campaign_id"],
            expected_version=campaign_before["version"],
            approval_sha=SHA,
            expected_plan_signature=readiness["plan_signature"],
            actor="owner",
        )

        completed = self.store.get_planning_job(waiting["id"])
        self.assertEqual(campaign["status"], "approved")
        self.assertEqual(completed["status"], "completed")
        self.assertIsNotNone(completed["finished_at"])
        completed_events = [
            event
            for event in self.store.overview(self.project_id)["audit"]
            if event["entity_id"] == waiting["id"]
            and event["action"] == "planning_job.completed"
        ]
        self.assertEqual(len(completed_events), 1)

    def test_campaign_cancel_cancels_linked_planning_job(self):
        waiting = self._complete_generated_plan()

        result = self.store.cancel_campaign(
            waiting["campaign_id"],
            actor="owner",
            reason="The generated plan is no longer wanted.",
        )

        cancelled = self.store.get_planning_job(waiting["id"])
        self.assertEqual(result["campaign"]["status"], "cancelled")
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertIsNotNone(cancelled["finished_at"])
        self.assertEqual(
            self.store.get_idea_seed(waiting["idea_seed_id"])["status"],
            "planned",
        )

    def test_planning_job_cancel_is_idempotent_in_every_cancellable_state(self):
        cancelled_job_ids = []

        def assert_idempotent_cancel(initial_status, job):
            with self.subTest(initial_status=initial_status):
                first = self.store.cancel_planning_job(
                    job["id"],
                    actor="owner",
                    reason="Stop this planning request.",
                )
                second = self.store.cancel_planning_job(
                    job["id"],
                    actor="owner",
                    reason="Stop this planning request.",
                )
                self.assertEqual(first["status"], "cancelled")
                self.assertEqual(second["status"], "cancelled")
                cancelled_job_ids.append(job["id"])

        assert_idempotent_cancel("queued", self._create_job())

        running = self._create_job()
        self.store.claim_planning_job()
        assert_idempotent_cancel("running", running)

        assert_idempotent_cancel("waiting_human", self._complete_generated_plan())

        failed = self._create_job()
        self.store.claim_planning_job()
        failed = self.store.fail_planning_job(failed["id"], "Planner failed.")
        assert_idempotent_cancel("failed", failed)

        cancelled_actions = [
            event
            for event in self.store.overview(self.project_id)["audit"]
            if event["action"] == "planning_job.cancelled"
            and event["entity_id"] in cancelled_job_ids
        ]
        self.assertEqual(len(cancelled_actions), 4)

    def test_late_failure_cannot_resurrect_cancelled_job(self):
        job = self._create_job()
        self.store.claim_planning_job()
        self.store.cancel_planning_job(job["id"], actor="owner")

        with self.assertRaises(ControlCenterError) as context:
            self.store.fail_planning_job(job["id"], "Late planner failure.")

        self.assertEqual(context.exception.code, "planning_job_not_running")
        self.assertEqual(
            self.store.get_planning_job(job["id"])["status"],
            "cancelled",
        )

    def test_cancel_before_plan_import_blocks_late_completion(self):
        resolver_reached = threading.Event()
        release_resolver = threading.Event()

        def blocking_resolver(_project):
            resolver_reached.set()
            release_resolver.wait(timeout=5)
            return SHA

        self.store.sha_resolver = blocking_resolver
        job = self._create_job()
        self.store.claim_planning_job()
        outcome = {}

        def complete_late():
            try:
                outcome["result"] = self.store.complete_planning_job(
                    job["id"],
                    self._generated_plan(),
                )
            except Exception as exc:  # The public error is asserted below.
                outcome["error"] = exc

        worker = threading.Thread(target=complete_late)
        worker.start()
        try:
            self.assertTrue(resolver_reached.wait(timeout=5))
            self.store.cancel_planning_job(job["id"], actor="owner")
        finally:
            release_resolver.set()
        worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertIsInstance(outcome.get("error"), ControlCenterError)
        self.assertEqual(outcome["error"].code, "planning_job_not_running")
        self.assertEqual(
            self.store.get_planning_job(job["id"])["status"],
            "cancelled",
        )
        self.assertEqual(self.store.overview(self.project_id)["campaigns"], [])

    def test_retry_uses_repository_policy_and_is_audited(self):
        self.store.update_repository_policy(
            self.project_id,
            {"max_retry_attempts": 1},
            actor="owner",
        )
        job = self._create_job()
        first_attempt = self.store.claim_planning_job()
        self.assertEqual(first_attempt["attempt"], 1)
        self.store.fail_planning_job(job["id"], "First attempt failed.")

        retried = self.store.retry_planning_job(job["id"], actor="owner")

        self.assertEqual(retried["status"], "queued")
        retry_events = [
            event
            for event in self.store.overview(self.project_id)["audit"]
            if event["entity_id"] == job["id"]
            and event["action"] == "planning_job.retried"
        ]
        self.assertEqual(len(retry_events), 1)
        self.assertEqual(retry_events[0]["actor"], "owner")
        self.assertEqual(retry_events[0]["from_state"], "failed")
        self.assertEqual(retry_events[0]["to_state"], "queued")
        self.assertEqual(retry_events[0]["evidence"]["max_retry_attempts"], 1)

        second_attempt = self.store.claim_planning_job()
        self.assertEqual(second_attempt["attempt"], 2)
        self.store.fail_planning_job(job["id"], "Second attempt failed.")
        with self.assertRaises(ControlCenterError) as context:
            self.store.retry_planning_job(job["id"], actor="owner")

        self.assertEqual(context.exception.code, "planning_retry_limit")
        self.assertEqual(self.store.get_planning_job(job["id"])["status"], "failed")


if __name__ == "__main__":
    unittest.main()
