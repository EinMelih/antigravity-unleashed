"""Separate, SHA-bound activation of approved PR candidates."""

from src.control_center.common import ControlCenterError, clean_text, public_id


ACTIVATION_COMPLETE_STATES = ("completed", "merged", "deployed", "obsolete")


class WorkOrderMixin:
    @staticmethod
    def _unstarted_task_blockers(conn, task, *, expected_status):
        """Return durable activity that makes a work-order withdrawal unsafe."""
        blockers = []
        scalar_activity = {
            "status": task["status"] != expected_status,
            "attempt": int(task["attempt"] or 0) != 0,
            "started_at": bool(task["started_at"]),
            "lease": bool(
                task["lease_owner"] or task["lease_token"] or task["lease_until"]
            ),
            "current_sha": bool(task["current_sha"]),
            "merged_sha": bool(task["merged_sha"]),
            "worktree": bool(task["worktree_path"]),
            "antigravity_chat": bool(task["antigravity_chat_id"]),
            "issue": task["issue_number"] is not None or bool(task["issue_url"]),
            "pull_request": task["pr_number"] is not None or bool(task["pr_url"]),
            "checkpoint": bool(task["last_checkpoint_id"]),
            "wake_at": bool(task["wake_at"]),
            "last_error": bool(task["last_error"]),
            "progress": bool(
                int(task["no_progress_count"] or 0)
                or int(task["consumed_tokens"] or 0)
                or task["last_progress_hash"]
            ),
            "finished_at": (
                expected_status == "queued" and bool(task["finished_at"])
            ),
        }
        blockers.extend(name for name, active in scalar_activity.items() if active)
        related_queries = {
            "task_events": (
                "SELECT COUNT(*) AS count FROM control_task_events WHERE task_id = ?",
                (task["id"],),
            ),
            "findings": (
                "SELECT COUNT(*) AS count FROM control_findings WHERE task_id = ?",
                (task["id"],),
            ),
            "approvals": (
                """SELECT COUNT(*) AS count FROM control_human_approvals
                   WHERE entity_type = 'agent_task' AND entity_id = ?""",
                (task["id"],),
            ),
            "deployments": (
                "SELECT COUNT(*) AS count FROM control_deployments WHERE task_id = ?",
                (task["id"],),
            ),
            "metrics": (
                "SELECT COUNT(*) AS count FROM control_metrics WHERE task_id = ?",
                (task["id"],),
            ),
            "evidence": (
                """SELECT COUNT(*) AS count
                   FROM control_evidence_items item
                   JOIN control_evidence_packs pack
                     ON pack.id = item.evidence_pack_id
                   WHERE pack.task_id = ?""",
                (task["id"],),
            ),
            "open_attention": (
                """SELECT COUNT(*) AS count FROM control_attention_items
                   WHERE entity_type = 'agent_task' AND entity_id = ?
                     AND status = 'open'""",
                (task["id"],),
            ),
        }
        for name, (query, params) in related_queries.items():
            if int(conn.execute(query, params).fetchone()["count"] or 0):
                blockers.append(name)
        pack = conn.execute(
            """SELECT sha, status, summary, preview_url, risk_json, test_pack_json
               FROM control_evidence_packs WHERE task_id = ?""",
            (task["id"],),
        ).fetchone()
        expected_pack_status = (
            "cancelled" if expected_status == "cancelled" else "collecting"
        )
        allowed_summary = (
            "Vor Ausführung zurückgenommen."
            if expected_status == "cancelled"
            else ""
        )
        if (
            not pack
            or pack["sha"]
            or pack["status"] != expected_pack_status
            or pack["summary"] != allowed_summary
            or pack["preview_url"]
            or pack["risk_json"] not in ("", "{}")
            or pack["test_pack_json"] not in ("", "{}")
        ):
            blockers.append("evidence_pack")
        return blockers

    def _reactivate_cancelled_work_order(
        self,
        conn,
        *,
        work_order,
        candidate,
        verified_sha,
        actor,
        rationale,
    ):
        task = conn.execute(
            "SELECT * FROM control_agent_tasks WHERE work_order_id = ?",
            (work_order["id"],),
        ).fetchone()
        blockers = (
            self._unstarted_task_blockers(
                conn,
                task,
                expected_status="cancelled",
            )
            if task
            else ["task_missing"]
        )
        if blockers:
            raise ControlCenterError(
                "Der zurückgenommene Arbeitsauftrag ist nicht reaktivierbar.",
                code="work_order_reactivation_conflict",
                status=409,
            )
        conn.execute(
            """UPDATE control_work_orders
               SET status = 'approved', approval_sha = ?, approved_by = ?,
                   rationale = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ? AND status = 'cancelled'""",
            (verified_sha, actor, rationale, work_order["id"]),
        )
        conn.execute(
            """UPDATE control_agent_tasks
               SET status = 'queued', wake_reason = 'work_order',
                   base_sha = ?, finished_at = NULL, last_error = '',
                   wake_at = NULL, updated_at = CURRENT_TIMESTAMP
               WHERE id = ? AND status = 'cancelled'""",
            (verified_sha, task["id"]),
        )
        conn.execute(
            """UPDATE control_evidence_packs
               SET status = 'collecting', summary = '',
                   updated_at = CURRENT_TIMESTAMP
               WHERE task_id = ?""",
            (task["id"],),
        )
        self._audit(
            conn,
            project_id=int(candidate["project_id"]),
            entity_type="agent_task",
            entity_id=str(task["id"]),
            action="agent_task.requeued",
            actor=actor,
            from_state="cancelled",
            to_state="queued",
            reason=rationale,
            evidence={"work_order_id": work_order["id"], "unstarted": True},
        )

    @staticmethod
    def _candidate_activation_blockers(conn, candidate_id, campaign_id, wave):
        placeholders = ", ".join("?" for _ in ACTIVATION_COMPLETE_STATES)
        dependencies = conn.execute(
            f"""SELECT dependency.id, dependency.title, dependency.status,
                       contract.wave
                FROM control_pr_dependencies edge
                JOIN control_pr_candidates dependency
                  ON dependency.id = edge.depends_on_id
                LEFT JOIN control_candidate_contracts contract
                  ON contract.candidate_id = dependency.id
                WHERE edge.candidate_id = ?
                  AND dependency.status NOT IN ({placeholders})
                ORDER BY contract.wave ASC, dependency.priority ASC,
                         dependency.created_at ASC""",
            (candidate_id, *ACTIVATION_COMPLETE_STATES),
        ).fetchall()
        earlier_wave = []
        if int(wave or 0) > 1:
            earlier_wave = conn.execute(
                f"""SELECT candidate.id, candidate.title, candidate.status,
                           contract.wave
                    FROM control_pr_candidates candidate
                    JOIN control_candidate_contracts contract
                      ON contract.candidate_id = candidate.id
                    WHERE candidate.campaign_id = ?
                      AND candidate.id <> ?
                      AND contract.wave > 0
                      AND contract.wave < ?
                      AND candidate.status NOT IN ({placeholders})
                    ORDER BY contract.wave ASC, candidate.priority ASC,
                             candidate.created_at ASC""",
                (
                    campaign_id,
                    candidate_id,
                    int(wave),
                    *ACTIVATION_COMPLETE_STATES,
                ),
            ).fetchall()
        return dependencies, earlier_wave

    @staticmethod
    def _describe_activation_blockers(rows):
        return ", ".join(
            f"{row['id']} „{row['title']}“ ({row['status']}, Wave {int(row['wave'] or 0)})"
            for row in rows
        )

    def activate_candidate(self, candidate_id, *, approval_sha, actor="human", rationale=""):
        actor_name = clean_text(actor, "actor", maximum=120)
        explanation = str(rationale or "").strip()
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            policy = conn.execute(
                "SELECT mode, paused FROM control_settings WHERE singleton_id = 1"
            ).fetchone()
            if policy["paused"]:
                raise ControlCenterError(
                    "Control Center ist pausiert.",
                    code="control_center_paused",
                    status=409,
                )
            if policy["mode"] != "guided":
                raise ControlCenterError(
                    "Im Observer-Modus können keine Arbeitsaufträge aktiviert werden.",
                    code="observer_mode",
                    status=409,
                )
            candidate = conn.execute(
                """SELECT pc.*, c.project_id, c.status AS campaign_status,
                          contract.wave
                   FROM control_pr_candidates pc
                   JOIN control_campaigns c ON c.id = pc.campaign_id
                   LEFT JOIN control_candidate_contracts contract
                     ON contract.candidate_id = pc.id
                   WHERE pc.id = ?""",
                (candidate_id,),
            ).fetchone()
            if not candidate:
                raise ControlCenterError("PR Candidate nicht gefunden.", code="candidate_not_found", status=404)
            existing = conn.execute(
                "SELECT * FROM control_work_orders WHERE candidate_id = ?", (candidate_id,)
            ).fetchone()
            if existing and existing["status"] == "approved":
                work_order = dict(existing)
                self._ensure_agent_task(
                    conn,
                    work_order=work_order,
                    candidate=dict(candidate),
                    project_id=int(candidate["project_id"]),
                )
                conn.commit()
                return work_order
            if existing and existing["status"] != "cancelled":
                raise ControlCenterError(
                    "Für diesen PR Candidate existiert bereits ein nicht aktiver Arbeitsauftrag.",
                    code="work_order_conflict",
                    status=409,
                )
            if candidate["campaign_status"] != "approved":
                raise ControlCenterError(
                    "Zuerst muss die aktuelle Campaign-Version freigegeben werden.",
                    code="campaign_not_approved", status=409,
                )
            if candidate["status"] != "ready":
                raise ControlCenterError("PR Candidate ist nicht aktivierbar.", code="candidate_not_ready", status=409)
            self._simulate_campaign_in_connection(
                conn,
                str(candidate["campaign_id"]),
                persist=True,
            )
            candidate = conn.execute(
                """SELECT pc.*, c.project_id, c.status AS campaign_status,
                          contract.wave
                   FROM control_pr_candidates pc
                   JOIN control_campaigns c ON c.id = pc.campaign_id
                   JOIN control_candidate_contracts contract
                     ON contract.candidate_id = pc.id
                   WHERE pc.id = ?""",
                (candidate_id,),
            ).fetchone()
            dependencies, earlier_wave = self._candidate_activation_blockers(
                conn,
                candidate_id,
                str(candidate["campaign_id"]),
                int(candidate["wave"] or 0),
            )
            if dependencies:
                raise ControlCenterError(
                    "PR Candidate ist durch noch nicht abgeschlossene Abhängigkeiten "
                    "blockiert: "
                    + self._describe_activation_blockers(dependencies),
                    code="candidate_dependencies_pending",
                    status=409,
                )
            if earlier_wave:
                raise ControlCenterError(
                    f"PR Candidate ist für Wave {int(candidate['wave'])} geplant. "
                    "Zuerst müssen alle Candidates früherer Waves abgeschlossen sein: "
                    + self._describe_activation_blockers(earlier_wave),
                    code="candidate_wave_blocked",
                    status=409,
                )
            project = self._project(candidate["project_id"])
            verified_sha = self._resolve_sha(project, approval_sha, require=True)
            if verified_sha != str(candidate["base_sha"] or "").lower():
                raise ControlCenterError(
                    "Freigabe gilt nicht für den Basis-SHA dieses PR Candidates.",
                    code="approval_sha_mismatch", status=409,
                )
            if existing:
                work_order_id = str(existing["id"])
                self._reactivate_cancelled_work_order(
                    conn,
                    work_order=dict(existing),
                    candidate=dict(candidate),
                    verified_sha=verified_sha,
                    actor=actor_name,
                    rationale=explanation,
                )
                audit_action = "work_order.reapproved"
                audit_from_state = "cancelled"
            else:
                work_order_id = public_id("WO")
                conn.execute(
                    """INSERT INTO control_work_orders (
                           id, candidate_id, approval_sha, approved_by, rationale
                       ) VALUES (?, ?, ?, ?, ?)""",
                    (
                        work_order_id,
                        candidate_id,
                        verified_sha,
                        actor_name,
                        explanation,
                    ),
                )
                audit_action = "work_order.approved"
                audit_from_state = ""
            work_order = dict(conn.execute(
                "SELECT * FROM control_work_orders WHERE id = ?", (work_order_id,)
            ).fetchone())
            self._ensure_agent_task(
                conn,
                work_order=work_order,
                candidate=dict(candidate),
                project_id=int(candidate["project_id"]),
            )
            conn.execute(
                "UPDATE control_pr_candidates SET status = 'approved', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (candidate_id,),
            )
            self._resolve_attention(conn, "pr_candidate", candidate_id, "work_order_approval")
            self._audit(
                conn, project_id=int(candidate["project_id"]), entity_type="work_order",
                entity_id=work_order_id, action=audit_action, actor=actor_name,
                from_state=audit_from_state, to_state="approved", reason=explanation,
                evidence={
                    "candidate_id": candidate_id,
                    "campaign_id": candidate["campaign_id"],
                    "sha": verified_sha,
                },
            )
            conn.commit()
            return work_order

    def cancel_unstarted_work_order(
        self,
        work_order_id,
        *,
        actor="human",
        reason="",
    ):
        """Withdraw an approved work order before any executor activity."""
        actor_name = clean_text(actor, "actor", maximum=120)
        explanation = clean_text(reason, "reason", maximum=2000)
        with self.db._get_connection() as conn:
            # This serializes the state check against executor leasing.
            conn.execute("BEGIN IMMEDIATE")
            work_order = conn.execute(
                """SELECT wo.*, pc.campaign_id, pc.title AS candidate_title,
                          pc.risk_level, pc.status AS candidate_status,
                          c.project_id
                   FROM control_work_orders wo
                   JOIN control_pr_candidates pc ON pc.id = wo.candidate_id
                   JOIN control_campaigns c ON c.id = pc.campaign_id
                   WHERE wo.id = ?""",
                (str(work_order_id),),
            ).fetchone()
            if not work_order:
                raise ControlCenterError(
                    "Arbeitsauftrag nicht gefunden.",
                    code="work_order_not_found",
                    status=404,
                )
            task = conn.execute(
                "SELECT * FROM control_agent_tasks WHERE work_order_id = ?",
                (work_order["id"],),
            ).fetchone()
            if work_order["status"] == "cancelled":
                if (
                    not task
                    or task["status"] != "cancelled"
                    or work_order["candidate_status"] != "ready"
                ):
                    raise ControlCenterError(
                        "Der Rücknahmezustand des Arbeitsauftrags ist inkonsistent.",
                        code="work_order_cancel_conflict",
                        status=409,
                    )
                conn.commit()
                return {
                    "work_order": dict(work_order),
                    "task": self._row(
                        task,
                        ("allowed_actions_json", "protected_paths_json"),
                    ),
                    "candidate_id": str(work_order["candidate_id"]),
                    "idempotent": True,
                }
            if (
                work_order["status"] != "approved"
                or work_order["candidate_status"] != "approved"
                or not task
            ):
                raise ControlCenterError(
                    "Nur ein freigegebener, noch nicht gestarteter Arbeitsauftrag "
                    "kann zurückgenommen werden.",
                    code="work_order_cancel_conflict",
                    status=409,
                )
            blockers = self._unstarted_task_blockers(
                conn,
                task,
                expected_status="queued",
            )
            if blockers:
                raise ControlCenterError(
                    "Der Arbeitsauftrag wurde bereits gestartet und kann nicht "
                    "mehr zurückgenommen werden.",
                    code="work_order_already_started",
                    status=409,
                )
            updated = conn.execute(
                """UPDATE control_agent_tasks
                   SET status = 'cancelled',
                       wake_reason = 'work_order_cancelled',
                       finished_at = CURRENT_TIMESTAMP,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = 'queued' AND attempt = 0""",
                (task["id"],),
            )
            if updated.rowcount != 1:
                raise ControlCenterError(
                    "Der Arbeitsauftrag wurde parallel gestartet.",
                    code="work_order_already_started",
                    status=409,
                )
            conn.execute(
                """UPDATE control_evidence_packs
                   SET status = 'cancelled',
                       summary = 'Vor Ausführung zurückgenommen.',
                       updated_at = CURRENT_TIMESTAMP
                   WHERE task_id = ?""",
                (task["id"],),
            )
            work_order_update = conn.execute(
                """UPDATE control_work_orders
                   SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = 'approved'""",
                (work_order["id"],),
            )
            candidate_update = conn.execute(
                """UPDATE control_pr_candidates
                   SET status = 'ready', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = 'approved'""",
                (work_order["candidate_id"],),
            )
            if work_order_update.rowcount != 1 or candidate_update.rowcount != 1:
                raise ControlCenterError(
                    "Der Arbeitsauftrag wurde parallel verändert.",
                    code="work_order_cancel_conflict",
                    status=409,
                )
            self._attention(
                conn,
                project_id=int(work_order["project_id"]),
                category="work_order_approval",
                entity_type="pr_candidate",
                entity_id=str(work_order["candidate_id"]),
                title=f"PR-Slice „{work_order['candidate_title']}“ aktivieren",
                consequence=(
                    "Der zurückgenommene Slice bleibt ohne neue Freigabe inaktiv."
                ),
                recommendation=(
                    "Abhängigkeiten, Scope und exakten Basis-SHA erneut prüfen."
                ),
                urgency=(
                    "high"
                    if work_order["risk_level"] in {"high", "critical"}
                    else "normal"
                ),
            )
            evidence = {
                "work_order_id": str(work_order["id"]),
                "candidate_id": str(work_order["candidate_id"]),
                "campaign_id": str(work_order["campaign_id"]),
                "task_id": str(task["id"]),
                "unstarted": True,
            }
            self._audit(
                conn,
                project_id=int(work_order["project_id"]),
                entity_type="agent_task",
                entity_id=str(task["id"]),
                action="agent_task.cancelled",
                actor=actor_name,
                from_state="queued",
                to_state="cancelled",
                reason=explanation,
                evidence=evidence,
            )
            self._audit(
                conn,
                project_id=int(work_order["project_id"]),
                entity_type="work_order",
                entity_id=str(work_order["id"]),
                action="work_order.cancelled",
                actor=actor_name,
                from_state="approved",
                to_state="cancelled",
                reason=explanation,
                evidence=evidence,
            )
            conn.commit()
            return {
                "work_order": dict(
                    conn.execute(
                        "SELECT * FROM control_work_orders WHERE id = ?",
                        (work_order["id"],),
                    ).fetchone()
                ),
                "task": self._row(
                    conn.execute(
                        "SELECT * FROM control_agent_tasks WHERE id = ?",
                        (task["id"],),
                    ).fetchone(),
                    ("allowed_actions_json", "protected_paths_json"),
                ),
                "candidate_id": str(work_order["candidate_id"]),
                "idempotent": False,
            }
