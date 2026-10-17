"""Canonical idea, design, ADR, and architecture artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict

from src.control_center.common import (
    ControlCenterError,
    canonical_json_sha256,
    clean_text,
    public_id,
)


ARTIFACT_TYPES = {
    "idea_group",
    "design_document",
    "adr",
    "arc42",
    "repository_map",
    "plan_simulation",
    "test_pack",
    "evidence_pack",
}

ARTIFACT_STATUSES = {
    "draft",
    "proposed",
    "accepted",
    "deprecated",
    "superseded",
    "current",
}

IDEA_SEED_EDITABLE_FIELDS = {"title", "note", "source", "provenance"}
IDEA_SEED_STATES = {"inbox", "deferred", "dismissed", "planning", "planned"}
IDEA_SEED_DISPOSITIONS = {"inbox", "deferred", "dismissed"}
IDEA_SEED_TRANSITIONS = {
    "inbox": {"deferred", "dismissed"},
    "deferred": {"inbox", "dismissed"},
    "dismissed": {"inbox"},
}


def slugify(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9äöüß]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    if not text:
        raise ControlCenterError("slug ist erforderlich.", code="missing_slug")
    return text[:100]


def _artifact_relative_path(artifact_type: str, slug: str, metadata: Dict[str, Any]) -> str:
    if artifact_type == "idea_group":
        filename = str(metadata.get("filename") or "README.md")
        allowed = {"README.md", "idea.md", "context.md", "sources.md", "decisions.md"}
        if filename not in allowed:
            raise ControlCenterError(
                "Ungültige Idea-Group-Datei.",
                code="invalid_idea_group_file",
            )
        return f"docs/ideas/{slug}/{filename}"
    if artifact_type == "design_document":
        return f"docs/design/{slug}.md"
    if artifact_type == "adr":
        return f"docs/adr/{slug}.md"
    if artifact_type == "arc42":
        return "docs/arc42/index.md"
    if artifact_type == "repository_map":
        return f"docs/design/{slug}-repository-map.md"
    if artifact_type == "plan_simulation":
        return f"docs/design/{slug}-plan-simulation.md"
    if artifact_type == "test_pack":
        return f"docs/test-packs/{slug}.md"
    return f"docs/evidence/{slug}.md"


class ArtifactMixin:
    def create_idea_seed(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        project = self._project(payload.get("project_id"))
        title = clean_text(payload.get("title"), "title", minimum=3, maximum=200)
        note = clean_text(payload.get("note"), "note", minimum=3, maximum=5000)
        source = str(payload.get("source") or "human").strip()[:120]
        provenance = payload.get("provenance") or {}
        if not isinstance(provenance, dict):
            raise ControlCenterError(
                "provenance muss ein Objekt sein.",
                code="invalid_provenance",
            )
        seed_id = public_id("IDEA")
        with self.db._get_connection() as conn:
            conn.execute(
                """INSERT INTO control_idea_seeds (
                       id, project_id, title, note, source, provenance_json
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    seed_id,
                    int(project["id"]),
                    title,
                    note,
                    source,
                    json.dumps(provenance, ensure_ascii=False),
                ),
            )
            self._audit(
                conn,
                project_id=int(project["id"]),
                entity_type="idea_seed",
                entity_id=seed_id,
                action="idea_seed.created",
                actor=source,
                to_state="inbox",
                evidence=provenance,
            )
            conn.commit()
            return self._row(
                conn.execute(
                    "SELECT * FROM control_idea_seeds WHERE id = ?",
                    (seed_id,),
                ).fetchone(),
                ("provenance_json",),
            )

    def list_idea_seeds(
        self,
        project_id: Any = None,
    ) -> list[Dict[str, Any]]:
        query = "SELECT * FROM control_idea_seeds"
        params: tuple[Any, ...] = ()
        if project_id not in (None, ""):
            project = self._project(project_id)
            query += " WHERE project_id = ?"
            params = (int(project["id"]),)
        else:
            query += (
                " WHERE project_id IN "
                "(SELECT id FROM projects WHERE archived_at IS NULL)"
            )
        query += " ORDER BY created_at DESC, id DESC"
        with self.db._get_connection() as conn:
            return [
                self._row(row, ("provenance_json",))
                for row in conn.execute(query, params).fetchall()
            ]

    def get_idea_seed(self, idea_seed_id: str) -> Dict[str, Any]:
        with self.db._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM control_idea_seeds WHERE id = ?",
                (str(idea_seed_id),),
            ).fetchone()
        if not row:
            raise ControlCenterError(
                "Idea Seed nicht gefunden.",
                code="idea_seed_not_found",
                status=404,
            )
        return self._row(row, ("provenance_json",))

    def update_idea_seed(
        self,
        idea_seed_id: str,
        payload: Dict[str, Any],
        *,
        actor: str = "human",
    ) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise ControlCenterError(
                "Idea-Seed-Änderung muss ein Objekt sein.",
                code="invalid_idea_seed_update",
            )
        unknown_fields = set(payload) - IDEA_SEED_EDITABLE_FIELDS
        if unknown_fields:
            raise ControlCenterError(
                "Diese Idea-Seed-Felder können nicht geändert werden.",
                code="invalid_idea_seed_fields",
            )
        if not payload:
            raise ControlCenterError(
                "Mindestens ein Idea-Seed-Feld ist erforderlich.",
                code="idea_seed_update_required",
            )

        updates: Dict[str, Any] = {}
        if "title" in payload:
            updates["title"] = clean_text(
                payload.get("title"),
                "title",
                minimum=3,
                maximum=200,
            )
        if "note" in payload:
            updates["note"] = clean_text(
                payload.get("note"),
                "note",
                minimum=3,
                maximum=5000,
            )
        if "source" in payload:
            updates["source"] = clean_text(
                payload.get("source"),
                "source",
                maximum=120,
            )
        if "provenance" in payload:
            provenance = payload.get("provenance")
            if not isinstance(provenance, dict):
                raise ControlCenterError(
                    "provenance muss ein Objekt sein.",
                    code="invalid_provenance",
                )
            updates["provenance_json"] = json.dumps(
                provenance,
                ensure_ascii=False,
            )

        actor_name = clean_text(actor, "actor", maximum=120)
        assignments = ", ".join(f"{field} = ?" for field in updates)
        values = list(updates.values())
        with self.db._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM control_idea_seeds WHERE id = ?",
                (str(idea_seed_id),),
            ).fetchone()
            if not row:
                raise ControlCenterError(
                    "Idea Seed nicht gefunden.",
                    code="idea_seed_not_found",
                    status=404,
                )
            conn.execute(
                f"""UPDATE control_idea_seeds
                    SET {assignments}, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?""",
                (*values, str(idea_seed_id)),
            )
            self._audit(
                conn,
                project_id=int(row["project_id"]),
                entity_type="idea_seed",
                entity_id=str(idea_seed_id),
                action="idea_seed.updated",
                actor=actor_name,
                from_state=str(row["status"]),
                to_state=str(row["status"]),
                evidence={"fields": sorted(payload)},
            )
            conn.commit()
        return self.get_idea_seed(str(idea_seed_id))

    def disposition_idea_seed(
        self,
        idea_seed_id: str,
        *,
        disposition: str,
        reason: str = "",
        actor: str = "human",
    ) -> Dict[str, Any]:
        target = str(disposition or "").strip().lower()
        if target not in IDEA_SEED_DISPOSITIONS:
            raise ControlCenterError(
                "Unbekannte Idea-Seed-Entscheidung.",
                code="invalid_disposition",
            )
        explanation = str(reason or "").strip()
        if target in {"deferred", "dismissed"} and not explanation:
            raise ControlCenterError(
                "Für diese Entscheidung ist eine Begründung erforderlich.",
                code="reason_required",
            )
        actor_name = clean_text(actor, "actor", maximum=120)
        with self.db._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM control_idea_seeds WHERE id = ?",
                (str(idea_seed_id),),
            ).fetchone()
            if not row:
                raise ControlCenterError(
                    "Idea Seed nicht gefunden.",
                    code="idea_seed_not_found",
                    status=404,
                )
            current = str(row["status"])
            if target == current:
                return self._row(row, ("provenance_json",))
            if target not in IDEA_SEED_TRANSITIONS.get(current, set()):
                raise ControlCenterError(
                    f"Übergang von {current} zu {target} ist nicht erlaubt.",
                    code="invalid_state_transition",
                    status=409,
                )
            conn.execute(
                """UPDATE control_idea_seeds
                   SET status = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (target, str(idea_seed_id)),
            )
            self._audit(
                conn,
                project_id=int(row["project_id"]),
                entity_type="idea_seed",
                entity_id=str(idea_seed_id),
                action="idea_seed.dispositioned",
                actor=actor_name,
                from_state=current,
                to_state=target,
                reason=explanation,
            )
            conn.commit()
        return self.get_idea_seed(str(idea_seed_id))

    def save_artifact(
        self,
        payload: Dict[str, Any],
        *,
        actor: str = "human",
    ) -> Dict[str, Any]:
        project = self._project(payload.get("project_id"))
        artifact_type = str(payload.get("artifact_type") or "").strip()
        if artifact_type not in ARTIFACT_TYPES:
            raise ControlCenterError(
                "Unbekannter Artefakttyp.",
                code="invalid_artifact_type",
            )
        title = clean_text(payload.get("title"), "title", minimum=3, maximum=250)
        slug = slugify(payload.get("slug") or title)
        content = clean_text(
            payload.get("content"),
            "content",
            minimum=3,
            maximum=500_000,
        )
        status = str(payload.get("status") or "draft").strip().lower()
        if status not in ARTIFACT_STATUSES:
            raise ControlCenterError(
                "Ungültiger Artefaktstatus.",
                code="invalid_artifact_status",
            )
        metadata = payload.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ControlCenterError(
                "metadata muss ein Objekt sein.",
                code="invalid_artifact_metadata",
            )
        campaign_id = str(payload.get("campaign_id") or "").strip() or None
        supersedes_id = str(payload.get("supersedes_id") or "").strip() or None
        materialize = payload.get("materialize", True)
        if not isinstance(materialize, bool):
            raise ControlCenterError(
                "materialize muss ein Boolean sein.",
                code="invalid_materialize",
            )
        destination: Path | None = None
        if materialize:
            root = Path(str(project.get("path") or "")).resolve()
            if not root.is_dir():
                raise ControlCenterError(
                    "Der lokale Projektordner ist nicht verfügbar.",
                    code="project_path_unavailable",
                    status=409,
                )

        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            campaign = None
            if campaign_id:
                campaign = self._campaign(conn, campaign_id)
                if int(campaign["project_id"]) != int(project["id"]):
                    raise ControlCenterError(
                        "Campaign und Artefakt gehören nicht zum selben Projekt.",
                        code="artifact_campaign_mismatch",
                    )
                if str(campaign["status"]) != "draft":
                    raise ControlCenterError(
                        "Ein genehmigter Plan benötigt ein Amendment.",
                        code="campaign_locked",
                        status=409,
                    )
            if supersedes_id:
                previous = conn.execute(
                    "SELECT * FROM control_artifacts WHERE id = ?",
                    (supersedes_id,),
                ).fetchone()
                if not previous or int(previous["project_id"]) != int(project["id"]):
                    raise ControlCenterError(
                        "Das ersetzte Artefakt wurde nicht gefunden.",
                        code="superseded_artifact_not_found",
                        status=404,
                    )
                previous_campaign_id = (
                    str(previous["campaign_id"] or "").strip() or None
                )
                if previous_campaign_id != campaign_id:
                    raise ControlCenterError(
                        "Artefakte dürfen nur innerhalb derselben Campaign "
                        "ersetzt werden.",
                        code="artifact_supersedes_campaign_mismatch",
                        status=409,
                    )
            if campaign:
                post_mutation_version = self._invalidate_draft_plan_in_connection(
                    conn,
                    campaign_id,
                )
                metadata = {
                    **metadata,
                    "base_sha": str(campaign["base_sha"] or "").strip().lower(),
                    "campaign_version": post_mutation_version,
                }
                if artifact_type == "plan_simulation":
                    canonical_simulation = self._simulate_campaign_in_connection(
                        conn,
                        campaign_id,
                        persist=False,
                    )
                    metadata["simulation_sha256"] = canonical_json_sha256(
                        canonical_simulation
                    )
            latest = conn.execute(
                """SELECT MAX(version) AS version FROM control_artifacts
                   WHERE project_id = ? AND artifact_type = ? AND slug = ?""",
                (int(project["id"]), artifact_type, slug),
            ).fetchone()
            version = int(latest["version"] or 0) + 1
            relative_path = _artifact_relative_path(artifact_type, slug, metadata)
            if materialize:
                destination = (root / relative_path).resolve()
                if not destination.is_relative_to(root):
                    raise ControlCenterError(
                        "Ungültiger Artefaktpfad.",
                        code="artifact_path_escape",
                    )
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            artifact_id = public_id("DOC")
            conn.execute(
                """INSERT INTO control_artifacts (
                       id, project_id, campaign_id, artifact_type, slug, title,
                       status, version, supersedes_id, relative_path, content_text,
                       content_sha256, metadata_json, materialization_status
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    artifact_id,
                    int(project["id"]),
                    campaign_id,
                    artifact_type,
                    slug,
                    title,
                    status,
                    version,
                    supersedes_id,
                    relative_path,
                    content,
                    digest,
                    json.dumps(metadata, ensure_ascii=False),
                    "pending" if materialize else "not_requested",
                ),
            )
            if supersedes_id:
                conn.execute(
                    """UPDATE control_artifacts
                       SET status = 'superseded', updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (supersedes_id,),
                )
            self._audit(
                conn,
                project_id=int(project["id"]),
                entity_type=artifact_type,
                entity_id=artifact_id,
                action="artifact.created",
                actor=str(actor or "human")[:120],
                to_state=status,
                evidence={
                    "version": version,
                    "path": relative_path,
                    "sha256": digest,
                    "campaign_id": campaign_id,
                },
            )
            if destination is None:
                conn.commit()
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                temp_path = destination.with_name(
                    f".{destination.name}.{artifact_id}.tmp"
                )
                previous_content = (
                    destination.read_bytes() if destination.exists() else None
                )
                materialized_bytes = (content.rstrip() + "\n").encode("utf-8")
                materialized_digest = hashlib.sha256(materialized_bytes).hexdigest()
                replacement_applied = False
                try:
                    temp_path.write_bytes(materialized_bytes)
                    temp_path.replace(destination)
                    replacement_applied = True
                    conn.execute(
                        """UPDATE control_artifacts
                           SET materialization_status = 'materialized',
                               materialized_sha256 = ?,
                               materialized_at = CURRENT_TIMESTAMP,
                               updated_at = CURRENT_TIMESTAMP
                           WHERE id = ?""",
                        (materialized_digest, artifact_id),
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    if replacement_applied:
                        if previous_content is None:
                            destination.unlink(missing_ok=True)
                        else:
                            restore_path = destination.with_name(
                                f".{destination.name}.{artifact_id}.restore"
                            )
                            try:
                                restore_path.write_bytes(previous_content)
                                restore_path.replace(destination)
                            finally:
                                restore_path.unlink(missing_ok=True)
                    raise
                finally:
                    temp_path.unlink(missing_ok=True)

        return self.get_artifact(artifact_id)

    def get_artifact(self, artifact_id: str) -> Dict[str, Any]:
        with self.db._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM control_artifacts WHERE id = ?",
                (str(artifact_id),),
            ).fetchone()
        if not row:
            raise ControlCenterError(
                "Artefakt nicht gefunden.",
                code="artifact_not_found",
                status=404,
            )
        return self._row(row, ("metadata_json",))

    def list_artifacts(self, project_id: Any, campaign_id: str = "") -> list[Dict[str, Any]]:
        project = self._project(project_id)
        query = "SELECT * FROM control_artifacts WHERE project_id = ?"
        params: list[Any] = [int(project["id"])]
        if campaign_id:
            query += " AND campaign_id = ?"
            params.append(campaign_id)
        query += " ORDER BY updated_at DESC, version DESC"
        with self.db._get_connection() as conn:
            return [
                self._row(row, ("metadata_json",))
                for row in conn.execute(query, params).fetchall()
            ]
