"""Canonical complete plan fixtures for downstream control-plane tests."""

from __future__ import annotations

import hashlib
import json

from src.control_center.common import canonical_json_sha256


def prepare_plan_for_approval(store, campaign_id: str) -> dict:
    """Complete an existing test campaign without exercising plan mutation APIs."""
    with store.db._get_connection() as conn:
        campaign = conn.execute(
            "SELECT * FROM control_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if not campaign:
            raise AssertionError(f"Campaign fixture not found: {campaign_id}")
        conn.execute(
            """UPDATE control_campaigns
               SET non_goals = CASE WHEN TRIM(non_goals) = ''
                   THEN 'Do not merge, deploy, or broaden the test scope.'
                   ELSE non_goals END
               WHERE id = ?""",
            (campaign_id,),
        )
        alternatives = [
            {
                "title": "Persistent control state",
                "mechanism": "Persist the plan and approvals in the control database.",
                "tradeoffs": "More fixture state, but deterministic recovery and review.",
            },
            {
                "title": "Ephemeral process state",
                "mechanism": "Keep the plan only in the active worker process.",
                "tradeoffs": "Less storage, but unsafe restart and approval semantics.",
            },
        ]
        conn.execute(
            """UPDATE control_campaign_profiles
               SET pivotal_fork = CASE WHEN TRIM(pivotal_fork) = ''
                       THEN 'Persist exact plan state instead of process memory.'
                       ELSE pivotal_fork END,
                   success_metrics_json = CASE WHEN success_metrics_json = '[]'
                       THEN '["The exact approved contract remains verifiable."]'
                       ELSE success_metrics_json END,
                   acceptance_matrix_json = CASE WHEN acceptance_matrix_json = '[]'
                       THEN '["Approved snapshot -> exact evidence"]'
                       ELSE acceptance_matrix_json END,
                   alternatives_json = ?,
                   review_strategy = CASE WHEN TRIM(review_strategy) = ''
                       THEN 'An independent reviewer checks scope, tests, risks, and rollback.'
                       ELSE review_strategy END,
                   rollout_plan = CASE WHEN TRIM(rollout_plan) = ''
                       THEN 'Exercise the bounded change in one private proof repository.'
                       ELSE rollout_plan END,
                   rollback_plan = CASE WHEN TRIM(rollback_plan) = ''
                       THEN 'Revert the bounded change and restore the prior SHA.'
                       ELSE rollback_plan END
               WHERE campaign_id = ?""",
            (json.dumps(alternatives), campaign_id),
        )
        candidates = conn.execute(
            "SELECT id FROM control_pr_candidates WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchall()
        for candidate in candidates:
            candidate_id = str(candidate["id"])
            conn.execute(
                """UPDATE control_pr_candidates
                   SET non_goals = CASE WHEN TRIM(non_goals) = ''
                       THEN 'Do not change unrelated behavior.' ELSE non_goals END
                   WHERE id = ?""",
                (candidate_id,),
            )
            conn.execute(
                """UPDATE control_candidate_contracts
                   SET purpose = CASE WHEN TRIM(purpose) = ''
                           THEN 'Deliver the bounded candidate outcome.' ELSE purpose END,
                       components_json = CASE WHEN components_json = '[]'
                           THEN '["src"]' ELSE components_json END,
                       expected_diff_type = CASE WHEN TRIM(expected_diff_type) = ''
                           THEN 'code-and-tests' ELSE expected_diff_type END,
                       required_checks_json = CASE WHEN required_checks_json = '[]'
                           THEN '["unit"]' ELSE required_checks_json END,
                       manual_tests_json = CASE WHEN manual_tests_json = '[]'
                           THEN '["Verify the bounded outcome manually."]'
                           ELSE manual_tests_json END,
                       reversibility = CASE WHEN TRIM(reversibility) = ''
                           THEN 'Revert the candidate commit.' ELSE reversibility END,
                       migration_plan = CASE WHEN TRIM(migration_plan) = ''
                           THEN 'Not applicable: no persistent data changes.'
                           ELSE migration_plan END,
                       compatibility_plan = CASE WHEN TRIM(compatibility_plan) = ''
                           THEN 'Preserve the existing public contract.'
                           ELSE compatibility_plan END,
                       documentation_json = CASE WHEN documentation_json = '[]'
                           THEN '["Document the verified behavior."]'
                           ELSE documentation_json END,
                       definition_of_done = CASE WHEN TRIM(definition_of_done) = ''
                           THEN 'The exact checks and manual proof pass.'
                           ELSE definition_of_done END
                   WHERE candidate_id = ?""",
                (candidate_id,),
            )
        for branch in ("architecture", "data", "security", "operations"):
            question_id = f"FIX-{campaign_id}-{branch}"
            evidence = json.dumps(
                {
                    "path": "src/control_center/planning.py",
                    "fact": f"Fixture grounds the {branch} branch.",
                }
            )
            conn.execute(
                """INSERT OR IGNORE INTO control_question_ledger (
                       id, campaign_id, branch, question, rationale,
                       status, owner, evidence_json, resolved_in_version
                   ) VALUES (?, ?, ?, ?, ?, 'grounded', 'test-fixture', ?, ?)""",
                (
                    question_id,
                    campaign_id,
                    branch,
                    f"What repository fact grounds the {branch} branch?",
                    f"The test fixture records the {branch} repository boundary.",
                    evidence,
                    int(campaign["version"]),
                ),
            )
        required_artifacts = [("repository_map", "current")]
        profile = conn.execute(
            "SELECT planning_depth FROM control_campaign_profiles WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if profile and str(profile["planning_depth"]) in {
            "balanced",
            "deep",
            "exhaustive",
        }:
            required_artifacts.extend(
                [("design_document", "proposed"), ("plan_simulation", "current")]
            )
        if str(campaign["risk_level"]) in {"high", "critical"}:
            required_artifacts.append(("adr", "proposed"))
        simulation_hash = ""
        if any(
            artifact_type == "plan_simulation"
            for artifact_type, _status in required_artifacts
        ):
            simulation_hash = canonical_json_sha256(
                store._simulate_campaign_in_connection(
                    conn,
                    campaign_id,
                    persist=False,
                )
            )
        for artifact_type, status in required_artifacts:
            content = f"# {artifact_type}\n\nVerified fixture for `{campaign_id}`."
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            artifact_id = f"FIX-DOC-{campaign_id}-{artifact_type}"
            metadata = {
                "base_sha": str(campaign["base_sha"] or ""),
                "campaign_version": int(campaign["version"]),
            }
            if artifact_type == "repository_map":
                metadata["grounded_paths"] = ["src/control_center/planning.py"]
            if artifact_type == "plan_simulation":
                metadata["simulation_sha256"] = simulation_hash
            conn.execute(
                """INSERT OR IGNORE INTO control_artifacts (
                       id, project_id, campaign_id, artifact_type, slug, title,
                       status, version, relative_path, content_text,
                       content_sha256, metadata_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, '', ?, ?, ?)""",
                (
                    artifact_id,
                    int(campaign["project_id"]),
                    campaign_id,
                    artifact_type,
                    f"fixture-{campaign_id}-{artifact_type}",
                    f"Fixture {artifact_type}",
                    status,
                    content,
                    digest,
                    json.dumps(metadata),
                ),
            )
        conn.commit()
    readiness = store.evaluate_campaign_readiness(campaign_id, persist=False)
    if not readiness["ready"]:
        raise AssertionError(
            f"Canonical approval fixture is not ready: {readiness['missing']}"
        )
    return readiness
