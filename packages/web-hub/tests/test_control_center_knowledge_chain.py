"""Durable, source-backed knowledge-chain contracts."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.control_center import ControlCenterError, ControlCenterStore
from src.control_center_handlers import handle_knowledge_chains
from src.database import Database


class TracingDatabase(Database):
    def __init__(self, db_path: Path) -> None:
        self.traced_statements: list[str] = []
        super().__init__(db_path)

    def _get_connection(self):
        connection = super()._get_connection()
        connection.set_trace_callback(self.traced_statements.append)
        return connection


class TestKnowledgeSchemaMigration(unittest.TestCase):
    def test_legacy_artifacts_gain_materialization_and_relation_schema_idempotently(self):
        with tempfile.TemporaryDirectory(prefix="ag_knowledge_schema_") as temp:
            database = Database(Path(temp) / "control.db")
            with database._get_connection() as conn:
                conn.execute(
                    """CREATE TABLE control_artifacts (
                           id TEXT PRIMARY KEY, project_id INTEGER NOT NULL,
                           campaign_id TEXT, artifact_type TEXT NOT NULL,
                           slug TEXT NOT NULL, title TEXT NOT NULL,
                           status TEXT NOT NULL DEFAULT 'draft',
                           version INTEGER NOT NULL DEFAULT 1,
                           supersedes_id TEXT,
                           relative_path TEXT NOT NULL DEFAULT '',
                           content_text TEXT NOT NULL DEFAULT '',
                           content_sha256 TEXT NOT NULL DEFAULT '',
                           metadata_json TEXT NOT NULL DEFAULT '{}',
                           created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                           updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                           UNIQUE(project_id, artifact_type, slug, version)
                       )"""
                )
                conn.commit()

            ControlCenterStore(database)
            ControlCenterStore(database)

            with database._get_connection() as conn:
                artifact_columns = {
                    row["name"]: row
                    for row in conn.execute(
                        "PRAGMA table_info(control_artifacts)"
                    ).fetchall()
                }
                relation_tables = {
                    str(row["name"])
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                foreign_keys = {
                    table: {
                        (str(row["from"]), str(row["table"]), str(row["to"]))
                        for row in conn.execute(
                            f"PRAGMA foreign_key_list({table})"
                        ).fetchall()
                    }
                    for table in (
                        "control_idea_seed_artifacts",
                        "control_artifact_relations",
                        "control_candidate_artifacts",
                    )
                }
                indexes = {
                    table: {
                        str(row["name"])
                        for row in conn.execute(
                            f"PRAGMA index_list({table})"
                        ).fetchall()
                    }
                    for table in foreign_keys
                }

            self.assertTrue(
                {
                    "materialization_status",
                    "materialized_sha256",
                    "materialized_commit_sha",
                    "materialized_at",
                }
                <= set(artifact_columns)
            )
            self.assertEqual(
                artifact_columns["materialization_status"]["dflt_value"],
                "'unknown'",
            )
            self.assertTrue(
                {
                    "control_idea_seed_artifacts",
                    "control_artifact_relations",
                    "control_candidate_artifacts",
                }
                <= relation_tables
            )
            self.assertEqual(
                foreign_keys["control_idea_seed_artifacts"],
                {
                    ("idea_seed_id", "control_idea_seeds", "id"),
                    ("artifact_id", "control_artifacts", "id"),
                },
            )
            self.assertEqual(
                foreign_keys["control_artifact_relations"],
                {
                    ("source_artifact_id", "control_artifacts", "id"),
                    ("target_artifact_id", "control_artifacts", "id"),
                },
            )
            self.assertEqual(
                foreign_keys["control_candidate_artifacts"],
                {
                    ("candidate_id", "control_pr_candidates", "id"),
                    ("artifact_id", "control_artifacts", "id"),
                },
            )
            self.assertIn(
                "idx_control_idea_seed_artifacts_artifact",
                indexes["control_idea_seed_artifacts"],
            )
            self.assertIn(
                "idx_control_artifact_relations_target",
                indexes["control_artifact_relations"],
            )
            self.assertIn(
                "idx_control_candidate_artifacts_artifact",
                indexes["control_candidate_artifacts"],
            )


class TestKnowledgeLinking(unittest.TestCase):
    SHA = "a" * 40

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ag_knowledge_links_")
        self.root = Path(self.temp.name)
        self.database = TracingDatabase(self.root / "control.db")
        self.project_id = self.database.add_project(
            "Knowledge links",
            str(self.root),
        )
        self.store = ControlCenterStore(
            self.database,
            sha_resolver=lambda _project, _requested="": self.SHA,
            repository_reader=lambda _project, _sha, path: (
                "class PlanningJobMixin:\n    pass\n"
                if path == "src/control_center/planning_jobs.py"
                else None
            ),
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _campaign(self):
        return self.store.create_campaign(
            {
                "project_id": self.project_id,
                "title": "Durable knowledge chain",
                "goal": "Keep every implementation linked to its source decisions.",
                "non_goals": "Do not infer external provider state.",
                "base_sha": self.SHA,
                "planning_depth": "compact",
                "max_candidates": 2,
            }
        )

    def _artifact(self, campaign_id: str, artifact_type: str, title: str):
        return self.store.save_artifact(
            {
                "project_id": self.project_id,
                "campaign_id": campaign_id,
                "artifact_type": artifact_type,
                "title": title,
                "content": f"# {title}\n\nVerified knowledge content.",
                "status": "proposed",
                "materialize": False,
            }
        )

    def _campaign_version(self, campaign_id: str) -> int:
        campaign = next(
            item
            for item in self.store.overview(self.project_id)["campaigns"]
            if item["id"] == campaign_id
        )
        return int(campaign["version"])

    @staticmethod
    def _generated_plan():
        return {
            "title": "Traceable knowledge delivery",
            "goal": "Keep the implementation chain traceable from idea to deployment.",
            "non_goals": "Do not claim unobserved GitHub or deployment state.",
            "risk_level": "medium",
            "pivotal_fork": "Store semantic links instead of duplicating documents.",
            "success_metrics": ["Every PR slice links to its design and decision."],
            "alternatives": [
                {
                    "title": "Semantic relation tables",
                    "mechanism": "Persist typed links between durable entities.",
                    "tradeoffs": "Adds schema, but keeps one source of truth.",
                },
                {
                    "title": "Markdown-only references",
                    "mechanism": "Store links only as unstructured document text.",
                    "tradeoffs": "Less schema, but no reliable traversal or coverage.",
                },
            ],
            "review_strategy": "Review schema, generated documents, links, and redaction.",
            "rollout_plan": "Read the chain in the private control database first.",
            "rollback_plan": "Revert the additive schema and generated draft rows.",
            "repository_map": (
                "# Repository map\n\n"
                "`src/control_center/planning_jobs.py` imports generated plans."
            ),
            "branch_assessments": [
                {
                    "branch": branch,
                    "question": f"What repository fact grounds {branch}?",
                    "rationale": f"The importer owns the {branch} impact.",
                    "status": "grounded",
                    "owner": "repository-mapper",
                    "evidence": {
                        "path": "src/control_center/planning_jobs.py"
                    },
                }
                for branch in ("architecture", "data", "security", "operations")
            ],
            "candidates": [
                {
                    "id": "slice-01",
                    "title": "Expose knowledge chain",
                    "scope": "Implement the durable knowledge-chain vertical slice.",
                    "purpose": "Make provenance traversable without duplicated content.",
                    "non_goals": "Do not expose private artifact bodies.",
                    "components": ["src/control_center/knowledge.py"],
                    "expected_diff_type": "code-and-tests",
                    "acceptance_criteria": [
                        "The knowledge chain is linked from seed through PR slice."
                    ],
                    "required_checks": ["focused unit tests"],
                    "manual_tests": ["Open the read-only Knowledge view."],
                    "reversibility": "Revert the additive change.",
                    "migration_plan": "Use additive tables and columns.",
                    "compatibility_plan": "Keep legacy artifacts readable.",
                    "documentation_changes": ["Document the knowledge read model."],
                    "definition_of_done": "The focused knowledge tests pass.",
                    "risk_level": "medium",
                    "priority": 10,
                    "depends_on": [],
                }
            ],
        }

    def test_new_draft_link_invalidates_once_and_exact_replay_is_idempotent(self):
        campaign = self._campaign()
        design = self._artifact(
            campaign["id"],
            "design_document",
            "Knowledge design",
        )
        decision = self._artifact(
            campaign["id"],
            "adr",
            "Knowledge decision",
        )
        with self.database._get_connection() as conn:
            conn.execute(
                """UPDATE control_campaign_profiles
                   SET plan_signature = ? WHERE campaign_id = ?""",
                ("f" * 64, campaign["id"]),
            )
            conn.commit()
        before_version = self._campaign_version(campaign["id"])
        payload = {
            "source_kind": "artifact",
            "source_id": design["id"],
            "target_kind": "artifact",
            "target_id": decision["id"],
            "relation_type": "decided_by",
        }

        created = self.store.link_knowledge(payload, actor="planner")
        replay = self.store.link_knowledge(payload, actor="planner")

        self.assertTrue(created["created"])
        self.assertFalse(replay["created"])
        self.assertEqual(created["relation"], replay["relation"])
        self.assertEqual(
            self._campaign_version(campaign["id"]),
            before_version + 1,
        )
        self.assertEqual(
            self.store.get_campaign_profile(campaign["id"])["plan_signature"],
            "",
        )

    def test_links_reject_inverse_cross_project_and_locked_plan_mutations(self):
        campaign = self._campaign()
        design = self._artifact(
            campaign["id"],
            "design_document",
            "Validated design",
        )
        decision = self._artifact(
            campaign["id"],
            "adr",
            "Validated decision",
        )
        repository_map = self._artifact(
            campaign["id"],
            "repository_map",
            "Validated repository map",
        )
        self.store.link_knowledge(
            {
                "source_kind": "artifact",
                "source_id": design["id"],
                "target_kind": "artifact",
                "target_id": decision["id"],
                "relation_type": "decided_by",
            }
        )

        with self.assertRaises(ControlCenterError) as inverse_context:
            self.store.link_knowledge(
                {
                    "source_kind": "artifact",
                    "source_id": decision["id"],
                    "target_kind": "artifact",
                    "target_id": design["id"],
                    "relation_type": "decided_by",
                }
            )
        self.assertEqual(
            inverse_context.exception.code,
            "inverse_knowledge_relation",
        )

        other_root = self.root / "other"
        other_root.mkdir()
        other_project_id = self.database.add_project(
            "Other knowledge project",
            str(other_root),
        )
        other_seed = self.store.create_idea_seed(
            {
                "project_id": other_project_id,
                "title": "Other project seed",
                "note": "This seed must remain in its own project.",
            }
        )
        with self.assertRaises(ControlCenterError) as project_context:
            self.store.link_knowledge(
                {
                    "source_kind": "idea_seed",
                    "source_id": other_seed["id"],
                    "target_kind": "artifact",
                    "target_id": design["id"],
                    "relation_type": "developed_into",
                }
            )
        self.assertEqual(
            project_context.exception.code,
            "knowledge_project_mismatch",
        )

        with self.database._get_connection() as conn:
            conn.execute(
                "UPDATE control_campaigns SET status = 'approved' WHERE id = ?",
                (campaign["id"],),
            )
            conn.commit()
        with self.assertRaises(ControlCenterError) as lock_context:
            self.store.link_knowledge(
                {
                    "source_kind": "artifact",
                    "source_id": design["id"],
                    "target_kind": "artifact",
                    "target_id": repository_map["id"],
                    "relation_type": "references",
                }
            )
        self.assertEqual(lock_context.exception.code, "campaign_locked")

    def test_artifact_materialization_state_reports_only_completed_work(self):
        campaign = self._campaign()
        database_only = self.store.save_artifact(
            {
                "project_id": self.project_id,
                "campaign_id": campaign["id"],
                "artifact_type": "design_document",
                "title": "Database-only design",
                "content": "# Database-only design\n\nNo file was requested.",
                "status": "proposed",
                "materialize": False,
            }
        )
        materialized = self.store.save_artifact(
            {
                "project_id": self.project_id,
                "campaign_id": campaign["id"],
                "artifact_type": "adr",
                "title": "Materialized decision",
                "content": "# Materialized decision\n\nThe file write completed.",
                "status": "proposed",
                "materialize": True,
            }
        )

        self.assertEqual(
            database_only["materialization_status"],
            "not_requested",
        )
        self.assertEqual(database_only["materialized_sha256"], "")
        self.assertEqual(database_only["materialized_commit_sha"], "")
        self.assertIsNone(database_only["materialized_at"])
        self.assertEqual(materialized["materialization_status"], "materialized")
        self.assertEqual(materialized["materialized_commit_sha"], "")
        self.assertIsNotNone(materialized["materialized_at"])
        destination = self.root / materialized["relative_path"]
        self.assertTrue(destination.is_file())
        materialized_digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        self.assertEqual(materialized["materialized_sha256"], materialized_digest)
        self.assertNotEqual(materialized["content_sha256"], materialized_digest)
        self.assertEqual(
            destination.read_text(encoding="utf-8"),
            "# Materialized decision\n\nThe file write completed.\n",
        )

    def test_plan_signature_binds_relations_but_not_materialization_state(self):
        campaign = self._campaign()
        design = self._artifact(
            campaign["id"],
            "design_document",
            "Signed knowledge design",
        )
        decision = self._artifact(
            campaign["id"],
            "adr",
            "Signed knowledge decision",
        )
        before = self.store.evaluate_campaign_readiness(
            campaign["id"],
            persist=False,
        )
        with self.database._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self.store._record_knowledge_link_in_connection(
                conn,
                {
                    "source_kind": "artifact",
                    "source_id": design["id"],
                    "target_kind": "artifact",
                    "target_id": decision["id"],
                    "relation_type": "decided_by",
                },
                actor="planner",
                invalidate_plan=False,
            )
            conn.commit()
        linked = self.store.evaluate_campaign_readiness(
            campaign["id"],
            persist=False,
        )
        with self.database._get_connection() as conn:
            conn.execute(
                """UPDATE control_artifacts
                   SET materialization_status = 'materialized',
                       materialized_sha256 = content_sha256,
                       materialized_commit_sha = ?,
                       materialized_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                ("b" * 40, design["id"]),
            )
            conn.commit()
        materialized = self.store.evaluate_campaign_readiness(
            campaign["id"],
            persist=False,
        )

        self.assertEqual(linked["plan_signature_version"], 2)
        self.assertNotEqual(
            before["plan_signature"],
            linked["plan_signature"],
        )
        self.assertEqual(
            linked["plan_signature"],
            materialized["plan_signature"],
        )

    def test_final_planner_import_creates_complete_linked_idea_group(self):
        seed = self.store.create_idea_seed(
            {
                "project_id": self.project_id,
                "title": "Trace knowledge from idea to delivery",
                "note": "Keep design decisions available to every PR slice.",
                "source": "human",
            }
        )
        job = self.store.create_planning_job(
            {
                "idea_seed_id": seed["id"],
                "wish": "Plan one traceable and reviewable knowledge-chain slice.",
                "planning_depth": "compact",
                "max_candidates": 1,
            }
        )
        self.store.claim_planning_job()

        waiting = self.store.complete_planning_job(
            job["id"],
            self._generated_plan(),
        )

        artifacts = self.store.list_artifacts(
            self.project_id,
            waiting["campaign_id"],
        )
        idea_group = [
            artifact
            for artifact in artifacts
            if artifact["artifact_type"] == "idea_group"
        ]
        self.assertEqual(len(idea_group), 5)
        self.assertEqual(
            {Path(artifact["relative_path"]).name for artifact in idea_group},
            {"README.md", "idea.md", "context.md", "sources.md", "decisions.md"},
        )
        self.assertEqual(
            {artifact["materialization_status"] for artifact in idea_group},
            {"not_requested"},
        )
        root = next(
            artifact
            for artifact in idea_group
            if artifact["relative_path"].endswith("/README.md")
        )
        design = next(
            artifact
            for artifact in artifacts
            if artifact["artifact_type"] == "design_document"
        )
        decision = next(
            artifact
            for artifact in artifacts
            if artifact["artifact_type"] == "adr"
        )
        self.assertIn(
            "Keep the implementation chain traceable",
            design["content_text"],
        )
        self.assertIn(
            "Store semantic links instead of duplicating documents",
            decision["content_text"],
        )
        candidate = self.store.overview(self.project_id)["campaigns"][0][
            "pr_candidates"
        ][0]
        expected_links = [
            {
                "source_kind": "idea_seed",
                "source_id": seed["id"],
                "target_kind": "artifact",
                "target_id": root["id"],
                "relation_type": "developed_into",
            },
            *[
                {
                    "source_kind": "artifact",
                    "source_id": root["id"],
                    "target_kind": "artifact",
                    "target_id": artifact["id"],
                    "relation_type": "contains",
                }
                for artifact in idea_group
                if artifact["id"] != root["id"]
            ],
            {
                "source_kind": "artifact",
                "source_id": root["id"],
                "target_kind": "artifact",
                "target_id": design["id"],
                "relation_type": "informs",
            },
            {
                "source_kind": "artifact",
                "source_id": design["id"],
                "target_kind": "artifact",
                "target_id": decision["id"],
                "relation_type": "decided_by",
            },
            {
                "source_kind": "candidate",
                "source_id": candidate["id"],
                "target_kind": "artifact",
                "target_id": design["id"],
                "relation_type": "implements_design",
            },
            {
                "source_kind": "candidate",
                "source_id": candidate["id"],
                "target_kind": "artifact",
                "target_id": decision["id"],
                "relation_type": "follows_decision",
            },
        ]
        before_replays = self._campaign_version(waiting["campaign_id"])
        for payload in expected_links:
            self.assertFalse(
                self.store.link_knowledge(payload, actor="planner")["created"]
            )
        self.assertEqual(
            self._campaign_version(waiting["campaign_id"]),
            before_replays,
        )

    def test_linked_idea_seed_cannot_cross_campaign_boundaries(self):
        seed = self.store.create_idea_seed(
            {
                "project_id": self.project_id,
                "title": "Campaign-bound provenance",
                "note": "Keep one idea seed inside its generated Campaign.",
            }
        )
        job = self.store.create_planning_job(
            {
                "idea_seed_id": seed["id"],
                "wish": "Generate one Campaign-bound knowledge chain.",
                "planning_depth": "compact",
                "max_candidates": 1,
            }
        )
        self.store.claim_planning_job()
        generated = self.store.complete_planning_job(
            job["id"],
            self._generated_plan(),
        )
        other_campaign = self._campaign()
        other_artifact = self._artifact(
            other_campaign["id"],
            "design_document",
            "Unrelated Campaign design",
        )

        with self.assertRaises(ControlCenterError) as context:
            self.store.link_knowledge(
                {
                    "source_kind": "idea_seed",
                    "source_id": seed["id"],
                    "target_kind": "artifact",
                    "target_id": other_artifact["id"],
                    "relation_type": "developed_into",
                }
            )

        self.assertEqual(context.exception.code, "knowledge_campaign_mismatch")
        chain = next(
            item
            for item in self.store.get_knowledge_chains(self.project_id)["chains"]
            if item["campaign"]["id"] == generated["campaign_id"]
        )
        self.assertEqual(chain["idea_seed"]["id"], seed["id"])

    def test_final_import_rolls_back_every_knowledge_row_on_late_failure(self):
        seed = self.store.create_idea_seed(
            {
                "project_id": self.project_id,
                "title": "Atomic knowledge import",
                "note": "Never retain a partial Campaign or document chain.",
            }
        )
        job = self.store.create_planning_job(
            {
                "idea_seed_id": seed["id"],
                "wish": "Import the complete knowledge chain in one transaction.",
                "planning_depth": "compact",
                "max_candidates": 1,
            }
        )
        self.store.claim_planning_job()
        invalid_plan = self._generated_plan()
        invalid_plan["adr"] = {"unexpected": "object"}

        with self.assertRaises(ControlCenterError) as context:
            self.store.complete_planning_job(job["id"], invalid_plan)

        self.assertEqual(context.exception.code, "invalid_generated_adr")
        self.assertEqual(self.store.overview(self.project_id)["campaigns"], [])
        self.assertEqual(self.store.list_artifacts(self.project_id), [])
        self.assertEqual(self.store.get_planning_job(job["id"])["status"], "running")
        self.assertEqual(self.store.get_idea_seed(seed["id"])["status"], "planning")

    def test_read_model_is_bundled_truthful_redacted_and_shows_unlinked_nodes(self):
        seed = self.store.create_idea_seed(
            {
                "project_id": self.project_id,
                "title": "Knowledge read model",
                "note": "Expose provenance without private document bodies.",
            }
        )
        job = self.store.create_planning_job(
            {
                "idea_seed_id": seed["id"],
                "wish": "Build one redacted knowledge-chain projection.",
                "planning_depth": "compact",
                "max_candidates": 1,
            }
        )
        self.store.claim_planning_job()
        waiting = self.store.complete_planning_job(
            job["id"],
            self._generated_plan(),
        )
        campaign_id = waiting["campaign_id"]
        candidate = self.store.overview(self.project_id)["campaigns"][0][
            "pr_candidates"
        ][0]
        unlinked_seed = self.store.create_idea_seed(
            {
                "project_id": self.project_id,
                "title": "Unlinked future idea",
                "note": "This idea has not entered planning yet.",
            }
        )
        unlinked_artifact = self.store.save_artifact(
            {
                "project_id": self.project_id,
                "campaign_id": campaign_id,
                "artifact_type": "test_pack",
                "title": "Unlinked private pack",
                "content": "private-content-secret",
                "metadata": {"token": "metadata-secret"},
                "materialize": False,
            }
        )
        with self.database._get_connection() as conn:
            conn.execute(
                """INSERT INTO control_pr_candidates (
                       id, campaign_id, title, scope,
                       acceptance_criteria_json, priority, base_sha
                   ) VALUES (
                       'PRC-UNLINKED', ?, 'Unlinked candidate',
                       'A candidate without knowledge links.',
                       '["Keep it visible as unlinked."]', 999, ?
                   )""",
                (campaign_id, self.SHA),
            )
            conn.execute(
                """INSERT INTO control_work_orders (
                       id, candidate_id, approval_sha, approved_by
                   ) VALUES ('WO-KNOWLEDGE', ?, ?, 'owner')""",
                (candidate["id"], self.SHA),
            )
            conn.execute(
                """INSERT INTO control_agent_tasks (
                       id, work_order_id, project_id, campaign_id,
                       candidate_id, status, base_sha, current_sha,
                       merged_sha, branch_name, issue_number, issue_url,
                       pr_number, pr_url
                   ) VALUES (
                       'TASK-KNOWLEDGE', 'WO-KNOWLEDGE', ?, ?, ?,
                       'review_ready', ?, ?, '', 'ag/knowledge',
                       12, 'ftp://user:super-secret@example.test/build?token=hidden',
                       34, 'https://github.com/org/repo/pull/34?token=hidden'
                   )""",
                (
                    self.project_id,
                    campaign_id,
                    candidate["id"],
                    self.SHA,
                    "b" * 40,
                ),
            )
            conn.execute(
                """INSERT INTO control_evidence_packs (
                       id, task_id, project_id, candidate_id,
                       sha, status, summary
                   ) VALUES (
                       'EVD-KNOWLEDGE', 'TASK-KNOWLEDGE', ?, ?, ?,
                       'ready', 'Focused checks and human review are recorded.'
                   )""",
                (self.project_id, candidate["id"], "b" * 40),
            )
            conn.execute(
                """INSERT INTO control_deployments (
                       id, task_id, project_id, environment, status, sha,
                       artifact_ref, previous_stable_sha, logs_json
                   ) VALUES (
                       'DEP-KNOWLEDGE', 'TASK-KNOWLEDGE', ?, 'staging',
                       'planned', ?,
                       'artifact/path?password=hidden#private-fragment', ?,
                       '["password=super-secret"]'
                   )""",
                (self.project_id, "b" * 40, self.SHA),
            )
            conn.commit()

        self.database.traced_statements.clear()
        first = self.store.get_knowledge_chains(self.project_id)
        first_select_count = sum(
            statement.lstrip().upper().startswith("SELECT")
            for statement in self.database.traced_statements
        )
        self.database.traced_statements.clear()
        second = self.store.get_knowledge_chains(self.project_id)

        self.assertEqual(first, second)
        self.assertLessEqual(first_select_count, 12)
        chain = next(
            chain
            for chain in first["chains"]
            if chain["campaign"]["id"] == campaign_id
        )
        self.assertEqual(chain["idea_seed"]["id"], seed["id"])
        branch = next(
            branch
            for branch in chain["branches"]
            if branch["candidate"]["id"] == candidate["id"]
        )
        self.assertEqual(branch["task"]["issue_number"], 12)
        self.assertEqual(branch["task"]["pr_number"], 34)
        self.assertEqual(branch["task"]["issue_url"], "")
        self.assertEqual(
            branch["task"]["pr_url"],
            "https://github.com/org/repo/pull/34",
        )
        self.assertEqual(branch["evidence"]["id"], "EVD-KNOWLEDGE")
        self.assertEqual(branch["deployments"][0]["id"], "DEP-KNOWLEDGE")
        self.assertEqual(
            branch["deployments"][0]["artifact_ref"],
            "artifact/path",
        )
        self.assertEqual(
            branch["deployments"][0]["previous_stable_sha"],
            self.SHA,
        )
        self.assertIn(
            unlinked_seed["id"],
            {item["id"] for item in first["unlinked"]["idea_seeds"]},
        )
        self.assertIn(
            unlinked_artifact["id"],
            {item["id"] for item in first["unlinked"]["artifacts"]},
        )
        self.assertIn(
            "PRC-UNLINKED",
            {item["id"] for item in first["unlinked"]["candidates"]},
        )
        self.assertGreaterEqual(chain["coverage"]["linked_artifacts"], 7)
        self.assertGreaterEqual(chain["coverage"]["unlinked_artifacts"], 1)
        serialized = json.dumps(first, ensure_ascii=False)
        for forbidden in (
            "private-content-secret",
            "metadata-secret",
            "super-secret",
            "access_token=hidden",
            "token=hidden",
            "password=hidden",
            "content_text",
            "metadata_json",
            "logs_json",
        ):
            self.assertNotIn(forbidden, serialized)


class TestKnowledgeChainHTTP(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ag_knowledge_http_")
        self.database = Database(Path(self.temp.name) / "control.db")
        self.project_id = self.database.add_project(
            "Knowledge HTTP",
            self.temp.name,
        )
        self.store = ControlCenterStore(self.database)
        self.seed = self.store.create_idea_seed(
            {
                "project_id": self.project_id,
                "title": "HTTP-visible seed",
                "note": "Keep the unlinked state visible through the GET route.",
            }
        )
        self.store_patch = patch(
            "src.control_center_handlers.control_center",
            self.store,
        )
        self.store_patch.start()
        app = web.Application()
        app.router.add_get(
            "/api/control-center/knowledge-chains",
            handle_knowledge_chains,
        )
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        self.store_patch.stop()
        self.temp.cleanup()

    async def test_get_filters_by_project_and_rejects_unknown_project(self):
        response = await self.client.get(
            "/api/control-center/knowledge-chains"
            f"?project_id={self.project_id}"
        )

        self.assertEqual(response.status, 200, await response.text())
        body = await response.json()
        self.assertEqual(body["chains"], [])
        self.assertEqual(
            [item["id"] for item in body["unlinked"]["idea_seeds"]],
            [self.seed["id"]],
        )
        missing = await self.client.get(
            "/api/control-center/knowledge-chains?project_id=999999"
        )
        self.assertEqual(missing.status, 404, await missing.text())
        self.assertEqual((await missing.json())["code"], "project_not_found")

    async def test_default_list_excludes_archived_projects(self):
        with self.database._get_connection() as conn:
            conn.execute(
                "UPDATE projects SET archived_at = CURRENT_TIMESTAMP WHERE id = ?",
                (self.project_id,),
            )
            conn.commit()

        response = await self.client.get(
            "/api/control-center/knowledge-chains"
        )

        self.assertEqual(response.status, 200, await response.text())
        body = await response.json()
        self.assertEqual(body["chains"], [])
        self.assertEqual(body["unlinked"]["idea_seeds"], [])
        self.assertEqual(body["unlinked"]["artifacts"], [])
        self.assertEqual(body["unlinked"]["candidates"], [])

    async def test_empty_campaign_shell_is_not_presented_as_knowledge(self):
        with self.database._get_connection() as conn:
            conn.execute(
                """INSERT INTO control_campaigns (
                       id, project_id, title, goal, status, base_sha
                   ) VALUES (
                       'CMP-EMPTY', ?, 'Discarded scratch plan',
                       'No durable knowledge was produced.', 'cancelled', ?
                   )""",
                (self.project_id, "a" * 40),
            )
            conn.commit()

        response = await self.client.get(
            "/api/control-center/knowledge-chains"
        )

        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual((await response.json())["chains"], [])

    def test_proxy_app_registers_public_read_only_route(self):
        from src.proxy_server import create_app

        paths = {resource.canonical for resource in create_app().router.resources()}
        self.assertIn("/api/control-center/knowledge-chains", paths)


if __name__ == "__main__":
    unittest.main()
