"""Public overview contracts for derived, read-only flow metrics."""

import tempfile
import unittest
from pathlib import Path

from src.control_center import ControlCenterStore
from src.database import Database


SHA = "a" * 40


class TestControlCenterFlowMetrics(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ag_flow_metrics_")
        self.root = Path(self.temp.name)
        self.database = Database(self.root / "control.db")
        self.project_id = self.database.add_project("Flow Alpha", str(self.root / "alpha"))
        self.other_project_id = self.database.add_project(
            "Flow Beta", str(self.root / "beta")
        )
        self.archived_project_id = self.database.add_project(
            "Flow Archived", str(self.root / "archived")
        )
        with self.database._get_connection() as conn:
            conn.execute(
                "UPDATE projects SET archived_at = CURRENT_TIMESTAMP WHERE id = ?",
                (self.archived_project_id,),
            )
        self.store = ControlCenterStore(self.database, sha_resolver=lambda _project: SHA)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _campaign(conn, project_id, suffix, status):
        campaign_id = f"campaign-{suffix}"
        conn.execute(
            """INSERT INTO control_campaigns (id, project_id, title, goal, status)
               VALUES (?, ?, ?, ?, ?)""",
            (campaign_id, project_id, f"Campaign {suffix}", "Measure flow.", status),
        )
        return campaign_id

    @staticmethod
    def _planning_job(conn, project_id, suffix, status):
        seed_id = f"seed-{suffix}"
        conn.execute(
            """INSERT INTO control_idea_seeds (id, project_id, title, note)
               VALUES (?, ?, ?, ?)""",
            (seed_id, project_id, f"Seed {suffix}", "Canonical planning input."),
        )
        conn.execute(
            """INSERT INTO control_planning_jobs (
                   id, project_id, idea_seed_id, status, planning_depth,
                   max_candidates, activation_policy, wish
               ) VALUES (?, ?, ?, ?, 'compact', 3, 'per_candidate', ?)""",
            (f"planning-{suffix}", project_id, seed_id, status, f"Plan {suffix}"),
        )

    @staticmethod
    def _task(conn, project_id, campaign_id, suffix, status):
        candidate_id = f"candidate-{suffix}"
        work_order_id = f"work-order-{suffix}"
        conn.execute(
            """INSERT INTO control_pr_candidates (
                   id, campaign_id, title, scope, acceptance_criteria_json, base_sha
               ) VALUES (?, ?, ?, ?, '[]', ?)""",
            (candidate_id, campaign_id, f"Candidate {suffix}", "Bounded scope.", SHA),
        )
        conn.execute(
            """INSERT INTO control_work_orders (
                   id, candidate_id, approval_sha, approved_by
               ) VALUES (?, ?, ?, 'owner')""",
            (work_order_id, candidate_id, SHA),
        )
        conn.execute(
            """INSERT INTO control_agent_tasks (
                   id, work_order_id, project_id, campaign_id, candidate_id,
                   status, base_sha, branch_name
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"task-{suffix}",
                work_order_id,
                project_id,
                campaign_id,
                candidate_id,
                status,
                SHA,
                f"ag/{suffix}",
            ),
        )

    @staticmethod
    def _metric(payload, key):
        return next(item for item in payload["flow_metrics"] if item["key"] == key)

    def _seed_deterministic_history(self):
        with self.database._get_connection() as conn:
            completed_campaign = self._campaign(
                conn, self.project_id, "alpha-completed", "completed"
            )
            active_campaign = self._campaign(conn, self.project_id, "alpha-active", "active")
            self._campaign(conn, self.project_id, "alpha-cancelled", "cancelled")

            for index, status in enumerate(
                ("completed", "completed", "failed", "cancelled", "queued"), start=1
            ):
                self._planning_job(conn, self.project_id, f"alpha-{index}", status)

            for index, status in enumerate(
                ("completed", "completed", "failed", "repair", "running", "cancelled"),
                start=1,
            ):
                campaign_id = completed_campaign if index <= 3 else active_campaign
                self._task(conn, self.project_id, campaign_id, f"alpha-{index}", status)

            for index in range(3):
                conn.execute(
                    """INSERT INTO control_question_ledger (
                           id, campaign_id, branch, question
                       ) VALUES (?, ?, 'scope', ?)""",
                    (f"question-alpha-{index}", active_campaign, f"Question {index}?"),
                )
            for index in range(2):
                conn.execute(
                    """INSERT INTO control_plan_amendments (
                           id, campaign_id, from_version, proposed_version,
                           reason, impact_json, proposed_by
                       ) VALUES (?, ?, 1, 2, 'New evidence', '{}', 'planner')""",
                    (f"amendment-alpha-{index}", active_campaign),
                )

            audit_rows = (
                ("task-alpha-4", "agent_task.transition", "running", "repair"),
                ("task-alpha-5", "human_test.rejected_for_repair", "waiting_human", "repair"),
                ("task-alpha-4", "finding.reopened", "resolved", "open"),
            )
            conn.executemany(
                """INSERT INTO control_audit_events (
                       project_id, entity_type, entity_id, action, actor, from_state, to_state
                   ) VALUES (?, 'agent_task', ?, ?, 'system', ?, ?)""",
                [
                    (self.project_id, entity_id, action, from_state, to_state)
                    for entity_id, action, from_state, to_state in audit_rows
                ],
            )

            conn.executemany(
                """INSERT INTO control_deployments (
                       id, project_id, environment, status, sha, rollback_of
                   ) VALUES (?, ?, 'staging', 'succeeded', ?, ?)""",
                (
                    ("deployment-alpha-1", self.project_id, SHA, None),
                    ("deployment-alpha-2", self.project_id, SHA, None),
                    ("deployment-alpha-rollback", self.project_id, SHA, "deployment-alpha-1"),
                ),
            )

            beta_campaign = self._campaign(
                conn, self.other_project_id, "beta-completed", "completed"
            )
            self._planning_job(conn, self.other_project_id, "beta-1", "completed")
            self._task(
                conn,
                self.other_project_id,
                beta_campaign,
                "beta-1",
                "completed",
            )

            archived_campaign = self._campaign(
                conn, self.archived_project_id, "archived-completed", "completed"
            )
            self._planning_job(conn, self.archived_project_id, "archived-1", "failed")
            self._task(
                conn,
                self.archived_project_id,
                archived_campaign,
                "archived-1",
                "failed",
            )
            conn.execute(
                """INSERT INTO control_audit_events (
                       project_id, entity_type, entity_id, action, actor, to_state
                   ) VALUES (?, 'agent_task', 'task-archived-1',
                             'agent_task.transition', 'system', 'repair')""",
                (self.archived_project_id,),
            )

    def test_overview_derives_deterministic_project_scoped_flow_metrics(self):
        self._seed_deterministic_history()

        overview = self.store.overview(self.project_id)

        planning = self._metric(overview, "planning_outcomes")
        self.assertEqual(
            (planning["value"], planning["numerator"], planning["denominator"]),
            (50.0, 2, 4),
        )
        self.assertEqual(
            planning["breakdown"],
            {"completed": 2, "failed": 1, "cancelled": 1},
        )

        campaigns = self._metric(overview, "campaign_progress")
        self.assertEqual((campaigns["value"], campaigns["sample_size"]), (33.3, 3))
        self.assertEqual(campaigns["breakdown"], {"completed": 1, "open": 1, "other": 1})

        tasks = self._metric(overview, "task_progress")
        self.assertEqual((tasks["value"], tasks["sample_size"]), (33.3, 6))
        self.assertEqual(
            tasks["breakdown"],
            {"completed": 2, "failed": 1, "active": 2, "other": 1},
        )

        expected_counts = {
            "human_questions": (3, 3),
            "repair_reopen_events": (3, 6),
            "plan_amendments": (2, 3),
            "deployment_rollbacks": (1, 2),
        }
        for key, expected in expected_counts.items():
            metric = self._metric(overview, key)
            self.assertEqual((metric["value"], metric["sample_size"]), expected)
            self.assertEqual(metric["unit"], "count")

        global_overview = self.store.overview()
        self.assertEqual(
            self._metric(global_overview, "planning_outcomes")["value"], 60.0
        )
        self.assertEqual(
            self._metric(global_overview, "campaign_progress")["sample_size"], 4
        )
        self.assertEqual(
            self._metric(global_overview, "task_progress")["sample_size"], 7
        )
        self.assertEqual(
            self._metric(global_overview, "repair_reopen_events")["value"], 3
        )

    def test_empty_scope_returns_null_values_instead_of_misleading_zero_rates(self):
        overview = self.store.overview(self.other_project_id)

        self.assertEqual(len(overview["flow_metrics"]), 7)
        for metric in overview["flow_metrics"]:
            self.assertIsNone(metric["value"])
            self.assertEqual(metric["numerator"], 0)
            self.assertEqual(metric["denominator"], 0)
            self.assertEqual(metric["sample_size"], 0)
            self.assertNotIn("project_id", metric)
            self.assertNotIn(str(self.other_project_id), metric["label"])

    def test_overview_flow_metrics_do_not_mutate_the_database(self):
        self._seed_deterministic_history()
        tables = (
            "control_planning_jobs",
            "control_campaigns",
            "control_agent_tasks",
            "control_question_ledger",
            "control_audit_events",
            "control_plan_amendments",
            "control_deployments",
        )
        with self.database._get_connection() as observer:
            before_version = observer.execute("PRAGMA data_version").fetchone()[0]
            before_counts = {
                table: observer.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in tables
            }

            self.store.overview(self.project_id)

            after_version = observer.execute("PRAGMA data_version").fetchone()[0]
            after_counts = {
                table: observer.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in tables
            }

        self.assertEqual(after_version, before_version)
        self.assertEqual(after_counts, before_counts)


if __name__ == "__main__":
    unittest.main()
