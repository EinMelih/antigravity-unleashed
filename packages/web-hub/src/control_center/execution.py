"""Durable multi-project task scheduling, leases, retries, and wake-ups."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from src.control_center.common import (
    TASK_STATES,
    ControlCenterError,
    clean_text,
    public_id,
)


ACTIVE_TASK_STATES = {
    "leased",
    "running",
    "waiting_ci",
    "waiting_review",
    "repair",
}
FINISHED_CANDIDATE_STATES = {"completed", "merged", "deployed", "obsolete"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_sqlite_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _branch_name(candidate_id: str, title: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:42]
    suffix = candidate_id.lower().replace("_", "-")
    return f"ag/{suffix}-{slug or 'change'}"[:100]


class ExecutionMixin:
    def _ensure_agent_task(
        self,
        conn,
        *,
        work_order: Dict[str, Any],
        candidate: Dict[str, Any],
        project_id: int,
    ) -> Dict[str, Any]:
        existing = conn.execute(
            "SELECT * FROM control_agent_tasks WHERE work_order_id = ?",
            (work_order["id"],),
        ).fetchone()
        if existing:
            return self._row(
                existing,
                ("allowed_actions_json", "protected_paths_json"),
            )
        policy = conn.execute(
            "SELECT * FROM control_repository_policies WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        if not policy:
            repository_policy = self._repository_policy_in_connection(conn, project_id)
            capability = repository_policy["capability"]
            protected_paths = repository_policy["protected_paths"]
        else:
            capability = json.loads(policy["capability_json"] or "{}")
            protected_paths = json.loads(policy["protected_paths_json"] or "[]")
        allowed_actions = [
            action for action, permitted in capability.items() if bool(permitted)
        ]
        task_id = public_id("TASK")
        conn.execute(
            """INSERT INTO control_agent_tasks (
                   id, work_order_id, project_id, campaign_id, candidate_id,
                   base_sha, branch_name, allowed_actions_json,
                   protected_paths_json
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task_id,
                work_order["id"],
                project_id,
                candidate["campaign_id"],
                candidate["id"],
                work_order["approval_sha"],
                _branch_name(candidate["id"], candidate["title"]),
                json.dumps(allowed_actions, ensure_ascii=False),
                json.dumps(protected_paths, ensure_ascii=False),
            ),
        )
        conn.execute(
            """INSERT INTO control_evidence_packs (
                   id, task_id, project_id, candidate_id, rollback_plan
               ) VALUES (?, ?, ?, ?, ?)""",
            (
                public_id("EVD"),
                task_id,
                project_id,
                candidate["id"],
                str(
                    (
                        conn.execute(
                            """SELECT rollback_plan FROM control_campaign_profiles
                               WHERE campaign_id = ?""",
                            (candidate["campaign_id"],),
                        ).fetchone()
                        or {"rollback_plan": ""}
                    )["rollback_plan"]
                    or ""
                ),
            ),
        )
        self._audit(
            conn,
            project_id=project_id,
            entity_type="agent_task",
            entity_id=task_id,
            action="agent_task.queued",
            actor="orchestrator",
            to_state="queued",
            evidence={
                "work_order_id": work_order["id"],
                "candidate_id": candidate["id"],
                "branch_name": _branch_name(candidate["id"], candidate["title"]),
            },
        )
        row = conn.execute(
            "SELECT * FROM control_agent_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        return self._row(row, ("allowed_actions_json", "protected_paths_json"))

    def get_task(self, task_id: str) -> Dict[str, Any]:
        with self.db._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM control_agent_tasks WHERE id = ?",
                (str(task_id),),
            ).fetchone()
        if not row:
            raise ControlCenterError(
                "Agent Task nicht gefunden.",
                code="task_not_found",
                status=404,
            )
        return self._row(row, ("allowed_actions_json", "protected_paths_json"))

    def list_tasks(
        self,
        *,
        project_id: Any = None,
        campaign_id: str = "",
        status: str = "",
    ) -> list[Dict[str, Any]]:
        query = (
            "SELECT task.* FROM control_agent_tasks task "
            "JOIN projects project ON project.id = task.project_id "
            "WHERE project.archived_at IS NULL"
        )
        params: list[Any] = []
        if project_id not in (None, ""):
            project = self._project(project_id)
            query += " AND task.project_id = ?"
            params.append(int(project["id"]))
        if campaign_id:
            query += " AND task.campaign_id = ?"
            params.append(campaign_id)
        if status:
            statuses = [item.strip() for item in status.split(",") if item.strip()]
            unknown = set(statuses) - TASK_STATES
            if unknown:
                raise ControlCenterError(
                    "Unbekannter Task-Status.",
                    code="invalid_task_status",
                )
            placeholders = ",".join("?" for _ in statuses)
            query += f" AND task.status IN ({placeholders})"
            params.extend(statuses)
        query += " ORDER BY task.created_at DESC"
        with self.db._get_connection() as conn:
            return [
                self._row(row, ("allowed_actions_json", "protected_paths_json"))
                for row in conn.execute(query, params).fetchall()
            ]

    @staticmethod
    def _dependencies_finished(conn, candidate_id: str) -> bool:
        row = conn.execute(
            """SELECT COUNT(*) AS blocked
               FROM control_pr_dependencies d
               JOIN control_pr_candidates dependency ON dependency.id = d.depends_on_id
               WHERE d.candidate_id = ?
                 AND dependency.status NOT IN ('completed', 'merged', 'deployed', 'obsolete')""",
            (candidate_id,),
        ).fetchone()
        return int(row["blocked"]) == 0

    @staticmethod
    def _conflicts_with_active(conn, candidate_id: str) -> bool:
        row = conn.execute(
            """SELECT COUNT(*) AS blocked
               FROM control_candidate_conflicts conflict
               JOIN control_agent_tasks task
                 ON task.candidate_id = CASE
                     WHEN conflict.candidate_id = ? THEN conflict.conflicts_with_id
                     ELSE conflict.candidate_id
                 END
               WHERE (conflict.candidate_id = ? OR conflict.conflicts_with_id = ?)
                 AND task.status IN ('leased', 'running', 'waiting_ci',
                                     'waiting_review', 'repair')""",
            (candidate_id, candidate_id, candidate_id),
        ).fetchone()
        return int(row["blocked"]) > 0

    def activate_ready_wave(
        self,
        campaign_id: str,
        *,
        actor: str = "orchestrator",
    ) -> Dict[str, Any]:
        global_policy = self.get_policy()
        if global_policy["paused"]:
            raise ControlCenterError(
                "Control Center ist pausiert.",
                code="control_center_paused",
                status=409,
            )
        if global_policy["mode"] not in {"campaign", "autopilot"}:
            raise ControlCenterError(
                "Automatische Waves benötigen Campaign- oder Autopilot-Modus.",
                code="campaign_mode_required",
                status=409,
            )
        actor_name = clean_text(actor, "actor", maximum=120)
        with self.db._get_connection() as conn:
            campaign = self._campaign(conn, campaign_id)
            if campaign["status"] not in {"approved", "active"}:
                raise ControlCenterError(
                    "Campaign ist nicht für die Ausführung freigegeben.",
                    code="campaign_not_approved",
                    status=409,
                )
            profile = conn.execute(
                "SELECT * FROM control_campaign_profiles WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            if not profile or profile["activation_policy"] not in {
                "campaign_wave",
                "autopilot",
            }:
                raise ControlCenterError(
                    "Campaign benötigt eine Wave-Aktivierungs-Policy.",
                    code="wave_activation_not_allowed",
                    status=409,
                )
            if self._complete_campaign_if_done(
                conn,
                campaign_id,
                actor=actor_name,
            ):
                conn.commit()
                return {
                    "campaign_id": campaign_id,
                    "activated": [],
                    "remaining_capacity": 0,
                    "reason": "campaign_completed",
                }
            policy = self._repository_policy_in_connection(
                conn,
                int(campaign["project_id"]),
            )
            open_count = int(
                conn.execute(
                    """SELECT COUNT(*) AS count FROM control_agent_tasks
                       WHERE project_id = ?
                         AND status NOT IN ('completed', 'failed', 'cancelled')""",
                    (int(campaign["project_id"]),),
                ).fetchone()["count"]
            )
            available = max(0, int(policy["max_open_prs"]) - open_count)
            if available == 0:
                return {
                    "campaign_id": campaign_id,
                    "activated": [],
                    "reason": "max_open_prs",
                }
            terminal_placeholders = ", ".join(
                "?" for _ in FINISHED_CANDIDATE_STATES
            )
            open_wave = conn.execute(
                f"""SELECT MIN(cc.wave) AS wave
                    FROM control_pr_candidates pc
                    JOIN control_candidate_contracts cc
                      ON cc.candidate_id = pc.id
                    WHERE pc.campaign_id = ?
                      AND pc.status NOT IN ({terminal_placeholders})""",
                (campaign_id, *sorted(FINISHED_CANDIDATE_STATES)),
            ).fetchone()
            current_wave = (
                int(open_wave["wave"])
                if open_wave and open_wave["wave"] is not None
                else None
            )
            rows = conn.execute(
                """SELECT pc.*, cc.wave, cc.ready_score, cc.pinned, cc.paused
                   FROM control_pr_candidates pc
                   JOIN control_candidate_contracts cc ON cc.candidate_id = pc.id
                   LEFT JOIN control_work_orders wo ON wo.candidate_id = pc.id
                   WHERE pc.campaign_id = ? AND pc.status = 'ready'
                     AND wo.id IS NULL AND cc.paused = 0 AND cc.wave = ?
                   ORDER BY cc.pinned DESC, cc.wave ASC, cc.ready_score DESC,
                            pc.priority ASC, pc.created_at ASC""",
                (campaign_id, current_wave),
            ).fetchall()
            activated = []
            for candidate in rows:
                if len(activated) >= available:
                    break
                candidate_id = str(candidate["id"])
                if not self._dependencies_finished(conn, candidate_id):
                    continue
                if self._conflicts_with_active(conn, candidate_id):
                    continue
                work_order_id = public_id("WO")
                conn.execute(
                    """INSERT INTO control_work_orders (
                           id, candidate_id, status, approval_sha, approved_by, rationale
                       ) VALUES (?, ?, 'approved', ?, ?, ?)""",
                    (
                        work_order_id,
                        candidate_id,
                        campaign["approved_sha"],
                        actor_name,
                        "Campaign-Wave-Freigabe",
                    ),
                )
                conn.execute(
                    """UPDATE control_pr_candidates
                       SET status = 'approved', updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (candidate_id,),
                )
                work_order = dict(
                    conn.execute(
                        "SELECT * FROM control_work_orders WHERE id = ?",
                        (work_order_id,),
                    ).fetchone()
                )
                task = self._ensure_agent_task(
                    conn,
                    work_order=work_order,
                    candidate=dict(candidate),
                    project_id=int(campaign["project_id"]),
                )
                self._resolve_attention(
                    conn,
                    "pr_candidate",
                    candidate_id,
                    "work_order_approval",
                )
                activated.append(
                    {
                        "candidate_id": candidate_id,
                        "work_order_id": work_order_id,
                        "task_id": task["id"],
                    }
                )
            if activated:
                conn.execute(
                    """UPDATE control_campaigns
                       SET status = 'active', updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (campaign_id,),
                )
                conn.execute(
                    """UPDATE control_campaign_profiles
                       SET current_wave = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE campaign_id = ?""",
                    (current_wave, campaign_id),
                )
                self._audit(
                    conn,
                    project_id=int(campaign["project_id"]),
                    entity_type="campaign",
                    entity_id=campaign_id,
                    action="campaign.wave_activated",
                    actor=actor_name,
                    evidence={"activated": activated},
                )
            conn.commit()
            return {
                "campaign_id": campaign_id,
                "activated": activated,
                "remaining_capacity": max(0, available - len(activated)),
            }

    def recover_expired_leases(self) -> int:
        now = _utcnow()
        recovered = 0
        with self.db._get_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM control_agent_tasks
                   WHERE status IN ('leased', 'running', 'repair')
                     AND lease_until IS NOT NULL""",
            ).fetchall()
            for row in rows:
                expires = _parse_sqlite_time(row["lease_until"])
                if not expires or expires > now:
                    continue
                conn.execute(
                    """UPDATE control_agent_tasks
                       SET status = 'queued', wake_reason = 'lease_expired',
                           lease_owner = '', lease_token = '', lease_until = NULL,
                           updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (row["id"],),
                )
                self._audit(
                    conn,
                    project_id=int(row["project_id"]),
                    entity_type="agent_task",
                    entity_id=str(row["id"]),
                    action="agent_task.lease_recovered",
                    actor="orchestrator",
                    from_state=str(row["status"]),
                    to_state="queued",
                )
                recovered += 1
            conn.commit()
        return recovered

    def resume_task_after_operator_fix(
        self,
        task_id: str,
        *,
        actor: str,
        reason: str,
    ) -> Dict[str, Any]:
        """Requeue one interrupted task without spending another retry attempt.

        This recovery path is deliberately limited to an explicitly paused
        control plane. It preserves all materialized GitHub and Anti-Gravity
        identities so the executor continues the same task after an
        infrastructure/code fix instead of creating a replacement task.
        """

        actor_name = clean_text(actor, "actor", maximum=120)
        resume_reason = clean_text(reason, "reason", maximum=1000)
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            policy = conn.execute(
                "SELECT paused FROM control_settings WHERE singleton_id = 1"
            ).fetchone()
            if not policy or not bool(policy["paused"]):
                raise ControlCenterError(
                    "Operator-Resume benötigt einen global pausierten Hub.",
                    code="operator_resume_requires_pause",
                    status=409,
                )
            task = conn.execute(
                "SELECT * FROM control_agent_tasks WHERE id = ?",
                (str(task_id),),
            ).fetchone()
            if not task:
                raise ControlCenterError(
                    "Agent Task nicht gefunden.",
                    code="task_not_found",
                    status=404,
                )
            if (
                task["status"] == "queued"
                and task["wake_reason"] == "operator_resume"
            ):
                conn.commit()
                return self.get_task(str(task_id))
            repair_resume = (
                task["status"] == "repair"
                and task["wake_reason"] in {
                    "retry:executor_failure",
                    "protected_path_rejected",
                }
            )
            failed_resume = (
                task["status"] == "failed"
                and (
                    task["wake_reason"] == "failed:executor_failure"
                    or (
                        task["wake_reason"] == "agent_execution"
                        and str(task["last_error"] or "").startswith(
                            "Executor-Fehler:"
                        )
                    )
                )
            )
            blocking_review_findings = int(
                conn.execute(
                    """SELECT COUNT(*) AS count
                       FROM control_findings
                       WHERE task_id = ? AND status = 'open'
                         AND classification IN ('BLOCKER', 'REQUIRED')""",
                    (task["id"],),
                ).fetchone()["count"]
            )
            review_resume = (
                task["status"] in {"waiting_ci", "waiting_review"}
                and task["wake_reason"] in {
                    "github_checks",
                    "review_and_evidence",
                }
                and bool(task["current_sha"])
                and blocking_review_findings > 0
            )
            if not repair_resume and not failed_resume and not review_resume:
                raise ControlCenterError(
                    "Nur ein gestoppter systemischer Executor-Repair oder ein "
                    "SHA-gebundener Review mit offenem BLOCKER/REQUIRED-Finding "
                    "kann so fortgesetzt werden.",
                    code="operator_resume_not_allowed",
                    status=409,
                )
            if task["merged_sha"]:
                raise ControlCenterError(
                    "Ein bereits gemergter Task darf nicht erneut gestartet werden.",
                    code="operator_resume_merged_task",
                    status=409,
                )
            if task["lease_owner"] or task["lease_token"] or task["lease_until"]:
                raise ControlCenterError(
                    "Der Task besitzt noch eine aktive Lease.",
                    code="operator_resume_active_lease",
                    status=409,
                )
            previous_attempt = int(task["attempt"])
            refunded_attempt = max(0, previous_attempt - 1)
            conn.execute(
                """UPDATE control_agent_tasks
                   SET status = 'queued', wake_reason = 'operator_resume',
                       attempt = ?, wake_at = NULL, finished_at = NULL,
                       lease_owner = '', lease_token = '', lease_until = NULL,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (refunded_attempt, task["id"]),
            )
            conn.execute(
                """UPDATE control_pr_candidates
                   SET status = 'approved', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (task["candidate_id"],),
            )
            self._audit(
                conn,
                project_id=int(task["project_id"]),
                entity_type="agent_task",
                entity_id=str(task["id"]),
                action="agent_task.operator_resumed",
                actor=actor_name,
                from_state=str(task["status"]),
                to_state="queued",
                reason=resume_reason,
                evidence={
                    "attempt_before": previous_attempt,
                    "attempt_after": refunded_attempt,
                    "resume_kind": (
                        "review_after_system_fix"
                        if review_resume
                        else "executor_after_system_fix"
                    ),
                    "blocking_review_findings": blocking_review_findings,
                    "previous_error": str(task["last_error"] or "")[:5000],
                    "previous_wake_reason": str(task["wake_reason"] or ""),
                    "work_order_id": task["work_order_id"],
                    "issue_number": task["issue_number"],
                    "worktree_path": task["worktree_path"],
                    "branch_name": task["branch_name"],
                    "antigravity_chat_id": task["antigravity_chat_id"],
                    "pr_number": task["pr_number"],
                },
            )
            conn.commit()
        return self.get_task(str(task_id))

    def lease_next_task(
        self,
        worker_id: str,
        *,
        project_id: Any = None,
    ) -> Optional[Dict[str, Any]]:
        worker = clean_text(worker_id, "worker_id", maximum=120)
        policy = self.get_policy()
        if policy["paused"] or policy["mode"] == "observer":
            return None
        selected_project = (
            self._project(project_id) if project_id not in (None, "") else None
        )
        now = _utcnow()
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            query = """
                SELECT task.*, pc.priority, cc.ready_score, cc.pinned
                FROM control_agent_tasks task
                JOIN control_pr_candidates pc ON pc.id = task.candidate_id
                JOIN control_candidate_contracts cc ON cc.candidate_id = task.candidate_id
                WHERE task.status IN ('queued', 'repair')
                  AND (task.wake_at IS NULL OR task.wake_at <= CURRENT_TIMESTAMP)
            """
            params: list[Any] = []
            if selected_project:
                query += " AND task.project_id = ?"
                params.append(int(selected_project["id"]))
            query += """
                ORDER BY cc.pinned DESC, cc.ready_score DESC,
                         pc.priority ASC, task.created_at ASC
            """
            candidates = conn.execute(query, params).fetchall()
            selected = None
            selected_policy = None
            selected_attempt_increment = 1
            for row in candidates:
                repo_policy = self._repository_policy_in_connection(
                    conn,
                    int(row["project_id"]),
                )
                publish_continuation = (
                    str(row["wake_reason"] or "") == "protected_path_approved"
                )
                operator_refund_continuation = (
                    str(row["wake_reason"] or "") == "operator_resume"
                    and int(row["attempt"]) > 0
                )
                if (
                    not publish_continuation
                    and int(row["attempt"])
                    > int(repo_policy["max_retry_attempts"])
                ):
                    continue
                active_count = int(
                    conn.execute(
                        """SELECT COUNT(*) AS count FROM control_agent_tasks
                           WHERE project_id = ?
                             AND status IN ('leased', 'running')""",
                        (int(row["project_id"]),),
                    ).fetchone()["count"]
                )
                if active_count >= int(repo_policy["max_parallel_tasks"]):
                    continue
                if not self._dependencies_finished(conn, str(row["candidate_id"])):
                    continue
                if self._conflicts_with_active(conn, str(row["candidate_id"])):
                    continue
                selected = row
                selected_policy = repo_policy
                selected_attempt_increment = (
                    0
                    if publish_continuation or operator_refund_continuation
                    else 1
                )
                break
            if not selected:
                conn.commit()
                return None
            token = secrets.token_urlsafe(24)
            lease_until = now + timedelta(
                seconds=int(selected_policy["lease_seconds"])
            )
            updated = conn.execute(
                """UPDATE control_agent_tasks
                   SET status = 'leased', lease_owner = ?, lease_token = ?,
                       lease_until = ?, attempt = attempt + ?,
                       started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status IN ('queued', 'repair')
                     AND (
                         wake_reason = 'protected_path_approved'
                         OR attempt <= ?
                     )""",
                (
                    worker,
                    token,
                    lease_until.isoformat(sep=" ", timespec="seconds"),
                    selected_attempt_increment,
                    selected["id"],
                    int(selected_policy["max_retry_attempts"]),
                ),
            )
            if updated.rowcount != 1:
                conn.rollback()
                return None
            self._audit(
                conn,
                project_id=int(selected["project_id"]),
                entity_type="agent_task",
                entity_id=str(selected["id"]),
                action="agent_task.leased",
                actor=worker,
                from_state=str(selected["status"]),
                to_state="leased",
                evidence={
                    "lease_until": lease_until.isoformat(),
                    "attempt_increment": selected_attempt_increment,
                    "publish_continuation": publish_continuation,
                    "operator_refund_continuation": (
                        operator_refund_continuation
                    ),
                },
            )
            conn.commit()
        result = self.get_task(str(selected["id"]))
        result["lease_token"] = token
        return result

    def heartbeat_task(
        self,
        task_id: str,
        *,
        worker_id: str,
        lease_token: str,
    ) -> Dict[str, Any]:
        worker = clean_text(worker_id, "worker_id", maximum=120)
        token = clean_text(lease_token, "lease_token", maximum=200)
        task = self.get_task(task_id)
        repo_policy = self.get_repository_policy(task["project_id"])
        lease_until = _utcnow() + timedelta(seconds=int(repo_policy["lease_seconds"]))
        with self.db._get_connection() as conn:
            updated = conn.execute(
                """UPDATE control_agent_tasks
                   SET lease_until = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND lease_owner = ? AND lease_token = ?
                     AND status IN ('leased', 'running', 'repair')""",
                (
                    lease_until.isoformat(sep=" ", timespec="seconds"),
                    task_id,
                    worker,
                    token,
                ),
            )
            if updated.rowcount != 1:
                raise ControlCenterError(
                    "Task-Lease ist nicht mehr gültig.",
                    code="invalid_task_lease",
                    status=409,
                )
            conn.commit()
        return self.get_task(task_id)

    def transition_task(
        self,
        task_id: str,
        *,
        to_state: str,
        actor: str,
        lease_token: str = "",
        reason: str = "",
        fields: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if to_state not in TASK_STATES:
            raise ControlCenterError(
                "Unbekannter Task-Zielstatus.",
                code="invalid_task_status",
            )
        task = self.get_task(task_id)
        mutable_without_lease = {
            "paused",
            "cancelled",
            "waiting_review",
            "waiting_human",
            "repair",
        }
        if to_state not in mutable_without_lease:
            if not lease_token or lease_token != task["lease_token"]:
                raise ControlCenterError(
                    "Task-Lease ist für diese Änderung erforderlich.",
                    code="task_lease_required",
                    status=409,
                )
        allowed_fields = {
            "current_sha",
            "worktree_path",
            "antigravity_chat_id",
            "issue_number",
            "issue_url",
            "pr_number",
            "pr_url",
            "last_checkpoint_id",
            "last_error",
            "wake_reason",
            "wake_at",
            "consumed_tokens",
        }
        values = fields or {}
        unknown = set(values) - allowed_fields
        if unknown:
            raise ControlCenterError(
                f"Unbekannte Task-Felder: {', '.join(sorted(unknown))}",
                code="invalid_task_fields",
            )
        assignments = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
        params: list[Any] = [to_state]
        for key, value in values.items():
            assignments.append(f"{key} = ?")
            params.append(value)
        if to_state in {
            "waiting_ci",
            "waiting_review",
            "waiting_human",
            "repair",
            "paused",
            "completed",
            "failed",
            "cancelled",
        }:
            assignments.extend(
                [
                    "lease_owner = ''",
                    "lease_token = ''",
                    "lease_until = NULL",
                ]
            )
        if to_state in {"completed", "failed", "cancelled"}:
            assignments.extend(
                [
                    "finished_at = CURRENT_TIMESTAMP",
                ]
            )
        params.append(task_id)
        with self.db._get_connection() as conn:
            conn.execute(
                f"UPDATE control_agent_tasks SET {', '.join(assignments)} WHERE id = ?",
                params,
            )
            candidate_status = {
                "running": "running",
                "waiting_ci": "draft_pr",
                "waiting_review": "review",
                "waiting_human": "human_test",
                "completed": "completed",
                "failed": "failed",
                "paused": "paused",
                "cancelled": "cancelled",
            }.get(to_state)
            if candidate_status:
                conn.execute(
                    """UPDATE control_pr_candidates
                       SET status = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (candidate_status, task["candidate_id"]),
                )
            self._audit(
                conn,
                project_id=int(task["project_id"]),
                entity_type="agent_task",
                entity_id=task_id,
                action=f"agent_task.{to_state}",
                actor=str(actor or "orchestrator")[:120],
                from_state=str(task["status"]),
                to_state=to_state,
                reason=str(reason or "")[:5000],
                evidence=values,
            )
            conn.commit()
        return self.get_task(task_id)

    def record_task_progress(
        self,
        task_id: str,
        *,
        worker_id: str,
        lease_token: str,
        progress: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not isinstance(progress, dict) or not progress:
            raise ControlCenterError(
                "progress muss ein nichtleeres Objekt sein.",
                code="invalid_progress",
            )
        task = self.get_task(task_id)
        if task["lease_owner"] != worker_id or task["lease_token"] != lease_token:
            raise ControlCenterError(
                "Task-Lease ist nicht mehr gültig.",
                code="invalid_task_lease",
                status=409,
            )
        fingerprint = hashlib.sha256(
            json.dumps(progress, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        repeated = fingerprint == str(task["last_progress_hash"] or "")
        no_progress = int(task["no_progress_count"]) + 1 if repeated else 0
        policy = self.get_repository_policy(task["project_id"])
        with self.db._get_connection() as conn:
            conn.execute(
                """UPDATE control_agent_tasks
                   SET last_progress_hash = ?, no_progress_count = ?,
                       status = CASE WHEN ? >= ? THEN 'paused' ELSE status END,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (
                    fingerprint,
                    no_progress,
                    no_progress,
                    int(policy["no_progress_limit"]),
                    task_id,
                ),
            )
            checkpoint_id = public_id("CHK")
            conn.execute(
                """INSERT INTO control_checkpoints (
                       id, project_id, entity_type, entity_id, actor,
                       summary, payload_json
                   ) VALUES (?, ?, 'agent_task', ?, ?, ?, ?)""",
                (
                    checkpoint_id,
                    int(task["project_id"]),
                    task_id,
                    worker_id[:120],
                    str(progress.get("summary") or "Task-Fortschritt")[:5000],
                    json.dumps(progress, ensure_ascii=False),
                ),
            )
            conn.execute(
                """UPDATE control_agent_tasks SET last_checkpoint_id = ?
                   WHERE id = ?""",
                (checkpoint_id, task_id),
            )
            if no_progress >= int(policy["no_progress_limit"]):
                self._attention(
                    conn,
                    project_id=int(task["project_id"]),
                    category="no_progress",
                    entity_type="agent_task",
                    entity_id=task_id,
                    title="Agent Task ohne nachweisbaren Fortschritt",
                    consequence="Automatische Wiederholungen wurden pausiert.",
                    recommendation="Fehlerursache und letzten Checkpoint prüfen.",
                    urgency="high",
                )
            self._audit(
                conn,
                project_id=int(task["project_id"]),
                entity_type="agent_task",
                entity_id=task_id,
                action="agent_task.progress",
                actor=worker_id[:120],
                evidence={
                    "checkpoint_id": checkpoint_id,
                    "fingerprint": fingerprint,
                    "no_progress_count": no_progress,
                },
            )
            conn.commit()
        return self.get_task(task_id)

    def enqueue_task_event(
        self,
        task_id: str,
        *,
        event_type: str,
        dedupe_key: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        self.get_task(task_id)
        if not isinstance(payload, dict):
            raise ControlCenterError(
                "Event-Payload muss ein Objekt sein.",
                code="invalid_event_payload",
            )
        event_id = public_id("EVT")
        with self.db._get_connection() as conn:
            existing = conn.execute(
                "SELECT * FROM control_task_events WHERE dedupe_key = ?",
                (dedupe_key,),
            ).fetchone()
            if existing:
                return self._row(existing, ("payload_json",))
            conn.execute(
                """INSERT INTO control_task_events (
                       id, task_id, event_type, dedupe_key, payload_json
                   ) VALUES (?, ?, ?, ?, ?)""",
                (
                    event_id,
                    task_id,
                    clean_text(event_type, "event_type", maximum=120),
                    clean_text(dedupe_key, "dedupe_key", maximum=250),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            conn.commit()
            return self._row(
                conn.execute(
                    "SELECT * FROM control_task_events WHERE id = ?",
                    (event_id,),
                ).fetchone(),
                ("payload_json",),
            )
