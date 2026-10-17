"""Socratic planning-session contracts at the ControlCenterStore seam."""

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from src.control_center import ControlCenterError, ControlCenterStore
from src.control_center.agent_adapter import AntiGravityTaskAdapter
from src.database import Database


SHA = "a" * 40


class TestPlanningSessions(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ag_planning_session_")
        self.root = Path(self.temp.name)
        self.database = Database(self.root / "control.db")
        self.project_id = self.database.add_project(
            "Socratic planning",
            str(self.root),
        )
        self.store = ControlCenterStore(
            self.database,
            sha_resolver=lambda _project: SHA,
            repository_reader=lambda _project, _sha, path: (
                "class PlanningMixin:\n    pass\n"
                if path == "src/control_center/planning.py"
                else None
            ),
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _running_job(self):
        job = self.store.create_planning_job(
            {
                "project_id": self.project_id,
                "wish": "Clarify the ambiguous delivery target before creating PR slices.",
                "planning_depth": "compact",
                "max_candidates": 2,
            }
        )
        return self.store.claim_planning_job()

    @staticmethod
    def _question(text="Which user-visible outcome defines success?"):
        return {
            "type": "question",
            "question": {
                "branch": "success",
                "question": text,
                "rationale": "The answer changes acceptance criteria and PR scope.",
            },
        }

    @staticmethod
    def _plan():
        return {
            "title": "Resolved delivery plan",
            "goal": "Deliver the clarified user outcome with verifiable evidence.",
            "non_goals": "No production deployment.",
            "risk_level": "medium",
            "pivotal_fork": "Persist session decisions instead of relying on chat memory.",
            "success_metrics": ["A verified user can finish the clarified flow."],
            "alternatives": [
                {
                    "title": "Durable session ledger",
                    "mechanism": "Persist every question and answer in SQLite.",
                    "tradeoffs": "More schema state, but restart-safe continuation.",
                },
                {
                    "title": "Conversation-only state",
                    "mechanism": "Keep prior answers only in the planner chat.",
                    "tradeoffs": "Less storage, but no deterministic recovery.",
                },
            ],
            "review_strategy": "An independent reviewer checks the exact flow and evidence.",
            "rollout_plan": "Verify the bounded flow in one private proof repository.",
            "rollback_plan": "Revert the bounded flow implementation.",
            "repository_map": (
                "# Repository map\n\n"
                "`src/control_center/planning.py` owns planning."
            ),
            "branch_assessments": [
                {
                    "branch": branch,
                    "question": f"What repository fact grounds {branch}?",
                    "rationale": f"Repository inspection verifies the {branch} boundary.",
                    "status": "grounded",
                    "owner": "repository-mapper",
                    "evidence": {"path": "src/control_center/planning.py"},
                }
                for branch in ("architecture", "data", "security", "operations")
            ],
            "candidates": [
                {
                    "id": "slice-01",
                    "title": "Implement verified flow",
                    "scope": "Implement and verify the clarified end-to-end user flow.",
                    "purpose": "Deliver the clarified user-visible outcome.",
                    "non_goals": "Do not change unrelated flows or deploy automatically.",
                    "components": ["src/control_center"],
                    "expected_diff_type": "code-and-tests",
                    "acceptance_criteria": [
                        "A verified user can finish the flow."
                    ],
                    "required_checks": ["unit"],
                    "manual_tests": ["Complete the clarified flow as a verified user."],
                    "reversibility": "Revert the bounded implementation commit.",
                    "migration_plan": "Not applicable: no persistent user data change.",
                    "compatibility_plan": "Preserve existing API and session behavior.",
                    "documentation_changes": ["Document the clarified flow."],
                    "definition_of_done": "The exact flow is covered by tests.",
                    "risk_level": "medium",
                    "priority": 10,
                    "depends_on": [],
                }
            ],
        }

    def _continued_session(self):
        running = self._running_job()
        self.store.update_planning_job_chat(running["id"], "planner-chat-1")
        waiting = self.store.complete_planning_job(
            running["id"],
            self._question(),
        )
        question_id = waiting["active_question_id"]
        self.store.answer_planning_question(
            question_id,
            {
                "answer": "Success means a verified user can finish the flow.",
                "answer_source": "owner",
            },
        )
        return self.store.claim_planning_job(), question_id, waiting["campaign_id"]

    def test_first_question_creates_one_draft_campaign_and_human_gate(self):
        running = self._running_job()

        waiting = self.store.complete_planning_job(
            running["id"],
            self._question(),
        )

        self.assertEqual(waiting["status"], "waiting_human")
        self.assertEqual(waiting["waiting_reason"], "question")
        self.assertEqual(waiting["round_number"], 1)
        self.assertTrue(waiting["active_question_id"])
        overview = self.store.overview(self.project_id)
        self.assertEqual(len(overview["campaigns"]), 1)
        campaign = overview["campaigns"][0]
        self.assertEqual(campaign["id"], waiting["campaign_id"])
        self.assertEqual(campaign["status"], "draft")
        self.assertEqual(campaign["pr_candidates"], [])
        self.assertEqual(len(campaign["questions"]), 1)
        self.assertEqual(
            campaign["questions"][0]["planning_job_id"],
            waiting["id"],
        )
        gates = [
            item
            for item in overview["attention"]
            if item["status"] == "open"
            and item["category"] == "planning_question"
            and item["entity_id"] == waiting["active_question_id"]
        ]
        self.assertEqual(len(gates), 1)

    def test_human_answer_requeues_same_chat_without_spending_retry(self):
        running = self._running_job()
        self.store.update_planning_job_chat(running["id"], "planner-chat-1")
        waiting = self.store.complete_planning_job(
            running["id"],
            self._question(),
        )

        answered = self.store.answer_planning_question(
            waiting["active_question_id"],
            {
                "answer": "Success means a verified user can finish the flow.",
                "answer_source": "owner",
            },
        )

        queued = self.store.get_planning_job(running["id"])
        self.assertEqual(answered["status"], "answered")
        self.assertEqual(queued["status"], "queued")
        self.assertEqual(queued["waiting_reason"], "")
        self.assertEqual(queued["antigravity_chat_id"], "planner-chat-1")
        self.assertEqual(queued["attempt"], 1)

        continued = self.store.claim_planning_job()
        self.assertEqual(continued["id"], running["id"])
        self.assertTrue(continued["continuation"])
        self.assertEqual(continued["attempt"], 1)
        self.assertEqual(continued["antigravity_chat_id"], "planner-chat-1")
        self.assertEqual(len(continued["session_questions"]), 1)
        self.assertEqual(
            continued["session_questions"][0]["answer"],
            "Success means a verified user can finish the flow.",
        )

    def test_final_plan_requires_explicit_resolved_question_ids(self):
        continued, question_id, campaign_id = self._continued_session()

        with self.assertRaises(ControlCenterError) as context:
            self.store.complete_planning_job(
                continued["id"],
                {"type": "plan", "plan": self._plan()},
            )

        self.assertEqual(context.exception.code, "resolved_question_ids_required")
        self.assertEqual(
            self.store.get_planning_job(continued["id"])["status"],
            "running",
        )
        campaign = self.store.overview(self.project_id)["campaigns"][0]
        self.assertEqual(campaign["id"], campaign_id)
        self.assertEqual(campaign["pr_candidates"], [])
        self.assertEqual(campaign["questions"][0]["id"], question_id)
        self.assertEqual(campaign["questions"][0]["status"], "answered")

    def test_final_plan_envelope_cannot_also_contain_a_question(self):
        running = self._running_job()

        with self.assertRaises(ControlCenterError) as context:
            self.store.complete_planning_job(
                running["id"],
                {
                    "type": "plan",
                    "resolved_question_ids": [],
                    "plan": self._plan(),
                    "question": self._question()["question"],
                },
            )

        self.assertEqual(context.exception.code, "invalid_generated_plan_envelope")
        self.assertEqual(
            self.store.get_planning_job(running["id"])["status"],
            "running",
        )
        self.assertEqual(self.store.overview(self.project_id)["campaigns"], [])

    def test_legacy_session_plan_rejects_malformed_resolved_question_ids(self):
        continued, _question_id, _campaign_id = self._continued_session()
        malformed = self._plan()
        malformed["resolved_question_ids"] = 42

        with self.assertRaises(ControlCenterError) as context:
            self.store.complete_planning_job(continued["id"], malformed)

        self.assertEqual(context.exception.code, "resolved_question_ids_required")
        self.assertEqual(
            self.store.get_planning_job(continued["id"])["status"],
            "running",
        )

    def test_final_plan_fills_same_campaign_and_resolves_session_questions(self):
        continued, question_id, campaign_id = self._continued_session()

        waiting = self.store.complete_planning_job(
            continued["id"],
            {
                "type": "plan",
                "resolved_question_ids": [question_id],
                "plan": self._plan(),
            },
        )

        self.assertEqual(waiting["status"], "waiting_human")
        self.assertEqual(waiting["waiting_reason"], "plan_approval")
        self.assertIsNone(waiting["active_question_id"])
        self.assertEqual(waiting["campaign_id"], campaign_id)
        overview = self.store.overview(self.project_id)
        self.assertEqual(len(overview["campaigns"]), 1)
        campaign = overview["campaigns"][0]
        self.assertEqual(campaign["id"], campaign_id)
        self.assertEqual(campaign["title"], "Resolved delivery plan")
        self.assertEqual(len(campaign["pr_candidates"]), 1)
        session_question = next(
            item for item in campaign["questions"] if item["id"] == question_id
        )
        self.assertEqual(session_question["status"], "resolved")
        self.assertEqual(
            session_question["resolved_in_version"],
            campaign["version"],
        )
        plan_gates = [
            item
            for item in overview["attention"]
            if item["status"] == "open"
            and item["category"] == "plan_approval"
            and item["entity_id"] == campaign_id
        ]
        self.assertEqual(len(plan_gates), 1)

    def test_campaign_approval_terminalizes_planning_job_metadata_idempotently(self):
        continued, question_id, campaign_id = self._continued_session()
        self.store.complete_planning_job(
            continued["id"],
            {
                "type": "plan",
                "resolved_question_ids": [question_id],
                "plan": self._plan(),
            },
        )
        campaign = self.store.overview(self.project_id)["campaigns"][0]
        readiness = self.store.evaluate_campaign_readiness(
            campaign_id,
            persist=False,
        )

        self.store.approve_campaign(
            campaign_id,
            expected_version=campaign["version"],
            approval_sha=SHA,
            expected_plan_signature=readiness["plan_signature"],
            actor="owner",
        )
        completed = self.store.get_planning_job(continued["id"])
        self.store.approve_campaign(
            campaign_id,
            expected_version=campaign["version"],
            approval_sha=SHA,
            expected_plan_signature=readiness["plan_signature"],
            actor="owner",
        )
        replayed = self.store.get_planning_job(continued["id"])

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["waiting_reason"], "")
        self.assertIsNone(completed["active_question_id"])
        self.assertIsNotNone(completed["finished_at"])
        self.assertEqual(replayed, completed)

    def test_final_plan_must_resolve_every_answered_session_question(self):
        continued, first_question_id, campaign_id = self._continued_session()
        second_waiting = self.store.complete_planning_job(
            continued["id"],
            self._question("Which repository check proves the user outcome?"),
        )
        second_question_id = second_waiting["active_question_id"]
        self.store.answer_planning_question(
            second_question_id,
            {
                "answer": "The focused end-to-end test proves the outcome.",
                "answer_source": "owner",
            },
        )
        final_round = self.store.claim_planning_job()

        with self.assertRaises(ControlCenterError) as context:
            self.store.complete_planning_job(
                final_round["id"],
                {
                    "type": "plan",
                    "resolved_question_ids": [first_question_id],
                    "plan": self._plan(),
                },
            )

        self.assertEqual(context.exception.code, "planning_questions_unresolved")
        current = self.store.get_planning_job(final_round["id"])
        self.assertEqual(current["status"], "running")
        campaign = self.store.overview(self.project_id)["campaigns"][0]
        self.assertEqual(campaign["id"], campaign_id)
        self.assertEqual(campaign["pr_candidates"], [])
        self.assertEqual(
            {question["id"]: question["status"] for question in campaign["questions"]},
            {
                first_question_id: "answered",
                second_question_id: "answered",
            },
        )

    def test_recovery_does_not_refund_unspent_continuation_attempt(self):
        continued, _question_id, _campaign_id = self._continued_session()
        self.assertEqual(continued["attempt"], 1)

        recovered = self.store.recover_interrupted_planning_jobs()

        self.assertEqual(recovered, 1)
        current = self.store.get_planning_job(continued["id"])
        self.assertEqual(current["status"], "failed")
        self.assertEqual(current["attempt"], 1)

    def test_recovery_does_not_overwrite_concurrent_cancel(self):
        running = self._running_job()
        original_connection = self.database._get_connection
        injected = False

        class CursorWithCancel:
            def __init__(self, cursor, connection):
                self.cursor = cursor
                self.connection = connection

            def fetchall(self):
                nonlocal injected
                rows = self.cursor.fetchall()
                if not injected:
                    injected = True
                    self.connection.execute(
                        """UPDATE control_planning_jobs
                           SET status = 'cancelled',
                               finished_at = CURRENT_TIMESTAMP
                           WHERE id = ? AND status = 'running'""",
                        (running["id"],),
                    )
                return rows

        class ConnectionWithCancel:
            def __init__(self, connection):
                self.connection = connection

            def execute(self, sql, parameters=()):
                cursor = self.connection.execute(sql, parameters)
                if (
                    "FROM control_planning_jobs" in sql
                    and "WHERE status = 'running'" in sql
                ):
                    return CursorWithCancel(cursor, self.connection)
                return cursor

            def __getattr__(self, name):
                return getattr(self.connection, name)

        @contextmanager
        def connection_with_cancel():
            with original_connection() as connection:
                yield ConnectionWithCancel(connection)

        with patch.object(
            self.database,
            "_get_connection",
            connection_with_cancel,
        ):
            recovered = self.store.recover_interrupted_planning_jobs()

        self.assertEqual(recovered, 0)
        self.assertEqual(
            self.store.get_planning_job(running["id"])["status"],
            "cancelled",
        )

    def test_retry_starts_new_chat_with_existing_session_ledger(self):
        continued, question_id, _campaign_id = self._continued_session()
        self.store.fail_planning_job(
            continued["id"],
            "The existing planner chat became unavailable.",
        )

        retried = self.store.retry_planning_job(continued["id"], actor="owner")
        claimed = self.store.claim_planning_job()

        self.assertEqual(retried["antigravity_chat_id"], "")
        self.assertFalse(claimed["continuation"])
        self.assertEqual(claimed["attempt"], 2)
        self.assertEqual(
            [question["id"] for question in claimed["session_questions"]],
            [question_id],
        )
        prompt = AntiGravityTaskAdapter.build_planning_prompt(
            claimed,
            {"path": str(self.root), "name": "Socratic planning"},
        )
        self.assertIn("Which user-visible outcome defines success?", prompt)
        self.assertIn(
            "Success means a verified user can finish the flow.",
            prompt,
        )
        self.assertIn(
            "list every answered session question id",
            prompt.casefold(),
        )

    def test_repeated_question_is_rejected_as_no_progress(self):
        continued, question_id, campaign_id = self._continued_session()

        with self.assertRaises(ControlCenterError) as context:
            self.store.complete_planning_job(
                continued["id"],
                self._question("  WHICH user-visible outcome defines SUCCESS?  "),
            )

        self.assertEqual(context.exception.code, "planning_question_no_progress")
        current = self.store.get_planning_job(continued["id"])
        self.assertEqual(current["status"], "running")
        overview = self.store.overview(self.project_id)
        self.assertEqual(len(overview["campaigns"]), 1)
        self.assertEqual(overview["campaigns"][0]["id"], campaign_id)
        self.assertEqual(len(overview["campaigns"][0]["questions"]), 1)
        self.assertEqual(
            overview["campaigns"][0]["questions"][0]["id"],
            question_id,
        )

    def test_cancelled_session_rejects_late_final_plan_without_import(self):
        continued, question_id, campaign_id = self._continued_session()
        self.store.cancel_planning_job(
            continued["id"],
            actor="owner",
            reason="The direction changed.",
        )

        with self.assertRaises(ControlCenterError) as context:
            self.store.complete_planning_job(
                continued["id"],
                {
                    "type": "plan",
                    "resolved_question_ids": [question_id],
                    "plan": self._plan(),
                },
            )

        self.assertEqual(context.exception.code, "planning_job_not_running")
        self.assertEqual(
            self.store.get_planning_job(continued["id"])["status"],
            "cancelled",
        )
        overview = self.store.overview(self.project_id)
        self.assertEqual(len(overview["campaigns"]), 1)
        campaign = overview["campaigns"][0]
        self.assertEqual(campaign["id"], campaign_id)
        self.assertEqual(campaign["status"], "cancelled")
        self.assertEqual(campaign["pr_candidates"], [])
        self.assertEqual(campaign["questions"][0]["status"], "answered")

    def test_cancelled_job_rejects_late_chat_assignment(self):
        running = self._running_job()
        self.store.cancel_planning_job(
            running["id"],
            actor="owner",
            reason="Stop before the planner chat is registered.",
        )

        with self.assertRaises(ControlCenterError) as context:
            self.store.update_planning_job_chat(running["id"], "late-chat")

        self.assertEqual(context.exception.code, "planning_job_not_running")
        cancelled = self.store.get_planning_job(running["id"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["antigravity_chat_id"], "")

    def test_campaign_cancel_terminalizes_planning_job_metadata_idempotently(self):
        running = self._running_job()
        self.store.update_planning_job_chat(running["id"], "planner-chat-1")
        waiting = self.store.complete_planning_job(
            running["id"],
            self._question(),
        )

        self.store.cancel_campaign(
            waiting["campaign_id"],
            actor="owner",
            reason="The planning direction changed.",
        )
        cancelled = self.store.get_planning_job(running["id"])
        self.store.cancel_campaign(waiting["campaign_id"], actor="owner")
        replayed = self.store.get_planning_job(running["id"])

        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["waiting_reason"], "")
        self.assertIsNone(cancelled["active_question_id"])
        self.assertIsNotNone(cancelled["finished_at"])
        self.assertEqual(replayed, cancelled)

    def test_manual_question_answer_preserves_legacy_resolution_version(self):
        campaign = self.store.create_campaign(
            {
                "project_id": self.project_id,
                "title": "Manual planning ledger",
                "goal": "Keep the existing manual question workflow compatible.",
            }
        )
        question = self.store.add_planning_question(
            campaign["id"],
            {
                "branch": "scope",
                "question": "Which boundary remains outside this campaign?",
            },
        )

        answered = self.store.answer_planning_question(
            question["id"],
            {
                "answer": "Production deployment remains outside the campaign.",
                "answer_source": "owner",
            },
        )

        self.assertEqual(answered["status"], "answered")
        current_campaign = self.store.overview(self.project_id)["campaigns"][0]
        self.assertEqual(
            answered["resolved_in_version"],
            current_campaign["version"],
        )
        self.assertEqual(current_campaign["version"], campaign["version"] + 2)


if __name__ == "__main__":
    unittest.main()
