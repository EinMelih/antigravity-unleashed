"""Recommendation capture, deduplication, and disposition transitions."""

import hashlib

from src.control_center.common import (
    RECOMMENDATION_STATES,
    ControlCenterError,
    clean_text,
    public_id,
)


class RecommendationMixin:
    def create_recommendation(self, payload):
        project = self._project(payload.get("project_id"))
        title = clean_text(payload.get("title"), "title", minimum=3, maximum=200)
        summary = clean_text(payload.get("summary"), "summary", minimum=3, maximum=5000)
        evidence = str(payload.get("evidence") or "").strip()[:10000]
        source = str(payload.get("source") or "human").strip().lower()
        if source not in {"human", "agent", "system"}:
            raise ControlCenterError("Unbekannte Empfehlungsquelle.", code="invalid_source")
        risk = self._risk(payload.get("risk_level"))
        actor = clean_text(payload.get("actor") or "human", "actor", maximum=120)
        normalized = "|".join((str(project["id"]), title.casefold(), summary.casefold(), evidence.casefold()))
        dedupe_key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()

        with self.db._get_connection() as conn:
            duplicate = conn.execute(
                """SELECT * FROM control_recommendations
                   WHERE project_id = ? AND dedupe_key = ? AND status <> 'rejected'
                   ORDER BY created_at DESC LIMIT 1""",
                (project["id"], dedupe_key),
            ).fetchone()
            if duplicate:
                result = dict(duplicate)
                result["deduplicated"] = True
                return result
            recommendation_id = public_id("REC")
            conn.execute(
                """INSERT INTO control_recommendations (
                       id, project_id, title, summary, evidence, source, risk_level, dedupe_key
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (recommendation_id, project["id"], title, summary, evidence, source, risk, dedupe_key),
            )
            self._audit(
                conn,
                project_id=project["id"], entity_type="recommendation",
                entity_id=recommendation_id, action="recommendation.captured",
                actor=actor, to_state="new", evidence={"source": source, "risk_level": risk},
            )
            conn.commit()
            result = dict(conn.execute(
                "SELECT * FROM control_recommendations WHERE id = ?", (recommendation_id,)
            ).fetchone())
            result["deduplicated"] = False
            return result

    def disposition_recommendation(self, recommendation_id, *, disposition, reason, actor="human"):
        target = str(disposition or "").strip().lower()
        if target not in RECOMMENDATION_STATES - {"new"}:
            raise ControlCenterError("Unbekannte Entscheidung.", code="invalid_disposition")
        explanation = str(reason or "").strip()
        if target in {"deferred", "rejected"} and not explanation:
            raise ControlCenterError("Für diese Entscheidung ist eine Begründung erforderlich.", code="reason_required")
        actor_name = clean_text(actor, "actor", maximum=120)
        with self.db._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM control_recommendations WHERE id = ?", (recommendation_id,)
            ).fetchone()
            if not row:
                raise ControlCenterError("Empfehlung nicht gefunden.", code="recommendation_not_found", status=404)
            current = str(row["status"])
            allowed = {"new": {"accepted", "deferred", "rejected"}, "deferred": {"accepted", "rejected"}}
            if target == current:
                return dict(row)
            if target not in allowed.get(current, set()):
                raise ControlCenterError(
                    f"Übergang von {current} zu {target} ist nicht erlaubt.",
                    code="invalid_state_transition", status=409,
                )
            conn.execute(
                """UPDATE control_recommendations
                   SET status = ?, disposition_reason = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (target, explanation, recommendation_id),
            )
            if target == "accepted":
                self._attention(
                    conn, project_id=int(row["project_id"]), category="campaign_planning",
                    entity_type="recommendation", entity_id=recommendation_id,
                    title=f"Campaign für „{row['title']}“ planen",
                    consequence="Die Empfehlung ist akzeptiert, aber noch kein Umsetzungsplan freigegeben.",
                    recommendation="Campaign mit Ziel, Grenzen und kleinen PR-Slices anlegen.",
                )
            else:
                self._resolve_attention(conn, "recommendation", recommendation_id, "campaign_planning")
            self._audit(
                conn, project_id=int(row["project_id"]), entity_type="recommendation",
                entity_id=recommendation_id, action="recommendation.dispositioned",
                actor=actor_name, from_state=current, to_state=target, reason=explanation,
            )
            conn.commit()
            return dict(conn.execute(
                "SELECT * FROM control_recommendations WHERE id = ?", (recommendation_id,)
            ).fetchone())
