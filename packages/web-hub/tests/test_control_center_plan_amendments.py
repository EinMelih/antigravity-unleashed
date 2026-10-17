"""Exact, staged and atomic Campaign plan amendments."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from src.control_center import ControlCenterError, ControlCenterStore
from src.control_center.agent_adapter import AntiGravityTaskAdapter
from src.database import Database


SHA = "a" * 40


class PlanAmendmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ag_plan_amendment_")
        self.root = Path(self.temp.name)
        self.database = Database(self.root / "control.db")
        self.project_id = self.database.add_project(
            "Plan Amendments",
            str(self.root),
        )
        self.store = ControlCenterStore(
            self.database,
            sha_resolver=lambda _project: SHA,
        )

    def tearDown(self):
        self.temp.cleanup()

    def _approved_campaign(self, *, candidate_count: int = 1):
        campaign = self.store.create_campaign(
            {
                "project_id": self.project_id,
                "title": "Exact amendment source",
                "goal": "Keep every approved plan change exact and reviewable.",
                "non_goals": "Do not write GitHub, deployment, or task state.",
                "risk_level": "medium",
                "planning_depth": "compact",
                "success_metrics": ["Every accepted target has three exact hashes."],
                "pivotal_fork": "Stage a typed target instead of mutating the source plan.",
                "alternatives": [
                    {
                        "title": "Typed staged target",
                        "mechanism": "Persist a normalized full target and deterministic patch.",
                        "tradeoffs": "More validation state, but exact review and replay safety.",
                    },
                    {
                        "title": "Immediate edits",
                        "mechanism": "Apply planner suggestions directly to live plan rows.",
                        "tradeoffs": "Less staging code, but no safe human review boundary.",
                    },
                ],
                "review_strategy": (
                    "An independent reviewer compares before, target, patch and exact hashes."
                ),
                "rollout_plan": "Apply only after exact human approval, then approve the plan again.",
                "rollback_plan": "Reject or cancel before apply and restore the exact prior status.",
            }
        )
        for branch in ("architecture", "data", "security", "operations"):
            self.store.add_planning_question(
                campaign["id"],
                {
                    "branch": branch,
                    "question": f"Which source fact grounds {branch} for this plan?",
                    "rationale": f"The {branch} decision is pinned to reviewed evidence.",
                    "status": "grounded",
                    "owner": "planner",
                    "evidence": {
                        "path": "src/control_center/planning.py",
                        "fact": f"Reviewed {branch} planning seam.",
                    },
                },
            )
        self.store.save_artifact(
            {
                "project_id": self.project_id,
                "campaign_id": campaign["id"],
                "artifact_type": "repository_map",
                "title": "Pinned repository map",
                "status": "current",
                "content": "# Repository map\n\n`src/control_center/planning.py` owns readiness.",
                "metadata": {"base_sha": SHA},
                "materialize": False,
            }
        )
        candidates = []
        for index in range(candidate_count):
            candidates.append(
                self.store.create_pr_candidate(
                    campaign["id"],
                    {
                        "title": f"Future slice {index + 1}",
                        "scope": "Change only the bounded future planning contract safely.",
                        "purpose": "Prove exact amendment staging and atomic application.",
                        "non_goals": "No GitHub, task, evidence, approval, or deployment writes.",
                        "components": ["src/control_center/amendments.py"],
                        "expected_diff_type": "code-and-tests",
                        "acceptance_criteria": ["Exact target apply is atomic and reviewable."],
                        "required_checks": ["focused-amendment-tests"],
                        "manual_tests": ["Review the deterministic patch before approval."],
                        "definition_of_done": "Focused tests prove the amendment invariants.",
                        "reversibility": "Reject the staged target before plan reapproval.",
                        "migration_plan": "Use an idempotent SQLite migration.",
                        "compatibility_plan": "Legacy amendments remain readable but not approvable.",
                        "documentation_changes": ["Document the exact amendment API."],
                        "estimated_size": "small",
                        "business_value": 8,
                        "unblock_score": 7,
                        "learning_value": 5,
                        "urgency_score": 6,
                        "effort_score": 3,
                        "change_risk_score": 4,
                        "reversibility_score": 8,
                        "risk_level": "medium",
                        "priority": (index + 1) * 10,
                    },
                )
            )
        readiness = self.store.evaluate_campaign_readiness(
            campaign["id"],
            persist=False,
        )
        self.assertTrue(readiness["ready"], readiness)
        current = next(
            item
            for item in self.store.overview(self.project_id)["campaigns"]
            if item["id"] == campaign["id"]
        )
        approved = self.store.approve_campaign(
            campaign["id"],
            expected_version=current["version"],
            approval_sha=SHA,
            expected_plan_signature=readiness["plan_signature"],
        )
        return approved, candidates, readiness

    def _start(self, campaign, readiness, **overrides):
        payload = {
            "reason": "Split the remaining future work into a safer exact target plan.",
            "focus": {
                "branches": ["scope", "architecture"],
                "requested_change": "Rename the future slice without touching active work.",
            },
            "expected_version": campaign["version"],
            "expected_base_sha": campaign["base_sha"],
            "expected_plan_signature": readiness["plan_signature"],
            "expected_plan_signature_version": readiness["plan_signature_version"],
            "actor": "human",
        }
        payload.update(overrides)
        return self.store.start_plan_amendment(campaign["id"], payload)

    def _stage_title_change(
        self,
        amendment_id,
        job_id,
        title="Safer future slice",
        *,
        add_candidate_artifact_link=False,
    ):
        claimed = self.store.claim_planning_job()
        self.assertEqual(claimed["id"], job_id)
        amendment = self.store.get_plan_amendment(amendment_id)
        target = copy.deepcopy(amendment["before_plan"])
        target["candidates"][0]["title"] = title
        if add_candidate_artifact_link:
            target["knowledge_relations"]["candidate_artifacts"].append(
                {
                    "source_kind": "candidate",
                    "source_id": target["candidates"][0]["id"],
                    "target_kind": "artifact",
                    "target_id": target["artifacts"][0]["id"],
                    "relation_type": "references",
                }
            )
        staged = self.store.complete_planning_job(
            job_id,
            {
                "type": "amendment_plan",
                "resolved_question_ids": [],
                "target_plan": target,
            },
        )
        self.assertEqual(staged["status"], "waiting_human")
        self.assertEqual(staged["waiting_reason"], "amendment_approval")
        return self.store.get_plan_amendment(amendment_id)

    def test_schema_and_start_bind_exact_source_and_create_nullable_typed_job(self):
        with self.database._get_connection() as conn:
            columns = {
                row["name"]: row
                for row in conn.execute("PRAGMA table_info(control_planning_jobs)")
            }
        self.assertEqual(columns["idea_seed_id"]["notnull"], 0)
        self.assertIn("job_type", columns)
        self.assertIn("amendment_id", columns)

        campaign, _candidates, readiness = self._approved_campaign()
        with self.assertRaises(ControlCenterError) as stale:
            self._start(campaign, readiness, expected_plan_signature="f" * 64)
        self.assertEqual(stale.exception.code, "stale_plan_signature")

        result = self._start(campaign, readiness)
        amendment = result["amendment"]
        job = result["planning_job"]
        self.assertEqual(amendment["status"], "planning")
        self.assertEqual(amendment["prior_campaign_status"], "approved")
        self.assertEqual(amendment["from_plan_signature"], readiness["plan_signature"])
        self.assertEqual(amendment["from_signature_version"], 2)
        self.assertEqual(len(amendment["before_plan_sha256"]), 64)
        self.assertEqual(amendment["planning_base_sha"], SHA)
        self.assertEqual(job["job_type"], "plan_amendment")
        self.assertEqual(job["amendment_id"], amendment["id"])
        self.assertIsNone(job["idea_seed_id"])
        self.assertEqual(job["campaign_id"], campaign["id"])
        current = next(
            item
            for item in self.store.overview(self.project_id)["campaigns"]
            if item["id"] == campaign["id"]
        )
        self.assertEqual(current["status"], "paused")
        with self.assertRaises(ControlCenterError) as duplicate:
            self._start(campaign, readiness)
        self.assertEqual(duplicate.exception.code, "amendment_already_open")

    def test_legacy_planning_job_migration_preserves_rows_and_foreign_keys(self):
        legacy_job = self.store.create_planning_job(
            {
                "project_id": self.project_id,
                "wish": "Preserve this existing planning session through the schema migration.",
                "planning_depth": "compact",
                "max_candidates": 3,
                "activation_policy": "per_candidate",
            }
        )
        legacy_columns = (
            "id, project_id, idea_seed_id, status, planning_depth, max_candidates, "
            "activation_policy, wish, constraints_json, antigravity_chat_id, "
            "campaign_id, waiting_reason, active_question_id, round_number, attempt, "
            "output_json, last_error, created_by, created_at, started_at, finished_at, "
            "updated_at"
        )
        with self.database._get_connection() as conn:
            conn.commit()
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """CREATE TABLE control_planning_jobs_legacy (
                       id TEXT PRIMARY KEY, project_id INTEGER NOT NULL,
                       idea_seed_id TEXT NOT NULL,
                       status TEXT NOT NULL DEFAULT 'queued',
                       planning_depth TEXT NOT NULL, max_candidates INTEGER NOT NULL,
                       activation_policy TEXT NOT NULL, wish TEXT NOT NULL,
                       constraints_json TEXT NOT NULL DEFAULT '[]',
                       antigravity_chat_id TEXT NOT NULL DEFAULT '', campaign_id TEXT,
                       waiting_reason TEXT NOT NULL DEFAULT '', active_question_id TEXT,
                       round_number INTEGER NOT NULL DEFAULT 0,
                       attempt INTEGER NOT NULL DEFAULT 0,
                       output_json TEXT NOT NULL DEFAULT '{}',
                       last_error TEXT NOT NULL DEFAULT '',
                       created_by TEXT NOT NULL DEFAULT 'human',
                       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                       started_at TIMESTAMP, finished_at TIMESTAMP,
                       updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                   )"""
            )
            conn.execute(
                f"""INSERT INTO control_planning_jobs_legacy ({legacy_columns})
                    SELECT {legacy_columns} FROM control_planning_jobs"""
            )
            conn.execute("DROP TABLE control_planning_jobs")
            conn.execute(
                "ALTER TABLE control_planning_jobs_legacy RENAME TO control_planning_jobs"
            )
            conn.commit()
            conn.execute("PRAGMA foreign_keys = ON")

        migrated_store = ControlCenterStore(
            self.database,
            sha_resolver=lambda _project: SHA,
        )
        migrated = migrated_store.get_planning_job(legacy_job["id"])
        with self.database._get_connection() as conn:
            columns = {
                row["name"]: row
                for row in conn.execute("PRAGMA table_info(control_planning_jobs)")
            }
            foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        self.assertEqual(columns["idea_seed_id"]["notnull"], 0)
        self.assertEqual(migrated["idea_seed_id"], legacy_job["idea_seed_id"])
        self.assertEqual(migrated["wish"], legacy_job["wish"])
        self.assertEqual(migrated["job_type"], "initial_plan")
        self.assertIsNone(migrated["amendment_id"])
        self.assertEqual(foreign_key_errors, [])

    def test_migration_keeps_only_newest_legacy_open_amendment(self):
        campaign, _candidates, _readiness = self._approved_campaign()
        with self.database._get_connection() as conn:
            conn.execute("DROP INDEX idx_control_amendment_unique_open")
            for amendment_id, created_at in (
                ("AMD-legacy-older", "2026-08-25 10:00:00"),
                ("AMD-legacy-newer", "2026-08-25 11:00:00"),
            ):
                conn.execute(
                    """INSERT INTO control_plan_amendments (
                           id, campaign_id, from_version, proposed_version,
                           reason, impact_json, status, proposed_by, created_at
                       ) VALUES (?, ?, ?, ?, ?, '{}', 'proposed', 'legacy', ?)""",
                    (
                        amendment_id,
                        campaign["id"],
                        campaign["version"],
                        campaign["version"] + 1,
                        "Legacy duplicate open amendment.",
                        created_at,
                    ),
                )
            conn.commit()

        ControlCenterStore(self.database, sha_resolver=lambda _project: SHA)
        with self.database._get_connection() as conn:
            rows = {
                row["id"]: dict(row)
                for row in conn.execute(
                    """SELECT id, status, resolved_by
                       FROM control_plan_amendments WHERE campaign_id = ?""",
                    (campaign["id"],),
                ).fetchall()
            }
        self.assertEqual(rows["AMD-legacy-newer"]["status"], "proposed")
        self.assertEqual(rows["AMD-legacy-older"]["status"], "cancelled")
        self.assertEqual(rows["AMD-legacy-older"]["resolved_by"], "schema_migration")

    def test_amendment_question_round_does_not_change_source_identity(self):
        campaign, _candidates, readiness = self._approved_campaign()
        started = self._start(campaign, readiness)
        amendment = started["amendment"]
        job = started["planning_job"]
        self.store.claim_planning_job()

        waiting = self.store.complete_planning_job(
            job["id"],
            {
                "type": "question",
                "question": {
                    "branch": "scope",
                    "question": "Should the future slice keep its current public API?",
                    "rationale": "The answer changes the exact acceptance contract.",
                },
            },
        )
        self.assertEqual(waiting["waiting_reason"], "question")
        after_question = self.store.evaluate_campaign_readiness(
            campaign["id"], persist=False
        )
        self.assertEqual(after_question["plan_signature"], readiness["plan_signature"])
        current = self.store.get_plan_amendment(amendment["id"])
        self.assertEqual(current["before_plan_sha256"], amendment["before_plan_sha256"])

        self.store.answer_planning_question(
            waiting["active_question_id"],
            {
                "answer": "Yes, preserve the current public API.",
                "status": "answered",
                "answer_source": "human",
            },
        )
        requeued = self.store.get_planning_job(job["id"])
        self.assertEqual(requeued["status"], "queued")
        self.assertEqual(requeued["antigravity_chat_id"], waiting["antigravity_chat_id"])
        after_answer = self.store.evaluate_campaign_readiness(
            campaign["id"], persist=False
        )
        self.assertEqual(after_answer["plan_signature"], readiness["plan_signature"])

    def test_final_target_is_staged_without_source_mutation_then_applied_atomically(self):
        campaign, candidates, readiness = self._approved_campaign()
        started = self._start(campaign, readiness)
        staged = self._stage_title_change(
            started["amendment"]["id"],
            started["planning_job"]["id"],
            add_candidate_artifact_link=True,
        )
        self.assertEqual(staged["status"], "review")
        self.assertEqual(staged["validation"]["ready"], True)
        self.assertEqual(len(staged["target_plan_sha256"]), 64)
        self.assertEqual(len(staged["patch_sha256"]), 64)
        with self.database._get_connection() as conn:
            source_title = conn.execute(
                "SELECT title FROM control_pr_candidates WHERE id = ?",
                (candidates[0]["id"],),
            ).fetchone()["title"]
            staged_link_count = conn.execute(
                "SELECT COUNT(*) AS count FROM control_candidate_artifacts",
            ).fetchone()["count"]
        self.assertEqual(source_title, "Future slice 1")
        self.assertEqual(staged_link_count, 0)

        applied = self.store.decide_plan_amendment(
            staged["id"],
            decision="approved",
            actor="human",
            reason="Exact target reviewed.",
            expected_from_version=staged["from_version"],
            expected_before_plan_sha256=staged["before_plan_sha256"],
            expected_target_plan_sha256=staged["target_plan_sha256"],
            expected_patch_sha256=staged["patch_sha256"],
        )
        self.assertEqual(applied["status"], "approved")
        with self.database._get_connection() as conn:
            current_campaign = dict(
                conn.execute(
                    "SELECT * FROM control_campaigns WHERE id = ?",
                    (campaign["id"],),
                ).fetchone()
            )
            current_title = conn.execute(
                "SELECT title FROM control_pr_candidates WHERE id = ?",
                (candidates[0]["id"],),
            ).fetchone()["title"]
            profile = dict(
                conn.execute(
                    "SELECT * FROM control_campaign_profiles WHERE campaign_id = ?",
                    (campaign["id"],),
                ).fetchone()
            )
            applied_link = conn.execute(
                """SELECT relation_type FROM control_candidate_artifacts
                   WHERE candidate_id = ?""",
                (candidates[0]["id"],),
            ).fetchone()
        self.assertEqual(current_title, "Safer future slice")
        self.assertEqual(current_campaign["status"], "draft")
        self.assertEqual(current_campaign["version"], campaign["version"] + 1)
        self.assertIsNone(current_campaign["approved_version"])
        self.assertEqual(profile["plan_signature"], "")
        self.assertEqual(profile["readiness_status"], "draft")
        self.assertEqual(applied_link["relation_type"], "references")
        self.assertEqual(
            self.store.get_planning_job(started["planning_job"]["id"])["status"],
            "completed",
        )
        self.assertEqual(
            self.store._plan_snapshot_sha256(
                self.store.get_plan_snapshot(campaign["id"])
            ),
            staged["target_plan_sha256"],
        )

    def test_immutable_candidate_change_is_rejected_without_partial_plan_writes(self):
        campaign, candidates, readiness = self._approved_campaign(candidate_count=2)
        with self.database._get_connection() as conn:
            conn.execute(
                """INSERT INTO control_work_orders (
                       id, candidate_id, status, approval_sha, approved_by
                   ) VALUES ('WO-immutable', ?, 'approved', ?, 'human')""",
                (candidates[1]["id"], SHA),
            )
            conn.commit()
        started = self._start(campaign, readiness)
        self.store.claim_planning_job()
        amendment = self.store.get_plan_amendment(started["amendment"]["id"])
        target = copy.deepcopy(amendment["before_plan"])
        immutable_target = next(
            item
            for item in target["candidates"]
            if item["id"] == candidates[1]["id"]
        )
        immutable_target["title"] = "Illegal immutable rewrite"

        with self.assertRaises(ControlCenterError) as immutable:
            self.store.complete_planning_job(
                started["planning_job"]["id"],
                {
                    "type": "amendment_plan",
                    "resolved_question_ids": [],
                    "target_plan": target,
                },
            )
        self.assertEqual(immutable.exception.code, "immutable_candidate_changed")
        with self.database._get_connection() as conn:
            titles = [
                row["title"]
                for row in conn.execute(
                    "SELECT title FROM control_pr_candidates WHERE campaign_id = ? ORDER BY priority",
                    (campaign["id"],),
                )
            ]
        self.assertEqual(titles, ["Future slice 1", "Future slice 2"])

    def test_reject_restores_prior_status_and_terminal_replay_is_exact(self):
        campaign, _candidates, readiness = self._approved_campaign()
        started = self._start(campaign, readiness)
        staged = self._stage_title_change(
            started["amendment"]["id"],
            started["planning_job"]["id"],
        )
        identity = {
            "expected_from_version": staged["from_version"],
            "expected_before_plan_sha256": staged["before_plan_sha256"],
            "expected_target_plan_sha256": staged["target_plan_sha256"],
            "expected_patch_sha256": staged["patch_sha256"],
        }
        rejected = self.store.decide_plan_amendment(
            staged["id"],
            decision="rejected",
            actor="human",
            reason="Keep the current plan.",
            **identity,
        )
        replay = self.store.decide_plan_amendment(
            staged["id"],
            decision="rejected",
            actor="human",
            reason="Keep the current plan.",
            **identity,
        )
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(replay["status"], "rejected")
        current = next(
            item
            for item in self.store.overview(self.project_id)["campaigns"]
            if item["id"] == campaign["id"]
        )
        self.assertEqual(current["status"], "approved")
        self.assertEqual(current["version"], campaign["version"])
        after = self.store.evaluate_campaign_readiness(campaign["id"], persist=False)
        self.assertEqual(after["plan_signature"], readiness["plan_signature"])
        with self.assertRaises(ControlCenterError) as opposite:
            self.store.decide_plan_amendment(
                staged["id"],
                decision="approved",
                actor="human",
                **identity,
            )
        self.assertEqual(opposite.exception.code, "amendment_decision_conflict")

    def test_approval_rejects_tampered_stored_target_payload(self):
        campaign, _candidates, readiness = self._approved_campaign()
        started = self._start(campaign, readiness)
        staged = self._stage_title_change(
            started["amendment"]["id"],
            started["planning_job"]["id"],
        )
        identity = {
            "expected_from_version": staged["from_version"],
            "expected_before_plan_sha256": staged["before_plan_sha256"],
            "expected_target_plan_sha256": staged["target_plan_sha256"],
            "expected_patch_sha256": staged["patch_sha256"],
        }
        tampered = copy.deepcopy(staged["target_plan"])
        tampered["candidates"][0]["title"] = "Unreviewed database mutation"
        with self.database._get_connection() as conn:
            conn.execute(
                "UPDATE control_plan_amendments SET target_plan_json = ? WHERE id = ?",
                (json.dumps(tampered), staged["id"]),
            )
            conn.commit()

        with self.assertRaises(ControlCenterError) as mismatch:
            self.store.decide_plan_amendment(
                staged["id"],
                decision="approved",
                actor="human",
                **identity,
            )
        self.assertEqual(mismatch.exception.code, "amendment_payload_hash_mismatch")
        with self.database._get_connection() as conn:
            conn.execute(
                "UPDATE control_plan_amendments SET target_plan_json = '[]' WHERE id = ?",
                (staged["id"],),
            )
            conn.commit()
        with self.assertRaises(ControlCenterError) as invalid_shape:
            self.store.decide_plan_amendment(
                staged["id"],
                decision="approved",
                actor="human",
                **identity,
            )
        self.assertEqual(
            invalid_shape.exception.code,
            "amendment_payload_hash_mismatch",
        )
        with self.database._get_connection() as conn:
            source = conn.execute(
                "SELECT title FROM control_pr_candidates WHERE campaign_id = ?",
                (campaign["id"],),
            ).fetchone()
        self.assertEqual(source["title"], "Future slice 1")

    def test_overview_redacts_amendment_target_from_planning_job_output(self):
        campaign, _candidates, readiness = self._approved_campaign()
        started = self._start(campaign, readiness)
        self._stage_title_change(
            started["amendment"]["id"],
            started["planning_job"]["id"],
        )

        job = next(
            item
            for item in self.store.overview(self.project_id)["planning_jobs"]
            if item["id"] == started["planning_job"]["id"]
        )
        self.assertEqual(job["output"].get("type"), "amendment_plan")
        self.assertEqual(job["output"].get("amendment_id"), started["amendment"]["id"])
        self.assertNotIn("target_plan", job["output"])

    def test_failed_retry_and_cancel_preserve_pause_then_restore_prior_status(self):
        campaign, _candidates, readiness = self._approved_campaign()
        started = self._start(campaign, readiness)
        job_id = started["planning_job"]["id"]
        self.store.claim_planning_job()

        failed = self.store.fail_planning_job(job_id, "Planner transport failed.")
        self.assertEqual(failed["status"], "failed")
        current = self.store.get_plan_amendment(started["amendment"]["id"])
        self.assertEqual(current["status"], "failed")
        campaign_after_failure = next(
            item
            for item in self.store.overview(self.project_id)["campaigns"]
            if item["id"] == campaign["id"]
        )
        self.assertEqual(campaign_after_failure["status"], "paused")

        retried = self.store.retry_planning_job(job_id, actor="human")
        self.assertEqual(retried["status"], "queued")
        self.assertEqual(
            self.store.get_plan_amendment(started["amendment"]["id"])["status"],
            "planning",
        )
        cancelled = self.store.cancel_planning_job(
            job_id,
            actor="human",
            reason="Stop the amendment safely.",
        )
        self.assertEqual(cancelled["status"], "cancelled")
        amendment = self.store.get_plan_amendment(started["amendment"]["id"])
        self.assertEqual(amendment["status"], "cancelled")
        restored = next(
            item
            for item in self.store.overview(self.project_id)["campaigns"]
            if item["id"] == campaign["id"]
        )
        self.assertEqual(restored["status"], "approved")

    def test_legacy_proposed_amendment_without_target_cannot_be_approved(self):
        campaign, _candidates, _readiness = self._approved_campaign()
        with self.database._get_connection() as conn:
            conn.execute(
                """INSERT INTO control_plan_amendments (
                       id, campaign_id, from_version, proposed_version,
                       reason, impact_json, status, proposed_by
                   ) VALUES (
                       'AMD-legacy-targetless', ?, ?, ?, ?, '{}', 'proposed', 'legacy'
                   )""",
                (
                    campaign["id"],
                    campaign["version"],
                    campaign["version"] + 1,
                    "Legacy row predates typed target plans.",
                ),
            )
            conn.commit()

        with self.assertRaises(ControlCenterError) as legacy:
            self.store.decide_plan_amendment(
                "AMD-legacy-targetless",
                decision="approved",
                actor="human",
                expected_from_version=campaign["version"],
                expected_before_plan_sha256="",
                expected_target_plan_sha256="",
                expected_patch_sha256="",
            )
        self.assertEqual(legacy.exception.code, "legacy_amendment_target_missing")
        current = next(
            item
            for item in self.store.overview(self.project_id)["campaigns"]
            if item["id"] == campaign["id"]
        )
        self.assertEqual(current["status"], "approved")
        self.assertEqual(current["version"], campaign["version"])

    def test_adapter_uses_amendment_envelope_and_exact_source_context(self):
        prompt = AntiGravityTaskAdapter.build_planning_prompt(
            {
                "job_type": "plan_amendment",
                "amendment_id": "AMD-1",
                "planning_depth": "balanced",
                "max_candidates": 12,
                "activation_policy": "per_candidate",
                "wish": "Change only future slices.",
                "constraints": [],
                "session_questions": [],
                "amendment": {
                    "from_version": 7,
                    "from_base_sha": SHA,
                    "planning_base_sha": SHA,
                    "from_plan_signature": "b" * 64,
                    "from_signature_version": 2,
                    "before_plan_sha256": "c" * 64,
                    "before_plan": {"campaign": {"id": "CMP-1"}},
                    "focus": {"branches": ["scope"]},
                },
            },
            {"path": str(self.root)},
        )
        self.assertIn('"type": "amendment_plan"', prompt)
        self.assertIn('"target_plan"', prompt)
        self.assertIn("Plan signature v2", prompt)
        self.assertIn("c" * 64, prompt)
        self.assertNotIn('"type": "plan"', prompt)


if __name__ == "__main__":
    unittest.main()
