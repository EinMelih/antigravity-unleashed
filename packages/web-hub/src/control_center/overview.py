"""Read model for the repository-scoped Control Center dashboard."""


_OPEN_CAMPAIGN_STATES = {"draft", "approved", "active", "paused"}
_ACTIVE_TASK_STATES = {
    "leased",
    "running",
    "waiting_ci",
    "waiting_review",
    "waiting_human",
    "repair",
}


def _status_counts(conn, table, project_scope, params):
    return {
        str(row["status"]): int(row["count"])
        for row in conn.execute(
            f"""SELECT status, COUNT(*) AS count FROM {table}
                WHERE {project_scope} GROUP BY status""",
            params,
        ).fetchall()
    }


def _percentage_metric(*, key, label, description, numerator, denominator, breakdown):
    return {
        "key": key,
        "label": label,
        "description": description,
        "value": round((numerator / denominator) * 100, 1) if denominator else None,
        "unit": "percent",
        "numerator": int(numerator),
        "denominator": int(denominator),
        "sample_size": int(denominator),
        "breakdown": breakdown,
    }


def _count_metric(*, key, label, description, numerator, denominator):
    return {
        "key": key,
        "label": label,
        "description": description,
        "value": int(numerator) if denominator else None,
        "unit": "count",
        "numerator": int(numerator),
        "denominator": int(denominator),
        "sample_size": int(denominator),
        "breakdown": {},
    }


def _derive_flow_metrics(conn, project_scope, params):
    """Derive an immutable snapshot from canonical control-plane history."""
    planning = _status_counts(conn, "control_planning_jobs", project_scope, params)
    planning_breakdown = {
        "completed": planning.get("completed", 0),
        "failed": planning.get("failed", 0),
        "cancelled": planning.get("cancelled", 0),
    }
    planning_terminal = sum(planning_breakdown.values())

    campaigns = _status_counts(conn, "control_campaigns", project_scope, params)
    campaign_total = sum(campaigns.values())
    campaign_completed = campaigns.get("completed", 0)
    campaign_open = sum(campaigns.get(status, 0) for status in _OPEN_CAMPAIGN_STATES)
    campaign_breakdown = {
        "completed": campaign_completed,
        "open": campaign_open,
        "other": campaign_total - campaign_completed - campaign_open,
    }

    tasks = _status_counts(conn, "control_agent_tasks", project_scope, params)
    task_total = sum(tasks.values())
    task_completed = tasks.get("completed", 0)
    task_failed = tasks.get("failed", 0)
    task_active = sum(tasks.get(status, 0) for status in _ACTIVE_TASK_STATES)
    task_breakdown = {
        "completed": task_completed,
        "failed": task_failed,
        "active": task_active,
        "other": task_total - task_completed - task_failed - task_active,
    }

    campaign_scope = f"c.{project_scope}"
    question_count = int(
        conn.execute(
            f"""SELECT COUNT(*) AS count FROM control_question_ledger q
                JOIN control_campaigns c ON c.id = q.campaign_id
                WHERE {campaign_scope}""",
            params,
        ).fetchone()["count"]
    )
    amendment_count = int(
        conn.execute(
            f"""SELECT COUNT(*) AS count FROM control_plan_amendments a
                JOIN control_campaigns c ON c.id = a.campaign_id
                WHERE {campaign_scope}""",
            params,
        ).fetchone()["count"]
    )
    repair_reopen_count = int(
        conn.execute(
            f"""SELECT COUNT(*) AS count FROM control_audit_events
                WHERE {project_scope}
                  AND (to_state = 'repair' OR action = 'finding.reopened')""",
            params,
        ).fetchone()["count"]
    )
    deployment_scope = f"WHERE {project_scope}"
    deployment_rollbacks = int(
        conn.execute(
            f"""SELECT COUNT(*) AS count FROM control_deployments
                {deployment_scope} AND rollback_of IS NOT NULL""",
            params,
        ).fetchone()["count"]
    )
    deployment_originals = int(
        conn.execute(
            f"""SELECT COUNT(*) AS count FROM control_deployments
                {deployment_scope} AND rollback_of IS NULL""",
            params,
        ).fetchone()["count"]
    )

    return [
        _percentage_metric(
            key="planning_outcomes",
            label="Planung erfolgreich",
            description=(
                "Abgeschlossene Planungsläufe unter allen beendeten Läufen; "
                "offene Läufe gehören nicht zur Stichprobe."
            ),
            numerator=planning_breakdown["completed"],
            denominator=planning_terminal,
            breakdown=planning_breakdown,
        ),
        _percentage_metric(
            key="campaign_progress",
            label="Kampagnen abgeschlossen",
            description="Abgeschlossene Kampagnen im Verhältnis zu allen Kampagnen.",
            numerator=campaign_completed,
            denominator=campaign_total,
            breakdown=campaign_breakdown,
        ),
        _percentage_metric(
            key="task_progress",
            label="Tasks abgeschlossen",
            description="Abgeschlossene Tasks im Verhältnis zu allen angelegten Tasks.",
            numerator=task_completed,
            denominator=task_total,
            breakdown=task_breakdown,
        ),
        _count_metric(
            key="human_questions",
            label="Menschliche Rückfragen",
            description="Persistierte Planungsfragen in der betrachteten Kampagnenmenge.",
            numerator=question_count,
            denominator=campaign_total,
        ),
        _count_metric(
            key="repair_reopen_events",
            label="Repair-/Reopen-Ereignisse",
            description=(
                "Persistierte Übergänge in Repair oder wieder geöffnete Findings; "
                "ein Task kann mehrfach zählen."
            ),
            numerator=repair_reopen_count,
            denominator=task_total,
        ),
        _count_metric(
            key="plan_amendments",
            label="Planänderungen",
            description="Persistierte Plan-Amendments in der betrachteten Kampagnenmenge.",
            numerator=amendment_count,
            denominator=campaign_total,
        ),
        _count_metric(
            key="deployment_rollbacks",
            label="Deployment-Rollbacks",
            description="Persistierte Rollbacks je ursprünglichem Deployment.",
            numerator=deployment_rollbacks,
            denominator=deployment_originals,
        ),
    ]


class OverviewMixin:
    def overview(self, project_id=None):
        selected = self._project(project_id) if project_id not in (None, "") else None
        params = (int(selected["id"]),) if selected else ()
        project_scope = (
            "project_id = ?"
            if selected
            else "project_id IN (SELECT id FROM projects WHERE archived_at IS NULL)"
        )
        where = f"WHERE {project_scope}"
        with self.db._get_connection() as conn:
            recommendations = [dict(row) for row in conn.execute(
                f"""SELECT * FROM control_recommendations {where}
                    ORDER BY CASE status WHEN 'new' THEN 0 WHEN 'deferred' THEN 1 ELSE 2 END,
                             updated_at DESC""",
                params,
            ).fetchall()]
            campaigns = [dict(row) for row in conn.execute(
                f"SELECT * FROM control_campaigns {where} ORDER BY updated_at DESC", params
            ).fetchall()]
            for campaign in campaigns:
                campaign["profile"] = self._row(
                    conn.execute(
                        """SELECT * FROM control_campaign_profiles
                           WHERE campaign_id = ?""",
                        (campaign["id"],),
                    ).fetchone(),
                    (
                        "success_metrics_json",
                        "constraints_json",
                        "assumptions_json",
                        "acceptance_matrix_json",
                        "alternatives_json",
                    ),
                )
                campaign["questions"] = [
                    self._row(row, ("evidence_json",))
                    for row in conn.execute(
                        """SELECT * FROM control_question_ledger
                           WHERE campaign_id = ?
                           ORDER BY created_at ASC""",
                        (campaign["id"],),
                    ).fetchall()
                ]
                campaign["artifacts"] = [
                    self._row(row, ("metadata_json",))
                    for row in conn.execute(
                        """SELECT * FROM control_artifacts
                           WHERE campaign_id = ?
                           ORDER BY artifact_type, version DESC""",
                        (campaign["id"],),
                    ).fetchall()
                ]
                campaign["amendments"] = [
                    self._amendment_row(row, include_payload=False)
                    for row in conn.execute(
                        """SELECT * FROM control_plan_amendments
                           WHERE campaign_id = ?
                           ORDER BY created_at DESC""",
                        (campaign["id"],),
                    ).fetchall()
                ]
                rows = conn.execute(
                    """SELECT * FROM control_pr_candidates WHERE campaign_id = ?
                       ORDER BY priority ASC, created_at ASC""",
                    (campaign["id"],),
                ).fetchall()
                campaign["pr_candidates"] = []
                for row in rows:
                    candidate = self._row(row, ("acceptance_criteria_json",))
                    dependencies = conn.execute(
                        """SELECT depends_on_id FROM control_pr_dependencies
                           WHERE candidate_id = ? ORDER BY depends_on_id""",
                        (candidate["id"],),
                    ).fetchall()
                    candidate["depends_on"] = [str(item["depends_on_id"]) for item in dependencies]
                    work_order = conn.execute(
                        "SELECT * FROM control_work_orders WHERE candidate_id = ?", (candidate["id"],)
                    ).fetchone()
                    candidate["work_order"] = dict(work_order) if work_order else None
                    candidate["contract"] = self._row(
                        conn.execute(
                            """SELECT * FROM control_candidate_contracts
                               WHERE candidate_id = ?""",
                            (candidate["id"],),
                        ).fetchone(),
                        (
                            "components_json",
                            "required_checks_json",
                            "manual_tests_json",
                            "documentation_json",
                        ),
                    )
                    candidate["conflicts"] = [
                        self._row(row, ("resources_json",))
                        for row in conn.execute(
                            """SELECT * FROM control_candidate_conflicts
                               WHERE candidate_id = ? OR conflicts_with_id = ?
                               ORDER BY created_at ASC""",
                            (candidate["id"], candidate["id"]),
                        ).fetchall()
                    ]
                    task = conn.execute(
                        """SELECT * FROM control_agent_tasks
                           WHERE candidate_id = ?""",
                        (candidate["id"],),
                    ).fetchone()
                    candidate["task"] = (
                        self._row(
                            task,
                            ("allowed_actions_json", "protected_paths_json"),
                        )
                        if task
                        else None
                    )
                    if task:
                        pack = conn.execute(
                            """SELECT * FROM control_evidence_packs
                               WHERE task_id = ?""",
                            (task["id"],),
                        ).fetchone()
                        candidate["evidence_pack"] = (
                            self._row(pack, ("risk_json", "test_pack_json"))
                            if pack
                            else None
                        )
                        candidate["findings"] = [
                            dict(row)
                            for row in conn.execute(
                                """SELECT * FROM control_findings
                                   WHERE task_id = ?
                                   ORDER BY created_at DESC""",
                                (task["id"],),
                            ).fetchall()
                        ]
                        candidate["approvals"] = [
                            self._row(row, ("evidence_json",))
                            for row in conn.execute(
                                """SELECT * FROM control_human_approvals
                                   WHERE entity_type = 'agent_task'
                                     AND entity_id = ?
                                   ORDER BY created_at DESC""",
                                (task["id"],),
                            ).fetchall()
                        ]
                    campaign["pr_candidates"].append(candidate)

            attention_where = f"WHERE status = 'open' AND {project_scope}"
            attention_params = params
            attention = [dict(row) for row in conn.execute(
                f"""SELECT * FROM control_attention_items {attention_where}
                    ORDER BY CASE urgency WHEN 'critical' THEN 0 WHEN 'high' THEN 1 ELSE 2 END,
                             created_at ASC""",
                attention_params,
            ).fetchall()]
            audit_where = f"WHERE {project_scope}"
            audit = [self._row(row, ("evidence_json",)) for row in conn.execute(
                f"SELECT * FROM control_audit_events {audit_where} ORDER BY id DESC LIMIT 80", params
            ).fetchall()]
            checkpoints = [self._row(row, ("payload_json",)) for row in conn.execute(
                f"""SELECT * FROM control_checkpoints {audit_where}
                    ORDER BY created_at DESC LIMIT 30""",
                params,
            ).fetchall()]
            work_order_count = conn.execute(
                """SELECT COUNT(*) AS count FROM control_work_orders wo
                   JOIN control_pr_candidates pc ON pc.id = wo.candidate_id
                   JOIN control_campaigns c ON c.id = pc.campaign_id
                   WHERE wo.status = 'approved'"""
                + (
                    " AND c.project_id = ?"
                    if selected
                    else " AND c.project_id IN (SELECT id FROM projects WHERE archived_at IS NULL)"
                ),
                params,
            ).fetchone()["count"]
            task_where = f"WHERE {project_scope}"
            tasks = [
                self._row(row, ("allowed_actions_json", "protected_paths_json"))
                for row in conn.execute(
                    f"""SELECT * FROM control_agent_tasks {task_where}
                        ORDER BY updated_at DESC""",
                    params,
                ).fetchall()
            ]
            deployments = [
                self._row(row, ("migration_json", "logs_json", "health_json"))
                for row in conn.execute(
                    f"""SELECT * FROM control_deployments {task_where}
                        ORDER BY created_at DESC LIMIT 100""",
                    params,
                ).fetchall()
            ]
            metrics = [
                self._row(row, ("labels_json",))
                for row in conn.execute(
                    f"""SELECT * FROM control_metrics {task_where}
                        ORDER BY recorded_at DESC LIMIT 200""",
                    params,
                ).fetchall()
            ]
            webhook_count = int(
                conn.execute(
                    """SELECT COUNT(*) AS count FROM control_webhook_events
                       WHERE status IN ('pending', 'failed')"""
                ).fetchone()["count"]
            )
            planning_jobs = [
                self._row(row, ("constraints_json", "output_json"))
                for row in conn.execute(
                    f"""SELECT * FROM control_planning_jobs {task_where}
                        ORDER BY created_at DESC LIMIT 100""",
                    params,
                ).fetchall()
            ]
            for planning_job in planning_jobs:
                output = planning_job.get("output") or {}
                if (
                    planning_job.get("job_type") == "plan_amendment"
                    and output.get("type") == "amendment_plan"
                ):
                    planning_job["output"] = {
                        "type": "amendment_plan",
                        "amendment_id": planning_job.get("amendment_id"),
                        "resolved_question_ids": output.get(
                            "resolved_question_ids", []
                        ),
                    }
            flow_metrics = _derive_flow_metrics(conn, project_scope, params)
            permission_by_entity = {
                (str(item["entity_type"]), str(item["entity_id"])): item
                for item in attention
                if item["category"] == "agent_permission"
            }
            for task in tasks:
                task["agent_gate"] = permission_by_entity.get(
                    ("agent_task", str(task["id"]))
                )
            for planning_job in planning_jobs:
                planning_job["agent_gate"] = permission_by_entity.get(
                    ("planning_job", str(planning_job["id"]))
                )
            task_human_gate_ids = {
                str(item["id"])
                for item in tasks
                if item["status"] == "waiting_human" or bool(item.get("agent_gate"))
            }
            human_decision_entities = {
                (str(item["entity_type"]), str(item["entity_id"]))
                for item in attention
            }
            human_decision_entities.update(
                ("agent_task", task_id)
                for task_id in task_human_gate_ids
            )
        return {
            "policy": self.get_policy(), "project": selected,
            "summary": {
                "attention_open": len(attention),
                "recommendations_open": sum(item["status"] in {"new", "deferred"} for item in recommendations),
                "campaigns_open": sum(item["status"] in {"draft", "approved", "active", "paused"} for item in campaigns),
                "work_orders_approved": int(work_order_count),
                "tasks_active": sum(
                    item["status"] in {
                        "leased",
                        "running",
                        "waiting_ci",
                        "waiting_review",
                        "waiting_human",
                        "repair",
                    }
                    for item in tasks
                ),
                "tasks_waiting_human": sum(
                    1 for _task_id in task_human_gate_ids
                ),
                "human_gates_open": len(human_decision_entities),
                "deployments_active": sum(
                    item["status"] in {"planned", "running"} for item in deployments
                ),
                "webhooks_pending": webhook_count,
                "planning_jobs_active": sum(
                    item["status"] in {"queued", "running"}
                    for item in planning_jobs
                ),
            },
            "attention": attention, "recommendations": recommendations,
            "campaigns": campaigns, "tasks": tasks,
            "planning_jobs": planning_jobs,
            "deployments": deployments, "metrics": metrics,
            "flow_metrics": flow_metrics,
            "checkpoints": checkpoints, "audit": audit,
        }
