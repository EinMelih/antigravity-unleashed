"""Contract tests for the complete engineering control-plane state machine."""

import tempfile
import unittest
from pathlib import Path

from src.control_center import ControlCenterError, ControlCenterStore
from src.database import Database
from tests.control_center_plan_fixtures import prepare_plan_for_approval


SHA_A = "a" * 40
SHA_B = "b" * 40


class TestMasterplanControlPlane(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ag_masterplan_")
        self.root = Path(self.temp.name)
        self.database = Database(self.root / "control.db")
        self.project_id = self.database.add_project("Masterplan Test", str(self.root))
        self.sha = SHA_A
        self.store = ControlCenterStore(
            self.database,
            sha_resolver=lambda _project: self.sha,
        )
        self.repository_files = {
            "src/control_center/planning.py": (
                "class PlanningMixin:\n"
                "    def evaluate_campaign_readiness(self):\n"
                "        pass\n"
            ),
            "src/control_center/planning_jobs.py": "class PlanningJobMixin:\n    pass\n",
        }
        self.store.repository_reader = (
            lambda _project, _sha, path: self.repository_files.get(path)
        )

    def tearDown(self):
        self.temp.cleanup()

    def _campaign(self, **overrides):
        payload = {
            "project_id": self.project_id,
            "title": "Masterplan Reliability",
            "goal": "Build a deterministic and reviewable delivery control plane.",
            "non_goals": "No automatic production merge or deployment.",
            "risk_level": "medium",
            "planning_depth": "compact",
            "max_candidates": 5,
            "pivotal_fork": "Use durable state instead of process memory.",
            "success_metrics": ["Every exact plan transition is verifiable."],
            "alternatives": [
                {
                    "title": "Durable state",
                    "mechanism": "Persist transitions in the control database.",
                    "tradeoffs": "More schema work, deterministic recovery.",
                },
                {
                    "title": "Process memory",
                    "mechanism": "Keep transitions in one worker process.",
                    "tradeoffs": "Less code, but restart loses exact state.",
                },
            ],
            "review_strategy": "An independent reviewer checks the exact plan evidence.",
            "rollout_plan": "Exercise the plan in one private proof repository.",
            "rollback_plan": "Revert the merge commit and restore the last stable SHA.",
        }
        payload.update(overrides)
        return self.store.create_campaign(payload)

    def _candidate(self, campaign_id, title="Persist leases", **overrides):
        payload = {
            "title": title,
            "scope": "Persist an isolated lease and prove deterministic recovery.",
            "purpose": "Provide deterministic lease ownership and recovery.",
            "non_goals": "Do not change unrelated executor behavior.",
            "components": ["src/control_center"],
            "expected_diff_type": "code-and-tests",
            "acceptance_criteria": ["Expired leases are recovered exactly once."],
            "required_checks": ["unit"],
            "manual_tests": ["Simulate an expired lease and verify one recovery."],
            "reversibility": "Revert the bounded candidate commit.",
            "migration_plan": "Use an additive idempotent schema migration.",
            "compatibility_plan": "Preserve existing task rows and API fields.",
            "documentation_changes": ["Document lease recovery behavior."],
            "definition_of_done": "Unit evidence passes for the exact PR SHA.",
            "risk_level": "medium",
            "priority": 10,
        }
        payload.update(overrides)
        return self.store.create_pr_candidate(campaign_id, payload)

    def _approved_task(self):
        campaign = self._campaign()
        candidate = self._candidate(campaign["id"])
        readiness = prepare_plan_for_approval(self.store, campaign["id"])
        campaign = self.store.overview(self.project_id)["campaigns"][0]
        campaign = self.store.approve_campaign(
            campaign["id"],
            expected_version=campaign["version"],
            approval_sha=SHA_A,
            expected_plan_signature=readiness["plan_signature"],
            actor="owner",
        )
        self.store.activate_candidate(
            candidate["id"],
            approval_sha=campaign["approved_sha"],
            actor="owner",
        )
        return self.store.list_tasks(campaign_id=campaign["id"])[0]

    def test_planning_depth_and_candidate_limits_are_hard_gates(self):
        with self.assertRaises(ControlCenterError) as context:
            self._campaign(planning_depth="exhaustive", max_candidates=101)
        self.assertEqual(context.exception.code, "invalid_max_candidates")

        campaign = self._campaign(max_candidates=1)
        self._candidate(campaign["id"])
        with self.assertRaises(ControlCenterError) as context:
            self._candidate(campaign["id"], title="Second slice")
        self.assertEqual(context.exception.code, "candidate_limit_reached")

    def test_balanced_plan_requires_design_inputs_before_approval(self):
        campaign = self._campaign(
            planning_depth="balanced",
            pivotal_fork="Use durable leases instead of in-memory ownership.",
            success_metrics=["No duplicate execution under two workers."],
            acceptance_matrix=["Lease race -> exactly one winner."],
            rollout_plan="Enable for one private proof repository first.",
        )
        self._candidate(campaign["id"])
        readiness = self.store.evaluate_campaign_readiness(campaign["id"])
        self.assertFalse(readiness["ready"])
        self.assertIn("repository_map", readiness["missing"])
        self.assertIn("design_document", readiness["missing"])
        self.assertIn("plan_simulation_artifact", readiness["missing"])

    def test_answered_question_blocks_readiness_until_plan_marks_it_resolved(self):
        campaign = self._campaign()
        self._candidate(campaign["id"])
        question = self.store.add_planning_question(
            campaign["id"],
            {
                "branch": "scope",
                "question": "Which boundary remains outside this campaign?",
            },
        )
        self.store.answer_planning_question(
            question["id"],
            {
                "answer": "Production deployment remains outside the campaign.",
                "answer_source": "owner",
            },
        )

        answered = self.store.evaluate_campaign_readiness(
            campaign["id"],
            persist=False,
        )
        self.assertFalse(answered["ready"])
        self.assertIn("unresolved_questions", answered["missing"])

        self.store.answer_planning_question(
            question["id"],
            {
                "answer": "Production deployment remains outside the campaign.",
                "answer_source": "owner",
                "status": "resolved",
            },
        )
        resolved = self.store.evaluate_campaign_readiness(
            campaign["id"],
            persist=False,
        )
        self.assertNotIn("unresolved_questions", resolved["missing"])

    def test_dependency_and_conflict_graph_produces_safe_waves(self):
        campaign = self._campaign(max_candidates=4)
        first = self._candidate(campaign["id"], title="First")
        second = self._candidate(campaign["id"], title="Second")
        third = self._candidate(
            campaign["id"],
            title="Third",
            depends_on=[first["id"]],
        )
        self.store.set_candidate_conflicts(
            campaign["id"],
            first["id"],
            [
                {
                    "candidate_id": second["id"],
                    "reason": "Both change the lease table.",
                    "resources": ["src/control_center/schema.py"],
                }
            ],
        )
        simulation = self.store.simulate_campaign(campaign["id"])
        waves = {
            candidate_id: wave["wave"]
            for wave in simulation["waves"]
            for candidate_id in wave["candidate_ids"]
        }
        self.assertNotEqual(waves[first["id"]], waves[second["id"]])
        self.assertGreater(waves[third["id"]], waves[first["id"]])
        self.assertTrue(simulation["acyclic"])

    def test_conflict_simulation_is_deterministic_across_insert_order(self):
        campaign = self._campaign(max_candidates=3)
        first = self._candidate(campaign["id"], title="First")
        second = self._candidate(campaign["id"], title="Second")
        third = self._candidate(campaign["id"], title="Third")
        conflicts = [
            {
                "candidate_id": second["id"],
                "reason": "Shared database boundary.",
                "resources": ["src/control_center/schema.py"],
            },
            {
                "candidate_id": third["id"],
                "reason": "Shared executor boundary.",
                "resources": ["src/control_center/executor_service.py"],
            },
        ]

        self.store.set_candidate_conflicts(
            campaign["id"],
            first["id"],
            conflicts,
        )
        forward = self.store.simulate_campaign(campaign["id"], persist=False)
        self.store.set_candidate_conflicts(
            campaign["id"],
            first["id"],
            list(reversed(conflicts)),
        )
        reverse = self.store.simulate_campaign(campaign["id"], persist=False)

        self.assertEqual(forward["conflicts"], reverse["conflicts"])
        self.assertEqual(forward["waves"], reverse["waves"])

    def test_task_lease_is_exclusive_and_replay_is_idempotent(self):
        task = self._approved_task()
        first = self.store.lease_next_task("worker-1")
        second = self.store.lease_next_task("worker-2")
        self.assertEqual(first["id"], task["id"])
        self.assertIsNone(second)
        replay = self.store.enqueue_task_event(
            task["id"],
            event_type="ci.completed",
            dedupe_key="delivery-1",
            payload={"conclusion": "success"},
        )
        duplicate = self.store.enqueue_task_event(
            task["id"],
            event_type="ci.completed",
            dedupe_key="delivery-1",
            payload={"conclusion": "success"},
        )
        self.assertEqual(replay["id"], duplicate["id"])

    def test_evidence_is_sha_bound_and_findings_block_human_gate(self):
        task = self._approved_task()
        self.store.set_task_revision(task["id"], sha=SHA_A)
        for key in ("acceptance:1", "check:unit", "manual:1"):
            self.store.add_evidence(
                task["id"],
                {
                    "kind": "test",
                    "criterion_key": key,
                    "title": key,
                    "status": "passed",
                    "sha": SHA_A,
                },
            )
        finding = self.store.record_finding(
            task["id"],
            {
                "classification": "BLOCKER",
                "source": "review",
                "external_id": "R1",
                "body": "A race can still duplicate a lease.",
                "sha": SHA_A,
            },
        )
        blocked = self.store.evaluate_evidence_pack(task["id"])
        self.assertEqual(blocked["status"], "blocked")
        self.store.resolve_finding(
            finding["id"],
            resolution="Atomic BEGIN IMMEDIATE coverage was added.",
        )
        ready = self.store.evaluate_evidence_pack(task["id"])
        self.assertEqual(ready["status"], "ready_for_human")
        human = self.store.record_human_approval(
            task["id"],
            approval_type="human_test",
            sha=SHA_A,
            decision="approved",
            actor="owner",
        )
        self.assertEqual(human["decision"], "approved")
        self.store.set_task_revision(task["id"], sha=SHA_B)
        pack = self.store.evidence_pack(task["id"])
        self.assertEqual(pack["status"], "collecting")
        self.assertIsNotNone(pack["approvals"][0]["revoked_at"])
        with self.assertRaises(ControlCenterError) as context:
            self.store.record_human_approval(
                task["id"],
                approval_type="merge",
                sha=SHA_A,
                decision="approved",
                actor="owner",
            )
        self.assertEqual(context.exception.code, "approval_sha_mismatch")

    def test_deployment_and_rollback_are_capability_gated(self):
        task = self._approved_task()
        self.store.set_task_revision(task["id"], sha=SHA_A)
        with self.assertRaises(ControlCenterError) as context:
            self.store.create_deployment(
                task["id"],
                {"environment": "staging", "sha": SHA_A},
            )
        self.assertEqual(context.exception.code, "deployment_capability_denied")

        self.store.update_repository_policy(
            self.project_id,
            {
                "capability": {
                    "deploy_staging": True,
                    "rollback": True,
                }
            },
        )
        deployment = self.store.create_deployment(
            task["id"],
            {
                "environment": "staging",
                "sha": SHA_A,
                "previous_stable_sha": SHA_B,
            },
        )
        running = self.store.update_deployment(
            deployment["id"],
            status="running",
        )
        self.assertEqual(running["status"], "running")
        failed = self.store.update_deployment(
            deployment["id"],
            status="failed",
            health={"ok": False},
        )
        self.assertEqual(failed["status"], "failed")
        rollback = self.store.rollback_deployment(
            deployment["id"],
            reason="Staging health check failed.",
        )
        self.assertEqual(rollback["rollback_of"], deployment["id"])
        self.assertEqual(rollback["sha"], SHA_B)

    def _generated_plan(self):
        return {
            "title": "Generated reliability plan",
            "goal": "Prove deterministic execution and SHA-bound human gates.",
            "non_goals": "No production deployment.",
            "risk_level": "medium",
            "pivotal_fork": "Use durable leases and isolated worktrees.",
            "success_metrics": ["No duplicate task execution."],
            "constraints": ["Keep production disabled."],
            "assumptions": ["GitHub checks expose stable names."],
            "acceptance_matrix": ["Two workers -> one lease winner."],
            "alternatives": [
                {
                    "title": "Durable leases",
                    "mechanism": "Claim a persisted lease in one atomic transaction.",
                    "tradeoffs": "Schema complexity, but restart-safe ownership.",
                },
                {
                    "title": "In-memory ownership",
                    "mechanism": "Track the active worker only inside one process.",
                    "tradeoffs": "Simpler code, but restart loses ownership state.",
                },
            ],
            "review_strategy": "An independent reviewer verifies race safety and exact evidence.",
            "rollout_plan": "Start with one private proof repository.",
            "rollback_plan": "Revert the merge commit.",
            "repository_map": (
                "# Repository map\n\n"
                "`src/control_center/planning.py` owns canonical plan readiness."
            ),
            "design_document": "# Design\n\nDurable state machine.",
            "adr": "",
            "branch_assessments": [
                {
                    "branch": branch,
                    "question": f"What repository fact grounds {branch}?",
                    "rationale": f"The repository map verifies the {branch} boundary.",
                    "status": "grounded",
                    "owner": "repository-mapper",
                    "evidence": {"path": "src/control_center/planning.py"},
                }
                for branch in ("architecture", "data", "security", "operations")
            ],
            "candidates": [
                {
                    "id": "slice-01",
                    "title": "Persist executor lease",
                    "scope": "Persist and atomically acquire one executor lease.",
                    "purpose": "Provide restart-safe exclusive lease ownership.",
                    "non_goals": "Do not alter unrelated task execution.",
                    "components": ["src/control_center/execution.py"],
                    "expected_diff_type": "code-and-tests",
                    "acceptance_criteria": ["Exactly one worker acquires the lease."],
                    "required_checks": ["unit"],
                    "manual_tests": ["Race two workers against one queued task."],
                    "reversibility": "Revert the lease persistence commit.",
                    "migration_plan": "Add lease columns idempotently.",
                    "compatibility_plan": "Default legacy task rows safely.",
                    "documentation_changes": ["Document lease ownership."],
                    "definition_of_done": "Unit proof exists for the final SHA.",
                    "risk_level": "medium",
                    "priority": 10,
                    "depends_on": [],
                },
                {
                    "id": "slice-02",
                    "title": "Expose evidence gate",
                    "scope": "Expose the exact-SHA evidence gate in the Hub API.",
                    "purpose": "Prevent stale evidence from authorizing a new revision.",
                    "non_goals": "Do not change merge or deployment policy.",
                    "components": ["src/control_center/evidence.py"],
                    "expected_diff_type": "code-and-tests",
                    "acceptance_criteria": ["A new SHA revokes the old approval."],
                    "required_checks": ["unit"],
                    "manual_tests": ["Change the SHA and inspect revoked approval."],
                    "reversibility": "Revert the evidence-gate commit.",
                    "migration_plan": "Not applicable: no persistent shape change.",
                    "compatibility_plan": "Preserve prior evidence response fields.",
                    "documentation_changes": ["Document SHA-bound approvals."],
                    "definition_of_done": "Revocation is covered by a unit test.",
                    "risk_level": "medium",
                    "priority": 20,
                    "depends_on": ["slice-01"],
                },
            ],
        }

    def test_generated_plan_requires_exactly_one_assessment_per_branch(self):
        job = self.store.create_planning_job(
            {
                "project_id": self.project_id,
                "wish": "Build a deterministic exact-branch planning contract.",
                "planning_depth": "balanced",
                "max_candidates": 12,
            }
        )
        self.store.claim_planning_job()
        plan = self._generated_plan()
        plan["branch_assessments"][-1] = dict(plan["branch_assessments"][0])

        with self.assertRaises(ControlCenterError) as context:
            self.store.complete_planning_job(job["id"], plan)

        self.assertEqual(context.exception.code, "invalid_branch_assessment_set")

    def test_generated_plan_rejects_unverified_branch_dispositions(self):
        def assert_rejected(mutator, expected_code):
            job = self.store.create_planning_job(
                {
                    "project_id": self.project_id,
                    "wish": "Verify every final branch against the pinned repository.",
                    "planning_depth": "balanced",
                    "max_candidates": 12,
                }
            )
            claimed = self.store.claim_planning_job()
            self.assertEqual(claimed["id"], job["id"])
            plan = self._generated_plan()
            plan["title"] = f"Rejected {expected_code}"
            mutator(plan)
            caught = None
            try:
                self.store.complete_planning_job(job["id"], plan)
            except ControlCenterError as exc:
                caught = exc
            finally:
                current = self.store.get_planning_job(job["id"])
                if current["status"] in {
                    "queued",
                    "running",
                    "waiting_human",
                    "failed",
                }:
                    self.store.cancel_planning_job(
                        job["id"],
                        actor="test",
                        reason="Finish rejected-grounding regression setup.",
                    )
            self.assertIsNotNone(caught)
            self.assertEqual(caught.code, expected_code)

        def defer_every_branch(plan):
            for assessment in plan["branch_assessments"]:
                assessment.update(
                    {
                        "status": "deferred",
                        "rationale": "The repository shows this branch is outside scope.",
                        "owner": "planner",
                        "evidence": {"not_applicable": True},
                    }
                )

        cases = (
            (defer_every_branch, "grounded_branch_required"),
            (
                lambda plan: plan["branch_assessments"][0].update(
                    {"evidence": {"invalid_json": "synthetic sentinel"}}
                ),
                "invalid_branch_assessment_evidence",
            ),
            (
                lambda plan: plan["branch_assessments"][0].update(
                    {"status": "resolved", "answer": ""}
                ),
                "invalid_branch_assessment_resolution",
            ),
            (
                lambda plan: plan["branch_assessments"][0].update(
                    {"evidence": {"path": "src/missing.py"}}
                ),
                "planning_grounded_path_not_found",
            ),
            (
                lambda plan: plan["branch_assessments"][0].update(
                    {
                        "evidence": {
                            "path": "src/control_center/planning.py",
                            "symbol": "DefinitelyMissingSymbol",
                        }
                    }
                ),
                "planning_grounded_symbol_not_found",
            ),
            (
                lambda plan: plan["branch_assessments"][0].update(
                    {
                        "evidence": {
                            "path": "src/control_center/planning.py",
                            "symbol": "Planning",
                        }
                    }
                ),
                "planning_grounded_symbol_not_found",
            ),
            (
                lambda plan: plan.update(
                    {"repository_map": "# Repository map\n\nNo verified path listed."}
                ),
                "repository_map_grounding_missing",
            ),
            (
                lambda plan: plan.update(
                    {
                        "repository_map": (
                            "# Repository map\n\n"
                            "Only `src/control_center/planning.py.backup` is listed."
                        )
                    }
                ),
                "repository_map_grounding_missing",
            ),
        )
        for mutator, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                assert_rejected(mutator, expected_code)

    def test_generated_plan_rejects_every_missing_candidate_contract_field(self):
        required_fields = {
            "components": [],
            "required_checks": [],
            "manual_tests": [],
            "documentation_changes": [],
            "non_goals": "",
            "purpose": "",
            "expected_diff_type": "",
            "reversibility": "",
            "migration_plan": "",
            "compatibility_plan": "",
            "definition_of_done": "",
        }
        for field, empty_value in required_fields.items():
            with self.subTest(field=field):
                job = self.store.create_planning_job(
                    {
                        "project_id": self.project_id,
                        "wish": "Reject incomplete generated PR contracts before import.",
                        "planning_depth": "balanced",
                        "max_candidates": 12,
                    }
                )
                claimed = self.store.claim_planning_job()
                self.assertEqual(claimed["id"], job["id"])
                plan = self._generated_plan()
                plan["title"] = f"Missing generated contract field {field}"
                plan["candidates"][0][field] = empty_value
                caught = None
                try:
                    self.store.complete_planning_job(job["id"], plan)
                except ControlCenterError as exc:
                    caught = exc
                finally:
                    current = self.store.get_planning_job(job["id"])
                    if current["status"] in {
                        "queued",
                        "running",
                        "waiting_human",
                        "failed",
                    }:
                        self.store.cancel_planning_job(
                            job["id"],
                            actor="test",
                            reason="Finish strict generated-contract regression setup.",
                        )
                self.assertIsNotNone(caught)
                self.assertEqual(caught.code, f"missing_{field}")

    def test_generated_plan_is_imported_as_one_reviewable_campaign(self):
        job = self.store.create_planning_job(
            {
                "project_id": self.project_id,
                "wish": "Build a deterministic executor with exact-SHA human gates.",
                "planning_depth": "balanced",
                "max_candidates": 12,
            }
        )
        claimed = self.store.claim_planning_job()
        self.assertEqual(claimed["id"], job["id"])
        completed = self.store.complete_planning_job(
            job["id"],
            self._generated_plan(),
        )
        self.assertEqual(completed["status"], "waiting_human")
        overview = self.store.overview(self.project_id)
        campaign = overview["campaigns"][0]
        self.assertEqual(len(campaign["pr_candidates"]), 2)
        self.assertEqual(
            campaign["pr_candidates"][1]["depends_on"],
            [campaign["pr_candidates"][0]["id"]],
        )
        artifact_types = {item["artifact_type"] for item in campaign["artifacts"]}
        self.assertTrue(
            {"repository_map", "design_document", "plan_simulation"}
            <= artifact_types
        )
        self.assertEqual(len(campaign["profile"]["alternatives"]), 2)
        self.assertTrue(campaign["profile"]["review_strategy"])
        self.assertTrue(
            {"architecture", "data", "security", "operations"}
            <= {question["branch"] for question in campaign["questions"]}
        )

    def test_generated_percentage_scores_are_normalized_to_ten_point_scale(self):
        job = self.store.create_planning_job(
            {
                "project_id": self.project_id,
                "wish": "Normalize model-generated percentage scores safely.",
            }
        )
        self.store.claim_planning_job()
        plan = self._generated_plan()
        plan["candidates"] = [plan["candidates"][0]]
        plan["candidates"][0].update(
            {
                "business_value": 30,
                "unblock_score": 100,
                "learning_value": 20,
                "urgency_score": 50,
                "effort_score": 3,
                "change_risk_score": 1,
                "reversibility_score": 1,
            }
        )

        self.store.complete_planning_job(job["id"], plan)

        candidate = self.store.overview(self.project_id)["campaigns"][0][
            "pr_candidates"
        ][0]
        contract = candidate["contract"]
        self.assertEqual(contract["business_value"], 3)
        self.assertEqual(contract["unblock_score"], 10)
        self.assertEqual(contract["learning_value"], 2)
        self.assertEqual(contract["urgency_score"], 5)
        self.assertEqual(contract["effort_score"], 3)

    def test_generated_scores_above_percentage_scale_remain_invalid(self):
        job = self.store.create_planning_job(
            {
                "project_id": self.project_id,
                "wish": "Reject nonsensical model-generated scores.",
            }
        )
        self.store.claim_planning_job()
        plan = self._generated_plan()
        plan["candidates"] = [plan["candidates"][0]]
        plan["candidates"][0]["business_value"] = 101

        with self.assertRaises(ControlCenterError) as context:
            self.store.complete_planning_job(job["id"], plan)

        self.assertEqual(context.exception.code, "invalid_business_value")

    def test_interrupted_planning_job_is_failed_and_attempt_is_refunded(self):
        job = self.store.create_planning_job(
            {
                "project_id": self.project_id,
                "wish": "Recover safely after an interrupted planner process.",
            }
        )
        claimed = self.store.claim_planning_job()
        self.assertEqual(claimed["attempt"], 1)
        self.store.update_planning_job_chat(job["id"], "planner-chat")

        recovered = self.store.recover_interrupted_planning_jobs()

        self.assertEqual(recovered, 1)
        current = self.store.get_planning_job(job["id"])
        self.assertEqual(current["status"], "failed")
        self.assertEqual(current["attempt"], 0)
        self.assertIn("neu gestartet", current["last_error"])
        retried = self.store.retry_planning_job(job["id"])
        self.assertEqual(retried["status"], "queued")

    def test_agent_permission_attention_is_unique_and_redacts_secrets(self):
        gate = {
            "chat_id": "chat-secret",
            "tool_name": "run_command",
            "command": (
                "curl -H 'Authorization: Bearer EXAMPLE_TOKEN_DO_NOT_USE' "
                "https://example.test?token=plainsecret"
            ),
        }
        for _ in range(2):
            self.store.set_agent_permission_attention(
                project_id=self.project_id,
                entity_type="planning_job",
                entity_id="PLAN-SECRET",
                gate=gate,
            )

        overview = self.store.overview(self.project_id)
        matching = [
            item
            for item in overview["attention"]
            if item["category"] == "agent_permission"
            and item["entity_id"] == "PLAN-SECRET"
        ]
        self.assertEqual(len(matching), 1)
        serialized = str(matching[0]) + str(overview["audit"])
        self.assertNotIn("EXAMPLE_TOKEN_DO_NOT_USE", serialized)
        self.assertNotIn("plainsecret", serialized)
        self.assertIn("[REDACTED]", serialized)

        self.store.set_agent_permission_attention(
            project_id=self.project_id,
            entity_type="planning_job",
            entity_id="PLAN-SECRET",
            gate=None,
        )
        self.assertFalse(
            any(
                item["entity_id"] == "PLAN-SECRET"
                for item in self.store.overview(self.project_id)["attention"]
            )
        )

    def test_invalid_generated_cycle_rolls_back_campaign(self):
        job = self.store.create_planning_job(
            {
                "project_id": self.project_id,
                "wish": "Create a plan that must reject cyclic slice dependencies.",
            }
        )
        self.store.claim_planning_job()
        plan = self._generated_plan()
        plan["candidates"][0]["depends_on"] = ["slice-02"]
        with self.assertRaises(ControlCenterError) as context:
            self.store.complete_planning_job(job["id"], plan)
        self.assertEqual(context.exception.code, "cyclic_pr_dependencies")
        self.assertEqual(self.store.overview(self.project_id)["campaigns"], [])

    def test_exhaustive_plan_maps_100_candidates_without_materializing_work(self):
        job = self.store.create_planning_job(
            {
                "project_id": self.project_id,
                "wish": "Map every useful reliability slice before selecting a bounded wave.",
                "planning_depth": "exhaustive",
                "max_candidates": 100,
            }
        )
        claimed = self.store.claim_planning_job()
        self.assertEqual(claimed["id"], job["id"])
        plan = self._generated_plan()
        plan["title"] = "Exhaustive bounded map"
        plan["candidates"] = [
            {
                "id": f"slice-{index:03d}",
                "title": f"Reliability slice {index:03d}",
                "scope": (
                    "Implement one independently reviewable reliability improvement "
                    f"for subsystem {index:03d}."
                ),
                "purpose": (
                    f"Make subsystem {index:03d} independently verifiable."
                ),
                "non_goals": "Do not change unrelated subsystems.",
                "components": [f"src/subsystem-{index:03d}"],
                "expected_diff_type": "code-and-tests",
                "acceptance_criteria": [
                    f"Subsystem {index:03d} has exact-SHA evidence."
                ],
                "required_checks": ["unit"],
                "manual_tests": [
                    f"Inspect subsystem {index:03d} at the exact planned SHA."
                ],
                "reversibility": "Revert the bounded subsystem commit.",
                "migration_plan": "Not applicable: no persistent data migration.",
                "compatibility_plan": "Preserve the existing subsystem interface.",
                "documentation_changes": [
                    f"Document the subsystem {index:03d} evidence contract."
                ],
                "definition_of_done": "The isolated evidence gate passes.",
                "risk_level": "low",
                "priority": index,
                "depends_on": [],
            }
            for index in range(1, 101)
        ]
        completed = self.store.complete_planning_job(job["id"], plan)
        self.assertEqual(completed["status"], "waiting_human")
        overview = self.store.overview(self.project_id)
        self.assertEqual(len(overview["campaigns"][0]["pr_candidates"]), 100)
        self.assertEqual(overview["tasks"], [])


if __name__ == "__main__":
    unittest.main()
