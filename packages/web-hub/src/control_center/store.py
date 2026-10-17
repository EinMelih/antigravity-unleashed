"""Composed Stage-1 control store and cross-cutting policy state."""

import json

from src.control_center.base import ControlStoreBase
from src.control_center.artifacts import ArtifactMixin
from src.control_center.amendments import AmendmentPlanningMixin
from src.control_center.campaigns import CampaignMixin
from src.control_center.candidates import CandidateMixin
from src.control_center.common import CONTROL_MODES, ENTITY_TYPES, ControlCenterError, clean_text, public_id
from src.control_center.delivery import DeliveryMixin
from src.control_center.evidence import EvidenceMixin
from src.control_center.execution import ExecutionMixin
from src.control_center.knowledge import KnowledgeMixin
from src.control_center.overview import OverviewMixin
from src.control_center.planning import PlanningMixin
from src.control_center.planning_jobs import PlanningJobMixin
from src.control_center.policies import PolicyMixin
from src.control_center.recommendations import RecommendationMixin
from src.control_center.work_orders import WorkOrderMixin
from src.control_center.webhooks import WebhookMixin


class ControlCenterStore(
    PolicyMixin,
    ArtifactMixin,
    KnowledgeMixin,
    AmendmentPlanningMixin,
    PlanningMixin,
    PlanningJobMixin,
    ExecutionMixin,
    EvidenceMixin,
    DeliveryMixin,
    WebhookMixin,
    RecommendationMixin,
    CampaignMixin,
    CandidateMixin,
    WorkOrderMixin,
    OverviewMixin,
    ControlStoreBase,
):
    """SQLite-backed control center with explicit, auditable transitions."""

    def get_policy(self):
        with self.db._get_connection() as conn:
            result = dict(conn.execute(
                "SELECT * FROM control_settings WHERE singleton_id = 1"
            ).fetchone())
            result["paused"] = bool(result["paused"])
            return result

    def update_policy(self, *, mode, paused, reason, actor="human"):
        selected_mode = str(mode or "guided").strip().lower()
        if selected_mode not in CONTROL_MODES:
            raise ControlCenterError(
                "Erlaubte Modi sind Observer, Guided, Campaign und Autopilot.",
                code="unsupported_control_mode",
            )
        if not isinstance(paused, bool):
            raise ControlCenterError("paused muss ein Boolean sein.", code="invalid_paused_value")
        pause_reason = str(reason or "").strip()
        if paused and not pause_reason:
            raise ControlCenterError("Für die Pause ist eine Begründung erforderlich.", code="pause_reason_required")
        actor_name = clean_text(actor, "actor", maximum=120)
        before = self.get_policy()
        with self.db._get_connection() as conn:
            conn.execute(
                """UPDATE control_settings
                   SET mode = ?, paused = ?, pause_reason = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE singleton_id = 1""",
                (selected_mode, 1 if paused else 0, pause_reason if paused else ""),
            )
            self._audit(
                conn, project_id=None, entity_type="policy", entity_id="global",
                action="policy.updated", actor=actor_name,
                from_state=f"{before['mode']}:{'paused' if before['paused'] else 'running'}",
                to_state=f"{selected_mode}:{'paused' if paused else 'running'}",
                reason=pause_reason,
            )
            conn.commit()
        return self.get_policy()

    def create_checkpoint(self, payload):
        project = self._project(payload.get("project_id"))
        entity_type = str(payload.get("entity_type") or "").strip()
        if entity_type not in ENTITY_TYPES:
            raise ControlCenterError("Ungültiger Checkpoint-Entitätstyp.", code="invalid_entity_type")
        entity_id = clean_text(payload.get("entity_id"), "entity_id", maximum=80)
        summary = clean_text(payload.get("summary"), "summary", minimum=3, maximum=5000)
        actor = clean_text(payload.get("actor") or "agent", "actor", maximum=120)
        details = payload.get("payload") or {}
        if not isinstance(details, dict):
            raise ControlCenterError("Checkpoint-Payload muss ein Objekt sein.", code="invalid_checkpoint_payload")
        checkpoint_id = public_id("CHK")
        with self.db._get_connection() as conn:
            conn.execute(
                """INSERT INTO control_checkpoints (
                       id, project_id, entity_type, entity_id, actor, summary, payload_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    checkpoint_id, project["id"], entity_type, entity_id,
                    actor, summary, json.dumps(details, ensure_ascii=False),
                ),
            )
            self._audit(
                conn, project_id=int(project["id"]), entity_type=entity_type,
                entity_id=entity_id, action="checkpoint.created", actor=actor,
                evidence={"checkpoint_id": checkpoint_id},
            )
            conn.commit()
            return self._row(conn.execute(
                "SELECT * FROM control_checkpoints WHERE id = ?", (checkpoint_id,)
            ).fetchone(), ("payload_json",))

    def get_idempotent(self, key, operation):
        if not key:
            return None
        with self.db._get_connection() as conn:
            row = conn.execute(
                """SELECT operation, response_json FROM control_idempotency
                   WHERE idempotency_key = ?""",
                (key,),
            ).fetchone()
            if not row:
                return None
            if row["operation"] != operation:
                raise ControlCenterError(
                    "Idempotency-Key wurde bereits für eine andere Aktion verwendet.",
                    code="idempotency_conflict", status=409,
                )
            return json.loads(row["response_json"])

    def remember_idempotent(self, key, operation, response):
        if not key:
            return
        with self.db._get_connection() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO control_idempotency (
                       idempotency_key, operation, response_json
                   ) VALUES (?, ?, ?)""",
                (key, operation, json.dumps(response, ensure_ascii=False)),
            )
            conn.commit()
