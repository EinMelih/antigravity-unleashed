"""Deep planning, readiness gates, graph simulation, and amendments."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from typing import Any, Dict, Iterable

from src.control_center.artifacts import slugify
from src.control_center.common import (
    ACTIVATION_POLICIES,
    PLANNING_DEPTHS,
    QUESTION_STATES,
    ControlCenterError,
    canonical_json_sha256,
    clean_text,
    public_id,
    validate_acceptance_criteria,
)


DEPTH_DEFAULT_LIMITS = {
    "compact": 5,
    "balanced": 12,
    "deep": 30,
    "exhaustive": 100,
}

PLAN_SIGNATURE_VERSION = 2
REQUIRED_DECISION_BRANCHES = ("architecture", "data", "security", "operations")
TERMINAL_QUESTION_STATES = {
    "resolved",
    "grounded",
    "assumption-accepted",
    "discovery-assigned",
    "deferred",
}
UNCERTAINTY_QUESTION_STATES = {
    "assumption-accepted",
    "discovery-assigned",
    "deferred",
}


def _unique_text_list(
    value: Any,
    field: str,
    *,
    required: bool = False,
    maximum: int = 200,
    item_maximum: int = 2000,
) -> list[str]:
    if isinstance(value, str):
        value = [line.strip() for line in value.splitlines() if line.strip()]
    if value is None:
        value = []
    if not isinstance(value, list):
        raise ControlCenterError(f"{field} muss eine Liste sein.", code=f"invalid_{field}")
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text[:item_maximum])
    if required and not result:
        raise ControlCenterError(f"{field} ist erforderlich.", code=f"missing_{field}")
    if len(result) > maximum:
        raise ControlCenterError(
            f"{field} darf höchstens {maximum} Einträge enthalten.",
            code=f"{field}_too_large",
        )
    return result


def _score(value: Any, field: str, default: float) -> float:
    if value in (None, ""):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ControlCenterError(
            f"{field} muss eine Zahl sein.",
            code=f"invalid_{field}",
        ) from exc
    if not 0 <= number <= 10:
        raise ControlCenterError(
            f"{field} muss zwischen 0 und 10 liegen.",
            code=f"invalid_{field}",
        )
    return number


def _normalize_alternatives(value: Any) -> list[Dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ControlCenterError(
            "alternatives muss eine Liste sein.",
            code="invalid_alternatives",
        )
    if len(value) > 20:
        raise ControlCenterError(
            "alternatives darf höchstens 20 Einträge enthalten.",
            code="alternatives_too_large",
        )
    result: list[Dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ControlCenterError(
                "Alternativen müssen strukturierte Objekte sein.",
                code="invalid_alternative",
            )
        result.append(
            {
                "title": clean_text(
                    item.get("title"),
                    "alternative_title",
                    minimum=3,
                    maximum=200,
                ),
                "mechanism": clean_text(
                    item.get("mechanism"),
                    "alternative_mechanism",
                    minimum=10,
                    maximum=5000,
                ),
                "tradeoffs": clean_text(
                    item.get("tradeoffs"),
                    "alternative_tradeoffs",
                    minimum=10,
                    maximum=5000,
                ),
            }
        )
    return result


def _optional_reason(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return clean_text(text, field, minimum=10, maximum=10000)


class PlanningMixin:
    def _invalidate_draft_plan_in_connection(
        self,
        conn,
        campaign_id: str,
    ) -> int:
        updated = conn.execute(
            """UPDATE control_campaigns
               SET version = version + 1, approved_version = NULL,
                   approved_sha = '', approved_by = '',
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = ? AND status = 'draft'""",
            (campaign_id,),
        )
        if updated.rowcount != 1:
            raise ControlCenterError(
                "Ein genehmigter Plan benötigt ein Amendment.",
                code="campaign_locked",
                status=409,
            )
        conn.execute(
            """UPDATE control_campaign_profiles
               SET readiness_status = 'draft', readiness_score = 0,
                   plan_signature = '', updated_at = CURRENT_TIMESTAMP
               WHERE campaign_id = ?""",
            (campaign_id,),
        )
        conn.execute(
            """UPDATE control_artifacts
               SET status = 'superseded', updated_at = CURRENT_TIMESTAMP
               WHERE campaign_id = ? AND artifact_type = 'plan_simulation'
                 AND status != 'superseded'""",
            (campaign_id,),
        )
        row = conn.execute(
            "SELECT version FROM control_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        return int(row["version"])

    @staticmethod
    def _insert_campaign_profile(
        conn,
        campaign_id: str,
        title: str,
        payload: Dict[str, Any],
    ) -> None:
        depth = str(payload.get("planning_depth") or "compact").strip().lower()
        if depth not in PLANNING_DEPTHS:
            raise ControlCenterError(
                "Unbekannter Planungsgrad.",
                code="invalid_planning_depth",
            )
        try:
            requested = int(
                payload.get("max_candidates", DEPTH_DEFAULT_LIMITS[depth])
            )
        except (TypeError, ValueError) as exc:
            raise ControlCenterError(
                "max_candidates muss eine Zahl sein.",
                code="invalid_max_candidates",
            ) from exc
        if not 1 <= requested <= 100:
            raise ControlCenterError(
                "max_candidates muss zwischen 1 und 100 liegen.",
                code="invalid_max_candidates",
            )
        activation_policy = str(
            payload.get("activation_policy") or "per_candidate"
        ).strip()
        if activation_policy not in ACTIVATION_POLICIES:
            raise ControlCenterError(
                "Unbekannte Aktivierungs-Policy.",
                code="invalid_activation_policy",
            )
        conn.execute(
            """INSERT INTO control_campaign_profiles (
                   campaign_id, slug, planning_depth, requested_max_candidates,
                   activation_policy, pivotal_fork, pivotal_fork_na_reason,
                   success_metrics_json,
                   constraints_json, assumptions_json, acceptance_matrix_json,
                   alternatives_json, review_strategy, rollout_plan, rollback_plan
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(campaign_id) DO UPDATE SET
                   slug = excluded.slug,
                   planning_depth = excluded.planning_depth,
                   requested_max_candidates = excluded.requested_max_candidates,
                   activation_policy = excluded.activation_policy,
                   readiness_status = 'draft',
                    readiness_score = 0,
                    pivotal_fork = excluded.pivotal_fork,
                    pivotal_fork_na_reason = excluded.pivotal_fork_na_reason,
                   success_metrics_json = excluded.success_metrics_json,
                   constraints_json = excluded.constraints_json,
                    assumptions_json = excluded.assumptions_json,
                    acceptance_matrix_json = excluded.acceptance_matrix_json,
                    alternatives_json = excluded.alternatives_json,
                    review_strategy = excluded.review_strategy,
                    rollout_plan = excluded.rollout_plan,
                   rollback_plan = excluded.rollback_plan,
                   plan_signature = '',
                   updated_at = CURRENT_TIMESTAMP""",
            (
                campaign_id,
                slugify(payload.get("slug") or title),
                depth,
                requested,
                activation_policy,
                str(payload.get("pivotal_fork") or "").strip()[:10000],
                _optional_reason(
                    payload.get("pivotal_fork_na_reason"),
                    "pivotal_fork_na_reason",
                ),
                json.dumps(
                    _unique_text_list(payload.get("success_metrics"), "success_metrics"),
                    ensure_ascii=False,
                ),
                json.dumps(
                    _unique_text_list(payload.get("constraints"), "constraints"),
                    ensure_ascii=False,
                ),
                json.dumps(
                    _unique_text_list(payload.get("assumptions"), "assumptions"),
                    ensure_ascii=False,
                ),
                json.dumps(
                    _unique_text_list(
                        payload.get("acceptance_matrix"),
                        "acceptance_matrix",
                    ),
                    ensure_ascii=False,
                ),
                json.dumps(
                    _normalize_alternatives(payload.get("alternatives")),
                    ensure_ascii=False,
                ),
                str(payload.get("review_strategy") or "").strip()[:10000],
                str(payload.get("rollout_plan") or "").strip()[:10000],
                str(payload.get("rollback_plan") or "").strip()[:10000],
            ),
        )

    def get_campaign_profile(self, campaign_id: str) -> Dict[str, Any]:
        with self.db._get_connection() as conn:
            campaign = self._campaign(conn, campaign_id)
            row = conn.execute(
                "SELECT * FROM control_campaign_profiles WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
        if not row:
            raise ControlCenterError(
                "Campaign-Planungsprofil fehlt.",
                code="campaign_profile_not_found",
                status=404,
            )
        result = self._row(
            row,
            (
                "success_metrics_json",
                "constraints_json",
                "assumptions_json",
                "acceptance_matrix_json",
                "alternatives_json",
            ),
        )
        result["project_id"] = int(campaign["project_id"])
        return result

    def update_campaign_profile(
        self,
        campaign_id: str,
        payload: Dict[str, Any],
        *,
        actor: str = "human",
    ) -> Dict[str, Any]:
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            campaign = self._campaign(conn, campaign_id)
            if campaign["status"] != "draft":
                raise ControlCenterError(
                    "Ein genehmigter Plan benötigt ein Amendment.",
                    code="campaign_locked",
                    status=409,
                )
            current_row = conn.execute(
                "SELECT * FROM control_campaign_profiles WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            if not current_row:
                raise ControlCenterError(
                    "Campaign-Planungsprofil fehlt.",
                    code="campaign_profile_not_found",
                    status=404,
                )
            current = self._row(
                current_row,
                (
                    "success_metrics_json",
                    "constraints_json",
                    "assumptions_json",
                    "acceptance_matrix_json",
                    "alternatives_json",
                ),
            )
            depth = str(payload.get("planning_depth", current["planning_depth"])).strip()
            if depth not in PLANNING_DEPTHS:
                raise ControlCenterError(
                    "Unbekannter Planungsgrad.",
                    code="invalid_planning_depth",
                )
            try:
                maximum = int(
                    payload.get(
                        "max_candidates",
                        current["requested_max_candidates"],
                    )
                )
            except (TypeError, ValueError) as exc:
                raise ControlCenterError(
                    "max_candidates muss eine Zahl sein.",
                    code="invalid_max_candidates",
                ) from exc
            policy = self._repository_policy_in_connection(
                conn,
                int(campaign["project_id"]),
            )
            maximum = min(maximum, int(policy["max_candidates"]))
            if not 1 <= maximum <= 100:
                raise ControlCenterError(
                    "max_candidates muss zwischen 1 und 100 liegen.",
                    code="invalid_max_candidates",
                )
            activation = str(
                payload.get("activation_policy", current["activation_policy"])
            ).strip()
            if activation not in ACTIVATION_POLICIES:
                raise ControlCenterError(
                    "Unbekannte Aktivierungs-Policy.",
                    code="invalid_activation_policy",
                )

            list_fields = {
                "success_metrics": "success_metrics_json",
                "constraints": "constraints_json",
                "assumptions": "assumptions_json",
                "acceptance_matrix": "acceptance_matrix_json",
            }
            serialized = {}
            for public_name, column in list_fields.items():
                value = payload.get(public_name, current.get(public_name))
                serialized[column] = json.dumps(
                    _unique_text_list(value, public_name),
                    ensure_ascii=False,
                )
            alternatives = _normalize_alternatives(
                payload.get("alternatives", current.get("alternatives"))
            )
            review_strategy = str(
                payload.get("review_strategy", current.get("review_strategy") or "")
            ).strip()[:10000]
            pivotal = str(
                payload.get("pivotal_fork", current["pivotal_fork"])
            ).strip()[:10000]
            pivotal_na_reason = _optional_reason(
                payload.get(
                    "pivotal_fork_na_reason",
                    current.get("pivotal_fork_na_reason"),
                ),
                "pivotal_fork_na_reason",
            )
            rollout = str(
                payload.get("rollout_plan", current["rollout_plan"])
            ).strip()[:10000]
            rollback = str(
                payload.get("rollback_plan", current["rollback_plan"])
            ).strip()[:10000]
            conn.execute(
                """UPDATE control_campaign_profiles
                   SET planning_depth = ?, requested_max_candidates = ?,
                        activation_policy = ?, pivotal_fork = ?,
                        pivotal_fork_na_reason = ?,
                        success_metrics_json = ?, constraints_json = ?,
                        assumptions_json = ?, acceptance_matrix_json = ?,
                        alternatives_json = ?, review_strategy = ?,
                        rollout_plan = ?, rollback_plan = ?,
                       readiness_status = 'draft', readiness_score = 0,
                       plan_signature = '', updated_at = CURRENT_TIMESTAMP
                   WHERE campaign_id = ?""",
                (
                    depth,
                    maximum,
                    activation,
                    pivotal,
                    pivotal_na_reason,
                    serialized["success_metrics_json"],
                    serialized["constraints_json"],
                    serialized["assumptions_json"],
                    serialized["acceptance_matrix_json"],
                    json.dumps(alternatives, ensure_ascii=False),
                    review_strategy,
                    rollout,
                    rollback,
                    campaign_id,
                ),
            )
            self._invalidate_draft_plan_in_connection(conn, campaign_id)
            self._audit(
                conn,
                project_id=int(campaign["project_id"]),
                entity_type="campaign",
                entity_id=campaign_id,
                action="campaign.profile_updated",
                actor=str(actor or "human")[:120],
                evidence={
                    "planning_depth": depth,
                    "max_candidates": maximum,
                    "activation_policy": activation,
                },
            )
            conn.commit()
        return self.get_campaign_profile(campaign_id)

    def add_planning_question(
        self,
        campaign_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        branch = clean_text(payload.get("branch"), "branch", maximum=120)
        question = clean_text(payload.get("question"), "question", minimum=5, maximum=5000)
        rationale = str(payload.get("rationale") or "").strip()[:5000]
        status = str(payload.get("status") or "open").strip()
        if status not in QUESTION_STATES:
            raise ControlCenterError(
                "Ungültiger Fragenstatus.",
                code="invalid_question_status",
            )
        evidence = payload.get("evidence") or {}
        if not isinstance(evidence, dict):
            raise ControlCenterError(
                "evidence muss ein Objekt sein.",
                code="invalid_question_evidence",
            )
        question_id = public_id("Q")
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            campaign = self._campaign(conn, campaign_id)
            if str(campaign["status"]) != "draft":
                raise ControlCenterError(
                    "Ein genehmigter Plan benötigt ein Amendment.",
                    code="campaign_locked",
                    status=409,
                )
            conn.execute(
                """INSERT INTO control_question_ledger (
                       id, campaign_id, branch, question, rationale, status,
                       owner, evidence_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    question_id,
                    campaign_id,
                    branch,
                    question,
                    rationale,
                    status,
                    str(payload.get("owner") or "")[:120],
                    json.dumps(evidence, ensure_ascii=False),
                ),
            )
            self._invalidate_draft_plan_in_connection(conn, campaign_id)
            self._audit(
                conn,
                project_id=int(campaign["project_id"]),
                entity_type="campaign",
                entity_id=campaign_id,
                action="planning.question_added",
                actor=str(payload.get("actor") or "planner")[:120],
                evidence={"question_id": question_id, "branch": branch, "status": status},
            )
            conn.commit()
            return self._row(
                conn.execute(
                    "SELECT * FROM control_question_ledger WHERE id = ?",
                    (question_id,),
                ).fetchone(),
                ("evidence_json",),
            )

    def answer_planning_question(
        self,
        question_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        status = str(payload.get("status") or "answered").strip()
        if status not in QUESTION_STATES - {"open", "researching", "contradiction"}:
            raise ControlCenterError(
                "Dieser Status schließt eine Frage nicht ab.",
                code="invalid_answer_status",
            )
        answer = clean_text(payload.get("answer"), "answer", minimum=1, maximum=20000)
        source = clean_text(
            payload.get("answer_source") or "human",
            "answer_source",
            maximum=120,
        )
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT q.*, c.project_id, c.version,
                          c.status AS campaign_status
                   FROM control_question_ledger q
                   JOIN control_campaigns c ON c.id = q.campaign_id
                   WHERE q.id = ?""",
                (question_id,),
            ).fetchone()
            if not row:
                raise ControlCenterError(
                    "Frage nicht gefunden.",
                    code="question_not_found",
                    status=404,
                )
            planning_job = None
            amendment_question = False
            if row["planning_job_id"]:
                if status != "answered":
                    raise ControlCenterError(
                        "Eine aktive Planning-Session erwartet eine menschliche Antwort.",
                        code="planning_session_answer_status_invalid",
                        status=409,
                    )
                planning_job = conn.execute(
                    "SELECT * FROM control_planning_jobs WHERE id = ?",
                    (row["planning_job_id"],),
                ).fetchone()
                if (
                    not planning_job
                    or str(planning_job["status"]) != "waiting_human"
                    or str(planning_job["waiting_reason"]) != "question"
                    or str(planning_job["active_question_id"]) != question_id
                ):
                    raise ControlCenterError(
                        "Diese Planning-Frage wartet nicht mehr auf eine Antwort.",
                        code="planning_question_not_active",
                        status=409,
                    )
                amendment_question = (
                    str(planning_job["job_type"] or "") == "plan_amendment"
                    and str(planning_job["amendment_id"] or "")
                    == str(row["amendment_id"] or "")
                )
            if amendment_question:
                if str(row["campaign_status"] or "") != "paused":
                    raise ControlCenterError(
                        "Die Amendment-Campaign ist nicht mehr pausiert.",
                        code="stale_amendment_source",
                        status=409,
                    )
            elif str(row["campaign_status"] or "") != "draft":
                raise ControlCenterError(
                    "Ein genehmigter Plan benötigt ein Amendment.",
                    code="campaign_locked",
                    status=409,
                )
            resolved_in_version = (
                int(row["version"]) + 1
                if not row["planning_job_id"] or status == "resolved"
                else None
            )
            conn.execute(
                """UPDATE control_question_ledger
                   SET answer = ?, answer_source = ?, status = ?,
                       resolved_in_version = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (answer, source, status, resolved_in_version, question_id),
            )
            if not amendment_question:
                self._invalidate_draft_plan_in_connection(
                    conn,
                    str(row["campaign_id"]),
                )
            if planning_job:
                updated = conn.execute(
                    """UPDATE control_planning_jobs
                       SET status = 'queued', waiting_reason = '',
                           last_error = '', finished_at = NULL,
                           updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND status = 'waiting_human'
                         AND waiting_reason = 'question'
                         AND active_question_id = ?""",
                    (planning_job["id"], question_id),
                )
                if updated.rowcount != 1:
                    conn.rollback()
                    raise ControlCenterError(
                        "Diese Planning-Frage wurde parallel verändert.",
                        code="planning_question_not_active",
                        status=409,
                    )
                self._resolve_attention(
                    conn,
                    "planning_question",
                    question_id,
                    "planning_question",
                )
                self._audit(
                    conn,
                    project_id=int(row["project_id"]),
                    entity_type="planning_job",
                    entity_id=str(planning_job["id"]),
                    action="planning_job.question_answered",
                    actor=source,
                    from_state="waiting_human",
                    to_state="queued",
                    evidence={
                        "question_id": question_id,
                        "round_number": int(planning_job["round_number"]),
                    },
                )
            self._audit(
                conn,
                project_id=int(row["project_id"]),
                entity_type="campaign",
                entity_id=str(row["campaign_id"]),
                action="planning.question_answered",
                actor=source,
                evidence={"question_id": question_id, "status": status},
            )
            conn.commit()
            return self._row(
                conn.execute(
                    "SELECT * FROM control_question_ledger WHERE id = ?",
                    (question_id,),
                ).fetchone(),
                ("evidence_json",),
            )

    @staticmethod
    def _write_candidate_contract(
        conn,
        candidate_id: str,
        payload: Dict[str, Any],
        criteria: Iterable[str],
        *,
        strict: bool = False,
    ) -> None:
        components = _unique_text_list(
            payload.get("components"),
            "components",
            required=strict,
        )
        required_checks = _unique_text_list(
            payload.get("required_checks"),
            "required_checks",
            required=strict,
        )
        manual_tests = _unique_text_list(
            payload.get("manual_tests"),
            "manual_tests",
            required=strict,
        )
        documentation = _unique_text_list(
            payload.get("documentation_changes"),
            "documentation_changes",
            required=strict,
        )
        if strict:
            clean_text(payload.get("non_goals"), "non_goals", maximum=5000)
            purpose = clean_text(
                payload.get("purpose"),
                "purpose",
                maximum=10000,
            )
            expected_diff_type = clean_text(
                payload.get("expected_diff_type"),
                "expected_diff_type",
                maximum=120,
            )
            reversibility = clean_text(
                payload.get("reversibility"),
                "reversibility",
                maximum=5000,
            )
            migration_plan = clean_text(
                payload.get("migration_plan"),
                "migration_plan",
                maximum=5000,
            )
            compatibility_plan = clean_text(
                payload.get("compatibility_plan"),
                "compatibility_plan",
                maximum=5000,
            )
            definition = clean_text(
                payload.get("definition_of_done"),
                "definition_of_done",
                maximum=10000,
            )
        else:
            purpose = str(payload.get("purpose") or "").strip()[:10000]
            expected_diff_type = str(
                payload.get("expected_diff_type") or ""
            ).strip()[:120]
            reversibility = str(payload.get("reversibility") or "").strip()[:5000]
            migration_plan = str(payload.get("migration_plan") or "").strip()[:5000]
            compatibility_plan = str(
                payload.get("compatibility_plan") or ""
            ).strip()[:5000]
            definition = str(payload.get("definition_of_done") or "").strip()[:10000]
        estimated_size = str(payload.get("estimated_size") or "small").strip().lower()
        if estimated_size not in {"discovery", "tiny", "small", "medium", "large"}:
            raise ControlCenterError(
                "Ungültige geschätzte PR-Größe.",
                code="invalid_estimated_size",
            )
        values = {
            "business_value": _score(payload.get("business_value"), "business_value", 5),
            "unblock_score": _score(payload.get("unblock_score"), "unblock_score", 0),
            "learning_value": _score(payload.get("learning_value"), "learning_value", 0),
            "urgency_score": _score(payload.get("urgency_score"), "urgency_score", 0),
            "effort_score": _score(payload.get("effort_score"), "effort_score", 3),
            "change_risk_score": _score(
                payload.get("change_risk_score"),
                "change_risk_score",
                3,
            ),
            "reversibility_score": _score(
                payload.get("reversibility_score"),
                "reversibility_score",
                7,
            ),
        }
        ready_score = round(
            values["business_value"] * 1.5
            + values["unblock_score"] * 1.4
            + values["learning_value"]
            + values["urgency_score"]
            + values["reversibility_score"] * 0.5
            - values["effort_score"]
            - values["change_risk_score"] * 1.2,
            2,
        )
        conn.execute(
            """INSERT INTO control_candidate_contracts (
                   candidate_id, purpose, components_json, expected_diff_type,
                   required_checks_json, manual_tests_json, reversibility,
                   migration_plan, compatibility_plan, documentation_json,
                   definition_of_done, estimated_size, business_value,
                   unblock_score, learning_value, urgency_score, effort_score,
                   change_risk_score, reversibility_score, ready_score
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                candidate_id,
                purpose,
                json.dumps(components, ensure_ascii=False),
                expected_diff_type,
                json.dumps(required_checks, ensure_ascii=False),
                json.dumps(manual_tests, ensure_ascii=False),
                reversibility,
                migration_plan,
                compatibility_plan,
                json.dumps(documentation, ensure_ascii=False),
                definition,
                estimated_size,
                values["business_value"],
                values["unblock_score"],
                values["learning_value"],
                values["urgency_score"],
                values["effort_score"],
                values["change_risk_score"],
                values["reversibility_score"],
                ready_score,
            ),
        )

    def set_candidate_conflicts(
        self,
        campaign_id: str,
        candidate_id: str,
        conflicts: list[Dict[str, Any]],
    ) -> None:
        if not isinstance(conflicts, list):
            raise ControlCenterError(
                "conflicts muss eine Liste sein.",
                code="invalid_conflicts",
            )
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            campaign = self._campaign(conn, campaign_id)
            if str(campaign["status"]) != "draft":
                raise ControlCenterError(
                    "Ein genehmigter Plan benötigt ein Amendment.",
                    code="campaign_locked",
                    status=409,
                )
            candidate = conn.execute(
                """SELECT id FROM control_pr_candidates
                   WHERE id = ? AND campaign_id = ?""",
                (candidate_id, campaign_id),
            ).fetchone()
            if not candidate:
                raise ControlCenterError(
                    "PR Candidate nicht gefunden.",
                    code="candidate_not_found",
                    status=404,
                )
            conn.execute(
                """DELETE FROM control_candidate_conflicts
                   WHERE candidate_id = ? OR conflicts_with_id = ?""",
                (candidate_id, candidate_id),
            )
            for item in conflicts:
                if not isinstance(item, dict):
                    raise ControlCenterError(
                        "Conflict-Einträge müssen Objekte sein.",
                        code="invalid_conflict",
                    )
                other_id = str(item.get("candidate_id") or "").strip()
                if not other_id or other_id == candidate_id:
                    raise ControlCenterError(
                        "Ungültiges Conflict-Ziel.",
                        code="invalid_conflict",
                    )
                other = conn.execute(
                    """SELECT id FROM control_pr_candidates
                       WHERE id = ? AND campaign_id = ?""",
                    (other_id, campaign_id),
                ).fetchone()
                if not other:
                    raise ControlCenterError(
                        "Conflict-Ziel gehört nicht zur Campaign.",
                        code="cross_campaign_conflict",
                    )
                first, second = sorted((candidate_id, other_id))
                resources = _unique_text_list(
                    item.get("resources"),
                    "conflict_resources",
                )
                conn.execute(
                    """INSERT OR REPLACE INTO control_candidate_conflicts (
                           candidate_id, conflicts_with_id, reason, resources_json
                       ) VALUES (?, ?, ?, ?)""",
                    (
                        first,
                        second,
                        clean_text(
                            item.get("reason"),
                            "conflict_reason",
                            maximum=2000,
                        ),
                        json.dumps(resources, ensure_ascii=False),
                    ),
                )
            self._audit(
                conn,
                project_id=int(campaign["project_id"]),
                entity_type="pr_candidate",
                entity_id=candidate_id,
                action="candidate.conflicts_updated",
                actor="planner",
                evidence={"count": len(conflicts)},
            )
            self._invalidate_draft_plan_in_connection(conn, campaign_id)
            conn.commit()

    def _simulate_campaign_in_connection(
        self,
        conn,
        campaign_id: str,
        *,
        persist: bool,
    ) -> Dict[str, Any]:
        self._campaign(conn, campaign_id)
        candidate_rows = conn.execute(
            """SELECT pc.*, cc.ready_score, cc.paused, cc.pinned
               FROM control_pr_candidates pc
               JOIN control_candidate_contracts cc ON cc.candidate_id = pc.id
               WHERE pc.campaign_id = ?
               ORDER BY pc.priority ASC, pc.created_at ASC""",
            (campaign_id,),
        ).fetchall()
        nodes = {str(row["id"]): dict(row) for row in candidate_rows}
        if not nodes:
            raise ControlCenterError(
                "Keine vollständigen PR-Verträge vorhanden.",
                code="candidate_contract_required",
                status=409,
            )
        dependency_rows = conn.execute(
            """SELECT d.candidate_id, d.depends_on_id
               FROM control_pr_dependencies d
               JOIN control_pr_candidates pc ON pc.id = d.candidate_id
               WHERE pc.campaign_id = ?""",
            (campaign_id,),
        ).fetchall()
        dependencies: Dict[str, set[str]] = {node: set() for node in nodes}
        reverse: Dict[str, set[str]] = defaultdict(set)
        for row in dependency_rows:
            node = str(row["candidate_id"])
            dependency = str(row["depends_on_id"])
            if node not in nodes or dependency not in nodes:
                raise ControlCenterError(
                    "Dependency Graph verweist außerhalb der Campaign.",
                    code="cross_campaign_dependency",
                    status=409,
                )
            dependencies[node].add(dependency)
            reverse[dependency].add(node)
        indegree = {node: len(values) for node, values in dependencies.items()}
        ready = deque(
            sorted(
                (node for node, count in indegree.items() if count == 0),
                key=lambda node: (
                    int(nodes[node]["priority"]),
                    -float(nodes[node]["ready_score"]),
                    node,
                ),
            )
        )
        topo: list[str] = []
        while ready:
            node = ready.popleft()
            topo.append(node)
            for child in sorted(reverse[node]):
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        if len(topo) != len(nodes):
            raise ControlCenterError(
                "Der PR-Abhängigkeitsgraph enthält einen Zyklus.",
                code="cyclic_pr_dependencies",
                status=409,
            )

        conflict_rows = conn.execute(
            """SELECT cc.* FROM control_candidate_conflicts cc
               JOIN control_pr_candidates pc ON pc.id = cc.candidate_id
               WHERE pc.campaign_id = ?
               ORDER BY cc.candidate_id ASC, cc.conflicts_with_id ASC""",
            (campaign_id,),
        ).fetchall()
        conflicts: Dict[str, set[str]] = defaultdict(set)
        conflict_details = []
        for row in conflict_rows:
            first = str(row["candidate_id"])
            second = str(row["conflicts_with_id"])
            conflicts[first].add(second)
            conflicts[second].add(first)
            conflict_details.append(
                {
                    "candidate_id": first,
                    "conflicts_with_id": second,
                    "reason": row["reason"],
                    "resources": json.loads(row["resources_json"] or "[]"),
                }
            )

        wave_by_node: Dict[str, int] = {}
        wave_members: Dict[int, list[str]] = defaultdict(list)
        for node in topo:
            wave = 1 + max(
                (wave_by_node[dependency] for dependency in dependencies[node]),
                default=0,
            )
            while any(member in conflicts[node] for member in wave_members[wave]):
                wave += 1
            wave_by_node[node] = wave
            wave_members[wave].append(node)

        if persist:
            for node, wave in wave_by_node.items():
                conn.execute(
                    """UPDATE control_candidate_contracts
                       SET wave = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE candidate_id = ?""",
                    (wave, node),
                )

        return {
            "campaign_id": campaign_id,
            "acyclic": True,
            "candidate_count": len(nodes),
            "topological_order": topo,
            "waves": [
                {
                    "wave": wave,
                    "candidate_ids": members,
                    "parallel_count": len(members),
                }
                for wave, members in sorted(wave_members.items())
            ],
            "dependencies": {
                node: sorted(values) for node, values in dependencies.items()
            },
            "conflicts": conflict_details,
            "max_wave": max(wave_members, default=0),
        }

    def simulate_campaign(self, campaign_id: str, *, persist: bool = True) -> Dict[str, Any]:
        with self.db._get_connection() as conn:
            result = self._simulate_campaign_in_connection(
                conn,
                campaign_id,
                persist=persist,
            )
            if persist:
                conn.commit()
            return result

    @staticmethod
    def _canonical_json(value: Any, *, fallback: Any) -> Any:
        try:
            return json.loads(value or json.dumps(fallback))
        except (json.JSONDecodeError, TypeError):
            return {"invalid_json": str(value or "")}

    def _evaluate_campaign_readiness_in_connection(
        self,
        conn,
        campaign_id: str,
        *,
        persist: bool,
    ) -> Dict[str, Any]:
        campaign = self._campaign(conn, campaign_id)
        profile_row = conn.execute(
            "SELECT * FROM control_campaign_profiles WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if not profile_row:
            raise ControlCenterError(
                "Campaign-Planungsprofil fehlt.",
                code="campaign_profile_not_found",
                status=404,
            )
        profile = self._row(
            profile_row,
            (
                "success_metrics_json",
                "constraints_json",
                "assumptions_json",
                "acceptance_matrix_json",
                "alternatives_json",
            ),
        )
        project = self._project(campaign["project_id"])
        candidate_rows = conn.execute(
            "SELECT * FROM control_pr_candidates WHERE campaign_id = ? ORDER BY id",
            (campaign_id,),
        ).fetchall()
        contract_rows = conn.execute(
            """SELECT cc.* FROM control_candidate_contracts cc
               JOIN control_pr_candidates pc ON pc.id = cc.candidate_id
               WHERE pc.campaign_id = ? ORDER BY cc.candidate_id""",
            (campaign_id,),
        ).fetchall()
        contracts_by_id = {str(row["candidate_id"]): row for row in contract_rows}
        question_rows = conn.execute(
            """SELECT * FROM control_question_ledger
               WHERE campaign_id = ? AND amendment_id IS NULL ORDER BY id""",
            (campaign_id,),
        ).fetchall()
        artifact_rows = conn.execute(
            "SELECT * FROM control_artifacts WHERE campaign_id = ? ORDER BY id",
            (campaign_id,),
        ).fetchall()
        dependency_rows = conn.execute(
            """SELECT d.candidate_id, d.depends_on_id
               FROM control_pr_dependencies d
               JOIN control_pr_candidates pc ON pc.id = d.candidate_id
               WHERE pc.campaign_id = ?
               ORDER BY d.candidate_id, d.depends_on_id""",
            (campaign_id,),
        ).fetchall()
        conflict_rows = conn.execute(
            """SELECT cf.* FROM control_candidate_conflicts cf
               JOIN control_pr_candidates pc ON pc.id = cf.candidate_id
               WHERE pc.campaign_id = ?
               ORDER BY cf.candidate_id, cf.conflicts_with_id""",
            (campaign_id,),
        ).fetchall()
        idea_seed_artifact_rows = conn.execute(
            """SELECT link.idea_seed_id, link.artifact_id,
                      link.relation_type
               FROM control_idea_seed_artifacts link
               JOIN control_artifacts artifact
                 ON artifact.id = link.artifact_id
               WHERE artifact.campaign_id = ?
               ORDER BY link.idea_seed_id, link.artifact_id,
                        link.relation_type""",
            (campaign_id,),
        ).fetchall()
        artifact_relation_rows = conn.execute(
            """SELECT relation.source_artifact_id,
                      relation.target_artifact_id,
                      relation.relation_type
               FROM control_artifact_relations relation
               JOIN control_artifacts source
                 ON source.id = relation.source_artifact_id
               JOIN control_artifacts target
                 ON target.id = relation.target_artifact_id
               WHERE source.campaign_id = ? AND target.campaign_id = ?
               ORDER BY relation.source_artifact_id,
                        relation.target_artifact_id,
                        relation.relation_type""",
            (campaign_id, campaign_id),
        ).fetchall()
        candidate_artifact_rows = conn.execute(
            """SELECT link.candidate_id, link.artifact_id,
                      link.relation_type
               FROM control_candidate_artifacts link
               JOIN control_pr_candidates candidate
                 ON candidate.id = link.candidate_id
               JOIN control_artifacts artifact
                 ON artifact.id = link.artifact_id
               WHERE candidate.campaign_id = ?
                 AND artifact.campaign_id = ?
               ORDER BY link.candidate_id, link.artifact_id,
                        link.relation_type""",
            (campaign_id, campaign_id),
        ).fetchall()

        missing: list[str] = []
        if not str(campaign["goal"] or "").strip():
            missing.append("goal")
        if not str(campaign["non_goals"] or "").strip():
            missing.append("non_goals")
        if not str(campaign["base_sha"] or "").strip():
            missing.append("base_sha")
        if not profile.get("success_metrics"):
            missing.append("success_metrics")

        pivotal_fork = str(profile.get("pivotal_fork") or "").strip()
        pivotal_na_reason = str(
            profile.get("pivotal_fork_na_reason") or ""
        ).strip()
        if not pivotal_fork and not pivotal_na_reason:
            missing.append("pivotal_fork")

        alternatives = profile.get("alternatives") or []
        if len(alternatives) < 2:
            missing.append("alternatives")
        if not str(profile.get("review_strategy") or "").strip():
            missing.append("review_strategy")
        if not str(profile.get("rollout_plan") or "").strip():
            missing.append("rollout_plan")
        if not str(profile.get("rollback_plan") or "").strip():
            missing.append("rollback_plan")

        question_evidence: Dict[str, Dict[str, Any]] = {}
        valid_branches: set[str] = set()
        if not question_rows:
            missing.append("decision_ledger")
        for row in question_rows:
            question_id = str(row["id"])
            status = str(row["status"] or "")
            branch = str(row["branch"] or "").strip().lower()
            rationale = str(row["rationale"] or "").strip()
            owner = str(row["owner"] or "").strip()
            evidence = self._canonical_json(row["evidence_json"], fallback={})
            question_evidence[question_id] = (
                evidence if isinstance(evidence, dict) else {"value": evidence}
            )
            row_valid = status in TERMINAL_QUESTION_STATES
            if not row_valid:
                missing.append(f"question_status:{question_id}")
            if status == "resolved" and not (
                str(row["answer"] or "").strip() or rationale
            ):
                missing.append(f"question_resolution:{question_id}")
                row_valid = False
            if status == "grounded" and not evidence:
                missing.append(f"question_evidence:{question_id}")
                row_valid = False
            if status in UNCERTAINTY_QUESTION_STATES:
                if not rationale:
                    missing.append(f"question_rationale:{question_id}")
                    row_valid = False
                if not owner:
                    missing.append(f"question_owner:{question_id}")
                    row_valid = False
                if status == "discovery-assigned" and not str(
                    (evidence.get("next_step") or "")
                    if isinstance(evidence, dict)
                    else ""
                ).strip():
                    missing.append(f"discovery_next_step:{question_id}")
                    row_valid = False
            if row_valid and branch:
                valid_branches.add(branch)
        if any(
            str(row["status"] or "") not in TERMINAL_QUESTION_STATES
            for row in question_rows
        ):
            missing.append("unresolved_questions")
        for branch in REQUIRED_DECISION_BRANCHES:
            if branch not in valid_branches:
                missing.append(f"branch:{branch}")

        verified_artifacts: Dict[str, list[tuple[Any, Dict[str, Any]]]] = defaultdict(
            list
        )
        for row in artifact_rows:
            content = str(row["content_text"] or "")
            metadata = self._canonical_json(row["metadata_json"], fallback={})
            content_verified = bool(content.strip()) and hashlib.sha256(
                content.encode("utf-8")
            ).hexdigest() == str(row["content_sha256"] or "").strip().lower()
            baseline_verified = isinstance(metadata, dict) and str(
                metadata.get("base_sha") or ""
            ).strip().lower() == str(campaign["base_sha"] or "").strip().lower()
            if content_verified and baseline_verified:
                verified_artifacts[str(row["artifact_type"])].append((row, metadata))
        repository_maps = [
            row
            for row, _metadata in verified_artifacts["repository_map"]
            if str(row["status"]) in {"accepted", "current"}
        ]
        if not repository_maps:
            missing.append("repository_map")
        usable_artifact_statuses = {"proposed", "accepted", "current"}
        depth = str(profile["planning_depth"])
        if depth in {"balanced", "deep", "exhaustive"}:
            if not (
                {
                    str(row["status"])
                    for row, _metadata in verified_artifacts["design_document"]
                }
                & usable_artifact_statuses
            ):
                missing.append("design_document")
        if (
            depth in {"balanced", "deep", "exhaustive"}
            and str(campaign["risk_level"]) in {"high", "critical"}
        ):
            if not (
                {
                    str(row["status"])
                    for row, _metadata in verified_artifacts["adr"]
                }
                & usable_artifact_statuses
            ):
                missing.append("adr")
            if not profile.get("acceptance_matrix"):
                missing.append("acceptance_matrix")

        if not candidate_rows:
            missing.append("pr_candidates")
        if len(candidate_rows) > int(profile["requested_max_candidates"]):
            missing.append("candidate_limit_exceeded")
        for candidate in candidate_rows:
            candidate_id = str(candidate["id"])
            contract = contracts_by_id.get(candidate_id)
            if not contract:
                missing.append(f"candidate_contract:{candidate_id}")
                continue
            try:
                validate_acceptance_criteria(
                    self._canonical_json(
                        candidate["acceptance_criteria_json"], fallback=[]
                    )
                )
            except ControlCenterError:
                missing.append(f"candidate_acceptance_criteria:{candidate_id}")
                missing.append("candidate_acceptance_criteria_invalid")
            required_list_fields = {
                "components": contract["components_json"],
                "required_checks": contract["required_checks_json"],
                "manual_tests": contract["manual_tests_json"],
                "documentation": contract["documentation_json"],
            }
            for field, raw in required_list_fields.items():
                value = self._canonical_json(raw, fallback=[])
                if not isinstance(value, list) or not value:
                    missing.append(f"candidate_{field}:{candidate_id}")
            required_text_fields = {
                "non_goals": candidate["non_goals"],
                "purpose": contract["purpose"],
                "expected_diff_type": contract["expected_diff_type"],
                "reversibility": contract["reversibility"],
                "migration_plan": contract["migration_plan"],
                "compatibility_plan": contract["compatibility_plan"],
                "definition_of_done": contract["definition_of_done"],
            }
            for field, value in required_text_fields.items():
                if not str(value or "").strip():
                    missing.append(f"candidate_{field}:{candidate_id}")

        try:
            current_sha = self._resolve_sha(
                project,
                str(campaign["base_sha"] or ""),
                require=True,
            )
            if current_sha != str(campaign["base_sha"] or "").lower():
                missing.append("stale_base_sha")
        except ControlCenterError as exc:
            missing.append(exc.code)

        simulation = None
        if candidate_rows and len(contracts_by_id) == len(candidate_rows):
            try:
                simulation = self._simulate_campaign_in_connection(
                    conn,
                    campaign_id,
                    persist=False,
                )
            except ControlCenterError as exc:
                missing.append(exc.code)
        if simulation is None:
            missing.append("plan_simulation")
        if depth in {"balanced", "deep", "exhaustive"}:
            expected_simulation_hash = (
                canonical_json_sha256(simulation) if simulation is not None else ""
            )

            def simulation_metadata_matches(metadata: Dict[str, Any]) -> bool:
                try:
                    artifact_campaign_version = int(
                        metadata.get("campaign_version") or 0
                    )
                except (TypeError, ValueError):
                    return False
                return (
                    artifact_campaign_version == int(campaign["version"])
                    and str(
                        metadata.get("simulation_sha256") or ""
                    ).strip().lower()
                    == expected_simulation_hash
                )

            valid_simulation_artifacts = [
                row
                for row, metadata in verified_artifacts["plan_simulation"]
                if str(row["status"]) in usable_artifact_statuses
                and simulation_metadata_matches(metadata)
            ]
            if not valid_simulation_artifacts:
                missing.append("plan_simulation_artifact")

        gate_keys = {
            "outcome_contract": {"goal", "non_goals", "success_metrics", "acceptance_matrix"},
            "pivotal_fork": {"pivotal_fork", "adr"},
            "repository_grounding": {
                "base_sha",
                "sha_required",
                "stale_base_sha",
                "repository_map",
                "design_document",
            },
            "decision_ledger": {"decision_ledger"},
            "alternatives_tradeoffs": {"alternatives"},
            "candidate_contracts": {"pr_candidates", "candidate_limit_exceeded"},
            "dependency_conflict_simulation": {
                "plan_simulation",
                "plan_simulation_artifact",
                "cyclic_pr_dependencies",
                "cross_campaign_dependency",
                "candidate_contract_required",
            },
            "verification_release": {"review_strategy", "rollout_plan", "rollback_plan"},
        }
        gate_missing: Dict[str, list[str]] = {key: [] for key in gate_keys}
        for item in sorted(set(missing)):
            if item == "unresolved_questions" or item.startswith(
                ("question_", "discovery_next_step:", "branch:")
            ):
                gate_missing["decision_ledger"].append(item)
            elif item.startswith("candidate_"):
                gate_missing["candidate_contracts"].append(item)
                if item.startswith(("candidate_required_checks:", "candidate_manual_tests:")):
                    gate_missing["verification_release"].append(item)
            else:
                matched = False
                for gate_key, exact_keys in gate_keys.items():
                    if item in exact_keys:
                        gate_missing[gate_key].append(item)
                        matched = True
                if not matched:
                    gate_missing["dependency_conflict_simulation"].append(item)

        evidence_by_gate: Dict[str, list[str]] = {
            "outcome_contract": [
                f"{len(profile.get('success_metrics') or [])} success metrics"
            ],
            "pivotal_fork": (
                ["pivotal_fork"] if pivotal_fork else ["explicit_not_applicable"]
            ),
            "repository_grounding": [
                f"{row['id']}:{row['content_sha256']}" for row in repository_maps
            ],
            "decision_ledger": [
                f"{len(question_rows)} ledger entries",
                *[f"branch:{branch}" for branch in sorted(valid_branches)],
            ],
            "alternatives_tradeoffs": [f"{len(alternatives)} alternatives"],
            "candidate_contracts": [f"{len(candidate_rows)} candidate contracts"],
            "dependency_conflict_simulation": (
                [
                    f"{simulation['candidate_count']} simulated candidates",
                    f"{len(simulation['conflicts'])} declared conflicts",
                ]
                if simulation
                else []
            ),
            "verification_release": [
                f"{sum(len(self._canonical_json(row['required_checks_json'], fallback=[])) for row in contract_rows)} required checks"
            ],
        }
        gates = [
            {
                "key": key,
                "passed": not gate_missing[key],
                "missing": gate_missing[key],
                "evidence": evidence_by_gate[key] if not gate_missing[key] else [],
            }
            for key in gate_keys
        ]
        all_gates_passed = all(gate["passed"] for gate in gates)
        passed_gates = sum(1 for gate in gates if gate["passed"])
        score = round(passed_gates / len(gates) * 100, 1)

        def canonical_row(row, *, json_fields=(), excluded=()):
            value = {
                key: row[key]
                for key in row.keys()
                if key not in excluded and not str(key).endswith("_at")
            }
            for field in json_fields:
                value[field.removesuffix("_json")] = self._canonical_json(
                    value.pop(field, None),
                    fallback={} if field in {"evidence_json", "metadata_json"} else [],
                )
            return value

        signature_source = {
            "signature_version": PLAN_SIGNATURE_VERSION,
            "campaign": canonical_row(
                campaign,
                excluded=("status", "approved_version", "approved_sha", "approved_by"),
            ),
            "profile": canonical_row(
                profile_row,
                json_fields=(
                    "success_metrics_json",
                    "constraints_json",
                    "assumptions_json",
                    "acceptance_matrix_json",
                    "alternatives_json",
                ),
                excluded=(
                    "readiness_status",
                    "readiness_score",
                    "plan_signature",
                    "current_wave",
                    "actual_cost",
                    "started_at",
                    "completed_at",
                ),
            ),
            "ledger": [
                canonical_row(
                    row,
                    json_fields=("evidence_json",),
                    excluded=("amendment_id",),
                )
                for row in question_rows
            ],
            "artifacts": [
                canonical_row(
                    row,
                    json_fields=("metadata_json",),
                    excluded=(
                        "content_text",
                        "materialization_status",
                        "materialized_sha256",
                        "materialized_commit_sha",
                        "materialized_at",
                    ),
                )
                for row in artifact_rows
            ],
            "knowledge_relations": {
                "idea_seed_artifacts": [
                    dict(row) for row in idea_seed_artifact_rows
                ],
                "artifact_relations": [
                    dict(row) for row in artifact_relation_rows
                ],
                "candidate_artifacts": [
                    dict(row) for row in candidate_artifact_rows
                ],
            },
            "candidates": [
                canonical_row(row, json_fields=("acceptance_criteria_json",))
                for row in candidate_rows
            ],
            "contracts": [
                canonical_row(
                    row,
                    json_fields=(
                        "components_json",
                        "required_checks_json",
                        "manual_tests_json",
                        "documentation_json",
                    ),
                    excluded=("wave",),
                )
                for row in contract_rows
            ],
            "dependencies": [dict(row) for row in dependency_rows],
            "conflicts": [
                canonical_row(row, json_fields=("resources_json",))
                for row in conflict_rows
            ],
            "simulation": simulation,
        }
        signature = hashlib.sha256(
            json.dumps(
                signature_source,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        historical_approval = (
            str(campaign["status"]) != "draft"
            and campaign["approved_version"] is not None
        )
        ready = all_gates_passed or historical_approval
        status = "approved" if historical_approval else "ready" if ready else "blocked"
        if persist and str(campaign["status"]) == "draft":
            conn.execute(
                """UPDATE control_campaign_profiles
                   SET readiness_status = ?, readiness_score = ?,
                       plan_signature = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE campaign_id = ?""",
                (status, score, signature, campaign_id),
            )
        return {
            "campaign_id": campaign_id,
            "ready": ready,
            "status": status,
            "score": score,
            "missing": sorted(set(missing)),
            "gates": gates,
            "plan_signature": signature,
            "plan_signature_version": PLAN_SIGNATURE_VERSION,
            "simulation": simulation,
            "grandfathered_approval": historical_approval,
        }

    def evaluate_campaign_readiness(
        self,
        campaign_id: str,
        *,
        persist: bool = True,
    ) -> Dict[str, Any]:
        with self.db._get_connection() as conn:
            result = self._evaluate_campaign_readiness_in_connection(
                conn,
                campaign_id,
                persist=persist,
            )
            if persist:
                conn.commit()
            return result
