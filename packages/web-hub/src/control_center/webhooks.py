"""Durable and idempotent GitHub webhook inbox."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from src.control_center.common import ControlCenterError, clean_text


class WebhookMixin:
    def record_webhook_event(
        self,
        *,
        delivery_id: str,
        event_type: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise ControlCenterError(
                "Webhook-Payload muss ein Objekt sein.",
                code="invalid_webhook_payload",
            )
        delivery = clean_text(delivery_id, "delivery_id", maximum=200)
        selected_type = clean_text(event_type, "event_type", maximum=120)
        repository = str(
            ((payload.get("repository") or {}).get("full_name") or "")
        ).strip()
        if not repository or "/" not in repository:
            raise ControlCenterError(
                "Webhook enthält kein Repository.",
                code="webhook_repository_missing",
            )
        action = str(payload.get("action") or "")[:120]
        entity_id = self._webhook_entity_id(selected_type, payload)
        with self.db._get_connection() as conn:
            existing = conn.execute(
                "SELECT * FROM control_webhook_events WHERE delivery_id = ?",
                (delivery,),
            ).fetchone()
            if existing:
                result = self._row(existing, ("payload_json",))
                result["deduplicated"] = True
                return result
            conn.execute(
                """INSERT INTO control_webhook_events (
                       delivery_id, event_type, action, repository,
                       entity_id, payload_json
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    delivery,
                    selected_type,
                    action,
                    repository,
                    entity_id,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            conn.commit()
            result = self._row(
                conn.execute(
                    """SELECT * FROM control_webhook_events
                       WHERE delivery_id = ?""",
                    (delivery,),
                ).fetchone(),
                ("payload_json",),
            )
            result["deduplicated"] = False
            return result

    @staticmethod
    def _webhook_entity_id(event_type: str, payload: Dict[str, Any]) -> str:
        sources = {
            "pull_request": payload.get("pull_request"),
            "pull_request_review": payload.get("review"),
            "pull_request_review_comment": payload.get("comment"),
            "check_run": payload.get("check_run"),
            "check_suite": payload.get("check_suite"),
            "workflow_run": payload.get("workflow_run"),
            "deployment_status": payload.get("deployment_status"),
        }
        source = sources.get(event_type) or {}
        return str(source.get("id") or source.get("number") or "")[:200]

    def resolve_webhook_task(
        self,
        repository: str,
        payload: Dict[str, Any],
    ) -> Optional[str]:
        owner, repo = repository.split("/", 1)
        pull = payload.get("pull_request") or {}
        number = pull.get("number") or (payload.get("issue") or {}).get("number")
        if not number:
            check = payload.get("check_run") or {}
            pulls = check.get("pull_requests") or []
            number = pulls[0].get("number") if pulls else None
        with self.db._get_connection() as conn:
            if number:
                row = conn.execute(
                    """SELECT task.id FROM control_agent_tasks task
                       JOIN projects project ON project.id = task.project_id
                       WHERE lower(project.github_owner) = lower(?)
                         AND lower(project.github_repo) = lower(?)
                         AND task.pr_number = ?
                       ORDER BY task.created_at DESC LIMIT 1""",
                    (owner, repo, int(number)),
                ).fetchone()
                if row:
                    return str(row["id"])
            branch = str(((pull.get("head") or {}).get("ref") or ""))
            if branch:
                row = conn.execute(
                    """SELECT task.id FROM control_agent_tasks task
                       JOIN projects project ON project.id = task.project_id
                       WHERE lower(project.github_owner) = lower(?)
                         AND lower(project.github_repo) = lower(?)
                         AND task.branch_name = ?
                       ORDER BY task.created_at DESC LIMIT 1""",
                    (owner, repo, branch),
                ).fetchone()
                if row:
                    return str(row["id"])
        return None

    def finish_webhook_event(
        self,
        delivery_id: str,
        *,
        status: str,
        error: str = "",
    ) -> Dict[str, Any]:
        if status not in {"processed", "ignored", "failed"}:
            raise ControlCenterError(
                "Ungültiger Webhook-Status.",
                code="invalid_webhook_status",
            )
        with self.db._get_connection() as conn:
            updated = conn.execute(
                """UPDATE control_webhook_events
                   SET status = ?, error = ?, processed_at = CURRENT_TIMESTAMP
                   WHERE delivery_id = ?""",
                (status, str(error or "")[:5000], delivery_id),
            )
            if updated.rowcount != 1:
                raise ControlCenterError(
                    "Webhook-Delivery nicht gefunden.",
                    code="webhook_not_found",
                    status=404,
                )
            conn.commit()
            return self._row(
                conn.execute(
                    """SELECT * FROM control_webhook_events
                       WHERE delivery_id = ?""",
                    (delivery_id,),
                ).fetchone(),
                ("payload_json",),
            )
