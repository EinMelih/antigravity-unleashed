"""SHA-bound findings, evidence packs, test packs, and human approvals."""

from __future__ import annotations

import json
from typing import Any, Dict

from src.control_center.common import (
    FINDING_CLASSES,
    SHA_PATTERN,
    ControlCenterError,
    clean_text,
    public_id,
)


EVIDENCE_STATUSES = {"pending", "passed", "failed", "skipped"}
APPROVAL_TYPES = {"protected_path", "human_test", "merge", "production"}
APPROVAL_DECISIONS = {"approved", "rejected"}
HUMAN_TEST_REPRODUCTION_FIELDS = {
    "executed_steps": 4000,
    "expected_behavior": 4000,
    "observed_behavior": 4000,
    "environment": 2000,
    "diagnosis": 4000,
    "artifact_ref": 2000,
    "note": 4000,
}
HUMAN_TEST_REPRODUCTION_REQUIRED = {
    "executed_steps",
    "expected_behavior",
    "observed_behavior",
    "environment",
}


class EvidenceMixin:
    @staticmethod
    def _evidence_pack_for_task(conn, task_id: str):
        row = conn.execute(
            "SELECT * FROM control_evidence_packs WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if not row:
            raise ControlCenterError(
                "Evidence Pack für Agent Task nicht gefunden.",
                code="evidence_pack_not_found",
                status=404,
            )
        return row

    def evidence_pack(self, task_id: str) -> Dict[str, Any]:
        task = self.get_task(task_id)
        with self.db._get_connection() as conn:
            pack = self._evidence_pack_for_task(conn, task_id)
            result = self._row(
                pack,
                ("risk_json", "test_pack_json"),
            )
            result["items"] = [
                self._row(row, ("payload_json",))
                for row in conn.execute(
                    """SELECT * FROM control_evidence_items
                       WHERE evidence_pack_id = ?
                       ORDER BY created_at ASC""",
                    (pack["id"],),
                ).fetchall()
            ]
            result["findings"] = [
                dict(row)
                for row in conn.execute(
                    """SELECT * FROM control_findings
                       WHERE task_id = ?
                       ORDER BY CASE classification
                           WHEN 'BLOCKER' THEN 0 WHEN 'REQUIRED' THEN 1
                           WHEN 'QUESTION' THEN 2 WHEN 'SUGGESTION' THEN 3
                           ELSE 4 END, created_at ASC""",
                    (task_id,),
                ).fetchall()
            ]
            result["approvals"] = [
                self._row(row, ("evidence_json",))
                for row in conn.execute(
                    """SELECT * FROM control_human_approvals
                       WHERE entity_type = 'agent_task' AND entity_id = ?
                       ORDER BY created_at DESC""",
                    (task_id,),
                ).fetchall()
            ]
        result["task"] = task
        return result

    def record_finding(
        self,
        task_id: str,
        payload: Dict[str, Any],
        *,
        actor: str = "reviewer",
    ) -> Dict[str, Any]:
        task = self.get_task(task_id)
        classification = str(payload.get("classification") or "").strip().upper()
        if classification not in FINDING_CLASSES:
            raise ControlCenterError(
                "Unbekannte Finding-Klasse.",
                code="invalid_finding_classification",
            )
        source = clean_text(payload.get("source"), "source", maximum=120)
        body = clean_text(payload.get("body"), "body", maximum=10000)
        external_id = str(payload.get("external_id") or "").strip()[:250]
        sha = str(payload.get("sha") or task.get("current_sha") or task["base_sha"]).lower()
        if not SHA_PATTERN.fullmatch(sha):
            raise ControlCenterError("Finding-SHA ist ungültig.", code="invalid_sha")
        with self.db._get_connection() as conn:
            existing = None
            if external_id:
                existing = conn.execute(
                    """SELECT * FROM control_findings
                       WHERE task_id = ? AND source = ? AND external_id = ?""",
                    (task_id, source, external_id),
                ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE control_findings
                       SET classification = ?, body = ?, status = 'open',
                           resolution = '', sha = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (classification, body, sha, existing["id"]),
                )
                finding_id = str(existing["id"])
                action = "finding.reopened"
            else:
                finding_id = public_id("FND")
                conn.execute(
                    """INSERT INTO control_findings (
                           id, task_id, classification, source, external_id, body, sha
                       ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        finding_id,
                        task_id,
                        classification,
                        source,
                        external_id,
                        body,
                        sha,
                    ),
                )
                action = "finding.created"
            if classification in {"BLOCKER", "REQUIRED"}:
                conn.execute(
                    """UPDATE control_evidence_packs
                       SET status = 'blocked', updated_at = CURRENT_TIMESTAMP
                       WHERE task_id = ?""",
                    (task_id,),
                )
            self._audit(
                conn,
                project_id=int(task["project_id"]),
                entity_type="agent_task",
                entity_id=task_id,
                action=action,
                actor=str(actor or "reviewer")[:120],
                evidence={
                    "finding_id": finding_id,
                    "classification": classification,
                    "source": source,
                    "sha": sha,
                },
            )
            conn.commit()
            return dict(
                conn.execute(
                    "SELECT * FROM control_findings WHERE id = ?",
                    (finding_id,),
                ).fetchone()
            )

    def resolve_finding(
        self,
        finding_id: str,
        *,
        resolution: str,
        actor: str = "agent",
    ) -> Dict[str, Any]:
        explanation = clean_text(
            resolution,
            "resolution",
            minimum=3,
            maximum=10000,
        )
        with self.db._get_connection() as conn:
            finding = conn.execute(
                """SELECT finding.*, task.project_id
                   FROM control_findings finding
                   JOIN control_agent_tasks task ON task.id = finding.task_id
                   WHERE finding.id = ?""",
                (finding_id,),
            ).fetchone()
            if not finding:
                raise ControlCenterError(
                    "Finding nicht gefunden.",
                    code="finding_not_found",
                    status=404,
                )
            conn.execute(
                """UPDATE control_findings
                   SET status = 'resolved', resolution = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (explanation, finding_id),
            )
            self._audit(
                conn,
                project_id=int(finding["project_id"]),
                entity_type="agent_task",
                entity_id=str(finding["task_id"]),
                action="finding.resolved",
                actor=str(actor or "agent")[:120],
                evidence={"finding_id": finding_id},
            )
            conn.commit()
            return dict(
                conn.execute(
                    "SELECT * FROM control_findings WHERE id = ?",
                    (finding_id,),
                ).fetchone()
            )

    def set_task_revision(
        self,
        task_id: str,
        *,
        sha: str,
        actor: str = "executor",
    ) -> Dict[str, Any]:
        normalized_sha = str(sha or "").strip().lower()
        if not SHA_PATTERN.fullmatch(normalized_sha):
            raise ControlCenterError("Task-SHA ist ungültig.", code="invalid_sha")
        task = self.get_task(task_id)
        previous_sha = str(task.get("current_sha") or "")
        with self.db._get_connection() as conn:
            conn.execute(
                """UPDATE control_agent_tasks
                   SET current_sha = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (normalized_sha, task_id),
            )
            conn.execute(
                """UPDATE control_evidence_packs
                   SET sha = ?, status = 'collecting',
                       updated_at = CURRENT_TIMESTAMP
                   WHERE task_id = ?""",
                (normalized_sha, task_id),
            )
            revoked = conn.execute(
                """UPDATE control_human_approvals
                   SET revoked_at = CURRENT_TIMESTAMP
                   WHERE entity_type = 'agent_task' AND entity_id = ?
                     AND revoked_at IS NULL AND sha <> ?""",
                (task_id, normalized_sha),
            ).rowcount
            self._audit(
                conn,
                project_id=int(task["project_id"]),
                entity_type="agent_task",
                entity_id=task_id,
                action="agent_task.revision_updated",
                actor=str(actor or "executor")[:120],
                from_state=previous_sha,
                to_state=normalized_sha,
                evidence={"approvals_revoked": revoked},
            )
            conn.commit()
        return self.get_task(task_id)

    def add_evidence(
        self,
        task_id: str,
        payload: Dict[str, Any],
        *,
        actor: str = "executor",
    ) -> Dict[str, Any]:
        task = self.get_task(task_id)
        sha = str(payload.get("sha") or task.get("current_sha") or "").strip().lower()
        if not SHA_PATTERN.fullmatch(sha):
            raise ControlCenterError(
                "Evidence benötigt den exakten Commit-SHA.",
                code="evidence_sha_required",
            )
        current_sha = str(task.get("current_sha") or "").lower()
        if current_sha and sha != current_sha:
            raise ControlCenterError(
                "Evidence gehört nicht zum aktuellen Task-SHA.",
                code="stale_evidence_sha",
                status=409,
            )
        status = str(payload.get("status") or "").strip().lower()
        if status not in EVIDENCE_STATUSES:
            raise ControlCenterError(
                "Unbekannter Evidence-Status.",
                code="invalid_evidence_status",
            )
        kind = clean_text(payload.get("kind"), "kind", maximum=80)
        title = clean_text(payload.get("title"), "title", maximum=500)
        criterion_key = str(payload.get("criterion_key") or "").strip()[:500]
        details = payload.get("payload") or {}
        if not isinstance(details, dict):
            raise ControlCenterError(
                "Evidence-Payload muss ein Objekt sein.",
                code="invalid_evidence_payload",
            )
        with self.db._get_connection() as conn:
            pack = self._evidence_pack_for_task(conn, task_id)
            existing = conn.execute(
                """SELECT * FROM control_evidence_items
                   WHERE evidence_pack_id = ? AND kind = ?
                     AND criterion_key = ? AND sha = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (pack["id"], kind, criterion_key, sha),
            ).fetchone()
            evidence_id = str(existing["id"]) if existing else public_id("EVI")
            command = str(payload.get("command") or "")[:4000]
            result = str(payload.get("result") or "")[:20000]
            artifact_ref = str(payload.get("artifact_ref") or "")[:2000]
            payload_json = json.dumps(
                details,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            values = (
                title,
                status,
                command,
                result,
                artifact_ref,
                payload_json,
            )
            existing_details = {}
            if existing:
                try:
                    existing_details = json.loads(existing["payload_json"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    existing_details = None
            changed = not existing or (
                str(existing["title"] or "") != title
                or str(existing["status"] or "") != status
                or str(existing["command"] or "") != command
                or str(existing["result"] or "") != result
                or str(existing["artifact_ref"] or "") != artifact_ref
                or existing_details != details
            )
            if existing and changed:
                conn.execute(
                    """UPDATE control_evidence_items
                       SET title = ?, status = ?, command = ?, result = ?,
                           artifact_ref = ?, payload_json = ?
                       WHERE id = ?""",
                    (*values, evidence_id),
                )
            elif not existing:
                conn.execute(
                    """INSERT INTO control_evidence_items (
                           id, evidence_pack_id, kind, criterion_key, title, status,
                           sha, command, result, artifact_ref, payload_json
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        evidence_id,
                        pack["id"],
                        kind,
                        criterion_key,
                        title,
                        status,
                        sha,
                        *values[2:],
                    ),
                )
            if changed:
                self._audit(
                    conn,
                    project_id=int(task["project_id"]),
                    entity_type="evidence_pack",
                    entity_id=str(pack["id"]),
                    action="evidence.recorded",
                    actor=str(actor or "executor")[:120],
                    evidence={
                        "evidence_id": evidence_id,
                        "kind": kind,
                        "status": status,
                        "sha": sha,
                        "criterion_key": criterion_key,
                        "updated": bool(existing),
                    },
                )
            conn.commit()
            return self._row(
                conn.execute(
                    "SELECT * FROM control_evidence_items WHERE id = ?",
                    (evidence_id,),
                ).fetchone(),
                ("payload_json",),
            )

    def evaluate_evidence_pack(
        self,
        task_id: str,
        *,
        actor: str = "orchestrator",
    ) -> Dict[str, Any]:
        task = self.get_task(task_id)
        current_sha = str(task.get("current_sha") or "").lower()
        with self.db._get_connection() as conn:
            pack = self._evidence_pack_for_task(conn, task_id)
            candidate = conn.execute(
                """SELECT pc.acceptance_criteria_json, contract.required_checks_json,
                          contract.manual_tests_json
                   FROM control_pr_candidates pc
                   JOIN control_candidate_contracts contract
                     ON contract.candidate_id = pc.id
                   WHERE pc.id = ?""",
                (task["candidate_id"],),
            ).fetchone()
            criteria = json.loads(candidate["acceptance_criteria_json"] or "[]")
            checks = json.loads(candidate["required_checks_json"] or "[]")
            manual_tests = json.loads(candidate["manual_tests_json"] or "[]")
            items = conn.execute(
                """SELECT * FROM control_evidence_items
                   WHERE evidence_pack_id = ? AND sha = ?""",
                (pack["id"], current_sha),
            ).fetchall()
            passed_keys = {
                str(item["criterion_key"])
                for item in items
                if item["status"] == "passed" and item["criterion_key"]
            }
            failed = [
                str(item["title"]) for item in items if item["status"] == "failed"
            ]
            missing_criteria = [
                f"acceptance:{index}"
                for index, _criterion in enumerate(criteria, start=1)
                if f"acceptance:{index}" not in passed_keys
            ]
            missing_checks = [
                f"check:{check}"
                for check in checks
                if f"check:{check}" not in passed_keys
            ]
            missing_manual = [
                f"manual:{index}"
                for index, _test in enumerate(manual_tests, start=1)
                if f"manual:{index}" not in passed_keys
            ]
            blocking_findings = [
                dict(row)
                for row in conn.execute(
                    """SELECT * FROM control_findings
                       WHERE task_id = ? AND status = 'open'
                         AND classification IN ('BLOCKER', 'REQUIRED')""",
                    (task_id,),
                ).fetchall()
            ]
            missing = []
            if not current_sha:
                missing.append("current_sha")
            if not str(pack["rollback_plan"] or "").strip():
                missing.append("rollback_plan")
            missing.extend(missing_criteria)
            missing.extend(missing_checks)
            missing.extend(missing_manual)
            if blocking_findings:
                missing.append("blocking_findings")
            if failed:
                missing.append("failed_evidence")
            ready = not missing
            test_pack = {
                "sha": current_sha,
                "acceptance_criteria": [
                    {"key": f"acceptance:{index}", "text": text}
                    for index, text in enumerate(criteria, start=1)
                ],
                "required_checks": [
                    {"key": f"check:{check}", "text": check} for check in checks
                ],
                "manual_tests": [
                    {"key": f"manual:{index}", "text": text}
                    for index, text in enumerate(manual_tests, start=1)
                ],
                "missing": missing,
                "failed": failed,
                "blocking_findings": [
                    finding["id"] for finding in blocking_findings
                ],
            }
            status = "ready_for_human" if ready else (
                "blocked" if blocking_findings or failed else "collecting"
            )
            summary = (
                "Alle automatischen und manuellen Nachweise liegen vor."
                if ready
                else f"{len(missing)} Nachweis-Gates sind offen."
            )
            try:
                previous_test_pack = json.loads(pack["test_pack_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                previous_test_pack = None
            pack_changed = (
                str(pack["sha"] or "").lower() != current_sha
                or str(pack["status"] or "") != status
                or str(pack["summary"] or "") != summary
                or previous_test_pack != test_pack
            )
            if pack_changed:
                conn.execute(
                    """UPDATE control_evidence_packs
                       SET sha = ?, status = ?, test_pack_json = ?,
                           summary = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (
                        current_sha,
                        status,
                        json.dumps(
                            test_pack,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        summary,
                        pack["id"],
                    ),
                )
            task_transitioned = (
                ready
                and task["status"]
                not in {"waiting_human", "completed", "cancelled", "failed"}
            )
            if task_transitioned:
                conn.execute(
                    """UPDATE control_agent_tasks
                       SET status = 'waiting_human', wake_reason = 'human_test',
                           updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (task_id,),
                )
            if pack_changed or task_transitioned:
                self._audit(
                    conn,
                    project_id=int(task["project_id"]),
                    entity_type="evidence_pack",
                    entity_id=str(pack["id"]),
                    action="evidence.evaluated",
                    actor=str(actor or "orchestrator")[:120],
                    to_state=status,
                    evidence={
                        "ready": ready,
                        "missing": missing,
                        "sha": current_sha,
                        "task_transitioned": task_transitioned,
                    },
                )
            conn.commit()
        return self.evidence_pack(task_id)

    @staticmethod
    def _human_test_reproduction(details: Dict[str, Any]) -> Dict[str, str]:
        missing = sorted(
            field
            for field in HUMAN_TEST_REPRODUCTION_REQUIRED
            if not isinstance(details.get(field), str)
            or not str(details.get(field) or "").strip()
        )
        if missing:
            raise ControlCenterError(
                "Für eine Human-Test-Ablehnung fehlen Reproduktionsangaben: "
                + ", ".join(missing),
                code="human_test_reproduction_required",
            )
        normalized: Dict[str, str] = {}
        for field, maximum in HUMAN_TEST_REPRODUCTION_FIELDS.items():
            value = details.get(field)
            text = str(value or "").strip()
            if len(text) > maximum:
                raise ControlCenterError(
                    f"{field} darf höchstens {maximum} Zeichen enthalten.",
                    code="invalid_human_test_reproduction",
                )
            if text or field in HUMAN_TEST_REPRODUCTION_REQUIRED:
                normalized[field] = text
        return normalized

    @staticmethod
    def _human_test_finding_body(details: Dict[str, str]) -> str:
        sections = [
            "Human test failed for the approved candidate revision.",
            f"Executed steps:\n{details['executed_steps']}",
            f"Expected behavior:\n{details['expected_behavior']}",
            f"Observed behavior:\n{details['observed_behavior']}",
            f"Environment:\n{details['environment']}",
        ]
        optional_labels = {
            "diagnosis": "Diagnosis",
            "artifact_ref": "Artifact",
            "note": "Additional note",
        }
        sections.extend(
            f"{optional_labels[field]}:\n{details[field]}"
            for field in optional_labels
            if details.get(field)
        )
        return "\n\n".join(sections)[:10000]

    def record_human_approval(
        self,
        task_id: str,
        *,
        approval_type: str,
        sha: str,
        decision: str,
        actor: str = "human",
        reason: str = "",
        evidence: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        task = self.get_task(task_id)
        selected_type = str(approval_type or "").strip().lower()
        selected_decision = str(decision or "").strip().lower()
        if selected_type not in APPROVAL_TYPES:
            raise ControlCenterError(
                "Unbekannter Freigabetyp.",
                code="invalid_approval_type",
            )
        if selected_decision not in APPROVAL_DECISIONS:
            raise ControlCenterError(
                "Entscheidung muss approved oder rejected sein.",
                code="invalid_approval_decision",
            )
        normalized_sha = str(sha or "").strip().lower()
        current_sha = str(task.get("current_sha") or "").lower()
        merged_sha = str(task.get("merged_sha") or "").lower()
        expected_sha = merged_sha if selected_type == "production" else current_sha
        if not expected_sha or normalized_sha != expected_sha:
            raise ControlCenterError(
                "Freigabe gilt nur für den exakten geprüften Ziel-SHA.",
                code="approval_sha_mismatch",
                status=409,
            )
        details = evidence or {}
        if not isinstance(details, dict):
            raise ControlCenterError(
                "Freigabe-Evidence muss ein Objekt sein.",
                code="invalid_approval_evidence",
            )
        if selected_type == "human_test" and selected_decision == "rejected":
            details = self._human_test_reproduction(details)
        actor_name = clean_text(actor, "actor", maximum=120)
        rejection_reason = str(reason or "")[:5000]
        with self.db._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            locked_task = conn.execute(
                "SELECT * FROM control_agent_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if not locked_task:
                raise ControlCenterError(
                    "Agent Task nicht gefunden.",
                    code="task_not_found",
                    status=404,
                )
            locked_current_sha = str(locked_task["current_sha"] or "").lower()
            locked_merged_sha = str(locked_task["merged_sha"] or "").lower()
            locked_expected_sha = (
                locked_merged_sha
                if selected_type == "production"
                else locked_current_sha
            )
            if not locked_expected_sha or normalized_sha != locked_expected_sha:
                raise ControlCenterError(
                    "Freigabe gilt nur für den exakten geprüften Ziel-SHA.",
                    code="approval_sha_mismatch",
                    status=409,
                )
            negative_human_test = (
                selected_type == "human_test"
                and selected_decision == "rejected"
            )
            if negative_human_test and str(locked_task["status"]) in {
                "completed",
                "cancelled",
                "failed",
            }:
                raise ControlCenterError(
                    "Ein terminaler Task kann durch eine verspätete Human-Test-Ablehnung nicht erneut gestartet werden.",
                    code="human_test_repair_not_allowed",
                    status=409,
                )
            pack = self._evidence_pack_for_task(conn, task_id)
            if (
                selected_type in {"human_test", "merge"}
                and pack["status"] not in {"ready_for_human", "approved"}
            ):
                raise ControlCenterError(
                    "Das Evidence Pack ist noch nicht bereit.",
                    code="evidence_pack_not_ready",
                    status=409,
                )
            if selected_type == "merge" and not self._active_approval(
                conn,
                task_id,
                "human_test",
                normalized_sha,
            ):
                raise ControlCenterError(
                    "Vor der Merge-Freigabe ist ein Human-Test erforderlich.",
                    code="human_test_required",
                    status=409,
                )
            if selected_type == "production":
                if locked_task["status"] != "completed" or not self._active_approval(
                    conn,
                    task_id,
                    "merge",
                    locked_current_sha,
                ):
                    raise ControlCenterError(
                        "Production-Freigabe ist erst nach freigegebenem Merge möglich.",
                        code="merged_revision_required",
                        status=409,
                    )
            if selected_type == "protected_path" and (
                locked_task["status"] != "paused"
                or locked_task["wake_reason"] != "protected_path_approval"
            ):
                raise ControlCenterError(
                    "Der Task wartet nicht auf eine Protected-Path-Freigabe.",
                    code="protected_path_approval_not_required",
                    status=409,
                )
            conn.execute(
                """UPDATE control_human_approvals
                   SET revoked_at = CURRENT_TIMESTAMP
                   WHERE entity_type = 'agent_task' AND entity_id = ?
                     AND approval_type = ? AND revoked_at IS NULL""",
                (task_id, selected_type),
            )
            if negative_human_test:
                conn.execute(
                    """UPDATE control_human_approvals
                       SET revoked_at = CURRENT_TIMESTAMP
                       WHERE entity_type = 'agent_task' AND entity_id = ?
                         AND approval_type = 'merge' AND revoked_at IS NULL""",
                    (task_id,),
                )
            approval_id = public_id("APR")
            conn.execute(
                """INSERT INTO control_human_approvals (
                       id, project_id, entity_type, entity_id, approval_type,
                       sha, decision, actor, reason, evidence_json
                   ) VALUES (?, ?, 'agent_task', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    approval_id,
                    int(locked_task["project_id"]),
                    task_id,
                    selected_type,
                    normalized_sha,
                    selected_decision,
                    actor_name,
                    rejection_reason,
                    json.dumps(
                        details,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ),
            )
            if selected_type == "human_test":
                pack_status = (
                    "approved" if selected_decision == "approved" else "rejected"
                )
                conn.execute(
                    """UPDATE control_evidence_packs
                       SET status = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (pack_status, pack["id"]),
                )
                if selected_decision == "approved":
                    self._resolve_attention(
                        conn,
                        "agent_task",
                        task_id,
                        "human_test_repair",
                    )
            rejection_evidence_id = ""
            rejection_finding_id = ""
            rejection_attention_id = ""
            if negative_human_test:
                criterion_key = "human_test:rejection"
                existing_evidence = conn.execute(
                    """SELECT * FROM control_evidence_items
                       WHERE evidence_pack_id = ? AND kind = 'human_test'
                         AND criterion_key = ? AND sha = ?
                       ORDER BY created_at DESC LIMIT 1""",
                    (pack["id"], criterion_key, normalized_sha),
                ).fetchone()
                rejection_evidence_id = (
                    str(existing_evidence["id"])
                    if existing_evidence
                    else public_id("EVI")
                )
                payload_json = json.dumps(
                    details,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if existing_evidence:
                    conn.execute(
                        """UPDATE control_evidence_items
                           SET title = ?, status = 'failed', command = ?,
                               result = ?, artifact_ref = ?, payload_json = ?
                           WHERE id = ?""",
                        (
                            "Human-Test-Reproduktionspaket",
                            details["executed_steps"],
                            details["observed_behavior"],
                            details.get("artifact_ref", ""),
                            payload_json,
                            rejection_evidence_id,
                        ),
                    )
                else:
                    conn.execute(
                        """INSERT INTO control_evidence_items (
                               id, evidence_pack_id, kind, criterion_key, title,
                               status, sha, command, result, artifact_ref,
                               payload_json
                           ) VALUES (?, ?, 'human_test', ?, ?, 'failed', ?, ?, ?, ?, ?)""",
                        (
                            rejection_evidence_id,
                            pack["id"],
                            criterion_key,
                            "Human-Test-Reproduktionspaket",
                            normalized_sha,
                            details["executed_steps"],
                            details["observed_behavior"],
                            details.get("artifact_ref", ""),
                            payload_json,
                        ),
                    )

                external_id = f"human-test:{task_id}:{normalized_sha}"[:250]
                finding_body = self._human_test_finding_body(details)
                existing_finding = conn.execute(
                    """SELECT * FROM control_findings
                       WHERE task_id = ? AND source = 'human_test'
                         AND external_id = ?""",
                    (task_id, external_id),
                ).fetchone()
                rejection_finding_id = (
                    str(existing_finding["id"])
                    if existing_finding
                    else public_id("FND")
                )
                if existing_finding:
                    conn.execute(
                        """UPDATE control_findings
                           SET classification = 'REQUIRED', body = ?,
                               status = 'open', resolution = '', sha = ?,
                               updated_at = CURRENT_TIMESTAMP
                           WHERE id = ?""",
                        (finding_body, normalized_sha, rejection_finding_id),
                    )
                else:
                    conn.execute(
                        """INSERT INTO control_findings (
                               id, task_id, classification, source,
                               external_id, body, sha
                           ) VALUES (?, ?, 'REQUIRED', 'human_test', ?, ?, ?)""",
                        (
                            rejection_finding_id,
                            task_id,
                            external_id,
                            finding_body,
                            normalized_sha,
                        ),
                    )

                updated = conn.execute(
                    """UPDATE control_agent_tasks
                       SET status = 'repair',
                           wake_reason = 'human_test_rejected',
                           last_error = ?, wake_at = NULL, finished_at = NULL,
                           lease_owner = '', lease_token = '', lease_until = NULL,
                           updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND current_sha = ?
                         AND status NOT IN ('completed', 'cancelled', 'failed')""",
                    (
                        "Human test rejected for the current SHA; bounded repair required.",
                        task_id,
                        normalized_sha,
                    ),
                )
                if updated.rowcount != 1:
                    raise ControlCenterError(
                        "Der Task wurde während der Human-Test-Ablehnung geändert.",
                        code="human_test_rejection_race",
                        status=409,
                    )
                conn.execute(
                    """UPDATE control_pr_candidates
                       SET status = 'repair', updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (locked_task["candidate_id"],),
                )
                rejection_attention_id = self._attention(
                    conn,
                    project_id=int(locked_task["project_id"]),
                    category="human_test_repair",
                    entity_type="agent_task",
                    entity_id=task_id,
                    title="Human-Test fehlgeschlagen",
                    consequence=details["observed_behavior"][:2000],
                    recommendation=(
                        "Reproduktionspaket und REQUIRED-Finding prüfen, den Fehler "
                        "in einem begrenzten Repair-Pass beheben und Evidence für "
                        "den neuen SHA erneut sammeln."
                    ),
                    urgency="high",
                )
                conn.execute(
                    """UPDATE control_attention_items
                       SET title = ?, consequence = ?, recommendation = ?,
                           urgency = 'high'
                       WHERE id = ?""",
                    (
                        "Human-Test fehlgeschlagen",
                        details["observed_behavior"][:2000],
                        (
                            "Reproduktionspaket und REQUIRED-Finding prüfen, den Fehler "
                            "in einem begrenzten Repair-Pass beheben und Evidence für "
                            "den neuen SHA erneut sammeln."
                        ),
                        rejection_attention_id,
                    ),
                )
                conn.execute(
                    """UPDATE control_evidence_packs
                       SET status = 'rejected',
                           summary = 'Human-Test abgelehnt; Reparatur erforderlich.',
                           updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (pack["id"],),
                )
            if (
                selected_type == "protected_path"
                and selected_decision == "approved"
            ):
                conn.execute(
                    """UPDATE control_agent_tasks
                       SET status = 'queued',
                           wake_reason = 'protected_path_approved',
                           last_error = '',
                           lease_owner = '', lease_token = '', lease_until = NULL,
                           updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (task_id,),
                )
                conn.execute(
                    """UPDATE control_pr_candidates
                       SET status = 'approved', updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (locked_task["candidate_id"],),
                )
                self._resolve_attention(
                    conn,
                    "agent_task",
                    task_id,
                    "protected_path",
                )
            if negative_human_test:
                self._audit(
                    conn,
                    project_id=int(locked_task["project_id"]),
                    entity_type="agent_task",
                    entity_id=task_id,
                    action="human_test.rejected_for_repair",
                    actor=actor_name,
                    from_state=str(locked_task["status"]),
                    to_state="repair",
                    reason=rejection_reason,
                    evidence={
                        "approval_id": approval_id,
                        "evidence_id": rejection_evidence_id,
                        "finding_id": rejection_finding_id,
                        "attention_id": rejection_attention_id,
                        "sha": normalized_sha,
                    },
                )
            else:
                self._audit(
                    conn,
                    project_id=int(locked_task["project_id"]),
                    entity_type="agent_task",
                    entity_id=task_id,
                    action=f"approval.{selected_type}.{selected_decision}",
                    actor=actor_name,
                    evidence={"approval_id": approval_id, "sha": normalized_sha},
                )
            conn.commit()
            return self._row(
                conn.execute(
                    "SELECT * FROM control_human_approvals WHERE id = ?",
                    (approval_id,),
                ).fetchone(),
                ("evidence_json",),
            )

    @staticmethod
    def _active_approval(
        conn,
        task_id: str,
        approval_type: str,
        sha: str,
    ) -> bool:
        row = conn.execute(
            """SELECT id FROM control_human_approvals
               WHERE entity_type = 'agent_task' AND entity_id = ?
                 AND approval_type = ? AND sha = ? AND decision = 'approved'
                 AND revoked_at IS NULL
               ORDER BY created_at DESC LIMIT 1""",
            (task_id, approval_type, sha),
        ).fetchone()
        return bool(row)
