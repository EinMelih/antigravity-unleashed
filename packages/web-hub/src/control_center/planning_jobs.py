"""Read-only Anti-Gravity planning jobs and atomic generated-plan import."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any, Dict, Optional

from src.control_center.common import (
    ACTIVATION_POLICIES,
    PLANNING_DEPTHS,
    RISK_LEVELS,
    ControlCenterError,
    canonical_json_sha256,
    clean_text,
    public_id,
    validate_acceptance_criteria,
)
from src.control_center.planning import (
    DEPTH_DEFAULT_LIMITS,
    REQUIRED_DECISION_BRANCHES,
)


PLANNING_JOB_STATES = {
    "queued",
    "running",
    "waiting_human",
    "completed",
    "failed",
    "cancelled",
}

PLANNING_JOB_CANCELLABLE_STATES = {
    "queued",
    "running",
    "waiting_human",
    "failed",
}

PLANNER_BRANCH_STATES = {
    "resolved",
    "grounded",
    "assumption-accepted",
    "discovery-assigned",
    "deferred",
}

GENERATED_SCORE_FIELDS = (
    "business_value",
    "unblock_score",
    "learning_value",
    "urgency_score",
    "effort_score",
    "change_risk_score",
    "reversibility_score",
)


class PlanningJobMixin:
    @staticmethod
    def _require_repository_read_capability(policy: Dict[str, Any]) -> None:
        if not bool((policy.get("capability") or {}).get("read_repository")):
            raise ControlCenterError(
                "Der Planner darf dieses Repository laut Policy nicht lesen.",
                code="planning_read_repository_denied",
                status=403,
            )

    def assert_planning_dispatch_allowed(self, job_id: str) -> None:
        """Recheck the live job and repository policy at the dispatch boundary."""
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            job = conn.execute(
                "SELECT * FROM control_planning_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if not job:
                raise ControlCenterError(
                    "Planning-Job nicht gefunden.",
                    code="planning_job_not_found",
                    status=404,
                )
            if str(job["status"]) != "running":
                raise ControlCenterError(
                    "Planning-Job ist nicht aktiv.",
                    code="planning_job_not_running",
                    status=409,
                )
            policy = self._repository_policy_in_connection(
                conn,
                int(job["project_id"]),
            )
            self._require_repository_read_capability(policy)
            if str(job["job_type"] or "") == "plan_amendment":
                amendment = self._get_plan_amendment_in_connection(
                    conn,
                    str(job["amendment_id"] or ""),
                )
                if amendment["status"] != "planning":
                    raise ControlCenterError(
                        "Dieses Amendment erwartet keinen Planner-Dispatch.",
                        code="amendment_not_planning",
                        status=409,
                    )
                self._assert_amendment_source_in_connection(conn, amendment)
            conn.commit()

    @staticmethod
    def _normalize_grounded_path(value: Any) -> str:
        raw = str(value or "").strip()
        normalized = raw.replace("\\", "/")
        path = PurePosixPath(normalized)
        if (
            not normalized
            or "\x00" in normalized
            or normalized.startswith("//")
            or path.is_absolute()
            or re.match(r"^[A-Za-z]:", normalized)
            or ".." in path.parts
        ):
            raise ControlCenterError(
                "Grounding-Pfade müssen sichere Repository-relative Pfade sein.",
                code="invalid_grounded_path",
            )
        return path.as_posix()

    @staticmethod
    def _contains_invalid_evidence_sentinel(value: Any) -> bool:
        if isinstance(value, dict):
            return "invalid_json" in value or any(
                PlanningJobMixin._contains_invalid_evidence_sentinel(item)
                for item in value.values()
            )
        if isinstance(value, list):
            return any(
                PlanningJobMixin._contains_invalid_evidence_sentinel(item)
                for item in value
            )
        return False

    @staticmethod
    def _contains_grounded_symbol(content: str, symbol: str) -> bool:
        return bool(
            re.search(
                rf"(?<![A-Za-z0-9_$]){re.escape(symbol)}(?![A-Za-z0-9_$])",
                content,
            )
        )

    @staticmethod
    def _repository_map_contains_path(repository_map: str, path: str) -> bool:
        return bool(
            re.search(
                rf"(?<![A-Za-z0-9_./-]){re.escape(path)}(?![A-Za-z0-9_./-])",
                repository_map,
            )
        )

    def _validate_generated_branch_assessments(
        self,
        plan: Dict[str, Any],
        project: Dict[str, Any],
        base_sha: str,
    ) -> tuple[list[Dict[str, Any]], list[str]]:
        assessments = plan.get("branch_assessments") or []
        assessment_branches = [
            str(assessment.get("branch") or "").strip().lower()
            if isinstance(assessment, dict)
            else ""
            for assessment in assessments
        ] if isinstance(assessments, list) else []
        if (
            len(assessment_branches) != len(REQUIRED_DECISION_BRANCHES)
            or sorted(assessment_branches) != sorted(REQUIRED_DECISION_BRANCHES)
        ):
            raise ControlCenterError(
                "Jeder Pflicht-Branch muss genau einmal bewertet werden.",
                code="invalid_branch_assessment_set",
            )

        normalized_assessments: list[Dict[str, Any]] = []
        grounded_paths: list[str] = []
        for assessment in assessments:
            branch = str(assessment.get("branch") or "").strip().lower()
            status = str(assessment.get("status") or "").strip()
            if status not in PLANNER_BRANCH_STATES:
                raise ControlCenterError(
                    "Ein finaler Planner-Branch hat einen ungültigen Status.",
                    code="invalid_branch_assessment_status",
                )
            evidence = assessment.get("evidence") or {}
            if (
                not isinstance(evidence, dict)
                or self._contains_invalid_evidence_sentinel(evidence)
            ):
                raise ControlCenterError(
                    "Branch-Evidence ist nicht valide strukturiert.",
                    code="invalid_branch_assessment_evidence",
                )
            rationale = str(assessment.get("rationale") or "").strip()
            owner = str(assessment.get("owner") or "").strip()
            answer = str(assessment.get("answer") or "").strip()
            normalized_evidence = dict(evidence)
            if status == "resolved" and not answer:
                raise ControlCenterError(
                    "Ein resolved Planner-Branch benötigt eine explizite Antwort.",
                    code="invalid_branch_assessment_resolution",
                )
            if status in {
                "assumption-accepted",
                "discovery-assigned",
                "deferred",
            }:
                if not rationale or not owner:
                    raise ControlCenterError(
                        "Unsichere Branch-Dispositionen benötigen Rationale und Owner.",
                        code="invalid_branch_assessment_uncertainty",
                    )
                if status == "discovery-assigned" and not str(
                    evidence.get("next_step") or ""
                ).strip():
                    raise ControlCenterError(
                        "Discovery benötigt einen belegten nächsten Schritt.",
                        code="invalid_branch_assessment_discovery",
                    )
                if status == "deferred" and evidence.get("not_applicable") is not True:
                    raise ControlCenterError(
                        "Deferred ist nur als explizit belegtes N/A zulässig.",
                        code="invalid_branch_assessment_deferred",
                    )
            if status == "grounded":
                relative_path = self._normalize_grounded_path(evidence.get("path"))
                content = self.repository_reader(project, base_sha, relative_path)
                if content is None:
                    raise ControlCenterError(
                        "Der Grounding-Pfad existiert nicht im gepinnten Commit.",
                        code="planning_grounded_path_not_found",
                    )
                symbol_value = evidence.get("symbol")
                if symbol_value is not None:
                    symbol = str(symbol_value).strip()
                    if not symbol:
                        raise ControlCenterError(
                            "Ein angegebenes Grounding-Symbol darf nicht leer sein.",
                            code="invalid_branch_assessment_evidence",
                        )
                    if not self._contains_grounded_symbol(content, symbol):
                        raise ControlCenterError(
                            "Das Grounding-Symbol fehlt im gepinnten Repository-Blob.",
                            code="planning_grounded_symbol_not_found",
                        )
                    normalized_evidence["symbol"] = symbol
                normalized_evidence.update(
                    {
                        "path": relative_path,
                        "pinned_sha": base_sha,
                        "blob_sha256": hashlib.sha256(
                            content.encode("utf-8")
                        ).hexdigest(),
                    }
                )
                if relative_path not in grounded_paths:
                    grounded_paths.append(relative_path)
            normalized_assessments.append(
                {
                    **assessment,
                    "branch": branch,
                    "status": status,
                    "evidence": normalized_evidence,
                }
            )
        if not grounded_paths:
            raise ControlCenterError(
                "Mindestens ein Branch muss am gepinnten Repository geerdet sein.",
                code="grounded_branch_required",
            )
        repository_map = str(plan.get("repository_map") or "")
        missing_paths = [
            path
            for path in grounded_paths
            if not self._repository_map_contains_path(repository_map, path)
        ]
        if missing_paths:
            raise ControlCenterError(
                "Die Repository-Map enthält nicht alle verifizierten Grounding-Pfade.",
                code="repository_map_grounding_missing",
            )
        return normalized_assessments, grounded_paths

    def create_planning_job(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        requested_seed_id = str(payload.get("idea_seed_id") or "").strip()
        existing_seed = (
            self.get_idea_seed(requested_seed_id)
            if requested_seed_id
            else None
        )
        project_id = (
            existing_seed["project_id"]
            if existing_seed
            else payload.get("project_id")
        )
        project = self._project(project_id)
        if (
            existing_seed
            and payload.get("project_id") not in (None, "")
            and int(payload["project_id"]) != int(existing_seed["project_id"])
        ):
            raise ControlCenterError(
                "Idea Seed und Projekt passen nicht zusammen.",
                code="idea_seed_project_mismatch",
                status=409,
            )
        wish = clean_text(
            payload.get("wish") or (existing_seed or {}).get("note"),
            "wish",
            minimum=10,
            maximum=50000,
        )
        depth = str(payload.get("planning_depth") or "balanced").strip().lower()
        if depth not in PLANNING_DEPTHS:
            raise ControlCenterError(
                "Unbekannter Planungsgrad.",
                code="invalid_planning_depth",
            )
        try:
            maximum = int(
                payload.get("max_candidates", DEPTH_DEFAULT_LIMITS[depth])
            )
        except (TypeError, ValueError) as exc:
            raise ControlCenterError(
                "max_candidates muss eine Zahl sein.",
                code="invalid_max_candidates",
            ) from exc
        policy = self.get_repository_policy(project["id"])
        self._require_repository_read_capability(policy)
        maximum = min(maximum, int(policy["max_candidates"]), 100)
        if not 1 <= maximum <= 100:
            raise ControlCenterError(
                "max_candidates muss zwischen 1 und 100 liegen.",
                code="invalid_max_candidates",
            )
        activation = str(
            payload.get("activation_policy") or "per_candidate"
        ).strip()
        if activation not in ACTIVATION_POLICIES:
            raise ControlCenterError(
                "Unbekannte Aktivierungs-Policy.",
                code="invalid_activation_policy",
            )
        constraints = payload.get("constraints") or []
        if isinstance(constraints, str):
            constraints = [
                line.strip() for line in constraints.splitlines() if line.strip()
            ]
        if not isinstance(constraints, list):
            raise ControlCenterError(
                "constraints muss eine Liste sein.",
                code="invalid_constraints",
            )
        actor = clean_text(payload.get("actor") or "human", "actor", maximum=120)
        title = str(
            payload.get("title")
            or (existing_seed or {}).get("title")
            or wish.splitlines()[0]
        )[:200]
        seed_id = requested_seed_id or public_id("IDEA")
        job_id = public_id("PLAN")
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            active = conn.execute(
                """SELECT id FROM control_planning_jobs
                   WHERE project_id = ? AND status IN ('queued', 'running')""",
                (int(project["id"]),),
            ).fetchone()
            if active:
                raise ControlCenterError(
                    "Für dieses Repository läuft bereits ein Planning-Job.",
                    code="planning_job_already_active",
                    status=409,
                )
            if requested_seed_id:
                seed = conn.execute(
                    "SELECT * FROM control_idea_seeds WHERE id = ?",
                    (requested_seed_id,),
                ).fetchone()
                if not seed:
                    raise ControlCenterError(
                        "Idea Seed nicht gefunden.",
                        code="idea_seed_not_found",
                        status=404,
                    )
                if str(seed["status"]) not in {"inbox", "deferred"}:
                    raise ControlCenterError(
                        "Dieser Idea Seed kann gerade nicht geplant werden.",
                        code="idea_seed_not_plannable",
                        status=409,
                    )
                provenance = json.loads(seed["provenance_json"] or "{}")
                provenance["planning_job_id"] = job_id
                conn.execute(
                    """UPDATE control_idea_seeds
                       SET status = 'planning', provenance_json = ?,
                           updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND status IN ('inbox', 'deferred')""",
                    (json.dumps(provenance, ensure_ascii=False), seed_id),
                )
                seed_from_state = str(seed["status"])
            else:
                conn.execute(
                    """INSERT INTO control_idea_seeds (
                           id, project_id, title, note, source, status,
                           provenance_json
                       ) VALUES (?, ?, ?, ?, ?, 'planning', ?)""",
                    (
                        seed_id,
                        int(project["id"]),
                        title,
                        wish,
                        actor,
                        json.dumps(
                            {"planning_job_id": job_id},
                            ensure_ascii=False,
                        ),
                    ),
                )
                seed_from_state = "inbox"
            conn.execute(
                """INSERT INTO control_planning_jobs (
                       id, project_id, idea_seed_id, planning_depth,
                       max_candidates, activation_policy, wish,
                       constraints_json, created_by
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job_id,
                    int(project["id"]),
                    seed_id,
                    depth,
                    maximum,
                    activation,
                    wish,
                    json.dumps(
                        [str(item)[:2000] for item in constraints],
                        ensure_ascii=False,
                    ),
                    actor,
                ),
            )
            self._audit(
                conn,
                project_id=int(project["id"]),
                entity_type="planning_job",
                entity_id=job_id,
                action="planning_job.queued",
                actor=actor,
                to_state="queued",
                evidence={"depth": depth, "max_candidates": maximum},
            )
            self._audit(
                conn,
                project_id=int(project["id"]),
                entity_type="idea_seed",
                entity_id=seed_id,
                action="idea_seed.planning_started",
                actor=actor,
                from_state=seed_from_state,
                to_state="planning",
                evidence={"planning_job_id": job_id},
            )
            conn.commit()
        return self.get_planning_job(job_id)

    def get_planning_job(self, job_id: str) -> Dict[str, Any]:
        with self.db._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM control_planning_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        if not row:
            raise ControlCenterError(
                "Planning-Job nicht gefunden.",
                code="planning_job_not_found",
                status=404,
            )
        return self._row(row, ("constraints_json", "output_json"))

    def list_planning_jobs(self, project_id: Any = None) -> list[Dict[str, Any]]:
        query = "SELECT * FROM control_planning_jobs"
        params: tuple[Any, ...] = ()
        if project_id not in (None, ""):
            project = self._project(project_id)
            query += " WHERE project_id = ?"
            params = (int(project["id"]),)
        query += " ORDER BY created_at DESC"
        with self.db._get_connection() as conn:
            return [
                self._row(row, ("constraints_json", "output_json"))
                for row in conn.execute(query, params).fetchall()
            ]

    def claim_planning_job(self) -> Optional[Dict[str, Any]]:
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT * FROM control_planning_jobs
                   WHERE status = 'queued'
                   ORDER BY created_at ASC LIMIT 1"""
            ).fetchone()
            if not row:
                conn.commit()
                return None
            policy = self._repository_policy_in_connection(
                conn,
                int(row["project_id"]),
            )
            self._require_repository_read_capability(policy)
            continuation = bool(
                str(row["antigravity_chat_id"] or "").strip()
                and str(row["campaign_id"] or "").strip()
                and str(row["active_question_id"] or "").strip()
            )
            session_questions = []
            if str(row["campaign_id"] or "").strip():
                session_questions = [
                    self._row(question, ("evidence_json",))
                    for question in conn.execute(
                        """SELECT * FROM control_question_ledger
                           WHERE planning_job_id = ?
                           ORDER BY created_at ASC, id ASC""",
                        (row["id"],),
                    ).fetchall()
                ]
            updated = conn.execute(
                """UPDATE control_planning_jobs
                   SET status = 'running', attempt = attempt + ?,
                       started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = 'queued'""",
                (0 if continuation else 1, row["id"]),
            )
            if updated.rowcount != 1:
                conn.rollback()
                return None
            conn.commit()
        claimed = self.get_planning_job(str(row["id"]))
        claimed["continuation"] = continuation
        claimed["session_questions"] = session_questions
        if str(claimed.get("job_type") or "") == "plan_amendment":
            claimed["amendment"] = self.get_plan_amendment(
                str(claimed.get("amendment_id") or "")
            )
        return claimed

    def update_planning_job_chat(self, job_id: str, chat_id: str) -> None:
        with self.db._get_connection() as conn:
            updated = conn.execute(
                """UPDATE control_planning_jobs
                   SET antigravity_chat_id = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = 'running'""",
                (str(chat_id)[:200], job_id),
            )
            if updated.rowcount != 1:
                conn.rollback()
                raise ControlCenterError(
                    "Planning-Job ist nicht aktiv.",
                    code="planning_job_not_running",
                    status=409,
                )
            conn.commit()

    def cancel_planning_job(
        self,
        job_id: str,
        *,
        actor: str = "human",
        reason: str = "",
    ) -> Dict[str, Any]:
        actor_name = clean_text(actor, "actor", maximum=120)
        explanation = str(reason or "").strip()
        if len(explanation) > 2000:
            raise ControlCenterError(
                "reason darf höchstens 2000 Zeichen enthalten.",
                code="reason_too_long",
            )
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM control_planning_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if not row:
                raise ControlCenterError(
                    "Planning-Job nicht gefunden.",
                    code="planning_job_not_found",
                    status=404,
                )
            current_status = str(row["status"])
            if current_status == "cancelled":
                conn.commit()
                return self._row(row, ("constraints_json", "output_json"))
            if current_status not in PLANNING_JOB_CANCELLABLE_STATES:
                raise ControlCenterError(
                    "Dieser Planning-Job kann nicht mehr abgebrochen werden.",
                    code="planning_job_not_cancellable",
                    status=409,
                )
            updated = conn.execute(
                """UPDATE control_planning_jobs
                   SET status = 'cancelled', finished_at = CURRENT_TIMESTAMP,
                       waiting_reason = '', active_question_id = NULL,
                       last_error = CASE WHEN status = 'failed'
                           THEN last_error ELSE '' END,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = ?""",
                (job_id, current_status),
            )
            if updated.rowcount != 1:
                conn.rollback()
                raise ControlCenterError(
                    "Der Planning-Job wurde parallel verändert.",
                    code="planning_job_cancel_conflict",
                    status=409,
                )
            self._audit(
                conn,
                project_id=int(row["project_id"]),
                entity_type="planning_job",
                entity_id=job_id,
                action="planning_job.cancelled",
                actor=actor_name,
                from_state=current_status,
                to_state="cancelled",
                reason=explanation,
            )
            if str(row["job_type"] or "") == "plan_amendment":
                self._cancel_amendment_for_job_in_connection(
                    conn,
                    row,
                    actor=actor_name,
                    reason=explanation,
                )
                conn.commit()
                return self.get_planning_job(job_id)
            campaign_id = str(row["campaign_id"] or "").strip()
            if campaign_id:
                campaign = conn.execute(
                    "SELECT * FROM control_campaigns WHERE id = ?",
                    (campaign_id,),
                ).fetchone()
                candidate_count = conn.execute(
                    """SELECT COUNT(*) AS count FROM control_pr_candidates
                       WHERE campaign_id = ?""",
                    (campaign_id,),
                ).fetchone()
                if (
                    campaign
                    and str(campaign["status"]) == "draft"
                    and int(candidate_count["count"]) == 0
                ):
                    conn.execute(
                        """UPDATE control_campaigns
                           SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
                           WHERE id = ? AND status = 'draft'""",
                        (campaign_id,),
                    )
                    conn.execute(
                        """UPDATE control_campaign_profiles
                           SET readiness_status = 'cancelled',
                               updated_at = CURRENT_TIMESTAMP
                           WHERE campaign_id = ?""",
                        (campaign_id,),
                    )
                    conn.execute(
                        """UPDATE control_attention_items
                           SET status = 'resolved',
                               resolved_at = CURRENT_TIMESTAMP
                           WHERE status = 'open'
                             AND (
                                 (entity_type = 'campaign' AND entity_id = ?)
                                 OR (
                                     entity_type = 'planning_question'
                                     AND entity_id IN (
                                         SELECT id FROM control_question_ledger
                                         WHERE planning_job_id = ?
                                     )
                                 )
                             )""",
                        (campaign_id, job_id),
                    )
                    self._audit(
                        conn,
                        project_id=int(row["project_id"]),
                        entity_type="campaign",
                        entity_id=campaign_id,
                        action="campaign.cancelled",
                        actor=actor_name,
                        from_state="draft",
                        to_state="cancelled",
                        reason=explanation,
                        evidence={
                            "planning_job_id": job_id,
                            "empty_session_shell": True,
                            "no_external_mutations": True,
                        },
                    )
            conn.execute(
                """UPDATE control_idea_seeds
                   SET status = 'inbox', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = 'planning'""",
                (row["idea_seed_id"],),
            )
            conn.commit()
        return self.get_planning_job(job_id)

    def fail_planning_job(self, job_id: str, error: str) -> Dict[str, Any]:
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM control_planning_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if not row:
                raise ControlCenterError(
                    "Planning-Job nicht gefunden.",
                    code="planning_job_not_found",
                    status=404,
                )
            current_status = str(row["status"])
            if current_status == "failed":
                conn.commit()
                return self._row(row, ("constraints_json", "output_json"))
            if current_status != "running":
                raise ControlCenterError(
                    "Planning-Job ist nicht aktiv.",
                    code="planning_job_not_running",
                    status=409,
                )
            updated = conn.execute(
                """UPDATE control_planning_jobs
                   SET status = 'failed', last_error = ?,
                       finished_at = CURRENT_TIMESTAMP,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = 'running'""",
                (self._redact_diagnostic(error), job_id),
            )
            if updated.rowcount != 1:
                conn.rollback()
                raise ControlCenterError(
                    "Der Planning-Job wurde parallel verändert.",
                    code="planning_job_not_running",
                    status=409,
                )
            self._audit(
                conn,
                project_id=int(row["project_id"]),
                entity_type="planning_job",
                entity_id=job_id,
                action="planning_job.failed",
                actor="planner",
                from_state="running",
                to_state="failed",
                reason=str(error)[:5000],
            )
            if str(row["job_type"] or "") == "plan_amendment":
                self._set_amendment_job_state_in_connection(conn, row, "failed")
            else:
                conn.execute(
                    """UPDATE control_idea_seeds
                       SET status = 'inbox', updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND status = 'planning'""",
                    (row["idea_seed_id"],),
                )
            conn.commit()
        return self.get_planning_job(job_id)

    def retry_planning_job(
        self,
        job_id: str,
        *,
        actor: str = "human",
    ) -> Dict[str, Any]:
        actor_name = clean_text(actor, "actor", maximum=120)
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            job = conn.execute(
                "SELECT * FROM control_planning_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if not job:
                raise ControlCenterError(
                    "Planning-Job nicht gefunden.",
                    code="planning_job_not_found",
                    status=404,
                )
            if str(job["status"]) != "failed":
                raise ControlCenterError(
                    "Nur fehlgeschlagene Planning-Jobs können wiederholt werden.",
                    code="planning_job_not_failed",
                    status=409,
                )
            policy = self._repository_policy_in_connection(
                conn,
                int(job["project_id"]),
            )
            self._require_repository_read_capability(policy)
            maximum_retries = int(policy["max_retry_attempts"])
            attempt = int(job["attempt"])
            if attempt > maximum_retries:
                raise ControlCenterError(
                    "Das Planning-Retry-Limit ist erreicht.",
                    code="planning_retry_limit",
                    status=409,
                )
            updated = conn.execute(
                """UPDATE control_planning_jobs
                   SET status = 'queued', last_error = '',
                       antigravity_chat_id = '', finished_at = NULL,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = 'failed'""",
                (job_id,),
            )
            if updated.rowcount != 1:
                conn.rollback()
                raise ControlCenterError(
                    "Der Planning-Job wurde parallel verändert.",
                    code="planning_job_not_failed",
                    status=409,
                )
            self._audit(
                conn,
                project_id=int(job["project_id"]),
                entity_type="planning_job",
                entity_id=job_id,
                action="planning_job.retried",
                actor=actor_name,
                from_state="failed",
                to_state="queued",
                evidence={
                    "attempt": attempt,
                    "max_retry_attempts": maximum_retries,
                },
            )
            if str(job["job_type"] or "") == "plan_amendment":
                self._set_amendment_job_state_in_connection(conn, job, "planning")
            else:
                conn.execute(
                    """UPDATE control_idea_seeds
                       SET status = 'planning', updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND status = 'inbox'""",
                    (job["idea_seed_id"],),
                )
            conn.commit()
        return self.get_planning_job(job_id)

    def recover_interrupted_planning_jobs(self) -> int:
        """Fail safely after a Hub restart and preserve one retry attempt."""
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """SELECT * FROM control_planning_jobs
                   WHERE status = 'running'"""
            ).fetchall()
            recovered = 0
            for row in rows:
                continuation = bool(
                    str(row["antigravity_chat_id"] or "").strip()
                    and str(row["campaign_id"] or "").strip()
                    and str(row["active_question_id"] or "").strip()
                )
                reason = (
                    "Der Hub wurde während der Planung neu gestartet. "
                    "Der Lauf wurde sicher beendet und kann erneut geplant werden."
                )
                updated = conn.execute(
                    """UPDATE control_planning_jobs
                       SET status = 'failed',
                           attempt = MAX(attempt - ?, 0),
                           last_error = ?,
                           finished_at = CURRENT_TIMESTAMP,
                           updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND status = 'running'""",
                    (0 if continuation else 1, reason, row["id"]),
                )
                if updated.rowcount != 1:
                    continue
                recovered += 1
                self._audit(
                    conn,
                    project_id=int(row["project_id"]),
                    entity_type="planning_job",
                    entity_id=str(row["id"]),
                    action="planning_job.recovered_after_restart",
                    actor="orchestrator",
                    from_state="running",
                    to_state="failed",
                    reason=reason,
                    evidence={
                        "chat_id": str(row["antigravity_chat_id"] or ""),
                        "attempt_refunded": not continuation,
                        "continuation": continuation,
                    },
                )
                if str(row["job_type"] or "") == "plan_amendment":
                    self._set_amendment_job_state_in_connection(
                        conn,
                        row,
                        "failed",
                    )
                else:
                    conn.execute(
                        """UPDATE control_idea_seeds
                           SET status = 'inbox', updated_at = CURRENT_TIMESTAMP
                           WHERE id = ? AND status = 'planning'""",
                        (row["idea_seed_id"],),
                    )
            conn.commit()
        return recovered

    def _record_planning_question(
        self,
        job_id: str,
        envelope: Dict[str, Any],
    ) -> Dict[str, Any]:
        question_payload = envelope.get("question")
        unexpected_fields = set(envelope) - {"type", "question"}
        if (
            not isinstance(question_payload, dict)
            or unexpected_fields
        ):
            raise ControlCenterError(
                "Eine Question-Envelope muss genau eine Frage enthalten.",
                code="invalid_planning_question_envelope",
            )
        branch = clean_text(
            question_payload.get("branch"),
            "branch",
            maximum=120,
        )
        question = clean_text(
            question_payload.get("question"),
            "question",
            minimum=5,
            maximum=5000,
        )
        rationale = str(question_payload.get("rationale") or "").strip()[:5000]
        evidence = question_payload.get("evidence") or {}
        if not isinstance(evidence, dict):
            raise ControlCenterError(
                "evidence muss ein Objekt sein.",
                code="invalid_question_evidence",
            )
        normalized_question = " ".join(question.casefold().split())
        content_hash = hashlib.sha256(
            normalized_question.encode("utf-8")
        ).hexdigest()
        job = self.get_planning_job(job_id)
        if job["status"] != "running":
            raise ControlCenterError(
                "Planning-Job ist nicht aktiv.",
                code="planning_job_not_running",
                status=409,
            )
        project = self._project(job["project_id"])
        base_sha = self._resolve_sha(project, require=True)
        question_id = public_id("Q")
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            locked_job = conn.execute(
                "SELECT * FROM control_planning_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if not locked_job or str(locked_job["status"]) != "running":
                conn.rollback()
                raise ControlCenterError(
                    "Planning-Job ist nicht aktiv.",
                    code="planning_job_not_running",
                    status=409,
                )
            job = self._row(
                locked_job,
                ("constraints_json", "output_json"),
            )
            amendment_mode = str(job.get("job_type") or "") == "plan_amendment"
            amendment_id = (
                str(job.get("amendment_id") or "") if amendment_mode else ""
            )
            campaign_id = str(job.get("campaign_id") or "")
            campaign_created = not bool(campaign_id)
            if campaign_id:
                campaign = self._campaign(conn, campaign_id)
                expected_status = "paused" if amendment_mode else "draft"
                if str(campaign["status"]) != expected_status:
                    conn.rollback()
                    raise ControlCenterError(
                        "Die Planning-Session-Campaign ist nicht mehr editierbar.",
                        code="planning_session_campaign_locked",
                        status=409,
                    )
                if amendment_mode:
                    amendment = self._get_plan_amendment_in_connection(
                        conn,
                        amendment_id,
                    )
                    if amendment["status"] != "planning":
                        raise ControlCenterError(
                            "Dieses Amendment erwartet keine weitere Rückfrage.",
                            code="amendment_not_planning",
                            status=409,
                        )
            else:
                if amendment_mode:
                    raise ControlCenterError(
                        "Amendment-Planning benötigt eine gebundene Campaign.",
                        code="amendment_campaign_missing",
                        status=409,
                    )
                campaign_id = public_id("CMP")
                seed = conn.execute(
                    "SELECT title FROM control_idea_seeds WHERE id = ?",
                    (job["idea_seed_id"],),
                ).fetchone()
                title = str(
                    (seed["title"] if seed else "")
                    or str(job["wish"]).splitlines()[0]
                )[:200]
                conn.execute(
                    """INSERT INTO control_campaigns (
                           id, project_id, title, goal, non_goals,
                           risk_level, base_sha, version
                       ) VALUES (?, ?, ?, ?, '', 'medium', ?, 1)""",
                    (
                        campaign_id,
                        int(job["project_id"]),
                        title,
                        str(job["wish"])[:10000],
                        base_sha,
                    ),
                )
                self._insert_campaign_profile(
                    conn,
                    campaign_id,
                    title,
                    {
                        "planning_depth": job["planning_depth"],
                        "max_candidates": int(job["max_candidates"]),
                        "activation_policy": job["activation_policy"],
                        "constraints": job["constraints"],
                    },
                )
            duplicate = conn.execute(
                """SELECT id FROM control_question_ledger
                   WHERE planning_job_id = ? AND content_hash = ?""",
                (job_id, content_hash),
            ).fetchone()
            if duplicate:
                conn.rollback()
                raise ControlCenterError(
                    "Die Planning-Session wiederholt dieselbe Frage ohne Fortschritt.",
                    code="planning_question_no_progress",
                    status=409,
                )
            conn.execute(
                """INSERT INTO control_question_ledger (
                       id, campaign_id, planning_job_id, amendment_id, content_hash,
                       branch, question, rationale, status, owner,
                       evidence_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)""",
                (
                    question_id,
                    campaign_id,
                    job_id,
                    amendment_id or None,
                    content_hash,
                    branch,
                    question,
                    rationale,
                    str(question_payload.get("owner") or "human")[:120],
                    json.dumps(evidence, ensure_ascii=False),
                ),
            )
            if not campaign_created and not amendment_mode:
                self._invalidate_draft_plan_in_connection(conn, campaign_id)
            self._attention(
                conn,
                project_id=int(job["project_id"]),
                category="planning_question",
                entity_type="planning_question",
                entity_id=question_id,
                title=question,
                consequence=(
                    rationale
                    or "Ohne diese Antwort kann der Plan nicht belastbar fortgesetzt werden."
                ),
                recommendation="Frage beantworten, damit derselbe Planner-Chat fortgesetzt wird.",
                urgency="normal",
            )
            updated = conn.execute(
                """UPDATE control_planning_jobs
                   SET status = 'waiting_human', campaign_id = ?,
                       waiting_reason = 'question', active_question_id = ?,
                       round_number = round_number + 1, output_json = ?,
                       last_error = '', finished_at = NULL,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = 'running'""",
                (
                    campaign_id,
                    question_id,
                    json.dumps(envelope, ensure_ascii=False),
                    job_id,
                ),
            )
            if updated.rowcount != 1:
                conn.rollback()
                raise ControlCenterError(
                    "Planning-Job ist nicht aktiv.",
                    code="planning_job_not_running",
                    status=409,
                )
            self._audit(
                conn,
                project_id=int(job["project_id"]),
                entity_type="planning_job",
                entity_id=job_id,
                action="planning_job.question_requested",
                actor="antigravity-planner",
                from_state="running",
                to_state="waiting_human",
                evidence={
                    "campaign_id": campaign_id,
                    "question_id": question_id,
                    "round_number": int(job["round_number"]) + 1,
                },
            )
            conn.commit()
        return self.get_planning_job(job_id)

    def complete_planning_job(
        self,
        job_id: str,
        plan: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not isinstance(plan, dict):
            raise ControlCenterError(
                "Planner-Ausgabe muss ein JSON-Objekt sein.",
                code="invalid_generated_plan",
            )
        result_type = str(plan.get("type") or "").strip().lower()
        if result_type == "question":
            return self._record_planning_question(job_id, plan)
        job = self.get_planning_job(job_id)
        if str(job.get("job_type") or "") == "plan_amendment":
            return self._complete_plan_amendment_job(job_id, plan)
        resolved_question_ids = plan.get("resolved_question_ids")
        resolved_question_ids_valid = (
            isinstance(resolved_question_ids, list)
            and all(
                isinstance(question_id, str) and question_id.strip()
                for question_id in resolved_question_ids
            )
        )
        if result_type == "plan":
            generated_plan = plan.get("plan")
            unexpected_fields = set(plan) - {
                "type",
                "resolved_question_ids",
                "plan",
            }
            if not isinstance(generated_plan, dict) or unexpected_fields:
                raise ControlCenterError(
                    "Eine Plan-Envelope muss genau einen vollständigen Plan enthalten.",
                    code="invalid_generated_plan_envelope",
                )
            if not resolved_question_ids_valid:
                raise ControlCenterError(
                    "resolved_question_ids muss für einen finalen Plan explizit angegeben werden.",
                    code="resolved_question_ids_required",
                )
            plan = generated_plan
        elif result_type:
            raise ControlCenterError(
                "Planner-Ausgabe hat einen unbekannten Ergebnistyp.",
                code="invalid_planning_result_type",
            )
        job = self.get_planning_job(job_id)
        if job["status"] != "running":
            raise ControlCenterError(
                "Planning-Job ist nicht aktiv.",
                code="planning_job_not_running",
                status=409,
            )
        candidates = plan.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ControlCenterError(
                "Generierter Plan enthält keine PR-Kandidaten.",
                code="generated_candidates_required",
            )
        if len(candidates) > int(job["max_candidates"]):
            raise ControlCenterError(
                "Generierter Plan überschreitet das Kandidatenlimit.",
                code="generated_candidate_limit_exceeded",
            )
        project = self._project(job["project_id"])
        base_sha = self._resolve_sha(project, require=True)
        title = clean_text(plan.get("title"), "title", minimum=3, maximum=200)
        goal = clean_text(
            plan.get("goal") or job["wish"],
            "goal",
            minimum=10,
            maximum=10000,
        )
        risk = str(plan.get("risk_level") or "medium").lower()
        if risk not in RISK_LEVELS:
            raise ControlCenterError(
                "Generierter Plan hat eine ungültige Risikostufe.",
                code="invalid_risk_level",
            )
        branch_assessments, grounded_paths = (
            self._validate_generated_branch_assessments(
                plan,
                project,
                base_sha,
            )
        )
        campaign_id = str(job.get("campaign_id") or "") or public_id("CMP")
        client_ids: Dict[str, str] = {}
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            locked_job = conn.execute(
                "SELECT * FROM control_planning_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if not locked_job or str(locked_job["status"]) != "running":
                conn.rollback()
                raise ControlCenterError(
                    "Planning-Job ist nicht aktiv.",
                    code="planning_job_not_running",
                    status=409,
                )
            job = self._row(
                locked_job,
                ("constraints_json", "output_json"),
            )
            session_questions = conn.execute(
                """SELECT * FROM control_question_ledger
                   WHERE planning_job_id = ?
                   ORDER BY created_at ASC, id ASC""",
                (job_id,),
            ).fetchall()
            resolved_ids = (
                {
                    str(question_id).strip()
                    for question_id in resolved_question_ids
                }
                if resolved_question_ids_valid
                else set()
            )
            if session_questions:
                if not resolved_question_ids_valid:
                    conn.rollback()
                    raise ControlCenterError(
                        "resolved_question_ids muss für diese Planning-Session angegeben werden.",
                        code="resolved_question_ids_required",
                    )
                if len(resolved_ids) != len(resolved_question_ids):
                    conn.rollback()
                    raise ControlCenterError(
                        "resolved_question_ids enthält doppelte Fragen.",
                        code="resolved_question_ids_invalid",
                    )
                session_ids = {str(question["id"]) for question in session_questions}
                answered_ids = {
                    str(question["id"])
                    for question in session_questions
                    if str(question["status"]) == "answered"
                }
                if resolved_ids - session_ids:
                    conn.rollback()
                    raise ControlCenterError(
                        "resolved_question_ids verweist auf unbekannte Session-Fragen.",
                        code="resolved_question_ids_invalid",
                    )
                if answered_ids != session_ids or not answered_ids <= resolved_ids:
                    conn.rollback()
                    raise ControlCenterError(
                        "Der finale Plan verarbeitet noch nicht alle beantworteten Fragen.",
                        code="planning_questions_unresolved",
                        status=409,
                    )
            existing_campaign_id = str(job.get("campaign_id") or "")
            if existing_campaign_id:
                campaign_id = existing_campaign_id
                campaign = self._campaign(conn, campaign_id)
                if str(campaign["status"]) != "draft":
                    conn.rollback()
                    raise ControlCenterError(
                        "Die Planning-Session-Campaign ist nicht mehr editierbar.",
                        code="planning_session_campaign_locked",
                        status=409,
                    )
                existing_candidates = conn.execute(
                    """SELECT COUNT(*) AS count FROM control_pr_candidates
                       WHERE campaign_id = ?""",
                    (campaign_id,),
                ).fetchone()
                if int(existing_candidates["count"]) != 0:
                    conn.rollback()
                    raise ControlCenterError(
                        "Die Planning-Session-Campaign enthält bereits PR-Slices.",
                        code="planning_session_campaign_not_empty",
                        status=409,
                    )
                campaign_version = int(campaign["version"]) + 1
                conn.execute(
                    """UPDATE control_campaigns
                       SET title = ?, goal = ?, non_goals = ?, risk_level = ?,
                           base_sha = ?, version = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND status = 'draft'""",
                    (
                        title,
                        goal,
                        str(plan.get("non_goals") or "")[:5000],
                        risk,
                        base_sha,
                        campaign_version,
                        campaign_id,
                    ),
                )
            else:
                campaign_version = 1
                conn.execute(
                    """INSERT INTO control_campaigns (
                           id, project_id, title, goal, non_goals,
                           risk_level, base_sha, version
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        campaign_id,
                        int(job["project_id"]),
                        title,
                        goal,
                        str(plan.get("non_goals") or "")[:5000],
                        risk,
                        base_sha,
                        campaign_version,
                    ),
                )
            profile_payload = {
                "planning_depth": job["planning_depth"],
                "max_candidates": int(job["max_candidates"]),
                "activation_policy": job["activation_policy"],
                "pivotal_fork": plan.get("pivotal_fork", ""),
                "pivotal_fork_na_reason": plan.get(
                    "pivotal_fork_na_reason",
                    "",
                ),
                "success_metrics": plan.get("success_metrics", []),
                "constraints": plan.get("constraints", job["constraints"]),
                "assumptions": plan.get("assumptions", []),
                "acceptance_matrix": plan.get("acceptance_matrix", []),
                "alternatives": plan.get("alternatives", []),
                "review_strategy": plan.get("review_strategy", ""),
                "rollout_plan": plan.get("rollout_plan", ""),
                "rollback_plan": plan.get("rollback_plan", ""),
            }
            self._insert_campaign_profile(
                conn,
                campaign_id,
                title,
                profile_payload,
            )
            for assessment in branch_assessments:
                branch = clean_text(
                    assessment.get("branch"),
                    "branch",
                    maximum=120,
                ).lower()
                assessment_status = str(
                    assessment.get("status") or ""
                ).strip()
                assessment_question = clean_text(
                    assessment.get("question"),
                    "question",
                    minimum=5,
                    maximum=5000,
                )
                assessment_evidence = assessment.get("evidence") or {}
                normalized_question = " ".join(
                    assessment_question.casefold().split()
                )
                content_hash = hashlib.sha256(
                    f"{branch}:{normalized_question}".encode("utf-8")
                ).hexdigest()
                conn.execute(
                    """INSERT INTO control_question_ledger (
                           id, campaign_id, planning_job_id, content_hash,
                           branch, question, rationale, answer, answer_source,
                           status, owner, evidence_json, resolved_in_version
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        public_id("Q"),
                        campaign_id,
                        job_id,
                        content_hash,
                        branch,
                        assessment_question,
                        str(assessment.get("rationale") or "")[:5000],
                        str(assessment.get("answer") or "")[:20000],
                        str(assessment.get("answer_source") or "planner")[:120],
                        assessment_status,
                        str(assessment.get("owner") or "")[:120],
                        json.dumps(assessment_evidence, ensure_ascii=False),
                        campaign_version,
                    ),
                )
            for index, candidate_plan in enumerate(candidates, start=1):
                if not isinstance(candidate_plan, dict):
                    raise ControlCenterError(
                        "PR-Kandidaten müssen Objekte sein.",
                        code="invalid_generated_candidate",
                    )
                for score_field in GENERATED_SCORE_FIELDS:
                    score_value = candidate_plan.get(score_field)
                    if score_value in (None, ""):
                        continue
                    try:
                        numeric_score = float(score_value)
                    except (TypeError, ValueError):
                        continue
                    if 10 < numeric_score <= 100:
                        candidate_plan[score_field] = numeric_score / 10
                client_id = str(candidate_plan.get("id") or f"slice-{index}")
                if client_id in client_ids:
                    raise ControlCenterError(
                        "Generierte PR-Kandidaten-IDs sind nicht eindeutig.",
                        code="duplicate_generated_candidate_id",
                    )
                candidate_id = public_id("PRC")
                client_ids[client_id] = candidate_id
                criteria = validate_acceptance_criteria(
                    candidate_plan.get("acceptance_criteria")
                )
                candidate_risk = str(
                    candidate_plan.get("risk_level") or "medium"
                ).lower()
                if candidate_risk not in RISK_LEVELS:
                    raise ControlCenterError(
                        "PR-Kandidat hat eine ungültige Risikostufe.",
                        code="invalid_risk_level",
                    )
                candidate_title = clean_text(
                    candidate_plan.get("title"),
                    "candidate_title",
                    minimum=3,
                    maximum=200,
                )
                scope = clean_text(
                    candidate_plan.get("scope"),
                    "candidate_scope",
                    minimum=10,
                    maximum=10000,
                )
                conn.execute(
                    """INSERT INTO control_pr_candidates (
                           id, campaign_id, title, scope,
                           acceptance_criteria_json, non_goals,
                           risk_level, priority, base_sha
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        candidate_id,
                        campaign_id,
                        candidate_title,
                        scope,
                        json.dumps(criteria, ensure_ascii=False),
                        str(candidate_plan.get("non_goals") or "")[:5000],
                        candidate_risk,
                        int(candidate_plan.get("priority") or index * 10),
                        base_sha,
                    ),
                )
                self._write_candidate_contract(
                    conn,
                    candidate_id,
                    candidate_plan,
                    criteria,
                    strict=True,
                )
            for index, candidate_plan in enumerate(candidates, start=1):
                generated_id = str(candidate_plan.get("id") or f"slice-{index}")
                candidate_id = client_ids[
                    generated_id
                ]
                for dependency in candidate_plan.get("depends_on") or []:
                    if str(dependency) not in client_ids:
                        raise ControlCenterError(
                            "Generierte Dependency verweist auf unbekannten Slice.",
                            code="invalid_dependency",
                        )
                    conn.execute(
                        """INSERT INTO control_pr_dependencies (
                               candidate_id, depends_on_id
                           ) VALUES (?, ?)""",
                        (candidate_id, client_ids[str(dependency)]),
                    )
                for conflict in candidate_plan.get("conflicts_with") or []:
                    other_client = (
                        str(conflict.get("id"))
                        if isinstance(conflict, dict)
                        else str(conflict)
                    )
                    if other_client not in client_ids or other_client == generated_id:
                        continue
                    first, second = sorted(
                        (candidate_id, client_ids[other_client])
                    )
                    reason = (
                        str(conflict.get("reason") or "Generated resource conflict")
                        if isinstance(conflict, dict)
                        else "Generated resource conflict"
                    )
                    resources = (
                        conflict.get("resources") or []
                        if isinstance(conflict, dict)
                        else []
                    )
                    conn.execute(
                        """INSERT OR IGNORE INTO control_candidate_conflicts (
                               candidate_id, conflicts_with_id, reason, resources_json
                           ) VALUES (?, ?, ?, ?)""",
                        (
                            first,
                            second,
                            reason[:2000],
                            json.dumps(resources, ensure_ascii=False),
                        ),
                    )
            self._validate_dag(conn, campaign_id)
            seed = conn.execute(
                "SELECT * FROM control_idea_seeds WHERE id = ?",
                (job["idea_seed_id"],),
            ).fetchone()
            if not seed:
                raise ControlCenterError(
                    "Idea Seed nicht gefunden.",
                    code="idea_seed_not_found",
                    status=404,
                )
            knowledge_documents = self._build_planning_knowledge_documents(
                seed=seed,
                job=job,
                plan={**plan, "title": title, "goal": goal},
                campaign_id=campaign_id,
                base_sha=base_sha,
                grounded_paths=grounded_paths,
                branch_assessments=branch_assessments,
            )
            common_artifact_metadata = {
                "base_sha": base_sha,
                "campaign_version": campaign_version,
                "source": "antigravity-planner",
            }
            idea_group_artifacts = []
            group_slug = knowledge_documents["group_slug"]
            for filename, content in knowledge_documents["idea_group"]:
                filename_slug = PurePosixPath(filename).stem.lower()
                idea_group_artifacts.append(
                    self._insert_planned_artifact_in_connection(
                        conn,
                        project_id=int(job["project_id"]),
                        campaign_id=campaign_id,
                        artifact_type="idea_group",
                        slug=f"{filename_slug}-{group_slug}",
                        title=f"{title} {filename}",
                        status="proposed",
                        content=content,
                        metadata={
                            **common_artifact_metadata,
                            "group_slug": group_slug,
                            "filename": filename,
                        },
                        relative_path=f"docs/ideas/{group_slug}/{filename}",
                    )
                )

            artifacts_by_type: Dict[str, Dict[str, Any]] = {}
            for artifact_type, key, status in (
                ("repository_map", "repository_map", "current"),
                ("design_document", "design_document", "proposed"),
                ("adr", "adr", "proposed"),
            ):
                content = str(
                    knowledge_documents.get(key)
                    if key in {"design_document", "adr"}
                    else plan.get(key)
                    or ""
                ).strip()
                if not content:
                    continue
                artifact_metadata = dict(common_artifact_metadata)
                if artifact_type == "repository_map":
                    artifact_metadata["grounded_paths"] = grounded_paths
                artifacts_by_type[artifact_type] = (
                    self._insert_planned_artifact_in_connection(
                        conn,
                        project_id=int(job["project_id"]),
                        campaign_id=campaign_id,
                        artifact_type=artifact_type,
                        slug=title,
                        title=(
                            f"{title} "
                            f"{artifact_type.replace('_', ' ').title()}"
                        ),
                        status=status,
                        content=content,
                        metadata=artifact_metadata,
                    )
                )
            simulation = self._simulate_campaign_in_connection(
                conn,
                campaign_id,
                persist=True,
            )
            simulation_content = (
                "# Plan Simulation\n\n```json\n"
                + json.dumps(simulation, ensure_ascii=False, indent=2)
                + "\n```\n"
            )
            artifacts_by_type["plan_simulation"] = (
                self._insert_planned_artifact_in_connection(
                    conn,
                    project_id=int(job["project_id"]),
                    campaign_id=campaign_id,
                    artifact_type="plan_simulation",
                    slug=title,
                    title=f"{title} Plan Simulation",
                    status="current",
                    content=simulation_content,
                    metadata={
                        **common_artifact_metadata,
                        "simulation_sha256": canonical_json_sha256(simulation),
                    },
                )
            )
            idea_group_root = next(
                artifact
                for artifact in idea_group_artifacts
                if str(artifact["relative_path"]).endswith("/README.md")
            )
            self._record_knowledge_link_in_connection(
                conn,
                {
                    "source_kind": "idea_seed",
                    "source_id": str(seed["id"]),
                    "target_kind": "artifact",
                    "target_id": str(idea_group_root["id"]),
                    "relation_type": "developed_into",
                },
                actor="antigravity-planner",
                invalidate_plan=False,
            )
            for artifact in idea_group_artifacts:
                if artifact["id"] == idea_group_root["id"]:
                    continue
                self._record_knowledge_link_in_connection(
                    conn,
                    {
                        "source_kind": "artifact",
                        "source_id": str(idea_group_root["id"]),
                        "target_kind": "artifact",
                        "target_id": str(artifact["id"]),
                        "relation_type": "contains",
                    },
                    actor="antigravity-planner",
                    invalidate_plan=False,
                )
            design_artifact = artifacts_by_type["design_document"]
            adr_artifact = artifacts_by_type["adr"]
            self._record_knowledge_link_in_connection(
                conn,
                {
                    "source_kind": "artifact",
                    "source_id": str(idea_group_root["id"]),
                    "target_kind": "artifact",
                    "target_id": str(design_artifact["id"]),
                    "relation_type": "informs",
                },
                actor="antigravity-planner",
                invalidate_plan=False,
            )
            self._record_knowledge_link_in_connection(
                conn,
                {
                    "source_kind": "artifact",
                    "source_id": str(design_artifact["id"]),
                    "target_kind": "artifact",
                    "target_id": str(adr_artifact["id"]),
                    "relation_type": "decided_by",
                },
                actor="antigravity-planner",
                invalidate_plan=False,
            )
            for candidate_id in client_ids.values():
                for artifact, relation_type in (
                    (design_artifact, "implements_design"),
                    (adr_artifact, "follows_decision"),
                ):
                    self._record_knowledge_link_in_connection(
                        conn,
                        {
                            "source_kind": "candidate",
                            "source_id": candidate_id,
                            "target_kind": "artifact",
                            "target_id": str(artifact["id"]),
                            "relation_type": relation_type,
                        },
                        actor="antigravity-planner",
                        invalidate_plan=False,
                    )
            if session_questions:
                for question in session_questions:
                    conn.execute(
                        """UPDATE control_question_ledger
                           SET status = 'resolved', resolved_in_version = ?,
                               updated_at = CURRENT_TIMESTAMP
                           WHERE id = ? AND planning_job_id = ?
                             AND status = 'answered'""",
                        (campaign_version, question["id"], job_id),
                    )
                self._audit(
                    conn,
                    project_id=int(job["project_id"]),
                    entity_type="campaign",
                    entity_id=campaign_id,
                    action="planning.questions_resolved",
                    actor="antigravity-planner",
                    evidence={
                        "planning_job_id": job_id,
                        "question_ids": sorted(resolved_ids),
                        "resolved_in_version": campaign_version,
                    },
                )
            self._attention(
                conn,
                project_id=int(job["project_id"]),
                category="plan_approval",
                entity_type="campaign",
                entity_id=campaign_id,
                title=f"Generierten Plan „{title}“ prüfen",
                consequence="Ohne deine Prüfung werden keine Work Orders aktiviert.",
                recommendation="PR-Slices, Dependencies, Konflikte und Grenzen prüfen.",
                urgency="high" if risk in {"high", "critical"} else "normal",
            )
            updated = conn.execute(
                """UPDATE control_planning_jobs
                   SET status = 'waiting_human', campaign_id = ?,
                       waiting_reason = 'plan_approval',
                       active_question_id = NULL, output_json = ?, last_error = '',
                       finished_at = NULL,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = 'running'""",
                (
                    campaign_id,
                    json.dumps(plan, ensure_ascii=False),
                    job_id,
                ),
            )
            if updated.rowcount != 1:
                conn.rollback()
                raise ControlCenterError(
                    "Planning-Job ist nicht aktiv.",
                    code="planning_job_not_running",
                    status=409,
                )
            self._audit(
                conn,
                project_id=int(job["project_id"]),
                entity_type="planning_job",
                entity_id=job_id,
                action="planning_job.plan_generated",
                actor="antigravity-planner",
                from_state="running",
                to_state="waiting_human",
                evidence={
                    "campaign_id": campaign_id,
                    "candidate_count": len(candidates),
                },
            )
            conn.execute(
                """UPDATE control_idea_seeds
                   SET status = 'planned', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = 'planning'""",
                (job["idea_seed_id"],),
            )
            conn.commit()
        return self.get_planning_job(job_id)
