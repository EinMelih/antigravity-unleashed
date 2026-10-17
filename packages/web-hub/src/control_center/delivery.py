"""Capability-gated deployments, health checks, rollbacks, and metrics."""

from __future__ import annotations

import json
from typing import Any, Dict

from src.control_center.common import ControlCenterError, clean_text, public_id


DEPLOYMENT_ENVIRONMENTS = {"preview", "staging", "production"}
DEPLOYMENT_STATES = {
    "planned",
    "running",
    "healthy",
    "failed",
    "rolled_back",
    "cancelled",
}


class DeliveryMixin:
    def create_deployment(
        self,
        task_id: str,
        payload: Dict[str, Any],
        *,
        actor: str = "human",
    ) -> Dict[str, Any]:
        task = self.get_task(task_id)
        environment = str(payload.get("environment") or "").strip().lower()
        if environment not in DEPLOYMENT_ENVIRONMENTS:
            raise ControlCenterError(
                "Unbekannte Deployment-Umgebung.",
                code="invalid_deployment_environment",
            )
        sha = str(payload.get("sha") or "").strip().lower()
        current_sha = str(task.get("current_sha") or "").lower()
        merged_sha = str(task.get("merged_sha") or "").lower()
        deployable_sha = (
            merged_sha
            if task.get("status") == "completed" and merged_sha
            else current_sha
        )
        if sha != deployable_sha:
            raise ControlCenterError(
                "Deployment gilt nur für den exakten deploybaren Task-SHA.",
                code="deployment_sha_mismatch",
                status=409,
            )
        policy = self.get_repository_policy(task["project_id"])
        capability_name = {
            "preview": "deploy_staging",
            "staging": "deploy_staging",
            "production": "deploy_production",
        }[environment]
        if not policy["capability"].get(capability_name, False):
            raise ControlCenterError(
                f"Capability {capability_name} ist nicht freigegeben.",
                code="deployment_capability_denied",
                status=403,
            )
        with self.db._get_connection() as conn:
            if environment == "production" and not self._active_approval(
                conn,
                task_id,
                "production",
                sha,
            ):
                raise ControlCenterError(
                    "Production benötigt eine separate SHA-gebundene Freigabe.",
                    code="production_approval_required",
                    status=409,
                )
            deployment_id = public_id("DPL")
            migration = payload.get("migration") or {}
            if not isinstance(migration, dict):
                raise ControlCenterError(
                    "migration muss ein Objekt sein.",
                    code="invalid_migration_plan",
                )
            conn.execute(
                """INSERT INTO control_deployments (
                       id, task_id, project_id, environment, sha, artifact_ref,
                       previous_stable_sha, migration_json, approved_by
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    deployment_id,
                    task_id,
                    int(task["project_id"]),
                    environment,
                    sha,
                    str(payload.get("artifact_ref") or "")[:2000],
                    str(payload.get("previous_stable_sha") or "")[:64].lower(),
                    json.dumps(migration, ensure_ascii=False),
                    str(actor or "human")[:120],
                ),
            )
            self._audit(
                conn,
                project_id=int(task["project_id"]),
                entity_type="deployment",
                entity_id=deployment_id,
                action="deployment.planned",
                actor=str(actor or "human")[:120],
                to_state="planned",
                evidence={"environment": environment, "sha": sha},
            )
            conn.commit()
            return self._deployment(conn, deployment_id)

    def update_deployment(
        self,
        deployment_id: str,
        *,
        status: str,
        logs: list[Any] | None = None,
        health: Dict[str, Any] | None = None,
        actor: str = "deployer",
    ) -> Dict[str, Any]:
        selected_status = str(status or "").strip().lower()
        if selected_status not in DEPLOYMENT_STATES:
            raise ControlCenterError(
                "Unbekannter Deployment-Status.",
                code="invalid_deployment_status",
            )
        log_items = logs or []
        health_result = health or {}
        if not isinstance(log_items, list) or not isinstance(health_result, dict):
            raise ControlCenterError(
                "Deployment-Logs bzw. Health müssen Liste/Objekt sein.",
                code="invalid_deployment_result",
            )
        with self.db._get_connection() as conn:
            current = conn.execute(
                "SELECT * FROM control_deployments WHERE id = ?",
                (deployment_id,),
            ).fetchone()
            if not current:
                raise ControlCenterError(
                    "Deployment nicht gefunden.",
                    code="deployment_not_found",
                    status=404,
                )
            allowed = {
                "planned": {"running", "cancelled"},
                "running": {"healthy", "failed", "cancelled"},
                "failed": {"running", "rolled_back"},
                "healthy": {"rolled_back"},
                "rolled_back": set(),
                "cancelled": set(),
            }
            if selected_status != current["status"] and selected_status not in allowed[
                str(current["status"])
            ]:
                raise ControlCenterError(
                    "Ungültiger Deployment-Statusübergang.",
                    code="invalid_deployment_transition",
                    status=409,
                )
            conn.execute(
                """UPDATE control_deployments
                   SET status = ?, logs_json = ?, health_json = ?,
                       started_at = CASE
                           WHEN ? = 'running' THEN COALESCE(started_at, CURRENT_TIMESTAMP)
                           ELSE started_at END,
                       finished_at = CASE
                           WHEN ? IN ('healthy', 'failed', 'rolled_back', 'cancelled')
                           THEN CURRENT_TIMESTAMP ELSE finished_at END,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (
                    selected_status,
                    json.dumps(log_items, ensure_ascii=False),
                    json.dumps(health_result, ensure_ascii=False),
                    selected_status,
                    selected_status,
                    deployment_id,
                ),
            )
            self._audit(
                conn,
                project_id=int(current["project_id"]),
                entity_type="deployment",
                entity_id=deployment_id,
                action="deployment.status_updated",
                actor=str(actor or "deployer")[:120],
                from_state=str(current["status"]),
                to_state=selected_status,
                evidence={"health": health_result},
            )
            conn.commit()
            return self._deployment(conn, deployment_id)

    def rollback_deployment(
        self,
        deployment_id: str,
        *,
        reason: str,
        actor: str = "human",
    ) -> Dict[str, Any]:
        explanation = clean_text(reason, "reason", minimum=3, maximum=5000)
        with self.db._get_connection() as conn:
            current = conn.execute(
                "SELECT * FROM control_deployments WHERE id = ?",
                (deployment_id,),
            ).fetchone()
            if not current:
                raise ControlCenterError(
                    "Deployment nicht gefunden.",
                    code="deployment_not_found",
                    status=404,
                )
            policy = self._repository_policy_in_connection(
                conn,
                int(current["project_id"]),
            )
            if not policy["capability"].get("rollback", False):
                raise ControlCenterError(
                    "Rollback-Capability ist nicht freigegeben.",
                    code="rollback_capability_denied",
                    status=403,
                )
            target_sha = str(current["previous_stable_sha"] or "").lower()
            if not target_sha:
                raise ControlCenterError(
                    "Kein vorheriger stabiler SHA für Rollback hinterlegt.",
                    code="rollback_target_missing",
                    status=409,
                )
            rollback_id = public_id("DPL")
            conn.execute(
                """INSERT INTO control_deployments (
                       id, task_id, project_id, environment, status, sha,
                       artifact_ref, previous_stable_sha, logs_json,
                       health_json, approved_by, rollback_of, started_at
                   ) VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, ?,
                             CURRENT_TIMESTAMP)""",
                (
                    rollback_id,
                    current["task_id"],
                    int(current["project_id"]),
                    current["environment"],
                    target_sha,
                    current["artifact_ref"],
                    current["sha"],
                    json.dumps([explanation], ensure_ascii=False),
                    json.dumps({}, ensure_ascii=False),
                    str(actor or "human")[:120],
                    deployment_id,
                ),
            )
            self._audit(
                conn,
                project_id=int(current["project_id"]),
                entity_type="deployment",
                entity_id=rollback_id,
                action="deployment.rollback_started",
                actor=str(actor or "human")[:120],
                to_state="running",
                reason=explanation,
                evidence={"rollback_of": deployment_id, "target_sha": target_sha},
            )
            conn.commit()
            return self._deployment(conn, rollback_id)

    def record_metric(
        self,
        metric: str,
        value: Any,
        *,
        project_id: Any = None,
        campaign_id: str = "",
        task_id: str = "",
        unit: str = "count",
        labels: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ControlCenterError(
                "Metrikwert muss numerisch sein.",
                code="invalid_metric_value",
            ) from exc
        project = (
            self._project(project_id) if project_id not in (None, "") else None
        )
        label_data = labels or {}
        if not isinstance(label_data, dict):
            raise ControlCenterError(
                "Metrik-Labels müssen ein Objekt sein.",
                code="invalid_metric_labels",
            )
        with self.db._get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO control_metrics (
                       project_id, campaign_id, task_id, metric, value, unit, labels_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(project["id"]) if project else None,
                    campaign_id or None,
                    task_id or None,
                    clean_text(metric, "metric", maximum=160),
                    numeric,
                    str(unit or "count")[:40],
                    json.dumps(label_data, ensure_ascii=False),
                ),
            )
            metric_id = int(cursor.lastrowid)
            conn.commit()
            return self._row(
                conn.execute(
                    "SELECT * FROM control_metrics WHERE id = ?",
                    (metric_id,),
                ).fetchone(),
                ("labels_json",),
            )

    def _deployment(self, conn, deployment_id: str) -> Dict[str, Any]:
        row = conn.execute(
            "SELECT * FROM control_deployments WHERE id = ?",
            (deployment_id,),
        ).fetchone()
        if not row:
            raise ControlCenterError(
                "Deployment nicht gefunden.",
                code="deployment_not_found",
                status=404,
            )
        return self._row(
            row,
            ("migration_json", "logs_json", "health_json"),
        )
