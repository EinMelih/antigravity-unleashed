"""Repository-scoped execution policy and capability boundaries."""

from __future__ import annotations

import json
from typing import Any, Dict

from src.control_center.common import (
    ACTIVATION_POLICIES,
    ControlCenterError,
)


DEFAULT_CAPABILITIES = {
    "read_repository": True,
    "create_issue": True,
    "create_branch": True,
    "push_branch": True,
    "create_draft_pr": True,
    "repair_ci": True,
    "respond_to_review": True,
    "merge_pr": False,
    "deploy_staging": False,
    "deploy_production": False,
    "rollback": False,
}

DEFAULT_PROTECTED_PATHS = [
    ".github/workflows/**",
    ".github/CODEOWNERS",
    "**/auth/**",
    "**/migrations/**",
    "**/secrets/**",
    "**/billing/**",
    "**/payments/**",
    "AGENTS.md",
    "**/AGENTS.md",
]


def _json_list(value: Any, field: str, *, maximum: int = 200) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ControlCenterError(f"{field} muss eine Liste sein.", code=f"invalid_{field}")
    result = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text[:500])
    if len(result) > maximum:
        raise ControlCenterError(
            f"{field} darf höchstens {maximum} Einträge enthalten.",
            code=f"{field}_too_large",
        )
    return result


class PolicyMixin:
    def _repository_policy_in_connection(
        self,
        conn,
        project_id: int,
    ) -> Dict[str, Any]:
        normalized_id = int(project_id)
        conn.execute(
            """INSERT OR IGNORE INTO control_repository_policies (
                   project_id, protected_paths_json, capability_json
               ) VALUES (?, ?, ?)""",
            (
                normalized_id,
                json.dumps(DEFAULT_PROTECTED_PATHS),
                json.dumps(DEFAULT_CAPABILITIES),
            ),
        )
        row = conn.execute(
            "SELECT * FROM control_repository_policies WHERE project_id = ?",
            (normalized_id,),
        ).fetchone()
        result = self._row(
            row,
            (
                "protected_paths_json",
                "required_checks_json",
                "deployment_json",
                "capability_json",
            ),
        )
        result["capability"] = {
            **DEFAULT_CAPABILITIES,
            **(result.get("capability") or {}),
        }
        return result

    def get_repository_policy(self, project_id: Any) -> Dict[str, Any]:
        project = self._project(project_id)
        with self.db._get_connection() as conn:
            result = self._repository_policy_in_connection(conn, int(project["id"]))
            conn.commit()
        return result

    def update_repository_policy(
        self,
        project_id: Any,
        payload: Dict[str, Any],
        *,
        actor: str = "human",
    ) -> Dict[str, Any]:
        project = self._project(project_id)
        current = self.get_repository_policy(project["id"])
        activation_policy = str(
            payload.get("activation_policy", current["activation_policy"])
        ).strip()
        if activation_policy not in ACTIVATION_POLICIES:
            raise ControlCenterError(
                "Unbekannte Aktivierungs-Policy.",
                code="invalid_activation_policy",
            )

        def bounded_int(name: str, minimum: int, maximum: int) -> int:
            try:
                value = int(payload.get(name, current[name]))
            except (TypeError, ValueError) as exc:
                raise ControlCenterError(
                    f"{name} muss eine Zahl sein.",
                    code=f"invalid_{name}",
                ) from exc
            if not minimum <= value <= maximum:
                raise ControlCenterError(
                    f"{name} muss zwischen {minimum} und {maximum} liegen.",
                    code=f"invalid_{name}",
                )
            return value

        protected_paths = _json_list(
            payload.get("protected_paths", current.get("protected_paths")),
            "protected_paths",
        )
        required_checks = _json_list(
            payload.get("required_checks", current.get("required_checks")),
            "required_checks",
        )
        capabilities = {
            **DEFAULT_CAPABILITIES,
            **(current.get("capability") or {}),
        }
        requested_capabilities = payload.get("capability")
        if requested_capabilities is not None:
            if not isinstance(requested_capabilities, dict):
                raise ControlCenterError(
                    "capability muss ein Objekt sein.",
                    code="invalid_capability",
                )
            unknown = set(requested_capabilities) - set(DEFAULT_CAPABILITIES)
            if unknown:
                raise ControlCenterError(
                    f"Unbekannte Capabilities: {', '.join(sorted(unknown))}",
                    code="unknown_capability",
                )
            for key, value in requested_capabilities.items():
                if not isinstance(value, bool):
                    raise ControlCenterError(
                        f"Capability {key} muss ein Boolean sein.",
                        code="invalid_capability_value",
                    )
                capabilities[key] = value

        deployment = payload.get("deployment", current.get("deployment") or {})
        if not isinstance(deployment, dict):
            raise ControlCenterError(
                "deployment muss ein Objekt sein.",
                code="invalid_deployment_policy",
            )
        merge_strategy = str(
            payload.get("merge_strategy", current.get("merge_strategy") or "squash")
        ).strip().lower()
        if merge_strategy not in {"merge", "squash", "rebase"}:
            raise ControlCenterError(
                "Unbekannte Merge-Strategie.",
                code="invalid_merge_strategy",
            )

        values = {
            "activation_policy": activation_policy,
            "max_parallel_tasks": bounded_int("max_parallel_tasks", 1, 20),
            "max_open_prs": bounded_int("max_open_prs", 1, 100),
            "max_candidates": bounded_int("max_candidates", 1, 100),
            "max_retry_attempts": bounded_int("max_retry_attempts", 0, 20),
            "no_progress_limit": bounded_int("no_progress_limit", 1, 20),
            "lease_seconds": bounded_int("lease_seconds", 30, 86400),
            "protected_paths_json": json.dumps(protected_paths, ensure_ascii=False),
            "required_checks_json": json.dumps(required_checks, ensure_ascii=False),
            "deployment_json": json.dumps(deployment, ensure_ascii=False),
            "capability_json": json.dumps(capabilities, ensure_ascii=False),
            "merge_strategy": merge_strategy,
        }
        with self.db._get_connection() as conn:
            conn.execute(
                """UPDATE control_repository_policies
                   SET activation_policy = ?, max_parallel_tasks = ?, max_open_prs = ?,
                       max_candidates = ?, max_retry_attempts = ?, no_progress_limit = ?,
                       lease_seconds = ?, protected_paths_json = ?, required_checks_json = ?,
                       deployment_json = ?, capability_json = ?, merge_strategy = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE project_id = ?""",
                (*values.values(), int(project["id"])),
            )
            self._audit(
                conn,
                project_id=int(project["id"]),
                entity_type="policy",
                entity_id=f"repository:{project['id']}",
                action="repository_policy.updated",
                actor=str(actor or "human")[:120],
                reason=str(payload.get("reason") or "")[:2000],
                evidence={
                    "activation_policy": activation_policy,
                    "max_parallel_tasks": values["max_parallel_tasks"],
                    "max_open_prs": values["max_open_prs"],
                },
            )
            conn.commit()
        return self.get_repository_policy(project["id"])
