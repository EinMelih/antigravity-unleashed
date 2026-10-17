"""Backward-compatible Control Center schema upgrade contracts."""

import tempfile
import unittest
from pathlib import Path

from src.control_center import ControlCenterStore
from src.database import Database


class TestControlCenterSchemaMigrations(unittest.TestCase):
    def test_legacy_planning_tables_gain_session_columns_idempotently(self):
        with tempfile.TemporaryDirectory(prefix="ag_schema_upgrade_") as temp:
            database = Database(Path(temp) / "control.db")
            with database._get_connection() as conn:
                conn.execute(
                    """CREATE TABLE control_campaign_profiles (
                           campaign_id TEXT PRIMARY KEY, slug TEXT NOT NULL,
                           planning_depth TEXT NOT NULL DEFAULT 'balanced',
                           requested_max_candidates INTEGER NOT NULL DEFAULT 12,
                           activation_policy TEXT NOT NULL DEFAULT 'per_candidate',
                           readiness_status TEXT NOT NULL DEFAULT 'draft',
                           readiness_score REAL NOT NULL DEFAULT 0,
                           pivotal_fork TEXT NOT NULL DEFAULT '',
                           success_metrics_json TEXT NOT NULL DEFAULT '[]',
                           constraints_json TEXT NOT NULL DEFAULT '[]',
                           assumptions_json TEXT NOT NULL DEFAULT '[]',
                           acceptance_matrix_json TEXT NOT NULL DEFAULT '[]',
                           rollout_plan TEXT NOT NULL DEFAULT '',
                           rollback_plan TEXT NOT NULL DEFAULT '',
                           repository_map_artifact_id TEXT,
                           design_artifact_id TEXT,
                           plan_simulation_artifact_id TEXT,
                           plan_signature TEXT NOT NULL DEFAULT '',
                           current_wave INTEGER NOT NULL DEFAULT 0,
                           estimated_cost REAL NOT NULL DEFAULT 0,
                           actual_cost REAL NOT NULL DEFAULT 0,
                           started_at TIMESTAMP, completed_at TIMESTAMP,
                           updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                       )"""
                )
                conn.execute(
                    """CREATE TABLE control_question_ledger (
                           id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL,
                           branch TEXT NOT NULL, question TEXT NOT NULL,
                           rationale TEXT NOT NULL DEFAULT '',
                           answer TEXT NOT NULL DEFAULT '',
                           answer_source TEXT NOT NULL DEFAULT '',
                           status TEXT NOT NULL DEFAULT 'open',
                           owner TEXT NOT NULL DEFAULT '',
                           evidence_json TEXT NOT NULL DEFAULT '{}',
                           contradiction_of TEXT, resolved_in_version INTEGER,
                           created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                           updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                       )"""
                )
                conn.execute(
                    """CREATE TABLE control_planning_jobs (
                           id TEXT PRIMARY KEY, project_id INTEGER NOT NULL,
                           idea_seed_id TEXT NOT NULL,
                           status TEXT NOT NULL DEFAULT 'queued',
                           planning_depth TEXT NOT NULL,
                           max_candidates INTEGER NOT NULL,
                           activation_policy TEXT NOT NULL,
                           wish TEXT NOT NULL,
                           constraints_json TEXT NOT NULL DEFAULT '[]',
                           antigravity_chat_id TEXT NOT NULL DEFAULT '',
                           campaign_id TEXT, attempt INTEGER NOT NULL DEFAULT 0,
                           output_json TEXT NOT NULL DEFAULT '{}',
                           last_error TEXT NOT NULL DEFAULT '',
                           created_by TEXT NOT NULL DEFAULT 'human',
                           created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                           started_at TIMESTAMP, finished_at TIMESTAMP,
                           updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                       )"""
                )
                conn.commit()

            ControlCenterStore(database)
            project_id = database.add_project("Legacy planning", temp)
            with database._get_connection() as conn:
                conn.execute(
                    """INSERT INTO control_idea_seeds
                       (id, project_id, title, note)
                       VALUES ('IDEA-LEGACY', ?, 'Legacy idea', 'Legacy note')""",
                    (project_id,),
                )
                conn.execute(
                    """INSERT INTO control_campaigns
                       (id, project_id, title, goal)
                       VALUES ('CMP-LEGACY', ?, 'Legacy plan', 'Legacy goal')""",
                    (project_id,),
                )
                conn.execute(
                    """INSERT INTO control_planning_jobs (
                           id, project_id, idea_seed_id, status,
                           planning_depth, max_candidates, activation_policy,
                           wish, campaign_id, waiting_reason
                       ) VALUES (
                           'PLAN-LEGACY', ?, 'IDEA-LEGACY', 'waiting_human',
                           'compact', 1, 'per_candidate', 'Legacy planning wish',
                           'CMP-LEGACY', ''
                       )""",
                    (project_id,),
                )
                for suffix, campaign_status in (
                    ("APPROVED", "approved"),
                    ("CANCELLED", "cancelled"),
                ):
                    conn.execute(
                        """INSERT INTO control_idea_seeds
                           (id, project_id, title, note)
                           VALUES (?, ?, ?, 'Legacy note')""",
                        (f"IDEA-{suffix}", project_id, f"{suffix} idea"),
                    )
                    conn.execute(
                        """INSERT INTO control_campaigns
                           (id, project_id, title, goal, status)
                           VALUES (?, ?, ?, 'Legacy goal', ?)""",
                        (
                            f"CMP-{suffix}",
                            project_id,
                            f"{suffix} plan",
                            campaign_status,
                        ),
                    )
                    conn.execute(
                        """INSERT INTO control_planning_jobs (
                               id, project_id, idea_seed_id, status,
                               planning_depth, max_candidates, activation_policy,
                               wish, campaign_id, waiting_reason
                           ) VALUES (
                               ?, ?, ?, 'waiting_human', 'compact', 1,
                               'per_candidate', 'Legacy planning wish', ?, ''
                           )""",
                        (
                            f"PLAN-{suffix}",
                            project_id,
                            f"IDEA-{suffix}",
                            f"CMP-{suffix}",
                        ),
                    )
                conn.execute(
                    """UPDATE control_campaigns
                       SET approved_version = 1
                       WHERE id = 'CMP-APPROVED'"""
                )
                conn.execute(
                    """INSERT INTO control_campaign_profiles (
                           campaign_id, slug, readiness_status
                       ) VALUES ('CMP-APPROVED', 'approved-plan', 'approved')"""
                )
                conn.execute(
                    """INSERT OR REPLACE INTO control_repository_policies (
                           project_id, protected_paths_json, capability_json
                       ) VALUES (?, '[]', '{}')""",
                    (project_id,),
                )
                conn.commit()

            upgraded_store = ControlCenterStore(database)

            with database._get_connection() as conn:
                job_columns = {
                    row["name"]
                    for row in conn.execute(
                        "PRAGMA table_info(control_planning_jobs)"
                    ).fetchall()
                }
                question_columns = {
                    row["name"]
                    for row in conn.execute(
                        "PRAGMA table_info(control_question_ledger)"
                    ).fetchall()
                }
                profile_columns = {
                    row["name"]
                    for row in conn.execute(
                        "PRAGMA table_info(control_campaign_profiles)"
                    ).fetchall()
                }
                indexes = {
                    row["name"]
                    for row in conn.execute(
                        "PRAGMA index_list(control_question_ledger)"
                    ).fetchall()
                }

            self.assertTrue(
                {"waiting_reason", "active_question_id", "round_number"}
                <= job_columns
            )
            self.assertTrue(
                {"planning_job_id", "content_hash"} <= question_columns
            )
            self.assertTrue(
                {
                    "alternatives_json",
                    "review_strategy",
                    "pivotal_fork_na_reason",
                }
                <= profile_columns
            )
            self.assertIn(
                "idx_control_questions_unique_session_content",
                indexes,
            )
            self.assertEqual(
                upgraded_store.get_planning_job("PLAN-LEGACY")["waiting_reason"],
                "plan_approval",
            )
            self.assertEqual(
                upgraded_store.get_planning_job("PLAN-APPROVED")["status"],
                "completed",
            )
            self.assertEqual(
                upgraded_store.get_planning_job("PLAN-CANCELLED")["status"],
                "cancelled",
            )
            self.assertTrue(
                upgraded_store.get_repository_policy(project_id)["capability"][
                    "read_repository"
                ]
            )
            historical = upgraded_store.evaluate_campaign_readiness(
                "CMP-APPROVED",
                persist=True,
            )
            self.assertTrue(historical["ready"])
            self.assertTrue(historical["grandfathered_approval"])
            self.assertEqual(historical["status"], "approved")


if __name__ == "__main__":
    unittest.main()
