"""Small PR-candidate contracts and dependency validation."""

import json

from src.control_center.common import (
    ControlCenterError,
    clean_text,
    public_id,
    validate_acceptance_criteria,
)


class CandidateMixin:
    def create_pr_candidate(self, campaign_id, payload):
        title = clean_text(payload.get("title"), "title", minimum=3, maximum=200)
        scope = clean_text(payload.get("scope"), "scope", minimum=10, maximum=10000)
        criteria = validate_acceptance_criteria(payload.get("acceptance_criteria"))
        non_goals = str(payload.get("non_goals") or "").strip()[:5000]
        risk = self._risk(payload.get("risk_level"))
        try:
            priority = int(payload.get("priority", 100))
        except (TypeError, ValueError):
            raise ControlCenterError("Priorität muss eine Zahl sein.", code="invalid_priority")
        dependencies = payload.get("depends_on") or []
        if not isinstance(dependencies, list):
            raise ControlCenterError("depends_on muss eine Liste sein.", code="invalid_dependencies")
        dependencies = list(dict.fromkeys(str(item).strip() for item in dependencies if str(item).strip()))
        actor = clean_text(payload.get("actor") or "human", "actor", maximum=120)

        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            campaign = self._campaign(conn, campaign_id)
            if campaign["status"] != "draft":
                raise ControlCenterError(
                    "PR-Slices können nach der Planfreigabe nur über ein Amendment geändert werden.",
                    code="campaign_locked", status=409,
                )
            profile = conn.execute(
                """SELECT requested_max_candidates FROM control_campaign_profiles
                   WHERE campaign_id = ?""",
                (campaign_id,),
            ).fetchone()
            policy = conn.execute(
                """SELECT max_candidates FROM control_repository_policies
                   WHERE project_id = ?""",
                (int(campaign["project_id"]),),
            ).fetchone()
            limit = min(
                int(profile["requested_max_candidates"] if profile else 5),
                int(policy["max_candidates"] if policy else 100),
                100,
            )
            existing_count = int(
                conn.execute(
                    """SELECT COUNT(*) AS count FROM control_pr_candidates
                       WHERE campaign_id = ?""",
                    (campaign_id,),
                ).fetchone()["count"]
            )
            if existing_count >= limit:
                raise ControlCenterError(
                    f"Das Campaign-Limit von {limit} PR Candidates ist erreicht.",
                    code="candidate_limit_reached",
                    status=409,
                )
            base_sha = str(campaign["base_sha"] or "")
            candidate_id = public_id("PRC")
            conn.execute(
                """INSERT INTO control_pr_candidates (
                       id, campaign_id, title, scope, acceptance_criteria_json,
                       non_goals, risk_level, priority, base_sha
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    candidate_id, campaign_id, title, scope,
                    json.dumps(criteria, ensure_ascii=False), non_goals, risk, priority, base_sha,
                ),
            )
            self._write_candidate_contract(conn, candidate_id, payload, criteria)
            for dependency_id in dependencies:
                dependency = conn.execute(
                    "SELECT campaign_id FROM control_pr_candidates WHERE id = ?", (dependency_id,)
                ).fetchone()
                if not dependency or dependency["campaign_id"] != campaign_id:
                    raise ControlCenterError(
                        "Alle PR-Abhängigkeiten müssen aus derselben Campaign stammen.",
                        code="invalid_dependency",
                    )
                conn.execute(
                    "INSERT INTO control_pr_dependencies (candidate_id, depends_on_id) VALUES (?, ?)",
                    (candidate_id, dependency_id),
                )
            self._validate_dag(conn, campaign_id)
            self._invalidate_draft_plan_in_connection(conn, campaign_id)
            self._audit(
                conn, project_id=int(campaign["project_id"]), entity_type="pr_candidate",
                entity_id=candidate_id, action="pr_candidate.created", actor=actor,
                to_state="ready",
                evidence={"campaign_id": campaign_id, "depends_on": dependencies, "base_sha": base_sha},
            )
            conn.commit()
            result = self._row(conn.execute(
                "SELECT * FROM control_pr_candidates WHERE id = ?", (candidate_id,)
            ).fetchone(), ("acceptance_criteria_json",))
            result["depends_on"] = dependencies
            result["contract"] = self._row(
                conn.execute(
                    """SELECT * FROM control_candidate_contracts
                       WHERE candidate_id = ?""",
                    (candidate_id,),
                ).fetchone(),
                (
                    "components_json",
                    "required_checks_json",
                    "manual_tests_json",
                    "documentation_json",
                ),
            )
            return result
