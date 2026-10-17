"""Shared persistence primitives and invariants for control-center mixins."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Optional

from src.control_center.common import (
    RISK_LEVELS,
    SHA_PATTERN,
    ControlCenterError,
    git_head,
    git_file_at_sha,
    public_id,
)
from src.control_center.schema import init_schema
from src.database import Database, db
from src.redaction import redact_sensitive_text


def _redact_sensitive_preview(value: Any, maximum: int = 500) -> str:
    return redact_sensitive_text(value, maximum=maximum)


class ControlStoreBase:
    def __init__(
        self,
        database: Database = db,
        sha_resolver=None,
        repository_reader=None,
    ) -> None:
        self.db = database
        self.sha_resolver = sha_resolver or git_head
        self.repository_reader = repository_reader or git_file_at_sha
        init_schema(self.db)

    def _project(self, project_id: Any) -> Dict[str, Any]:
        try:
            normalized = int(project_id)
        except (TypeError, ValueError):
            raise ControlCenterError("Ungültige Projekt-ID.", code="invalid_project_id")
        project = self.db.get_project(normalized)
        if not project:
            raise ControlCenterError("Projekt nicht gefunden.", code="project_not_found", status=404)
        return project

    @staticmethod
    def _risk(value: Any) -> str:
        risk = str(value or "medium").strip().lower()
        if risk not in RISK_LEVELS:
            raise ControlCenterError("Unbekannte Risikostufe.", code="invalid_risk_level")
        return risk

    def _resolve_sha(self, project: Dict[str, Any], requested: Any = "", *, require=False) -> str:
        requested_sha = str(requested or "").strip().lower()
        if requested_sha and not SHA_PATTERN.fullmatch(requested_sha):
            raise ControlCenterError("Der Commit-SHA ist ungültig.", code="invalid_sha")
        current_sha = str(self.sha_resolver(project) or "").strip().lower()
        if current_sha and requested_sha:
            if current_sha != requested_sha and not current_sha.startswith(requested_sha):
                raise ControlCenterError(
                    "Der Repository-Stand hat sich geändert. Bitte Plan neu prüfen.",
                    code="stale_base_sha",
                    status=409,
                )
            return current_sha
        resolved = current_sha or requested_sha
        if require and not resolved:
            raise ControlCenterError(
                "Kein verifizierbarer Commit-SHA verfügbar.", code="sha_required", status=409
            )
        return resolved

    @staticmethod
    def _row(row: Any, json_fields: Iterable[str] = ()) -> Optional[Dict[str, Any]]:
        if not row:
            return None
        result = dict(row)
        for field in json_fields:
            try:
                result[field.removesuffix("_json")] = json.loads(result.pop(field) or "[]")
            except (json.JSONDecodeError, TypeError):
                result[field.removesuffix("_json")] = []
        if "last_error" in result:
            result["last_error"] = _redact_sensitive_preview(
                result["last_error"],
                maximum=2000,
            )
        return result

    @staticmethod
    def _redact_diagnostic(value: Any, maximum: int = 2000) -> str:
        return _redact_sensitive_preview(value, maximum=maximum)

    @staticmethod
    def _audit(
        conn,
        *,
        project_id: Optional[int],
        entity_type: str,
        entity_id: str,
        action: str,
        actor: str,
        from_state: str = "",
        to_state: str = "",
        reason: str = "",
        evidence: Optional[Dict[str, Any]] = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO control_audit_events (
                project_id, entity_type, entity_id, action, actor,
                from_state, to_state, reason, evidence_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id, entity_type, entity_id, action, actor,
                from_state, to_state, reason,
                json.dumps(evidence or {}, ensure_ascii=False),
            ),
        )

    @staticmethod
    def _attention(
        conn,
        *,
        project_id: int,
        category: str,
        entity_type: str,
        entity_id: str,
        title: str,
        consequence: str,
        recommendation: str,
        urgency: str = "normal",
    ) -> str:
        existing = conn.execute(
            """SELECT id FROM control_attention_items
               WHERE entity_type = ? AND entity_id = ? AND category = ? AND status = 'open'""",
            (entity_type, entity_id, category),
        ).fetchone()
        if existing:
            return str(existing["id"])
        attention_id = public_id("ATT")
        conn.execute(
            """
            INSERT INTO control_attention_items (
                id, project_id, category, entity_type, entity_id, title,
                consequence, recommendation, urgency
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attention_id, project_id, category, entity_type, entity_id,
                title, consequence, recommendation, urgency,
            ),
        )
        return attention_id

    @staticmethod
    def _resolve_attention(conn, entity_type: str, entity_id: str, category: str) -> None:
        conn.execute(
            """UPDATE control_attention_items
               SET status = 'resolved', resolved_at = CURRENT_TIMESTAMP
               WHERE entity_type = ? AND entity_id = ? AND category = ? AND status = 'open'""",
            (entity_type, entity_id, category),
        )

    def set_agent_permission_attention(
        self,
        *,
        project_id: int,
        entity_type: str,
        entity_id: str,
        gate: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Open or resolve one idempotent live Anti-Gravity permission gate."""
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """SELECT id FROM control_attention_items
                   WHERE entity_type = ? AND entity_id = ?
                     AND category = 'agent_permission' AND status = 'open'""",
                (entity_type, entity_id),
            ).fetchone()
            if gate:
                tool_name = str(gate.get("tool_name") or "Aktion").strip()
                command = _redact_sensitive_preview(
                    gate.get("command")
                    or gate.get("detail")
                    or tool_name
                )
                chat_id = str(gate.get("chat_id") or "").strip()
                attention_id = self._attention(
                    conn,
                    project_id=int(project_id),
                    category="agent_permission",
                    entity_type=entity_type,
                    entity_id=entity_id,
                    title="Anti-Gravity wartet auf deine Freigabe",
                    consequence=command,
                    recommendation=(
                        "Öffne den zugehörigen Anti-Gravity-Chat, prüfe die "
                        "angeforderte Aktion und erlaube oder überspringe sie bewusst."
                    ),
                    urgency="high",
                )
                conn.execute(
                    """UPDATE control_attention_items
                       SET title = ?, consequence = ?, recommendation = ?,
                           urgency = 'high'
                       WHERE id = ?""",
                    (
                        "Anti-Gravity wartet auf deine Freigabe",
                        command,
                        (
                            "Öffne den zugehörigen Anti-Gravity-Chat, prüfe die "
                            "angeforderte Aktion und erlaube oder überspringe sie bewusst."
                        ),
                        attention_id,
                    ),
                )
                if not existing:
                    self._audit(
                        conn,
                        project_id=int(project_id),
                        entity_type=entity_type,
                        entity_id=entity_id,
                        action="agent.permission_required",
                        actor="antigravity",
                        evidence={
                            "chat_id": chat_id,
                            "tool_name": tool_name,
                            "detail": command,
                        },
                    )
            else:
                self._resolve_attention(
                    conn,
                    entity_type,
                    entity_id,
                    "agent_permission",
                )
                if existing:
                    self._audit(
                        conn,
                        project_id=int(project_id),
                        entity_type=entity_type,
                        entity_id=entity_id,
                        action="agent.permission_resolved",
                        actor="antigravity",
                    )
            conn.commit()

    def resolve_all_agent_permission_attention(self) -> int:
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            updated = conn.execute(
                """UPDATE control_attention_items
                   SET status = 'resolved', resolved_at = CURRENT_TIMESTAMP
                   WHERE category = 'agent_permission' AND status = 'open'"""
            ).rowcount
            conn.commit()
        return int(updated)

    @staticmethod
    def _campaign(conn, campaign_id: str):
        row = conn.execute("SELECT * FROM control_campaigns WHERE id = ?", (campaign_id,)).fetchone()
        if not row:
            raise ControlCenterError("Campaign nicht gefunden.", code="campaign_not_found", status=404)
        return row

    @staticmethod
    def _validate_dag(conn, campaign_id: str) -> None:
        node_ids = {
            str(row["id"])
            for row in conn.execute(
                "SELECT id FROM control_pr_candidates WHERE campaign_id = ?", (campaign_id,)
            ).fetchall()
        }
        edges = conn.execute(
            """SELECT d.candidate_id, d.depends_on_id
               FROM control_pr_dependencies d
               JOIN control_pr_candidates c ON c.id = d.candidate_id
               WHERE c.campaign_id = ?""",
            (campaign_id,),
        ).fetchall()
        graph = {node_id: [] for node_id in node_ids}
        for edge in edges:
            candidate_id, dependency_id = str(edge["candidate_id"]), str(edge["depends_on_id"])
            if dependency_id not in node_ids:
                raise ControlCenterError(
                    "PR-Abhängigkeit verweist außerhalb der Campaign.",
                    code="cross_campaign_dependency",
                    status=409,
                )
            graph[candidate_id].append(dependency_id)

        visiting, visited = set(), set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise ControlCenterError(
                    "Der PR-Abhängigkeitsgraph enthält einen Zyklus.",
                    code="cyclic_pr_dependencies",
                    status=409,
                )
            if node_id in visited:
                return
            visiting.add(node_id)
            for dependency in graph[node_id]:
                visit(dependency)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in graph:
            visit(node_id)
