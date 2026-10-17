"""Typed, exact and atomic re-planning for an existing Campaign."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable

from src.control_center.artifacts import slugify
from src.control_center.common import (
    ACTIVATION_POLICIES,
    PLANNING_DEPTHS,
    ControlCenterError,
    canonical_json_sha256,
    clean_text,
    public_id,
    validate_acceptance_criteria,
)
from src.control_center.planning import PLAN_SIGNATURE_VERSION


AMENDMENT_OPEN_STATES = {"planning", "review", "failed", "proposed"}
AMENDMENT_TERMINAL_STATES = {"approved", "rejected", "cancelled"}
AMENDMENT_JSON_FIELDS = (
    "impact_json",
    "focus_json",
    "before_plan_json",
    "target_plan_json",
    "patch_json",
    "validation_json",
)
PROFILE_LIST_FIELDS = (
    "success_metrics",
    "constraints",
    "assumptions",
    "acceptance_matrix",
)
CONTRACT_LIST_FIELDS = (
    "components",
    "required_checks",
    "manual_tests",
    "documentation_changes",
)


def _json_value(value: Any, fallback: Any) -> Any:
    if not isinstance(value, str):
        return copy.deepcopy(value if value is not None else fallback)
    try:
        return json.loads(value or json.dumps(fallback))
    except (json.JSONDecodeError, TypeError):
        return copy.deepcopy(fallback)


def _text_list(value: Any, field: str, *, required: bool = False) -> list[str]:
    if isinstance(value, str):
        value = [line.strip() for line in value.splitlines() if line.strip()]
    if not isinstance(value, list):
        raise ControlCenterError(
            f"{field} muss eine Liste sein.",
            code=f"invalid_{field}",
        )
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text[:2000])
    if required and not result:
        raise ControlCenterError(
            f"{field} ist erforderlich.",
            code=f"missing_{field}",
        )
    return result


class AmendmentPlanningMixin:
    """One staged target, one exact human decision, one atomic apply."""

    @staticmethod
    def _plan_snapshot_sha256(snapshot: Dict[str, Any]) -> str:
        return canonical_json_sha256(snapshot)

    @staticmethod
    def _deterministic_amendment_id(
        prefix: str,
        amendment_id: str,
        kind: str,
        client_id: str,
        index: int,
    ) -> str:
        digest = hashlib.sha256(
            f"{amendment_id}:{kind}:{client_id}:{index}".encode("utf-8")
        ).hexdigest()[:20]
        return f"{prefix}-{digest.upper()}"

    def _amendment_row(
        self,
        row,
        *,
        include_payload: bool,
    ) -> Dict[str, Any]:
        result = self._row(row, AMENDMENT_JSON_FIELDS)
        if result is None:
            raise ControlCenterError(
                "Plan Amendment nicht gefunden.",
                code="amendment_not_found",
                status=404,
            )
        if not include_payload:
            result.pop("before_plan", None)
            result.pop("target_plan", None)
            result.pop("patch", None)
        return result

    def _get_plan_amendment_in_connection(
        self,
        conn,
        amendment_id: str,
        *,
        include_payload: bool = True,
    ) -> Dict[str, Any]:
        row = conn.execute(
            "SELECT * FROM control_plan_amendments WHERE id = ?",
            (amendment_id,),
        ).fetchone()
        return self._amendment_row(row, include_payload=include_payload)

    def get_plan_amendment(self, amendment_id: str) -> Dict[str, Any]:
        with self.db._get_connection() as conn:
            return self._get_plan_amendment_in_connection(
                conn,
                clean_text(amendment_id, "amendment_id", maximum=120),
            )

    @staticmethod
    def _contract_snapshot(row) -> Dict[str, Any]:
        return {
            "purpose": str(row["purpose"] or ""),
            "components": _json_value(row["components_json"], []),
            "expected_diff_type": str(row["expected_diff_type"] or ""),
            "required_checks": _json_value(row["required_checks_json"], []),
            "manual_tests": _json_value(row["manual_tests_json"], []),
            "reversibility": str(row["reversibility"] or ""),
            "migration_plan": str(row["migration_plan"] or ""),
            "compatibility_plan": str(row["compatibility_plan"] or ""),
            "documentation_changes": _json_value(row["documentation_json"], []),
            "definition_of_done": str(row["definition_of_done"] or ""),
            "estimated_size": str(row["estimated_size"] or "small"),
            "business_value": float(row["business_value"]),
            "unblock_score": float(row["unblock_score"]),
            "learning_value": float(row["learning_value"]),
            "urgency_score": float(row["urgency_score"]),
            "effort_score": float(row["effort_score"]),
            "change_risk_score": float(row["change_risk_score"]),
            "reversibility_score": float(row["reversibility_score"]),
            "ready_score": float(row["ready_score"]),
            "pinned": bool(row["pinned"]),
            "paused": bool(row["paused"]),
            "override_reason": str(row["override_reason"] or ""),
        }

    def _plan_snapshot_in_connection(
        self,
        conn,
        campaign_id: str,
    ) -> Dict[str, Any]:
        campaign = self._campaign(conn, campaign_id)
        profile = conn.execute(
            "SELECT * FROM control_campaign_profiles WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if not profile:
            raise ControlCenterError(
                "Campaign-Planungsprofil fehlt.",
                code="campaign_profile_not_found",
                status=404,
            )
        contract_rows = conn.execute(
            """SELECT contract.* FROM control_candidate_contracts contract
               JOIN control_pr_candidates candidate
                 ON candidate.id = contract.candidate_id
               WHERE candidate.campaign_id = ?""",
            (campaign_id,),
        ).fetchall()
        contracts = {
            str(row["candidate_id"]): self._contract_snapshot(row)
            for row in contract_rows
        }
        candidates = []
        for row in conn.execute(
            """SELECT * FROM control_pr_candidates
               WHERE campaign_id = ? ORDER BY id""",
            (campaign_id,),
        ).fetchall():
            candidate_id = str(row["id"])
            candidates.append(
                {
                    "id": candidate_id,
                    "title": str(row["title"]),
                    "scope": str(row["scope"]),
                    "acceptance_criteria": _json_value(
                        row["acceptance_criteria_json"], []
                    ),
                    "non_goals": str(row["non_goals"] or ""),
                    "risk_level": str(row["risk_level"]),
                    "priority": int(row["priority"]),
                    "status": str(row["status"]),
                    "base_sha": str(row["base_sha"] or ""),
                    "contract": contracts.get(candidate_id),
                }
            )
        ledger = [
            {
                "id": str(row["id"]),
                "branch": str(row["branch"]),
                "planning_job_id": (
                    str(row["planning_job_id"])
                    if row["planning_job_id"] is not None
                    else None
                ),
                "content_hash": str(row["content_hash"] or ""),
                "question": str(row["question"]),
                "rationale": str(row["rationale"] or ""),
                "answer": str(row["answer"] or ""),
                "answer_source": str(row["answer_source"] or ""),
                "status": str(row["status"]),
                "owner": str(row["owner"] or ""),
                "evidence": _json_value(row["evidence_json"], {}),
                "contradiction_of": (
                    str(row["contradiction_of"])
                    if row["contradiction_of"] is not None
                    else None
                ),
                "resolved_in_version": row["resolved_in_version"],
            }
            for row in conn.execute(
                """SELECT * FROM control_question_ledger
                   WHERE campaign_id = ? AND amendment_id IS NULL
                   ORDER BY id""",
                (campaign_id,),
            ).fetchall()
        ]
        artifacts = [
            {
                "id": str(row["id"]),
                "artifact_type": str(row["artifact_type"]),
                "slug": str(row["slug"]),
                "title": str(row["title"]),
                "status": str(row["status"]),
                "version": int(row["version"]),
                "supersedes_id": (
                    str(row["supersedes_id"])
                    if row["supersedes_id"] is not None
                    else None
                ),
                "relative_path": str(row["relative_path"] or ""),
                "content": str(row["content_text"] or ""),
                "content_sha256": str(row["content_sha256"] or ""),
                "metadata": _json_value(row["metadata_json"], {}),
            }
            for row in conn.execute(
                """SELECT * FROM control_artifacts
                   WHERE campaign_id = ? ORDER BY id""",
                (campaign_id,),
            ).fetchall()
        ]
        dependencies = [
            dict(row)
            for row in conn.execute(
                """SELECT dependency.candidate_id, dependency.depends_on_id
                   FROM control_pr_dependencies dependency
                   JOIN control_pr_candidates candidate
                     ON candidate.id = dependency.candidate_id
                   WHERE candidate.campaign_id = ?
                   ORDER BY dependency.candidate_id, dependency.depends_on_id""",
                (campaign_id,),
            ).fetchall()
        ]
        conflicts = [
            {
                "candidate_id": str(row["candidate_id"]),
                "conflicts_with_id": str(row["conflicts_with_id"]),
                "reason": str(row["reason"]),
                "resources": _json_value(row["resources_json"], []),
            }
            for row in conn.execute(
                """SELECT conflict.* FROM control_candidate_conflicts conflict
                   JOIN control_pr_candidates candidate
                     ON candidate.id = conflict.candidate_id
                   WHERE candidate.campaign_id = ?
                   ORDER BY conflict.candidate_id, conflict.conflicts_with_id""",
                (campaign_id,),
            ).fetchall()
        ]
        knowledge = {
            "idea_seed_artifacts": [
                {
                    "source_kind": "idea_seed",
                    "source_id": str(row["idea_seed_id"]),
                    "target_kind": "artifact",
                    "target_id": str(row["artifact_id"]),
                    "relation_type": str(row["relation_type"]),
                }
                for row in conn.execute(
                    """SELECT link.* FROM control_idea_seed_artifacts link
                       JOIN control_artifacts artifact ON artifact.id = link.artifact_id
                       WHERE artifact.campaign_id = ?
                       ORDER BY link.idea_seed_id, link.artifact_id, link.relation_type""",
                    (campaign_id,),
                ).fetchall()
            ],
            "artifact_relations": [
                {
                    "source_kind": "artifact",
                    "source_id": str(row["source_artifact_id"]),
                    "target_kind": "artifact",
                    "target_id": str(row["target_artifact_id"]),
                    "relation_type": str(row["relation_type"]),
                }
                for row in conn.execute(
                    """SELECT relation.* FROM control_artifact_relations relation
                       JOIN control_artifacts source
                         ON source.id = relation.source_artifact_id
                       JOIN control_artifacts target
                         ON target.id = relation.target_artifact_id
                       WHERE source.campaign_id = ? AND target.campaign_id = ?
                       ORDER BY relation.source_artifact_id,
                                relation.target_artifact_id, relation.relation_type""",
                    (campaign_id, campaign_id),
                ).fetchall()
            ],
            "candidate_artifacts": [
                {
                    "source_kind": "candidate",
                    "source_id": str(row["candidate_id"]),
                    "target_kind": "artifact",
                    "target_id": str(row["artifact_id"]),
                    "relation_type": str(row["relation_type"]),
                }
                for row in conn.execute(
                    """SELECT link.* FROM control_candidate_artifacts link
                       JOIN control_pr_candidates candidate
                         ON candidate.id = link.candidate_id
                       JOIN control_artifacts artifact ON artifact.id = link.artifact_id
                       WHERE candidate.campaign_id = ? AND artifact.campaign_id = ?
                       ORDER BY link.candidate_id, link.artifact_id, link.relation_type""",
                    (campaign_id, campaign_id),
                ).fetchall()
            ],
        }
        return {
            "signature_version": PLAN_SIGNATURE_VERSION,
            "campaign": {
                "id": str(campaign["id"]),
                "title": str(campaign["title"]),
                "goal": str(campaign["goal"]),
                "non_goals": str(campaign["non_goals"] or ""),
                "risk_level": str(campaign["risk_level"]),
                "version": int(campaign["version"]),
                "base_sha": str(campaign["base_sha"] or ""),
                "approved_version": campaign["approved_version"],
                "approved_sha": str(campaign["approved_sha"] or ""),
                "approved_by": str(campaign["approved_by"] or ""),
            },
            "profile": {
                "slug": str(profile["slug"]),
                "planning_depth": str(profile["planning_depth"]),
                "requested_max_candidates": int(profile["requested_max_candidates"]),
                "activation_policy": str(profile["activation_policy"]),
                "pivotal_fork": str(profile["pivotal_fork"] or ""),
                "pivotal_fork_na_reason": str(
                    profile["pivotal_fork_na_reason"] or ""
                ),
                "success_metrics": _json_value(profile["success_metrics_json"], []),
                "constraints": _json_value(profile["constraints_json"], []),
                "assumptions": _json_value(profile["assumptions_json"], []),
                "acceptance_matrix": _json_value(
                    profile["acceptance_matrix_json"], []
                ),
                "alternatives": _json_value(profile["alternatives_json"], []),
                "review_strategy": str(profile["review_strategy"] or ""),
                "rollout_plan": str(profile["rollout_plan"] or ""),
                "rollback_plan": str(profile["rollback_plan"] or ""),
                "repository_map_artifact_id": profile["repository_map_artifact_id"],
                "design_artifact_id": profile["design_artifact_id"],
                "plan_simulation_artifact_id": profile["plan_simulation_artifact_id"],
                "estimated_cost": float(profile["estimated_cost"]),
            },
            "ledger": ledger,
            "artifacts": artifacts,
            "candidates": candidates,
            "dependencies": dependencies,
            "conflicts": conflicts,
            "knowledge_relations": knowledge,
        }

    def get_plan_snapshot(self, campaign_id: str) -> Dict[str, Any]:
        with self.db._get_connection() as conn:
            return self._plan_snapshot_in_connection(conn, campaign_id)

    def _mutable_candidate_ids(self, conn, campaign_id: str) -> set[str]:
        return {
            str(row["id"])
            for row in conn.execute(
                """SELECT candidate.id
                   FROM control_pr_candidates candidate
                   WHERE candidate.campaign_id = ? AND candidate.status = 'ready'
                     AND NOT EXISTS (
                         SELECT 1 FROM control_work_orders work_order
                         WHERE work_order.candidate_id = candidate.id
                     )
                     AND NOT EXISTS (
                         SELECT 1 FROM control_agent_tasks task
                         WHERE task.candidate_id = candidate.id
                     )""",
                (campaign_id,),
            ).fetchall()
        }

    @staticmethod
    def _relation_key(relation: Dict[str, Any]) -> tuple[str, ...]:
        return (
            str(relation.get("source_kind") or ""),
            str(relation.get("source_id") or ""),
            str(relation.get("target_kind") or ""),
            str(relation.get("target_id") or ""),
            str(relation.get("relation_type") or ""),
        )

    def _remove_knowledge_link_in_connection(
        self,
        conn,
        payload: Dict[str, Any],
        *,
        actor: str,
        invalidate_plan: bool,
    ) -> Dict[str, Any]:
        """Validated inverse of KnowledgeMixin's internal record seam."""
        source_kind = str(payload.get("source_kind") or "").strip().lower()
        target_kind = str(payload.get("target_kind") or "").strip().lower()
        source_id = clean_text(payload.get("source_id"), "source_id", maximum=120)
        target_id = clean_text(payload.get("target_id"), "target_id", maximum=120)
        relation_type = clean_text(
            payload.get("relation_type"), "relation_type", maximum=80
        ).lower()
        pair = (source_kind, target_kind)
        table_shape = {
            ("idea_seed", "artifact"): (
                "control_idea_seed_artifacts", "idea_seed_id", "artifact_id"
            ),
            ("artifact", "artifact"): (
                "control_artifact_relations", "source_artifact_id", "target_artifact_id"
            ),
            ("candidate", "artifact"): (
                "control_candidate_artifacts", "candidate_id", "artifact_id"
            ),
        }.get(pair)
        if table_shape is None:
            raise ControlCenterError(
                "Diese Knowledge-Link-Richtung ist nicht erlaubt.",
                code="invalid_knowledge_link_direction",
            )
        source = self._knowledge_entity(conn, source_kind, source_id)
        target = self._knowledge_entity(conn, target_kind, target_id)
        if int(source["project_id"]) != int(target["project_id"]):
            raise ControlCenterError(
                "Knowledge-Links dürfen keine Projektgrenzen überschreiten.",
                code="knowledge_project_mismatch",
                status=409,
            )
        source_campaign = str(source["campaign_id"] or "")
        target_campaign = str(target["campaign_id"] or "")
        if pair in {("artifact", "artifact"), ("candidate", "artifact")} and (
            source_campaign != target_campaign
        ):
            raise ControlCenterError(
                "Knowledge-Link gehört nicht zu einer gemeinsamen Campaign.",
                code="knowledge_campaign_mismatch",
                status=409,
            )
        campaign_id = target_campaign or source_campaign
        if campaign_id and str(self._campaign(conn, campaign_id)["status"]) != "draft":
            raise ControlCenterError(
                "Ein genehmigter Plan benötigt ein Amendment.",
                code="campaign_locked",
                status=409,
            )
        table, source_column, target_column = table_shape
        deleted = conn.execute(
            f"""DELETE FROM {table}
                WHERE {source_column} = ? AND {target_column} = ?
                  AND relation_type = ?""",
            (source_id, target_id, relation_type),
        )
        if deleted.rowcount and invalidate_plan and campaign_id:
            self._invalidate_draft_plan_in_connection(conn, campaign_id)
        return {
            "relation": {
                "source_kind": source_kind,
                "source_id": source_id,
                "target_kind": target_kind,
                "target_id": target_id,
                "relation_type": relation_type,
            },
            "removed": bool(deleted.rowcount),
            "actor": actor,
        }

    @staticmethod
    def _validate_hash(value: Any, field: str) -> str:
        digest = str(value or "").strip().lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ControlCenterError(
                f"{field} ist erforderlich.",
                code=f"{field}_required",
            )
        return digest

    def start_plan_amendment(
        self,
        campaign_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        reason = clean_text(payload.get("reason"), "reason", minimum=10, maximum=10000)
        focus = payload.get("focus") or {}
        if not isinstance(focus, dict) or not focus:
            raise ControlCenterError(
                "focus muss ein nichtleeres Objekt sein.",
                code="invalid_amendment_focus",
            )
        actor = clean_text(payload.get("actor") or "human", "actor", maximum=120)
        try:
            expected_version = int(payload.get("expected_version"))
            expected_signature_version = int(
                payload.get("expected_plan_signature_version")
            )
        except (TypeError, ValueError) as exc:
            raise ControlCenterError(
                "Planversion und Signaturversion sind erforderlich.",
                code="amendment_identity_required",
            ) from exc
        expected_base_sha = str(payload.get("expected_base_sha") or "").strip().lower()
        expected_signature = self._validate_hash(
            payload.get("expected_plan_signature"),
            "plan_signature",
        )
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            campaign = self._campaign(conn, campaign_id)
            if str(campaign["status"]) not in {"approved", "active", "paused"}:
                raise ControlCenterError(
                    "Nur ein freigegebener, aktiver oder pausierter Plan kann neu geplant werden.",
                    code="campaign_not_amendable",
                    status=409,
                )
            if int(campaign["version"]) != expected_version:
                raise ControlCenterError(
                    "Die Planversion hat sich geändert.",
                    code="stale_plan_version",
                    status=409,
                )
            if str(campaign["base_sha"] or "").lower() != expected_base_sha:
                raise ControlCenterError(
                    "Die Campaign-Baseline hat sich geändert.",
                    code="stale_base_sha",
                    status=409,
                )
            if expected_signature_version != PLAN_SIGNATURE_VERSION:
                raise ControlCenterError(
                    "Die angezeigte Plan-Signaturversion ist veraltet.",
                    code="stale_plan_signature_version",
                    status=409,
                )
            readiness = self._evaluate_campaign_readiness_in_connection(
                conn,
                campaign_id,
                persist=False,
            )
            if readiness["plan_signature"] != expected_signature:
                raise ControlCenterError(
                    "Der Quellplan hat eine andere Signatur.",
                    code="stale_plan_signature",
                    status=409,
                )
            open_row = conn.execute(
                """SELECT id FROM control_plan_amendments
                   WHERE campaign_id = ?
                     AND status IN ('planning', 'review', 'failed', 'proposed')
                   LIMIT 1""",
                (campaign_id,),
            ).fetchone()
            if open_row:
                raise ControlCenterError(
                    "Für diese Campaign ist bereits eine Planänderung offen.",
                    code="amendment_already_open",
                    status=409,
                )
            active_job = conn.execute(
                """SELECT id FROM control_planning_jobs
                   WHERE project_id = ? AND status IN ('queued', 'running')
                   LIMIT 1""",
                (int(campaign["project_id"]),),
            ).fetchone()
            if active_job:
                raise ControlCenterError(
                    "Für dieses Repository läuft bereits ein Planning-Job.",
                    code="planning_job_already_active",
                    status=409,
                )
            project = self._project(campaign["project_id"])
            policy = self._repository_policy_in_connection(
                conn,
                int(campaign["project_id"]),
            )
            self._require_repository_read_capability(policy)
            planning_base_sha = self._resolve_sha(project, require=True)
            before_plan = self._plan_snapshot_in_connection(conn, campaign_id)
            before_hash = self._plan_snapshot_sha256(before_plan)
            profile = conn.execute(
                """SELECT planning_depth, requested_max_candidates,
                          activation_policy, constraints_json
                   FROM control_campaign_profiles WHERE campaign_id = ?""",
                (campaign_id,),
            ).fetchone()
            amendment_id = public_id("AMD")
            job_id = public_id("PLAN")
            conn.execute(
                """INSERT INTO control_plan_amendments (
                       id, campaign_id, from_version, proposed_version,
                       reason, impact_json, focus_json, status, proposed_by,
                       prior_campaign_status, from_base_sha, planning_base_sha,
                       from_plan_signature, from_signature_version,
                       before_plan_json, before_plan_sha256
                   ) VALUES (?, ?, ?, ?, ?, '{}', ?, 'planning', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    amendment_id,
                    campaign_id,
                    int(campaign["version"]),
                    int(campaign["version"]) + 1,
                    reason,
                    json.dumps(focus, ensure_ascii=False),
                    actor,
                    str(campaign["status"]),
                    expected_base_sha,
                    planning_base_sha,
                    expected_signature,
                    PLAN_SIGNATURE_VERSION,
                    json.dumps(before_plan, ensure_ascii=False),
                    before_hash,
                ),
            )
            conn.execute(
                """INSERT INTO control_planning_jobs (
                       id, project_id, idea_seed_id, job_type, amendment_id,
                       planning_depth, max_candidates, activation_policy,
                       wish, constraints_json, campaign_id, created_by
                   ) VALUES (?, ?, NULL, 'plan_amendment', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job_id,
                    int(campaign["project_id"]),
                    amendment_id,
                    str(profile["planning_depth"]),
                    int(profile["requested_max_candidates"]),
                    str(profile["activation_policy"]),
                    reason,
                    str(profile["constraints_json"] or "[]"),
                    campaign_id,
                    actor,
                ),
            )
            conn.execute(
                """UPDATE control_plan_amendments
                   SET planning_job_id = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (job_id, amendment_id),
            )
            conn.execute(
                """UPDATE control_campaigns
                   SET status = 'paused', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (campaign_id,),
            )
            self._attention(
                conn,
                project_id=int(campaign["project_id"]),
                category="plan_amendment",
                entity_type="campaign",
                entity_id=campaign_id,
                title=f"Planänderung für „{campaign['title']}“ wird vorbereitet",
                consequence="Die Campaign bleibt bis zur exakten Entscheidung pausiert.",
                recommendation="Rückfragen beantworten und danach Zielplan sowie Patch prüfen.",
                urgency="high",
            )
            self._audit(
                conn,
                project_id=int(campaign["project_id"]),
                entity_type="campaign",
                entity_id=campaign_id,
                action="plan_amendment.started",
                actor=actor,
                from_state=str(campaign["status"]),
                to_state="paused",
                reason=reason,
                evidence={
                    "amendment_id": amendment_id,
                    "planning_job_id": job_id,
                    "from_version": int(campaign["version"]),
                    "from_base_sha": expected_base_sha,
                    "planning_base_sha": planning_base_sha,
                    "from_plan_signature": expected_signature,
                    "from_signature_version": PLAN_SIGNATURE_VERSION,
                    "before_plan_sha256": before_hash,
                },
            )
            conn.commit()
        return {
            "amendment": self.get_plan_amendment(amendment_id),
            "planning_job": self.get_planning_job(job_id),
        }

    def propose_plan_amendment(
        self,
        campaign_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Compatibility delegate; every persisted row still binds exact identities."""
        with self.db._get_connection() as conn:
            campaign = self._campaign(conn, campaign_id)
            readiness = self._evaluate_campaign_readiness_in_connection(
                conn,
                campaign_id,
                persist=False,
            )
        impact = payload.get("impact") or {}
        focus = impact if isinstance(impact, dict) and impact else {
            "branches": ["scope"],
            "requested_change": str(payload.get("reason") or ""),
        }
        result = self.start_plan_amendment(
            campaign_id,
            {
                "reason": payload.get("reason"),
                "focus": focus,
                "expected_version": campaign["version"],
                "expected_base_sha": campaign["base_sha"],
                "expected_plan_signature": readiness["plan_signature"],
                "expected_plan_signature_version": readiness[
                    "plan_signature_version"
                ],
                "actor": payload.get("actor") or "agent",
            },
        )
        return result["amendment"]

    def _normalize_profile(self, value: Any, *, title: str) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise ControlCenterError(
                "target_plan.profile muss ein Objekt sein.",
                code="invalid_amendment_target",
            )
        depth = str(value.get("planning_depth") or "").strip().lower()
        if depth not in PLANNING_DEPTHS:
            raise ControlCenterError("Unbekannter Planungsgrad.", code="invalid_planning_depth")
        activation = str(value.get("activation_policy") or "").strip()
        if activation not in ACTIVATION_POLICIES:
            raise ControlCenterError(
                "Unbekannte Aktivierungs-Policy.",
                code="invalid_activation_policy",
            )
        alternatives = value.get("alternatives")
        if not isinstance(alternatives, list):
            raise ControlCenterError(
                "alternatives muss eine Liste sein.",
                code="invalid_alternatives",
            )
        normalized_alternatives = []
        for item in alternatives:
            if not isinstance(item, dict):
                raise ControlCenterError(
                    "Alternativen müssen Objekte sein.",
                    code="invalid_alternative",
                )
            normalized_alternatives.append(
                {
                    "title": clean_text(item.get("title"), "alternative_title", minimum=3, maximum=200),
                    "mechanism": clean_text(item.get("mechanism"), "alternative_mechanism", minimum=10, maximum=5000),
                    "tradeoffs": clean_text(item.get("tradeoffs"), "alternative_tradeoffs", minimum=10, maximum=5000),
                }
            )
        try:
            maximum = int(value.get("requested_max_candidates"))
            estimated_cost = float(value.get("estimated_cost") or 0)
        except (TypeError, ValueError) as exc:
            raise ControlCenterError(
                "Planprofil enthält ungültige Zahlenwerte.",
                code="invalid_amendment_target",
            ) from exc
        return {
            "slug": slugify(value.get("slug") or title),
            "planning_depth": depth,
            "requested_max_candidates": maximum,
            "activation_policy": activation,
            "pivotal_fork": str(value.get("pivotal_fork") or "")[:10000],
            "pivotal_fork_na_reason": str(value.get("pivotal_fork_na_reason") or "")[:10000],
            "success_metrics": _text_list(value.get("success_metrics"), "success_metrics", required=True),
            "constraints": _text_list(value.get("constraints"), "constraints"),
            "assumptions": _text_list(value.get("assumptions"), "assumptions"),
            "acceptance_matrix": _text_list(value.get("acceptance_matrix"), "acceptance_matrix"),
            "alternatives": normalized_alternatives,
            "review_strategy": str(value.get("review_strategy") or "")[:10000],
            "rollout_plan": str(value.get("rollout_plan") or "")[:10000],
            "rollback_plan": str(value.get("rollback_plan") or "")[:10000],
            "repository_map_artifact_id": value.get("repository_map_artifact_id"),
            "design_artifact_id": value.get("design_artifact_id"),
            "plan_simulation_artifact_id": value.get("plan_simulation_artifact_id"),
            "estimated_cost": estimated_cost,
        }

    def _normalize_candidate(
        self,
        value: Any,
        *,
        candidate_id: str,
        base_sha: str,
        is_new: bool,
    ) -> Dict[str, Any]:
        if not isinstance(value, dict) or not isinstance(value.get("contract"), dict):
            raise ControlCenterError(
                "Jeder Zielkandidat benötigt einen vollständigen Contract.",
                code="invalid_amendment_candidate",
            )
        contract = copy.deepcopy(value["contract"])
        for field in CONTRACT_LIST_FIELDS:
            contract[field] = _text_list(contract.get(field), field, required=True)
        for field in (
            "purpose", "expected_diff_type", "reversibility", "migration_plan",
            "compatibility_plan", "definition_of_done",
        ):
            contract[field] = clean_text(contract.get(field), field, maximum=10000)
        criteria = validate_acceptance_criteria(value.get("acceptance_criteria"))
        try:
            priority = int(value.get("priority"))
        except (TypeError, ValueError) as exc:
            raise ControlCenterError(
                "Kandidatenpriorität ist ungültig.",
                code="invalid_priority",
            ) from exc
        status = str(value.get("status") or "ready").strip().lower()
        if is_new:
            status = "ready"
        elif status not in {"ready", "obsolete"}:
            raise ControlCenterError(
                "Nur zukünftige Kandidaten dürfen ready oder obsolete sein.",
                code="invalid_amendment_candidate_status",
            )
        return {
            "id": candidate_id,
            "title": clean_text(value.get("title"), "candidate_title", minimum=3, maximum=200),
            "scope": clean_text(value.get("scope"), "candidate_scope", minimum=10, maximum=10000),
            "acceptance_criteria": criteria,
            "non_goals": clean_text(value.get("non_goals"), "non_goals", maximum=5000),
            "risk_level": self._risk(value.get("risk_level")),
            "priority": priority,
            "status": status,
            "base_sha": base_sha,
            "contract": contract,
        }

    def _normalize_target_plan(
        self,
        conn,
        amendment: Dict[str, Any],
        value: Any,
    ) -> tuple[Dict[str, Any], set[str], set[str]]:
        if not isinstance(value, dict):
            raise ControlCenterError(
                "amendment_plan.target_plan muss ein vollständiges Objekt sein.",
                code="invalid_amendment_target",
            )
        encoded = json.dumps(value, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > 2_000_000:
            raise ControlCenterError(
                "Der Zielplan ist zu groß.",
                code="amendment_target_too_large",
            )
        required_sections = {
            "signature_version", "campaign", "profile", "ledger", "artifacts",
            "candidates", "dependencies", "conflicts", "knowledge_relations",
        }
        if set(value) != required_sections:
            raise ControlCenterError(
                "target_plan muss den vollständigen kanonischen Plan enthalten.",
                code="incomplete_amendment_target",
            )
        if int(value.get("signature_version") or 0) != PLAN_SIGNATURE_VERSION:
            raise ControlCenterError(
                "Der Zielplan verwendet nicht die aktuelle Signatursemantik.",
                code="stale_plan_signature_version",
                status=409,
            )
        campaign_value = value.get("campaign")
        if not isinstance(campaign_value, dict) or str(campaign_value.get("id")) != str(
            amendment["campaign_id"]
        ):
            raise ControlCenterError(
                "Der Zielplan gehört nicht zur Amendment-Campaign.",
                code="amendment_campaign_mismatch",
                status=409,
            )
        campaign = {
            "id": str(amendment["campaign_id"]),
            "title": clean_text(campaign_value.get("title"), "title", minimum=3, maximum=200),
            "goal": clean_text(campaign_value.get("goal"), "goal", minimum=10, maximum=10000),
            "non_goals": clean_text(campaign_value.get("non_goals"), "non_goals", minimum=3, maximum=5000),
            "risk_level": self._risk(campaign_value.get("risk_level")),
            "version": int(amendment["proposed_version"]),
            "base_sha": str(amendment["planning_base_sha"]),
            "approved_version": None,
            "approved_sha": "",
            "approved_by": "",
        }

        before = amendment["before_plan"]
        before_candidates = {
            str(item["id"]): item for item in before["candidates"]
        }
        mutable_ids = self._mutable_candidate_ids(
            conn,
            str(amendment["campaign_id"]),
        )
        immutable_ids = set(before_candidates) - mutable_ids
        raw_candidates = value.get("candidates")
        if not isinstance(raw_candidates, list):
            raise ControlCenterError(
                "target_plan.candidates muss eine Liste sein.",
                code="invalid_amendment_target",
            )
        candidate_id_map: Dict[str, str] = {}
        normalized_candidates: list[Dict[str, Any]] = []
        seen_client_ids: set[str] = set()
        for index, raw in enumerate(raw_candidates, start=1):
            if not isinstance(raw, dict):
                raise ControlCenterError(
                    "Zielkandidaten müssen Objekte sein.",
                    code="invalid_amendment_candidate",
                )
            client_id = str(raw.get("id") or f"new-candidate-{index}").strip()
            if not client_id or client_id in seen_client_ids:
                raise ControlCenterError(
                    "Zielkandidaten-IDs sind nicht eindeutig.",
                    code="duplicate_amendment_candidate_id",
                )
            seen_client_ids.add(client_id)
            is_new = client_id not in before_candidates
            candidate_id = (
                self._deterministic_amendment_id(
                    "PRC", amendment["id"], "candidate", client_id, index
                )
                if is_new
                else client_id
            )
            candidate_id_map[client_id] = candidate_id
            source_base = (
                str(before_candidates[client_id]["base_sha"])
                if client_id in immutable_ids
                else str(amendment["planning_base_sha"])
            )
            normalized = self._normalize_candidate(
                raw,
                candidate_id=candidate_id,
                base_sha=source_base,
                is_new=is_new,
            )
            if client_id in immutable_ids and normalized != before_candidates[client_id]:
                raise ControlCenterError(
                    f"Der bereits gestartete Kandidat {client_id} wurde verändert.",
                    code="immutable_candidate_changed",
                    status=409,
                )
            normalized_candidates.append(normalized)
        included_existing_ids = set(candidate_id_map) & set(before_candidates)
        missing_immutable = immutable_ids - included_existing_ids
        if missing_immutable:
            raise ControlCenterError(
                "Unveränderliche Kandidaten fehlen im vollständigen Zielplan.",
                code="immutable_candidate_changed",
                status=409,
            )
        for candidate_id in sorted(mutable_ids - included_existing_ids):
            retired = copy.deepcopy(before_candidates[candidate_id])
            retired["status"] = "obsolete"
            retired["base_sha"] = str(amendment["planning_base_sha"])
            normalized_candidates.append(retired)
            candidate_id_map[candidate_id] = candidate_id
        normalized_candidates.sort(key=lambda item: str(item["id"]))

        raw_artifacts = value.get("artifacts")
        if not isinstance(raw_artifacts, list):
            raise ControlCenterError(
                "target_plan.artifacts muss eine Liste sein.",
                code="invalid_amendment_target",
            )
        before_artifacts = {str(item["id"]): item for item in before["artifacts"]}
        artifact_id_map: Dict[str, str] = {}
        normalized_artifacts: list[Dict[str, Any]] = []
        seen_artifact_clients: set[str] = set()
        assigned_versions: Dict[tuple[str, str], int] = {}
        for index, raw in enumerate(raw_artifacts, start=1):
            if not isinstance(raw, dict):
                raise ControlCenterError(
                    "Zielartefakte müssen Objekte sein.",
                    code="invalid_amendment_artifact",
                )
            client_id = str(raw.get("id") or f"new-artifact-{index}").strip()
            if not client_id or client_id in seen_artifact_clients:
                raise ControlCenterError(
                    "Zielartefakt-IDs sind nicht eindeutig.",
                    code="duplicate_amendment_artifact_id",
                )
            seen_artifact_clients.add(client_id)
            if client_id in before_artifacts:
                if raw != before_artifacts[client_id]:
                    raise ControlCenterError(
                        "Bestehende Artefakte dürfen nicht in-place überschrieben werden.",
                        code="approved_artifact_immutable",
                        status=409,
                    )
                artifact_id_map[client_id] = client_id
                normalized_artifacts.append(copy.deepcopy(before_artifacts[client_id]))
                continue
            artifact_id = self._deterministic_amendment_id(
                "DOC", amendment["id"], "artifact", client_id, index
            )
            artifact_id_map[client_id] = artifact_id
            artifact_type = clean_text(
                raw.get("artifact_type"), "artifact_type", maximum=80
            )
            artifact_slug = slugify(raw.get("slug") or raw.get("title"))
            key = (artifact_type, artifact_slug)
            if key not in assigned_versions:
                latest = conn.execute(
                    """SELECT MAX(version) AS version FROM control_artifacts
                       WHERE project_id = ? AND artifact_type = ? AND slug = ?""",
                    (
                        int(self._campaign(conn, amendment["campaign_id"])["project_id"]),
                        artifact_type,
                        artifact_slug,
                    ),
                ).fetchone()
                assigned_versions[key] = int(latest["version"] or 0)
            assigned_versions[key] += 1
            relative_path = PurePosixPath(
                str(raw.get("relative_path") or "")
            ).as_posix()
            if relative_path and (
                PurePosixPath(relative_path).is_absolute()
                or ".." in PurePosixPath(relative_path).parts
            ):
                raise ControlCenterError(
                    "Ungültiger geplanter Artefaktpfad.",
                    code="artifact_path_escape",
                )
            content = str(raw.get("content") or "")
            metadata = raw.get("metadata") or {}
            if not isinstance(metadata, dict):
                raise ControlCenterError(
                    "Artefakt-Metadaten müssen ein Objekt sein.",
                    code="invalid_artifact_metadata",
                )
            supersedes = raw.get("supersedes_id")
            if supersedes not in (None, ""):
                supersedes = artifact_id_map.get(str(supersedes), str(supersedes))
                if supersedes not in before_artifacts:
                    raise ControlCenterError(
                        "Ein neues Artefakt darf nur ein bestehendes Artefakt superseden.",
                        code="invalid_supersedes_artifact",
                    )
            normalized_artifacts.append(
                {
                    "id": artifact_id,
                    "artifact_type": artifact_type,
                    "slug": artifact_slug,
                    "title": clean_text(raw.get("title"), "artifact_title", minimum=3, maximum=300),
                    "status": str(raw.get("status") or "proposed")[:40],
                    "version": assigned_versions[key],
                    "supersedes_id": supersedes or None,
                    "relative_path": relative_path,
                    "content": content,
                    "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    "metadata": copy.deepcopy(metadata),
                }
            )
        if set(before_artifacts) - seen_artifact_clients:
            raise ControlCenterError(
                "Bestehende Artefakte fehlen im vollständigen Zielplan.",
                code="approved_artifact_immutable",
                status=409,
            )
        normalized_artifacts.sort(key=lambda item: str(item["id"]))

        profile = self._normalize_profile(
            value.get("profile"),
            title=campaign["title"],
        )
        for pointer in (
            "repository_map_artifact_id",
            "design_artifact_id",
            "plan_simulation_artifact_id",
        ):
            if profile[pointer] not in (None, ""):
                profile[pointer] = artifact_id_map.get(
                    str(profile[pointer]), str(profile[pointer])
                )

        raw_ledger = value.get("ledger")
        if not isinstance(raw_ledger, list):
            raise ControlCenterError(
                "target_plan.ledger muss eine Liste sein.",
                code="invalid_amendment_target",
            )
        before_ledger = {str(item["id"]): item for item in before["ledger"]}
        normalized_ledger: list[Dict[str, Any]] = []
        seen_ledger_ids: set[str] = set()
        for index, raw in enumerate(raw_ledger, start=1):
            if not isinstance(raw, dict):
                raise ControlCenterError(
                    "Ledger-Einträge müssen Objekte sein.",
                    code="invalid_amendment_ledger",
                )
            client_id = str(raw.get("id") or f"new-ledger-{index}")
            if client_id in seen_ledger_ids:
                raise ControlCenterError(
                    "Ledger-IDs sind nicht eindeutig.",
                    code="duplicate_amendment_ledger_id",
                )
            seen_ledger_ids.add(client_id)
            if client_id in before_ledger:
                if raw != before_ledger[client_id]:
                    raise ControlCenterError(
                        "Bestehende Planentscheidungen dürfen nicht überschrieben werden.",
                        code="approved_ledger_immutable",
                        status=409,
                    )
                normalized_ledger.append(copy.deepcopy(before_ledger[client_id]))
                continue
            question = clean_text(raw.get("question"), "question", minimum=5, maximum=5000)
            branch = clean_text(raw.get("branch"), "branch", maximum=120).lower()
            normalized_question = " ".join(question.casefold().split())
            normalized_ledger.append(
                {
                    "id": self._deterministic_amendment_id(
                        "Q", amendment["id"], "ledger", client_id, index
                    ),
                    "branch": branch,
                    "planning_job_id": None,
                    "content_hash": hashlib.sha256(
                        f"{branch}:{normalized_question}".encode("utf-8")
                    ).hexdigest(),
                    "question": question,
                    "rationale": str(raw.get("rationale") or "")[:5000],
                    "answer": str(raw.get("answer") or "")[:20000],
                    "answer_source": str(raw.get("answer_source") or "planner")[:120],
                    "status": str(raw.get("status") or "resolved")[:40],
                    "owner": str(raw.get("owner") or "")[:120],
                    "evidence": copy.deepcopy(raw.get("evidence") or {}),
                    "contradiction_of": raw.get("contradiction_of"),
                    "resolved_in_version": int(amendment["proposed_version"]),
                }
            )
        if set(before_ledger) - seen_ledger_ids:
            raise ControlCenterError(
                "Bestehende Planentscheidungen fehlen im vollständigen Zielplan.",
                code="approved_ledger_immutable",
                status=409,
            )
        normalized_ledger.sort(key=lambda item: str(item["id"]))

        valid_candidate_ids = {item["id"] for item in normalized_candidates}
        dependencies = []
        seen_dependencies: set[tuple[str, str]] = set()
        raw_dependencies = value.get("dependencies")
        if not isinstance(raw_dependencies, list):
            raise ControlCenterError(
                "target_plan.dependencies muss eine Liste sein.",
                code="invalid_dependencies",
            )
        for raw in raw_dependencies:
            if not isinstance(raw, dict):
                raise ControlCenterError("Dependency muss ein Objekt sein.", code="invalid_dependency")
            first = candidate_id_map.get(str(raw.get("candidate_id")), str(raw.get("candidate_id") or ""))
            second = candidate_id_map.get(str(raw.get("depends_on_id")), str(raw.get("depends_on_id") or ""))
            if first not in valid_candidate_ids or second not in valid_candidate_ids or first == second:
                raise ControlCenterError("Dependency verweist auf einen ungültigen Slice.", code="invalid_dependency")
            key = (first, second)
            if key not in seen_dependencies:
                seen_dependencies.add(key)
                dependencies.append({"candidate_id": first, "depends_on_id": second})
        dependencies.sort(key=lambda item: (item["candidate_id"], item["depends_on_id"]))

        conflicts = []
        seen_conflicts: set[tuple[str, str]] = set()
        raw_conflicts = value.get("conflicts")
        if not isinstance(raw_conflicts, list):
            raise ControlCenterError(
                "target_plan.conflicts muss eine Liste sein.",
                code="invalid_conflicts",
            )
        for raw in raw_conflicts:
            if not isinstance(raw, dict):
                raise ControlCenterError("Konflikt muss ein Objekt sein.", code="invalid_conflicts")
            first = candidate_id_map.get(str(raw.get("candidate_id")), str(raw.get("candidate_id") or ""))
            second = candidate_id_map.get(str(raw.get("conflicts_with_id")), str(raw.get("conflicts_with_id") or ""))
            if first not in valid_candidate_ids or second not in valid_candidate_ids or first == second:
                raise ControlCenterError("Konflikt verweist auf einen ungültigen Slice.", code="invalid_conflicts")
            first, second = sorted((first, second))
            key = (first, second)
            if key in seen_conflicts:
                continue
            seen_conflicts.add(key)
            resources = _text_list(raw.get("resources") or [], "resources")
            conflicts.append(
                {
                    "candidate_id": first,
                    "conflicts_with_id": second,
                    "reason": clean_text(raw.get("reason"), "conflict_reason", maximum=2000),
                    "resources": resources,
                }
            )
        conflicts.sort(key=lambda item: (item["candidate_id"], item["conflicts_with_id"]))

        raw_knowledge = value.get("knowledge_relations")
        if not isinstance(raw_knowledge, dict) or set(raw_knowledge) != {
            "idea_seed_artifacts", "artifact_relations", "candidate_artifacts"
        }:
            raise ControlCenterError(
                "target_plan.knowledge_relations ist unvollständig.",
                code="invalid_amendment_knowledge",
            )
        knowledge = {key: [] for key in raw_knowledge}
        for key, relations in raw_knowledge.items():
            if not isinstance(relations, list):
                raise ControlCenterError(
                    "Knowledge-Relationen müssen Listen sein.",
                    code="invalid_amendment_knowledge",
                )
            seen: set[tuple[str, ...]] = set()
            for raw in relations:
                if not isinstance(raw, dict):
                    raise ControlCenterError("Knowledge-Link muss ein Objekt sein.", code="invalid_knowledge_link")
                source_kind = str(raw.get("source_kind") or "").strip().lower()
                target_kind = str(raw.get("target_kind") or "").strip().lower()
                source_id = str(raw.get("source_id") or "").strip()
                target_id = str(raw.get("target_id") or "").strip()
                if source_kind == "candidate":
                    source_id = candidate_id_map.get(source_id, source_id)
                elif source_kind == "artifact":
                    source_id = artifact_id_map.get(source_id, source_id)
                if target_kind == "artifact":
                    target_id = artifact_id_map.get(target_id, target_id)
                relation = {
                    "source_kind": source_kind,
                    "source_id": source_id,
                    "target_kind": target_kind,
                    "target_id": target_id,
                    "relation_type": str(raw.get("relation_type") or "").strip().lower(),
                }
                relation_key = self._relation_key(relation)
                if relation_key not in seen:
                    seen.add(relation_key)
                    knowledge[key].append(relation)
            knowledge[key].sort(key=self._relation_key)

        before_dependency_keys = {
            (item["candidate_id"], item["depends_on_id"])
            for item in before["dependencies"]
            if item["candidate_id"] in immutable_ids or item["depends_on_id"] in immutable_ids
        }
        target_dependency_keys = {
            (item["candidate_id"], item["depends_on_id"])
            for item in dependencies
            if item["candidate_id"] in immutable_ids or item["depends_on_id"] in immutable_ids
        }
        before_conflict_keys = {
            (item["candidate_id"], item["conflicts_with_id"], item["reason"], tuple(item["resources"]))
            for item in before["conflicts"]
            if item["candidate_id"] in immutable_ids or item["conflicts_with_id"] in immutable_ids
        }
        target_conflict_keys = {
            (item["candidate_id"], item["conflicts_with_id"], item["reason"], tuple(item["resources"]))
            for item in conflicts
            if item["candidate_id"] in immutable_ids or item["conflicts_with_id"] in immutable_ids
        }
        before_immutable_links = {
            self._relation_key(item)
            for item in before["knowledge_relations"]["candidate_artifacts"]
            if item["source_id"] in immutable_ids
        }
        target_immutable_links = {
            self._relation_key(item)
            for item in knowledge["candidate_artifacts"]
            if item["source_id"] in immutable_ids
        }
        if (
            before_dependency_keys != target_dependency_keys
            or before_conflict_keys != target_conflict_keys
            or before_immutable_links != target_immutable_links
        ):
            raise ControlCenterError(
                "Relationen bereits gestarteter Kandidaten dürfen nicht verändert werden.",
                code="immutable_candidate_relations_changed",
                status=409,
            )
        if len(normalized_candidates) > int(profile["requested_max_candidates"]):
            raise ControlCenterError(
                "Der Zielplan überschreitet das Kandidatenlimit.",
                code="generated_candidate_limit_exceeded",
            )
        return (
            {
                "signature_version": PLAN_SIGNATURE_VERSION,
                "campaign": campaign,
                "profile": profile,
                "ledger": normalized_ledger,
                "artifacts": normalized_artifacts,
                "candidates": normalized_candidates,
                "dependencies": dependencies,
                "conflicts": conflicts,
                "knowledge_relations": knowledge,
            },
            mutable_ids,
            immutable_ids,
        )

    @staticmethod
    def _patch_between(before: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, Any]:
        patch: Dict[str, Any] = {}
        for section in ("campaign", "profile"):
            changed = {
                key: value
                for key, value in target[section].items()
                if before[section].get(key) != value
            }
            if changed:
                patch[section] = {"set": changed}
        before_ledger = {item["id"]: item for item in before["ledger"]}
        ledger_add = [item for item in target["ledger"] if item["id"] not in before_ledger]
        if ledger_add:
            patch["ledger"] = {"add": ledger_add}
        before_artifacts = {item["id"]: item for item in before["artifacts"]}
        artifact_add = []
        artifact_supersede = []
        for item in target["artifacts"]:
            if item["id"] in before_artifacts:
                continue
            summary = {
                "id": item["id"],
                "title": item["title"],
                "artifact_type": item["artifact_type"],
            }
            if item.get("supersedes_id"):
                artifact_supersede.append(
                    {**summary, "supersedes_artifact_id": item["supersedes_id"]}
                )
            else:
                artifact_add.append(summary)
        if artifact_add or artifact_supersede:
            patch["artifacts"] = {
                "add": artifact_add,
                "supersede": artifact_supersede,
            }
        before_candidates = {item["id"]: item for item in before["candidates"]}
        candidate_add = []
        candidate_update = []
        candidate_retire = []
        for item in target["candidates"]:
            existing = before_candidates.get(item["id"])
            if existing is None:
                candidate_add.append({"id": item["id"], "title": item["title"]})
                continue
            if item == existing:
                continue
            fields = sorted(
                key for key in item if key != "id" and existing.get(key) != item.get(key)
            )
            summary = {"id": item["id"], "title": item["title"], "fields": fields}
            if item["status"] == "obsolete" and existing["status"] != "obsolete":
                candidate_retire.append(summary)
            else:
                candidate_update.append(summary)
        if candidate_add or candidate_update or candidate_retire:
            patch["candidates"] = {
                "add": candidate_add,
                "update": candidate_update,
                "retire": candidate_retire,
            }
        if before["dependencies"] != target["dependencies"]:
            patch["dependencies"] = {"replace_for_mutable": target["dependencies"]}
        if before["conflicts"] != target["conflicts"]:
            patch["conflicts"] = {"replace_for_mutable": target["conflicts"]}
        before_links = {
            AmendmentPlanningMixin._relation_key(item): item
            for values in before["knowledge_relations"].values()
            for item in values
        }
        target_links = {
            AmendmentPlanningMixin._relation_key(item): item
            for values in target["knowledge_relations"].values()
            for item in values
        }
        link_add = [target_links[key] for key in sorted(set(target_links) - set(before_links))]
        link_remove = [before_links[key] for key in sorted(set(before_links) - set(target_links))]
        if link_add or link_remove:
            patch["knowledge_relations"] = {"add": link_add, "remove": link_remove}
        return patch

    def _apply_target_plan_in_connection(
        self,
        conn,
        amendment: Dict[str, Any],
        target: Dict[str, Any],
        *,
        immutable_ids: set[str],
    ) -> Dict[str, Any]:
        campaign_id = str(amendment["campaign_id"])
        campaign_target = target["campaign"]
        conn.execute(
            """UPDATE control_campaigns
               SET title = ?, goal = ?, non_goals = ?, risk_level = ?,
                   version = ?, base_sha = ?, status = 'draft',
                   approved_version = NULL, approved_sha = '', approved_by = '',
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (
                campaign_target["title"], campaign_target["goal"],
                campaign_target["non_goals"], campaign_target["risk_level"],
                int(campaign_target["version"]), campaign_target["base_sha"], campaign_id,
            ),
        )
        profile = target["profile"]
        conn.execute(
            """UPDATE control_campaign_profiles
               SET slug = ?, planning_depth = ?, requested_max_candidates = ?,
                   activation_policy = ?, pivotal_fork = ?,
                   pivotal_fork_na_reason = ?, success_metrics_json = ?,
                   constraints_json = ?, assumptions_json = ?,
                   acceptance_matrix_json = ?, alternatives_json = ?,
                   review_strategy = ?, rollout_plan = ?, rollback_plan = ?,
                   repository_map_artifact_id = ?, design_artifact_id = ?,
                   plan_simulation_artifact_id = ?, estimated_cost = ?,
                   readiness_status = 'draft', readiness_score = 0,
                   plan_signature = '', updated_at = CURRENT_TIMESTAMP
               WHERE campaign_id = ?""",
            (
                profile["slug"], profile["planning_depth"],
                int(profile["requested_max_candidates"]), profile["activation_policy"],
                profile["pivotal_fork"], profile["pivotal_fork_na_reason"],
                json.dumps(profile["success_metrics"], ensure_ascii=False),
                json.dumps(profile["constraints"], ensure_ascii=False),
                json.dumps(profile["assumptions"], ensure_ascii=False),
                json.dumps(profile["acceptance_matrix"], ensure_ascii=False),
                json.dumps(profile["alternatives"], ensure_ascii=False),
                profile["review_strategy"], profile["rollout_plan"],
                profile["rollback_plan"], profile["repository_map_artifact_id"],
                profile["design_artifact_id"], profile["plan_simulation_artifact_id"],
                float(profile["estimated_cost"]), campaign_id,
            ),
        )
        existing_ledger = {
            str(row["id"])
            for row in conn.execute(
                "SELECT id FROM control_question_ledger WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchall()
        }
        for item in target["ledger"]:
            if item["id"] in existing_ledger:
                continue
            conn.execute(
                """INSERT INTO control_question_ledger (
                       id, campaign_id, planning_job_id, amendment_id,
                       content_hash, branch, question, rationale, answer,
                       answer_source, status, owner, evidence_json,
                       contradiction_of, resolved_in_version
                   ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item["id"], campaign_id, item["planning_job_id"],
                    item["content_hash"], item["branch"], item["question"],
                    item["rationale"], item["answer"], item["answer_source"],
                    item["status"], item["owner"],
                    json.dumps(item["evidence"], ensure_ascii=False),
                    item["contradiction_of"], item["resolved_in_version"],
                ),
            )
        project_id = int(self._campaign(conn, campaign_id)["project_id"])
        existing_artifacts = {
            str(row["id"])
            for row in conn.execute(
                "SELECT id FROM control_artifacts WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchall()
        }
        for item in target["artifacts"]:
            if item["id"] in existing_artifacts:
                continue
            conn.execute(
                """INSERT INTO control_artifacts (
                       id, project_id, campaign_id, artifact_type, slug, title,
                       status, version, supersedes_id, relative_path,
                       content_text, content_sha256, metadata_json,
                       materialization_status
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'not_requested')""",
                (
                    item["id"], project_id, campaign_id, item["artifact_type"],
                    item["slug"], item["title"], item["status"], int(item["version"]),
                    item.get("supersedes_id"), item["relative_path"], item["content"],
                    item["content_sha256"],
                    json.dumps(item["metadata"], ensure_ascii=False),
                ),
            )
        existing_candidates = {
            str(row["id"])
            for row in conn.execute(
                "SELECT id FROM control_pr_candidates WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchall()
        }
        for item in target["candidates"]:
            candidate_id = str(item["id"])
            if candidate_id in immutable_ids:
                continue
            if candidate_id in existing_candidates:
                conn.execute(
                    """UPDATE control_pr_candidates
                       SET title = ?, scope = ?, acceptance_criteria_json = ?,
                           non_goals = ?, risk_level = ?, priority = ?, status = ?,
                           base_sha = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (
                        item["title"], item["scope"],
                        json.dumps(item["acceptance_criteria"], ensure_ascii=False),
                        item["non_goals"], item["risk_level"], int(item["priority"]),
                        item["status"], item["base_sha"], candidate_id,
                    ),
                )
                conn.execute(
                    "DELETE FROM control_candidate_contracts WHERE candidate_id = ?",
                    (candidate_id,),
                )
            else:
                conn.execute(
                    """INSERT INTO control_pr_candidates (
                           id, campaign_id, title, scope, acceptance_criteria_json,
                           non_goals, risk_level, priority, status, base_sha
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        candidate_id, campaign_id, item["title"], item["scope"],
                        json.dumps(item["acceptance_criteria"], ensure_ascii=False),
                        item["non_goals"], item["risk_level"], int(item["priority"]),
                        item["status"], item["base_sha"],
                    ),
                )
            contract_payload = {**item["contract"], "non_goals": item["non_goals"]}
            self._write_candidate_contract(
                conn,
                candidate_id,
                contract_payload,
                item["acceptance_criteria"],
                strict=True,
            )
            conn.execute(
                """UPDATE control_candidate_contracts
                   SET pinned = ?, paused = ?, override_reason = ?
                   WHERE candidate_id = ?""",
                (
                    1 if item["contract"].get("pinned") else 0,
                    1 if item["contract"].get("paused") else 0,
                    str(item["contract"].get("override_reason") or "")[:5000],
                    candidate_id,
                ),
            )
        for row in conn.execute(
            """SELECT dependency.candidate_id, dependency.depends_on_id
               FROM control_pr_dependencies dependency
               JOIN control_pr_candidates candidate
                 ON candidate.id = dependency.candidate_id
               WHERE candidate.campaign_id = ?""",
            (campaign_id,),
        ).fetchall():
            if row["candidate_id"] not in immutable_ids and row["depends_on_id"] not in immutable_ids:
                conn.execute(
                    "DELETE FROM control_pr_dependencies WHERE candidate_id = ? AND depends_on_id = ?",
                    (row["candidate_id"], row["depends_on_id"]),
                )
        for item in target["dependencies"]:
            conn.execute(
                "INSERT OR IGNORE INTO control_pr_dependencies (candidate_id, depends_on_id) VALUES (?, ?)",
                (item["candidate_id"], item["depends_on_id"]),
            )
        for row in conn.execute(
            """SELECT conflict.candidate_id, conflict.conflicts_with_id
               FROM control_candidate_conflicts conflict
               JOIN control_pr_candidates candidate
                 ON candidate.id = conflict.candidate_id
               WHERE candidate.campaign_id = ?""",
            (campaign_id,),
        ).fetchall():
            if row["candidate_id"] not in immutable_ids and row["conflicts_with_id"] not in immutable_ids:
                conn.execute(
                    "DELETE FROM control_candidate_conflicts WHERE candidate_id = ? AND conflicts_with_id = ?",
                    (row["candidate_id"], row["conflicts_with_id"]),
                )
        for item in target["conflicts"]:
            conn.execute(
                """INSERT OR IGNORE INTO control_candidate_conflicts (
                       candidate_id, conflicts_with_id, reason, resources_json
                   ) VALUES (?, ?, ?, ?)""",
                (
                    item["candidate_id"], item["conflicts_with_id"], item["reason"],
                    json.dumps(item["resources"], ensure_ascii=False),
                ),
            )
        desired_links = {
            self._relation_key(item): item
            for values in target["knowledge_relations"].values()
            for item in values
        }
        current_snapshot = self._plan_snapshot_in_connection(conn, campaign_id)
        current_links = {
            self._relation_key(item): item
            for values in current_snapshot["knowledge_relations"].values()
            for item in values
        }
        for key in sorted(set(current_links) - set(desired_links)):
            self._remove_knowledge_link_in_connection(
                conn,
                current_links[key],
                actor="antigravity-amendment",
                invalidate_plan=False,
            )
        for key in sorted(set(desired_links) - set(current_links)):
            self._record_knowledge_link_in_connection(
                conn,
                desired_links[key],
                actor="antigravity-amendment",
                invalidate_plan=False,
            )
        self._validate_dag(conn, campaign_id)
        simulation = self._simulate_campaign_in_connection(
            conn,
            campaign_id,
            persist=True,
        )
        simulation_id = self._deterministic_amendment_id(
            "DOC", amendment["id"], "simulation", "plan-simulation", 1
        )
        simulation_row = conn.execute(
            "SELECT id FROM control_artifacts WHERE id = ?",
            (simulation_id,),
        ).fetchone()
        if not simulation_row:
            simulation_content = (
                "# Plan Simulation\n\n```json\n"
                + json.dumps(simulation, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n```\n"
            )
            simulation_slug = slugify(f"amendment-{amendment['id']}")
            latest = conn.execute(
                """SELECT MAX(version) AS version FROM control_artifacts
                   WHERE project_id = ? AND artifact_type = 'plan_simulation'
                     AND slug = ?""",
                (project_id, simulation_slug),
            ).fetchone()
            conn.execute(
                """INSERT INTO control_artifacts (
                       id, project_id, campaign_id, artifact_type, slug, title,
                       status, version, relative_path, content_text,
                       content_sha256, metadata_json, materialization_status
                   ) VALUES (?, ?, ?, 'plan_simulation', ?, ?, 'current', ?, '', ?, ?, ?, 'not_requested')""",
                (
                    simulation_id, project_id, campaign_id, simulation_slug,
                    f"{campaign_target['title']} Plan Simulation",
                    int(latest["version"] or 0) + 1,
                    simulation_content,
                    hashlib.sha256(simulation_content.encode("utf-8")).hexdigest(),
                    json.dumps(
                        {
                            "base_sha": campaign_target["base_sha"],
                            "campaign_version": campaign_target["version"],
                            "source": "antigravity-amendment",
                            "simulation_sha256": canonical_json_sha256(simulation),
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
        conn.execute(
            """UPDATE control_campaign_profiles
               SET plan_simulation_artifact_id = ?, updated_at = CURRENT_TIMESTAMP
               WHERE campaign_id = ?""",
            (simulation_id, campaign_id),
        )
        return simulation

    def _assert_amendment_source_in_connection(
        self,
        conn,
        amendment: Dict[str, Any],
    ) -> None:
        before_hash = self._plan_snapshot_sha256(amendment["before_plan"])
        if before_hash != str(amendment["before_plan_sha256"] or ""):
            raise ControlCenterError(
                "Die gespeicherte Amendment-Quellpayload stimmt nicht mit ihrem Hash überein.",
                code="amendment_payload_hash_mismatch",
                status=409,
            )
        campaign = self._campaign(conn, amendment["campaign_id"])
        if str(campaign["status"]) != "paused":
            raise ControlCenterError(
                "Die Campaign ist nicht mehr für dieses Amendment pausiert.",
                code="stale_amendment_source",
                status=409,
            )
        if int(campaign["version"]) != int(amendment["from_version"]):
            raise ControlCenterError("Die Quellversion hat sich geändert.", code="stale_plan_version", status=409)
        if str(campaign["base_sha"] or "") != str(amendment["from_base_sha"]):
            raise ControlCenterError("Die Quell-Baseline hat sich geändert.", code="stale_base_sha", status=409)
        snapshot = self._plan_snapshot_in_connection(conn, amendment["campaign_id"])
        if self._plan_snapshot_sha256(snapshot) != amendment["before_plan_sha256"]:
            raise ControlCenterError(
                "Der Quellplan hat sich seit dem Start verändert.",
                code="stale_amendment_source",
                status=409,
            )
        readiness = self._evaluate_campaign_readiness_in_connection(
            conn,
            amendment["campaign_id"],
            persist=False,
        )
        if (
            readiness["plan_signature"] != amendment["from_plan_signature"]
            or readiness["plan_signature_version"] != amendment["from_signature_version"]
        ):
            raise ControlCenterError(
                "Die Quellplan-Signatur hat sich geändert.",
                code="stale_plan_signature",
                status=409,
            )
        project = self._project(campaign["project_id"])
        head = self._resolve_sha(
            project,
            amendment["planning_base_sha"],
            require=True,
        )
        if head != amendment["planning_base_sha"]:
            raise ControlCenterError(
                "Der Planning-Checkout hat sich geändert.",
                code="stale_amendment_head",
                status=409,
            )

    def _assert_amendment_target_payload_in_connection(
        self,
        amendment: Dict[str, Any],
    ) -> None:
        before = amendment.get("before_plan")
        target = amendment.get("target_plan")
        patch = amendment.get("patch")
        if not all(isinstance(value, dict) for value in (before, target, patch)):
            raise ControlCenterError(
                "Die gespeicherte Amendment-Payload hat eine ungültige Struktur.",
                code="amendment_payload_hash_mismatch",
                status=409,
            )
        target_hash = self._plan_snapshot_sha256(target)
        patch_hash = canonical_json_sha256(patch)
        expected_patch = self._patch_between(before, target)
        if (
            target_hash != str(amendment["target_plan_sha256"] or "")
            or patch_hash != str(amendment["patch_sha256"] or "")
            or patch != expected_patch
        ):
            raise ControlCenterError(
                "Die gespeicherte Amendment-Zielpayload stimmt nicht mit ihren Hashes überein.",
                code="amendment_payload_hash_mismatch",
                status=409,
            )

    def _complete_plan_amendment_job(
        self,
        job_id: str,
        envelope: Dict[str, Any],
    ) -> Dict[str, Any]:
        unexpected = set(envelope) - {
            "type", "resolved_question_ids", "target_plan"
        }
        resolved_ids = envelope.get("resolved_question_ids")
        if (
            str(envelope.get("type") or "").lower() != "amendment_plan"
            or unexpected
            or not isinstance(resolved_ids, list)
            or not all(isinstance(item, str) and item.strip() for item in resolved_ids)
        ):
            raise ControlCenterError(
                "Eine Amendment-Envelope benötigt genau Zielplan und aufgelöste Fragen.",
                code="invalid_amendment_plan_envelope",
            )
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            job = conn.execute(
                "SELECT * FROM control_planning_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if (
                not job
                or str(job["status"]) != "running"
                or str(job["job_type"]) != "plan_amendment"
                or not str(job["amendment_id"] or "")
            ):
                raise ControlCenterError(
                    "Amendment-Planning-Job ist nicht aktiv.",
                    code="planning_job_not_running",
                    status=409,
                )
            questions = conn.execute(
                """SELECT id, status FROM control_question_ledger
                   WHERE planning_job_id = ? ORDER BY id""",
                (job_id,),
            ).fetchall()
            session_ids = {str(item["id"]) for item in questions}
            supplied_ids = {str(item).strip() for item in resolved_ids}
            if len(supplied_ids) != len(resolved_ids) or supplied_ids != session_ids or any(
                str(item["status"]) != "answered" for item in questions
            ):
                raise ControlCenterError(
                    "Der Zielplan verarbeitet nicht exakt alle beantworteten Fragen.",
                    code="planning_questions_unresolved",
                    status=409,
                )
            amendment = self._get_plan_amendment_in_connection(
                conn,
                str(job["amendment_id"]),
            )
            if amendment["status"] not in {"planning", "failed"}:
                raise ControlCenterError(
                    "Dieses Amendment erwartet keinen Zielplan mehr.",
                    code="amendment_not_planning",
                    status=409,
                )
            self._assert_amendment_source_in_connection(conn, amendment)
            normalized, mutable_ids, immutable_ids = self._normalize_target_plan(
                conn,
                amendment,
                envelope.get("target_plan"),
            )
            conn.execute("SAVEPOINT validate_amendment_target")
            try:
                self._apply_target_plan_in_connection(
                    conn,
                    amendment,
                    normalized,
                    immutable_ids=immutable_ids,
                )
                readiness = self._evaluate_campaign_readiness_in_connection(
                    conn,
                    amendment["campaign_id"],
                    persist=False,
                )
                if not readiness["ready"]:
                    raise ControlCenterError(
                        "Der Zielplan erfüllt die Readiness-Gates nicht: "
                        + ", ".join(readiness["missing"]),
                        code="amendment_target_not_ready",
                        status=409,
                    )
                target = self._plan_snapshot_in_connection(
                    conn,
                    amendment["campaign_id"],
                )
            finally:
                conn.execute("ROLLBACK TO validate_amendment_target")
                conn.execute("RELEASE validate_amendment_target")
            patch = self._patch_between(amendment["before_plan"], target)
            target_hash = self._plan_snapshot_sha256(target)
            patch_hash = canonical_json_sha256(patch)
            validation = {
                "ready": True,
                "gates": readiness["gates"],
                "mutable_candidate_ids": sorted(mutable_ids),
                "immutable_candidate_ids": sorted(immutable_ids),
                "warnings": [],
                "plan_signature_version": readiness["plan_signature_version"],
            }
            conn.execute(
                """UPDATE control_plan_amendments
                   SET status = 'review', target_plan_json = ?,
                       target_plan_sha256 = ?, patch_json = ?, patch_sha256 = ?,
                       validation_json = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status IN ('planning', 'failed')""",
                (
                    json.dumps(target, ensure_ascii=False), target_hash,
                    json.dumps(patch, ensure_ascii=False), patch_hash,
                    json.dumps(validation, ensure_ascii=False), amendment["id"],
                ),
            )
            for question in questions:
                conn.execute(
                    """UPDATE control_question_ledger
                       SET status = 'resolved', resolved_in_version = ?,
                           updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND amendment_id = ? AND status = 'answered'""",
                    (int(amendment["proposed_version"]), question["id"], amendment["id"]),
                )
            updated = conn.execute(
                """UPDATE control_planning_jobs
                   SET status = 'waiting_human', waiting_reason = 'amendment_approval',
                       active_question_id = NULL, output_json = ?, last_error = '',
                       finished_at = NULL, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = 'running'""",
                (json.dumps(envelope, ensure_ascii=False), job_id),
            )
            if updated.rowcount != 1:
                raise ControlCenterError(
                    "Planning-Job wurde parallel verändert.",
                    code="planning_job_not_running",
                    status=409,
                )
            self._resolve_attention(
                conn,
                "campaign",
                str(amendment["campaign_id"]),
                "plan_amendment",
            )
            campaign = self._campaign(conn, amendment["campaign_id"])
            self._attention(
                conn,
                project_id=int(campaign["project_id"]),
                category="amendment_approval",
                entity_type="plan_amendment",
                entity_id=str(amendment["id"]),
                title=f"Zielplan v{amendment['proposed_version']} prüfen",
                consequence="Ohne exakte Freigabe bleibt der Quellplan unverändert und pausiert.",
                recommendation="Before-, Target- und Patch-Hash sowie immutable Slices prüfen.",
                urgency="high",
            )
            self._audit(
                conn,
                project_id=int(campaign["project_id"]),
                entity_type="plan_amendment",
                entity_id=str(amendment["id"]),
                action="plan_amendment.target_staged",
                actor="antigravity-planner",
                from_state="planning",
                to_state="review",
                evidence={
                    "before_plan_sha256": amendment["before_plan_sha256"],
                    "target_plan_sha256": target_hash,
                    "patch_sha256": patch_hash,
                    "mutable_candidate_ids": sorted(mutable_ids),
                    "immutable_candidate_ids": sorted(immutable_ids),
                },
            )
            conn.commit()
        return self.get_planning_job(job_id)

    @staticmethod
    def _decision_identity(
        amendment: Dict[str, Any],
        *,
        expected_from_version: Any,
        expected_before_plan_sha256: Any,
        expected_target_plan_sha256: Any,
        expected_patch_sha256: Any,
    ) -> None:
        try:
            version = int(expected_from_version)
        except (TypeError, ValueError) as exc:
            raise ControlCenterError(
                "Die geprüfte Quellversion ist erforderlich.",
                code="amendment_identity_required",
            ) from exc
        supplied = (
            version,
            str(expected_before_plan_sha256 or "").strip().lower(),
            str(expected_target_plan_sha256 or "").strip().lower(),
            str(expected_patch_sha256 or "").strip().lower(),
        )
        stored = (
            int(amendment["from_version"]),
            str(amendment["before_plan_sha256"] or "").lower(),
            str(amendment["target_plan_sha256"] or "").lower(),
            str(amendment["patch_sha256"] or "").lower(),
        )
        if supplied != stored:
            raise ControlCenterError(
                "Die geprüfte Amendment-Identität ist veraltet.",
                code="stale_amendment_target",
                status=409,
            )

    def _restore_amendment_source_in_connection(
        self,
        conn,
        amendment: Dict[str, Any],
        *,
        terminal_status: str,
        actor: str,
        reason: str,
    ) -> None:
        campaign = self._campaign(conn, amendment["campaign_id"])
        if str(campaign["status"]) != "paused":
            raise ControlCenterError(
                "Die Campaign wurde parallel verändert.",
                code="stale_amendment_source",
                status=409,
            )
        conn.execute(
            """UPDATE control_campaigns
               SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (amendment["prior_campaign_status"] or "approved", amendment["campaign_id"]),
        )
        conn.execute(
            """UPDATE control_plan_amendments
               SET status = ?, resolved_by = ?, decision_reason = ?,
                   resolved_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (terminal_status, actor, reason[:5000], amendment["id"]),
        )
        conn.execute(
            """UPDATE control_planning_jobs
               SET status = 'cancelled', waiting_reason = '',
                   active_question_id = NULL,
                   finished_at = COALESCE(finished_at, CURRENT_TIMESTAMP),
                   updated_at = CURRENT_TIMESTAMP
               WHERE amendment_id = ?
                 AND status IN ('queued', 'running', 'waiting_human', 'failed')""",
            (amendment["id"],),
        )
        self._resolve_attention(conn, "campaign", amendment["campaign_id"], "plan_amendment")
        self._resolve_attention(conn, "plan_amendment", amendment["id"], "amendment_approval")

    def decide_plan_amendment(
        self,
        amendment_id: str,
        *,
        decision: str,
        actor: str,
        approval_sha: str = "",
        reason: str = "",
        expected_from_version: Any = None,
        expected_before_plan_sha256: Any = "",
        expected_target_plan_sha256: Any = "",
        expected_patch_sha256: Any = "",
    ) -> Dict[str, Any]:
        selected = str(decision or "").strip().lower()
        if selected not in {"approved", "rejected"}:
            raise ControlCenterError(
                "Entscheidung muss approved oder rejected sein.",
                code="invalid_amendment_decision",
            )
        actor_name = clean_text(actor, "actor", maximum=120)
        explanation = str(reason or "").strip()[:5000]
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            amendment = self._get_plan_amendment_in_connection(conn, amendment_id)
            self._decision_identity(
                amendment,
                expected_from_version=expected_from_version,
                expected_before_plan_sha256=expected_before_plan_sha256,
                expected_target_plan_sha256=expected_target_plan_sha256,
                expected_patch_sha256=expected_patch_sha256,
            )
            if amendment["status"] in AMENDMENT_TERMINAL_STATES:
                if amendment["status"] == selected:
                    conn.commit()
                    return amendment
                raise ControlCenterError(
                    "Dieses Amendment wurde bereits anders entschieden.",
                    code="amendment_decision_conflict",
                    status=409,
                )
            campaign = self._campaign(conn, amendment["campaign_id"])
            if selected == "rejected":
                self._restore_amendment_source_in_connection(
                    conn,
                    amendment,
                    terminal_status="rejected",
                    actor=actor_name,
                    reason=explanation,
                )
                self._audit(
                    conn,
                    project_id=int(campaign["project_id"]),
                    entity_type="plan_amendment",
                    entity_id=amendment_id,
                    action="plan_amendment.rejected",
                    actor=actor_name,
                    from_state=str(amendment["status"]),
                    to_state="rejected",
                    reason=explanation,
                    evidence={
                        "before_plan_sha256": amendment["before_plan_sha256"],
                        "target_plan_sha256": amendment["target_plan_sha256"],
                        "patch_sha256": amendment["patch_sha256"],
                    },
                )
                conn.commit()
                return self._get_plan_amendment_in_connection(conn, amendment_id)
            if (
                amendment["status"] != "review"
                or not amendment["target_plan_sha256"]
                or not amendment["patch_sha256"]
            ):
                code = (
                    "legacy_amendment_target_missing"
                    if amendment["status"] == "proposed"
                    else "amendment_target_not_ready"
                )
                raise ControlCenterError(
                    "Dieses Amendment besitzt keinen freigabefähigen Zielplan.",
                    code=code,
                    status=409,
                )
            self._assert_amendment_source_in_connection(conn, amendment)
            self._assert_amendment_target_payload_in_connection(amendment)
            validation = amendment.get("validation") or {}
            if validation.get("ready") is not True:
                raise ControlCenterError(
                    "Der Zielplan ist nicht freigabefähig.",
                    code="amendment_target_not_ready",
                    status=409,
                )
            current_mutable = self._mutable_candidate_ids(
                conn,
                amendment["campaign_id"],
            )
            if sorted(current_mutable) != sorted(validation.get("mutable_candidate_ids") or []):
                raise ControlCenterError(
                    "Die Candidate-Mutability hat sich seit der Prüfung geändert.",
                    code="stale_amendment_mutability",
                    status=409,
                )
            immutable_ids = set(validation.get("immutable_candidate_ids") or [])
            self._apply_target_plan_in_connection(
                conn,
                amendment,
                amendment["target_plan"],
                immutable_ids=immutable_ids,
            )
            after = self._plan_snapshot_in_connection(conn, amendment["campaign_id"])
            if self._plan_snapshot_sha256(after) != amendment["target_plan_sha256"]:
                raise ControlCenterError(
                    "Der atomar angewendete Plan entspricht nicht dem geprüften Ziel.",
                    code="amendment_apply_hash_mismatch",
                    status=409,
                )
            verified_sha = str(amendment["planning_base_sha"])
            if approval_sha:
                verified_sha = self._resolve_sha(
                    self._project(campaign["project_id"]),
                    approval_sha,
                    require=True,
                )
                if verified_sha != amendment["planning_base_sha"]:
                    raise ControlCenterError(
                        "Freigabe-SHA und geprüfter Planning-Stand stimmen nicht überein.",
                        code="approval_sha_mismatch",
                        status=409,
                    )
            conn.execute(
                """UPDATE control_plan_amendments
                   SET status = 'approved', approved_by = ?, approved_sha = ?,
                       resolved_by = ?, decision_reason = ?,
                       resolved_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = 'review'""",
                (actor_name, verified_sha, actor_name, explanation, amendment_id),
            )
            conn.execute(
                """UPDATE control_planning_jobs
                   SET status = 'completed', waiting_reason = '',
                       active_question_id = NULL, last_error = '',
                       finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                   WHERE amendment_id = ? AND status = 'waiting_human'
                     AND waiting_reason = 'amendment_approval'""",
                (amendment_id,),
            )
            self._resolve_attention(conn, "plan_amendment", amendment_id, "amendment_approval")
            self._attention(
                conn,
                project_id=int(campaign["project_id"]),
                category="plan_approval",
                entity_type="campaign",
                entity_id=str(campaign["id"]),
                title=f"Geänderten Plan „{after['campaign']['title']}“ freigeben",
                consequence="Ohne normale exakte Planfreigabe startet kein neuer Work Order.",
                recommendation="Readiness und neue Plan-Signatur prüfen und Plan v"
                f"{after['campaign']['version']} separat freigeben.",
                urgency="high",
            )
            self._audit(
                conn,
                project_id=int(campaign["project_id"]),
                entity_type="plan_amendment",
                entity_id=amendment_id,
                action="plan_amendment.approved",
                actor=actor_name,
                from_state="review",
                to_state="approved",
                reason=explanation,
                evidence={
                    "from_version": amendment["from_version"],
                    "proposed_version": amendment["proposed_version"],
                    "before_plan_sha256": amendment["before_plan_sha256"],
                    "target_plan_sha256": amendment["target_plan_sha256"],
                    "patch_sha256": amendment["patch_sha256"],
                    "planning_base_sha": amendment["planning_base_sha"],
                },
            )
            conn.commit()
            return self._get_plan_amendment_in_connection(conn, amendment_id)

    def _cancel_amendment_for_job_in_connection(
        self,
        conn,
        job,
        *,
        actor: str,
        reason: str,
    ) -> None:
        amendment_id = str(job["amendment_id"] or "")
        if not amendment_id:
            return
        amendment = self._get_plan_amendment_in_connection(conn, amendment_id)
        if amendment["status"] in AMENDMENT_TERMINAL_STATES:
            return
        self._restore_amendment_source_in_connection(
            conn,
            amendment,
            terminal_status="cancelled",
            actor=actor,
            reason=reason,
        )

    @staticmethod
    def _set_amendment_job_state_in_connection(
        conn,
        job,
        status: str,
    ) -> None:
        amendment_id = str(job["amendment_id"] or "")
        if amendment_id:
            conn.execute(
                """UPDATE control_plan_amendments
                   SET status = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status IN ('planning', 'failed')""",
                (status, amendment_id),
            )
