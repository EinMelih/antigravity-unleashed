"""Hard plan-readiness and exact viewed-signature contracts."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.control_center import ControlCenterError, ControlCenterStore
from src.control_center_handlers import (
    handle_approve_campaign,
    handle_campaign_readiness,
    handle_campaign_simulation,
)
from src.database import Database


SHA = "a" * 40


class HardPlanReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ag_hard_readiness_")
        self.root = Path(self.temp.name)
        self.database = Database(self.root / "control.db")
        self.project_id = self.database.add_project(
            "Hard Readiness",
            str(self.root),
        )
        self.store = ControlCenterStore(
            self.database,
            sha_resolver=lambda _project: SHA,
        )

    def tearDown(self):
        self.temp.cleanup()

    def _campaign(self, **overrides):
        payload = {
            "project_id": self.project_id,
            "title": "Exact plan approval",
            "goal": "Deliver a deterministic plan that another agent can execute.",
            "non_goals": "Do not merge, deploy, or broaden the approved scope.",
            "risk_level": "medium",
            "planning_depth": "compact",
            "success_metrics": ["Every approved PR contract has exact evidence."],
            "pivotal_fork": "Persist plan state instead of relying on chat memory.",
            "alternatives": [
                {
                    "title": "Persistent state",
                    "mechanism": "Store every decision and contract in SQLite.",
                    "tradeoffs": "More schema work, but deterministic recovery.",
                },
                {
                    "title": "Conversation state",
                    "mechanism": "Keep decisions only in the planner conversation.",
                    "tradeoffs": "Less storage, but no durable handoff or recovery.",
                },
            ],
            "review_strategy": (
                "An independent reviewer checks the contract, exact SHA, tests, "
                "manual proof, migration safety, and rollback before approval."
            ),
            "rollout_plan": "Run the ordered slices in one private proof repository.",
            "rollback_plan": "Revert the bounded slice and restore the prior SHA.",
        }
        payload.update(overrides)
        return self.store.create_campaign(payload)

    def _ground_required_branches(self, campaign_id):
        for branch in ("architecture", "data", "security", "operations"):
            self.store.add_planning_question(
                campaign_id,
                {
                    "branch": branch,
                    "question": f"What repository fact grounds the {branch} branch?",
                    "rationale": (
                        f"The final plan records why the {branch} branch is safe "
                        "for this exact repository."
                    ),
                    "status": "grounded",
                    "owner": "repository-mapper",
                    "evidence": {
                        "path": "src/control_center/planning.py",
                        "fact": f"The {branch} assessment was verified in code.",
                    },
                },
            )

    def _repository_map(self, campaign_id, *, metadata=None):
        return self.store.save_artifact(
            {
                "project_id": self.project_id,
                "campaign_id": campaign_id,
                "artifact_type": "repository_map",
                "title": "Verified repository map",
                "status": "current",
                "content": (
                    "# Repository map\n\n"
                    "`src/control_center/planning.py` owns readiness and signatures."
                ),
                "metadata": metadata or {"base_sha": SHA, "mapper": "planner"},
                "materialize": False,
            }
        )

    def _candidate(self, campaign_id, **overrides):
        payload = {
            "title": "Enforce exact plan approval",
            "scope": "Bind human approval to the exact complete plan snapshot.",
            "purpose": "Prevent a changed plan from reusing an earlier approval.",
            "non_goals": "Do not authorize implementation or repository writes.",
            "components": ["src/control_center/planning.py"],
            "expected_diff_type": "code-and-tests",
            "acceptance_criteria": [
                "A stale plan signature is rejected before approval."
            ],
            "required_checks": ["focused-backend-tests"],
            "manual_tests": ["Review the signature shown before approval."],
            "reversibility": "Revert the focused backend change.",
            "migration_plan": "Use additive idempotent SQLite columns only.",
            "compatibility_plan": "Default legacy rows to safe empty values.",
            "documentation_changes": ["Document exact viewed-plan approval."],
            "definition_of_done": (
                "Focused tests prove the exact-signature race is rejected."
            ),
            "risk_level": "medium",
            "priority": 10,
        }
        payload.update(overrides)
        return self.store.create_pr_candidate(campaign_id, payload)

    def _ready_campaign(self):
        campaign = self._campaign()
        self._ground_required_branches(campaign["id"])
        self._repository_map(campaign["id"])
        self._candidate(campaign["id"])
        readiness = self.store.evaluate_campaign_readiness(
            campaign["id"], persist=False
        )
        self.assertTrue(readiness["ready"], readiness)
        current = next(
            item
            for item in self.store.overview(self.project_id)["campaigns"]
            if item["id"] == campaign["id"]
        )
        return current, readiness

    def _balanced_ready_artifacts(self):
        campaign = self._campaign(
            planning_depth="balanced",
            risk_level="high",
            acceptance_matrix=["Exact plan -> exact review and rollback proof."],
        )
        self._ground_required_branches(campaign["id"])
        repository_map = self._repository_map(campaign["id"])
        self._candidate(campaign["id"])
        design = self.store.save_artifact(
            {
                "project_id": self.project_id,
                "campaign_id": campaign["id"],
                "artifact_type": "design_document",
                "title": "Verified design",
                "status": "proposed",
                "content": "# Design\n\nUse one atomic exact-plan approval boundary.",
                "materialize": False,
            }
        )
        adr = self.store.save_artifact(
            {
                "project_id": self.project_id,
                "campaign_id": campaign["id"],
                "artifact_type": "adr",
                "title": "Verified decision",
                "status": "proposed",
                "content": "# ADR\n\nPersist the exact viewed plan signature.",
                "materialize": False,
            }
        )
        simulation = self.store.save_artifact(
            {
                "project_id": self.project_id,
                "campaign_id": campaign["id"],
                "artifact_type": "plan_simulation",
                "title": "Verified plan simulation",
                "status": "current",
                "content": "# Simulation\n\nThe deterministic graph is attached by metadata.",
                "materialize": False,
            }
        )
        current = next(
            item
            for item in self.store.overview(self.project_id)["campaigns"]
            if item["id"] == campaign["id"]
        )
        readiness = self.store.evaluate_campaign_readiness(
            campaign["id"], persist=False
        )
        return current, readiness, {
            "repository_map": repository_map,
            "design_document": design,
            "adr": adr,
            "plan_simulation": simulation,
        }

    def test_incomplete_plan_exposes_structured_blocking_gates(self):
        campaign = self.store.create_campaign(
            {
                "project_id": self.project_id,
                "title": "Incomplete campaign",
                "goal": "Deliver a verifiable but deliberately incomplete plan.",
                "risk_level": "medium",
                "planning_depth": "compact",
            }
        )

        readiness = self.store.evaluate_campaign_readiness(
            campaign["id"],
            persist=False,
        )

        self.assertFalse(readiness["ready"])
        self.assertLess(readiness["score"], 100)
        gates = {gate["key"]: gate for gate in readiness["gates"]}
        self.assertEqual(
            set(gates),
            {
                "outcome_contract",
                "pivotal_fork",
                "repository_grounding",
                "decision_ledger",
                "alternatives_tradeoffs",
                "candidate_contracts",
                "dependency_conflict_simulation",
                "verification_release",
            },
        )
        for gate in gates.values():
            self.assertEqual(set(gate), {"key", "passed", "missing", "evidence"})
        self.assertFalse(gates["outcome_contract"]["passed"])
        self.assertIn("non_goals", gates["outcome_contract"]["missing"])
        self.assertFalse(gates["decision_ledger"]["passed"])
        self.assertIn("decision_ledger", gates["decision_ledger"]["missing"])

    def test_manual_candidate_draft_does_not_invent_contract_evidence(self):
        campaign = self._campaign()
        candidate = self.store.create_pr_candidate(
            campaign["id"],
            {
                "title": "Incomplete manual draft",
                "scope": "Record an intentionally incomplete manual PR contract.",
                "acceptance_criteria": [
                    "Readiness reports every contract field that is still missing."
                ],
                "risk_level": "medium",
            },
        )

        contract = candidate["contract"]
        self.assertEqual(contract["purpose"], "")
        self.assertEqual(contract["expected_diff_type"], "")
        self.assertEqual(contract["required_checks"], [])
        self.assertEqual(contract["definition_of_done"], "")
        readiness = self.store.evaluate_campaign_readiness(
            campaign["id"],
            persist=False,
        )
        for field in (
            "purpose",
            "expected_diff_type",
            "required_checks",
            "definition_of_done",
        ):
            self.assertIn(
                f"candidate_{field}:{candidate['id']}",
                readiness["missing"],
            )

    def test_two_structured_alternatives_and_review_strategy_satisfy_gate(self):
        campaign = self.store.create_campaign(
            {
                "project_id": self.project_id,
                "title": "Alternative comparison",
                "goal": "Select a maintainable implementation from real alternatives.",
                "non_goals": "Do not deploy or merge automatically.",
                "risk_level": "medium",
                "planning_depth": "compact",
                "success_metrics": ["The chosen mechanism passes exact checks."],
                "pivotal_fork": "Use a durable queue rather than in-memory ownership.",
                "alternatives": [
                    {
                        "title": "Durable queue",
                        "mechanism": "Persist ownership and claim work atomically.",
                        "tradeoffs": "More schema work, deterministic recovery.",
                    },
                    {
                        "title": "In-memory queue",
                        "mechanism": "Keep ownership inside one process.",
                        "tradeoffs": "Less code, but restart loses ownership.",
                    },
                ],
                "review_strategy": (
                    "An independent reviewer checks scope, failure recovery, and the "
                    "exact required evidence before human approval."
                ),
                "rollout_plan": "Exercise the plan in one private proof repository.",
                "rollback_plan": "Discard the draft and retain the prior baseline.",
            }
        )

        readiness = self.store.evaluate_campaign_readiness(
            campaign["id"],
            persist=False,
        )

        gates = {gate["key"]: gate for gate in readiness["gates"]}
        self.assertTrue(gates["alternatives_tradeoffs"]["passed"])
        self.assertEqual(gates["alternatives_tradeoffs"]["missing"], [])
        self.assertIn("2 alternatives", gates["alternatives_tradeoffs"]["evidence"])
        self.assertNotIn("review_strategy", gates["verification_release"]["missing"])

    def test_pivotal_fork_accepts_only_explicit_reasoned_not_applicable(self):
        campaign = self.store.create_campaign(
            {
                "project_id": self.project_id,
                "title": "Documentation-only campaign",
                "goal": "Correct one factual document without changing runtime behavior.",
                "non_goals": "Do not change code, schemas, APIs, or deployment.",
                "risk_level": "low",
                "planning_depth": "compact",
                "success_metrics": ["The incorrect statement is removed."],
                "pivotal_fork_na_reason": (
                    "No architecture choice exists because the bounded change only "
                    "corrects an already decided factual statement."
                ),
                "rollout_plan": "Review the rendered document before merge.",
                "rollback_plan": "Revert the documentation commit.",
            }
        )

        readiness = self.store.evaluate_campaign_readiness(
            campaign["id"],
            persist=False,
        )

        gate = next(
            item for item in readiness["gates"] if item["key"] == "pivotal_fork"
        )
        self.assertTrue(gate["passed"])
        self.assertEqual(gate["missing"], [])
        self.assertEqual(gate["evidence"], ["explicit_not_applicable"])

    def test_uncertainty_states_require_owner_rationale_and_discovery_next_step(self):
        campaign = self._campaign()
        self.store.add_planning_question(
            campaign["id"],
            {
                "branch": "architecture",
                "question": "Can the queue recover after an interrupted claim?",
                "status": "assumption-accepted",
            },
        )
        self.store.add_planning_question(
            campaign["id"],
            {
                "branch": "data",
                "question": "Which migration order is safe for legacy rows?",
                "status": "discovery-assigned",
                "rationale": "A bounded experiment must verify the migration order.",
                "owner": "data-owner",
                "evidence": {},
            },
        )

        readiness = self.store.evaluate_campaign_readiness(
            campaign["id"], persist=False
        )

        gate = next(item for item in readiness["gates"] if item["key"] == "decision_ledger")
        self.assertFalse(gate["passed"])
        self.assertTrue(any(item.startswith("question_owner:") for item in gate["missing"]))
        self.assertTrue(any(item.startswith("question_rationale:") for item in gate["missing"]))
        self.assertTrue(any(item.startswith("discovery_next_step:") for item in gate["missing"]))

    def test_required_branches_must_be_grounded_or_explicitly_dispositioned(self):
        campaign = self._campaign()
        self.store.add_planning_question(
            campaign["id"],
            {
                "branch": "architecture",
                "question": "Which component owns planning readiness?",
                "rationale": "The concrete owner was verified in repository code.",
                "status": "grounded",
                "owner": "repository-mapper",
                "evidence": {"path": "src/control_center/planning.py"},
            },
        )

        incomplete = self.store.evaluate_campaign_readiness(
            campaign["id"], persist=False
        )
        gate = next(item for item in incomplete["gates"] if item["key"] == "decision_ledger")
        self.assertIn("branch:data", gate["missing"])
        self.assertIn("branch:security", gate["missing"])
        self.assertIn("branch:operations", gate["missing"])

        for branch in ("data", "security", "operations"):
            self.store.add_planning_question(
                campaign["id"],
                {
                    "branch": branch,
                    "question": f"Why is {branch} not changed by this plan?",
                    "rationale": (
                        f"Repository inspection shows the bounded plan does not "
                        f"change the {branch} boundary."
                    ),
                    "status": "deferred",
                    "owner": "planner",
                    "evidence": {"not_applicable": True},
                },
            )
        complete = self.store.evaluate_campaign_readiness(
            campaign["id"], persist=False
        )
        gate = next(item for item in complete["gates"] if item["key"] == "decision_ledger")
        self.assertNotIn("branch:data", gate["missing"])
        self.assertNotIn("branch:security", gate["missing"])
        self.assertNotIn("branch:operations", gate["missing"])

    def test_repository_map_requires_a_matching_hash_and_baseline(self):
        campaign = self._campaign()
        artifact = self._repository_map(campaign["id"])
        with self.database._get_connection() as conn:
            conn.execute(
                "UPDATE control_artifacts SET content_text = ? WHERE id = ?",
                ("# Tampered repository map", artifact["id"]),
            )
            conn.commit()

        readiness = self.store.evaluate_campaign_readiness(
            campaign["id"], persist=False
        )

        gate = next(
            item
            for item in readiness["gates"]
            if item["key"] == "repository_grounding"
        )
        self.assertFalse(gate["passed"])
        self.assertIn("repository_map", gate["missing"])

        wrong_baseline = self._campaign()
        wrong_artifact = self._repository_map(wrong_baseline["id"])
        with self.database._get_connection() as conn:
            conn.execute(
                "UPDATE control_artifacts SET metadata_json = ? WHERE id = ?",
                (
                    json.dumps({"base_sha": "b" * 40, "mapper": "planner"}),
                    wrong_artifact["id"],
                ),
            )
            conn.commit()
        readiness = self.store.evaluate_campaign_readiness(
            wrong_baseline["id"], persist=False
        )
        gate = next(
            item
            for item in readiness["gates"]
            if item["key"] == "repository_grounding"
        )
        self.assertFalse(gate["passed"])
        self.assertIn("repository_map", gate["missing"])

    def test_artifact_supersedes_never_crosses_campaign_boundary(self):
        first_campaign = self._campaign(title="First artifact campaign")
        second_campaign = self._campaign(title="Second artifact campaign")
        original = self._repository_map(first_campaign["id"])

        for target_campaign_id in (second_campaign["id"], None):
            with self.subTest(target_campaign_id=target_campaign_id):
                with self.assertRaises(ControlCenterError) as context:
                    self.store.save_artifact(
                        {
                            "project_id": self.project_id,
                            "campaign_id": target_campaign_id,
                            "artifact_type": "repository_map",
                            "title": f"Forbidden replacement {target_campaign_id}",
                            "status": "current",
                            "content": "# Replacement\n\nMust stay in one campaign.",
                            "supersedes_id": original["id"],
                            "materialize": False,
                        }
                    )
                self.assertEqual(
                    context.exception.code,
                    "artifact_supersedes_campaign_mismatch",
                )
                self.assertEqual(
                    self.store.get_artifact(original["id"])["status"],
                    "current",
                )

    def test_artifact_writer_stamps_final_version_and_stales_old_simulation(self):
        campaign, readiness, artifacts = self._balanced_ready_artifacts()
        simulation = artifacts["plan_simulation"]
        canonical_simulation = self.store.simulate_campaign(
            campaign["id"], persist=False
        )
        expected_simulation_hash = hashlib.sha256(
            json.dumps(
                canonical_simulation,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        self.assertTrue(readiness["ready"], readiness)
        for artifact in artifacts.values():
            self.assertEqual(artifact["metadata"]["base_sha"], SHA)
            self.assertIsInstance(artifact["metadata"]["campaign_version"], int)
        self.assertEqual(
            simulation["metadata"]["campaign_version"],
            campaign["version"],
        )
        self.assertEqual(
            simulation["metadata"]["simulation_sha256"],
            expected_simulation_hash,
        )

        self.store.update_campaign_profile(
            campaign["id"],
            {"review_strategy": "A fresh reviewer rechecks the changed exact plan."},
        )

        self.assertEqual(
            self.store.get_artifact(simulation["id"])["status"],
            "superseded",
        )
        changed = self.store.evaluate_campaign_readiness(
            campaign["id"], persist=False
        )
        self.assertIn("plan_simulation_artifact", changed["missing"])

    def test_required_artifacts_reject_tampered_content_baseline_and_graph(self):
        campaign, readiness, artifacts = self._balanced_ready_artifacts()
        self.assertTrue(readiness["ready"], readiness)

        corruptions = (
            (
                "design_document",
                "content_text = '# tampered design'",
                (),
                "design_document",
            ),
            (
                "adr",
                "metadata_json = ?",
                (json.dumps({"base_sha": "b" * 40}),),
                "adr",
            ),
            (
                "plan_simulation",
                "metadata_json = ?",
                (
                    json.dumps(
                        {
                            "base_sha": SHA,
                            "campaign_version": campaign["version"],
                            "simulation_sha256": "f" * 64,
                        }
                    ),
                ),
                "plan_simulation_artifact",
            ),
        )
        for artifact_type, assignment, values, expected_missing in corruptions:
            with self.subTest(artifact_type=artifact_type):
                artifact = artifacts[artifact_type]
                with self.database._get_connection() as conn:
                    original = conn.execute(
                        "SELECT content_text, metadata_json FROM control_artifacts WHERE id = ?",
                        (artifact["id"],),
                    ).fetchone()
                    conn.execute(
                        f"UPDATE control_artifacts SET {assignment} WHERE id = ?",
                        (*values, artifact["id"]),
                    )
                    conn.commit()
                tampered = self.store.evaluate_campaign_readiness(
                    campaign["id"], persist=False
                )
                self.assertIn(expected_missing, tampered["missing"])
                with self.database._get_connection() as conn:
                    conn.execute(
                        "UPDATE control_artifacts SET content_text = ?, metadata_json = ? WHERE id = ?",
                        (
                            original["content_text"],
                            original["metadata_json"],
                            artifact["id"],
                        ),
                    )
                    conn.commit()

    def test_signature_covers_ledger_artifact_candidate_dependency_and_conflict(self):
        campaign = self._campaign()
        signature_0 = self.store.evaluate_campaign_readiness(
            campaign["id"], persist=False
        )["plan_signature"]
        self._ground_required_branches(campaign["id"])
        signature_1 = self.store.evaluate_campaign_readiness(
            campaign["id"], persist=False
        )["plan_signature"]
        self.assertNotEqual(signature_0, signature_1)

        artifact = self._repository_map(campaign["id"])
        signature_2 = self.store.evaluate_campaign_readiness(
            campaign["id"], persist=False
        )["plan_signature"]
        self.assertNotEqual(signature_1, signature_2)

        first = self._candidate(campaign["id"])
        signature_3 = self.store.evaluate_campaign_readiness(
            campaign["id"], persist=False
        )["plan_signature"]
        self.assertNotEqual(signature_2, signature_3)

        second = self._candidate(
            campaign["id"],
            title="Expose stale-plan failure",
            scope="Expose a stable stale-plan error through the legacy API.",
            purpose="Let the human understand why approval was rejected.",
            priority=20,
        )
        signature_4 = self.store.evaluate_campaign_readiness(
            campaign["id"], persist=False
        )["plan_signature"]
        with self.database._get_connection() as conn:
            conn.execute(
                "INSERT INTO control_pr_dependencies (candidate_id, depends_on_id) VALUES (?, ?)",
                (second["id"], first["id"]),
            )
            conn.commit()
        signature_5 = self.store.evaluate_campaign_readiness(
            campaign["id"], persist=False
        )["plan_signature"]
        self.assertNotEqual(signature_4, signature_5)

        self.store.set_candidate_conflicts(
            campaign["id"],
            first["id"],
            [
                {
                    "candidate_id": second["id"],
                    "reason": "Both touch the exact approval boundary.",
                    "resources": ["src/control_center/planning.py"],
                }
            ],
        )
        signature_6 = self.store.evaluate_campaign_readiness(
            campaign["id"], persist=False
        )["plan_signature"]
        self.assertNotEqual(signature_5, signature_6)

        with self.database._get_connection() as conn:
            conn.execute(
                "UPDATE control_question_ledger SET updated_at = CURRENT_TIMESTAMP "
                "WHERE campaign_id = ?",
                (campaign["id"],),
            )
            conn.execute(
                "UPDATE control_artifacts SET created_at = '1999-01-01 00:00:00', "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (artifact["id"],),
            )
            conn.commit()
        self.assertEqual(
            self.store.evaluate_campaign_readiness(campaign["id"], persist=False)[
                "plan_signature"
            ],
            signature_6,
        )

        with self.database._get_connection() as conn:
            conn.execute(
                "UPDATE control_artifacts SET metadata_json = ? WHERE id = ?",
                ('{"base_sha":"changed"}', artifact["id"]),
            )
            conn.commit()
        signature_7 = self.store.evaluate_campaign_readiness(
            campaign["id"], persist=False
        )["plan_signature"]
        self.assertNotEqual(signature_6, signature_7)
        self.assertEqual(
            self.store.evaluate_campaign_readiness(campaign["id"], persist=False)[
                "plan_signature"
            ],
            signature_7,
        )

    def test_read_only_readiness_and_simulation_do_not_touch_persisted_state(self):
        campaign, _readiness = self._ready_campaign()
        with self.database._get_connection() as conn:
            conn.execute(
                "UPDATE control_campaign_profiles SET updated_at = '2001-01-01 00:00:00' WHERE campaign_id = ?",
                (campaign["id"],),
            )
            conn.execute(
                "UPDATE control_candidate_contracts SET wave = 0, updated_at = '2001-01-01 00:00:00' "
                "WHERE candidate_id IN (SELECT id FROM control_pr_candidates WHERE campaign_id = ?)",
                (campaign["id"],),
            )
            conn.commit()

        first = self.store.evaluate_campaign_readiness(campaign["id"], persist=False)
        second = self.store.evaluate_campaign_readiness(campaign["id"], persist=False)
        simulation = self.store.simulate_campaign(campaign["id"], persist=False)

        self.assertEqual(first["plan_signature"], second["plan_signature"])
        self.assertEqual(first["simulation"], simulation)
        with self.database._get_connection() as conn:
            profile = conn.execute(
                "SELECT readiness_status, readiness_score, plan_signature, updated_at "
                "FROM control_campaign_profiles WHERE campaign_id = ?",
                (campaign["id"],),
            ).fetchone()
            contract = conn.execute(
                "SELECT wave, updated_at FROM control_candidate_contracts "
                "WHERE candidate_id IN (SELECT id FROM control_pr_candidates WHERE campaign_id = ?)",
                (campaign["id"],),
            ).fetchone()
        self.assertEqual(profile["updated_at"], "2001-01-01 00:00:00")
        self.assertEqual(profile["plan_signature"], "")
        self.assertEqual(contract["wave"], 0)
        self.assertEqual(contract["updated_at"], "2001-01-01 00:00:00")

    def test_approval_requires_the_exact_viewed_plan_signature(self):
        campaign, readiness = self._ready_campaign()
        with self.assertRaises(ControlCenterError) as context:
            self.store.approve_campaign(
                campaign["id"],
                expected_version=campaign["version"],
                approval_sha=SHA,
                expected_plan_signature=None,
                actor="owner",
            )
        self.assertEqual(context.exception.code, "plan_signature_required")

        approved = self.store.approve_campaign(
            campaign["id"],
            expected_version=campaign["version"],
            approval_sha=SHA,
            expected_plan_signature=readiness["plan_signature"],
            actor="owner",
        )
        self.assertEqual(approved["status"], "approved")
        with self.assertRaises(ControlCenterError) as context:
            self.store.approve_campaign(
                campaign["id"],
                expected_version=campaign["version"],
                approval_sha=SHA,
                expected_plan_signature="f" * 64,
                actor="owner",
            )
        self.assertEqual(context.exception.code, "stale_plan_signature")

        stale_campaign, stale_readiness = self._ready_campaign()
        with self.database._get_connection() as conn:
            question = conn.execute(
                "SELECT id FROM control_question_ledger WHERE campaign_id = ? ORDER BY id LIMIT 1",
                (stale_campaign["id"],),
            ).fetchone()
            conn.execute(
                "UPDATE control_question_ledger SET evidence_json = ? WHERE id = ?",
                ('{"path":"changed.py","fact":"new evidence"}', question["id"]),
            )
            conn.commit()
        with self.assertRaises(ControlCenterError) as context:
            self.store.approve_campaign(
                stale_campaign["id"],
                expected_version=stale_campaign["version"],
                approval_sha=SHA,
                expected_plan_signature=stale_readiness["plan_signature"],
                actor="owner",
            )
        self.assertEqual(context.exception.code, "stale_plan_signature")

    def test_planner_requires_explicit_repository_read_capability(self):
        self.store.update_repository_policy(
            self.project_id,
            {"capability": {"read_repository": False}},
        )

        with self.assertRaises(ControlCenterError) as context:
            self.store.create_planning_job(
                {
                    "project_id": self.project_id,
                    "wish": "Inspect the repository and create a bounded plan.",
                }
            )

        self.assertEqual(context.exception.code, "planning_read_repository_denied")

    def test_each_draft_plan_mutation_bumps_once_and_approved_plan_is_locked(self):
        campaign = self._campaign()

        def current():
            return next(
                item
                for item in self.store.overview(self.project_id)["campaigns"]
                if item["id"] == campaign["id"]
            )

        def assert_bumped_once(previous_version):
            snapshot = current()
            self.assertEqual(snapshot["version"], previous_version + 1)
            self.assertEqual(snapshot["profile"]["plan_signature"], "")
            return snapshot["version"]

        self.store.evaluate_campaign_readiness(campaign["id"], persist=True)
        version = current()["version"]
        self.store.update_campaign_profile(
            campaign["id"],
            {"review_strategy": "A second reviewer checks the complete exact plan."},
        )
        version = assert_bumped_once(version)

        question = self.store.add_planning_question(
            campaign["id"],
            {
                "branch": "architecture",
                "question": "Which component owns readiness evaluation?",
            },
        )
        version = assert_bumped_once(version)
        self.store.answer_planning_question(
            question["id"],
            {
                "answer": "PlanningMixin owns the canonical readiness evaluation.",
                "answer_source": "repository-mapper",
                "status": "resolved",
            },
        )
        version = assert_bumped_once(version)

        self._repository_map(campaign["id"])
        version = assert_bumped_once(version)
        self._candidate(campaign["id"])
        assert_bumped_once(version)

        approved_campaign, readiness = self._ready_campaign()
        self.store.approve_campaign(
            approved_campaign["id"],
            expected_version=approved_campaign["version"],
            approval_sha=SHA,
            expected_plan_signature=readiness["plan_signature"],
        )
        locked_operations = (
            lambda: self.store.update_campaign_profile(
                approved_campaign["id"], {"review_strategy": "Changed review."}
            ),
            lambda: self.store.add_planning_question(
                approved_campaign["id"],
                {
                    "branch": "architecture",
                    "question": "Can an approved plan change silently?",
                },
            ),
            lambda: self.store.save_artifact(
                {
                    "project_id": self.project_id,
                    "campaign_id": approved_campaign["id"],
                    "artifact_type": "repository_map",
                    "title": "Changed map",
                    "status": "current",
                    "content": "# Changed map",
                    "materialize": False,
                }
            ),
            lambda: self._candidate(
                approved_campaign["id"], title="Forbidden silent candidate"
            ),
        )
        for operation in locked_operations:
            with self.assertRaises(ControlCenterError) as context:
                operation()
            self.assertEqual(context.exception.code, "campaign_locked")


class ReadOnlyPlanningHandlersTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        class FakeStore:
            def __init__(self):
                self.simulation_persist = []
                self.readiness_persist = []

            def simulate_campaign(self, campaign_id, *, persist):
                self.simulation_persist.append(persist)
                return {"campaign_id": campaign_id, "acyclic": True}

            def evaluate_campaign_readiness(self, campaign_id, *, persist):
                self.readiness_persist.append(persist)
                return {
                    "campaign_id": campaign_id,
                    "ready": False,
                    "plan_signature": "a" * 64,
                }

        self.fake_store = FakeStore()
        self.store_patch = patch(
            "src.control_center_handlers.control_center",
            self.fake_store,
        )
        self.store_patch.start()
        app = web.Application()
        app.router.add_get(
            "/campaigns/{campaign_id}/simulation",
            handle_campaign_simulation,
        )
        app.router.add_get(
            "/campaigns/{campaign_id}/readiness",
            handle_campaign_readiness,
        )
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.store_patch.stop()

    async def test_get_handlers_are_explicitly_read_only(self):
        simulation = await self.client.get("/campaigns/CMP-1/simulation")
        readiness = await self.client.get("/campaigns/CMP-1/readiness")

        self.assertEqual(simulation.status, 200, await simulation.text())
        self.assertEqual(readiness.status, 200, await readiness.text())
        self.assertEqual(self.fake_store.simulation_persist, [False])
        self.assertEqual(self.fake_store.readiness_persist, [False])


class CampaignApprovalHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        class FakeStore:
            def __init__(self):
                self.cached = {}
                self.approval_signatures = []

            def get_idempotent(self, key, operation):
                return self.cached.get((key, operation))

            def remember_idempotent(self, key, operation, result):
                self.cached[(key, operation)] = result

            def approve_campaign(self, campaign_id, **payload):
                signature = payload["expected_plan_signature"]
                self.approval_signatures.append(signature)
                if signature != "a" * 64:
                    raise ControlCenterError(
                        "Plan signature changed.",
                        code="stale_plan_signature",
                        status=409,
                    )
                return {"id": campaign_id, "status": "approved"}

        self.fake_store = FakeStore()
        self.store_patch = patch(
            "src.control_center_handlers.control_center",
            self.fake_store,
        )
        self.store_patch.start()
        app = web.Application()
        app.router.add_post(
            "/campaigns/{campaign_id}/approve",
            handle_approve_campaign,
        )
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.store_patch.stop()

    async def test_idempotency_cache_is_bound_to_the_viewed_signature(self):
        headers = {"Idempotency-Key": "same-human-action"}
        payload = {
            "expected_version": 3,
            "approval_sha": SHA,
            "expected_plan_signature": "a" * 64,
        }
        approved = await self.client.post(
            "/campaigns/CMP-1/approve",
            json=payload,
            headers=headers,
        )
        self.assertEqual(approved.status, 200, await approved.text())

        stale = await self.client.post(
            "/campaigns/CMP-1/approve",
            json={**payload, "expected_plan_signature": "b" * 64},
            headers=headers,
        )

        self.assertEqual(stale.status, 409, await stale.text())
        self.assertEqual((await stale.json())["code"], "stale_plan_signature")
        self.assertEqual(
            self.fake_store.approval_signatures,
            ["a" * 64, "b" * 64],
        )


if __name__ == "__main__":
    unittest.main()
