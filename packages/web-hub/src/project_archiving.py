"""Safe, reversible Hub project archiving without filesystem side effects."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict

from src.database import Database


ACTIVE_TASK_STATES = (
    "queued",
    "leased",
    "running",
    "waiting_ci",
    "waiting_review",
    "waiting_human",
    "repair",
    "paused",
)
ACTIVE_CAMPAIGN_STATES = ("draft", "approved", "active", "paused")
ACTIVE_CANDIDATE_STATES = (
    "ready",
    "approved",
    "queued",
    "leased",
    "running",
    "waiting_ci",
    "waiting_review",
    "waiting_human",
    "repair",
    "paused",
    "failed",
)


class ProjectNotFoundError(LookupError):
    """Raised when an archive operation references an unknown project."""


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone() is not None


def _count(conn: sqlite3.Connection, query: str, params=()) -> int:
    return int(conn.execute(query, params).fetchone()[0])


def _state_counts(
    conn: sqlite3.Connection,
    table: str,
    project_join: str,
    project_id: int,
    active_states: tuple[str, ...],
) -> Dict[str, int]:
    if not _has_table(conn, table):
        return {"total": 0, "active": 0}
    placeholders = ",".join("?" for _ in active_states)
    total = _count(
        conn,
        f"SELECT COUNT(*) FROM {table} {project_join}",
        (project_id,),
    )
    active = _count(
        conn,
        f"SELECT COUNT(*) FROM {table} {project_join} AND status IN ({placeholders})",
        (project_id, *active_states),
    )
    return {"total": total, "active": active}


def _impact(conn: sqlite3.Connection, project: Dict[str, Any]) -> Dict[str, Any]:
    project_id = int(project["id"])
    issues = _state_counts(
        conn,
        "issues",
        "WHERE project_id = ?",
        project_id,
        ("pending", "running", "open"),
    )
    agent_runs = {"total": 0, "active": 0}
    subtasks = {"total": 0, "active": 0}
    if _has_table(conn, "agent_runs"):
        agent_runs = {
            "total": _count(
                conn,
                """SELECT COUNT(*) FROM agent_runs run
                   JOIN issues issue ON issue.id = run.issue_id
                   WHERE issue.project_id = ?""",
                (project_id,),
            ),
            "active": _count(
                conn,
                """SELECT COUNT(*) FROM agent_runs run
                   JOIN issues issue ON issue.id = run.issue_id
                   WHERE issue.project_id = ? AND run.status = 'running'""",
                (project_id,),
            ),
        }
    if _has_table(conn, "subtasks"):
        subtasks = {
            "total": _count(
                conn,
                """SELECT COUNT(*) FROM subtasks subtask
                   JOIN issues issue ON issue.id = subtask.issue_id
                   WHERE issue.project_id = ?""",
                (project_id,),
            ),
            "active": _count(
                conn,
                """SELECT COUNT(*) FROM subtasks subtask
                   JOIN issues issue ON issue.id = subtask.issue_id
                   WHERE issue.project_id = ?
                     AND subtask.status IN ('pending', 'running')""",
                (project_id,),
            ),
        }

    campaigns = _state_counts(
        conn,
        "control_campaigns",
        "WHERE project_id = ?",
        project_id,
        ACTIVE_CAMPAIGN_STATES,
    )
    tasks = _state_counts(
        conn,
        "control_agent_tasks",
        "WHERE project_id = ?",
        project_id,
        ACTIVE_TASK_STATES,
    )
    planning_jobs = _state_counts(
        conn,
        "control_planning_jobs",
        "WHERE project_id = ?",
        project_id,
        ("queued", "running", "waiting_human"),
    )
    deployments = _state_counts(
        conn,
        "control_deployments",
        "WHERE project_id = ?",
        project_id,
        ("planned", "running"),
    )
    candidates = {"total": 0, "active": 0, "with_pull_request": 0}
    work_orders = {"total": 0, "active": 0}
    if _has_table(conn, "control_pr_candidates") and _has_table(
        conn, "control_campaigns"
    ):
        candidate_join = (
            "FROM control_pr_candidates candidate "
            "JOIN control_campaigns campaign ON campaign.id = candidate.campaign_id "
            "WHERE campaign.project_id = ?"
        )
        candidate_placeholders = ",".join("?" for _ in ACTIVE_CANDIDATE_STATES)
        candidates = {
            "total": _count(conn, f"SELECT COUNT(*) {candidate_join}", (project_id,)),
            "active": _count(
                conn,
                f"SELECT COUNT(*) {candidate_join} AND candidate.status IN ({candidate_placeholders})",
                (project_id, *ACTIVE_CANDIDATE_STATES),
            ),
            "with_pull_request": 0,
        }
        if _has_table(conn, "control_agent_tasks"):
            candidates["with_pull_request"] = _count(
                conn,
                """SELECT COUNT(DISTINCT candidate.id)
                   FROM control_pr_candidates candidate
                   JOIN control_campaigns campaign ON campaign.id = candidate.campaign_id
                   JOIN control_agent_tasks task ON task.candidate_id = candidate.id
                   WHERE campaign.project_id = ? AND task.pr_number IS NOT NULL""",
                (project_id,),
            )
        if _has_table(conn, "control_work_orders"):
            work_orders = {
                "total": _count(
                    conn,
                    """SELECT COUNT(*) FROM control_work_orders work_order
                       JOIN control_pr_candidates candidate ON candidate.id = work_order.candidate_id
                       JOIN control_campaigns campaign ON campaign.id = candidate.campaign_id
                       WHERE campaign.project_id = ?""",
                    (project_id,),
                ),
                "active": _count(
                    conn,
                    """SELECT COUNT(*) FROM control_work_orders work_order
                       JOIN control_pr_candidates candidate ON candidate.id = work_order.candidate_id
                       JOIN control_campaigns campaign ON campaign.id = candidate.campaign_id
                       WHERE campaign.project_id = ? AND work_order.status = 'approved'""",
                    (project_id,),
                ),
            }

    task_native_chats = 0
    if _has_table(conn, "control_agent_tasks"):
        task_native_chats = _count(
            conn,
            """SELECT COUNT(DISTINCT antigravity_chat_id)
               FROM control_agent_tasks
               WHERE project_id = ? AND antigravity_chat_id <> ''""",
            (project_id,),
        )
    tasks["with_native_chat"] = task_native_chats

    attention = {"total": 0, "open": 0}
    if _has_table(conn, "control_attention_items"):
        attention = {
            "total": _count(
                conn,
                "SELECT COUNT(*) FROM control_attention_items WHERE project_id = ?",
                (project_id,),
            ),
            "open": _count(
                conn,
                """SELECT COUNT(*) FROM control_attention_items
                   WHERE project_id = ? AND status = 'open'""",
                (project_id,),
            ),
        }

    github_owner = str(project.get("github_owner") or "").strip()
    github_repo = str(project.get("github_repo") or "").strip()
    full_name = f"{github_owner}/{github_repo}" if github_owner and github_repo else ""
    return {
        "project": {
            "id": project_id,
            "name": str(project.get("name") or ""),
            "archived": bool(project.get("archived_at")),
            "github_repository": {
                "linked": bool(full_name),
                "full_name": full_name,
            },
        },
        "dependencies": {
            "issues": issues,
            "agent_runs": agent_runs,
            "subtasks": subtasks,
            "lessons": {
                "total": _count(
                    conn,
                    "SELECT COUNT(*) FROM lessons WHERE project_id = ?",
                    (project_id,),
                )
                if _has_table(conn, "lessons")
                else 0
            },
            "campaigns": campaigns,
            "pr_candidates": candidates,
            "work_orders": work_orders,
            "tasks": tasks,
            "planning_jobs": planning_jobs,
            "attention": attention,
            "proxy_chats": {
                "total": (
                    _count(
                        conn,
                        "SELECT COUNT(*) FROM proxy_conversations WHERE project_id = ?",
                        (project_id,),
                    )
                    if _has_table(conn, "proxy_conversations")
                    else 0
                ) + (
                    _count(
                        conn,
                        "SELECT COUNT(*) FROM provider_conversations WHERE project_id = ?",
                        (project_id,),
                    )
                    if _has_table(conn, "provider_conversations")
                    else 0
                )
            },
            "deployments": deployments,
        },
        "retention": {
            "local_project_directory": "preserved",
            "local_git_repository": "preserved",
            "hub_history": "preserved",
            "github_repository": "preserved",
        },
        "remote_repository_deletion": {
            "supported": True,
            "separate_confirmation_required": True,
            "required_identity": full_name,
            "required_permission": "delete_repo",
        },
    }


class ProjectArchiver:
    """Archive Hub projects and terminalize their active local control state."""

    def __init__(self, database: Database) -> None:
        self.db = database

    def impact(self, project_id: int) -> Dict[str, Any]:
        with self.db._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?",
                (int(project_id),),
            ).fetchone()
            if not row:
                raise ProjectNotFoundError("Project not found")
            return _impact(conn, dict(row))

    def archive(self, project_id: int) -> Dict[str, Any]:
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?",
                (int(project_id),),
            ).fetchone()
            if not row:
                raise ProjectNotFoundError("Project not found")
            project = dict(row)
            impact = _impact(conn, project)
            already_archived = bool(project.get("archived_at"))
            transitions: Dict[str, int] = {}

            def update(name: str, query: str, params=()) -> None:
                transitions[name] = int(conn.execute(query, params).rowcount)

            if not already_archived:
                if _has_table(conn, "control_agent_tasks"):
                    placeholders = ",".join("?" for _ in ACTIVE_TASK_STATES)
                    update(
                        "tasks_cancelled",
                        f"""UPDATE control_agent_tasks
                            SET status = 'cancelled', wake_reason = 'project_archived',
                                lease_owner = '', lease_token = '', lease_until = NULL,
                                finished_at = COALESCE(finished_at, CURRENT_TIMESTAMP),
                                updated_at = CURRENT_TIMESTAMP
                            WHERE project_id = ? AND status IN ({placeholders})""",
                        (int(project_id), *ACTIVE_TASK_STATES),
                    )
                if _has_table(conn, "control_evidence_packs"):
                    update(
                        "evidence_packs_cancelled",
                        """UPDATE control_evidence_packs
                           SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
                           WHERE project_id = ? AND status NOT IN ('completed', 'cancelled')""",
                        (int(project_id),),
                    )
                if _has_table(conn, "control_work_orders") and _has_table(
                    conn, "control_campaigns"
                ):
                    update(
                        "work_orders_cancelled",
                        """UPDATE control_work_orders SET status = 'cancelled',
                               updated_at = CURRENT_TIMESTAMP
                           WHERE status = 'approved' AND candidate_id IN (
                               SELECT candidate.id FROM control_pr_candidates candidate
                               JOIN control_campaigns campaign ON campaign.id = candidate.campaign_id
                               WHERE campaign.project_id = ?
                           )""",
                        (int(project_id),),
                    )
                if _has_table(conn, "control_pr_candidates") and _has_table(
                    conn, "control_campaigns"
                ):
                    placeholders = ",".join("?" for _ in ACTIVE_CANDIDATE_STATES)
                    update(
                        "pr_candidates_cancelled",
                        f"""UPDATE control_pr_candidates SET status = 'cancelled',
                                updated_at = CURRENT_TIMESTAMP
                            WHERE campaign_id IN (
                                SELECT id FROM control_campaigns WHERE project_id = ?
                            ) AND status IN ({placeholders})""",
                        (int(project_id), *ACTIVE_CANDIDATE_STATES),
                    )
                if _has_table(conn, "control_campaigns"):
                    placeholders = ",".join("?" for _ in ACTIVE_CAMPAIGN_STATES)
                    update(
                        "campaigns_cancelled",
                        f"""UPDATE control_campaigns SET status = 'cancelled',
                                updated_at = CURRENT_TIMESTAMP
                            WHERE project_id = ? AND status IN ({placeholders})""",
                        (int(project_id), *ACTIVE_CAMPAIGN_STATES),
                    )
                if _has_table(conn, "control_planning_jobs"):
                    update(
                        "planning_jobs_cancelled",
                        """UPDATE control_planning_jobs
                           SET status = 'cancelled',
                               finished_at = COALESCE(finished_at, CURRENT_TIMESTAMP),
                               updated_at = CURRENT_TIMESTAMP
                           WHERE project_id = ?
                             AND status IN ('queued', 'running', 'waiting_human')""",
                        (int(project_id),),
                    )
                    if _has_table(conn, "control_idea_seeds"):
                        update(
                            "idea_seeds_returned_to_inbox",
                            """UPDATE control_idea_seeds
                               SET status = 'inbox',
                                   updated_at = CURRENT_TIMESTAMP
                               WHERE project_id = ? AND status = 'planning'
                                 AND id IN (
                                     SELECT idea_seed_id
                                     FROM control_planning_jobs
                                     WHERE project_id = ?
                                       AND status = 'cancelled'
                                 )""",
                            (int(project_id), int(project_id)),
                        )
                if _has_table(conn, "control_deployments"):
                    update(
                        "deployments_cancelled",
                        """UPDATE control_deployments SET status = 'cancelled',
                               finished_at = COALESCE(finished_at, CURRENT_TIMESTAMP),
                               updated_at = CURRENT_TIMESTAMP
                           WHERE project_id = ? AND status IN ('planned', 'running')""",
                        (int(project_id),),
                    )
                if _has_table(conn, "control_attention_items"):
                    update(
                        "attention_resolved",
                        """UPDATE control_attention_items SET status = 'resolved',
                               resolved_at = COALESCE(resolved_at, CURRENT_TIMESTAMP)
                           WHERE project_id = ? AND status = 'open'""",
                        (int(project_id),),
                    )
                conn.execute(
                    "UPDATE projects SET archived_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (int(project_id),),
                )
                if _has_table(conn, "control_audit_events"):
                    conn.execute(
                        """INSERT INTO control_audit_events (
                               project_id, entity_type, entity_id, action, actor,
                               from_state, to_state, reason, evidence_json
                           ) VALUES (?, 'project', ?, 'project.archived', 'human',
                                     'active', 'archived', ?, ?)""",
                        (
                            int(project_id),
                            str(project_id),
                            "Removed from the Hub; local and remote repositories preserved.",
                            json.dumps({"transitions": transitions}, sort_keys=True),
                        ),
                    )
            refreshed = conn.execute(
                "SELECT id, name, archived_at FROM projects WHERE id = ?",
                (int(project_id),),
            ).fetchone()
            conn.commit()
            return {
                "success": True,
                "archived": True,
                "already_archived": already_archived,
                "project": dict(refreshed),
                "transitions": transitions,
                "retention": impact["retention"],
            }

    def restore(self, project_id: int) -> Dict[str, Any]:
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT id, name, archived_at FROM projects WHERE id = ?",
                (int(project_id),),
            ).fetchone()
            if not row:
                raise ProjectNotFoundError("Project not found")
            was_archived = bool(row["archived_at"])
            conn.execute(
                "UPDATE projects SET archived_at = NULL WHERE id = ?",
                (int(project_id),),
            )
            refreshed = conn.execute(
                "SELECT id, name, archived_at FROM projects WHERE id = ?",
                (int(project_id),),
            ).fetchone()
            conn.commit()
            return {
                "success": True,
                "restored": True,
                "already_active": not was_archived,
                "project": dict(refreshed),
                "note": "Historical cancelled execution state is retained.",
            }
