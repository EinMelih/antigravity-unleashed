"""Validated semantic links and read models for durable knowledge chains."""

from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import Any, Dict
from urllib.parse import urlsplit, urlunsplit

from src.control_center.artifacts import _artifact_relative_path, slugify
from src.control_center.common import ControlCenterError, clean_text, public_id


KNOWLEDGE_RELATIONS = {
    ("idea_seed", "artifact"): {
        "developed_into",
        "references",
    },
    ("artifact", "artifact"): {
        "contains",
        "informs",
        "decided_by",
        "references",
    },
    ("candidate", "artifact"): {
        "implements_design",
        "follows_decision",
        "references",
    },
}


class KnowledgeMixin:
    """Keep semantic knowledge links coherent behind one Store interface."""

    @staticmethod
    def _markdown_list(values: Any, *, empty: str) -> list[str]:
        if not isinstance(values, list):
            values = []
        items = [str(value).strip() for value in values if str(value).strip()]
        return [f"- {item}" for item in items] or [f"- {empty}"]

    @staticmethod
    def _external_source_references(value: Any) -> list[str]:
        references: set[str] = set()

        def visit(item: Any) -> None:
            if isinstance(item, dict):
                for nested in item.values():
                    visit(nested)
            elif isinstance(item, list):
                for nested in item:
                    visit(nested)
            elif isinstance(item, str):
                candidate = item.strip()
                try:
                    parsed = urlsplit(candidate)
                except ValueError:
                    return
                if parsed.scheme in {"http", "https"} and parsed.netloc:
                    references.add(candidate)

        visit(value)
        return sorted(references)

    def _build_planning_knowledge_documents(
        self,
        *,
        seed,
        job: Dict[str, Any],
        plan: Dict[str, Any],
        campaign_id: str,
        base_sha: str,
        grounded_paths: list[str],
        branch_assessments: list[Dict[str, Any]],
    ) -> Dict[str, Any]:
        title = str(plan["title"]).strip()
        goal = str(plan.get("goal") or job["wish"]).strip()
        non_goals = str(plan.get("non_goals") or "").strip()
        group_slug = slugify(title)
        candidates = [
            candidate
            for candidate in (plan.get("candidates") or [])
            if isinstance(candidate, dict)
        ]
        provenance = {}
        try:
            loaded_provenance = json.loads(seed["provenance_json"] or "{}")
            if isinstance(loaded_provenance, dict):
                provenance = loaded_provenance
        except (json.JSONDecodeError, TypeError):
            provenance = {}
        sources = self._external_source_references(provenance)

        readme = "\n".join(
            (
                f"# {title}",
                "",
                "## Status",
                "",
                "- State: proposed",
                f"- Idea Seed: `{seed['id']}`",
                f"- Planning Job: `{job['id']}`",
                f"- Campaign: `{campaign_id}`",
                f"- Source: {str(seed['source'] or 'unknown').strip()}",
                "",
                "## Reading order",
                "",
                "1. `idea.md`",
                "2. `context.md`",
                "3. `sources.md`",
                "4. `decisions.md`",
            )
        )
        candidate_lines: list[str] = []
        for candidate in candidates:
            candidate_lines.extend(
                (
                    f"### {str(candidate.get('title') or '').strip()}",
                    "",
                    str(candidate.get("scope") or "").strip(),
                    "",
                )
            )
        idea = "\n".join(
            (
                f"# Idea: {str(seed['title']).strip()}",
                "",
                "## Seed note",
                "",
                str(seed["note"]).strip(),
                "",
                "## Planning wish",
                "",
                str(job["wish"]).strip(),
                "",
                "## Goal",
                "",
                goal,
                "",
                "## Non-goals",
                "",
                non_goals,
                "",
                "## Success metrics",
                "",
                *self._markdown_list(
                    plan.get("success_metrics"),
                    empty="No success metric was recorded.",
                ),
                "",
                "## Planned PR slices",
                "",
                *candidate_lines,
            )
        ).rstrip()
        context = "\n".join(
            (
                "# Repository context",
                "",
                "## Pinned baseline",
                "",
                f"`{base_sha}`",
                "",
                "## Verified repository paths",
                "",
                *self._markdown_list(
                    grounded_paths,
                    empty="No repository path was verified.",
                ),
                "",
                "## Constraints",
                "",
                *self._markdown_list(
                    plan.get("constraints", job.get("constraints")),
                    empty="No additional constraint was recorded.",
                ),
            )
        )
        source_lines = (
            [f"- {reference}" for reference in sources]
            if sources
            else ["- No external source was attached to the Idea Seed."]
        )
        sources_document = "\n".join(
            (
                "# Sources",
                "",
                *source_lines,
                "",
                "## Repository evidence",
                "",
                f"- Pinned baseline: `{base_sha}`",
                *[f"- `{path}`" for path in grounded_paths],
            )
        )
        alternative_lines: list[str] = []
        for alternative in plan.get("alternatives") or []:
            if not isinstance(alternative, dict):
                continue
            alternative_lines.extend(
                (
                    f"### {str(alternative.get('title') or '').strip()}",
                    "",
                    str(alternative.get("mechanism") or "").strip(),
                    "",
                    f"Trade-offs: {str(alternative.get('tradeoffs') or '').strip()}",
                    "",
                )
            )
        assessment_lines = [
            "- "
            + f"{str(assessment.get('branch') or '').strip()}: "
            + str(assessment.get("status") or "").strip()
            for assessment in branch_assessments
        ]
        pivotal_fork = str(plan.get("pivotal_fork") or "").strip()
        pivotal_na_reason = str(
            plan.get("pivotal_fork_na_reason") or ""
        ).strip()
        pivotal_statement = (
            pivotal_fork
            or (
                f"Not applicable: {pivotal_na_reason}"
                if pivotal_na_reason
                else "No pivotal fork or N/A rationale was recorded."
            )
        )
        decisions = "\n".join(
            (
                "# Decisions",
                "",
                "## Pivotal fork",
                "",
                pivotal_statement,
                "",
                "## Alternatives",
                "",
                *alternative_lines,
                "## Assumptions",
                "",
                *self._markdown_list(
                    plan.get("assumptions"),
                    empty="No assumption was recorded.",
                ),
                "",
                "## Decision branches",
                "",
                *assessment_lines,
            )
        ).rstrip()

        supplied_design = plan.get("design_document")
        if supplied_design not in (None, "") and not isinstance(
            supplied_design,
            str,
        ):
            raise ControlCenterError(
                "design_document muss Markdown-Text sein.",
                code="invalid_generated_design_document",
            )
        design_document = str(supplied_design or "").strip()
        if not design_document:
            design_document = "\n".join(
                (
                    f"# Design: {title}",
                    "",
                    "## Goal",
                    "",
                    goal,
                    "",
                    "## Repository scope",
                    "",
                    *[f"- `{path}`" for path in grounded_paths],
                    "",
                    "## PR slices",
                    "",
                    *candidate_lines,
                    "## Verification",
                    "",
                    str(plan.get("review_strategy") or "").strip(),
                    "",
                    "## Rollout",
                    "",
                    str(plan.get("rollout_plan") or "").strip(),
                    "",
                    "## Rollback",
                    "",
                    str(plan.get("rollback_plan") or "").strip(),
                )
            ).rstrip()

        supplied_adr = plan.get("adr")
        if supplied_adr not in (None, "") and not isinstance(supplied_adr, str):
            raise ControlCenterError(
                "adr muss Markdown-Text sein.",
                code="invalid_generated_adr",
            )
        adr = str(supplied_adr or "").strip()
        if not adr:
            adr = "\n".join(
                (
                    f"# ADR: {title}",
                    "",
                    "## Status",
                    "",
                    "proposed",
                    "",
                    "## Decision under review",
                    "",
                    pivotal_statement,
                    "",
                    "## Considered alternatives",
                    "",
                    *alternative_lines,
                )
            ).rstrip()

        return {
            "group_slug": group_slug,
            "idea_group": [
                ("README.md", readme),
                ("idea.md", idea),
                ("context.md", context),
                ("sources.md", sources_document),
                ("decisions.md", decisions),
            ],
            "design_document": design_document,
            "adr": adr,
        }

    def _insert_planned_artifact_in_connection(
        self,
        conn,
        *,
        project_id: int,
        campaign_id: str,
        artifact_type: str,
        slug: str,
        title: str,
        status: str,
        content: str,
        metadata: Dict[str, Any],
        relative_path: str = "",
    ) -> Dict[str, Any]:
        artifact_slug = slugify(slug)
        latest = conn.execute(
            """SELECT MAX(version) AS version FROM control_artifacts
               WHERE project_id = ? AND artifact_type = ? AND slug = ?""",
            (project_id, artifact_type, artifact_slug),
        ).fetchone()
        version = int(latest["version"] or 0) + 1
        artifact_id = public_id("DOC")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        path = relative_path or _artifact_relative_path(
            artifact_type,
            artifact_slug,
            metadata,
        )
        normalized_path = PurePosixPath(path).as_posix()
        if (
            PurePosixPath(normalized_path).is_absolute()
            or ".." in PurePosixPath(normalized_path).parts
        ):
            raise ControlCenterError(
                "Ungültiger geplanter Artefaktpfad.",
                code="artifact_path_escape",
            )
        conn.execute(
            """INSERT INTO control_artifacts (
                   id, project_id, campaign_id, artifact_type, slug, title,
                   status, version, relative_path, content_text,
                   content_sha256, metadata_json, materialization_status
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'not_requested')""",
            (
                artifact_id,
                project_id,
                campaign_id,
                artifact_type,
                artifact_slug,
                title,
                status,
                version,
                normalized_path,
                content,
                digest,
                json.dumps(metadata, ensure_ascii=False),
            ),
        )
        return dict(
            conn.execute(
                "SELECT * FROM control_artifacts WHERE id = ?",
                (artifact_id,),
            ).fetchone()
        )

    @staticmethod
    def _knowledge_entity(conn, kind: str, entity_id: str):
        if kind == "idea_seed":
            row = conn.execute(
                """SELECT id, project_id, NULL AS campaign_id
                   FROM control_idea_seeds WHERE id = ?""",
                (entity_id,),
            ).fetchone()
        elif kind == "artifact":
            row = conn.execute(
                """SELECT id, project_id, campaign_id
                   FROM control_artifacts WHERE id = ?""",
                (entity_id,),
            ).fetchone()
        elif kind == "candidate":
            row = conn.execute(
                """SELECT candidate.id, campaign.project_id,
                          candidate.campaign_id
                   FROM control_pr_candidates candidate
                   JOIN control_campaigns campaign
                     ON campaign.id = candidate.campaign_id
                   WHERE candidate.id = ?""",
                (entity_id,),
            ).fetchone()
        else:
            row = None
        if not row:
            raise ControlCenterError(
                "Knowledge-Entität nicht gefunden.",
                code=f"knowledge_{kind}_not_found",
                status=404,
            )
        return row

    @staticmethod
    def _knowledge_relation_shape(
        source_kind: str,
        source_id: str,
        target_kind: str,
        target_id: str,
        relation_type: str,
    ) -> Dict[str, str]:
        return {
            "source_kind": source_kind,
            "source_id": source_id,
            "target_kind": target_kind,
            "target_id": target_id,
            "relation_type": relation_type,
        }

    @staticmethod
    def _idea_seed_campaign_ids_in_connection(
        conn,
        idea_seed_id: str,
    ) -> set[str]:
        rows = conn.execute(
            """SELECT campaign_id
                 FROM control_planning_jobs
                WHERE idea_seed_id = ? AND campaign_id IS NOT NULL
               UNION
               SELECT artifact.campaign_id
                 FROM control_idea_seed_artifacts link
                 JOIN control_artifacts artifact
                   ON artifact.id = link.artifact_id
                WHERE link.idea_seed_id = ?
                  AND artifact.campaign_id IS NOT NULL""",
            (idea_seed_id, idea_seed_id),
        ).fetchall()
        return {
            str(row["campaign_id"]).strip()
            for row in rows
            if str(row["campaign_id"] or "").strip()
        }

    def _record_knowledge_link_in_connection(
        self,
        conn,
        payload: Dict[str, Any],
        *,
        actor: str,
        invalidate_plan: bool,
    ) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise ControlCenterError(
                "Knowledge-Link muss ein Objekt sein.",
                code="invalid_knowledge_link",
            )
        source_kind = str(payload.get("source_kind") or "").strip().lower()
        target_kind = str(payload.get("target_kind") or "").strip().lower()
        pair = (source_kind, target_kind)
        if pair not in KNOWLEDGE_RELATIONS:
            raise ControlCenterError(
                "Diese Knowledge-Link-Richtung ist nicht erlaubt.",
                code="invalid_knowledge_link_direction",
            )
        source_id = clean_text(
            payload.get("source_id"),
            "source_id",
            maximum=120,
        )
        target_id = clean_text(
            payload.get("target_id"),
            "target_id",
            maximum=120,
        )
        relation_type = clean_text(
            payload.get("relation_type"),
            "relation_type",
            maximum=80,
        ).lower()
        if relation_type not in KNOWLEDGE_RELATIONS[pair]:
            raise ControlCenterError(
                "Dieser semantische Relationstyp ist nicht erlaubt.",
                code="invalid_knowledge_relation_type",
            )
        if source_kind == target_kind and source_id == target_id:
            raise ControlCenterError(
                "Eine Knowledge-Entität kann nicht auf sich selbst zeigen.",
                code="knowledge_self_relation",
            )

        source = self._knowledge_entity(conn, source_kind, source_id)
        target = self._knowledge_entity(conn, target_kind, target_id)
        if int(source["project_id"]) != int(target["project_id"]):
            raise ControlCenterError(
                "Knowledge-Links dürfen keine Projektgrenzen überschreiten.",
                code="knowledge_project_mismatch",
                status=409,
            )
        source_campaign_id = str(source["campaign_id"] or "").strip()
        target_campaign_id = str(target["campaign_id"] or "").strip()
        if pair == ("idea_seed", "artifact"):
            bound_campaign_ids = self._idea_seed_campaign_ids_in_connection(
                conn,
                source_id,
            )
            if (
                bound_campaign_ids
                and target_campaign_id not in bound_campaign_ids
            ):
                raise ControlCenterError(
                    "Idea Seed und Artefakt müssen derselben Campaign gehören.",
                    code="knowledge_campaign_mismatch",
                    status=409,
                )
        if pair == ("artifact", "artifact") and (
            source_campaign_id != target_campaign_id
        ):
            raise ControlCenterError(
                "Artefakt-Links müssen innerhalb derselben Campaign bleiben.",
                code="knowledge_campaign_mismatch",
                status=409,
            )
        if pair == ("candidate", "artifact") and (
            source_campaign_id != target_campaign_id
        ):
            raise ControlCenterError(
                "PR-Slice und Artefakt müssen derselben Campaign gehören.",
                code="knowledge_campaign_mismatch",
                status=409,
            )

        if pair == ("idea_seed", "artifact"):
            table = "control_idea_seed_artifacts"
            source_column = "idea_seed_id"
            target_column = "artifact_id"
        elif pair == ("artifact", "artifact"):
            table = "control_artifact_relations"
            source_column = "source_artifact_id"
            target_column = "target_artifact_id"
        else:
            table = "control_candidate_artifacts"
            source_column = "candidate_id"
            target_column = "artifact_id"

        relation = self._knowledge_relation_shape(
            source_kind,
            source_id,
            target_kind,
            target_id,
            relation_type,
        )
        existing = conn.execute(
            f"""SELECT 1 FROM {table}
                WHERE {source_column} = ? AND {target_column} = ?
                  AND relation_type = ?""",
            (source_id, target_id, relation_type),
        ).fetchone()
        if existing:
            return {"relation": relation, "created": False}

        if pair == ("artifact", "artifact"):
            inverse = conn.execute(
                """SELECT 1 FROM control_artifact_relations
                   WHERE source_artifact_id = ? AND target_artifact_id = ?
                     AND relation_type = ?""",
                (target_id, source_id, relation_type),
            ).fetchone()
            if inverse:
                raise ControlCenterError(
                    "Die inverse Knowledge-Relation existiert bereits.",
                    code="inverse_knowledge_relation",
                    status=409,
                )

        campaign_id = target_campaign_id or source_campaign_id
        if campaign_id:
            campaign = self._campaign(conn, campaign_id)
            if str(campaign["status"]) != "draft":
                raise ControlCenterError(
                    "Ein genehmigter Plan benötigt ein Amendment.",
                    code="campaign_locked",
                    status=409,
                )

        conn.execute(
            f"""INSERT INTO {table} (
                    {source_column}, {target_column}, relation_type
                ) VALUES (?, ?, ?)""",
            (source_id, target_id, relation_type),
        )
        if invalidate_plan and campaign_id:
            self._invalidate_draft_plan_in_connection(conn, campaign_id)
        self._audit(
            conn,
            project_id=int(source["project_id"]),
            entity_type="knowledge_link",
            entity_id=f"{source_id}:{target_id}",
            action="knowledge_link.created",
            actor=actor,
            evidence=relation,
        )
        return {"relation": relation, "created": True}

    def link_knowledge(
        self,
        payload: Dict[str, Any],
        *,
        actor: str = "human",
    ) -> Dict[str, Any]:
        actor_name = clean_text(actor, "actor", maximum=120)
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            result = self._record_knowledge_link_in_connection(
                conn,
                payload,
                actor=actor_name,
                invalidate_plan=True,
            )
            conn.commit()
            return result

    @staticmethod
    def _safe_knowledge_reference(value: Any) -> str:
        text = str(value or "").strip()[:4000]
        if not text:
            return ""
        try:
            parsed = urlsplit(text)
        except ValueError:
            return ""
        if parsed.scheme not in {"http", "https"}:
            if parsed.scheme or parsed.netloc:
                return ""
            return urlunsplit(("", "", parsed.path, "", ""))
        if not parsed.netloc:
            return ""
        try:
            hostname = parsed.hostname or ""
        except ValueError:
            return ""
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        try:
            parsed_port = parsed.port
        except ValueError:
            return ""
        port = f":{parsed_port}" if parsed_port else ""
        return urlunsplit(
            (parsed.scheme.lower(), f"{hostname}{port}", parsed.path, "", "")
        )

    @staticmethod
    def _artifact_summary(row, *, include_scope: bool = False) -> Dict[str, Any]:
        result = {
            "id": str(row["id"]),
            "artifact_type": str(row["artifact_type"]),
            "title": str(row["title"]),
            "status": str(row["status"]),
            "version": int(row["version"]),
            "relative_path": str(row["relative_path"] or ""),
            "content_sha256": str(row["content_sha256"] or ""),
            "materialization_status": str(
                row["materialization_status"] or "unknown"
            ),
            "materialized_sha256": str(row["materialized_sha256"] or ""),
            "materialized_commit_sha": str(
                row["materialized_commit_sha"] or ""
            ),
            "materialized_at": row["materialized_at"],
        }
        if include_scope:
            result["project_id"] = int(row["project_id"])
            result["campaign_id"] = (
                str(row["campaign_id"])
                if row["campaign_id"] is not None
                else None
            )
        return result

    def get_knowledge_chains(self, project_id: Any = None) -> Dict[str, Any]:
        selected_project_id = None
        if project_id not in (None, ""):
            selected_project_id = int(self._project(project_id)["id"])

        def scope(column: str) -> tuple[str, tuple[Any, ...]]:
            if selected_project_id is None:
                return (
                    f" WHERE {column} IN "
                    "(SELECT id FROM projects WHERE archived_at IS NULL)",
                    (),
                )
            return f" WHERE {column} = ?", (selected_project_id,)

        with self.db._get_connection() as conn:
            clause, params = scope("id")
            project_rows = conn.execute(
                f"SELECT id, name FROM projects{clause} ORDER BY id",
                params,
            ).fetchall()
            clause, params = scope("project_id")
            seed_rows = conn.execute(
                f"""SELECT id, project_id, title, status, source, created_at
                    FROM control_idea_seeds{clause}
                    ORDER BY project_id, created_at, id""",
                params,
            ).fetchall()
            clause, params = scope("campaign.project_id")
            campaign_rows = conn.execute(
                f"""SELECT campaign.id, campaign.project_id, campaign.title,
                           campaign.status, campaign.version, campaign.base_sha,
                           COALESCE(profile.plan_signature, '') AS plan_signature,
                           (
                               SELECT job.idea_seed_id
                               FROM control_planning_jobs job
                               WHERE job.campaign_id = campaign.id
                               ORDER BY job.created_at DESC, job.id DESC
                               LIMIT 1
                           ) AS planning_idea_seed_id
                    FROM control_campaigns campaign
                    LEFT JOIN control_campaign_profiles profile
                      ON profile.campaign_id = campaign.id
                    {clause}
                    ORDER BY campaign.project_id, campaign.created_at, campaign.id""",
                params,
            ).fetchall()
            clause, params = scope("project_id")
            artifact_rows = conn.execute(
                f"""SELECT id, project_id, campaign_id, artifact_type, title,
                           status, version, relative_path, content_sha256,
                           materialization_status, materialized_sha256,
                           materialized_commit_sha, materialized_at
                    FROM control_artifacts{clause}
                    ORDER BY project_id, campaign_id, relative_path, id""",
                params,
            ).fetchall()
            clause, params = scope("artifact.project_id")
            seed_link_rows = conn.execute(
                f"""SELECT link.idea_seed_id, link.artifact_id,
                           link.relation_type
                    FROM control_idea_seed_artifacts link
                    JOIN control_artifacts artifact
                      ON artifact.id = link.artifact_id
                    {clause}
                    ORDER BY link.idea_seed_id, link.artifact_id,
                             link.relation_type""",
                params,
            ).fetchall()
            clause, params = scope("source.project_id")
            artifact_relation_rows = conn.execute(
                f"""SELECT relation.source_artifact_id,
                           relation.target_artifact_id,
                           relation.relation_type
                    FROM control_artifact_relations relation
                    JOIN control_artifacts source
                      ON source.id = relation.source_artifact_id
                    {clause}
                    ORDER BY relation.source_artifact_id,
                             relation.target_artifact_id,
                             relation.relation_type""",
                params,
            ).fetchall()
            clause, params = scope("campaign.project_id")
            candidate_rows = conn.execute(
                f"""SELECT candidate.id, candidate.campaign_id,
                           campaign.project_id, candidate.title,
                           candidate.status, candidate.priority,
                           candidate.base_sha
                    FROM control_pr_candidates candidate
                    JOIN control_campaigns campaign
                      ON campaign.id = candidate.campaign_id
                    {clause}
                    ORDER BY campaign.project_id, candidate.campaign_id,
                             candidate.priority, candidate.id""",
                params,
            ).fetchall()
            clause, params = scope("campaign.project_id")
            candidate_link_rows = conn.execute(
                f"""SELECT link.candidate_id, link.artifact_id,
                           link.relation_type
                    FROM control_candidate_artifacts link
                    JOIN control_pr_candidates candidate
                      ON candidate.id = link.candidate_id
                    JOIN control_campaigns campaign
                      ON campaign.id = candidate.campaign_id
                    {clause}
                    ORDER BY link.candidate_id, link.artifact_id,
                             link.relation_type""",
                params,
            ).fetchall()
            clause, params = scope("project_id")
            task_rows = conn.execute(
                f"""SELECT id, candidate_id, status, issue_number, issue_url,
                           pr_number, pr_url, current_sha, merged_sha, created_at
                    FROM control_agent_tasks{clause}
                    ORDER BY candidate_id, created_at DESC, id DESC""",
                params,
            ).fetchall()
            clause, params = scope("task.project_id")
            evidence_rows = conn.execute(
                f"""SELECT pack.id, pack.task_id, pack.status, pack.sha,
                           pack.summary
                    FROM control_evidence_packs pack
                    JOIN control_agent_tasks task ON task.id = pack.task_id
                    {clause}
                    ORDER BY pack.task_id, pack.created_at DESC, pack.id DESC""",
                params,
            ).fetchall()
            clause, params = scope("project_id")
            deployment_rows = conn.execute(
                f"""SELECT id, task_id, environment, status, sha,
                           artifact_ref, previous_stable_sha, rollback_of,
                           started_at, finished_at, created_at
                    FROM control_deployments{clause}
                    ORDER BY task_id, created_at DESC, id DESC""",
                params,
            ).fetchall()

        projects = {
            int(row["id"]): {"id": int(row["id"]), "name": str(row["name"])}
            for row in project_rows
        }
        seeds = {
            str(row["id"]): {
                "id": str(row["id"]),
                "project_id": int(row["project_id"]),
                "title": str(row["title"]),
                "status": str(row["status"]),
                "source": str(row["source"]),
                "created_at": row["created_at"],
            }
            for row in seed_rows
        }
        artifacts = {str(row["id"]): row for row in artifact_rows}
        artifacts_by_campaign: Dict[str, list[Any]] = {}
        for row in artifact_rows:
            campaign_id = str(row["campaign_id"] or "")
            if campaign_id:
                artifacts_by_campaign.setdefault(campaign_id, []).append(row)
        candidates_by_campaign: Dict[str, list[Any]] = {}
        for row in candidate_rows:
            candidates_by_campaign.setdefault(
                str(row["campaign_id"]),
                [],
            ).append(row)

        linked_seed_ids = {str(row["idea_seed_id"]) for row in seed_link_rows}
        linked_artifact_ids = {
            str(row["artifact_id"]) for row in seed_link_rows
        }
        linked_artifact_ids.update(
            str(row[column])
            for row in artifact_relation_rows
            for column in ("source_artifact_id", "target_artifact_id")
        )
        linked_artifact_ids.update(
            str(row["artifact_id"]) for row in candidate_link_rows
        )
        linked_candidate_ids = {
            str(row["candidate_id"]) for row in candidate_link_rows
        }

        seed_ids_by_campaign: Dict[str, list[str]] = {}
        for row in seed_link_rows:
            artifact = artifacts.get(str(row["artifact_id"]))
            if not artifact or not artifact["campaign_id"]:
                continue
            campaign_id = str(artifact["campaign_id"])
            seed_ids_by_campaign.setdefault(campaign_id, []).append(
                str(row["idea_seed_id"])
            )
        relations_by_campaign: Dict[str, list[Dict[str, str]]] = {}
        for row in artifact_relation_rows:
            source = artifacts.get(str(row["source_artifact_id"]))
            target = artifacts.get(str(row["target_artifact_id"]))
            if (
                not source
                or not target
                or source["campaign_id"] != target["campaign_id"]
                or source["campaign_id"] is None
            ):
                continue
            relations_by_campaign.setdefault(
                str(source["campaign_id"]),
                [],
            ).append(
                {
                    "source_artifact_id": str(row["source_artifact_id"]),
                    "target_artifact_id": str(row["target_artifact_id"]),
                    "relation_type": str(row["relation_type"]),
                }
            )
        artifact_ids_by_candidate: Dict[str, list[str]] = {}
        for row in candidate_link_rows:
            artifact_ids_by_candidate.setdefault(
                str(row["candidate_id"]),
                [],
            ).append(str(row["artifact_id"]))
        tasks_by_candidate: Dict[str, Dict[str, Any]] = {}
        task_ids_by_candidate: Dict[str, str] = {}
        for row in task_rows:
            candidate_id = str(row["candidate_id"])
            if candidate_id in tasks_by_candidate:
                continue
            task_ids_by_candidate[candidate_id] = str(row["id"])
            tasks_by_candidate[candidate_id] = {
                "id": str(row["id"]),
                "status": str(row["status"]),
                "issue_number": row["issue_number"],
                "issue_url": self._safe_knowledge_reference(row["issue_url"]),
                "pr_number": row["pr_number"],
                "pr_url": self._safe_knowledge_reference(row["pr_url"]),
                "current_sha": str(row["current_sha"] or ""),
                "merged_sha": str(row["merged_sha"] or ""),
            }
        evidence_by_task: Dict[str, Dict[str, Any]] = {}
        for row in evidence_rows:
            evidence_by_task.setdefault(
                str(row["task_id"]),
                {
                    "id": str(row["id"]),
                    "status": str(row["status"]),
                    "sha": str(row["sha"] or ""),
                    "summary": str(row["summary"] or ""),
                },
            )
        deployments_by_task: Dict[str, list[Dict[str, Any]]] = {}
        for row in deployment_rows:
            task_id = str(row["task_id"] or "")
            if not task_id:
                continue
            deployments_by_task.setdefault(task_id, []).append(
                {
                    "id": str(row["id"]),
                    "environment": str(row["environment"]),
                    "status": str(row["status"]),
                    "sha": str(row["sha"] or ""),
                    "artifact_ref": self._safe_knowledge_reference(
                        row["artifact_ref"]
                    ),
                    "previous_stable_sha": str(
                        row["previous_stable_sha"] or ""
                    ),
                    "rollback_of": (
                        str(row["rollback_of"])
                        if row["rollback_of"] is not None
                        else None
                    ),
                    "started_at": row["started_at"],
                    "finished_at": row["finished_at"],
                }
            )

        chains = []
        for campaign in campaign_rows:
            campaign_id = str(campaign["id"])
            campaign_artifacts = artifacts_by_campaign.get(campaign_id, [])
            campaign_candidates = candidates_by_campaign.get(campaign_id, [])
            seed_id = str(campaign["planning_idea_seed_id"] or "")
            if not seed_id:
                linked_seeds = sorted(set(seed_ids_by_campaign.get(campaign_id, [])))
                seed_id = linked_seeds[0] if linked_seeds else ""
            idea_seed = seeds.get(seed_id)
            if not idea_seed and not campaign_artifacts and not campaign_candidates:
                continue
            branches = []
            for candidate in campaign_candidates:
                candidate_id = str(candidate["id"])
                task_id = task_ids_by_candidate.get(candidate_id, "")
                branches.append(
                    {
                        "candidate": {
                            "id": candidate_id,
                            "title": str(candidate["title"]),
                            "status": str(candidate["status"]),
                            "priority": int(candidate["priority"]),
                            "base_sha": str(candidate["base_sha"] or ""),
                        },
                        "artifacts": [
                            self._artifact_summary(artifacts[artifact_id])
                            for artifact_id in artifact_ids_by_candidate.get(
                                candidate_id,
                                [],
                            )
                            if artifact_id in artifacts
                        ],
                        "task": tasks_by_candidate.get(candidate_id),
                        "evidence": evidence_by_task.get(task_id),
                        "deployments": deployments_by_task.get(task_id, []),
                    }
                )
            campaign_artifact_ids = {
                str(row["id"]) for row in campaign_artifacts
            }
            campaign_linked_artifact_ids = (
                campaign_artifact_ids & linked_artifact_ids
            )
            campaign_candidate_ids = {
                str(row["id"]) for row in campaign_candidates
            }
            campaign_linked_candidate_ids = (
                campaign_candidate_ids & linked_candidate_ids
            )
            chains.append(
                {
                    "project": projects[int(campaign["project_id"])],
                    "idea_seed": (
                        {
                            key: idea_seed[key]
                            for key in (
                                "id",
                                "title",
                                "status",
                                "source",
                                "created_at",
                            )
                        }
                        if idea_seed
                        else None
                    ),
                    "campaign": {
                        "id": campaign_id,
                        "title": str(campaign["title"]),
                        "status": str(campaign["status"]),
                        "version": int(campaign["version"]),
                        "base_sha": str(campaign["base_sha"] or ""),
                        "plan_signature": str(campaign["plan_signature"] or ""),
                    },
                    "idea_group": [
                        self._artifact_summary(row)
                        for row in campaign_artifacts
                        if str(row["artifact_type"]) == "idea_group"
                    ],
                    "artifacts": [
                        self._artifact_summary(row)
                        for row in campaign_artifacts
                    ],
                    "relations": relations_by_campaign.get(campaign_id, []),
                    "branches": branches,
                    "coverage": {
                        "idea_group_files": sum(
                            str(row["artifact_type"]) == "idea_group"
                            for row in campaign_artifacts
                        ),
                        "linked_artifacts": len(
                            campaign_linked_artifact_ids
                        ),
                        "unlinked_artifacts": len(campaign_artifact_ids)
                        - len(campaign_linked_artifact_ids),
                        "linked_candidates": len(
                            campaign_linked_candidate_ids
                        ),
                        "unlinked_candidates": len(campaign_candidate_ids)
                        - len(campaign_linked_candidate_ids),
                    },
                }
            )

        return {
            "chains": chains,
            "unlinked": {
                "idea_seeds": [
                    seed
                    for seed in seeds.values()
                    if seed["id"] not in linked_seed_ids
                ],
                "artifacts": [
                    self._artifact_summary(row, include_scope=True)
                    for row in artifact_rows
                    if str(row["id"]) not in linked_artifact_ids
                ],
                "candidates": [
                    {
                        "id": str(row["id"]),
                        "campaign_id": str(row["campaign_id"]),
                        "title": str(row["title"]),
                        "status": str(row["status"]),
                        "priority": int(row["priority"]),
                        "base_sha": str(row["base_sha"] or ""),
                    }
                    for row in candidate_rows
                    if str(row["id"]) not in linked_candidate_ids
                ],
            },
        }
