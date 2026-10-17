"""Versioned Campaign creation and human plan approval."""

import json

from src.control_center.common import ControlCenterError, clean_text, public_id


CAMPAIGN_COMPLETION_CANDIDATE_STATES = {
    "completed",
    "merged",
    "deployed",
    "obsolete",
}

CAMPAIGN_CANCELLABLE_STATES = {"draft", "paused", "approved"}
CAMPAIGN_UNSTARTED_CANDIDATE_STATES = {"ready", "approved", "cancelled"}
CAMPAIGN_UNSTARTED_WORK_ORDER_STATES = {"approved", "cancelled"}


class CampaignMixin:
    def _complete_planning_jobs_for_campaign(
        self,
        conn,
        campaign,
        *,
        actor,
    ):
        jobs = conn.execute(
            """SELECT * FROM control_planning_jobs
               WHERE campaign_id = ? AND status = 'waiting_human'""",
            (campaign["id"],),
        ).fetchall()
        changed = 0
        for job in jobs:
            updated = conn.execute(
                """UPDATE control_planning_jobs
                   SET status = 'completed', finished_at = CURRENT_TIMESTAMP,
                       waiting_reason = '', active_question_id = NULL,
                       last_error = '', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = 'waiting_human'""",
                (job["id"],),
            )
            if updated.rowcount != 1:
                continue
            changed += 1
            self._audit(
                conn,
                project_id=int(campaign["project_id"]),
                entity_type="planning_job",
                entity_id=str(job["id"]),
                action="planning_job.completed",
                actor=actor,
                from_state="waiting_human",
                to_state="completed",
                evidence={"campaign_id": str(campaign["id"])},
            )
        return changed

    def _cancel_planning_jobs_for_campaign(
        self,
        conn,
        campaign,
        *,
        actor,
        reason,
    ):
        jobs = conn.execute(
            """SELECT * FROM control_planning_jobs
               WHERE campaign_id = ?
                 AND status IN ('queued', 'waiting_human', 'failed')""",
            (campaign["id"],),
        ).fetchall()
        changed = 0
        for job in jobs:
            updated = conn.execute(
                """UPDATE control_planning_jobs
                   SET status = 'cancelled', finished_at = CURRENT_TIMESTAMP,
                       waiting_reason = '', active_question_id = NULL,
                       last_error = CASE WHEN status = 'failed'
                           THEN last_error ELSE '' END,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?
                     AND status IN ('queued', 'waiting_human', 'failed')""",
                (job["id"],),
            )
            if updated.rowcount != 1:
                continue
            changed += 1
            self._audit(
                conn,
                project_id=int(campaign["project_id"]),
                entity_type="planning_job",
                entity_id=str(job["id"]),
                action="planning_job.cancelled",
                actor=actor,
                from_state=str(job["status"]),
                to_state="cancelled",
                reason=reason,
                evidence={"campaign_id": str(campaign["id"])},
            )
        return changed

    def cancel_campaign(self, campaign_id, *, actor="human", reason=""):
        """Cancel an unstarted campaign while preserving its complete history."""
        actor_name = clean_text(actor, "actor", maximum=120)
        explanation = str(reason or "").strip()
        if len(explanation) > 2000:
            raise ControlCenterError(
                "reason darf höchstens 2000 Zeichen enthalten.",
                code="reason_too_long",
            )

        with self.db._get_connection() as conn:
            # Serialize the complete preflight and cascade against executor leases.
            conn.execute("BEGIN IMMEDIATE")
            campaign = self._campaign(conn, str(campaign_id))
            if campaign["status"] == "cancelled":
                planning_jobs = self._cancel_planning_jobs_for_campaign(
                    conn,
                    campaign,
                    actor=actor_name,
                    reason=explanation,
                )
                conn.commit()
                return {
                    "campaign": dict(campaign),
                    "cancelled": (
                        {"planning_jobs": planning_jobs}
                        if planning_jobs
                        else {}
                    ),
                    "idempotent": True,
                }
            if campaign["status"] not in CAMPAIGN_CANCELLABLE_STATES:
                raise ControlCenterError(
                    "Nur eine noch nicht gestartete Campaign im Entwurf, in Pause "
                    "oder nach Planfreigabe kann abgebrochen werden.",
                    code="campaign_cancel_conflict",
                    status=409,
                )

            candidates = conn.execute(
                "SELECT * FROM control_pr_candidates WHERE campaign_id = ?",
                (campaign["id"],),
            ).fetchall()
            candidate_ids = [str(row["id"]) for row in candidates]
            unsafe_candidates = [
                str(row["id"])
                for row in candidates
                if str(row["status"]) not in CAMPAIGN_UNSTARTED_CANDIDATE_STATES
            ]

            work_orders = conn.execute(
                """SELECT wo.* FROM control_work_orders wo
                   JOIN control_pr_candidates candidate
                     ON candidate.id = wo.candidate_id
                   WHERE candidate.campaign_id = ?""",
                (campaign["id"],),
            ).fetchall()
            unsafe_work_orders = [
                str(row["id"])
                for row in work_orders
                if str(row["status"]) not in CAMPAIGN_UNSTARTED_WORK_ORDER_STATES
            ]

            tasks = conn.execute(
                "SELECT * FROM control_agent_tasks WHERE campaign_id = ?",
                (campaign["id"],),
            ).fetchall()
            unsafe_tasks = []
            for task in tasks:
                status = str(task["status"])
                if status not in {"queued", "cancelled"}:
                    unsafe_tasks.append(str(task["id"]))
                    continue
                if self._unstarted_task_blockers(
                    conn,
                    task,
                    expected_status=status,
                ):
                    unsafe_tasks.append(str(task["id"]))

            active_planning_jobs = conn.execute(
                """SELECT id FROM control_planning_jobs
                   WHERE campaign_id = ? AND status IN ('claimed', 'running')""",
                (campaign["id"],),
            ).fetchall()
            blockers = {
                "candidates": unsafe_candidates,
                "work_orders": unsafe_work_orders,
                "tasks": unsafe_tasks,
                "planning_jobs": [str(row["id"]) for row in active_planning_jobs],
            }
            if any(blockers.values()):
                raise ControlCenterError(
                    "Die Campaign hat bereits gestartete, veröffentlichte, "
                    "gemergte oder ausgerollte Arbeit und kann nicht sicher "
                    "abgebrochen werden.",
                    code="campaign_already_started",
                    status=409,
                )

            cancelled = {}
            cancelled["evidence_packs"] = conn.execute(
                """UPDATE control_evidence_packs
                   SET status = 'cancelled',
                       summary = CASE WHEN summary = ''
                           THEN 'Campaign vor Ausführung abgebrochen.'
                           ELSE summary END,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE task_id IN (
                       SELECT id FROM control_agent_tasks WHERE campaign_id = ?
                   ) AND status = 'collecting'""",
                (campaign["id"],),
            ).rowcount
            cancelled["tasks"] = conn.execute(
                """UPDATE control_agent_tasks
                   SET status = 'cancelled', wake_reason = 'campaign_cancelled',
                       finished_at = COALESCE(finished_at, CURRENT_TIMESTAMP),
                       lease_owner = '', lease_token = '', lease_until = NULL,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE campaign_id = ? AND status = 'queued'""",
                (campaign["id"],),
            ).rowcount
            cancelled["work_orders"] = conn.execute(
                """UPDATE control_work_orders
                   SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
                   WHERE status = 'approved' AND candidate_id IN (
                       SELECT id FROM control_pr_candidates WHERE campaign_id = ?
                   )""",
                (campaign["id"],),
            ).rowcount
            cancelled["candidates"] = conn.execute(
                """UPDATE control_pr_candidates
                   SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
                   WHERE campaign_id = ? AND status IN ('ready', 'approved')""",
                (campaign["id"],),
            ).rowcount
            cancelled["planning_jobs"] = self._cancel_planning_jobs_for_campaign(
                conn,
                campaign,
                actor=actor_name,
                reason=explanation,
            )
            conn.execute(
                """UPDATE control_plan_amendments
                   SET status = 'cancelled', resolved_at = CURRENT_TIMESTAMP,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE campaign_id = ?
                     AND status IN ('planning', 'review', 'failed', 'proposed')""",
                (campaign["id"],),
            )
            conn.execute(
                """UPDATE control_campaign_profiles
                   SET readiness_status = 'cancelled',
                       updated_at = CURRENT_TIMESTAMP
                   WHERE campaign_id = ?""",
                (campaign["id"],),
            )

            attention_params = [str(campaign["id"]), *candidate_ids]
            candidate_placeholders = ",".join("?" for _ in candidate_ids)
            attention_clause = "entity_type = 'campaign' AND entity_id = ?"
            if candidate_ids:
                attention_clause += (
                    " OR (entity_type = 'pr_candidate' AND entity_id IN ("
                    + candidate_placeholders
                    + "))"
                )
            cancelled["attention"] = conn.execute(
                f"""UPDATE control_attention_items
                    SET status = 'resolved', resolved_at = CURRENT_TIMESTAMP
                    WHERE status = 'open' AND ({attention_clause})""",
                tuple(attention_params),
            ).rowcount

            updated = conn.execute(
                """UPDATE control_campaigns
                   SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status IN ('draft', 'paused', 'approved')""",
                (campaign["id"],),
            )
            if updated.rowcount != 1:
                raise ControlCenterError(
                    "Die Campaign wurde parallel verändert.",
                    code="campaign_cancel_conflict",
                    status=409,
                )
            self._audit(
                conn,
                project_id=int(campaign["project_id"]),
                entity_type="campaign",
                entity_id=str(campaign["id"]),
                action="campaign.cancelled",
                actor=actor_name,
                from_state=str(campaign["status"]),
                to_state="cancelled",
                reason=explanation,
                evidence={"cancelled": cancelled, "no_external_mutations": True},
            )
            conn.commit()
            return {
                "campaign": dict(
                    conn.execute(
                        "SELECT * FROM control_campaigns WHERE id = ?",
                        (campaign["id"],),
                    ).fetchone()
                ),
                "cancelled": cancelled,
                "idempotent": False,
            }

    def _complete_campaign_if_done(self, conn, campaign_id, *, actor="orchestrator"):
        """Complete a campaign once every planned candidate is terminal."""
        campaign = self._campaign(conn, campaign_id)
        candidates = conn.execute(
            "SELECT id, status FROM control_pr_candidates WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchall()
        if not candidates or any(
            str(candidate["status"]) not in CAMPAIGN_COMPLETION_CANDIDATE_STATES
            for candidate in candidates
        ):
            return False
        if campaign["status"] == "completed":
            return True
        if campaign["status"] not in {"approved", "active"}:
            return False

        conn.execute(
            """UPDATE control_campaigns
               SET status = 'completed', updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (campaign_id,),
        )
        conn.execute(
            """UPDATE control_campaign_profiles
               SET completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
                   updated_at = CURRENT_TIMESTAMP
               WHERE campaign_id = ?""",
            (campaign_id,),
        )
        for candidate in candidates:
            self._resolve_attention(
                conn,
                "pr_candidate",
                str(candidate["id"]),
                "work_order_approval",
            )
        self._audit(
            conn,
            project_id=int(campaign["project_id"]),
            entity_type="campaign",
            entity_id=campaign_id,
            action="campaign.completed",
            actor=str(actor or "orchestrator")[:120],
            from_state=str(campaign["status"]),
            to_state="completed",
            evidence={
                "candidate_states": {
                    str(candidate["id"]): str(candidate["status"])
                    for candidate in candidates
                }
            },
        )
        return True

    def create_campaign(self, payload):
        project = self._project(payload.get("project_id"))
        title = clean_text(payload.get("title"), "title", minimum=3, maximum=200)
        goal = clean_text(payload.get("goal"), "goal", minimum=10, maximum=10000)
        non_goals = str(payload.get("non_goals") or "").strip()[:5000]
        risk = self._risk(payload.get("risk_level"))
        base_sha = self._resolve_sha(project, payload.get("base_sha"))
        recommendation_id = str(payload.get("recommendation_id") or "").strip() or None
        actor = clean_text(payload.get("actor") or "human", "actor", maximum=120)
        with self.db._get_connection() as conn:
            if recommendation_id:
                recommendation = conn.execute(
                    "SELECT * FROM control_recommendations WHERE id = ?", (recommendation_id,)
                ).fetchone()
                if not recommendation or int(recommendation["project_id"]) != int(project["id"]):
                    raise ControlCenterError("Empfehlung passt nicht zum Projekt.", code="invalid_recommendation")
                if recommendation["status"] != "accepted":
                    raise ControlCenterError(
                        "Nur akzeptierte Empfehlungen können in eine Campaign überführt werden.",
                        code="recommendation_not_accepted", status=409,
                    )
            campaign_id = public_id("CMP")
            conn.execute(
                """INSERT INTO control_campaigns (
                       id, project_id, recommendation_id, title, goal, non_goals,
                       risk_level, base_sha
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (campaign_id, project["id"], recommendation_id, title, goal, non_goals, risk, base_sha),
            )
            self._insert_campaign_profile(conn, campaign_id, title, payload)
            if recommendation_id:
                self._resolve_attention(conn, "recommendation", recommendation_id, "campaign_planning")
            self._attention(
                conn, project_id=int(project["id"]), category="plan_approval",
                entity_type="campaign", entity_id=campaign_id,
                title=f"Campaign-Plan „{title}“ freigeben",
                consequence="Ohne Freigabe wird kein PR Candidate als Arbeitsauftrag aktiviert.",
                recommendation="Ziel, Nicht-Ziele, Baseline und PR-Slices prüfen.",
                urgency="high" if risk in {"high", "critical"} else "normal",
            )
            self._audit(
                conn, project_id=int(project["id"]), entity_type="campaign",
                entity_id=campaign_id, action="campaign.created", actor=actor,
                to_state="draft", evidence={"version": 1, "base_sha": base_sha, "risk_level": risk},
            )
            conn.commit()
            return dict(conn.execute(
                "SELECT * FROM control_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone())

    def approve_campaign(
        self,
        campaign_id,
        *,
        expected_version,
        approval_sha,
        expected_plan_signature,
        actor="human",
        reason="",
    ):
        try:
            version = int(expected_version)
        except (TypeError, ValueError):
            raise ControlCenterError("Planversion ist erforderlich.", code="version_required")
        expected_signature = str(expected_plan_signature or "").strip().lower()
        if len(expected_signature) != 64 or any(
            character not in "0123456789abcdef" for character in expected_signature
        ):
            raise ControlCenterError(
                "Die exakt angezeigte Plan-Signatur ist erforderlich.",
                code="plan_signature_required",
            )
        actor_name = clean_text(actor, "actor", maximum=120)
        explanation = str(reason or "").strip()
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            campaign = self._campaign(conn, campaign_id)
            if campaign["status"] == "approved" and int(campaign["approved_version"] or 0) == version:
                signature_audit = conn.execute(
                    """SELECT evidence_json FROM control_audit_events
                       WHERE entity_type = 'campaign' AND entity_id = ?
                         AND action = 'campaign.approved'
                       ORDER BY id DESC LIMIT 1""",
                    (campaign_id,),
                ).fetchone()
                audited_signature = ""
                if signature_audit:
                    try:
                        evidence = json.loads(signature_audit["evidence_json"] or "{}")
                    except (json.JSONDecodeError, TypeError):
                        evidence = {}
                    audited_signature = str(
                        evidence.get("plan_signature") or ""
                    ).strip().lower()
                if audited_signature and audited_signature != expected_signature:
                    raise ControlCenterError(
                        "Der bereits genehmigte Plan hat eine andere Signatur.",
                        code="stale_plan_signature",
                        status=409,
                    )
                self._complete_planning_jobs_for_campaign(
                    conn,
                    campaign,
                    actor=actor_name,
                )
                conn.commit()
                return dict(campaign)
            if campaign["status"] != "draft":
                raise ControlCenterError("Campaign ist nicht mehr im Entwurfszustand.", code="campaign_not_draft", status=409)
            if int(campaign["version"]) != version:
                raise ControlCenterError(
                    "Die Planversion hat sich geändert. Bitte Ansicht neu laden.",
                    code="stale_plan_version", status=409,
                )
            readiness = self._evaluate_campaign_readiness_in_connection(
                conn,
                campaign_id,
                persist=False,
            )
            if readiness["plan_signature"] != expected_signature:
                raise ControlCenterError(
                    "Der Plan hat sich seit der angezeigten Prüfung geändert. "
                    "Bitte Readiness und Plan erneut öffnen.",
                    code="stale_plan_signature",
                    status=409,
                )
            if not readiness["ready"]:
                for specific_code in ("stale_base_sha", "sha_required"):
                    if specific_code in readiness["missing"]:
                        raise ControlCenterError(
                            "Der Repository-Stand ist nicht mehr die geprüfte "
                            "Campaign-Baseline.",
                            code=specific_code,
                            status=409,
                        )
                raise ControlCenterError(
                    "Das Plan-Readiness-Gate ist nicht erfüllt: "
                    + ", ".join(readiness["missing"]),
                    code="plan_not_ready",
                    status=409,
                )
            candidates = conn.execute(
                "SELECT * FROM control_pr_candidates WHERE campaign_id = ?", (campaign_id,)
            ).fetchall()
            if not candidates:
                raise ControlCenterError(
                    "Vor der Planfreigabe ist mindestens ein PR-Slice erforderlich.",
                    code="pr_candidate_required", status=409,
                )
            self._validate_dag(conn, campaign_id)
            project = self._project(campaign["project_id"])
            verified_sha = self._resolve_sha(project, approval_sha, require=True)
            if verified_sha != str(campaign["base_sha"] or "").lower():
                raise ControlCenterError(
                    "Freigabe-SHA und Campaign-Basis stimmen nicht überein.",
                    code="approval_sha_mismatch", status=409,
                )
            conn.execute(
                """UPDATE control_campaigns
                   SET status = 'approved', approved_version = ?, approved_sha = ?,
                       approved_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                (version, verified_sha, actor_name, campaign_id),
            )
            self._resolve_attention(conn, "campaign", campaign_id, "plan_approval")
            for candidate in candidates:
                self._attention(
                    conn, project_id=int(campaign["project_id"]), category="work_order_approval",
                    entity_type="pr_candidate", entity_id=str(candidate["id"]),
                    title=f"PR-Slice „{candidate['title']}“ aktivieren",
                    consequence="Der Slice bleibt ohne separaten Arbeitsauftrag inaktiv.",
                    recommendation="Scope, Kriterien, Abhängigkeiten und exakten SHA prüfen.",
                    urgency="high" if candidate["risk_level"] in {"high", "critical"} else "normal",
                )
            self._audit(
                conn, project_id=int(campaign["project_id"]), entity_type="campaign",
                entity_id=campaign_id, action="campaign.approved", actor=actor_name,
                from_state="draft", to_state="approved", reason=explanation,
                evidence={
                    "version": version,
                    "sha": verified_sha,
                    "plan_signature": expected_signature,
                    "plan_signature_version": readiness["plan_signature_version"],
                },
            )
            conn.execute(
                """UPDATE control_campaign_profiles
                   SET readiness_status = 'approved', readiness_score = ?,
                       plan_signature = ?,
                       started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                       updated_at = CURRENT_TIMESTAMP
                   WHERE campaign_id = ?""",
                (readiness["score"], expected_signature, campaign_id),
            )
            self._complete_planning_jobs_for_campaign(
                conn,
                campaign,
                actor=actor_name,
            )
            conn.commit()
            return dict(conn.execute(
                "SELECT * FROM control_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone())
